"""Final cases (4.1) on stand-in cards for the final races; no real final card is read."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from boxbox.corpus import eval_set
from boxbox.evaluation import SamplingError, adapt_split
from boxbox.evaluation._io import dumps, read_jsonl
from scripts import final_cases

sys.path.insert(0, str(Path(__file__).parent))
from test_corpus import records


DRIVERS = [str(n) for n in range(1, 100) if n not in (16, 63)]  # 16, 63: the gaps


@pytest.fixture
def cards(tmp_path) -> Path:
    """The synthetic cards of test_corpus, moved to the 7 final races."""
    document = json.loads(Path("data/splits.json").read_text(encoding="utf-8"))
    races = document["splits"]["final"]
    folder = tmp_path / "cards"
    folder.mkdir()
    rows: dict[str, list[str]] = {race: [] for race in races}
    for index, record in enumerate(records()):
        race = races[index % len(races)]
        season, number = race.split("-")
        card = {**record["card"], "race": {**record["card"]["race"]}}
        card["race"].update(season=int(season), round=int(number))
        slot = index // len(races)  # one car and lap per card inside its race
        card["driver_number"] = DRIVERS[slot % len(DRIVERS)]
        card["lap"] = 30 + slot // len(DRIVERS)
        card["as_of_completed_lap"] = card["lap"] - 1
        rows[race].append(
            dumps(
                {
                    "card_id": f"{race}-{card['driver_number']}-L{card['lap']:02d}",
                    "split": "final",
                    "card": card,
                    "provenance": {
                        "source": "openf1",
                        "session_key": document["races"][race]["session_key"],
                        "cutoff_lap": card["as_of_completed_lap"],
                    },
                }
            )
        )
    for race, lines in rows.items():
        (folder / f"{race}.jsonl").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8"
        )
    return folder


@pytest.fixture
def out(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(final_cases, "FAILURE", tmp_path / "failure.json")
    return tmp_path / "final"


def test_build_writes_200_cases_and_40_review_targets(cards, out) -> None:
    final_cases.build(out, cards)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    cover = manifest["coverage"]
    assert cover["dialogues"] == cover["targets"] == 200
    assert cover["kinds"] == {
        "complete": 60,
        "missing": 40,
        "decidable": 30,
        "multi": 40,
        "out_of_scope": 30,
    }
    assert set(cover["families"]) == {
        "complete",
        "blocking_incomplete",
        "usable_incomplete",
        "follow_up",
        "out_of_scope",
    }
    assert cover["follow_up_card_states"]["blocking_incomplete"] == 8
    assert cover["follow_up_card_states"]["usable_incomplete"] == 8
    assert len(manifest["races_with_cards"]) == 7
    selection = json.loads((out / "review-selection.json").read_text(encoding="utf-8"))
    assert len(selection["selected_case_ids"]) == 40
    assert set(selection["family_counts"].values()) == {8}
    assert max(selection["race_counts"].values()) <= 8
    cases, digest = read_jsonl(out / "cases.jsonl")
    assert digest == manifest["files"]["cases.jsonl"] == selection["cases_sha256"]
    assert {c["split"] for c in cases} == {"final"}
    assert manifest["freeze"]["check"] == "intact"
    with pytest.raises(FileExistsError):
        final_cases.build(out, cards)


def test_build_stops_when_the_freeze_does_not_hold(cards, out, monkeypatch) -> None:
    monkeypatch.setattr(final_cases.freeze, "check", lambda: ["x changed"])
    with pytest.raises(ValueError, match="freeze does not hold"):
        final_cases.build(out, cards)
    assert not out.exists()


def test_a_sampling_failure_writes_diagnostics_only(cards, out, monkeypatch) -> None:
    def fail(cases):
        raise SamplingError({"unfilled": ["follow_up round 0"]})

    monkeypatch.setattr(final_cases, "select_review_cases", fail)
    with pytest.raises(SamplingError):
        final_cases.build(out, cards)
    assert not out.exists()
    report = json.loads(final_cases.FAILURE.read_text(encoding="utf-8"))
    assert report["diagnostics"] == {"unfilled": ["follow_up round 0"]}


def test_the_final_split_needs_the_explicit_opening(cards) -> None:
    document = json.loads(Path("data/splits.json").read_text(encoding="utf-8"))
    races = document["splits"]["final"]
    source = [r for race in races for r in read_jsonl(cards / f"{race}.jsonl")[0]]
    floats = [
        json.loads(line)
        for race in races
        for line in (cards / f"{race}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    items = eval_set(floats, "final", 2026)
    with pytest.raises(ValueError, match="adapted for"):
        adapt_split(items, source, document, "final")
    assert len(adapt_split(items, source, document, "final", final_open=True)) == 200
