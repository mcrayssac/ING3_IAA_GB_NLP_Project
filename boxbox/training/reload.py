"""Reload a saved adapter and compare its outputs with those stored at training time.

Run it in a fresh process: python -m boxbox.training.reload RUN_DIR [MAX_MEMORY_GB]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel

from boxbox.config import build_config
from boxbox.model import cap_mps_memory, get_device, load_model, model_dtype


def reload_check(run_dir: Path, max_memory_gb: float | None = None) -> dict[str, Any]:
    """Compare the reloaded adapter with training time and with the base, on every probe.

    Logits are compared through their softmax, because in bf16 one rounding step is
    0.125 near a logit of 30.
    """
    if max_memory_gb is not None:
        cap_mps_memory(max_memory_gb)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    device = get_device()
    adapter_file = run_dir / "adapter" / "adapter_model.safetensors"
    model, _ = load_model(build_config(manifest["config"]), device)
    model = PeftModel.from_pretrained(model, run_dir / "adapter").to(device).eval()
    saved = torch.load(run_dir / "reference.pt")
    vs_training, vs_base, same_argmax = [], [], True
    for ids, adapted, base in zip(saved["input_ids"], saved["adapted"], saved["base"]):
        with torch.no_grad():
            logits = model(ids.to(device)).logits[0, -1].float().cpu()
        probs = torch.softmax(logits, -1)
        vs_training.append((probs - torch.softmax(adapted, -1)).abs().max().item())
        vs_base.append((probs - torch.softmax(base, -1)).abs().max().item())
        same_argmax = same_argmax and logits.argmax().item() == adapted.argmax().item()
    return {
        "reload_device": str(device),
        "reload_dtype": str(model_dtype(device)),
        "adapter_sha256_at_reload": hashlib.sha256(
            adapter_file.read_bytes()
        ).hexdigest(),
        "probes": len(vs_training),
        "same_argmax_as_training": same_argmax,
        "max_prob_diff_vs_training": max(vs_training),
        "min_prob_diff_vs_base": min(vs_base),
    }


if __name__ == "__main__":
    cap = float(sys.argv[2]) if len(sys.argv) > 2 else None
    print(json.dumps(reload_check(Path(sys.argv[1]), cap)))
