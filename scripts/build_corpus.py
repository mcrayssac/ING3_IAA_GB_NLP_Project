"""Build corpus A, the evaluation sets and corpus B, then summarise their review.

Usage, from the repository root:
    python -m scripts.build_corpus build
    python -m scripts.build_corpus build-b
    python -m scripts.build_corpus review
    python -m scripts.build_corpus exposure

`build` reads cards only through boxbox.data.load_cards, so the final split stays
closed. It keeps the verdicts of the review sheet for every unchanged item.
`build-b` (task 3.1) derives corpus B from the committed corpus A alone, without
cards. `exposure` counts the tokens of A and B in the 2.6 training rows (prompts,
answers and completion masks), and their raw content, with the model tokenizer.
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
    check_corpus_b,
    check_set,
    check_unseen,
    corpus_a,
    corpus_b,
    eval_set,
    exposure,
    load_corpus,
    pairs,
)
from boxbox.data import load_cards, load_splits
from boxbox.rules import POLICY_VERSION

CORPUS_DIR = Path("data/corpus")
CARDS_MANIFEST = Path("data/cards/manifest.json")
SHEET = CORPUS_DIR / "review_sheet.csv"
PAIRS = "B_pairs.json"  # shared IDs and A/B pairs, next to the corpus files
EXPOSURE = "exposure.json"
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


def _write(path: Path, text: str) -> None:
    """Write UTF-8 with LF line ends on every OS, so the hash matches the file."""
    path.write_bytes(text.encode("utf-8"))


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


def _write_sheet(rows: list[dict[str, str]]) -> None:
    with SHEET.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


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
    errors += check_unseen(sets["A_train"], sets["validation"], sets["mini_test"])
    sets["B_train"] = corpus_b(sets["A_train"])
    errors += check_corpus_b(sets["A_train"], sets["B_train"], set(splits["train"]))
    return sets, errors


def _review_items(sets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Items with a review row: every item, except the B items that are A items."""
    return [
        i
        for name, items in sets.items()
        for i in items
        if name != "B_train" or i.get("source_id")
    ]


