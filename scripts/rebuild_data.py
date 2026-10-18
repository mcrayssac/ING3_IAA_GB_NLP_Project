"""Rebuild the race-level splits and the race cards from OpenF1 (task 2.1).

Usage, from the repository root:
    python -m scripts.rebuild_data splits --seasons 2023 2024 2025 --seed 2026
    python -m scripts.rebuild_data card --race 2024-01 --driver 1 --lap 20
    python -m scripts.rebuild_data cards

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from boxbox.data.openf1 import raw_sha256
from boxbox.data.splits import CLOSED_SPLITS, FRACTIONS, SPLITS_FILE
from boxbox.rules import decide

CARDS_DIR = Path("data/cards")
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
    args = parser.parse_args(argv)
    return {"splits": cmd_splits, "card": cmd_card, "cards": cmd_cards}[args.command](
        args
    )


if __name__ == "__main__":
    raise SystemExit(main())
