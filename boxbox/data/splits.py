"""Race-level splits, frozen in data/splits.json before any dialogue is generated."""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from boxbox.config import RunConfig

SPLITS_FILE = Path("data/splits.json")
SPLITS_V2_FILE = Path("data/splits-v2.json")
CARDS_DIR = Path("data/cards")
CLOSED_SPLITS = {"final", "test_2026"}  # read only once the versions are frozen
SPLIT_NAMES = ("train", "validation", "mini_test", "final")
FRACTIONS = {"train": 0.70, "validation": 0.10, "mini_test": 0.10, "final": 0.10}


def make_splits(
    race_ids: list[str],
    seed: int,
    fractions: dict[str, float] = FRACTIONS,
    min_eval_races: int = 5,
) -> dict[str, list[str]]:
    """Assign whole races to the four splits, deterministically for a given seed."""
    if set(fractions) != set(SPLIT_NAMES) or not math.isclose(
        sum(fractions.values()), 1.0
    ):
        raise ValueError(f"fractions must cover {SPLIT_NAMES} and sum to 1")
    ids = sorted(set(race_ids))
    if len(ids) != len(race_ids):
        raise ValueError("duplicate race ids")
    counts = {
        n: max(min_eval_races, round(fractions[n] * len(ids))) for n in SPLIT_NAMES[1:]
    }
    counts["train"] = len(ids) - sum(counts.values())
    if counts["train"] < 1:
        raise ValueError(
            f"{len(ids)} races are too few for {min_eval_races} per evaluation split"
        )
    random.Random(seed).shuffle(ids)
    splits, start = {}, 0
    for name in SPLIT_NAMES:
        splits[name] = sorted(ids[start : start + counts[name]])
        start += counts[name]
    check_disjoint(splits)
    return splits


def check_disjoint(splits: dict[str, list[str]]) -> None:
    """Raise if a race appears in two splits."""
    seen: dict[str, str] = {}
    for name, races in splits.items():
        for race in races:
            if race in seen:
                raise ValueError(f"race {race} is in both {seen[race]} and {name}")
            seen[race] = name


def splits_sha256(splits: dict[str, list[str]]) -> str:
    text = json.dumps(splits, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def document_sha256(document: dict[str, Any]) -> str:
    """Fingerprint of the whole manifest (races, session keys, settings), minus itself."""
    content = {k: v for k, v in document.items() if k != "document_sha256"}
    return splits_sha256(content)


def freeze_splits(document: dict[str, Any], path: Path = SPLITS_FILE) -> None:
    """Write the split manifest once; an existing file is never overwritten."""
    if path.exists():
        raise FileExistsError(f"{path} is frozen")
    document = {**document, "splits_sha256": splits_sha256(document["splits"])}
    document["document_sha256"] = document_sha256(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_splits(path: Path = SPLITS_FILE) -> dict[str, Any]:
    """Read the frozen manifest; refuse overlapping splits or a hand-edited file."""
    document = json.loads(path.read_text(encoding="utf-8"))
    check_disjoint(document["splits"])
    if document.get("splits_sha256") != splits_sha256(
        document["splits"]
    ) or document.get("document_sha256") != document_sha256(document):
        raise ValueError(f"{path} was edited by hand (fingerprint mismatch)")
    return document


class FinalSplitClosedError(RuntimeError):
    """The final split was requested before the final test was opened."""


def load_cards(
    split: str,
    config: RunConfig,
    cards_dir: Path = CARDS_DIR,
    splits_path: Path = SPLITS_FILE,
) -> list[dict[str, Any]]:
    """Card records of one split; `final` stays closed until config.final_test_open."""
    if split in CLOSED_SPLITS and not config.final_test_open:
        raise FinalSplitClosedError(f"{split} is closed until final_test_open is true")
    races = load_splits(splits_path)["splits"][split]
    records = []
    for race_id in races:
        lines = (
            (cards_dir / f"{race_id}.jsonl").read_text(encoding="utf-8").splitlines()
        )
        records += [json.loads(line) for line in lines]
    if any(record["split"] != split for record in records):
        raise ValueError(f"cards in {cards_dir} do not match the {split} split")
    return records
