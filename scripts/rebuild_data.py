"""Rebuild the race-level splits and the race cards from OpenF1 (task 2.1).

Usage, from the repository root:
    python -m scripts.rebuild_data splits --seasons 2023 2024 2025 --seed 2026
    python -m scripts.rebuild_data card --race 2024-01 --driver 1 --lap 20
    python -m scripts.rebuild_data cards
    python -m scripts.rebuild_data splits-v2
    python -m scripts.rebuild_data quality
    python -m scripts.rebuild_data priors
    python -m scripts.rebuild_data cards-v2

Raw responses stay in data/cache/openf1/ and cards in data/cards/; neither is
committed. Exit code 2 means a source failed, 3 that a card is out of scope.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from boxbox.data import (
    CardNotEligible,
    DataUnavailableError,
    build_card,
    build_race_cards,
    freeze_splits,
    load_splits,
    make_splits,
    race_table,
    season_races,
)
from boxbox.data.cards import SCHEMA_VERSION, timing_gaps
from boxbox.data.cards_v2 import SCHEMA_VERSION as SCHEMA_V2
from boxbox.data.cards_v2 import build_race_cards_v2, race_context
from boxbox.data.openf1 import ENDPOINTS_V2, race_control, race_extras, raw_sha256
from boxbox.data.priors import PRIORS_FILE, load_reference, race_summary
from boxbox.data.splits import CLOSED_SPLITS, FRACTIONS, SPLITS_FILE, SPLITS_V2_FILE
from boxbox.rules import decide

CARDS_DIR = Path("data/cards")
CARDS_V2_DIR = Path("data/cards-v2")
SNAPSHOT = datetime(2026, 10, 22, tzinfo=UTC)  # milestone 4 bis, D1
SETTLE = timedelta(days=3)  # OpenF1 keeps loading a race for a while after it ends
LAST_2026 = {"test_2026": 3, "validation": 3}  # the latest 2026 races, in time order
EVAL_SPLITS = ("validation", "mini_test", "final", "test_2026")
CONTRACT_ERRORS = (
    "The card schema",
    "The card identity",
)  # decide's reasons for a malformed card


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pandas": importlib.metadata.version("pandas"),
    }


def cmd_splits(args: argparse.Namespace) -> int:
    if SPLITS_FILE.exists():
        print(f"{SPLITS_FILE} is frozen; it is never overwritten", file=sys.stderr)
        return 1
    try:
        races = {
            race["race_id"]: race
            for season in args.seasons
            for race in season_races(season)
        }
    except DataUnavailableError as error:
        print(f"data unavailable: {error}", file=sys.stderr)
        return 2
    splits = make_splits(list(races), args.seed, FRACTIONS, args.min_eval_races)
    freeze_splits(
        {
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": "OpenF1 race sessions, Jolpica rounds and event names",
            "unit": "whole race",
            "seasons": args.seasons,
            "seed": args.seed,
            "fractions": FRACTIONS,
            "min_eval_races": args.min_eval_races,
            "counts": {name: len(ids) for name, ids in splits.items()},
            "races": dict(sorted(races.items())),
            "splits": splits,
        }
    )
    print(json.dumps({name: len(ids) for name, ids in splits.items()}))
    return 0


def split_2026(races: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Time-ordered 2026 split: the last races test, the ones before validate."""
    ids = [r["race_id"] for r in sorted(races, key=lambda r: r["date_end"])]
    test = ids[len(ids) - LAST_2026["test_2026"] :]
    validation = ids[len(ids) - sum(LAST_2026.values()) : len(ids) - len(test)]
    train = ids[: len(ids) - len(test) - len(validation)]
    return {"train": train, "validation": validation, "test_2026": test}


def cmd_splits_v2(args: argparse.Namespace) -> int:
    if SPLITS_V2_FILE.exists():
        print(f"{SPLITS_V2_FILE} is frozen; it is never overwritten", file=sys.stderr)
        return 1
    v1 = load_splits()
    try:
        found = {r["race_id"]: r for s in range(2023, 2027) for r in season_races(s)}
    except DataUnavailableError as error:
        print(f"data unavailable: {error}", file=sys.stderr)
        return 2
    if any(
        found[rid]["session_key"] != r["session_key"] for rid, r in v1["races"].items()
    ):
        print("session keys differ from data/splits.json", file=sys.stderr)
        return 2
    run = [
        r
        for r in found.values()
        if r["season"] == 2026
        and r["date_end"]
        and pd.Timestamp(r["date_end"]) <= SNAPSHOT - SETTLE
    ]
    splits = {name: list(ids) for name, ids in v1["splits"].items()}
    for name, ids in split_2026(run).items():
        splits[name] = sorted(splits.get(name, []) + ids)
    races = {
        rid: found[rid] for rid in sorted({*v1["races"], *(r["race_id"] for r in run)})
    }
    freeze_splits(
        {
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": "OpenF1 race sessions, Jolpica rounds and event names",
            "unit": "whole race",
            "base": {"file": str(SPLITS_FILE), "splits_sha256": v1["splits_sha256"]},
            "snapshot": SNAPSHOT.date().isoformat(),
            "rule": "2023-2025 keep data/splits.json; 2026 races ended 3 days before "
            "the snapshot go in time order: the last 3 to test_2026, the 3 before "
            "to validation, the rest to train",
            "counts": {name: len(ids) for name, ids in splits.items()},
            "races": races,
            "splits": splits,
        },
        SPLITS_V2_FILE,
    )
    print(json.dumps({name: len(ids) for name, ids in splits.items()}))
    return 0


