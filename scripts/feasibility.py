"""Disposable LoRA feasibility run for task 1.5. It is not adapter A.

Usage, from the repository root: python -m scripts.feasibility configs/feasibility.toml
If it prints NO-GO, run the same check on the fallback: configs/feasibility-smollm2.toml
"""

from __future__ import annotations

import copy
import json
import math
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from boxbox.config import RunConfig, load_run_settings
from boxbox.model import cap_mps_memory, get_device, model_dtype
from boxbox.rules import format_answer
from boxbox.runs import finish_run, start_run
from boxbox.training import train_lora

SYSTEM = (
    "You are BoxBox. Answer from the race card only, in exactly two lines: "
    "CALL: BOX, STAY OUT or NO CALL, then WHY: one sentence. /no_think"
)
QUESTIONS = [
    "Should this car box now?",
    "What is the call on this lap?",
    "Box or stay out?",
]


def disposable_rows(count: int, seed: int) -> list[dict[str, Any]]:
    """Varied copies of the fixture cards, labelled by the rule reference."""
    fixtures = json.loads(Path("reference/fixtures.json").read_text(encoding="utf-8"))
    cards = [case["card"] for case in fixtures["conversations"]]
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        card = copy.deepcopy(rng.choice(cards))
        card["tyre_age_laps"] = rng.randint(5, 29)
        if rng.random() < 0.8:
            card["gap_behind"] = {
                "state": "KNOWN",
                "seconds": round(rng.uniform(10, 30), 1),
            }
        question = f"{json.dumps(card)}\n\n{rng.choice(QUESTIONS)}"
        rows.append(
            {
                "prompt": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": question},
                ],
                "completion": [{"role": "assistant", "content": format_answer(card)}],
            }
        )
    return rows


def reload_in_fresh_process(run_dir: Path, max_memory_gb: float) -> dict[str, Any]:
    """Run the reload check in a new Python process with the same memory cap."""
    command = [
        sys.executable,
        "-m",
        "boxbox.training.reload",
        str(run_dir),
        str(max_memory_gb),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip().splitlines()[-1])
    return json.loads(result.stdout.strip().splitlines()[-1])


def go_checks(
    metrics: dict[str, Any],
    limits: dict[str, Any],
    config: RunConfig,
    backend: tuple[str, str],
) -> dict[str, bool]:
    """Extrapolate one adapter's training time and evaluate every go condition."""
    steps = math.ceil(limits["adapter_dialogues"] / config.lora.batch_size)
    minutes = steps * limits["adapter_epochs"] * metrics["seconds_per_step"] / 60
    metrics["adapter_minutes_estimate"] = round(minutes, 1)
    return {
        "time": minutes <= limits["max_adapter_minutes"],
        "memory": metrics["max_memory_gb_at_step_end"] <= limits["max_memory_gb"],
        "only_lora_trainable": metrics["only_lora_trainable"],
        "base_weights_unchanged": metrics["base_weights_unchanged"],
        "same_adapter_file": metrics["adapter_sha256_at_reload"]
        == metrics["adapter_sha256"],
        "same_backend": (metrics["reload_device"], metrics["reload_dtype"]) == backend,
        "same_argmax": metrics["same_argmax_as_training"],
        "reload_matches": metrics["max_prob_diff_vs_training"]
        <= limits["reload_max_prob_diff"],
        "differs_from_base": metrics["min_prob_diff_vs_base"]
        >= limits["min_base_separation"],
    }


def main(config_path: Path) -> int:
    config, limits = load_run_settings(config_path, "feasibility")
    cap_mps_memory(limits["max_memory_gb"])
    device = get_device()
    backend = (str(device), str(model_dtype(device)))
    run_dir = start_run(config_path.stem, config, *backend, extra=limits)
    metrics: dict[str, Any] = {"go": False}
    stage = "train"
    try:
        rows = disposable_rows(limits["rows"], config.seed)
        metrics.update(train_lora(config, rows, run_dir, device))
        stage = "reload"
        metrics.update(reload_in_fresh_process(run_dir, limits["max_memory_gb"]))
        stage = "decide"
        metrics["checks"] = go_checks(metrics, limits, config, backend)
        metrics["go"] = all(metrics["checks"].values())
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
    ) as error:  # kept as the NO-GO reason
        metrics.update(failed_stage=stage, error=repr(error))
    finish_run(run_dir, metrics)
    print(
        json.dumps({k: v for k, v in metrics.items() if k != "train_losses"}, indent=2)
    )
    print(f"{'GO' if metrics['go'] else 'NO-GO'}: {run_dir}")
    return 0 if metrics["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
