"""Runner boundaries, persistence and common-input controls without model weights."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from boxbox.config import RunConfig, load_config
from boxbox.evaluation import pair_outputs, prepare_case
from boxbox.evaluation._io import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    read_jsonl,
    sha256,
    write_jsonl,
)
from boxbox.model import ConversationEngineError, baseline_instructions
from boxbox.runs import config_toml
from scripts import compare_prompts as runner


def test_candidates_change_order_only_and_keep_integrated_policy():
    first = Path("configs/prompts/p01-policy-first.txt").read_text()
    second = Path("configs/prompts/p02-format-first.txt").read_text()
    assert first == baseline_instructions()
    assert first != second
    assert sorted(first.split("\n\n")) == sorted(second.split("\n\n"))
    assert second.index("Return exactly two lines") < second.index(
        "Apply BoxBox policy"
    )


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    fixture = json.loads(Path("reference/evaluation-fixtures.json").read_text())
    source = fixture["cases"][:2]
    cards = {row["card_id"]: row["card"] for row in fixture["cards"]}
    cases = [prepare_case(row, cards[row["card_id"]]) for row in source]
    versions = ["p01", "p02"]
    candidates = {}
    for version in versions:
        folder = tmp_path / "candidates" / version
        folder.mkdir(parents=True)
        (folder / "config.toml").write_text(
            config_toml(replace(RunConfig(), prompt_variant=version))
        )
        (folder / "prompt.txt").write_text(f"Instructions for {version}")
        candidates[version] = {
            "config_sha256": sha256((folder / "config.toml").read_bytes())
        }
    plan = {
        "candidate_ids": versions,
        "candidates": candidates,
        "source_sha256": "source",
        "cases_sha256": "a" * 64,
        "planned_responses": 4,
    }
    monkeypatch.setattr(runner, "verify_plan", lambda run: (plan, cases, {}))
    monkeypatch.setattr(runner, "source_sha256", lambda: "source")
    state = SimpleNamespace(
        preflights=[],
        calls=[],
        fail_preflight=False,
        interrupt=False,
        change_context=False,
    )

    class Engine:
        device, dtype, attn_implementation = "cpu", "float32", None
        model = object()
        tokenizer = SimpleNamespace(chat_template="native template")

        def __init__(self, *args, **kwargs):
            self.config = args[2] if len(args) > 2 else kwargs["config"]

        def preflight_candidates(self, candidates, **kwargs):
            assert kwargs["fixed_history"] is True
            state.preflights.append(kwargs)
            return {
                "ready": not state.fail_preflight,
                "common_unreduced_history": True,
                "candidates": {
                    v: {"input_token_ids_sha256": "fixed-tokens"} for v in candidates
                },
            }

        def generation_settings(self):
            return {"do_sample": False, "max_new_tokens": 64}

        def template_context(self):
            return {"date": "2026-10-19"}

        def respond_with_trace(self, **kwargs):
            assert len(state.preflights) == len(cases)
            state.calls.append((self.config.prompt_variant, kwargs))
            if state.interrupt and len(state.calls) == 2:
                raise RuntimeError("unexpected interruption")
            if self.config.prompt_variant == "p02":
                raise ConversationEngineError(
                    "generation_failed",
                    "original cause",
                    trace={
                        "history": {"retained": kwargs["history"]},
                        "prompt_token_ids_sha256": "fixed-tokens",
                    },
                    partial_response="real partial  ",
                )
            return "\nCALL: BOX\nWHY: raw answer  ", {
                "history": {"retained": kwargs["history"]},
                "prompt_token_ids_sha256": "changed"
                if getattr(state, "change_context", False)
                else "fixed-tokens",
            }

    import boxbox.model

    monkeypatch.setattr(
        boxbox.model,
        "load_conversation_engine",
        lambda config, **kwargs: Engine(config=config),
    )
    monkeypatch.setattr(boxbox.model, "ConversationEngine", Engine)
    return tmp_path, plan, cases, state


def test_all_preflight_before_calls_same_inputs_and_raw_errors_persist(prepared):
    run, plan, cases, state = prepared
    runner.generate(run)
    outputs, _ = read_jsonl(run / "outputs.jsonl")
    paired = pair_outputs(cases, outputs, plan["candidate_ids"], plan["cases_sha256"])
    assert len(outputs) == 4
    assert all(
        row["raw_response"] == "\nCALL: BOX\nWHY: raw answer  "
        for row in paired["p01"].values()
    )
    assert all(
        row["error"]["message"] == "original cause"
        and row["raw_response"] == "real partial  "
        for row in paired["p02"].values()
    )
    for index, case in enumerate(cases):
        assert state.calls[2 * index][1] == state.calls[2 * index + 1][1]
        assert state.calls[2 * index][1]["message"] == case["message"]
    assert (run / "attempt-complete.json").exists()
    with pytest.raises(FileExistsError):
        runner.generate(run)
    assert len(state.calls) == 4


def test_failed_preflight_prevents_every_generation(prepared):
    run, _, _, state = prepared
    state.fail_preflight = True
    with pytest.raises(ValueError, match="preflight failed"):
        runner.generate(run)
    assert not state.calls
    assert not (run / "outputs.jsonl").exists()
    assert (run / "attempt-failure.json").exists()
    assert not (run / "attempt-complete.json").exists()


def test_interruption_keeps_prior_response_and_cannot_select(prepared):
    run, _, _, state = prepared
    state.interrupt = True
    with pytest.raises(RuntimeError, match="unexpected interruption"):
        runner.generate(run)
    rows, _ = read_jsonl(run / "outputs.jsonl")
    assert len(rows) == 1
    assert rows[0]["raw_response"].startswith("\nCALL:")
    assert not (run / "attempt-complete.json").exists()
    with pytest.raises(FileNotFoundError):
        runner.score(run)
    assert not (run / "selection.json").exists()


def test_selected_config_remains_reloadable_with_same_generation_settings(tmp_path):
    source = RunConfig(prompt_variant="p02-format-first")
    path = tmp_path / "config.toml"
    path.write_text(config_toml(source))
    assert load_config(path) == source
    assert not load_config(path).final_test_open


@pytest.mark.parametrize("split", ["mini_test", "final"])
def test_restricted_split_rejected_before_corpus_or_card_read(
    tmp_path, monkeypatch, split
):
    config = tmp_path / "config.toml"
    config.write_text(
        f'[prompt_comparison]\nsplit="{split}"\n[prompt_comparison.candidates]\na="absent"\nb="absent"\n'
    )
    import boxbox.corpus
    import boxbox.data

    def forbidden(*args, **kwargs):
        pytest.fail("restricted data loader was reached")

    monkeypatch.setattr(boxbox.corpus, "load_corpus", forbidden)
    monkeypatch.setattr(boxbox.data, "load_cards", forbidden)
    monkeypatch.setattr(boxbox.data, "load_splits", forbidden)
    with pytest.raises(ValueError, match="validation only"):
        runner.prepare(config, "test", tmp_path, tmp_path)


def test_plan_rejects_changed_sealed_artifact(tmp_path):
    data = tmp_path / "config.toml"
    data.write_text("original")
    plan = {
        "split": "validation",
        "sealed_files": {"config.toml": sha256(data.read_bytes())},
    }
    (tmp_path / "plan.json").write_text(dumps(plan))
    (tmp_path / "manifest.json").write_text(
        dumps(
            {
                "extra": {
                    "prompt_comparison": {
                        "plan_sha256": sha256((tmp_path / "plan.json").read_bytes())
                    }
                }
            }
        )
    )
    data.write_text("changed")
    with pytest.raises(ValueError, match="sealed artifact changed"):
        runner.verify_plan(tmp_path)


def test_execution_context_drift_is_retained_but_cannot_be_selected(prepared):
    run, _, _, state = prepared
    state.change_context = True
    with pytest.raises(ValueError, match="executed context differs"):
        runner.generate(run)
    rows, _ = read_jsonl(run / "outputs.jsonl")
    assert len(rows) == 1
    assert not (run / "attempt-complete.json").exists()
    assert (run / "attempt-failure.json").exists()


def test_scoring_pairs_every_cell_and_copies_exact_selected_artifacts(
    tmp_path, monkeypatch
):
    fixture = json.loads(Path("reference/evaluation-fixtures.json").read_text())
    cards = {row["card_id"]: row["card"] for row in fixture["cards"]}
    cases = [prepare_case(row, cards[row["card_id"]]) for row in fixture["cases"]]
    versions = ["p01", "p02"]
    candidates = {}
    for v in versions:
        folder = tmp_path / "candidates" / v
        folder.mkdir(parents=True)
        (folder / "config.toml").write_text(
            config_toml(replace(RunConfig(), prompt_variant=v))
        )
        (folder / "prompt.txt").write_text(f"Exact {v} instructions\n")
        candidates[v] = {"config_sha256": sha256((folder / "config.toml").read_bytes())}
    case_hash = write_jsonl(tmp_path / "cases.jsonl", cases)
    outputs = []
    for case in cases:
        for v in versions:
            label = case["reference"]["expected_call"] if v == "p01" else "NO CALL"
            outputs.append(
                {
                    "response_id": f"{v}:{case['case_id']}",
                    "case_id": case["case_id"],
                    "version_id": v,
                    "run_id": "synthetic-score",
                    "config_sha256": candidates[v]["config_sha256"],
                    "protocol_id": PROTOCOL_ID,
                    "protocol_version": PROTOCOL_VERSION,
                    "cases_sha256": case_hash,
                    "input_sha256": case["input_sha256"],
                    "status": "ok",
                    "raw_response": f"CALL: {label}\nWHY: Synthetic test.",
                    "error": None,
                }
            )
    output_hash = write_jsonl(tmp_path / "outputs.jsonl", outputs)
    trace_hash = write_jsonl(tmp_path / "attempts.jsonl", [])
    runner.write_json(
        tmp_path / "attempt-complete.json",
        {"outputs_sha256": output_hash, "attempts_sha256": trace_hash},
    )
    runner.write_json(tmp_path / "runtime.json", {"synthetic_test": True})
    runner.write_json(tmp_path / "manifest.json", {"started": time.time()})
    plan = {
        "candidate_ids": versions,
        "candidates": candidates,
        "cases_sha256": case_hash,
        "planned_responses": len(outputs),
    }
    runner.write_json(tmp_path / "plan.json", plan)
    monkeypatch.setattr(runner, "verify_plan", lambda run: (plan, cases, {}))
    bootstrap = runner.bootstrap_compare
    monkeypatch.setattr(
        runner,
        "bootstrap_compare",
        lambda rows, old, new: bootstrap(rows, old, new, replications=100),
    )
    selected = runner.score(tmp_path)
    assert selected["selected_candidate"] == "p01"
    assert sha256((tmp_path / "outputs.jsonl").read_bytes()) == output_hash
    for filename in ("config.toml", "prompt.txt"):
        assert (tmp_path / "selected" / filename).read_bytes() == (
            tmp_path / "candidates/p01" / filename
        ).read_bytes()
    assert load_config(tmp_path / "selected/config.toml").prompt_variant == "p01"
    lock = json.loads((tmp_path / "selected/inference-lock.json").read_text())
    assert lock["acceptance_record"] is None
    assert lock["human_ratings"] == "not performed"
    assert not lock["final_test_open"]
    assert len((tmp_path / "paired.csv").read_text().splitlines()) == len(cases) + 1
