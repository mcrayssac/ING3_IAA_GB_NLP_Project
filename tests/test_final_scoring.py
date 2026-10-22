"""Final-run integrity and crash recovery on synthetic cards and fake engines only."""

from __future__ import annotations

import csv
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from test_final_cases import cards  # noqa: F401 - synthetic final-race fixture

from boxbox.config import load_config
from boxbox.evaluation._io import dumps, sha256
from scripts import final_cases
from scripts import final_scoring as runner


@pytest.fixture
def prepared(tmp_path, monkeypatch, cards):  # noqa: F811 - imported fixture
    out = tmp_path / "final"
    monkeypatch.setattr(final_cases, "FAILURES", tmp_path)
    final_cases.build(out, cards)
    monkeypatch.setattr(runner, "FINAL", out)
    prompt = Path("configs/prompts/p01-policy-first.txt").read_text()
    for v in ("A", "B"):
        folder = tmp_path / v
        folder.mkdir()
        (folder / "adapter_config.json").write_text(
            dumps(
                {
                    "r": 16,
                    "lora_alpha": 32,
                    "lora_dropout": 0.0,
                    "base_model_name_or_path": "HuggingFaceTB/SmolLM3-3B",
                    "peft_type": "LORA",
                    "task_type": "CAUSAL_LM",
                    "bias": "none",
                    "target_modules": [
                        "q_proj",
                        "k_proj",
                        "v_proj",
                        "o_proj",
                        "gate_proj",
                        "up_proj",
                        "down_proj",
                    ],
                }
            )
        )
        (folder / "adapter_model.safetensors").write_bytes(b"synthetic weights")
    monkeypatch.setattr(
        runner.mini_test,
        "resolve_adapter",
        lambda v: (
            replace(
                load_config(f"configs/adapter-{v.lower()}.toml"),
                seed=2028 if v == "A" else 2027,
            ),
            tmp_path / v,
            prompt,
        ),
    )
    run = runner.prepare(tmp_path / "runs")
    return run


def fake_stack(monkeypatch):
    calls = []

    class Model:
        active = "baseline"

        def to(self, device):
            return self

        def eval(self):
            return self

        def add_adapter(self, name, config):
            pass

        def load_adapter(self, folder, adapter_name):
            pass

        def set_adapter(self, name):
            self.active = name

    class Engine:
        def __init__(self, model, tokenizer, config, instructions, device, dtype):
            self.model, self.tokenizer, self.config = model, tokenizer, config
            self.instructions, self.device, self.dtype = instructions, device, dtype

        def generation_settings(self):
            return {"do_sample": False, "seed": self.config.seed, "seed_active": False}

        def prepare(self, **kw):
            inp = {k: kw[k] for k in ("card", "history", "message")}
            return SimpleNamespace(
                trace={
                    "prompt_token_ids_sha256": sha256(dumps(inp)),
                    "messages": inp,
                    "input_tokens": 12,
                }
            )

        def respond_with_trace(self, **kw):
            calls.append((self.model.active, sha256(dumps(kw))))
            return "CALL: BOX\nWHY: Synthetic answer.", self.prepare(**kw).trace

    peft = ModuleType("peft")

    def adapted(model, folder, config):
        model.active = "A"
        return model

    peft.PeftModel = SimpleNamespace(from_pretrained=adapted)
    peft.PeftConfig = SimpleNamespace(from_pretrained=lambda folder: {})
    monkeypatch.setitem(sys.modules, "peft", peft)
    import boxbox.model

    monkeypatch.setattr(boxbox.model, "ConversationEngine", Engine)
    real_verify = runner.verify_plan

    def verify(run):
        plan, cases, splits = real_verify(run)
        plan["versions"]["baseline"]["chat_template_sha256"] = sha256(
            "synthetic template"
        )
        return plan, cases, splits

    monkeypatch.setattr(runner, "verify_plan", verify)

    def load(plan, run):
        config = load_config(run / "versions/baseline/config.toml")
        prompt = (run / "versions/baseline/prompt.txt").read_text()
        base = Engine(
            Model(),
            SimpleNamespace(chat_template="synthetic template"),
            config,
            prompt,
            "cpu",
            "float32",
        )
        return {
            "baseline": base,
            **{v: runner.mini_test.resolve_adapter(v) for v in ("A", "B")},
        }

    monkeypatch.setattr(runner.mini_test, "load_engines", load)
    monkeypatch.setattr(runner.mini_test, "check_adapter", lambda *args: None)
    return calls


