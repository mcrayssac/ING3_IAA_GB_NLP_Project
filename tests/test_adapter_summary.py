"""Seed statistics, update budget and adapter loading of tasks 2.6 and 3.2."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from boxbox.config import load_config
from boxbox.evaluation._io import dumps, loads
from boxbox.model import (
    ConversationEngineError,
    load_conversation_engine,
    selected_adapter,
)
from boxbox.training.lora import _checkpoints
from scripts.train_adapter import (
    ADAPTERS,
    METRICS,
    SELECTION,
    against_a,
    all_seeds,
    baseline_source,
    check_rebuilt_baseline,
    equal_updates,
    median_version,
    paired_differences,
    planned_updates,
    run_name,
    seed_interval,
    seed_of,
    training_rows,
)

CONFIG = load_config(Path("configs/adapter-a.toml"))


def test_seed_interval_is_a_student_t_over_seeds() -> None:
    result = seed_interval([0.5, 0.6, 0.7])
    half = 4.303 * 0.1 / math.sqrt(3)
    assert result["mean"] == pytest.approx(0.6) and result["sd"] == pytest.approx(0.1)
    assert (result["low"], result["high"]) == (
        pytest.approx(0.6 - half),
        pytest.approx(0.6 + half),
    )
    assert seed_interval([0.5, None, 0.7])["mean"] is None
    assert seed_interval([Decimal("0.5"), Decimal("0.6"), Decimal("0.7")])[
        "mean"
    ] == pytest.approx(0.6)
    assert seed_interval([0.5])["mean"] is None


def test_update_budget_is_the_same_for_any_batch_split() -> None:
    assert planned_updates(CONFIG, 480) == 360
    split = replace(CONFIG.lora, batch_size=2, gradient_accumulation=2)
    assert planned_updates(replace(CONFIG, lora=split), 480) == 360


def test_checkpoints_carry_their_epoch_and_validation_loss(tmp_path) -> None:
    for step in (120, 240, 360):
        (tmp_path / "trainer" / f"checkpoint-{step}").mkdir(parents=True)
    history = [{"epoch": float(e), "eval_loss": 0.5 / e} for e in (1, 2, 3)]
    found = _checkpoints(tmp_path, history)
    assert [(c["epoch"], c["step"]) for c in found] == [(1, 120), (2, 240), (3, 360)]
    assert (
        found[1]["eval_loss"] == 0.25 and found[0]["folder"] == "trainer/checkpoint-120"
    )


def test_the_loader_needs_an_adapter_folder_exactly_for_an_adapter(tmp_path) -> None:
    with pytest.raises(ConversationEngineError, match="adapter_dir"):
        load_conversation_engine(CONFIG)
    with pytest.raises(ConversationEngineError, match="adapter_dir"):
        load_conversation_engine(replace(CONFIG, adapter="none"), adapter_dir=tmp_path)


def _rebuilt_run(
    folder: Path, prompt_sha256: str | None = None, measures: dict | None = None
) -> list[dict]:
    """A minimal re-run folder of the 2.5b baseline, with its lock and measures."""
    selection = loads(SELECTION.read_text())
    chosen = selection["selected_candidate"]
    (folder / "selected").mkdir(parents=True)
    record = {"version_id": chosen, "cases_sha256": selection["cases_sha256"]}
    records = [record] * selection["baseline_output_count"]
    ledger = "".join(dumps(r) + "\n" for r in records).encode()
    (folder / "outputs.jsonl").write_bytes(ledger)
    lock = {
        "selected_candidate": chosen,
        "prompt_sha256": prompt_sha256 or selection["prompt_sha256"],
        "cases_sha256": selection["cases_sha256"],
        "outputs_sha256": hashlib.sha256(ledger).hexdigest(),
    }
    (folder / "selected" / "inference-lock.json").write_text(dumps(lock))
    exact = measures or selection["selection"]["exact_values"][chosen]
    (folder / "selection.json").write_text(dumps({"exact_values": {chosen: exact}}))
    return records


def test_a_rebuilt_baseline_needs_the_2_5b_prompt_cases_and_measures(tmp_path) -> None:
    records = _rebuilt_run(tmp_path / "same")
    check_rebuilt_baseline(records, tmp_path / "same")
    with pytest.raises(ValueError, match="answers"):
        check_rebuilt_baseline(records[1:], tmp_path / "same")
    edited = [{**records[0], "raw_response": "CALL: BOX"}] + records[1:]
    with pytest.raises(ValueError, match="ledger"):
        check_rebuilt_baseline(edited, tmp_path / "same")
    records = _rebuilt_run(tmp_path / "prompt", prompt_sha256="0" * 64)
    with pytest.raises(ValueError, match="selected prompt"):
        check_rebuilt_baseline(records, tmp_path / "prompt")
    other = {"overall/strict_format_rate": {"numerator": 1, "denominator": 2}}
    records = _rebuilt_run(tmp_path / "measures", measures=other)
    with pytest.raises(ValueError, match="measures"):
        check_rebuilt_baseline(records, tmp_path / "measures")


def test_a_baseline_that_is_not_the_2_5b_file_needs_rebuilt(tmp_path) -> None:
    (tmp_path / "selected").mkdir()
    other = tmp_path / "selected" / "baseline-outputs.jsonl"
    other.write_text(dumps({"version_id": "p01-policy-first", "run_id": "x"}) + "\n")
    with pytest.raises(ValueError, match="--rebuilt"):
        baseline_source(other, rebuilt=False)


def _summary(numerators: tuple[int, ...]) -> dict:
    """Six selection metrics over 40 cases, in the 2.3a priority order."""
    names = [
        "overall/strict_format_rate",
        "overall/unjustified_decision_rate",
        "overall/excessive_refusal_rate",
        "overall/macro_label_agreement",
        "overall/macro_family_agreement",
        "overall/call_agreement",
    ]
    metrics = {
        name: {
            "status": "defined",
            "numerator": n,
            "denominator": 40,
            "exact": {"numerator": n, "denominator": 40},
        }
        for name, n in zip(names, numerators)
    }
    return {"metrics": metrics}


def test_the_median_seed_is_the_middle_of_the_2_3a_order() -> None:
    seeds = [
        {"version": "A-s2026-e3", "summary": _summary((40, 21, 0, 32, 32, 31))},
        {"version": "A-s2027-e3", "summary": _summary((40, 24, 0, 31, 31, 30))},
        {"version": "A-s2028-e1", "summary": _summary((40, 23, 1, 28, 30, 28))},
    ]
    ranking, median = median_version(seeds)
    assert ranking["ranked_candidate_ids"] == ["A-s2026-e3", "A-s2028-e1", "A-s2027-e3"]
    assert median == "A-s2028-e1"


def test_the_selected_adapter_is_refused_when_its_hash_differs(tmp_path) -> None:
    folder = tmp_path / "runs" / "run" / "trainer" / "checkpoint-120"
    folder.mkdir(parents=True)
    (folder / "adapter_model.safetensors").write_bytes(b"weights")
    config = Path("configs/adapter-a.toml")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Answer with CALL and WHY.", encoding="utf-8")
    selection = {
        "run": "run",
        "checkpoint": "trainer/checkpoint-120",
        "seed": 2028,
        "config_file": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "prompt_file": str(prompt),
        "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
        "adapter_sha256": hashlib.sha256(b"weights").hexdigest(),
        "hub": None,
    }
    file = tmp_path / "selection.json"
    file.write_text(dumps(selection))
    found, path, instructions = selected_adapter(file, tmp_path / "runs")
    assert (found.seed, found.adapter, path) == (2028, "A", folder)
    assert instructions == "Answer with CALL and WHY."
    (folder / "adapter_model.safetensors").write_bytes(b"other weights")
    with pytest.raises(ValueError, match="not the selected one"):
        selected_adapter(file, tmp_path / "runs")
    with pytest.raises(FileNotFoundError, match="no Hub copy"):
        selected_adapter(file, tmp_path / "elsewhere")
    prompt.write_text("Another prompt.", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since the adapter was trained"):
        selected_adapter(file, tmp_path / "runs")


def test_b_has_the_settings_of_a_except_its_corpus() -> None:
    a, b = (load_config(ADAPTERS[x]["config"]) for x in ("A", "B"))
    assert (b.adapter, b.abstention_share) == ("B", 0.15)
    assert replace(b, adapter=a.adapter, abstention_share=a.abstention_share) == a


def test_names_follow_the_adapter_and_its_task() -> None:
    assert run_name("A", "s2026") == "2-6-adapter-a-s2026"
    assert run_name("B", "summary") == "3-2-adapter-b-summary"
    assert seed_of("2026-10-19_2-6-adapter-a-s2028") == 2028


def test_training_rows_read_the_corpus_of_the_adapter(monkeypatch) -> None:
    import boxbox.corpus
    import boxbox.training

    read = []
    monkeypatch.setattr(boxbox.corpus, "load_corpus", lambda name: read.append(name))
    monkeypatch.setattr(boxbox.training, "build_rows", lambda engine, items, n: [])
    b = load_config(ADAPTERS["B"]["config"])
    training_rows(None, b)
    training_rows(None, CONFIG)
    assert read == ["B_train", "validation", "A_train", "validation"]


def test_paired_differences_are_taken_seed_by_seed() -> None:
    mine = [{m: value for m in METRICS} for value in (0.7, 0.8, 0.9)]
    theirs = [{m: 0.6 for m in METRICS} for _ in range(3)]
    result = paired_differences(mine, theirs)["overall/call_agreement"]
    half = 4.303 * 0.1 / math.sqrt(3)
    assert result["values"] == pytest.approx([0.1, 0.2, 0.3])
    assert (result["mean"], result["low"]) == (
        pytest.approx(0.2),
        pytest.approx(0.2 - half),
    )


def test_b_against_a_needs_an_a_summary_with_the_same_seeds(tmp_path) -> None:
    summary = tmp_path / "2026-10-20_2-6-adapter-a-summary.json"
    seeds = [{"run": "2026-10-19_2-6-adapter-a-s2026", "version": "A-s2026-e3"}]
    summary.write_text(dumps({"adapter_a": {}, "seeds": seeds}))
    runs = [tmp_path / "2026-10-21_3-2-adapter-b-s2028"]
    with pytest.raises(ValueError, match=r"no A run for seeds \[2028\]"):
        against_a(runs, [{}], summary)
    summary.write_text(dumps({"adapter_b": {}, "seeds": seeds}))
    with pytest.raises(ValueError, match="not a summary of adapter A"):
        against_a(runs, [{}], summary)


def _validated(folder: Path, letter: str, values: dict[int, float]) -> Path:
    """A run folder whose validation summaries give every metric one value per epoch."""
    folder.mkdir()
    summaries = {
        f"{letter}-s2026-e{epoch}": {"metrics": {m: {"value": v} for m in METRICS}}
        for epoch, v in values.items()
    }
    (folder / "validation-summaries.json").write_text(dumps(summaries))
    return folder


def test_equal_updates_compares_b_and_a_at_the_same_epoch(tmp_path) -> None:
    b = _validated(tmp_path / "b", "B", {1: 0.5, 2: 0.7, 3: 0.8})
    a = _validated(tmp_path / "a", "A", {1: 0.4, 2: 0.6, 3: 0.8})
    result = equal_updates([b], [a])
    assert list(result) == ["epoch 1", "epoch 2", "epoch 3"]
    values = [result[k]["overall/call_agreement"]["values"] for k in result]
    assert values == [pytest.approx([0.1]), pytest.approx([0.1]), pytest.approx([0.0])]
    short = _validated(tmp_path / "short", "A", {1: 0.4, 2: 0.6})
    with pytest.raises(ValueError, match="same epochs"):
        equal_updates([b], [short])


def test_a_failed_seed_does_not_stop_the_next_ones(tmp_path, monkeypatch) -> None:
    import subprocess

    calls = []

    def fake_run(command, check, stdout, stderr):
        args = command[3:]
        calls.append(args[0])
        if args[0] == "train":
            seed = args[args.index("--seed") + 1]
            if seed == "2026":
                return subprocess.CompletedProcess(command, 1)
            (tmp_path / "runs" / f"2026-10-21_3-2-adapter-b-s{seed}").mkdir()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", fake_run)
    statuses = all_seeds("B")
    assert [s.split(": ")[1] for s in statuses] == ["train failed", "ok", "ok"]
    assert calls == ["train", "train", "validate", "train", "validate"]
    status_file = tmp_path / "runs" / "3-2-logs" / "status.txt"
    assert status_file.read_text().count("seed") == 3
