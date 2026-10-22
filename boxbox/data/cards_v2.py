"""Race cards in the 2.0 shape: track conditions, tyre wear, neighbours' tyres.

A 2.0 card keeps every 1.0 field and is read at `as_of`, the moment its driver
crosses the line at the end of lap L - 1. Field values that every card of the lap
shares are read at the leader's crossing, which comes first. Learned values (pit
loss and degradation priors) come only from train races that ended earlier.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .cards import (
    DECIMALS,
    WET_COMPOUNDS,
    CardNotEligible,
    CutoffFacts,
    _driver_lap,
    _gap,
    cutoff_facts,
)
from .pitloss import (
    CONDITIONS,
    penalty_awards,
    pending_penalty,
    race_estimate,
    stop_losses,
)
from .priors import condition_ratio, degradation_prior, earlier, pit_loss_prior
from .tyres import DRY, RELIABLE_SE, clean_dry_laps, degradation

SCHEMA_VERSION = "2.0"
MARGIN = 2.0  # the rejoin margin of the policy, in seconds
RAIN_WINDOW = pd.Timedelta(minutes=10)
WET_SHARE = 0.5  # half the field on wet tyres means a wet track, not one car's bet
CROSSOVER = 1.10  # slicks lose to intermediates above about 110% of dry pace
WEATHER = ("air_temperature", "track_temperature", "humidity", "wind_speed", "rainfall")


@dataclass(frozen=True)
class RaceContext:
    """What a race offers its cards beyond the per-lap table."""

    losses: pd.DataFrame
    awards: list
    stop_times: dict[str, list[pd.Timestamp]]
    weather: pd.DataFrame
    past: list[dict]
    reference: dict[int, float]
    ratios: dict[str, float | None]  # pit loss of each condition over green


def race_context(
    race: dict[str, Any],
    table: pd.DataFrame,
    messages: list[dict[str, Any]],
    weather: list[dict[str, Any]],
    priors: dict[str, dict[str, Any]],
    reference: dict[int, float],
) -> RaceContext:
    readings = pd.DataFrame(weather)
    readings["at"] = pd.to_datetime(readings["date"], utc=True, format="ISO8601")
    stops = table[table["pit_in"]]
    return RaceContext(
        losses=stop_losses(table, messages),
        awards=penalty_awards(messages),
        stop_times=stops.groupby("driver_number")["at_line"].apply(list).to_dict(),
        weather=readings.sort_values("at"),
        past=earlier(priors, race),
        reference=reference,
        ratios={k: condition_ratio(list(priors.values()), k) for k in CONDITIONS},
    )


@dataclass(frozen=True)
class LapFacts:
    """Cutoff facts plus the 2.0 values every card of the lap shares."""

    facts: CutoffFacts
    slopes: dict[str, dict[str, float]]
    wet_share: float
    inflation: float | None


def lap_facts(table: pd.DataFrame, cutoff: int) -> LapFacts:
    facts = cutoff_facts(table, cutoff)
    known = table.iloc[0:0]  # a lap with no timed car (holes in 2025-06) knows nothing
    if facts.known_at is not None:
        known = table[(table["lap"] <= cutoff) & (table["at_line"] <= facts.known_at)]
    dry = clean_dry_laps(known)
    last = table[(table["lap"] == cutoff) & table["end_s"].notna()]
    return LapFacts(
        facts=facts,
        slopes=degradation(dry),
        wet_share=float(last["compound"].isin(WET_COMPOUNDS).mean())
        if len(last)
        else 0.0,
        inflation=_inflation(known, dry, cutoff),
    )


def _inflation(known: pd.DataFrame, dry: pd.DataFrame, cutoff: int) -> float | None:
    """Median green lap at the cutoff over the best median dry lap so far."""
    lap = known[
        (known["lap"] == cutoff)
        & ~known["pit_in"]
        & ~known["pit_out"]
        & ~known["neutralised_in_lap"]
    ]["lap_seconds"].dropna()
    per_lap = dry.groupby("lap")["lap_seconds"].median()
    if len(lap) < 5 or per_lap.empty:
        return None
    return round(float(lap.median() / per_lap.min()), 3)


def surface(lap: LapFacts, weather: pd.DataFrame, at: pd.Timestamp) -> str:
    """WET with rain in the last 10 minutes or lap times above the slick crossover.

    The share of cars on wet tyres only decides when lap times say nothing, as early
    in a race that starts wet; otherwise it would keep the track wet until most cars
    are back on slicks, after the moment that pays.
    """
    recent = weather[(weather["at"] > at - RAIN_WINDOW) & (weather["at"] <= at)]
    if bool((recent["rainfall"] > 0).any()):
        return "WET"
    if lap.inflation is None:
        return "WET" if lap.wet_share >= WET_SHARE else "DRY"
    return "WET" if lap.inflation >= CROSSOVER else "DRY"


def weather_at(weather: pd.DataFrame, at: pd.Timestamp) -> dict[str, Any] | None:
    readings = weather[weather["at"] <= at]
    if readings.empty:
        return None
    last = readings.iloc[-1]
    return {
        name: None if pd.isna(last[name]) else float(last[name]) for name in WEATHER
    }


def _pit_condition(status: str, surface_now: str, compound: str | None) -> str:
    if status in ("SC", "VSC"):
        return status
    return "WET" if surface_now == "WET" or compound in WET_COMPOUNDS else "GREEN"


def pit_loss_now(
    context: RaceContext, race: dict[str, Any], kind: str, known_at: pd.Timestamp
) -> tuple[float | None, int | None, str | None]:
    """(seconds, as-of lap, source): the race's own stops, then a scaled green value,
    then the circuit, a published reference or the overall prior."""
    value, as_of, _ = race_estimate(context.losses, kind, known_at)
    if value is not None:
        return value, as_of, "race"
    green, as_of, _ = race_estimate(context.losses, "GREEN", known_at)
    ratio = context.ratios.get(kind)
    if kind != "GREEN" and green is not None and ratio is not None:
        return round(green * ratio, DECIMALS), as_of, "race scaled"
    prior, source = pit_loss_prior(context.past, race, ratio, context.reference)
    return prior, (0 if prior is not None else None), source


def slope_now(
    lap: LapFacts, context: RaceContext, race: dict[str, Any], compound: str | None
) -> tuple[float | None, str | None]:
    """Degradation of a compound: this race's laps once reliable, else the prior."""
    if compound not in DRY:
        return None, None
    fit = lap.slopes.get(compound)
    # a negative slope means fresh sets were still coming in, not tyres that improve
    if fit and fit["se"] < RELIABLE_SE and fit["b"] > 0:
        return round(fit["b"], 4), "race"
    return degradation_prior(context.past, race, compound)


