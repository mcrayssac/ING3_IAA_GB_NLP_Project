"""Race cards in the 1.0 contract shape, built from the per-lap table only.

A card for lap L is a snapshot at the start of lap L: every value comes from laps
up to L - 1, the cutoff. Nothing is imputed; an unknown value stays unknown.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Any

import pandas as pd

SCHEMA_VERSION = "1.0"
WET_COMPOUNDS = {"INTERMEDIATE", "WET"}
PIT_LOSS_BOUNDS = (5.0, 60.0)  # data-cleaning bounds, not F1 truths
MIN_PIT_STOPS = 3
PACE_LAPS, MIN_PACE_LAPS = 5, 2
MIN_REFERENCE_LAPS = 5


class CardNotEligible(ValueError):
    """The situation is outside the card scope; the message is the reason."""


@dataclass(frozen=True)
class CutoffFacts:
    """Field-level values at one cutoff lap, shared by every driver's card."""

    lap: int
    order: list[str]
    order_complete: bool
    end_s: dict[str, float]
    status: str
    wet: bool
    pit_loss: float | None
    pit_loss_lap: int | None
    pit_loss_stops: int
    reference_lap: float | None
    reference_laps: int


def _clean(laps: pd.DataFrame) -> pd.Series:
    """Green racing laps: no pit entry or exit, not lap 1, timed."""
    return (
        ~laps["pit_in"]
        & ~laps["pit_out"]
        & (laps["lap"] > 1)
        & (laps["status"] == "GREEN")
        & laps["lap_seconds"].notna()
    )


def pit_loss(hist: pd.DataFrame) -> tuple[float | None, int | None, int]:
    """Median green pit loss: in-lap + out-lap - 2 x the driver's recent clean pace."""
    losses, latest = [], None
    for _, laps in hist.groupby("driver_number"):
        laps = laps.sort_values("lap").set_index("lap", drop=False)
        for in_lap in laps.index[laps["pit_in"]]:
            pair = laps.loc[laps.index.isin([in_lap, in_lap + 1])]
            if (
                len(pair) < 2
                or not pair["pit_out"].iloc[1]
                or (pair["status"] != "GREEN").any()
            ):
                continue
            pace = laps[(laps["lap"] < in_lap) & _clean(laps)].tail(PACE_LAPS)[
                "lap_seconds"
            ]
            if pair["lap_seconds"].isna().any() or len(pace) < MIN_PACE_LAPS:
                continue
            loss = pair["lap_seconds"].sum() - 2 * pace.median()
            if PIT_LOSS_BOUNDS[0] <= loss <= PIT_LOSS_BOUNDS[1]:
                losses.append(loss)
                latest = max(latest or 0, in_lap + 1)
    if len(losses) < MIN_PIT_STOPS:
        return None, None, len(losses)
    return round(float(median(losses)), 3), latest, len(losses)


def cutoff_facts(table: pd.DataFrame, cutoff: int) -> CutoffFacts:
    """Everything known at the end of lap `cutoff`, from laps up to the cutoff only."""
    hist = table[table["lap"] <= cutoff]
    at_cutoff = hist[(hist["lap"] == cutoff) & hist["end_s"].notna()]
    at_cutoff = at_cutoff.sort_values(["end_s", "driver_number"])
    timed_before = hist.loc[
        (hist["lap"] == cutoff - 1) & hist["end_s"].notna(), "driver_number"
    ]
    clean = hist[_clean(hist)]["lap_seconds"]
    loss, loss_lap, stops = pit_loss(hist)
    statuses = hist.loc[hist["lap"] == cutoff, "status"]
    return CutoffFacts(
        lap=cutoff,
        order=list(at_cutoff["driver_number"]),
        # a car timed on the previous lap but not on this one has an unknown place
        order_complete=set(timed_before) <= set(at_cutoff["driver_number"]),
        end_s=dict(zip(at_cutoff["driver_number"], at_cutoff["end_s"])),
        status=statuses.iloc[0] if len(statuses) else "UNKNOWN",
        wet=bool(hist["compound"].isin(WET_COMPOUNDS).any()),
        pit_loss=loss,
        pit_loss_lap=loss_lap,
        pit_loss_stops=stops,
        reference_lap=round(float(median(clean)), 3)
        if len(clean) >= MIN_REFERENCE_LAPS
        else None,
        reference_laps=len(clean),
    )


