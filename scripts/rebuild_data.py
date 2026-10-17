#!/usr/bin/env python3
"""Rebuild BoxBox race data from FastF1 (roadmap task M2.1).

Run from the repository root:

    python scripts/rebuild_data.py splits --seasons 2023 2024 2025 --seed 2026
    python scripts/rebuild_data.py card --race 2024-01 --driver VER --lap 20
    python scripts/rebuild_data.py cards

`splits` freezes data/splits.json and refuses to overwrite it (use --force only
after an explicit team decision, before any dialogue exists). `cards` builds
every eligible card of the frozen races into data/cards/<split>.jsonl with a
manifest. Raw timing data stays in the local FastF1 cache (data/cache/) and is
never committed or redistributed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boxbox import data as D  # noqa: E402

DATA = ROOT / "data"
SPLITS = DATA / "splits.json"
CACHE = DATA / "cache"
CARDS = DATA / "cards"

DEFAULT_FRACTIONS = {"train": 0.70, "validation": 0.10, "mini_test": 0.10, "final": 0.10}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def versions() -> dict[str, str]:
    import fastf1
    import pandas

    return {"python": platform.python_version(), "fastf1": fastf1.__version__, "pandas": pandas.__version__}


def load_splits() -> dict:
    if not SPLITS.exists():
        sys.exit(f"error: {SPLITS} not found. Run `splits` first.")
    doc = json.loads(SPLITS.read_text(encoding="utf-8"))
    D.check_disjoint(doc["splits"])
    expected = D.sha256_text(D.canonical_json(doc["splits"]))
    if doc.get("splits_sha256") != expected:
        sys.exit("error: data/splits.json was edited by hand (fingerprint mismatch).")
    return doc


def cmd_splits(args: argparse.Namespace) -> int:
    if SPLITS.exists() and not args.force:
        print(f"error: {SPLITS} already exists and is frozen. Not overwriting.", file=sys.stderr)
        return 1
    events: dict[str, str] = {}
    for season in args.seasons:
        for race in D.list_races(season):
            events[race["race_id"]] = race["event"]
    excluded = sorted(set(args.exclude or []))
    for rid in excluded:
        events.pop(rid, None)
    splits = D.make_splits(list(events), args.seed, DEFAULT_FRACTIONS, args.min_eval_races)
    doc = {
        "created_utc": now(),
        "seed": args.seed,
        "seasons": args.seasons,
        "fractions": DEFAULT_FRACTIONS,
        "min_eval_races": args.min_eval_races,
        "excluded_races": excluded,
        "unit": "whole race (FastF1 session 'R')",
        "versions": versions(),
        "events": dict(sorted(events.items())),
        "splits": splits,
        "splits_sha256": D.sha256_text(D.canonical_json(splits)),
        "counts": {k: len(v) for k, v in splits.items()},
    }
    DATA.mkdir(exist_ok=True)
    SPLITS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(doc["counts"]))
    print(f"wrote {SPLITS}  sha256={doc['splits_sha256'][:12]}")
    return 0


def cmd_card(args: argparse.Namespace) -> int:
    season, rnd = D.parse_race_id(args.race)
    try:
        laps, meta = D.load_race(season, rnd, CACHE)
        card = D.build_card(laps, meta, args.driver.upper(), args.lap)
    except D.DataUnavailableError as exc:
        print(f"error: data unavailable: {exc}", file=sys.stderr)
        return 2
    except D.CardNotEligible as exc:
        print(f"not eligible: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(card, indent=2, ensure_ascii=False))
    print(f"sha256={D.card_fingerprint(card)}", file=sys.stderr)
    return 0


def cmd_cards(args: argparse.Namespace) -> int:
    doc = load_splits()
    params = D.CardParams()
    CARDS.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_utc": now(),
        "splits_sha256": doc["splits_sha256"],
        "params": params.to_dict(),
        "schema_version": D.CARD_SCHEMA_VERSION,
        "versions": versions(),
        "files": {},
        "races": {},
        "failures": {},
    }
    only = set(args.split) if args.split else set(D.SPLIT_NAMES)
    for split, races in doc["splits"].items():
        if split not in only:
            continue
        lines: list[str] = []
        for rid in races:
            season, rnd = D.parse_race_id(rid)
            try:
                laps, meta = D.load_race(season, rnd, CACHE)
            except D.DataUnavailableError as exc:
                manifest["failures"][rid] = str(exc)
                print(f"[{split}] {rid}: FAILED {exc}", file=sys.stderr)
                continue
            cards, skipped = D.build_race_cards(laps, meta, params)
            lines += [D.canonical_json(c) for c in cards]
            manifest["races"][rid] = {"split": split, "event": meta["event"], "cards": len(cards), "skipped": skipped}
            print(f"[{split}] {rid} {meta['event']}: {len(cards)} cards")
        text = "\n".join(lines) + ("\n" if lines else "")
        path = CARDS / f"{split}.jsonl"
        path.write_text(text, encoding="utf-8")
        manifest["files"][f"cards/{split}.jsonl"] = {"cards": len(lines), "sha256": D.sha256_text(text)}
    (CARDS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if manifest["failures"]:
        print(f"{len(manifest['failures'])} race(s) failed, see data/cards/manifest.json", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("splits", help="freeze the race-level splits")
    s.add_argument("--seasons", type=int, nargs="+", default=[2023, 2024, 2025])
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--min-eval-races", type=int, default=5)
    s.add_argument("--exclude", nargs="*", help="race ids to leave out, e.g. 2023-06")
    s.add_argument("--force", action="store_true", help="overwrite (team decision required)")
    s.set_defaults(func=cmd_splits)

    c = sub.add_parser("card", help="print one card (reproducibility check)")
    c.add_argument("--race", required=True, help="race id, e.g. 2024-01")
    c.add_argument("--driver", required=True, help="three-letter code, e.g. VER")
    c.add_argument("--lap", type=int, required=True)
    c.set_defaults(func=cmd_card)

    a = sub.add_parser("cards", help="build all cards of the frozen splits")
    a.add_argument("--split", nargs="*", choices=D.SPLIT_NAMES)
    a.set_defaults(func=cmd_cards)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