def gap_differences(
    table: pd.DataFrame, race: dict[str, Any], intervals: list[dict[str, Any]]
) -> list[float]:
    """Seconds between each known card gap ahead and OpenF1's interval just after."""
    records, _ = build_race_cards(table, race)
    crossings = table.set_index(["driver_number", "lap"])["at_line"]
    cards = pd.DataFrame(
        {
            "driver_number": r["card"]["driver_number"],
            "at": crossings[(r["card"]["driver_number"], r["card"]["lap"] - 1)],
            "gap": r["card"]["gap_ahead"]["seconds"],
        }
        for r in records
        if r["card"]["gap_ahead"]["state"] == "KNOWN"
    )
    official = pd.DataFrame(intervals)
    official = official.assign(
        driver_number=official["driver_number"].astype(str),
        at=pd.to_datetime(official["date"], utc=True, format="ISO8601"),
        interval=pd.to_numeric(official["interval"], errors="coerce"),  # "+1 LAP"
    ).dropna(subset=["interval"])
    if cards.empty or official.empty:
        return []
    for frame in (cards, official):  # the two sources keep different time resolutions
        frame["at"] = frame["at"].astype("datetime64[ns, UTC]")
    joined = pd.merge_asof(
        cards.sort_values("at"),
        official[["driver_number", "at", "interval"]].sort_values("at"),
        on="at",
        by="driver_number",
        direction="forward",
        tolerance=pd.Timedelta(seconds=6),  # intervals come about every 4 s
    ).dropna(subset=["interval"])
    return list((joined["gap"] - joined["interval"]).abs())


def _summary(values: list[float]) -> dict[str, Any]:
    series = pd.Series(values, dtype=float)
    return {
        "cards": len(series),
        "median_s": round(float(series.median()), 2) if len(series) else None,
        "max_s": round(float(series.max()), 2) if len(series) else None,
        "over_0_5_s": round(float((series > 0.5).mean()), 4) if len(series) else None,
    }


def cmd_quality(args: argparse.Namespace) -> int:
    """Check card gaps against OpenF1 intervals on the evaluation races (D12)."""
    document = load_splits(SPLITS_V2_FILE)
    report: dict[str, Any] = {}
    for split in EVAL_SPLITS:
        values: list[float] = []
        for race_id in document["splits"][split]:
            race = document["races"][race_id]
            try:
                official = race_extras(race, intervals=True)["intervals"]
                values += gap_differences(race_table(race), race, official)
            except DataUnavailableError as error:
                report.setdefault("failures", {})[race_id] = str(error)
        report[split] = _summary(values)
    print(json.dumps(report, indent=2))
    return 2 if "failures" in report else 0


def cmd_priors(args: argparse.Namespace) -> int:
    """Summarise every train race of the v2 splits for the card priors."""
    document = load_splits(SPLITS_V2_FILE)
    races = {}
    for race_id in document["splits"]["train"]:
        race = document["races"][race_id]
        races[race_id] = race_summary(race, race_table(race), race_control(race))
    PRIORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRIORS_FILE.write_text(
        json.dumps(
            {
                "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "splits_sha256": document["splits_sha256"],
                "races": races,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"races": len(races)}))
    return 0


def _rebuild_race_v2(
    race: dict[str, Any], split: str, priors: dict, reference: dict
) -> tuple[dict[str, Any], Counter]:
    """Write one race's 2.0 cards and return its manifest entry and label counts."""
    table = race_table(race)
    weather = race_extras(race)["weather"]
    context = race_context(race, table, race_control(race), weather, priors, reference)
    records, skipped = build_race_cards_v2(table, race, context)
    text = "".join(_canonical({**record, "split": split}) + "\n" for record in records)
    (CARDS_V2_DIR / f"{race['race_id']}.jsonl").write_text(text, encoding="utf-8")
    answers = [decide(record["card"]) for record in records]
    entry = {
        "split": split,
        "event": race["event"],
        "cards": len(records),
        "skipped": dict(skipped),
        "contract_errors": sum(why.startswith(CONTRACT_ERRORS) for _, why in answers),
        "sha256": _sha256(text),
        "raw_sha256": raw_sha256(race, names=ENDPOINTS_V2),
    }
    return entry, Counter(call for call, _ in answers)


