"""4.4 analysis on a synthetic sealed final run: checks, contrasts and refusals."""

from __future__ import annotations

import pytest
from test_final_cases import cards  # noqa: F401 - synthetic final-race fixture
from test_final_scoring import fake_stack, prepared  # noqa: F401 - sealed-run fixtures

from boxbox.evaluation._io import dumps, loads, sha256
from scripts import final_analysis as analysis
from scripts import final_scoring as runner


@pytest.fixture
def sealed(prepared, monkeypatch, tmp_path):  # noqa: F811 - imported fixture
    fake_stack(monkeypatch)
    runner.generate(prepared)
    runner.seal(prepared)
    monkeypatch.setattr(analysis, "FINAL_CASES", runner.FINAL / "cases.jsonl")
    results = tmp_path / "final-scoring-results.json"
    results.write_text(
        dumps({"complete_sha256": sha256((prepared / "complete.json").read_bytes())})
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
    assert (folder / "evidence.json").exists()
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
    results.write_text(dumps({"complete_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="not the record 4.2 published"):
        analysis.check_run(run, results)


def test_summaries_must_match_those_4_2_recorded(sealed):
    run, results = sealed
    checked = analysis.check_run(run, results)
    checked["recorded"]["evaluator_summaries"] = {"baseline": {}}
    with pytest.raises(ValueError, match="differ from those 4.2 recorded"):
        analysis.analyse(checked, replications=20)
