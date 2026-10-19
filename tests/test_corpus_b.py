"""Corpus B: 340 items shared with A and 60 matched NO CALL variants (task 3.1)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_corpus import records

from boxbox.corpus import (
    B_SHARED,
    check_corpus_b,
    corpus_a,
    corpus_b,
    exposure,
    load_corpus,
    pairs,
)
from boxbox.data import load_splits
from boxbox.rules import decide, remove_field


@pytest.fixture(scope="module")
def a_items() -> list[dict]:
    return corpus_a(records(), 2026)


def _races() -> set[str]:
    return {r["card_id"].rsplit("-", 2)[0] for r in records()}


def test_b_keeps_340_items_and_replaces_the_60_swaps(a_items) -> None:
    original = copy.deepcopy(a_items)
    b_items = corpus_b(a_items)
    assert a_items == original  # A is not touched
    assert check_corpus_b(a_items, b_items, _races()) == []
    assert sum(a == b for a, b in zip(a_items, b_items)) == B_SHARED == 340
    for a, b in zip(a_items, b_items):
        if not a["swap_field"]:
            continue
        assert b["id"] == a["id"] + "-B" and b["source_id"] == a["id"]
        assert b["card"] == remove_field(a["card"], a["swap_field"])
        assert b["messages"][0] == a["messages"][0]  # same question
        assert b["messages"][1]["content"].startswith("CALL: NO CALL\nWHY: ")
        assert decide(a["card"])[0] != "NO CALL" and b["kind"] == "missing"
    assert corpus_b(a_items) == b_items  # deterministic


def test_pairs_list_the_shared_items_and_every_variant(a_items) -> None:
    links = pairs(corpus_b(a_items))
    assert len(links["shared"]) == 340 and len(links["pairs"]) == 60
    swapped = {i["id"] for i in a_items if i["swap_field"]}
    assert {p["a"] for p in links["pairs"]} == swapped
    assert not swapped & set(links["shared"])


@pytest.mark.parametrize(
    "tamper, message",
    [
        (lambda a, b: _shared(b)["messages"].append({}), "B changes"),
        (lambda a, b: b.pop(), "instead of 400"),
        (lambda a, b: _swap(b).update(card=a[_at(a)]["card"]), "still gets"),
        (lambda a, b: _swap(b)["messages"][0].update(content="Hi?"), "question"),
        (
            lambda a, b: _swap(b)["card"].update(reference_lap_seconds=1.0),
            "more than",
        ),
        (lambda a, b: _swap(b).update(removed_field="lap"), "not the swap field"),
        (lambda a, b: _swap(b).update(scope="betting"), "metadata"),
    ],
)
def test_checks_catch_a_broken_b(a_items, tamper, message) -> None:
    b_items = corpus_b(a_items)
    tamper(a_items, b_items)
    assert any(message in e for e in check_corpus_b(a_items, b_items, _races()))


def _at(items: list[dict]) -> int:
    return next(n for n, i in enumerate(items) if i["swap_field"])


def _shared(b_items: list[dict]) -> dict:
    return next(i for i in b_items if not i.get("source_id"))


def _swap(b_items: list[dict]) -> dict:
    return next(i for i in b_items if i.get("source_id"))


def test_checks_catch_a_race_outside_train(a_items) -> None:
    errors = check_corpus_b(a_items, corpus_b(a_items), {"2023-01"})
    assert any("race outside the train split" in e for e in errors)


def test_exposure_counts_cards_conversations_and_answers(a_items) -> None:
    b_items = corpus_b(a_items)
    chars = exposure(a_items)
    assert chars["items"] == 400 and chars["completion"] < chars["total"]
    words = exposure(b_items, lambda text: len(text.split()))
    assert 0 < words["completion"] < words["total"]
    shared = [a for a, b in zip(a_items, b_items) if a == b]
    assert exposure(shared)["total"] < chars["total"]


def test_build_b_writes_b_without_cards_and_keeps_a(monkeypatch, tmp_path) -> None:
    from scripts import build_corpus

    pools = {"train": records("2023"), "validation": records("2024")}
    pools["mini_test"] = records("2025")
    splits = {
        s: sorted({r["card_id"].rsplit("-", 2)[0] for r in p}) for s, p in pools.items()
    }
    monkeypatch.setattr(build_corpus, "load_cards", lambda split, c: pools[split])
    monkeypatch.setattr(
        build_corpus, "load_splits", lambda: {"splits": splits, "document_sha256": "x"}
    )
    monkeypatch.setattr(build_corpus, "_cards_sha256", lambda: "cards")
    monkeypatch.setattr(build_corpus, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "SHEET", tmp_path / "review_sheet.csv")
    assert build_corpus.main(["build"]) == 0
    built = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    (tmp_path / "B_train.jsonl").unlink()
    assert build_corpus.main(["build-b"]) == 0
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert after == built  # build-b alone gives what the full build gives
    assert len(load_corpus("B_train", tmp_path)) == 400
    review = json.loads((tmp_path / "review.json").read_text())
    assert review["rows"] == 600 and review["pending"] == 600
    assert b"\r\n" not in after["B_train.jsonl"]

    a_file = tmp_path / "A_train.jsonl"
    a_file.write_bytes(a_file.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError, match="differs from manifest.json"):
        build_corpus.main(["build-b"])


@pytest.mark.skipif(
    not Path("data/corpus/B_train.jsonl").exists(), reason="corpus B not built"
)
def test_committed_b_is_the_matched_corpus_of_committed_a() -> None:
    a_items, b_items = load_corpus("A_train"), load_corpus("B_train")
    assert b_items == corpus_b(a_items)
    train = set(load_splits()["splits"]["train"])
    assert check_corpus_b(a_items, b_items, train) == []
    manifest = json.loads(Path("data/corpus/manifest.json").read_text())
    links = Path("data/corpus") / manifest["b_pairs"]["file"]
    assert json.loads(links.read_text()) == pairs(b_items)
