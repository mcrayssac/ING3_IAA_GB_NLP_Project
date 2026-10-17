"""Disposable LoRA feasibility run for task 1.5. It is not adapter A.

Usage, from the repository root: python -m scripts.feasibility configs/feasibility.toml
"""

from __future__ import annotations

import copy
import json
import math
import random
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from boxbox.config import RunConfig, build_config
from boxbox.model import cap_mps_memory, get_device
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


def decide_go(
    metrics: dict[str, Any], limits: dict[str, Any], config: RunConfig
) -> bool:
    """Extrapolate one adapter's training time and apply the go rule."""
    steps = math.ceil(limits["adapter_dialogues"] / config.lora.batch_size)
    minutes = steps * limits["adapter_epochs"] * metrics["seconds_per_step"] / 60
    metrics["adapter_minutes_estimate"] = round(minutes, 1)
    return (
        minutes <= limits["max_adapter_minutes"]
        and metrics["peak_memory_gb"] <= limits["max_memory_gb"]
        and metrics["only_lora_trainable"]
        and metrics["base_weight_unchanged"]
        and metrics["same_argmax_as_training"]
        and metrics["max_prob_diff_vs_training"] <= limits["reload_max_prob_diff"]
    )


def main(config_path: Path) -> int:
    settings = tomllib.loads(config_path.read_text(encoding="utf-8"))
    limits = settings.pop("feasibility")
    config = build_config(settings)
    cap_mps_memory(limits["max_memory_gb"])
    device = get_device()
    run_dir = start_run("feasibility", config, config_path, str(device))
    metrics = train_lora(
        config, disposable_rows(limits["rows"], config.seed), run_dir, device
    )
    reload = subprocess.run(
        [sys.executable, "-m", "boxbox.training.reload", str(run_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    metrics.update(json.loads(reload.stdout.strip().splitlines()[-1]))
    metrics["go"] = decide_go(metrics, limits, config)
    finish_run(run_dir, metrics)
    print(
        json.dumps({k: v for k, v in metrics.items() if k != "train_losses"}, indent=2)
    )
    print(f"{'GO' if metrics['go'] else 'NO-GO'}: {run_dir}")
    return 0 if metrics["go"] else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