def _tyre_loss(slope: float | None, age: Any) -> float | None:
    if slope is None or age is None or pd.isna(age):
        return None
    return round(max(slope, 0.0) * float(age), 2)


def _neighbour(
    table: pd.DataFrame, gap: dict, lap: LapFacts, context, race, cutoff: int
) -> dict:
    """The gap object with the neighbour's tyres at the cutoff, for a known gap."""
    if gap["state"] != "KNOWN":
        return gap
    row = _driver_lap(table, gap["driver_number"], cutoff)
    slope, _ = slope_now(lap, context, race, row["compound"])
    age = None if pd.isna(row["tyre_age_end"]) else int(row["tyre_age_end"])
    return {
        **gap,
        "compound": row["compound"],
        "tyre_age_laps": age,
        "in_pit_lane": bool(row["pit_in"]),
        "tyre_loss_s_per_lap": _tyre_loss(slope, age),
    }


def mandatory_stop_pending(table: pd.DataFrame, driver: str, cutoff: int) -> bool:
    """A dry race requires two dry compounds; wet tyres lift the rule."""
    used = table[(table["driver_number"] == driver) & (table["lap"] <= cutoff)]
    if used["compound"].isin(WET_COMPOUNDS).any():
        return False
    return used.loc[used["compound"].isin(DRY), "compound"].nunique() < 2


