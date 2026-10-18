"""Corpus A, the evaluation sets and their checks, on synthetic cards (task 2.2)."""

from __future__ import annotations

import copy
import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from boxbox.corpus import (
    A_KINDS,
    EVAL_KINDS,
    check_corpus_a,
    check_set,
    corpus_a,
    eval_set,
)
from boxbox.corpus.build import path_of, remove_field
from boxbox.corpus.templates import what_if_answer
from boxbox.rules import decide
from boxbox.rules.decision import article, laps

BASE = json.loads(Path("reference/fixtures.json").read_text(encoding="utf-8"))
BASE = BASE["conversations"][0]["card"]
KNOWN = {"state": "KNOWN"}
SHAPES = {  # (tyre age, gap ahead, gap behind, pit loss) for each rule path
    "box_old_tyres": (20, None, 30.0, 20.0),
    "box_gap_ahead": (14, 1.0, 30.0, 20.0),
    "box_no_car_behind": (20, None, "NONE", 20.0),
    "stay_young_tyres": (5, None, 3.0, 20.0),
    "stay_gap_ahead": (14, 5.0, 30.0, 20.0),
    "stay_rejoin": (20, None, 5.0, 20.0),
    "missing": (20, None, "UNKNOWN", 20.0),
    "decidable": (5, None, 3.0, None),
}


def _gap(value, number):
    if value in ("NONE", "UNKNOWN"):
        return {"state": value, "seconds": None}
    if value is None:
        return {"state": "NONE", "seconds": None}
    return {**KNOWN, "seconds": value, "driver_number": number}


def records(split_race: str = "2024") -> list[dict]:
    """100 cards per shape, each from its own race and driver, all green and dry."""
    out = []
    for index, (age, ahead, behind, loss) in enumerate(SHAPES.values()):
        for n in range(100):
            card = copy.deepcopy(BASE)
            card["race"]["round"] = n % 20 + 1
            card.update(
                tyre_age_laps=age, pit_loss_seconds=loss, reference_lap_seconds=90.0
            )
            card["pit_loss_as_of_completed_lap"] = None if loss is None else 29
            card["gap_ahead"], card["gap_behind"] = (
                _gap(ahead, "16"),
                _gap(behind, "63"),
            )
            race = f"{split_race}-{n % 20 + 1:02d}"
            out.append(
                {
                    "card_id": f"{race}-{index}{n:02d}-L30",
                    "card": card,
                    "split": "x",
                }
            )
    return out


def test_paths_and_removed_fields() -> None:
    for shape, record in zip(SHAPES, records()[::100]):
        if shape in ("missing", "decidable"):
            continue
        assert path_of(record["card"]) == shape
    old = records()[0]["card"]
    assert decide(remove_field(old, "pit_loss_seconds"))[0] == "NO CALL"
    assert decide(remove_field(old, "gap_ahead"))[0] == "BOX"


def test_corpus_a_balance_swaps_and_checks() -> None:
    items = corpus_a(records(), 2026)
    races = {r["card_id"].rsplit("-", 2)[0] for r in records()}
    assert check_corpus_a(items, races) == []
    assert Counter(i["kind"] for i in items) == Counter(A_KINDS)
    paths = Counter(i["path"] for i in items if i["kind"] == "complete")
    assert max(paths.values()) - min(paths.values()) <= 10
    swaps = Counter(i["path"] for i in items if i["swap_field"])
    assert sum(swaps.values()) == 60 and set(swaps.values()) == {10}
    assert corpus_a(records(), 2026) == items  # same seed, same corpus


def test_eval_set_covers_every_category() -> None:
    items = eval_set(records(), "validation", 2026)
    races = {r["card_id"].rsplit("-", 2)[0] for r in records()}
    assert check_set(items, EVAL_KINDS["validation"], races, 6) == []
    assert sum("removed_field" in i for i in items) == 10 + 7