def test_prepare_checks_200_cases_and_40_review_targets(prepared):
    plan, cases, _ = runner.verify_plan(prepared)
    assert len(cases) == 200
    assert plan["planned_responses"] == 600
    assert plan["version_ids"] == ["baseline", "A", "B"]
    for version, seed in (("baseline", 2026), ("A", 2028), ("B", 2027)):
        entry = plan["versions"][version]
        assert entry["config_sha256"] == runner.digest(
            prepared / entry["effective_config_file"]
        )
        assert load_config(prepared / entry["effective_config_file"]).seed == seed
        assert entry["frozen_config_sha256"] == runner.digest(
            prepared / f"versions/{version}/frozen-config.toml"
        )
    assert (
        len(runner.read(prepared / "review-selection.json")["selected_case_ids"]) == 40
    )
    evaluation = runner.read(prepared / "manifest.json")["extra"]["evaluation"]
    assert evaluation["acceptance_record"].startswith("https://github.com/")
    with pytest.raises(FileExistsError):
        runner.prepare(prepared.parent)


def test_changed_sealed_prompt_refused(prepared):
    (prepared / "versions/A/prompt.txt").write_text("changed")
    with pytest.raises(ValueError, match="sealed artifact changed"):
        runner.verify_plan(prepared)


def test_changed_final_cases_refused_before_prepare(prepared):
    (runner.FINAL / "cases.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="final artifact changed"):
        runner.final_inputs()


def test_full_matrix_exports_and_no_rerun(prepared, monkeypatch):
    calls = fake_stack(monkeypatch)
    runner.generate(prepared)
    assert len(calls) == 600
    assert len(set(calls)) == 600
    report = runner.seal(prepared)
    assert report["responses"] == 600
    assert all(v["statuses"] == {"ok": 200} for v in report["versions"].values())
    assert runner.verify(prepared) == report
    assert runner.seal(prepared) == report
    with (prepared / "review/review.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 120 and all(r["rating_status"] == "pending" for r in rows)
    assert len({r["case_id"] for r in rows}) == 40
    with pytest.raises(ValueError, match="completed final run"):
        runner.generate(prepared, "attempt to rerun")
    assert len(calls) == 600
    p = next((prepared / "requests").rglob("result.json"))
    p.write_text(p.read_text() + " ")
    with pytest.raises(ValueError, match="inventory changed"):
        runner.verify(prepared)


def test_technical_resume_keeps_started_request_as_error(prepared, monkeypatch):
    calls = fake_stack(monkeypatch)
    original = runner.answer_once
    state = {"count": 0}

    def interrupt(engine, case, version, run, plan, session):
        state["count"] += 1
        if state["count"] == 3:
            runner.put(
                runner.request_path(run, version, case) / "start.json",
                {
                    "case_id": case["case_id"],
                    "version_id": version,
                    "input_sha256": case["input_sha256"],
                    "session": session,
                    "started_utc": runner.now(),
                },
            )
            raise KeyboardInterrupt("synthetic crash during request")
        return original(engine, case, version, run, plan, session)

    monkeypatch.setattr(runner, "answer_once", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.generate(prepared)
    first = {p: p.read_bytes() for p in (prepared / "requests").rglob("result.json")}
    with pytest.raises(ValueError, match="--resume-reason"):
        runner.generate(prepared)
    monkeypatch.setattr(runner, "answer_once", original)
    runner.generate(prepared, "synthetic process interruption")
    assert len(calls) == 599 and len(set(calls)) == 599
    assert all(p.read_bytes() == b for p, b in first.items())
    report = runner.seal(prepared)
    assert report["versions"]["baseline"]["statuses"] == {
        "ok": 199,
        "generation_error": 1,
    }
    assert report["sessions"] == 2


def test_no_generation_after_preflight_failure(prepared, monkeypatch):
    calls = fake_stack(monkeypatch)
    import boxbox.model

    def fail(*args, **kw):
        raise ValueError("context preflight")

    monkeypatch.setattr(boxbox.model.ConversationEngine, "prepare", fail)
    with pytest.raises(ValueError, match="context preflight"):
        runner.generate(prepared)
    assert calls == [] and not (prepared / "requests").exists()
    assert (prepared / "sessions/001/failure.json").exists()


def test_seal_rejects_missing_output(prepared, monkeypatch):
    fake_stack(monkeypatch)
    runner.put_bytes(prepared / "preflight.jsonl", b"")
    with pytest.raises(ValueError, match="no recorded successful preflight"):
        runner.seal(prepared)
    assert not (prepared / "complete.json").exists()


def test_result_without_receipt_is_recovered_without_call(prepared, monkeypatch):
    plan, cases, _ = runner.verify_plan(prepared)
    case = cases[0]
    folder = runner.request_path(prepared, "A", case)
    runner.put(folder / "start.json", {"case_id": case["case_id"]})
    result = runner.failed(case, "A", prepared, plan, "synthetic_error", "test error")
    runner.put(folder / "result.json", result)
    runner.answer_once(None, case, "A", prepared, plan, "002")
    assert runner.read(folder / "result.json") == result
    assert runner.read(folder / "receipt.json")["recovered_receipt_in_session"] == "002"


def test_atomic_write_refuses_overwrite(tmp_path):
    path = tmp_path / "result.json"
    runner.put(path, {"original": True})
    with pytest.raises(FileExistsError):
        runner.put(path, {"original": False})
    assert runner.read(path) == {"original": True}


def test_parallel_run_lock_refused(prepared):
    with (
        runner.locked(prepared),
        pytest.raises(ValueError, match="another process"),
        runner.locked(prepared),
    ):
        pass


def test_peft_override_refused(prepared):
    plan = runner.read(prepared / "plan.json")
    cfg = runner.read(prepared / "versions/A/adapter_config.json")
    cfg["lora_alpha"] = 64
    with pytest.raises(ValueError, match="PEFT configuration differs"):
        runner.check_peft_config(
            dumps(cfg).encode(),
            plan["versions"]["A"],
            runner.read(runner.freeze.FREEZE)["model"],
        )


def test_changed_prompt_trace_cannot_be_sealed(prepared, monkeypatch):
    fake_stack(monkeypatch)
    runner.generate(prepared)
    path = next((prepared / "requests").rglob("result.json"))
    result = runner.read(path)
    result["attempt"]["trace"]["messages"] = {"card": "another card"}
    path.write_text(dumps(result))
    # Even an internally consistent result checksum cannot excuse wrong case binding.
    receipt = path.with_name("receipt.json")
    receipt.write_text(dumps({"result_sha256": runner.digest(path)}))
    with pytest.raises(ValueError, match="trace differs from case preflight"):
        runner.seal(prepared)


def test_resume_requires_same_runtime(prepared, monkeypatch):
    fake_stack(monkeypatch)
    original = runner.answer_once

    def crash(*args):
        raise KeyboardInterrupt("synthetic interruption")

    monkeypatch.setattr(runner, "answer_once", crash)
    with pytest.raises(KeyboardInterrupt):
        runner.generate(prepared)
    monkeypatch.setattr(runner, "answer_once", original)
    monkeypatch.setattr(runner.platform, "node", lambda: "a different host")
    with pytest.raises(ValueError, match="changed machine"):
        runner.generate(prepared, "synthetic resume on wrong host")
    assert not (prepared / "requests").exists()


def test_failed_request_is_retained_without_retry(prepared, monkeypatch):
    calls = fake_stack(monkeypatch)
    import boxbox.model

    original = boxbox.model.ConversationEngine.respond_with_trace
    state = {"failed": False}

    def respond(self, **kw):
        if not state["failed"]:
            state["failed"] = True
            raise boxbox.model.ConversationEngineError(
                "synthetic_backend_failure",
                "Synthetic failure for test only",
                trace=self.prepare(**kw).trace,
            )
        return original(self, **kw)

    monkeypatch.setattr(boxbox.model.ConversationEngine, "respond_with_trace", respond)
    runner.generate(prepared)
    report = runner.seal(prepared)
    assert len(calls) == 599
    assert report["versions"]["baseline"]["statuses"] == {
        "generation_error": 1,
        "ok": 199,
    }
    assert report["responses"] == 600


def test_missing_completed_request_prevents_sealing(prepared, monkeypatch):
    fake_stack(monkeypatch)
    runner.generate(prepared)
    path = next((prepared / "requests").rglob("result.json"))
    path.unlink()  # synthetic interrupted persistence, not a real run
    with pytest.raises(FileNotFoundError):
        runner.seal(prepared)
    assert not (prepared / "complete.json").exists()
