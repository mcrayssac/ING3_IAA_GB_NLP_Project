"""Historical race-card extraction and race-level splits (roadmap task M2.1).

Everything that turns FastF1 timing data into BoxBox race cards lives here.

Design rules (see docs/data-protocol.md):

* Causality: a card for lap L is built only from laps whose LapNumber <= L.
  ``build_card`` truncates the laps table before computing anything, so no
  value can depend on a later lap. Pit loss uses only stops completed by L.
* No invention: a value that cannot be computed is ``None`` and the reason is
  written in ``card["missing"]``. Deciding whether a missing field blocks a
  call belongs to the decision policy (M1.1), not to this module.
* Splits are made by whole race, frozen in data/splits.json, before any
  dialogue is generated (M2.2).

The card field names below are a proposal until the M1.1 contract is
integrated; align ``CARD_FIELDS`` with docs/race-card-policy.md then.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

CARD_SCHEMA_VERSION = "0.1-draft"

# Fields every card carries (value may be None, see card["missing"]).
CARD_FIELDS = (
    "card_id",
    "race_id",
    "season",
    "round",
    "event",
    "lap",
    "total_laps",
    "laps_remaining",
    "driver",
    "team",
    "position",
    "compound",
    "tyre_age_laps",
    "compounds_used",
    "car_ahead",
    "gap_ahead_s",
    "car_behind",
    "gap_behind_s",
    "track_status",
    "pit_loss_s",
)

DRY_COMPOUNDS = {"SOFT", "MEDIUM", "HARD"}
WET_COMPOUNDS = {"INTERMEDIATE", "WET"}
SPLIT_NAMES = ("train", "validation", "mini_test", "final")


@dataclass(frozen=True)
class CardParams:
    """Reconstruction parameters. Stored in every manifest."""

    min_pit_stops: int = 3          # stops needed before a pit-loss estimate
    ref_laps: int = 5               # clean green laps used as reference pace
    min_ref_laps: int = 2
    pit_loss_bounds_s: tuple[float, float] = (5.0, 60.0)  # data-cleaning bounds only
    skip_first_lap: bool = True
    skip_last_lap: bool = True
    gap_decimals: int = 3

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pit_loss_bounds_s"] = list(self.pit_loss_bounds_s)
        return d


class DataUnavailableError(RuntimeError):
    """Raised when FastF1 data cannot be fetched or loaded (network, cache...)."""


class CardNotEligible(ValueError):
    """Raised when (race, driver, lap) is outside the card scope."""


# --------------------------------------------------------------------------
# Splits
# --------------------------------------------------------------------------

def make_splits(
    race_ids: list[str],
    seed: int,
    fractions: dict[str, float],
    min_eval_races: int = 5,
) -> dict[str, list[str]]:
    """Assign whole races to the four splits, deterministically.

    ``race_ids`` order does not matter: they are sorted before shuffling.
    """
    if set(fractions) != set(SPLIT_NAMES):
        raise ValueError(f"fractions must define exactly {SPLIT_NAMES}")
    if not math.isclose(sum(fractions.values()), 1.0, abs_tol=1e-9):
        raise ValueError("fractions must sum to 1")
    ids = sorted(set(race_ids))
    if len(ids) != len(race_ids):
        raise ValueError("duplicate race ids")

    eval_names = [n for n in SPLIT_NAMES if n != "train"]
    counts = {n: max(min_eval_races, round(fractions[n] * len(ids))) for n in eval_names}
    counts["train"] = len(ids) - sum(counts.values())
    if counts["train"] < 1:
        raise ValueError(
            f"not enough races ({len(ids)}) for {min_eval_races} races per evaluation split"
        )

    rng = random.Random(seed)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    out: dict[str, list[str]] = {}
    start = 0
    for name in SPLIT_NAMES:
        out[name] = sorted(shuffled[start : start + counts[name]])
        start += counts[name]
    check_disjoint(out)
    return out


def check_disjoint(splits: dict[str, list[str]]) -> None:
    seen: dict[str, str] = {}
    for name, races in splits.items():
        for r in races:
            if r in seen:
                raise ValueError(f"race {r} is in both {seen[r]} and {name}")
            seen[r] = name


def split_of(splits: dict[str, list[str]], race_id: str) -> str:
    for name, races in splits.items():
        if race_id in races:
            return name
    raise KeyError(f"race {race_id} is not in any split")


def race_id(season: int, round_number: int) -> str:
    return f"{season}-{round_number:02d}"


def parse_race_id(rid: str) -> tuple[int, int]:
    season, rnd = rid.split("-")
    return int(season), int(rnd)


# --------------------------------------------------------------------------
# FastF1 access (the only part that needs the network or the cache)
# --------------------------------------------------------------------------

def list_races(season: int) -> list[dict[str, Any]]:
    """Championship races of a season from the FastF1 schedule (no testing)."""
    import fastf1

    try:
        schedule = fastf1.get_event_schedule(season, include_testing=False)
    except Exception as exc:  # network / backend failure
        raise DataUnavailableError(f"schedule {season}: {exc}") from exc
    races = []
    for _, ev in schedule.iterrows():
        rnd = int(ev["RoundNumber"])
        if rnd <= 0:
            continue
        races.append({"race_id": race_id(season, rnd), "event": str(ev["EventName"])})
    return races


def load_race(season: int, round_number: int, cache_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the race session laps. Raises DataUnavailableError on any failure."""
    import fastf1

    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    try:
        session = fastf1.get_session(season, round_number, "R")
        session.load(laps=True, telemetry=False, weather=False, messages=False)
        laps = pd.DataFrame(session.laps)
    except Exception as exc:
        raise DataUnavailableError(f"race {race_id(season, round_number)}: {exc}") from exc
    if laps.empty:
        raise DataUnavailableError(f"race {race_id(season, round_number)}: no lap data")
    total = getattr(session, "total_laps", None)
    meta = {
        "season": season,
        "round": round_number,
        "event": str(session.event["EventName"]),
        "total_laps": int(total) if total is not None and not pd.isna(total) else None,
        "fastf1_version": fastf1.__version__,
    }
    return laps, meta