def test_checks_catch_a_wrong_answer_and_a_foreign_race() -> None:
    items = corpus_a(records(), 2026)
    items[0]["messages"][1]["content"] = "CALL: BOX\nWHY: Because. It is time."
    errors = check_corpus_a(items, {"2023-01"})
    assert any("not the rule's answer" in e for e in errors)
    assert any("WHY is not one sentence" in e for e in errors)
    assert any("race outside the split" in e for e in errors)


def test_wording() -> None:
    assert [article(n) for n in ("8.4", "11.0", "18.2", "83.0", "1.5", "24.0")] == [
        "an",
        "an",
        "an",
        "an",
        "a",
        "a",
    ]
    assert (laps(1), laps(3)) == ("1 lap", "3 laps")
    answer = what_if_answer(records()[0]["card"], 8.0)
    assert answer.startswith(
        "CALL: STAY OUT\nWHY: Assuming an 8.0-second gap behind, with MEDIUM tyres"
    )


def test_build_never_opens_the_final_split(monkeypatch, tmp_path) -> None:
    from scripts import build_corpus

    asked = []
    pools = {
        "train": records("2023"),
        "validation": records("2024"),
        "mini_test": records("2025"),
    }

    def fake_cards(split, config):
        asked.append(split)
        return pools[split]

    splits = {
        s: sorted({r["card_id"].rsplit("-", 2)[0] for r in p}) for s, p in pools.items()
    }
    document = {"splits": splits, "document_sha256": "x"}
    monkeypatch.setattr(build_corpus, "load_cards", fake_cards)
    monkeypatch.setattr(build_corpus, "load_splits", lambda: document)
    monkeypatch.setattr(build_corpus, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "SHEET", tmp_path / "review_sheet.csv")
    monkeypatch.setattr(build_corpus, "CARDS_MANIFEST", Path("reference/fixtures.json"))
    assert build_corpus.main(["build"]) == 0
    assert "final" not in asked
    sheet = (tmp_path / "review_sheet.csv").read_text(encoding="utf-8")
    assert sheet.count("\n") == 400 + 100 + 40 + 1


def test_review_verdicts_survive_only_unchanged_items(monkeypatch, tmp_path) -> None:
    from scripts import build_corpus

    item = corpus_a(records(), 2026)[0]
    first = build_corpus._rows([item], {})[0]
    reviewed = {**first, "verdict": "ok", "note": "confirmed: wording fits the card."}
    kept = build_corpus._rows([item], {item["id"]: reviewed})[0]
    changed = {
        **item,
        "messages": item["messages"][:1] + [{"role": "assistant", "content": "x"}],
    }
    lost = build_corpus._rows([changed], {item["id"]: reviewed})[0]
    assert (kept["verdict"], lost["verdict"]) == ("ok", "")
    assert (kept["note"], lost["note"]) == (reviewed["note"], "")


def test_review_counts_distinguish_decisions_from_pending_notes(monkeypatch, tmp_path):
    from scripts import build_corpus

    sheet = tmp_path / "review_sheet.csv"
    rows = [
        {"id": "1", "verdict": "ok", "note": "automatic: checked against policy."},
        {"id": "2", "verdict": "ok", "note": "confirmed: accepted this case."},
        {"id": "3", "verdict": "fix", "note": "confirmed: wrong car in question."},
        {"id": "4", "verdict": "", "note": "automatic: awaiting confirmation."},
        {"id": "5", "verdict": "ok", "note": "Earlier review without a prefix."},
    ]
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_corpus.SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(build_corpus, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "SHEET", sheet)
    assert build_corpus.main(["review"]) == 0
    review = json.loads((tmp_path / "review.json").read_text())
    assert review == {
        "rows": 5,
        "read": 4,
        "automatic": 1,
        "confirmed": 2,
        "unattributed": 1,
        "pending": 1,
        "ok": 3,
        "fix": [{"id": "3", "note": rows[2]["note"]}],
    }


@pytest.mark.parametrize("split", ["validation", "mini_test"])
def test_eval_sizes(split) -> None:
    assert len(eval_set(records(), split, 2026)) == sum(EVAL_KINDS[split].values())
