"""Build corpus A and the evaluation sets, then summarise their review (task 2.2).

Usage, from the repository root:
    python -m scripts.build_corpus build
    python -m scripts.build_corpus review

`build` reads cards only through boxbox.data.load_cards, so the final split stays
closed. It keeps the verdicts of the review sheet for every unchanged item.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from boxbox.config import RunConfig
from boxbox.corpus import (
    EVAL_KINDS,
    TRACK_ITEMS,
    check_corpus_a,
    check_set,
    corpus_a,
    eval_set,
)
from boxbox.data import load_cards, load_splits
from boxbox.rules import POLICY_VERSION

CORPUS_DIR = Path("data/corpus")
CARDS_MANIFEST = Path("data/cards/manifest.json")
SHEET = CORPUS_DIR / "review_sheet.csv"
SHEET_FIELDS = [
    "id",
    "digest",
    "split",
    "kind",
    "path",
    "card",
    "conversation",
    "verdict",
    "note",
]
EVAL_CAP = 6  # three capped pools of 2 per race and driver in an evaluation set


def _jsonl(items: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(i, sort_keys=True, ensure_ascii=False) + "\n" for i in items
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cards_sha256() -> str:
    """Hash of the per-race card files the corpus can read, without the build time."""
    races = json.loads(CARDS_MANIFEST.read_text(encoding="utf-8"))["races"]
    hashes = {race: v["sha256"] for race, v in races.items() if v["split"] != "final"}
    return _sha256(json.dumps(hashes, sort_keys=True))


def _summary(card: dict[str, Any]) -> str:
    gaps = []
    for side in ("gap_ahead", "gap_behind"):
        gap = card[side]
        seconds = "" if gap["seconds"] is None else f" {gap['seconds']} s"
        gaps.append(
            f"{side.split('_')[1]} {gap['state']}{seconds} #{gap.get('driver_number', '-')}"
        )
    return (
        f"{card['race']['season']} {card['race']['event']} lap {card['lap']} car "
        f"{card['driver_number']} | {card['compound']} {card['tyre_age_laps']} laps | "
        f"{' | '.join(gaps)} | pit loss {card['pit_loss_seconds']} | {card['track_status']}"
    )


def _rows(
    items: list[dict[str, Any]], old: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    """Review rows; a verdict is kept only while the item stays exactly the same."""
    rows = []
    for item in items:
        digest = _sha256(json.dumps([item["card"], item["messages"]], sort_keys=True))[
            :12
        ]
        talk = " || ".join(
            f"{m['role'].upper()}: {m['content']}" for m in item["messages"]
        )
        previous = old.get(item["id"], {})
        kept = previous.get("digest") == digest
        rows.append(
            {
                "id": item["id"],
                "digest": digest,
                "split": item["split"],
                "kind": item["kind"],
                "path": item["path"] or "",
                "card": _summary(item["card"]),
                "conversation": talk.replace("\n", " / "),
                "verdict": previous.get("verdict", "") if kept else "",
                "note": previous.get("note", "") if kept else "",
            }
        )
    return rows


def _read_sheet() -> dict[str, dict[str, str]]:
    if not SHEET.exists():
        return {}
    with SHEET.open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


def _sets(seed: int) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    splits = load_splits()["splits"]
    config = RunConfig()
    sets = {"A_train": corpus_a(load_cards("train", config), seed)}
    errors = check_corpus_a(sets["A_train"], set(splits["train"]))
    for split in ("validation", "mini_test"):
        sets[split] = eval_set(load_cards(split, config), split, seed)
        errors += check_set(
            sets[split],
            EVAL_KINDS[split],
            set(splits[split]),
            EVAL_CAP,
            TRACK_ITEMS[split],
        )
    return sets, errors


def cmd_build(args: argparse.Namespace) -> int:
    seed = RunConfig().seed
    sets, errors = _sets(seed)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, items in sets.items():
        text = _jsonl(items)
        (CORPUS_DIR / f"{name}.jsonl").write_text(text, encoding="utf-8")
        files[f"{name}.jsonl"] = {"items": len(items), "sha256": _sha256(text)}
    rows = _rows([i for items in sets.values() for i in items], _read_sheet())
    with SHEET.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "seed": seed,
        "policy_version": POLICY_VERSION,
        "splits_document_sha256": load_splits()["document_sha256"],
        "cards_sha256": _cards_sha256(),
        "files": files,
    }
    (CORPUS_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    if _write_review(rows) is None:
        return 1
    pending = sum(not row["verdict"] for row in rows)
    print(json.dumps({"files": files, "rows_to_review": pending}, indent=2))
    return 0


def _write_review(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    """Write the current sheet counts for both build and review commands."""
    bad = [r["id"] for r in rows if r["verdict"] not in ("", "ok", "fix")]
    if bad:
        print(f"verdicts must be ok or fix: {bad[:5]}", file=sys.stderr)
        return None
    reviewed = [r for r in rows if r["verdict"]]
    automatic = sum(r["note"].startswith("automatic:") for r in reviewed)
    confirmed = sum(r["note"].startswith("confirmed:") for r in reviewed)
    review = {
        "rows": len(rows),
        "read": len(reviewed),
        "automatic": automatic,
        "confirmed": confirmed,
        "unattributed": len(reviewed) - automatic - confirmed,
        "pending": len(rows) - len(reviewed),
        "ok": sum(r["verdict"] == "ok" for r in rows),
        "fix": [
            {"id": r["id"], "note": r["note"]} for r in rows if r["verdict"] == "fix"
        ],
    }
    (CORPUS_DIR / "review.json").write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    return review


def cmd_review(args: argparse.Namespace) -> int:
    review = _write_review(list(_read_sheet().values()))
    if review is None:
        return 1
    print(json.dumps({k: v if k != "fix" else len(v) for k, v in review.items()}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "build", help="build the corpus, the manifest and the review sheet"
    )
    commands.add_parser("review", help="summarise the filled review sheet")
    args = parser.parse_args(argv)
    return {"build": cmd_build, "review": cmd_review}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
