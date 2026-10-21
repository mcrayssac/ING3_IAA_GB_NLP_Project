"""Prepare the reserved final cases under the freeze (task 4.1).

Usage, from the repository root:
    python -m scripts.final_cases cards     # rebuild the final races' cards from OpenF1
    python -m scripts.final_cases build     # final dialogues, cases and the 40 review targets

Both commands first check `configs/freeze.json` (task 3.5) with `scripts.freeze check`
and stop on any difference: the final cards are read only under the recorded freeze.
`build` writes `data/final/` once and never overwrites it:

- `final.jsonl`: about 200 dialogues from the final races, built by the same corpus code
  as validation and the mini-test, and checked the same way (categories, caps, rule
  answers, wording unseen in corpus A, races of the final split only);
- `cases.jsonl`: one evaluation case per dialogue, its last assistant turn the target;
- `review-selection.json`: the 40 human-review targets of protocol section 8, chosen
  from case metadata before any model answers, the same for every retained version;
- `manifest.json`: hashes of the freeze, splits, cards and every file, and the counts.

If the 40 targets cannot be selected, nothing is written except the diagnostics in
`data/final-sampling-failure-<time>.json`, one file per attempt: the protocol forbids relaxing quotas or caps, so
the team decides what to do. No model is loaded and no answer is generated here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from boxbox.config import load_config
from boxbox.corpus import (
    EVAL_CAP,
    EVAL_KINDS,
    TRACK_ITEMS,
    check_incomplete_whys,
    check_set,
    check_unseen,
    eval_set,
    load_corpus,
)
from boxbox.evaluation import (
    SamplingError,
    adapt_split,
    select_review_cases,
    validate_cases,
)
from boxbox.evaluation._io import dumps, read_jsonl, sha256, write_jsonl
from scripts import freeze

SPLIT = "final"
SEED = 2026  # the corpus seed of 2.2
CARDS_DIR = Path("data/cards")
OUT = Path("data/final")
FAILURES = Path("data")  # data/final-sampling-failure-<time>.json, one per attempt
PARIS = ZoneInfo("Europe/Paris")


def gate() -> dict[str, Any]:
    """The freeze record, refused unless every frozen file still has its hash."""
    if not freeze.FREEZE.exists():
        raise ValueError("no configs/freeze.json: the versions are not frozen (3.5)")
    problems = freeze.check()
    if problems:
        raise ValueError("the freeze does not hold:\n" + "\n".join(problems))
    record = json.loads(freeze.FREEZE.read_text(encoding="utf-8"))
    if record.get("final_test_open") is not False:
        raise ValueError("the freeze record does not describe a closed final test")
    return record


def open_config(record: dict[str, Any]):
    """The baseline config of the freeze, with the final split opened for this task only."""
    config = load_config(record["versions"]["baseline"]["config_file"])
    return replace(config, final_test_open=True)


def rebuild_cards() -> dict[str, int]:
    """The final races' card files only, with their own manifest."""
    from boxbox.data import load_splits
    from scripts import rebuild_data

    gate()
    document = load_splits()
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    entries = {
        race: rebuild_data._rebuild_race(document["races"][race], SPLIT)[0]
        for race in document["splits"][SPLIT]
    }
    report = {
        "created_at": datetime.now(PARIS).isoformat(timespec="seconds"),
        "splits_sha256": document["splits_sha256"],
        "races": entries,
    }
    with (CARDS_DIR / "final-manifest.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return {race: entry["cards"] for race, entry in entries.items()}


def coverage(items: list[dict], cases: list[dict]) -> dict[str, Any]:
    """Counts by kind, family, expected call, race and follow-up card state."""
    return {
        "dialogues": len(items),
        "targets": len(cases),
        "kinds": dict(Counter(i["kind"] for i in items)),
        "families": dict(Counter(c["primary_family"] for c in cases)),
        "expected_calls": dict(Counter(c["reference"]["expected_call"] for c in cases)),
        "races": dict(sorted(Counter(c["race_id"] for c in cases).items())),
        "follow_up_card_states": dict(
            Counter(
                c["attributes"]["card_state"]
                for c in cases
                if c["primary_family"] == "follow_up"
            )
        ),
        "history_sensitive": sum(c["attributes"]["history_sensitive"] for c in cases),
    }


def build(out: Path = OUT, cards_dir: Path = CARDS_DIR) -> Path:
    """Final dialogues, cases and review targets, written once under the freeze."""
    from boxbox.data import load_cards, load_splits

    if out.exists():
        raise FileExistsError(f"{out} exists; the final cases are never rebuilt")
    record = gate()
    config = open_config(record)
    document = load_splits()
    races = document["splits"][SPLIT]
    # as in 2.2, dialogues come from load_cards (which refuses cards of another split);
    # the cases keep the exact decimals of the card files, as in 2.7
    items = eval_set(load_cards(SPLIT, config, cards_dir=cards_dir), SPLIT, SEED)
    records = [r for race in races for r in read_jsonl(cards_dir / f"{race}.jsonl")[0]]
    errors = check_set(
        items, EVAL_KINDS[SPLIT], set(races), EVAL_CAP, TRACK_ITEMS[SPLIT]
    )
    errors += check_incomplete_whys(items, SPLIT)
    errors += check_unseen(load_corpus("A_train"), items)
    others = {r for name, rs in document["splits"].items() if name != SPLIT for r in rs}
    errors += [
        f"{i['id']}: race also in another split"
        for i in items
        if i["card_id"].rsplit("-", 2)[0] in others
    ]
    if errors:
        raise ValueError("final dialogues fail their checks:\n" + "\n".join(errors))
    cases = adapt_split(
        items,
        records,
        document,
        SPLIT,
        record["shared_inference"]["history_turns"],
        final_open=True,
    )
    validate_cases(cases, document)
    try:
        selection = select_review_cases(cases)
    except SamplingError as error:
        report = {
            "created_at": datetime.now(PARIS).isoformat(timespec="seconds"),
            "error": str(error),
            "diagnostics": error.diagnostics,
            "coverage": coverage(items, cases),
            "rule": "protocol section 8: no quota redistribution, cap relaxation or "
            "replacement; the team decides before any generation",
        }
        stamp = datetime.now(PARIS).strftime("%Y%m%dT%H%M%S")
        failure = FAILURES / f"final-sampling-failure-{stamp}.json"
        with failure.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(dumps(report) + "\n")
        raise SamplingError({**error.diagnostics, "report": str(failure)}) from error
    out.mkdir(parents=True)
    items_hash = write_jsonl(out / "final.jsonl", items)
    cases_hash = write_jsonl(out / "cases.jsonl", cases)
    selection["cases_sha256"] = cases_hash
    selection.pop("sampling_manifest_sha256")
    selection["sampling_manifest_sha256"] = sha256(dumps(selection))
    with (out / "review-selection.json").open(
        "x", encoding="utf-8", newline="\n"
    ) as stream:
        stream.write(dumps(selection) + "\n")
    card_files = sorted(p for p in cards_dir.glob("*.jsonl") if p.stem in races)
    manifest = {
        "task": "4.1",
        "created_at": datetime.now(PARIS).isoformat(timespec="seconds"),
        "freeze": {
            "file": freeze.FREEZE.as_posix(),
            "sha256": sha256(freeze.FREEZE.read_bytes()),
            "frozen_at": record["frozen_at"],
            "git_commit": record["git_commit"],
            "check": "intact",
        },
        "git_commit": freeze.git("rev-parse", "HEAD"),
        "git_dirty": bool(freeze.git("status", "--porcelain", "--untracked-files=no")),
        "seed": SEED,
        "splits_document_sha256": document["document_sha256"],
        "final_races": races,
        "races_with_cards": sorted({c["race_id"] for c in cases}),
        "card_files": {p.name: sha256(p.read_bytes()) for p in card_files},
        "files": {
            "final.jsonl": items_hash,
            "cases.jsonl": cases_hash,
            "review-selection.json": sha256(
                (out / "review-selection.json").read_bytes()
            ),
        },
        "sampling_manifest_sha256": selection["sampling_manifest_sha256"],
        "coverage": coverage(items, cases),
        "review_targets": {
            "count": len(selection["selected_case_ids"]),
            "families": selection["family_counts"],
            "races": selection["race_counts"],
        },
    }
    with (out / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cards", help="rebuild the final races' cards")
    commands.add_parser("build", help="final dialogues, cases and review targets")
    args = parser.parse_args(argv)
    try:
        if args.command == "cards":
            print(json.dumps(rebuild_cards(), indent=2))
        else:
            manifest = json.loads((build() / "manifest.json").read_text())
            print(json.dumps(manifest["coverage"], indent=2))
            print(json.dumps(manifest["review_targets"], indent=2))
    except SamplingError as error:
        print(f"{error}; diagnostics in {error.diagnostics['report']}", file=sys.stderr)
        return 1
    except (ValueError, FileExistsError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
