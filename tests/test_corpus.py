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
    TRACK_ITEMS,
    check_corpus_a,
    check_set,
    check_unseen,
    corpus_a,
    eval_set,
    load_corpus,
)
from boxbox.corpus.build import path_of, remove_field
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
    "neutral": (20, None, 30.0, 20.0),  # under a safety car
}
# ages above are for MEDIUM; SOFT limits sit 4 laps lower and HARD limits 6 laps higher
SHIFT = {"MEDIUM": 0, "SOFT": -4, "HARD": 6}


def _gap(value, number):
    if value in ("NONE", "UNKNOWN"):
        return {"state": value, "seconds": None}
    if value is None:
        return {"state": "NONE", "seconds": None}
    return {**KNOWN, "seconds": value, "driver_number": number}


def records(split_race: str = "2024") -> list[dict]:
    """100 cards per shape, each from its own race and driver, dry, a third per compound."""
    out = []
    for index, (shape, (age, ahead, behind, loss)) in enumerate(SHAPES.items()):
        for n in range(100):
            card = copy.deepcopy(BASE)
            card["race"]["round"] = n % 20 + 1
            compound = list(SHIFT)[n % 3]
            card.update(
                compound=compound,
                tyre_age_laps=age + SHIFT[compound],
                pit_loss_seconds=loss,
                reference_lap_seconds=90.0,
                track_status="SC" if shape == "neutral" else "GREEN",
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
    for n in range(3):  # MEDIUM, SOFT and HARD cards of every shape
        for shape, record in zip(SHAPES, records()[n::100]):
            if shape not in ("missing", "decidable", "neutral"):
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
    tyres = Counter(
        (i["path"], i["card"]["compound"]) for i in items if i["kind"] == "complete"
    )
    for path, n in paths.items():  # every compound has its share of each path
        assert min(tyres[(path, c)] for c in SHIFT) >= 0.2 * n
    assert corpus_a(records(), 2026) == items  # same seed, same corpus


def test_eval_set_covers_every_category() -> None:
    items = eval_set(records(), "validation", 2026)
    races = {r["card_id"].rsplit("-", 2)[0] for r in records()}
    assert check_set(items, EVAL_KINDS["validation"], races, 6, 4) == []
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


def test_a_gap_stated_in_the_message_keeps_the_card_answer() -> None:
    items = corpus_a(records(), 2026)
    stated = [i for i in items if i["follow_up"] == "stated"]
    assert len(stated) == 20
    for (
        item
    ) in stated:  # same call as the first answer, and the WHY says the card decides
        first, second = item["messages"][1]["content"], item["messages"][3]["content"]
        assert second.split("\n")[0] == first.split("\n")[0]
        assert second.startswith(
            second.split("\n")[0] + "\nWHY: The call uses the card, not"
        )
        assert second.endswith(first[first.index("WHY: ") + 6 :])
    stated[0]["messages"][3]["content"] = (
        "CALL: BOX\nWHY: The stated gap allows a stop."
    )
    errors = check_corpus_a(items, {r["card_id"].rsplit("-", 2)[0] for r in records()})
    assert any("stated follow-up is not the rule's answer" in e for e in errors)


def test_evaluation_questions_are_worded_apart_from_corpus_a() -> None:
    train = corpus_a(records(), 2026)
    validation = eval_set(records(), "validation", 2026)
    assert check_unseen(train, validation) == []
    validation[0]["messages"][0] = train[0]["messages"][0]
    assert check_unseen(train, validation) == [
        f"{validation[0]['id']}: question wording also in corpus A"
    ]


def test_track_status_cards_need_every_other_field_known() -> None:
    items = eval_set(records(), "validation", 2026)
    races = {r["card_id"].rsplit("-", 2)[0] for r in records()}
    track = next(i for i in items if i["scope"] == "track_status")
    track["card"] = remove_field(track["card"], "pit_loss_seconds")
    errors = check_set(items, EVAL_KINDS["validation"], races, 6, 4)
    assert any("track status items" in e for e in errors)


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
    cards = tmp_path / "cards_manifest.json"
    monkeypatch.setattr(build_corpus, "CARDS_MANIFEST", cards)
    manifests = []
    for created in (
        "2026-10-18T10:00",
        "2026-10-18T11:00",
    ):  # a card rebuild, same cards
        race = {"split": "train", "sha256": "a"}
        cards.write_text(
            json.dumps({"created_utc": created, "races": {"2023-01": race}})
        )
        assert build_corpus.main(["build"]) == 0
        manifests.append((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "final" not in asked
    assert manifests[0] == manifests[1]
    sheet = (tmp_path / "review_sheet.csv").read_text(encoding="utf-8")
    assert sheet.count("\n") == 400 + 100 + 40 + 60 + 1  # B adds its 60 variants


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


@pytest.mark.parametrize("changed_field", ["card", "messages"])
def test_build_refreshes_review_after_an_item_changes(
    monkeypatch, tmp_path, capsys, changed_field
) -> None:
    from scripts import build_corpus

    items = corpus_a(records(), 2026)[:2]
    monkeypatch.setattr(build_corpus, "_sets", lambda seed: ({"A_train": items}, []))
    monkeypatch.setattr(build_corpus, "_cards_sha256", lambda: "cards")
    monkeypatch.setattr(
        build_corpus, "load_splits", lambda: {"document_sha256": "splits"}
    )
    monkeypatch.setattr(build_corpus, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "SHEET", tmp_path / "review_sheet.csv")
    assert build_corpus.main(["build"]) == 0
    assert json.loads(capsys.readouterr().out)["rows_to_review"] == 2
    summary = tmp_path / "review.json"
    assert json.loads(summary.read_text())["pending"] == 2

    rows = list(build_corpus._read_sheet().values())
    for row, source in zip(rows, ("automatic", "confirmed")):
        row.update(verdict="ok", note=f"{source}: checked this item.")
    with build_corpus.SHEET.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_corpus.SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    assert build_corpus.main(["review"]) == 0
    assert json.loads(summary.read_text())["ok"] == 2

    if changed_field == "card":
        items[0]["card"]["reference_lap_seconds"] += 1
    else:
        items[0]["messages"][0]["content"] = "Please explain the call."
    assert build_corpus.main(["build"]) == 0
    rebuilt = build_corpus._read_sheet()
    assert rebuilt[rows[0]["id"]]["verdict"] == ""
    assert rebuilt[rows[0]["id"]]["note"] == ""
    assert rebuilt[rows[1]["id"]] == rows[1]
    review = json.loads(summary.read_text())
    assert review["rows"] == 2
    assert review["read"] == review["confirmed"] == review["ok"] == 1
    assert review["automatic"] == review["unattributed"] == 0
    assert review["pending"] == 1 and review["fix"] == []


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


@pytest.mark.parametrize("split", ["train", "validation", "mini_test"])
def test_track_status_items_get_no_call(split) -> None:
    items = (
        corpus_a(records(), 2026)
        if split == "train"
        else eval_set(records(), split, 2026)
    )
    tracks = [i for i in items if i["scope"] == "track_status"]
    assert len(tracks) == TRACK_ITEMS[split]
    assert {i["kind"] for i in tracks} == {"out_of_scope"}
    for item in tracks:
        assert item["card"]["track_status"] == "SC"
        assert item["messages"][1]["content"].startswith(
            "CALL: NO CALL\nWHY: The card does not show green-flag running"
        )


def test_load_corpus_rejects_a_changed_file_or_policy(tmp_path) -> None:
    for name in ("manifest.json", "mini_test.jsonl"):
        (tmp_path / name).write_bytes((Path("data/corpus") / name).read_bytes())
    assert len(load_corpus("mini_test", tmp_path)) == 40
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(
        json.dumps({**manifest, "policy_version": "1.0"})
    )
    with pytest.raises(ValueError, match="policy 1.0"):
        load_corpus("mini_test", tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with (tmp_path / "mini_test.jsonl").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="differs from manifest.json"):
        load_corpus("mini_test", tmp_path)
