"""Seed statistics, update budget and adapter loading of task 2.6."""

from __future__ import annotations

import math
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from boxbox.config import load_config
from boxbox.evaluation._io import dumps, loads
from boxbox.model import ConversationEngineError, load_conversation_engine
from boxbox.training.lora import _checkpoints
from scripts.train_adapter import (
    SELECTION,
    check_rebuilt_baseline,
    planned_updates,
    seed_interval,
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
    lock = {
        "selected_candidate": chosen,
        "prompt_sha256": prompt_sha256 or selection["prompt_sha256"],
        "cases_sha256": selection["cases_sha256"],
    }
    (folder / "selected" / "inference-lock.json").write_text(dumps(lock))
    exact = measures or selection["selection"]["exact_values"][chosen]
    (folder / "selection.json").write_text(dumps({"exact_values": {chosen: exact}}))
    record = {"version_id": chosen, "cases_sha256": selection["cases_sha256"]}
    return [record] * selection["baseline_output_count"]


def test_a_rebuilt_baseline_needs_the_2_5b_prompt_cases_and_measures(tmp_path) -> None:
    records = _rebuilt_run(tmp_path / "same")
    check_rebuilt_baseline(records, tmp_path / "same")
    with pytest.raises(ValueError, match="answers"):
        check_rebuilt_baseline(records[1:], tmp_path / "same")
    records = _rebuilt_run(tmp_path / "prompt", prompt_sha256="0" * 64)
    with pytest.raises(ValueError, match="selected prompt"):
        check_rebuilt_baseline(records, tmp_path / "prompt")
    other = {"overall/strict_format_rate": {"numerator": 1, "denominator": 2}}
    records = _rebuilt_run(tmp_path / "measures", measures=other)
    with pytest.raises(ValueError, match="measures"):
        check_rebuilt_baseline(records, tmp_path / "measures")
