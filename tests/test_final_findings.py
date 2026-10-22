"""4.5 findings on a synthetic sealed final run and a synthetic rating sheet."""

from __future__ import annotations

import pytest
from test_evaluation import cases, toy  # noqa: F401 - protocol calibration fixtures
from test_final_analysis import sealed  # noqa: F401 - synthetic sealed-run fixture
from test_final_cases import cards  # noqa: F401 - synthetic final-race fixture
from test_final_scoring import prepared  # noqa: F401 - sealed-run fixtures
from test_human_review import complete, rows, write

from boxbox.evaluation._io import dumps, loads, sha256
from scripts import final_analysis as analysis
from scripts import final_findings as findings
from scripts import human_review


@pytest.fixture
def rated(sealed, tmp_path, monkeypatch):  # noqa: F811 - imported fixture
    run, _ = sealed
    folder = analysis.run(run, replications=20, runs_dir=tmp_path / "4-4")
    monkeypatch.setattr(findings, "EVIDENCE_4_4", folder / "evidence.json")
    table = rows(run / "review" / "review.csv")
    for row in table:
        complete(row)
        row["correctness"] = "0"  # every right call then has a wrong reason
    sheet = tmp_path / "rated.csv"
    write(sheet, table)
    initial = tmp_path / "initial.jsonl"
    human_review.import_ratings(run, sheet, initial)
    return run, sheet, initial


def test_findings_on_a_complete_sheet(rated, tmp_path):
    run, sheet, initial = rated
    folder = findings.run(run, sheet, initial, 20, tmp_path / "out")
    result = loads((folder / "evidence.json").read_text())
    assert result["reviewed_targets"] == 40
    for v in analysis.VERSIONS:
        mean = result["human"]["summaries"][v]["overall/human_correctness_mean"]
        assert (mean["numerator"], mean["denominator"]) == (0, 40)
        audit = result["call_against_reading"][v]
        assert audit["right_call_wrong_reason"] == audit["right_call"]
    assert result["second_review"]["rows"] == 0
    case = {c["mechanism"]: c for c in result["cases"]}["Right call, wrong reason"]
    seen = case["versions"][case["highlighted_version"]]
    assert seen["call"] == case["expected_call"]
    assert seen["human"]["scores"]["correctness"] == 0
    manifest = loads((folder / "manifest.json").read_text())
    assert manifest["provenance"]["sheet_sha256"] == sha256(sheet.read_bytes())
    assert manifest["protocol_settings"] is False  # 20 draws are for tests only
    assert manifest["evidence_sha256"] == sha256(
        (folder / "evidence.json").read_bytes()
    )
    with pytest.raises(FileExistsError):
        findings.run(run, sheet, initial, 20, tmp_path / "out")


def test_pick_ignores_candidate_order():
    pairs = [("c1", "A"), ("c2", "A"), ("c3", "B")]
    assert findings.pick("m", pairs) == findings.pick("m", pairs[::-1])
    assert findings.pick("m", []) is None


def test_pending_sheet_is_refused(rated, tmp_path):
    run, _, initial = rated
    with pytest.raises(ValueError, match="not complete"):
        findings.run(run, run / "review" / "review.csv", initial, 20, tmp_path / "out")


def test_changed_primary_score_is_refused(rated, tmp_path):
    run, sheet, initial = rated
    table = rows(sheet)
    table[0]["role_format"] = "1"
    changed = tmp_path / "changed.csv"
    write(changed, table)
    with pytest.raises(ValueError, match="differ from the initial ratings"):
        findings.run(run, changed, initial, 20, tmp_path / "out")


def test_summaries_must_match_the_committed_evidence(rated, tmp_path, monkeypatch):
    run, sheet, initial = rated
    evidence = loads(findings.EVIDENCE_4_4.read_text())
    evidence["summaries"]["A"]["metrics"]["overall/call_agreement"]["numerator"] += 1
    tampered = tmp_path / "evidence.json"
    tampered.write_text(dumps(evidence))
    monkeypatch.setattr(findings, "EVIDENCE_4_4", tampered)
    with pytest.raises(ValueError, match="differs from"):
        findings.run(run, sheet, initial, 20, tmp_path / "out")