def _gap(facts: CutoffFacts, driver: str, offset: int, own_lap: float | None) -> dict:
    """Gap object to the neighbour `offset` places away in running order."""
    if not facts.order_complete:
        return {"state": "UNKNOWN", "seconds": None}
    index = facts.order.index(driver) + offset
    if not 0 <= index < len(facts.order):
        return {"state": "NONE", "seconds": None}
    other = facts.order[index]
    seconds = round(
        float(abs(facts.end_s[driver] - facts.end_s[other])), 3
    )  # plain float for decide
    if own_lap is None or pd.isna(own_lap) or seconds >= own_lap:  # a lap or more apart
        return {"state": "UNKNOWN", "seconds": None, "driver_number": other}
    return {"state": "KNOWN", "seconds": seconds, "driver_number": other}


def _driver_lap(table: pd.DataFrame, driver: str, lap: int) -> pd.Series:
    rows = table[(table["driver_number"] == driver) & (table["lap"] == lap)]
    if rows.empty or pd.isna(rows["end_s"].iloc[0]):
        raise CardNotEligible("no timing at the cutoff")
    return rows.iloc[0]


def build_card(
    table: pd.DataFrame,
    race: dict[str, Any],
    driver: str,
    lap: int,
    facts: CutoffFacts | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (card, provenance) for `driver` at the start of `lap`."""
    total_laps = int(table["lap"].max())
    if not 2 <= lap < total_laps:
        raise CardNotEligible("first or final lap")
    facts = facts or cutoff_facts(table, lap - 1)
    mine = _driver_lap(table, driver, lap - 1)
    if mine["pit_in"]:
        raise CardNotEligible("starts the lap in the pit lane")
    if facts.status == "RED":
        raise CardNotEligible("red flag at the cutoff")
    if facts.wet:
        raise CardNotEligible("wet running by the cutoff")
    age = mine["tyre_age_end"]
    card = {
        "schema_version": SCHEMA_VERSION,
        "race": {
            "season": race["season"],
            "round": race["round"],
            "event": race["event"],
            "completed": True,
        },
        "lap": lap,
        "total_laps": total_laps,
        "driver_number": driver,
        "as_of_completed_lap": lap - 1,
        "surface": "DRY",
        "track_status": facts.status,
        "compound": mine["compound"],
        "tyre_age_laps": None if pd.isna(age) else int(age),
        "gap_ahead": _gap(facts, driver, -1, mine["lap_seconds"]),
        "gap_behind": _gap(facts, driver, 1, mine["lap_seconds"]),
        "pit_loss_seconds": facts.pit_loss,
        "pit_loss_as_of_completed_lap": facts.pit_loss_lap,
        "reference_lap_seconds": facts.reference_lap,
    }
    provenance = {
        "source": "openf1",
        "session_key": race["session_key"],
        "cutoff_lap": lap - 1,
        "pit_loss_stops": facts.pit_loss_stops,
        "reference_laps": facts.reference_laps,
    }
    return card, provenance


def build_race_cards(
    table: pd.DataFrame, race: dict[str, Any]
) -> tuple[list[dict[str, Any]], Counter]:
    """Every eligible (driver, lap) card of a race, plus the count of skip reasons."""
    records, skipped = [], Counter()
    for lap in range(2, int(table["lap"].max())):
        facts = cutoff_facts(table, lap - 1)
        for driver in sorted(table["driver_number"].unique(), key=int):
            try:
                card, provenance = build_card(table, race, driver, lap, facts)
            except CardNotEligible as reason:
                skipped[str(reason)] += 1
                continue
            card_id = f"{race['race_id']}-{driver}-L{lap:02d}"
            records.append({"card_id": card_id, "card": card, "provenance": provenance})
    return records, skipped