# --------------------------------------------------------------------------
# Card construction (pure functions on a laps table: testable offline)
# --------------------------------------------------------------------------

def _s(td: Any) -> float | None:
    """Timedelta -> seconds, None if missing."""
    if td is None or pd.isna(td):
        return None
    return td.total_seconds()


def track_status_label(code: Any) -> str | None:
    """Map a FastF1 lap TrackStatus string to the most severe status on the lap.

    FastF1 codes: 1 green, 2 yellow, 4 safety car, 5 red flag,
    6 VSC deployed, 7 VSC ending.
    """
    if code is None or (isinstance(code, float) and math.isnan(code)) or str(code) in ("", "nan"):
        return None
    code = str(code)
    if "5" in code:
        return "RED"
    if "4" in code:
        return "SC"
    if "6" in code or "7" in code:
        return "VSC"
    if "2" in code:
        return "YELLOW"
    if "1" in code:
        return "GREEN"
    return None


def _clean(text: Any) -> str | None:
    if text is None or pd.isna(text) or str(text).strip() in ("", "nan", "None", "UNKNOWN", "TEST_UNKNOWN"):
        return None
    return str(text).strip().upper()


def estimate_pit_loss(hist: pd.DataFrame, params: CardParams) -> tuple[float | None, dict[str, Any]]:
    """Median green-flag pit loss from stops completed in ``hist``.

    loss = in-lap time + out-lap time - 2 x reference pace, where the reference
    pace is the median of the driver's last clean green laps before the stop.
    Stops whose in-lap or out-lap was not fully green are ignored.
    ``hist`` must already be truncated to laps <= the evaluated lap.
    """
    losses: list[float] = []
    lo, hi = params.pit_loss_bounds_s
    for drv, dl in hist.groupby("Driver", sort=True):
        dl = dl.sort_values("LapNumber").set_index("LapNumber")
        for in_lap in dl.index[dl["PitInTime"].notna()]:
            out_lap = in_lap + 1
            if out_lap not in dl.index or pd.isna(dl.at[out_lap, "PitOutTime"]):
                continue
            pair = dl.loc[[in_lap, out_lap]]
            if any(track_status_label(s) != "GREEN" for s in pair["TrackStatus"]):
                continue
            t_in, t_out = _s(dl.at[in_lap, "LapTime"]), _s(dl.at[out_lap, "LapTime"])
            if t_in is None or t_out is None:
                continue
            before = dl[(dl.index < in_lap) & (dl.index > 1)]
            clean = before[
                before["PitInTime"].isna()
                & before["PitOutTime"].isna()
                & before["LapTime"].notna()
                & (before["TrackStatus"].map(track_status_label) == "GREEN")
            ].tail(params.ref_laps)
            if len(clean) < params.min_ref_laps:
                continue
            ref = clean["LapTime"].map(_s).median()
            loss = t_in + t_out - 2 * ref
            if lo <= loss <= hi:
                losses.append(loss)
    info = {"stops_used": len(losses), "min_stops": params.min_pit_stops}
    if len(losses) < params.min_pit_stops:
        return None, info
    return round(float(pd.Series(losses).median()), params.gap_decimals), info


