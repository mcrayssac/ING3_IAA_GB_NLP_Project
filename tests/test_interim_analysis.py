"""Evidence integrity and paired regressions of the read-only 3.3 audit."""

from copy import deepcopy

import pytest

from boxbox.evaluation._io import dumps, sha256
from scripts import interim_analysis as audit


def test_evidence_rejects_traversal_and_symlinks(tmp_path):
    folder = tmp_path / "evidence"
    folder.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("private")
    (folder / "link.json").symlink_to(outside)
    for name in ("../outside.json", "link.json"):
        with pytest.raises(ValueError, match="escapes"):
            audit.Evidence().file(folder, name)


def test_fraction_comparison_never_uses_rounded_display_values():
    with pytest.raises(ValueError, match="differs"):
        audit.same({"numerator": 1, "denominator": 3}, {"value": 0.333}, "count")


def test_transitions_preserve_regressions_and_invalid_labels():
    def row(cid, expected, predicted):
        return {
            "case_id": cid,
            "reference": {"expected_call": expected},
            "extracted_call": predicted,
        }

    rows = {
        "A": [
            row("1", "BOX", "BOX"),
            row("2", "NO CALL", "BOX"),
            row("3", "BOX", None),
            row("4", "BOX", "BOX"),
        ],
        "B": [
            row("1", "BOX", "NO CALL"),
            row("2", "NO CALL", "NO CALL"),
            row("3", "BOX", "STAY OUT"),
            row("4", "BOX", "BOX"),
        ],
    }
    result = audit.transitions(rows, "A", "B")
    assert result["counts"] == {
        "both_correct": 1,
        "both_wrong": 1,
        "new_only_correct": 1,
        "old_only_correct": 1,
    }
    assert result["case_ids"]["old_only_correct"] == ["1"]
    assert any(r["old"] == "INVALID" for r in result["label_transitions"])


def trace_matrix():
    cases = [{"case_id": "1", "history": []}]
    paired, attempts = {}, []
    for version in ("A", "B"):
        row = {
            "case_id": "1",
            "version_id": version,
            "response_id": version + "1",
            "input_sha256": "input",
            "raw_response": "answer",
        }
        paired[version] = {"1": row}
        trace = {
            "raw_response": "answer",
            "prompt_token_ids_sha256": "tokens",
            "instructions": "instructions",
            "instructions_sha256": sha256("instructions"),
            "messages": [],
            "prompt_messages_sha256": sha256(dumps([])),
            "generated_token_ids": [1],
            "generated_tokens": 1,
            "generation_settings": {
                "max_new_tokens": 64,
                "seed": 2026 if version == "A" else 2027,
            },
            "history": {"retained": [], "was_reduced": False},
            "possibly_truncated": False,
            "duration_seconds": 0.5,
        }
        attempts.append(
            {k: v for k, v in row.items() if k != "raw_response"} | {"trace": trace}
        )
    return cases, paired, attempts


@pytest.mark.parametrize(
    "change", ["duplicate", "raw", "prompt", "generation", "history"]
)
def test_trace_drift_stops_the_audit(change):
    cases, paired, attempts = trace_matrix()
    assert audit.trace_checks(cases, paired, attempts)["same_prompt_tokens"] == {
        "A": 1,
        "B": 1,
    }
    changed = deepcopy(attempts)
    if change == "duplicate":
        changed.append(deepcopy(changed[0]))
    else:
        trace = changed[-1]["trace"]
        if change == "raw":
            trace["raw_response"] = "edited answer"
        elif change == "prompt":
            trace["prompt_token_ids_sha256"] = "other tokens"
        elif change == "generation":
            trace["generation_settings"]["max_new_tokens"] = 128
        else:
            trace["history"]["retained"] = [{"role": "user", "content": "another card"}]
    with pytest.raises(ValueError):
        audit.trace_checks(cases, paired, changed)


def test_a_plan_cannot_add_a_reserved_card_file(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path / "repo")
    splits = audit.ROOT / "data/splits.json"
    splits.parent.mkdir(parents=True)
    splits.write_text(dumps({"splits": {"mini_test": ["2025-01"]}}))
    names = [
        "boxbox/rules/decision.py",
        "data/corpus/manifest.json",
        "data/corpus/mini_test.jsonl",
        "data/splits.json",
        "docs/evaluation-protocol.md",
        "reference/evaluation-fixtures.json",
        "reference/fixtures.json",
    ]
    plan = {
        "version_ids": ["baseline", "A", "B"],
        "split": "mini_test",
        "normative_files": dict.fromkeys(names, "hash"),
        "sealed_files": {"sources/data/cards/2099-99.jsonl": "hash"},
    }
    run = tmp_path / audit.MINI
    run.mkdir()
    (run / "plan.json").write_text(dumps(plan))
    # The forbidden card does not exist; validation must stop before attempting to open it.
    with pytest.raises(ValueError, match="outside mini-test scope"):
        audit.mini_test(audit.Evidence(), tmp_path)


def test_existing_output_is_preserved_without_reading_runs(tmp_path, monkeypatch):
    output = tmp_path / "analysis.json"
    output.write_text("previous evidence")
    monkeypatch.setattr(
        "sys.argv",
        [
            "interim_analysis",
            "--runs-root",
            str(tmp_path / "absent"),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(FileExistsError):
        audit.main()
    assert output.read_text() == "previous evidence"
