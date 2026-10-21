"""Final cases (4.1) on stand-in cards for the final races; no real final card is read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_corpus import records

from boxbox.corpus import eval_set
from boxbox.evaluation import SamplingError, adapt_split
from boxbox.evaluation._io import dumps, read_jsonl
from scripts import final_cases

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
    monkeypatch.setattr(final_cases, "FAILURES", tmp_path)
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
    with pytest.raises(SamplingError) as raised:
        final_cases.build(out, cards)
    assert not out.exists()
    report = json.loads(Path(raised.value.diagnostics["report"]).read_text("utf-8"))
    assert report["diagnostics"] == {"unfilled": ["follow_up round 0"]}
    assert report["coverage"]["targets"] == 200  # the evidence of the failed attempt


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


def test_incomplete_whys_respect_the_race_driver_cap() -> None:
    """Regression (#58 review): the whys come last and must fit what the cap leaves."""
    import random
    from collections import Counter

    from boxbox.corpus import EVAL_CAP
    from boxbox.corpus.build import complete
    from boxbox.corpus.sets import _race_driver_of, _why_incomplete

    usable = [r for r in records() if complete(r["card"])]
    crowded = [
        {**r, "card_id": f"2024-01-77-L{30 + i}"} for i, r in enumerate(usable[:12])
    ]
    others = [
        {**r, "card_id": f"2024-02-{i:02d}-L30"} for i, r in enumerate(usable[12:20])
    ]
    taken = Counter({"2024-01-77": EVAL_CAP - 1})  # one card left for that car
    whys = _why_incomplete(
        crowded + others, set(), random.Random(0), 8, "blocking", taken
    )
    per_car = Counter(_race_driver_of(i) for i in whys)
    assert len(whys) == 8 and per_car["2024-01-77"] <= 1
    assert taken["2024-01-77"] <= EVAL_CAP
    with pytest.raises(ValueError, match="under the cap"):
        _why_incomplete(crowded, set(), random.Random(0), 8, "blocking", Counter(taken))


def test_final_track_items_accept_sc_cards_with_an_unknown_field() -> None:
    """Team decision on #20: the final races have SC/VSC cards, none neutral."""
    from boxbox.corpus import EVAL_CAP, EVAL_KINDS, TRACK_ITEMS, check_set, track_rule

    cards = []
    for record in records():
        card = record["card"]
        if card["track_status"] != "GREEN":  # no neutral card left, as in the final
            card = {**card, "gap_behind": {"state": "UNKNOWN", "seconds": None}}
        cards.append({**record, "card": card})
    races = {f"2024-{n:02d}" for n in range(1, 21)}
    items = eval_set(cards, "final", 2026)
    tracks = [i for i in items if i["scope"] == "track_status"]
    assert len(tracks) == 8
    assert all(i["card"]["gap_behind"]["state"] == "UNKNOWN" for i in tracks)
    assert (
        check_set(items, EVAL_KINDS["final"], races, EVAL_CAP, 8, track_rule("final"))
        == []
    )
    # validation keeps the neutral rule: the same cards cannot fill its track items
    validation = eval_set(cards, "validation", 2026)
    errors = check_set(validation, EVAL_KINDS["validation"], races, EVAL_CAP, 4)
    assert any("track status items" in e for e in errors)
    assert TRACK_ITEMS["validation"] == 4


def test_final_usable_cards_include_box_calls() -> None:
    """Team decision on #20: section 8 reviews 4 usable incomplete BOX targets."""
    from collections import Counter

    from boxbox.rules import decide

    items = eval_set(records(), "final", 2026)
    usable = Counter(
        decide(i["card"])[0]
        for i in items
        if i["kind"] == "decidable" and i.get("removed_field")
    )
    assert usable["BOX"] >= 8 and sum(usable.values()) == 15


def test_track_items_take_sc_or_vsc_cards_only() -> None:
    """Regression (#59 review): other non-green statuses are not track-status items."""
    from boxbox.corpus.sets import track_card

    sc = next(r["card"] for r in records() if r["card"]["track_status"] == "SC")
    assert track_card(sc) and track_card({**sc, "track_status": "VSC"})
    for status in ("UNKNOWN", "RED", None):
        assert not track_card({**sc, "track_status": status})


def test_box_preselection_respects_the_race_driver_cap() -> None:
    """Regression (#59 review): BOX cards crowded on one car stay under the cap."""
    import random
    from collections import Counter

    from boxbox.corpus import EVAL_CAP
    from boxbox.corpus.build import path_of
    from boxbox.corpus.sets import _irrelevant

    boxes = [
        r
        for r in records()
        if path_of(r["card"]) in ("box_old_tyres", "box_no_car_behind")
    ]
    crowded = [
        {**r, "card_id": f"2024-01-77-L{30 + i}"} for i, r in enumerate(boxes[:12])
    ]
    spread = [
        {**r, "card_id": f"2024-02-{i:02d}-L30"} for i, r in enumerate(boxes[12:20])
    ]
    taken = Counter({"2024-01-77": EVAL_CAP - 1})
    items = _irrelevant(crowded + spread, set(), random.Random(0), 8, 8, taken)
    per_car = Counter(i["card_id"].rsplit("-", 1)[0] for i in items)
    assert len(items) == 8 and per_car["2024-01-77"] <= 1
    with pytest.raises(ValueError, match="BOX cards"):
        _irrelevant(crowded, set(), random.Random(0), 8, 8, taken)