def build_card(
    laps: pd.DataFrame,
    meta: dict[str, Any],
    driver: str,
    lap: int,
    params: CardParams = CardParams(),
) -> dict[str, Any]:
    """Build the race card of ``driver`` at the end of ``lap``.

    Raises CardNotEligible if the situation is outside the BoxBox scope
    (first/last lap, in-lap/out-lap, red flag, wet tyres, no timing).
    """
    lap = int(lap)
    # Causality guard: nothing after the evaluated lap is ever visible below.
    hist = laps[laps["LapNumber"] <= lap].copy()
    total = meta.get("total_laps")

    if params.skip_first_lap and lap <= 1:
        raise CardNotEligible("first lap")
    if params.skip_last_lap and total is not None and lap >= total:
        raise CardNotEligible("last lap")

    row = hist[(hist["Driver"] == driver) & (hist["LapNumber"] == lap)]
    if row.empty:
        raise CardNotEligible("driver did not complete this lap")
    row = row.iloc[0]
    if pd.isna(row["Time"]):
        raise CardNotEligible("no timing at end of lap")
    if pd.notna(row["PitInTime"]) or pd.notna(row["PitOutTime"]):
        raise CardNotEligible("in-lap or out-lap")

    status = track_status_label(row["TrackStatus"])
    if status == "RED":
        raise CardNotEligible("red flag")
    compound = _clean(row["Compound"])
    drv_hist = hist[hist["Driver"] == driver]
    used = sorted({c for c in drv_hist["Compound"].map(_clean) if c})
    if compound in WET_COMPOUNDS or any(c in WET_COMPOUNDS for c in used):
        raise CardNotEligible("wet tyres used (dry track only)")

    missing: dict[str, str] = {}

    # Order at the end of the lap = order of crossing the line on this lap.
    on_lap = hist[(hist["LapNumber"] == lap) & hist["Time"].notna()].sort_values(["Time", "Driver"])
    order = list(on_lap["Driver"])
    times = dict(zip(on_lap["Driver"], on_lap["Time"]))
    idx = order.index(driver)
    position = idx + 1

    car_ahead = order[idx - 1] if idx > 0 else None
    car_behind = order[idx + 1] if idx + 1 < len(order) else None
    gap_ahead = gap_behind = None
    if car_ahead is None:
        missing["gap_ahead_s"] = "no car ahead (race leader)"
    else:
        gap_ahead = round(_s(times[driver] - times[car_ahead]), params.gap_decimals)
    if car_behind is None:
        missing["gap_behind_s"] = "no car behind on this lap (last classified runner)"
    else:
        gap_behind = round(_s(times[car_behind] - times[driver]), params.gap_decimals)

    if compound is None:
        missing["compound"] = "compound not available in timing data"
    elif compound not in DRY_COMPOUNDS:
        missing["compound"] = f"unrecognised compound {compound!r}"
        compound = None

    tyre_age = None if pd.isna(row["TyreLife"]) else int(row["TyreLife"])
    if tyre_age is None:
        missing["tyre_age_laps"] = "tyre life not available in timing data"

    if status is None:
        missing["track_status"] = "track status not available"

    pit_loss, pit_info = estimate_pit_loss(hist, params)
    if pit_loss is None:
        missing["pit_loss_s"] = (
            f"only {pit_info['stops_used']} usable green-flag stop(s) before this lap "
            f"(need {params.min_pit_stops})"
        )

    if total is None:
        missing["total_laps"] = "scheduled race distance not available"

    team = str(row["Team"]).strip() if "Team" in row and _clean(row["Team"]) else None
    rid = race_id(meta["season"], meta["round"])
    card = {
        "card_id": f"{rid}-{driver}-L{lap:02d}",
        "race_id": rid,
        "season": meta["season"],
        "round": meta["round"],
        "event": meta["event"],
        "lap": lap,
        "total_laps": total,
        "laps_remaining": (total - lap) if total is not None else None,
        "driver": driver,
        "team": team,
        "position": position,
        "compound": compound,
        "tyre_age_laps": tyre_age,
        "compounds_used": used,
        "car_ahead": car_ahead,
        "gap_ahead_s": gap_ahead,
        "car_behind": car_behind,
        "gap_behind_s": gap_behind,
        "track_status": status,
        "pit_loss_s": pit_loss,
        "missing": missing,
        "provenance": {
            "source": "FastF1",
            "session": "R",
            "laps_used": [1, lap],
            "pit_stops_used": pit_info["stops_used"],
            "schema_version": CARD_SCHEMA_VERSION,
            "fastf1_version": meta.get("fastf1_version"),
        },
    }
    assert set(CARD_FIELDS) <= set(card)
    return card


def build_race_cards(
    laps: pd.DataFrame, meta: dict[str, Any], params: CardParams = CardParams()
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """All eligible cards of a race, in deterministic order, plus skip reasons."""
    cards: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    pairs = laps[["Driver", "LapNumber"]].dropna().drop_duplicates()
    for drv, lp in sorted((str(d), int(n)) for d, n in pairs.itertuples(index=False)):
        try:
            cards.append(build_card(laps, meta, drv, lp, params))
        except CardNotEligible as exc:
            skipped[str(exc)] = skipped.get(str(exc), 0) + 1
    return cards, skipped


# --------------------------------------------------------------------------
# Serialisation and fingerprints
# --------------------------------------------------------------------------

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def card_fingerprint(card: dict[str, Any]) -> str:
    return sha256_text(canonical_json(card))
