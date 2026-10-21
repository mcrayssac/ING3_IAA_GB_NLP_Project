"""OpenJev request, references, threshold rule and calibration of task 3.4, with no server."""

from __future__ import annotations

import io
import json
import urllib.error
from copy import deepcopy
from pathlib import Path

import pytest

from boxbox.model import openjev
from boxbox.model.openjev import (
    OpenJevError,
    ask,
    build_request,
    load_settings,
    policy_instructions,
    references,
)
from scripts import openjev_baseline
from scripts.openjev_baseline import (
    averaged,
    calibration,
    check_version,
    choose_tau,
    decided,
    loro,
    outputs_at,
    peak_memory,
    shuffled_order,
)

CARD = {
    "as_of_completed_lap": 30,
    "compound": "MEDIUM",
    "driver_number": "4",
    "gap_ahead": {"driver_number": "27", "seconds": 12.9, "state": "KNOWN"},
    "gap_behind": {"seconds": None, "state": "NONE"},
    "lap": 31,
    "pit_loss_as_of_completed_lap": 30,
    "pit_loss_seconds": 22.8,
    "race": {
        "completed": True,
        "event": "Bahrain Grand Prix",
        "round": 1,
        "season": 2023,
    },
    "reference_lap_seconds": 99.2,
    "schema_version": "1.0",
    "surface": "DRY",
    "total_laps": 57,
    "track_status": "GREEN",
    "tyre_age_laps": 3,
}
CALLS = ["BOX", "STAY OUT", "NO CALL"]


def case(changes: dict | None = None, expected="STAY OUT", out_of_scope=False) -> dict:
    card = deepcopy(CARD) | (changes or {})
    inputs = {"card": card, "history": [], "message": "Which call fits car 4?"}
    return {
        "case_id": "c1",
        "input_sha256": "0" * 64,
        "input_json": json.dumps(inputs),
        "reference": {"expected_call": expected},
        "attributes": {"out_of_scope": out_of_scope},
    }


def answered(choice: str, probabilities: dict, case_id: str = "c1") -> dict:
    call = {"choice": choice, "probabilities": probabilities}
    return {"case_id": case_id, "status": "ok", "answers": {"call": call}}


def test_the_policy_loses_only_its_answer_format_paragraph():
    prompt = "Apply the policy.\n\nReturn exactly two lines:\nCALL: BOX\nWHY: one"
    assert policy_instructions(prompt) == "Apply the policy."
    with pytest.raises(ValueError, match="answer-format"):
        policy_instructions("Apply the policy.")


def test_the_request_holds_the_engine_card_text_and_the_conversation():
    settings = load_settings()
    inputs = {
        "card": CARD,
        "history": [
            {"role": "user", "content": "Call?"},
            {"role": "assistant", "content": "CALL: STAY OUT"},
        ],
        "message": "Why?",
    }
    request = build_request(settings, "Policy.", inputs)
    state = request["state"]
    assert state.startswith("Policy.\n\nCurrent race card (authoritative JSON):\n{")
    assert state.endswith(
        "Conversation (latest message last):\n"
        "User: Call?\nAssistant: CALL: STAY OUT\nUser: Why?"
    )
    assert list(request["questions"]) == list(settings["questions"])
    assert list(request["questions"]["call"]["criteria"]) == CALLS
    assert request["questions"]["call"]["criteria"]["BOX"] is None
    assert "criteria" not in request["questions"]["in_scope"]


def test_a_shuffled_request_reorders_the_call_options_only():
    settings, inputs = load_settings(), json.loads(case()["input_json"])
    order = ["NO CALL", "BOX", "STAY OUT"]
    request = build_request(settings, "Policy.", inputs, order, diagnostics=False)
    assert list(request["questions"]) == ["call"]
    assert list(request["questions"]["call"]["criteria"]) == order
    with pytest.raises(ValueError, match="reordering"):
        build_request(settings, "Policy.", inputs, ["BOX", "STAY OUT"])


