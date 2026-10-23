"""Losses read back from a run folder or from the Trainer's console log (task 5.4)."""

from __future__ import annotations

import json
from pathlib import Path

from boxbox.training import loss_history

LOG = """Loading weights: 100%
  0%|          | 1/4 [00:11<00:33, 11.0s/it]{'loss': '1.288', 'grad_norm': '3.093', 'epoch': '0.5'}
{'loss': '0.5193', 'grad_norm': '1.848', 'epoch': '1'}
{'eval_loss': '0.174', 'eval_runtime': '95.5', 'epoch': '1'}
{'loss': '0.09515', 'grad_norm': '0.4801', 'epoch': '1.5'}
{'loss': '1.021e-02', 'grad_norm': '0.2', 'epoch': '2'}
 50%|#####     | 2/4 [01:02<00:10]{'eval_loss': '0.1666', 'eval_runtime': '95.2', 'epoch': '2'}
{'train_runtime': '4310', 'train_loss': '0.06229', 'epoch': '2'}
answered validation with A-s2028-e1
selected A-s2028-e1, reload ok: True
"""


def test_log_gives_the_printed_losses_and_the_selected_epoch(tmp_path: Path) -> None:
    log = tmp_path / "seed-2028.log"
    log.write_text(LOG, encoding="utf-8")
    history = loss_history(log)
    assert history["train"] == [1.288, 0.5193, 0.09515, 0.01021]
    assert history["validation"] == [0.174, 0.1666]  # the closing summary is not a loss
    assert history["selected_epoch"] == 1
    assert history["exact"] is False


def test_log_without_selection(tmp_path: Path) -> None:
    log = tmp_path / "seed.log"
    log.write_text(LOG.split("answered")[0], encoding="utf-8")
    assert loss_history(log)["selected_epoch"] is None


def test_run_folder_gives_the_exact_losses(tmp_path: Path) -> None:
    metrics = {
        "train_losses": [1.1290786266326904, 0.8246124386787415],
        "eval_losses": [
            {"epoch": 1.0, "step": 1, "eval_loss": 0.051596976816654205},
            {"epoch": 2.0, "step": 2, "eval_loss": 0.07506441324949265},
        ],
    }
    (tmp_path / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    history = loss_history(tmp_path)
    assert history["train"] == metrics["train_losses"]
    assert history["validation"] == [0.051596976816654205, 0.07506441324949265]
    assert history["selected_epoch"] is None and history["exact"] is True
    selection = {"selected_candidate": "B-s2027-e2"}
    (tmp_path / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
    assert loss_history(tmp_path)["selected_epoch"] == 2
