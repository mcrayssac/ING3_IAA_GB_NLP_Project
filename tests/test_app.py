"""The demo shell on hand-written cards: panels, session steps and handlers (task 2.4)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from boxbox.app import build_app, stub_respond
from boxbox.app import layout as L
from boxbox.app import panels as P
from boxbox.app.session import load_upload, sample_cards, send
from boxbox.evaluation.parsing import parse_response
from boxbox.rules import format_answer

FIXTURES = json.loads(Path("reference/fixtures.json").read_text(encoding="utf-8"))
CARDS = {c["id"]: c["card"] for c in FIXTURES["conversations"]}


def card(name: str = "medium_safe", **fields) -> dict:
    """A fixture card with some fields replaced."""
    return {**copy.deepcopy(CARDS[name]), **fields}


def test_circle_angles_and_rejoin_point() -> None:
    points = P.circle_points(
        card()
    )  # lap 90 s, ahead 1.5 s, behind 24.0 s, loss 21.0 s
    assert points["ahead"] == pytest.approx(6.0)
    assert points["behind"] == pytest.approx(-96.0)
    assert points["rejoin"] == pytest.approx(-84.0)
    assert points["band_end"] == pytest.approx(-92.0)
    assert points["cleared"] is True


def test_circle_with_unknown_gaps_missing_loss_and_lap_time() -> None:
    edge = card(
        gap_behind={"state": "KNOWN", "seconds": 23.0}
    )  # equality clears, rule 6
    assert P.circle_points(edge)["cleared"] is True
    assert (
        P.circle_points(card(gap_ahead={"state": "UNKNOWN", "seconds": None}))["ahead"]
        is None
    )
    assert (
        P.circle_points(card(gap_behind={"state": "NONE", "seconds": None}))["behind"]
        is None
    )
    assert P.circle_points(card(pit_loss_seconds=None))["rejoin"] is None
    assert "reference lap time" in P.circle_points(card(reference_lap_seconds=None))


def test_circle_readout_gives_the_numbers_in_words() -> None:
    assert P.circle_readout(card()) == (
        "Rejoins 21.0 s back, margin to 23.0 s. "
        "Car 63 behind at 24.0 s clears the margin by 1.0 s. Car 16 ahead at 1.5 s."
    )
    short = P.circle_readout(card(gap_behind={"state": "KNOWN", "seconds": 4.6}))
    assert "The car behind at 4.6 s is 18.4 s short of it." in short
    blanks = card(
        gap_ahead={"state": "UNKNOWN", "seconds": None},
        gap_behind={"state": "NONE", "seconds": None},
        pit_loss_seconds=None,
        reference_lap_seconds=None,
    )
    assert P.circle_readout(blanks) == (
        "No circle: the card has no reference lap time. "
        "No rejoin point: the pit loss is missing. No car behind. Gap ahead unknown."
    )


def test_charts_are_labelled_svg_and_skip_missing_data() -> None:
    circle = P.circle_of_doom(card())
    assert f'aria-label="{P.circle_readout(card())}"' in circle and "<svg" in circle
    assert "<svg" not in P.circle_of_doom(card(reference_lap_seconds=None))
    tyres = P.tyre_window(card())
    assert f'aria-label="{P.tyre_readout(card())}"' in tyres
    assert P.tyre_readout(card()) == (
        "15 laps on MEDIUM, in the window. Window from 12 laps, opportunity from 18."
    )
    assert "<svg" not in P.tyre_window(card(tyre_age_laps=None))
    sources = [f.read_text(encoding="utf-8") for f in Path("boxbox/app").glob("*.py")]
    assert not any("matplotlib" in source for source in sources)


def test_sending_disables_the_controls_until_the_engine_answers() -> None:
    waiting = L.busy(3)
    assert [u["interactive"] for u in waiting[:3]] == [False] * 3
    assert "Waiting for the engine" in waiting[3]
    assert [u["interactive"] for u in L.ready(3)] == [True] * 3


@pytest.mark.parametrize(
    ("compound", "young", "old"),
    [("SOFT", 8, 14), ("MEDIUM", 12, 18), ("HARD", 18, 24)],
)
def test_tyre_window_zones(compound, young, old) -> None:
    assert P.tyre_zones(card(compound=compound, tyre_age_laps=10)) == (
        young,
        old,
        10,
        old + 4,
    )
    assert P.tyre_zones(card(compound=compound, tyre_age_laps=40))[3] == 44


def test_tyre_window_names_why_it_is_not_drawn() -> None:
    assert "INTERMEDIATE" in P.tyre_zones(card(compound="INTERMEDIATE"))
    assert "tyre age is missing" in P.tyre_zones(card(tyre_age_laps=None))


def test_answers_are_read_never_repaired() -> None:
    assert P.parse_answer("CALL: BOX\nWHY: The gap covers the loss.") == (
        "BOX",
        "The gap covers the loss.",
    )
    for bad in ("CALL: BOX", "CALL: MAYBE\nWHY: x.", "Sure!\nCALL: BOX\nWHY: x.", None):
        assert P.parse_answer(bad) is None
    assert "not in CALL/WHY format" in P.banner("CALL: BOX")
    assert "No call yet" in P.banner(None)


def test_used_by_rule_and_highlighted_inputs() -> None:
    young = card(tyre_age_laps=5)  # STAY OUT on tyre age alone
    assert P.used_by_rule(young, "tyre_age_laps")
    assert not P.used_by_rule(young, "gap_behind")
    assert P.used_by_rule(card(), "gap_ahead") and P.used_by_rule(
        card(), "pit_loss_seconds"
    )
    table = P.inputs_table(card(tyre_age_laps=5, pit_loss_seconds=None), with_rule=True)
    assert '<tr class="unknown"><td>Pit loss</td>' in table and "<th>Rule</th>" in table
    assert "<th>Rule</th>" not in P.inputs_table(card(), with_rule=False)
    neutral = P.inputs_table(card(track_status="VSC"), with_rule=True)  # NO CALL card
    assert "<th>Rule</th>" not in neutral and "gives NO CALL" in neutral
    assert "1 lap on MEDIUM" in P.inputs_table(card(tyre_age_laps=1), with_rule=False)


def test_uploaded_text_is_escaped() -> None:
    hostile = card(
        race={"season": 2024, "event": "<script>x</script>", "completed": True}
    )
    assert "<script>" not in P.situation(hostile)


def test_send_bounds_the_history_and_never_stores_a_failure() -> None:
    seen = []

    def engine(current, history, message):
        seen.append(len(history))
        return format_answer(current)

    history = []
    for _ in range(5):
        history, problem = send(card(), history, "Box?", engine, turns=3)
        assert problem is None
    assert seen == [0, 2, 4, 6, 6] and len(history) == 10

    def broken(current, history, message):
        raise RuntimeError("model not loaded")

    kept, problem = send(card(), history, "Box?", broken, turns=3)
    assert kept is history and "model not loaded" in problem
    assert send(card(), history, "   ", engine, turns=3) == (history, None)
    assert "no text" in send(card(), [], "Box?", lambda c, h, m: None, turns=3)[1]


def test_sessions_do_not_share_history() -> None:
    first, _ = send(card(), [], "Box?", stub_respond, turns=3)
    second, _ = send(card("box_old"), [], "Box?", stub_respond, turns=3)
    first_again, _ = send(card(), first, "Why?", stub_respond, turns=3)
    assert len(first) == 2 and len(second) == 2 and len(first_again) == 4
    assert second[1]["content"] == format_answer(CARDS["box_old"])


def test_upload_refuses_anything_but_one_json_object(tmp_path) -> None:
    good, bad, text = (
        tmp_path / "card.json",
        tmp_path / "list.json",
        tmp_path / "x.json",
    )
    good.write_text(json.dumps(card()))
    bad.write_text("[1, 2]")
    text.write_text("not json")
    assert load_upload(str(good)) == (card(), None)
    assert (
        load_upload(str(bad))[0] is None
        and "one JSON object" in load_upload(str(bad))[1]
    )
    assert load_upload(str(text))[0] is None
    assert load_upload(None)[0] is None


def test_handlers_reset_on_card_change_reset_and_error(tmp_path) -> None:
    shown = L.show_card(card(), False)
    assert shown[:5] == (card(), [], [], "", "") and len(shown) == 12
    history, chat, box, problem, banner, policy = L.ask(
        stub_respond, 3, card(), [], "Box?", True
    )
    assert history == chat and box == "" and problem == "" and "BOX" in banner
    assert policy["visible"] is True and "Matches the rule" in policy["value"]
    assert L.clear(card(), False)[:3] == ([], [], "")

    def broken(current, history, message):
        raise RuntimeError("timeout")

    with pytest.warns(UserWarning, match="timeout"):  # shown as a gr.Warning
        kept = L.ask(broken, 3, card(), history, "Why?", False)
    assert kept[0] is history and kept[2] == "Why?" and "timeout" in kept[3]
    wrong = tmp_path / "wrong.json"
    wrong.write_text("[]")
    with pytest.warns(UserWarning, match="one JSON object"):
        refused = L.upload_card(str(wrong), False)
    assert len(refused) == 13 and "one JSON object" in refused[4]


def test_picker_and_app_build() -> None:
    cards = sample_cards()
    synthetic = [name for name in cards if name.startswith("Synthetic example")]
    real = [name for name in cards if name.startswith("Real race")]
    assert len(synthetic) == 5 and len(real) == 8
    assert len(build_app(cards=cards).fns) > 0
    assert "stub" in L.role_text(stub=True) and "stub" not in L.role_text(stub=False)


def test_history_bound_follows_the_evaluator_including_zero() -> None:
    seen = []

    def engine(current, history, message):
        seen.append(len(history))
        return format_answer(current)

    history = []
    for turns in (0, 1, 3):
        for _ in range(3):
            history, _ = send(card(), history, "Box?", engine, turns=turns)
    assert seen == [0, 0, 0, 2, 2, 2, 6, 6, 6]
    assert [L.history_line(n) for n in (0, 1, 3)] == [
        "Engine sees no earlier exchange",
        "Engine sees the last exchange",
        "Engine sees the last 3 exchanges",
    ]
    assert len(build_app(turns=0).fns) > 0


@pytest.mark.parametrize(
    "raw",
    [
        "CALL: BOX\nWHY: The gap covers the loss.",
        "CALL: BOX\nWHY: The gap covers the loss.\n",
        "CALL: BOX\r\nWHY: The gap covers the loss.",
        "CALL: BOX\nWHY: The gap covers the loss.\n\n",
        "CALL: BOX\nWHY:  The gap covers the loss.",
        "CALL: BOX\nWHY: The gap covers the loss. ",
        "CALL: BOX\nWHY: Two\fparts.",
        "CALL: BOX\nWHY: ",
        "CALL: MAYBE\nWHY: x.",
        "call: BOX\nWHY: x.",
        " CALL: BOX\nWHY: x.",
        "CALL: STAY OUT\nWHY: Young tyres.",
        "CALL: NO CALL\nWHY: The pit loss is missing.",
        "Sure!\nCALL: BOX\nWHY: x.",
    ],
)
def test_banner_parser_agrees_with_the_evaluator(raw) -> None:
    ours, theirs = P.parse_answer(raw), parse_response(raw)
    assert (ours is not None) == theirs["strict_format_valid"]
    if ours:
        assert ours[0] == theirs["extracted_call"]


def test_picking_and_uploading_keep_the_picker_honest(tmp_path) -> None:
    picked = L.pick_card({"A card": card()}, "A card", False)
    assert picked[0] == card() and picked[-1]["label"] == L.PICKER
    good = tmp_path / "card.json"
    good.write_text(json.dumps(card()))
    uploaded = L.upload_card(str(good), False)
    assert uploaded[0] == card() and uploaded[-1]["value"] is None
    assert "uploaded file on screen" in uploaded[-1]["label"]
