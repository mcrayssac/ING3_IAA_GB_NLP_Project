import ast
import copy
from pathlib import Path

import pytest

from boxbox.rules import decide
from boxbox.rules.policy2 import TYRE_LOSS_LIMITS, decide_v2

YOUNG, OLD = (float(limit) for limit in TYRE_LOSS_LIMITS["MEDIUM"])
CARD = {
    "schema_version": "2.0",
    "race": {
        "season": 2026,
        "round": 7,
        "event": "Barcelona Grand Prix",
        "completed": True,
    },
    "lap": 30,
    "total_laps": 66,
    "driver_number": "44",
    "as_of_completed_lap": 29,
    "as_of": "2026-06-14T14:00:00+00:00",
    "surface": "DRY",
    "track_status": "GREEN",
    "compound": "MEDIUM",
    "tyre_age_laps": 20,
    "tyre_loss_s_per_lap": OLD,
    "gap_ahead": {
        "state": "KNOWN",
        "seconds": 1.0,
        "driver_number": "16",
        "tyre_loss_s_per_lap": 1.2,
    },
    "gap_behind": {"state": "KNOWN", "seconds": 26.0, "driver_number": "63"},
    "cars_in_pit_window": 0,
    "pit_loss_seconds": 21.0,
    "pit_loss_as_of_completed_lap": 28,
    "penalty_pending_seconds": 0,
    "mandatory_stop_pending": False,
}


def card(**changes) -> dict:
    result = copy.deepcopy(CARD)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def call(**changes) -> str:
    return decide(card(**changes))[0]


def test_decide_sends_2_0_cards_to_policy_2_0() -> None:
    assert decide(CARD) == decide_v2(CARD) == ("BOX", decide_v2(CARD)[1])


def test_worn_tyres_box_whatever_the_traffic() -> None:
    traffic = {"gap_behind": {"seconds": 3.0}, "gap_ahead": {"seconds": 9.0}}
    assert call(tyre_loss_s_per_lap=OLD, **traffic) == "BOX"
    assert call(tyre_loss_s_per_lap=OLD - 0.01, **traffic) == "STAY OUT"
    unknown = {"gap_behind": {"state": "UNKNOWN", "seconds": None}}
    assert call(tyre_loss_s_per_lap=OLD, **unknown) == "BOX"
    assert call(tyre_loss_s_per_lap=None, tyre_age_laps=18, **traffic) == "BOX"
    assert call(tyre_loss_s_per_lap=None, tyre_age_laps=17, **traffic) == "STAY OUT"


def test_tyre_wear_edges() -> None:
    assert call(tyre_loss_s_per_lap=YOUNG - 0.01) == "STAY OUT"
    assert (
        call(tyre_loss_s_per_lap=OLD, gap_ahead={"state": "NONE", "seconds": None})
        == "BOX"
    )
    # inside the window the undercut decides
    assert call(tyre_loss_s_per_lap=YOUNG) == "BOX"
    assert call(tyre_loss_s_per_lap=YOUNG, gap_ahead={"seconds": 1.3}) == "STAY OUT"


def test_the_undercut_reach_is_the_rival_loss_or_two_seconds() -> None:
    inside = {"tyre_loss_s_per_lap": YOUNG}
    assert call(**inside, gap_ahead={"seconds": 1.2}) == "BOX"  # equal reach counts
    unknown_rival = {"seconds": 1.9, "tyre_loss_s_per_lap": None}
    assert call(**inside, gap_ahead=unknown_rival) == "BOX"
    assert (
        call(**inside, gap_ahead={"seconds": 2.1, "tyre_loss_s_per_lap": None})
        == "STAY OUT"
    )
    assert call(**inside, gap_ahead={"state": "UNKNOWN", "seconds": None}) == "NO CALL"
    assert call(**inside, gap_ahead={"state": "NONE", "seconds": None}) == "STAY OUT"


def test_a_safety_car_needs_an_empty_pit_window_and_no_undercut() -> None:
    sc = {
        "track_status": "SC",
        "tyre_loss_s_per_lap": YOUNG,
        "gap_ahead": {"seconds": 9.0},
    }
    assert call(**sc) == "BOX"
    assert call(**sc, cars_in_pit_window=2) == "STAY OUT"
    assert call(**sc, cars_in_pit_window=None) == "NO CALL"
    assert (
        call(track_status="VSC", tyre_loss_s_per_lap=YOUNG, gap_ahead={"seconds": 9.0})
        == "BOX"
    )


def test_tyres_that_do_not_match_the_surface_open_a_stop() -> None:
    assert call(surface="WET", tyre_loss_s_per_lap=0.0) == "BOX"
    assert call(compound="INTERMEDIATE", tyre_loss_s_per_lap=None) == "BOX"
    assert call(surface="WET", compound="INTERMEDIATE") == "STAY OUT"


def test_a_pending_penalty_adds_to_the_pit_cost() -> None:
    window = {"tyre_loss_s_per_lap": YOUNG}  # an undercut, so the rejoin decides
    assert call(**window) == "BOX"  # 26.0 >= 21.0 + 2.0
    assert call(**window, penalty_pending_seconds=5) == "STAY OUT"  # 26.0 < 28.0
    assert call(**window, pit_loss_seconds=None) == "NO CALL"
    assert call(**window, pit_loss_as_of_completed_lap=30) == "NO CALL"


def test_without_a_wear_value_the_age_limits_apply() -> None:
    assert call(tyre_loss_s_per_lap=None, tyre_age_laps=11) == "STAY OUT"  # MEDIUM 12
    assert call(tyre_loss_s_per_lap=None, tyre_age_laps=18) == "BOX"


@pytest.mark.parametrize(
    "changes",
    [
        {"surface": "UNKNOWN"},
        {"track_status": "RED"},
        {"compound": None},
        {"tyre_age_laps": None},
        {"schema_version": "1.0"},
    ],
)
def test_out_of_scope_cards_get_no_call(changes) -> None:
    assert decide_v2(card(**changes))[0] == "NO CALL"


def test_policy_2_0_reads_only_the_card() -> None:
    tree = ast.parse(Path("boxbox/rules/policy2.py").read_text(encoding="utf-8"))
    modules = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert modules <= {"__future__", "decimal", "typing", "decision", ""}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"open", "Path"}


def test_a_pending_mandatory_stop_is_made_under_a_safety_car() -> None:
    sc = {"track_status": "SC", "tyre_loss_s_per_lap": 0.1, "cars_in_pit_window": 6}
    assert call(**sc) == "STAY OUT"
    assert call(**sc, mandatory_stop_pending=True) == "BOX"
    assert call(**{**sc, "track_status": "VSC"}, mandatory_stop_pending=True) == "BOX"
    assert call(tyre_loss_s_per_lap=0.1, mandatory_stop_pending=True) == "STAY OUT"