def test_references_name_the_field_the_rule_lacks():
    complete = references(case())
    assert complete == {
        "call": "STAY OUT",
        "in_scope": True,
        "required_known": True,
        "missing_field": "none",
    }
    behind = {"driver_number": "16", "seconds": 9.0, "state": "KNOWN"}
    old_tyres = {"tyre_age_laps": 20, "gap_behind": behind}
    blocked = references(case(old_tyres | {"pit_loss_seconds": None}, "NO CALL"))
    assert blocked["required_known"] is False
    assert blocked["missing_field"] == "pit_loss_seconds"
    # young tyres decide before the pit loss is read: a usable incomplete card
    usable = references(case({"pit_loss_seconds": None}))
    assert (usable["required_known"], usable["missing_field"]) == (True, "none")
    safety_car = references(case({"track_status": "SC"}, "NO CALL"))
    assert safety_car["missing_field"] == "track_status"
    assert references(case(out_of_scope=True, expected="NO CALL"))["in_scope"] is False
    with pytest.raises(ValueError, match="no diagnostic field"):
        references(case({"surface": "WET"}, "NO CALL"))


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_ask_refuses_a_reply_without_every_answer(monkeypatch):
    request = build_request(
        load_settings(), "Policy.", json.loads(case()["input_json"])
    )
    full = {
        "call": {"choice": "BOX", "probabilities": {}},
        "in_scope": {"noul": 0.9},
        "required_known": {"noul": 0.2},
        "missing_field": {"choice": "none", "probabilities": {}},
    }

    def reply(answers):
        body = json.dumps({"answers": answers}).encode()
        return lambda *args, **kwargs: Reply(body)

    monkeypatch.setattr(openjev.urllib.request, "urlopen", reply(full))
    assert ask("http://127.0.0.1:3000/v1", request, 5)["answers"] == full
    partial = {k: v for k, v in full.items() if k != "required_known"}
    monkeypatch.setattr(openjev.urllib.request, "urlopen", reply(partial))
    with pytest.raises(OpenJevError) as error:
        ask("http://127.0.0.1:3000/v1", request, 5)
    assert error.value.code == "incomplete_answer"


def test_ask_keeps_http_and_connection_failures_as_errors(monkeypatch):
    request = build_request(
        load_settings(), "Policy.", json.loads(case()["input_json"])
    )

    def refused(*args, **kwargs):
        raise urllib.error.HTTPError("url", 422, "bad", {}, io.BytesIO(b"bad question"))

    def dropped(*args, **kwargs):
        raise ConnectionResetError("closed without a reply")

    for failure, code in ((refused, "http_422"), (dropped, "request_failed")):
        monkeypatch.setattr(openjev.urllib.request, "urlopen", failure)
        with pytest.raises(OpenJevError) as error:
            ask("http://127.0.0.1:3000/v1", request, 5)
        assert error.value.code == code


def test_the_threshold_rule_answers_only_above_tau():
    box = {
        "choice": "BOX",
        "probabilities": {"BOX": 0.6, "STAY OUT": 0.3, "NO CALL": 0.1},
    }
    assert decided(box, None) == "BOX"
    assert decided(box, 0.6) == "BOX"  # reaching tau is enough
    assert decided(box, 0.61) == "NO CALL"
    refusal = {"choice": "NO CALL", "probabilities": {"BOX": 0.3, "NO CALL": 0.4}}
    assert decided(refusal, 0.0) == "NO CALL"


def test_tau_ties_go_to_fewer_unjustified_decisions_then_the_lower_tau():
    def point(tau, agreement, unjustified):
        return {
            "tau": tau,
            "call_agreement": agreement,
            "unjustified_decision_rate": unjustified,
        }

    curve = [
        point(0.2, 0.7, 0.5),
        point(0.5, 0.8, 0.4),
        point(0.6, 0.8, 0.3),
        point(0.7, 0.8, 0.3),
    ]
    assert choose_tau(curve)["tau"] == 0.6


def test_outputs_keep_failed_requests_as_generation_errors():
    failed = {"case_id": "c2", "status": "request_error", "answers": None}
    failed["error"] = {"code": "request_failed", "message": "closed"}
    rows = [answered("STAY OUT", {"STAY OUT": 0.7}), failed]
    cases = [case(), case() | {"case_id": "c2"}]
    out = outputs_at(rows, cases, None, "run", "a" * 64, "b" * 64)
    assert [o["raw_response"] for o in out] == ["CALL: STAY OUT", None]
    assert [o["status"] for o in out] == ["ok", "generation_error"]
    assert out[1]["error"]["code"] == "request_failed"
    assert out[0]["version_id"] == "openjev-argmax"
    with pytest.raises(ValueError, match="case order"):
        outputs_at(rows[::-1], cases, 0.5, "run", "a" * 64, "b" * 64)


def test_brier_and_ece_on_two_answers():
    cases = [case(expected="BOX"), case(expected="STAY OUT") | {"case_id": "c2"}]
    answers = [
        answered("BOX", {"BOX": 0.8, "STAY OUT": 0.1, "NO CALL": 0.1}),
        answered("BOX", {"BOX": 0.6, "STAY OUT": 0.3, "NO CALL": 0.1}, "c2"),
        {"case_id": "c3", "status": "request_error", "answers": None},
    ]
    result = calibration(answers, cases)
    assert result["targets"] == 2 and result["excluded_errors"] == 1
    assert result["brier"] == pytest.approx((0.06 + 0.86) / 2)
    # bin 0.8: confidence 0.8, accuracy 1; bin 0.6: confidence 0.6, accuracy 0
    assert result["ece"] == pytest.approx(0.5 * 0.2 + 0.5 * 0.6)
    assert [b["count"] for b in result["bins"]] == [0, 0, 0, 0, 0, 0, 1, 0, 1, 0]


def test_shuffled_orders_are_fixed_and_never_the_original():
    orders = [shuffled_order(CALLS, f"case-{i}", 2026) for i in range(200)]
    assert CALLS not in orders
    assert all(sorted(o) == sorted(CALLS) for o in orders)
    assert orders == [shuffled_order(CALLS, f"case-{i}", 2026) for i in range(200)]
    assert len({tuple(o) for o in orders}) == 5


