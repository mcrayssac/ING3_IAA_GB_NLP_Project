"""Reload a saved adapter and compare its logits with those stored at training time.

Run it in a fresh process: python -m boxbox.training.reload RUN_DIR
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
from peft import PeftModel

from boxbox.config import build_config
from boxbox.model import get_device, load_model


def reload_check(run_dir: Path) -> dict[str, float]:
    """Compare the reloaded adapter's next-token output with training time and the base.

    Logits are compared in bf16, where one rounding step is 0.125 near a logit of 30,
    so the check uses the softmax probabilities and the argmax.
    """
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    device = get_device()
    model, _ = load_model(build_config(manifest["config"]), device)
    model = PeftModel.from_pretrained(model, run_dir / "adapter").to(device).eval()
    saved = torch.load(run_dir / "reference.pt")
    with torch.no_grad():
        logits = model(saved["input_ids"].to(device)).logits[0, -1].float().cpu()
    probs = torch.softmax(logits, -1)
    return {
        "max_logit_diff_vs_training": (logits - saved["adapted"]).abs().max().item(),
        "max_logit_diff_vs_base": (logits - saved["base"]).abs().max().item(),
        "max_prob_diff_vs_training": (probs - torch.softmax(saved["adapted"], -1))
        .abs()
        .max()
        .item(),
        "max_prob_diff_vs_base": (probs - torch.softmax(saved["base"], -1))
        .abs()
        .max()
        .item(),
        "same_argmax_as_training": logits.argmax().item()
        == saved["adapted"].argmax().item(),
    }


if __name__ == "__main__":
    print(json.dumps(reload_check(Path(sys.argv[1]))))