def cars_in_pit_window(
    facts: CutoffFacts, driver: str, loss: float | None, own_lap: float | None
) -> int | None:
    """Cars behind on the same lap within the pit loss plus the margin."""
    if loss is None or not facts.order_complete or own_lap is None or pd.isna(own_lap):
        return None
    mine = facts.end_s[driver]
    behind = [
        facts.end_s[d] - mine for d in facts.order[facts.order.index(driver) + 1 :]
    ]
    return sum(gap <= loss + MARGIN for gap in behind if gap < own_lap)


def build_card_v2(
    table: pd.DataFrame,
    race: dict[str, Any],
    driver: str,
    lap_number: int,
    lap: LapFacts,
    context: RaceContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (card, provenance) in the 2.0 shape for `driver` at `lap_number`."""
    total_laps = int(table["lap"].max())
    if not 2 <= lap_number < total_laps:
        raise CardNotEligible("first or final lap")
    cutoff, facts = lap_number - 1, lap.facts
    mine = _driver_lap(table, driver, cutoff)
    if mine["pit_in"]:
        raise CardNotEligible("starts the lap in the pit lane")
    if mine["status"] == "RED":
        raise CardNotEligible("red flag at the cutoff")
    at = mine["at_line"]
    wet = surface(lap, context.weather, at)
    kind = _pit_condition(mine["status"], wet, mine["compound"])
    loss, loss_lap, loss_source = pit_loss_now(context, race, kind, facts.known_at)
    slope, slope_source = slope_now(lap, context, race, mine["compound"])
    age = None if pd.isna(mine["tyre_age_end"]) else int(mine["tyre_age_end"])
    gaps = {
        name: _neighbour(
            table,
            _gap(facts, driver, step, mine["lap_seconds"]),
            lap,
            context,
            race,
            cutoff,
        )
        for name, step in (("gap_ahead", -1), ("gap_behind", 1))
    }
    card = {
        "schema_version": SCHEMA_VERSION,
        "race": {
            "season": race["season"],
            "round": race["round"],
            "event": race["event"],
            "completed": True,
            "circuit_key": race["circuit_key"],
        },
        "lap": lap_number,
        "total_laps": total_laps,
        "driver_number": driver,
        "as_of_completed_lap": cutoff,
        "as_of": at.isoformat(),
        "surface": wet,
        "track_status": mine["status"],
        "compound": mine["compound"],
        "tyre_age_laps": age,
        "tyre_degradation_s_per_lap": slope,
        "tyre_degradation_source": slope_source,
        "tyre_loss_s_per_lap": _tyre_loss(slope, age),
        **gaps,
        "cars_in_pit_window": cars_in_pit_window(
            facts, driver, loss, mine["lap_seconds"]
        ),
        "mandatory_stop_pending": mandatory_stop_pending(table, driver, cutoff),
        "pit_loss_seconds": loss,
        "pit_loss_as_of_completed_lap": loss_lap,
        "pit_loss_condition": kind,
        "pit_loss_source": loss_source,
        "penalty_pending_seconds": pending_penalty(
            context.awards, context.stop_times.get(driver, []), driver, at
        ),
        "weather": weather_at(context.weather, at),
        "reference_lap_seconds": facts.reference_lap,
    }
    provenance = {
        "source": "openf1",
        "session_key": race["session_key"],
        "cutoff_lap": cutoff,
        "pit_loss_stops": facts.pit_loss_stops,
        "reference_laps": facts.reference_laps,
    }
    return card, provenance


def build_race_cards_v2(
    table: pd.DataFrame, race: dict[str, Any], context: RaceContext
) -> tuple[list[dict[str, Any]], Counter]:
    """Every eligible 2.0 card of a race, plus the count of skip reasons."""
    records, skipped = [], Counter()
    for lap_number in range(2, int(table["lap"].max())):
        lap = lap_facts(table, lap_number - 1)
        for driver in sorted(table["driver_number"].unique(), key=int):
            try:
                card, provenance = build_card_v2(
                    table, race, driver, lap_number, lap, context
                )
            except CardNotEligible as reason:
                skipped[str(reason)] += 1
                continue
            card_id = f"{race['race_id']}-{driver}-L{lap_number:02d}"
            records.append({"card_id": card_id, "card": card, "provenance": provenance})
    return records, skipped