def test_server_checks_read_the_version_and_the_time_report():
    settings = load_settings()
    version = {
        "T": 1.07,
        "noul_t": 1.074766,
        "noul_bias": 0.0,
        "shim_sha256": settings["helper"]["sha256"]["helper/shim.py"],
        "flags": {"targeted": True, "perms": 1, "instr_style": "pyrepr"},
    }
    check_version(version, settings)
    with pytest.raises(ValueError, match="pinned"):
        check_version(version | {"T": 1.1}, settings)
    report = (
        "  6906871808  maximum resident set size\n 10784363896  peak memory footprint\n"
    )
    assert peak_memory(report) == {"peak_memory_gb": 10.78, "max_resident_gb": 6.91}
    assert peak_memory("") == {"peak_memory_gb": None, "max_resident_gb": None}


def test_the_upgrade_request_asks_the_call_in_three_described_orders():
    settings = load_settings(Path("configs/openjev-upgrade.toml"))
    request = build_request(settings, "Policy.", json.loads(case()["input_json"]))
    questions = request["questions"]
    assert list(questions) == ["call", "call_1", "call_2"]
    orders = [list(q["criteria"]) for q in questions.values()]
    assert orders == [CALLS, CALLS[1:] + CALLS[:1], CALLS[2:] + CALLS[:2]]
    described = questions["call"]["criteria"]
    assert all(isinstance(text, str) and text for text in described.values())
    assert all(q["criteria"] == described for q in questions.values())  # same pairs


def test_the_averaged_call_is_the_argmax_of_the_mean():
    def call(box, stay, none):
        p = {"BOX": box, "STAY OUT": stay, "NO CALL": none}
        return {"choice": max(p, key=p.get), "probabilities": p}

    answers = {
        "call": call(0.5, 0.4, 0.1),
        "call_1": call(0.2, 0.7, 0.1),
        "call_2": call(0.5, 0.2, 0.3),
    }
    result = averaged(answers)
    assert result["call"]["choice"] == "STAY OUT"  # two of the three orders pick BOX
    assert result["call"]["probabilities"]["STAY OUT"] == pytest.approx(1.3 / 3)
    assert result["call_0"] == answers["call"]
    single = {"call": call(0.5, 0.4, 0.1)}
    assert averaged(single) is single
    tie = {"call": call(0.45, 0.1, 0.45), "call_1": call(0.45, 0.1, 0.45)}
    assert averaged(tie)["call"]["choice"] == "NO CALL"  # a tie abstains
    # 0.4332, 0.4048 and 0.812 average to 0.55 exactly, which reaches tau 0.55
    edge = {"call": call(0.4332, 0.5, 0.0668), "call_1": call(0.4048, 0.5, 0.0952)}
    edge["call_2"] = call(0.812, 0.1, 0.088)
    assert decided(averaged(edge)["call"], 0.55) == "BOX"


def test_loro_chooses_each_tau_without_its_own_race(monkeypatch):
    seen = []

    def fake_measures(cases, rows, cases_hash, splits):
        seen.append({c["race_id"] for c in cases})
        expected = {c["case_id"]: c["reference"]["expected_call"] for c in cases}
        said = {r["case_id"]: r["raw_response"].removeprefix("CALL: ") for r in rows}
        z = [cid for cid, call in expected.items() if call == "NO CALL"]
        values = {
            "call_agreement": sum(said[c] == e for c, e in expected.items())
            / len(cases),
            "unjustified_decision_rate": sum(said[c] != "NO CALL" for c in z) / len(z)
            if z
            else 0.0,
            "excessive_refusal_rate": 0.0,
            "decision_coverage": 0.0,
        }
        return {"metrics": {f"overall/{k}": {"value": v} for k, v in values.items()}}

    monkeypatch.setattr(openjev_baseline, "measures", fake_measures)
    cases = [
        case(expected="BOX") | {"case_id": "c1", "race_id": "r1"},
        case(expected="NO CALL") | {"case_id": "c2", "race_id": "r2"},
    ]
    probabilities = {"BOX": 0.7, "STAY OUT": 0.2, "NO CALL": 0.1}
    answers = [
        answered("BOX", probabilities, "c1"),
        answered("BOX", {"BOX": 0.5, "STAY OUT": 0.3, "NO CALL": 0.2}, "c2"),
    ]
    result = loro(answers, cases, "run", "a" * 64, "b" * 64, None)
    # r1 held out: tau from r2 alone, where only tau above 0.5 refuses c2
    # r2 held out: tau from r1 alone, where every tau up to 0.7 is right
    assert result["taus"] == {"r1": 0.51, "r2": 0.0}
    assert result["call_agreement"] == 0.5
    assert all(races == {"r2"} for races in seen[:101])
    assert all(races == {"r1"} for races in seen[101:202])
    assert seen[202] == {"r1", "r2"}
