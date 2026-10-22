"""4.4 analysis on a synthetic sealed final run: checks, contrasts and refusals."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_evaluation import cases, toy  # noqa: F401 - protocol calibration fixtures
from test_final_cases import cards  # noqa: F401 - synthetic final-race fixture
from test_final_scoring import fake_stack, prepared  # noqa: F401 - sealed-run fixtures

from boxbox.evaluation._io import dumps, loads, read_jsonl, sha256
from scripts import final_analysis as analysis
from scripts import final_scoring as runner


@pytest.fixture
def sealed(prepared, monkeypatch, tmp_path):  # noqa: F811 - imported fixture
    fake_stack(monkeypatch)
    runner.generate(prepared)
    runner.seal(prepared)
    monkeypatch.setattr(analysis, "FINAL_CASES", runner.FINAL / "cases.jsonl")
    targets, cases_hash = read_jsonl(prepared / "cases.jsonl")
    outputs, outputs_hash = read_jsonl(prepared / "outputs.jsonl")
    paired = analysis.pair_outputs(
        targets, outputs, analysis.VERSIONS, cases_hash, analysis.load_splits()
    )
    rows = analysis.observations(targets, paired)
    results = tmp_path / "final-scoring-results.json"
    results.write_text(
        dumps(
            {
                "run_directory": prepared.name,
                "complete_sha256": sha256((prepared / "complete.json").read_bytes()),
                "cases_sha256": cases_hash,
                "outputs_sha256": outputs_hash,
                "attempts_sha256": sha256((prepared / "attempts.jsonl").read_bytes()),
                "freeze_sha256": sha256(analysis.FREEZE.read_bytes()),
                "evaluator_summaries": {
                    v: analysis.summarize(rows[v]) for v in analysis.VERSIONS
                },
            }
        )
    )
    monkeypatch.setattr(analysis, "RESULTS_4_2", results)
    return prepared, results


def test_contrasts_transitions_and_identities(sealed, tmp_path):
    run, _ = sealed
    folder = analysis.run(run, replications=20, runs_dir=tmp_path / "out")
    result = loads((folder / "analysis.json").read_text())
    roles = {k: v["contrast_role"] for k, v in result["contrasts"].items()}
    assert roles == {
        "A_minus_baseline": "principal",
        "B_minus_A": "principal",
        "B_minus_baseline": "exploratory",
    }
    for contrast in result["contrasts"].values():
        assert sum(contrast["transitions"]["counts"].values()) == 200
        assert contrast["settings"]["replications"] == 20
    for version in ("baseline", "A", "B"):
        z, d = result["identities"][version]["Z"], result["identities"][version]["D"]
        assert z[0] == z[1] and d[0] == d[1] and z[1] + d[1] == 200
        assert len(result["response_ids"][version]) == 200
    manifest = loads((folder / "manifest.json").read_text())
    assert manifest["protocol_settings"] is False  # 20 draws are for tests only
    evidence = loads((folder / "evidence.json").read_text())
    assert evidence == analysis.compact(result)
    assert evidence["response_ids"] == result["response_ids"]
    assert evidence["provenance"] == manifest["provenance"]
    assert manifest["analysis_sha256"] == sha256(
        (folder / "analysis.json").read_bytes()
    )
    assert manifest["evidence_sha256"] == sha256(
        (folder / "evidence.json").read_bytes()
    )
    assert evidence["analysis_script_sha256"] == sha256(
        Path(analysis.__file__).read_bytes()
    )
    recorded = loads(analysis.RESULTS_4_2.read_text())
    for key in (
        "complete_sha256",
        "cases_sha256",
        "outputs_sha256",
        "attempts_sha256",
        "freeze_sha256",
    ):
        assert evidence["provenance"][key] == recorded[key]
    assert evidence["provenance"]["results_4_2_sha256"] == sha256(
        analysis.RESULTS_4_2.read_bytes()
    )
    for name, contrast in result["contrasts"].items():
        compact = evidence["contrasts"][name]
        assert compact["race_order"] == contrast["race_order"]
        assert compact["scenario_sizes"] == contrast["scenario_sizes"]
        for key, metric in compact["metrics"].items():
            original = contrast["metrics"][key]
            assert metric["component_races"] == original["component_races"]
            assert metric["conditional_on_valid_replications"] == (
                metric["invalid_replications"] > 0
            )
            assert metric["valid_draws"] + metric["invalid_replications"] == 20
        assert compact["metrics"]["overall/macro_label_agreement"]["component_races"]
    undefined = evidence["summaries"]["A"]["metrics"][
        "family/complete/unjustified_decision_rate"
    ]
    assert undefined["value"] is None
    assert undefined["reason"] == "empty_population"
    with pytest.raises(FileExistsError):
        analysis.run(run, replications=20, runs_dir=tmp_path / "out")


def test_changed_output_is_refused(sealed):
    run, results = sealed
    outputs = run / "outputs.jsonl"
    outputs.write_text(outputs.read_text() + "\n")
    with pytest.raises(ValueError, match="differ from its completion record"):
        analysis.check_run(run, results)


def test_other_completion_record_is_refused(sealed):
    run, results = sealed
    recorded = loads(results.read_text())
    recorded["complete_sha256"] = "0" * 64
    results.write_text(dumps(recorded))
    with pytest.raises(ValueError, match="not the record 4.2 published"):
        analysis.check_run(run, results)


def test_summaries_must_match_those_4_2_recorded(sealed):
    run, results = sealed
    checked = analysis.check_run(run, results)
    checked["recorded"]["evaluator_summaries"] = {"baseline": {}}
    with pytest.raises(ValueError, match="differ from those 4.2 recorded"):
        analysis.analyse(checked, replications=20)


@pytest.mark.parametrize("summaries", [None, {}, {"baseline": {}}])
def test_missing_summaries_refused_before_reading_ledgers(
    sealed, monkeypatch, summaries
):
    run, results = sealed
    recorded = loads(results.read_text())
    if summaries is None:
        recorded.pop("evaluator_summaries")
    else:
        recorded["evaluator_summaries"] = summaries
    results.write_text(dumps(recorded))

    def unexpected_read(*args):
        pytest.fail("a final ledger was read before checking the 4.2 summaries")

    monkeypatch.setattr(analysis, "read_jsonl", unexpected_read)
    with pytest.raises(ValueError, match="must record evaluator_summaries"):
        analysis.check_run(run, results)


@pytest.mark.parametrize(
    "key", ["cases_sha256", "outputs_sha256", "attempts_sha256", "freeze_sha256"]
)
def test_published_input_hash_mismatch_refused(sealed, key):
    run, results = sealed
    recorded = loads(results.read_text())
    recorded[key] = "0" * 64
    results.write_text(dumps(recorded))
    with pytest.raises(ValueError, match="input hashes differ"):
        analysis.check_run(run, results)


def test_freeze_gate_precedes_all_input_reads(monkeypatch, tmp_path):
    def closed():
        raise ValueError("freeze does not hold")

    monkeypatch.setattr(analysis, "gate", closed)
    with pytest.raises(ValueError, match="freeze does not hold"):
        analysis.check_run(tmp_path / "missing-run", tmp_path / "missing-results.json")


def test_analysis_matches_protocol_hand_counts(toy):  # noqa: F811 - imported fixture
    targets, outputs, _ = toy
    versions = {"baseline": "toy_old", "A": "toy_new", "B": "toy_new"}
    renamed = [
        row | {"version_id": version, "response_id": f"{version}:{row['case_id']}"}
        for version, source in versions.items()
        for row in outputs
        if row["version_id"] == source
    ]
    paired = analysis.pair_outputs(targets, renamed, list(versions), "a" * 64)
    rows = analysis.observations(targets, paired)
    result = analysis.analyse(
        {
            "cases": targets,
            "cases_sha256": "a" * 64,
            "outputs": renamed,
            "attempts": [],
            "provenance": {"input_run": "synthetic_protocol_fixture"},
            "recorded": {
                "evaluator_summaries": loads(
                    dumps({v: analysis.summarize(rows[v]) for v in versions})
                )
            },
        },
        replications=20,
    )
    contrast = result["contrasts"]["A_minus_baseline"]
    metrics = contrast["metrics"]
    assert metrics["overall/call_agreement"]["difference"] == pytest.approx(1 / 3)
    assert metrics["overall/unjustified_decision_rate"]["difference"] == -0.5
    assert metrics["overall/excessive_refusal_rate"]["difference"] == 0
    assert metrics["overall/decision_coverage"]["difference"] == pytest.approx(-1 / 6)
    assert metrics["overall/decision_coverage"]["gain"] is None
    assert sum(contrast["transitions"]["counts"].values()) == 6
    for metric in result["contrasts"]["B_minus_A"]["metrics"].values():
        assert metric["difference"] in (0, None)
