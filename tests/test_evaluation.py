"""Deterministic synthetic checks only; no real corpus, model, or reserved-card I/O."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from boxbox.evaluation import (
    PairingError,
    SamplingError,
    bootstrap_compare,
    corpus_case,
    export_review,
    import_review,
    observations,
    pair_outputs,
    parse_response,
    prepare_case,
    quantile,
    review_response_count,
    select_review_cases,
    summarize,
    validate_cases,
    validate_rating,
    version_codes,
)
from boxbox.evaluation.__main__ import calibration_checks, main
from boxbox.evaluation._io import AXES, dumps, loads, read_jsonl, sha256, write_jsonl
from boxbox.evaluation.metrics import all_measures
from boxbox.evaluation.review import PREFIX, _allocate
from boxbox.rules import decide

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = loads((ROOT / "reference/evaluation-fixtures.json").read_text())
CARDS = {r["card_id"]: r["card"] for r in FIXTURE["cards"]}


@pytest.fixture
def cases():
    return [prepare_case(c, CARDS[c["card_id"]]) for c in FIXTURE["cases"]]


def output(case, version, call=None, *, digest="a" * 64):
    label = call or case["reference"]["expected_call"]
    return {
        "response_id": f"syn:response:{version}:{case['case_id']}",
        "case_id": case["case_id"],
        "version_id": version,
        "run_id": "syn:run:unit",
        "cases_sha256": digest,
        "config_sha256": "b" * 64,
        "protocol_id": "boxbox-eval",
        "protocol_version": "1.1.0",
        "input_sha256": case["input_sha256"],
        "status": "ok",
        "raw_response": f"CALL: {label}\nWHY: This is a synthetic example.",
        "error": None,
    }


@pytest.fixture
def toy(cases):
    index = {c["case_id"]: c for c in cases}
    selected, outputs = [], []
    for row in FIXTURE["paired_example"]["rows"]:
        case = index[row["case_id"]]
        selected.append(case)
        for version in ("toy_old", "toy_new"):
            record = output(case, version, row[version]["extracted_call"])
            if row[version]["status"] != "ok":
                record.update(
                    status="generation_error",
                    raw_response=None,
                    error={"code": "synthetic", "message": "Illustrative failure."},
                )
            outputs.append(record)
    return (
        selected,
        outputs,
        pair_outputs(selected, outputs, ["toy_old", "toy_new"], "a" * 64),
    )


def quota_cases(cases):
    """Expand the metadata witness with explicitly synthetic cards and annotations."""
    expanded = []
    for witness in FIXTURE["quota_witness"]["cases"]:
        template = next(
            c
            for c in cases
            if c["attributes"]["card_state"] == witness["card_state"]
            and c["reference"]["policy_call"] == witness["policy_call"]
        )
        case = deepcopy(template)
        case.update(
            case_id=witness["case_id"],
            card_id="syn:card:" + witness["case_id"],
            race_id=witness["race_id"],
            scenario_id=witness["scenario_id"],
            variant_id="syn:variant:" + witness["case_id"],
            split="synthetic",
            turn_index=2 if witness["history_sensitive"] else 1,
            primary_family=witness["primary_family"],
        )
        card = deepcopy(template["card"])
        card["race"]["event"] = "Synthetic quota expansion"
        call, reason = decide(card)
        follow = witness["primary_family"] == "follow_up"
        scope = witness["primary_family"] == "out_of_scope"
        history = (
            [
                {"role": "user", "content": "What is the card's policy call?"},
                {"role": "assistant", "content": f"CALL: {call}\nWHY: {reason}"},
            ]
            if follow
            else []
        )
        case.update(
            history=history,
            full_history=history,
            message="Explain the preceding call."
            if follow
            else "Predict tomorrow's weather."
            if scope
            else "What is the policy call?",
            attributes={
                "card_state": witness["card_state"],
                "follow_up": follow,
                "history_sensitive": follow,
                "out_of_scope": scope,
                "input_issue": None,
            },
            applicability={
                axis: follow
                if axis == "history"
                else scope
                if axis == "scope"
                else True
                for axis in AXES
            },
            reference={
                "oracle": "message_annotation"
                if scope
                else "policy_with_follow_up_annotation"
                if follow
                else "policy",
                "policy_call": call,
                "policy_reason": reason,
                "expected_call": witness["expected_call"],
                "why_reference": "The historical card cannot forecast weather."
                if scope
                else reason,
                "required_evidence": ["current card and declared product limits"],
                "history_requirement": "Explain the preceding policy call."
                if follow
                else None,
                "scope_requirement": "Refuse the weather forecast." if scope else None,
            },
        )
        expanded.append(prepare_case(case, card))
    validate_cases(expanded)
    return expanded


def synthetic_note(case, response, score=1):
    return {
        "response_id": response["response_id"],
        "case_id": case["case_id"],
        "rating_status": "synthetic_expected",
        "annotation_kind": "synthetic_expected",
        "rater_id": None,
        "rated_at": None,
        "applicability": case["applicability"],
        "scores": {
            axis: score if case["applicability"][axis] else "N/A" for axis in AXES
        },
        "reasons": {axis: "Synthetic calibration expectation." for axis in AXES},
    }


@pytest.mark.parametrize(
    "raw,label,strict",
    [
        ("CALL: BOX\nWHY: The 23.0-second gap is supported.", "BOX", True),
        ("CALL: BOX\r\nWHY: A supported paraphrase.\r\n", "BOX", True),
        ("CALL: STAY OUT\nWHY: A reason.\n", "STAY OUT", True),
        ("CALL: NO CALL\nWHY: A limit.\n\n", "NO CALL", False),
        ("CALL: BOX\nWHY: A reason.\nExtra text", "BOX", False),
        ("CALL: BOX\nWHY: ", "BOX", False),
        ("CALL: BOX", "BOX", False),
        ("CALL: BOX\nWHY:  A reason.", "BOX", False),
        ("CALL: BOX\nWHY: A reason.\t", "BOX", False),
        ("\ufeffCALL: BOX\nWHY: A reason.", None, False),
        (" CALL: BOX\nWHY: A reason.", None, False),
        ("CALL: box\nWHY: A reason.", None, False),
        ("CALL: BOX | STAY OUT\nWHY: A reason.", None, False),
        ("Preamble\nCALL: BOX\nWHY: A reason.", None, False),
        ("CALL: BOX\nWHY: One.\rTwo.", "BOX", False),
        ("CALL: BOX\nWHY: One.\u2028Two.", "BOX", False),
        ("", None, False),
    ],
)
def test_strict_parser(raw, label, strict):
    before = raw.encode()
    assert parse_response(raw) == {
        "extracted_call": label,
        "strict_format_valid": strict,
    }
    assert raw.encode() == before
    assert parse_response(raw, "generation_error") == {
        "extracted_call": None,
        "strict_format_valid": False,
    }


def test_all_calibration_expectations_and_policy_pins():
    prepared, result = calibration_checks(FIXTURE)
    assert (result["cards"], result["cases"], result["responses"]) == (27, 35, 55)
    assert len(validate_cases(prepared)) == 35
    assert (
        sha256((ROOT / "boxbox/rules/decision.py").read_bytes())
        == FIXTURE["revision"]["policy_source_sha256"]
    )


def test_decimal_bytes_history_and_json_validation(cases):
    case = deepcopy(cases[0])
    card = deepcopy(case["card"])
    card["gap_behind"]["seconds"] = Decimal("23.00000000000000000000001")
    prepared = prepare_case(case, card)
    assert "23.00000000000000000000001" in prepared["input_json"]
    assert (
        hashlib.sha256(prepared["input_json"].encode()).hexdigest()
        == prepared["input_sha256"]
    )
    with pytest.raises(ValueError, match="stale policy"):
        validate_cases([prepared])
    prepared["reference"]["policy_reason"] = decide(card)[1]
    prepared["reference"]["why_reference"] = decide(card)[1]
    prepared["reference"]["required_evidence"] = ["the exact updated decimal gap"]
    validate_cases([prepared])
    for bad in ('{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}'):
        with pytest.raises(ValueError):
            loads(bad)
    with pytest.raises(ValueError):
        dumps(Decimal("NaN"))
    sensitive = next(c for c in cases if c["attributes"]["history_sensitive"])
    with pytest.raises(ValueError, match="referent"):
        prepare_case(sensitive, sensitive["card"], history_turns=0)


def test_context_family_and_source_adapter(cases):
    scope = next(c for c in cases if c["case_id"] == "syn:case:scope")
    assert scope["reference"]["expected_call"] == "NO CALL"
    assert decide(scope["card"])[0] == "BOX"
    stated = next(c for c in cases if c["case_id"] == "syn:case:stated-gap")
    assert stated["attributes"]["follow_up"] and not stated["applicability"]["history"]
    source = deepcopy(cases[0])
    source["card"]["race"].update(season=2022, round=1)
    source["card_id"] = "2022-01-44-L30"
    source["scenario_id"] = "2022-01-44-L30"
    source["variant_id"] = "original"
    source["attributes"]["follow_up"] = True
    source["primary_family"] = "follow_up"
    source["reference"]["oracle"] = "policy_with_follow_up_annotation"
    first = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier fixed reply"},
    ]
    target = [
        {"role": "user", "content": "Current question"},
        {"role": "assistant", "content": "REFERENCE MUST NOT BECOME INPUT"},
    ]
    item = {
        "id": "synthetic-item",
        "card_id": source["card_id"],
        "card": source["card"],
        "kind": "multi",
        "follow_up": "field",
        "messages": first + target,
    }
    source_record = {
        "card_id": item["card_id"],
        "split": "validation",
        "card": item["card"],
        "provenance": {"source": "synthetic test", "session_key": 123},
    }
    adapted = corpus_case(item, source, "validation", source_record=source_record)
    assert adapted["turn_index"] == 2 and adapted["history"] == first
    assert adapted["message"] == "Current question"
    assert "REFERENCE MUST NOT BECOME INPUT" not in adapted["input_json"]
    validate_cases([adapted], {"validation": ["2022-01"]})
    mock_manifest = {
        "splits": {"validation": ["2022-01"]},
        "races": {"2022-01": {"session_key": 124}},
    }
    with pytest.raises(ValueError, match="session"):
        validate_cases([adapted], mock_manifest)
    with pytest.raises(ValueError, match="accepted split"):
        validate_cases([adapted], {"validation": []})
    incorrect = deepcopy(cases[0])
    incorrect["attributes"]["card_state"] = "usable_incomplete"
    with pytest.raises(ValueError):
        validate_cases([incorrect])


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "unknown",
        "input",
        "ledger",
        "protocol",
        "status",
        "config",
        "response_id",
    ],
)
def test_pairing_defects_are_not_inner_joined(toy, mutation):
    cases, original, _ = toy
    rows = deepcopy(original)
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "unknown":
        rows[0]["case_id"] = "syn:unknown"
    elif mutation == "input":
        rows[0]["input_sha256"] = "c" * 64
    elif mutation == "ledger":
        rows[0]["cases_sha256"] = "c" * 64
    elif mutation == "protocol":
        rows[0]["protocol_version"] = "1.0.0"
    elif mutation == "status":
        rows[0]["status"] = "absent"
    elif mutation == "config":
        rows[0]["config_sha256"] = "c" * 64
    else:
        rows[0]["response_id"] = rows[1]["response_id"]
    with pytest.raises(PairingError):
        pair_outputs(cases, rows, ["toy_old", "toy_new"], "a" * 64)


def test_case_duplicates_scenario_collisions_and_missing_versions(toy):
    cases, rows, _ = toy
    with pytest.raises(PairingError):
        pair_outputs(
            cases + [deepcopy(cases[0])], rows, ["toy_old", "toy_new"], "a" * 64
        )
    damaged = deepcopy(cases)
    damaged[0]["scenario_id"] = damaged[-1]["scenario_id"]
    with pytest.raises(PairingError, match="scenario"):
        pair_outputs(damaged, rows, ["toy_old", "toy_new"], "a" * 64)
    with pytest.raises(PairingError, match="missing output"):
        pair_outputs(cases, rows, ["toy_old", "toy_new", "absent"], "a" * 64)


def test_manual_fractions_and_empty_categories(toy):
    cases, _, paired = toy
    rows = observations(cases, paired)
    old, new = (all_measures(rows[v]) for v in ("toy_old", "toy_new"))
    expected = {
        "call_agreement": (Fraction(2, 6), Fraction(4, 6)),
        "justified_abstention_call_rate": (Fraction(0, 2), Fraction(2, 2)),
        "unjustified_decision_rate": (Fraction(1, 2), Fraction(0, 2)),
        "excessive_refusal_rate": (Fraction(1, 4), Fraction(1, 4)),
        "decision_coverage": (Fraction(4, 6), Fraction(3, 6)),
        "eligible_decision_coverage": (Fraction(3, 4), Fraction(3, 4)),
        "unusable_label_rate": (Fraction(1, 6), Fraction(0, 6)),
        "macro_label_agreement": (Fraction(1, 3), Fraction(2, 3)),
    }
    for name, values in expected.items():
        assert (old["overall/" + name].exact, new["overall/" + name].exact) == values
    for metrics in (old, new):
        assert (
            sum(
                metrics["overall/" + n].exact
                for n in ("justified_abstention_call_rate", "unjustified_decision_rate")
            )
            + metrics["eligibility/Z/unusable_label_rate"].exact
            == 1
        )
        assert (
            sum(
                metrics["overall/" + n].exact
                for n in ("eligible_decision_coverage", "excessive_refusal_rate")
            )
            + metrics["eligibility/D/unusable_label_rate"].exact
            == 1
        )
    report = summarize(rows["toy_old"])
    assert report["confusion"]["NO CALL"]["INVALID"] == 1
    assert report["metrics"]["overall/macro_family_agreement"][
        "missing_components"
    ] == ["family/follow_up/call_agreement", "family/out_of_scope/call_agreement"]
    assert report["metrics"]["family/out_of_scope/call_agreement"]["value"] is None
    assert (
        summarize([])["metrics"]["overall/call_agreement"]["reason"]
        == "empty_population"
    )


def test_ratings_na_pending_and_exact_mean(cases):
    selected = cases[:2]
    outputs = [output(case, v) for case in selected for v in ("v1", "v2")]
    paired = pair_outputs(selected, outputs, ["v1", "v2"], "a" * 64)
    notes = [
        synthetic_note(case, paired[v][case["case_id"]], score=i)
        for i, case in enumerate(selected)
        for v in paired
    ]
    for note in notes:
        with pytest.raises(ValueError, match="synthetic"):
            validate_rating(note, selected[0], allow_synthetic=False)
    observed = observations(
        selected, paired, notes, [c["case_id"] for c in selected], allow_synthetic=True
    )
    summary = summarize(observed["v1"], human=True)
    assert summary["rating_population"] == "synthetic_expected"
    assert summary["axes"]["correctness"]["mean"]["value"] == 0.5
    assert summary["axes"]["history"]["mean"]["reason"] == "no_applicable_scores"
    bad = deepcopy(notes[0])
    bad["scores"]["correctness"] = True
    with pytest.raises(ValueError, match="integer"):
        validate_rating(bad, selected[0], True)
    pending = deepcopy(notes[0])
    pending.update(rating_status="pending")
    pending["scores"] = {
        a: None if selected[0]["applicability"][a] else "N/A" for a in AXES
    }
    obs = observations(selected, paired, [pending], [c["case_id"] for c in selected])
    summary = summarize(obs["v1"], human=True)
    assert summary["axes"]["correctness"]["rated"] == 0
    assert summary["axes"]["correctness"]["missing"] == 2
    assert summary["axes"]["correctness"]["mean"]["reason"] == "no_rated_scores"
    comparison = bootstrap_compare(obs, "v1", "v2", human=True, replications=10)
    assert (
        comparison["metrics"]["overall/human_correctness_mean"]["interval_status"]
        == "incomplete_ratings"
    )
    with pytest.raises(ValueError, match="preselected"):
        observations(selected, paired, notes)


def test_race_draw_manual_multiplicity(toy, monkeypatch):
    cases, _, paired = toy
    observed = observations(cases, paired)
    calls = []

    class Fixed:
        def __init__(self, seed):
            assert seed == 2026
            self.draw = iter((0, 0, 2))

        def randrange(self, n):
            calls.append(n)
            return next(self.draw)

    monkeypatch.setattr("boxbox.evaluation.statistics.random.Random", Fixed)
    result = bootstrap_compare(observed, "toy_old", "toy_new", replications=1)
    metric = result["metrics"]["overall/call_agreement"]
    assert calls == [3, 3, 3]
    assert metric["difference_interval"] == pytest.approx([Fraction(1, 3)] * 2)


def test_bootstrap_identical_single_and_reproducible(toy):
    cases, _, paired = toy
    observed = observations(cases, paired)
    first = bootstrap_compare(observed, "toy_old", "toy_new", replications=100)
    second = bootstrap_compare(observed, "toy_old", "toy_new", replications=100)
    assert first == second
    assert first["metrics"]["overall/decision_coverage"]["gain"] is None
    assert first["metrics"]["overall/call_agreement"]["interval_status"] == "few_races"
    identical = bootstrap_compare(observed, "toy_old", "toy_old", replications=30)
    for metric in identical["metrics"].values():
        if metric["difference"] is not None:
            assert metric["difference"] == 0
            if metric["difference_interval"] is not None:
                assert metric["difference_interval"] == [0, 0]
    single = {v: rows[:2] for v, rows in observed.items()}
    report = bootstrap_compare(single, "toy_old", "toy_new", replications=20)
    assert (
        report["metrics"]["overall/call_agreement"]["interval_status"] == "single_race"
    )
    assert report["metrics"]["overall/call_agreement"]["difference_interval"] is None
    empty = bootstrap_compare(
        {v: [] for v in paired}, "toy_old", "toy_new", replications=5
    )
    assert (
        empty["metrics"]["overall/call_agreement"]["interval_status"]
        == "empty_population"
    )
    assert quantile([0, 10, 20, 30], 0.25) == 7.5


def test_sparse_denominators_and_single_contributing_component(toy):
    cases, _, paired = toy
    observed = observations(cases, paired)
    expanded = {}
    for version, rows in observed.items():
        more = deepcopy(rows)
        # Two extra complete, non-abstention races dilute draws containing the two Z races.
        for n in (4, 5):
            row = deepcopy(rows[0])
            row.update(
                case_id=f"syn:extra:{n}",
                race_id=f"syn:race:{n}",
                scenario_id=f"syn:scenario:{n}",
            )
            more.append(row)
        expanded[version] = more
    result = bootstrap_compare(expanded, "toy_old", "toy_new", replications=1000)
    abstention = result["metrics"]["overall/justified_abstention_call_rate"]
    assert abstention["interval_status"] == "insufficient_valid_replicates"
    assert abstention["valid_replications"] < 950
    # A category contributed by one race stays single_race even with other races in U.
    altered = deepcopy(observed)
    for rows in altered.values():
        for row in rows:
            if row["race_id"] != "syn:race:1":
                row["reference"]["expected_call"] = "STAY OUT"
    one = bootstrap_compare(altered, "toy_old", "toy_new", replications=40)
    assert (
        one["metrics"]["overall/justified_abstention_call_rate"]["interval_status"]
        == "single_race"
    )
    assert (
        one["metrics"]["overall/macro_label_agreement"]["interval_status"]
        == "single_race"
    )


def test_quota_selection_codes_and_failure_diagnostics():
    witness = FIXTURE["quota_witness"]["cases"]
    selection = select_review_cases(witness)
    shuffled = deepcopy(witness)
    random.Random(11).shuffle(shuffled)
    assert select_review_cases(shuffled) == selection
    assert selection["targets"] == 40
    assert set(selection["family_counts"].values()) == {8}
    assert (
        len(selection["race_counts"]) == 5
        and max(selection["race_counts"].values()) == 8
    )
    assert (
        len(selection["scenario_counts"]) == 20
        and max(selection["scenario_counts"].values()) == 2
    )
    assert review_response_count(["baseline", "A", "B"]) == 120
    with pytest.raises(ValueError, match="explicit"):
        review_response_count(["baseline", "A"])
    assert review_response_count(["baseline", "A"], "synthetic:drop-decision") == 80
    assert version_codes(["baseline", "A", "B"]) == version_codes(
        ["B", "baseline", "A"]
    )
    expected_order = sorted(
        ["baseline", "A", "B"],
        key=lambda v: hashlib.sha256((PREFIX + "mask|" + v).encode()).hexdigest(),
    )
    assert [version_codes(expected_order)[v] for v in expected_order] == [
        "V01",
        "V02",
        "V03",
    ]
    with pytest.raises(SamplingError) as error:
        select_review_cases(witness[:-1])
    assert error.value.diagnostics["required_slots"] == 40
    with pytest.raises(ValueError, match="duplicate"):
        select_review_cases(witness + [witness[0]])


def test_backtracking_preserves_first_complete_solution():
    ids = sorted(
        ["syn:trap:1", "syn:trap:2"],
        key=lambda c: hashlib.sha256((PREFIX + "sample|" + c).encode()).hexdigest(),
    )
    base = {
        "primary_family": "complete",
        "card_state": "complete",
        "history_sensitive": False,
    }
    pool = [
        {
            **base,
            "case_id": ids[0],
            "race_id": "syn:r1",
            "scenario_id": "syn:s1",
            "expected_call": "BOX",
            "policy_call": "BOX",
        },
        {
            **base,
            "case_id": ids[1],
            "race_id": "syn:r2",
            "scenario_id": "syn:s2",
            "expected_call": "STAY OUT",
            "policy_call": "STAY OUT",
        },
    ]
    result = _allocate(
        pool,
        [{"family": "complete"}, {"family": "complete", "expected_call": "BOX"}],
        1,
        1,
    )
    assert [r["expected_call"] for r in result] == ["STAY OUT", "BOX"]


def test_full_review_export_round_trip_and_integrity(cases, tmp_path):
    full = quota_cases(cases)
    chosen = select_review_cases(full)["selected_case_ids"]
    versions = ["baseline", "A", "B"]
    outputs = [output(case, version) for case in full for version in versions]
    paired = pair_outputs(full, outputs, versions, "a" * 64)
    folder = tmp_path / "review"
    report = export_review(folder, full, paired, chosen, illustrative=True)
    assert (report["targets"], report["responses"]) == (40, 120)
    lookup = loads((folder / "response-lookup.json").read_text())
    notes = import_review(folder / "review.csv", lookup, full, illustrative=True)
    assert len(notes) == 120 and all(n["rating_status"] == "pending" for n in notes)
    with (folder / "review.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
        assert (
            not {"version_id", "run_id", "response_id", "config_sha256"}
            & rows[0].keys()
        )
    second = tmp_path / "again"
    export_review(second, full, paired, list(reversed(chosen)), illustrative=True)
    assert (folder / "review.csv").read_bytes() == (second / "review.csv").read_bytes()
    assert (folder / "version-key.json").exists()
    with pytest.raises(FileExistsError):
        export_review(folder, full, paired, chosen, illustrative=True)
    rows[0]["raw_response"] = "altered"
    with (folder / "review.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="altered"):
        import_review(folder / "review.csv", lookup, full, illustrative=True)


def test_initial_notes_remain_separate_from_adjudication(cases, tmp_path):
    case = cases[0]
    rows = [output(case, "v1")]
    paired = pair_outputs([case], rows, ["v1"], "a" * 64)
    note = synthetic_note(case, rows[0], 1)
    note["adjudication"] = {
        "synthetic_note": "separate proposed resolution",
        "scores": {"correctness": 2},
    }
    export_review(
        tmp_path / "notes", [case], paired, [case["case_id"]], [note], illustrative=True
    )
    folder = tmp_path / "notes"
    restored = import_review(
        folder / "review.csv",
        loads((folder / "response-lookup.json").read_text()),
        [case],
        illustrative=True,
    )
    assert restored[0]["scores"]["correctness"] == 1
    assert restored[0]["adjudication"]["scores"]["correctness"] == 2
    adjudicated = deepcopy(note)
    adjudicated["rating_phase"] = "adjudicated"
    adjudicated["scores"]["correctness"] = 2
    export_review(
        tmp_path / "adjudicated",
        [case],
        paired,
        [case["case_id"]],
        [note, adjudicated],
        illustrative=True,
        rating_phase="adjudicated",
    )
    returned = import_review(
        tmp_path / "adjudicated/review.csv",
        loads((tmp_path / "adjudicated/response-lookup.json").read_text()),
        [case],
        illustrative=True,
    )
    assert returned[0]["rating_phase"] == "adjudicated"
    assert returned[0]["scores"]["correctness"] == 2
    assert restored[0]["scores"]["correctness"] == 1


def test_final_gate_precedes_case_reads(tmp_path, capsys):
    missing = tmp_path / "must-not-open.jsonl"
    code = main(
        [
            "score",
            "--cases",
            str(missing),
            "--outputs",
            str(missing),
            "--versions",
            "baseline",
            "A",
            "--split",
            "final",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
    diagnostic = json.loads(capsys.readouterr().err)
    assert "final_split_closed" in diagnostic["message"]
    assert not (tmp_path / "out").exists()


def test_human_bootstrap_uses_selected_races_only(toy):
    cases, _, paired = toy
    observed = observations(cases, paired, [], [c["case_id"] for c in cases[:2]])
    human = bootstrap_compare(
        observed, "toy_old", "toy_new", human=True, replications=5
    )
    automatic = bootstrap_compare(observed, "toy_old", "toy_new", replications=5)
    assert human["race_order"] == ["syn:race:1"]
    assert len(automatic["race_order"]) == 3
    assert human["analysis_population"] == "selected_review_targets"


def test_empty_output_rating_anchor_is_validated(cases):
    case = cases[0]
    response = output(case, "synthetic")
    response["raw_response"] = ""
    note = synthetic_note(case, response, 2)
    with pytest.raises(ValueError, match="applicable zeros"):
        validate_rating(note, case, True, response=response)
    zero = synthetic_note(case, response, 0)
    validate_rating(zero, case, True, response=response)


def test_cli_metadata_selection_and_history_bound(cases, tmp_path, capsys):
    full = quota_cases(cases)
    source = tmp_path / "synthetic-ledger.jsonl"
    digest = write_jsonl(source, full)
    folder = tmp_path / "sampled"
    assert main(["sample", "--cases", str(source), "--output", str(folder)]) == 0
    selection = loads((folder / "selection.json").read_text())
    assert selection["targets"] == 40 and selection["cases_sha256"] == digest
    assert (folder / "cases.jsonl").read_bytes() == source.read_bytes()
    # A common context configuration cannot silently change saved target inputs.
    configuration = tmp_path / "history.toml"
    configuration.write_text("history_turns = 0\n")
    code = main(
        [
            "score",
            "--config",
            str(configuration),
            "--cases",
            str(source),
            "--outputs",
            str(tmp_path / "must-not-open.jsonl"),
            "--versions",
            "baseline",
            "A",
            "--output",
            str(tmp_path / "wrong-history"),
        ]
    )
    assert code == 2 and "common history bound" in capsys.readouterr().err


def test_eighty_response_review_requires_explicit_drop(cases, tmp_path):
    full = quota_cases(cases)
    selected = select_review_cases(full)["selected_case_ids"]
    outputs = [output(case, version) for case in full for version in ("baseline", "A")]
    paired = pair_outputs(full, outputs, ["baseline", "A"], "a" * 64)
    with pytest.raises(ValueError, match="explicit"):
        export_review(tmp_path / "unapproved", full, paired, selected)
    report = export_review(
        tmp_path / "approved",
        full,
        paired,
        selected,
        drop_b_record="synthetic:test-decision-only",
    )
    assert report["responses"] == 80
    assert not (tmp_path / "unapproved").exists()


def test_cli_worked_example_and_generic_score(tmp_path):
    folder = tmp_path / "worked"
    command = [sys.executable, "-m", "boxbox.evaluation"]
    run = subprocess.run(
        command + ["fixtures", "--output", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    comparison = loads((folder / "comparisons.json").read_text())[0]
    assert comparison["settings"]["replications"] == 10000
    assert float(
        comparison["metrics"]["overall/call_agreement"]["difference"]
    ) == pytest.approx(1 / 3)
    assert loads((folder / "review/manifest.json").read_text())["responses"] == 12
    manifest = loads((folder / "manifest.json").read_text())
    assert not manifest["model_executed"]
    assert manifest["extra"]["evaluation"]["acceptance_record"] is None
    assert manifest["extra"]["evaluation"]["protocol_status"] == "proposed"
    assert (folder / "evaluation-protocol.md").read_bytes() == (
        ROOT / "docs/evaluation-protocol.md"
    ).read_bytes()
    result = tmp_path / "scored"
    score = subprocess.run(
        command
        + [
            "score",
            "--cases",
            str(folder / "cases.jsonl"),
            "--outputs",
            str(folder / "outputs.jsonl"),
            "--versions",
            "toy_old",
            "toy_new",
            "--output",
            str(result),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert score.returncode == 0, score.stderr
    assert loads((result / "metrics.json").read_text()) == loads(
        (folder / "metrics.json").read_text()
    )
    rerun = subprocess.run(
        command + ["fixtures", "--output", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rerun.returncode == 2 and "File exists" in rerun.stderr
    broken, digest = read_jsonl(folder / "outputs.jsonl")
    assert digest == manifest["extra"]["evaluation"]["outputs_sha256"]
    broken.pop()
    path = tmp_path / "broken.jsonl"
    write_jsonl(path, broken)
    fail = subprocess.run(
        command
        + [
            "score",
            "--cases",
            str(folder / "cases.jsonl"),
            "--outputs",
            str(path),
            "--versions",
            "toy_old",
            "toy_new",
            "--output",
            str(tmp_path / "invalid"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert fail.returncode == 2 and "missing output" in fail.stderr
