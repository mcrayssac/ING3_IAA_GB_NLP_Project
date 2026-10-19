"""Seed statistics, update budget and adapter loading of task 2.6."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from boxbox.config import load_config
from boxbox.model import ConversationEngineError, load_conversation_engine
from boxbox.training.lora import _checkpoints
from scripts.train_adapter import planned_updates, seed_interval

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
