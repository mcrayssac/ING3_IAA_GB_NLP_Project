"""Agreement with the teams: does a policy say BOX when cars really stopped?

Usage, from the repository root:
    python -m scripts.reality_check [--splits validation mini_test final]

Recall is the share of real stops whose card, at the start of the stop lap, says
BOX. Precision is the share of BOX cards followed by a stop of that car within two
laps. Teams are not ground truth: they use more than a card holds, and a card taken
at the start of a lap cannot see a safety car that comes out during it. Stops that no pit-wall policy chooses are left out: red-flag tyre changes,
retirements, damage (a stint of under 3 laps) and penalty stops.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import quantiles
from typing import Any

import pandas as pd

from boxbox.data import build_race_cards, race_table
from boxbox.data.openf1 import race_control
from boxbox.data.pitloss import condition, penalty_awards, pending_penalty
from boxbox.data.splits import SPLITS_V2_FILE, load_splits
from boxbox.rules import TYRE_LIMITS, decide

CARDS_V2_DIR = Path("data/cards-v2")
LEAD = 2  # a BOX counts as followed when the car stops within 2 laps
TYRE_RULE_RACES = {"2023-17"}  # Qatar 2023 limited every set to 18 laps
MIN_STINT = 3  # a shorter stint before a stop means damage, not strategy
DRAWS = 1000


def real_stops(table: pd.DataFrame, messages: list[dict[str, Any]]) -> list[dict]:
    """Strategy stops: (driver, in-lap, previous in-lap, condition)."""
    rows = table.set_index(["driver_number", "lap"])
    awards = penalty_awards(messages)
    last_lap = int(table["lap"].max())
    stops, previous = [], {}
    for _, stop in (
        table[table["pit_in"]].sort_values(["driver_number", "lap"]).iterrows()
    ):
        driver, lap = stop["driver_number"], int(stop["lap"])
        start = previous.get(driver, 0)
        previous[driver] = lap
        out = (driver, lap + 1)
        if out not in rows.index or not rows.loc[out, "pit_out"] or lap >= last_lap - 1:
            continue  # a retirement, or the last laps
        times = table.loc[
            table["pit_in"] & (table["driver_number"] == driver), "at_line"
        ]
        if lap - start < MIN_STINT or pending_penalty(
            awards, list(times), driver, stop["at_line"]
        ):
            continue
        kind = condition(stop, rows.loc[out])
        if kind is not None:
            stops.append(
                {"driver": driver, "lap": lap, "since": start, "condition": kind}
            )
    return stops


def baselines(cards: list[dict]) -> dict[str, dict]:
    """Age only (BOX from the 1.1 'always' age) and BOX under every SC or VSC."""
    age, neutral = {}, {}
    for record in cards:
        card = record["card"]
        key = (card["driver_number"], card["lap"])
        old = TYRE_LIMITS.get(card["compound"], (None, None))[1]
        aged = old is not None and (card.get("tyre_age_laps") or 0) >= old
        age[key] = "BOX" if aged else "STAY OUT"
        neutral[key] = "BOX" if card["track_status"] in ("SC", "VSC") else "STAY OUT"
    return {"age only": age, "box under SC/VSC": neutral}


def race_cases(race: dict[str, Any]) -> dict[str, Any]:
    """Each policy's call on every card of a race, and the race's strategy stops."""
    table = race_table(race)
    v1 = {
        (r["card"]["driver_number"], r["card"]["lap"]): decide(r["card"])[0]
        for r in build_race_cards(table, race)[0]
    }
    path = CARDS_V2_DIR / f"{race['race_id']}.jsonl"
    cards = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    v2 = {
        (r["card"]["driver_number"], r["card"]["lap"]): decide(r["card"])[0]
        for r in cards
    }
    return {
        "race_id": race["race_id"],
        "calls": {"policy 1.1": v1, "policy 2.0": v2, **baselines(cards)},
        "stops": real_stops(table, race_control(race)),
        "cards": {
            (r["card"]["driver_number"], r["card"]["lap"]): r["card"] for r in cards
        },
    }


def counts(race: dict[str, Any], name: str, kind: str | None) -> dict[str, int]:
    """Stops called BOX on their lap, and BOX cards followed by a stop within 2 laps."""
    calls = race["calls"][name]
    stops = [s for s in race["stops"] if kind is None or s["condition"] == kind]
    stopped = {(s["driver"], s["lap"]) for s in race["stops"]}
    seen = [s for s in stops if (s["driver"], s["lap"]) in calls]
    boxes = [key for key, call in calls.items() if call == "BOX"]
    soon = [
        (d, lap)
        for d, lap in boxes
        if any((d, lap + k) in stopped for k in range(LEAD + 1))
    ]
    return {
        "stops": len(seen),
        "called": sum(calls[(s["driver"], s["lap"])] == "BOX" for s in seen),
        "boxes": len(boxes),
        "followed": len(soon),
        "cards": len(calls),
    }


def _rate(rows: list[dict[str, int]], top: str, bottom: str) -> float | None:
    total = sum(r[bottom] for r in rows)
    return round(sum(r[top] for r in rows) / total, 3) if total else None


def summary(races: list[dict], name: str, kind: str | None = None) -> dict[str, Any]:
    """Recall at the stop lap and precision of BOX, with race-level 95% intervals."""
    rows = [counts(race, name, kind) for race in races]
    rng = random.Random(2026)
    draws = {"recall": [], "precision": []}
    for _ in range(DRAWS):
        sample = rng.choices(rows, k=len(rows))
        draws["recall"].append(_rate(sample, "called", "stops") or 0.0)
        draws["precision"].append(_rate(sample, "followed", "boxes") or 0.0)
    interval = {
        k: [
            round(sorted(v)[int(0.025 * DRAWS)], 3),
            round(sorted(v)[int(0.975 * DRAWS)], 3),
        ]
        for k, v in draws.items()
    }
    return {
        "stops": sum(r["stops"] for r in rows),
        "recall": _rate(rows, "called", "stops"),
        "recall_interval": interval["recall"],
        "precision": _rate(rows, "followed", "boxes"),
        "precision_interval": interval["precision"],
        "box_rate": _rate(rows, "boxes", "cards"),
    }


def report(races: list[dict]) -> dict[str, Any]:
    names = list(races[0]["calls"]) if races else []
    out = {"all": {name: summary(races, name) for name in names}}
    for kind in ("GREEN", "SC", "VSC", "WET"):
        out[kind] = {name: summary(races, name, kind) for name in names}
    return out


def stop_thresholds(races: list[dict]) -> dict[str, list[float]]:
    """25th percentile and median tyre loss on the cards of real green stops (D7)."""
    values: dict[str, list[float]] = defaultdict(list)
    for race in races:
        if race["race_id"] in TYRE_RULE_RACES:
            continue
        for stop in race["stops"]:
            card = race["cards"].get((stop["driver"], stop["lap"]))
            loss = card and card.get("tyre_loss_s_per_lap")
            if (
                stop["condition"] == "GREEN"
                and loss is not None
                and card["surface"] == "DRY"
            ):
                values[card["compound"]].append(loss)
    return {
        c: [round(q, 2) for q in quantiles(v, n=4)[:2]]
        for c, v in sorted(values.items())
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--splits", nargs="+", default=["validation", "mini_test", "final"]
    )
    parser.add_argument("--thresholds", action="store_true", help="print D7 thresholds")
    args = parser.parse_args(argv)
    document = load_splits(SPLITS_V2_FILE)
    races = [
        race_cases(document["races"][race_id])
        for split in args.splits
        for race_id in document["splits"][split]
    ]
    if args.thresholds:
        print(json.dumps(stop_thresholds(races)))
        return 0
    print(json.dumps({"splits": args.splits, **report(races)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