def _b_files(
    a_items: list[dict[str, Any]], b_items: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """B_pairs.json text, the B_train.jsonl manifest entry and the B manifest keys."""
    text, links = _jsonl(b_items), pairs(b_items)
    links_text = json.dumps(links, indent=2) + "\n"
    entry = {
        "items": len(b_items),
        "sha256": _sha256(text),
        "source": "A_train.jsonl",
        "shared": len(links["shared"]),
        "variants": len(links["pairs"]),
    }
    keys = {
        "b_pairs": {"file": PAIRS, "sha256": _sha256(links_text)},
        "exposure_characters": {
            "A_train": exposure(a_items),
            "B_train": exposure(b_items),
        },
    }
    return links_text, entry, keys


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
        _write(CORPUS_DIR / f"{name}.jsonl", text)
        files[f"{name}.jsonl"] = {"items": len(items), "sha256": _sha256(text)}
    b_keys = {}
    if "B_train" in sets:
        links_text, files["B_train.jsonl"], b_keys = _b_files(
            sets["A_train"], sets["B_train"]
        )
        _write(CORPUS_DIR / PAIRS, links_text)
    rows = _rows(_review_items(sets), _read_sheet())
    _write_sheet(rows)
    manifest = {
        "seed": seed,
        "policy_version": POLICY_VERSION,
        "splits_document_sha256": load_splits()["document_sha256"],
        "cards_sha256": _cards_sha256(),
        "files": files,
        **b_keys,
    }
    _write(CORPUS_DIR / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    if _write_review(rows) is None:
        return 1
    pending = sum(not row["verdict"] for row in rows)
    print(json.dumps({"files": files, "rows_to_review": pending}, indent=2))
    return 0


def cmd_build_b(args: argparse.Namespace) -> int:
    """Corpus B from the committed corpus A only; A and the evaluation sets stay as they are."""
    # load_corpus refuses an A whose bytes differ from the manifest hash
    a_items = load_corpus("A_train", CORPUS_DIR)
    b_items = corpus_b(a_items)
    errors = check_corpus_b(a_items, b_items, set(load_splits()["splits"]["train"]))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    links_text, entry, b_keys = _b_files(a_items, b_items)
    _write(CORPUS_DIR / "B_train.jsonl", _jsonl(b_items))
    _write(CORPUS_DIR / PAIRS, links_text)
    path = CORPUS_DIR / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"]["B_train.jsonl"] = entry
    manifest.update(b_keys)
    _write(path, json.dumps(manifest, indent=2) + "\n")
    old = _read_sheet()
    variants = [i for i in b_items if i.get("source_id")]
    ids = {i["id"] for i in variants}
    rows = [r for r in old.values() if r["id"] not in ids] + _rows(variants, old)
    _write_sheet(rows)
    if _write_review(rows) is None:
        return 1
    pending = sum(not row["verdict"] for row in rows if row["id"] in ids)
    print(json.dumps({"B_train.jsonl": entry, "variants_to_review": pending}, indent=2))
    return 0


ADAPTER_CONFIG = Path("configs/adapter-a.toml")  # the 2.6 training settings, kept for B


def training_exposure(engine: Any, items: list[dict], max_length: int) -> dict:
    """What one training epoch shows: the 2.6 rows, prompts included, and their masks.

    Every assistant turn is one row: the engine's prompt (system prompt with the card,
    history and question) followed by the answer and its end-of-turn token. The loss
    falls on the tokens whose completion mask is 1.
    """
    from boxbox.training.rows import build_rows

    rows = build_rows(engine, items, max_length)
    tokens = sum(len(row["input_ids"]) for row in rows)
    completion = sum(sum(row["completion_mask"]) for row in rows)
    return {
        "items": len(items),
        "rows": len(rows),
        "input_tokens": tokens,
        "prompt_tokens": tokens - completion,
        "completion_tokens": completion,
    }


def _difference(counts: dict[str, dict[str, int]], keys: tuple[str, ...]) -> dict:
    return {k: counts["B_train"][k] - counts["A_train"][k] for k in keys}


def tokenizer_engine(config: Any, tokenizer: Any) -> Any:
    """The 2.6 training engine without model weights: rows need only the tokenizer."""
    import torch

    from boxbox.model import ConversationEngine
    from scripts.train_adapter import selected_prompt

    return ConversationEngine(
        torch.nn.Module(),  # no weights: training_ids renders and tokenizes only
        tokenizer,
        config,
        instructions=selected_prompt(),
        device="cpu",
        dtype="not loaded",
    )


def cmd_exposure(args: argparse.Namespace) -> int:
    """Training-row tokens of A and B per epoch, and raw content tokens, to exposure.json."""
    from transformers import AutoTokenizer

    from boxbox.config import load_config

    config = load_config(ADAPTER_CONFIG)
    tokenizer = AutoTokenizer.from_pretrained(
        config.model_id, revision=config.model_revision
    )
    engine = tokenizer_engine(config, tokenizer)

    def tokens(text: str) -> int:
        return len(tokenizer(text, add_special_tokens=False)["input_ids"])

    sets = {name: load_corpus(name, CORPUS_DIR) for name in ("A_train", "B_train")}
    rows = {
        name: training_exposure(engine, items, config.lora.max_length)
        for name, items in sets.items()
    }
    raw = {name: exposure(items, tokens) for name, items in sets.items()}
    report = {
        "tokenizer": {"model_id": config.model_id, "revision": config.model_revision},
        "training_rows": {
            "unit": "tokens of the 2.6 training rows in one epoch: prompt (system "
            "prompt with the card, history, question) and completion (answer and "
            "end-of-turn token, where the loss falls)",
            "config_file": str(ADAPTER_CONFIG.as_posix()),
            "config_sha256": hashlib.sha256(ADAPTER_CONFIG.read_bytes()).hexdigest(),
            "prompt_sha256": hashlib.sha256(engine.instructions.encode()).hexdigest(),
            "epochs": config.lora.epochs,
            **rows,
            "B_minus_A": _difference(
                rows, ("rows", "input_tokens", "prompt_tokens", "completion_tokens")
            ),
        },
        "raw_content": {
            "unit": "tokens of the card JSON and every message, without the chat "
            "template, the system prompt or the end-of-turn tokens",
            **raw,
            "B_minus_A": _difference(raw, ("total", "completion")),
        },
    }
    _write(CORPUS_DIR / EXPOSURE, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
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
    commands.add_parser(
        "build-b",
        help="derive corpus B from corpus A and add its 60 variants to review",
    )
    commands.add_parser("review", help="summarise the filled review sheet")
    commands.add_parser("exposure", help="count the training-row tokens of A and B")
    args = parser.parse_args(argv)
    run = {
        "build": cmd_build,
        "build-b": cmd_build_b,
        "review": cmd_review,
        "exposure": cmd_exposure,
    }
    return run[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