def cmd_cards_v2(args: argparse.Namespace) -> int:
    """Rebuild every 2.0 card of the v2 splits with the train-race priors."""
    document = load_splits(SPLITS_V2_FILE)
    priors = json.loads(PRIORS_FILE.read_text(encoding="utf-8"))["races"]
    reference = load_reference()
    CARDS_V2_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "splits_sha256": document["splits_sha256"],
        "schema_version": SCHEMA_V2,
        "versions": _versions(),
        "labels": {},
        "races": {},
        "failures": {},
    }
    for split, race_ids in document["splits"].items():
        labels: Counter = Counter()
        for race_id in race_ids:
            try:
                manifest["races"][race_id], counts = _rebuild_race_v2(
                    document["races"][race_id], split, priors, reference
                )
            except DataUnavailableError as error:
                manifest["failures"][race_id] = str(error)
                continue
            labels.update(counts)
        if split not in CLOSED_SPLITS:
            manifest["labels"][split] = dict(labels)
    (CARDS_V2_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"labels": manifest["labels"], "failures": manifest["failures"]}))
    return 2 if manifest["failures"] else 0


def cmd_card(args: argparse.Namespace) -> int:
    race = load_splits()["races"][args.race]
    try:
        card, _ = build_card(race_table(race), race, str(args.driver), args.lap, None)
    except DataUnavailableError as error:
        print(f"data unavailable: {error}", file=sys.stderr)
        return 2
    except CardNotEligible as reason:
        print(f"not eligible: {reason}", file=sys.stderr)
        return 3
    print(json.dumps(card, indent=2, ensure_ascii=False))
    print(f"sha256={_sha256(_canonical(card))}", file=sys.stderr)
    return 0


def _timed_share(table) -> float:
    """Timed laps over drivers x race laps; lapped cars and retirements also lower it."""
    expected = table["driver_number"].nunique() * table["lap"].max()
    return round(float(table["end_s"].notna().sum() / expected), 3)


def _rebuild_race(race: dict[str, Any], split: str) -> tuple[dict[str, Any], Counter]:
    """Write one race's cards and return its manifest entry and label counts."""
    table = race_table(race)
    records, skipped = build_race_cards(table, race)
    text = "".join(_canonical({**record, "split": split}) + "\n" for record in records)
    (CARDS_DIR / f"{race['race_id']}.jsonl").write_text(text, encoding="utf-8")
    answers = [decide(record["card"]) for record in records]
    entry = {
        "split": split,
        "event": race["event"],
        "cards": len(records),
        "skipped": dict(skipped),
        "contract_errors": sum(why.startswith(CONTRACT_ERRORS) for _, why in answers),
        "sha256": _sha256(text),
        "timed_lap_share": _timed_share(table),
        "raw_sha256": raw_sha256(race),
        "timing_gaps": timing_gaps(table),  # must be 0, see boxbox.data.cards
    }
    return entry, Counter(call for call, _ in answers)


def cmd_cards(args: argparse.Namespace) -> int:
    document = load_splits()
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "splits_sha256": document["splits_sha256"],
        "schema_version": SCHEMA_VERSION,
        "versions": _versions(),
        "labels": {},
        "races": {},
        "failures": {},
    }
    for split, race_ids in document["splits"].items():
        labels: Counter = Counter()
        for race_id in race_ids:
            try:
                manifest["races"][race_id], counts = _rebuild_race(
                    document["races"][race_id], split
                )
            except DataUnavailableError as error:
                manifest["failures"][race_id] = str(error)
                continue
            labels.update(counts)
        if split not in CLOSED_SPLITS:
            manifest["labels"][split] = dict(labels)
    (CARDS_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"labels": manifest["labels"], "failures": len(manifest["failures"])}
        )
    )
    return 2 if manifest["failures"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    splits = commands.add_parser("splits", help="freeze the race-level splits once")
    splits.add_argument("--seasons", type=int, nargs="+", required=True)
    splits.add_argument("--seed", type=int, required=True)
    splits.add_argument("--min-eval-races", type=int, default=5)
    card = commands.add_parser("card", help="print one card and its sha256")
    card.add_argument("--race", required=True)
    card.add_argument("--driver", type=int, required=True)
    card.add_argument("--lap", type=int, required=True)
    commands.add_parser("cards", help="rebuild every card of the frozen splits")
    commands.add_parser("splits-v2", help="freeze the 2023-2026 splits once")
    commands.add_parser("quality", help="check card gaps against OpenF1 intervals")
    commands.add_parser("priors", help="summarise the v2 train races for priors")
    commands.add_parser("cards-v2", help="rebuild every 2.0 card of the v2 splits")
    args = parser.parse_args(argv)
    handlers = {
        "splits": cmd_splits,
        "card": cmd_card,
        "cards": cmd_cards,
        "splits-v2": cmd_splits_v2,
        "quality": cmd_quality,
        "priors": cmd_priors,
        "cards-v2": cmd_cards_v2,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
