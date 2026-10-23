"""Losses of a finished training run, from its run folder or from its console log."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

# the Trainer prints one dict per update and one per evaluation, values as strings
LOGGED = re.compile(r"\{'(?:loss|eval_loss)': [^{}]*\}")
SELECTED = re.compile(r"^selected \w+-s\d+-e(\d+)", re.MULTILINE)


def loss_history(source: Path) -> dict[str, Any]:
    """Training loss per update, validation loss per epoch and the selected epoch.

    A run folder gives the exact values of its metrics.json and selection.json. A log
    gives the values the Trainer printed, rounded to four significant digits.
    """
    if source.is_dir():
        metrics = json.loads((source / "metrics.json").read_text(encoding="utf-8"))
        chosen = source / "selection.json"
        selected = (
            json.loads(chosen.read_text(encoding="utf-8"))["selected_candidate"]
            if chosen.exists()
            else None
        )
        return {
            "train": [float(x) for x in metrics["train_losses"]],
            "validation": [float(e["eval_loss"]) for e in metrics["eval_losses"]],
            "selected_epoch": int(selected.rsplit("-e", 1)[1]) if selected else None,
            "exact": True,
        }
    text = source.read_text(encoding="utf-8")
    records = [ast.literal_eval(match) for match in LOGGED.findall(text)]
    selected = SELECTED.search(text)
    return {
        "train": [float(r["loss"]) for r in records if "loss" in r],
        "validation": [float(r["eval_loss"]) for r in records if "eval_loss" in r],
        "selected_epoch": int(selected[1]) if selected else None,
        "exact": False,
    }
