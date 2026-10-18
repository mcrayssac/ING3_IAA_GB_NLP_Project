"""LoRA training on a frozen base model."""

from __future__ import annotations

import hashlib
import statistics
import time
from pathlib import Path
from typing import Any

import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import PreTrainedModel, TrainerCallback
from trl import SFTConfig, SFTTrainer

from boxbox.config import RunConfig
from boxbox.model import load_model, memory_gb, synchronize

REFERENCE_PROBES = 8  # prompts whose logits the fresh-process reload must reproduce


class StepMeter(TrainerCallback):
    """Time every optimizer step and read accelerator memory at each step end."""

    def __init__(self, device: torch.device) -> None:
        self.device = device
        self.times: list[float] = []
        self.max_gb = 0.0
        self._start = 0.0

    def on_step_begin(self, args, state, control, **kwargs) -> None:
        synchronize(self.device)
        self._start = time.perf_counter()

    def on_step_end(self, args, state, control, **kwargs) -> None:
        synchronize(self.device)
        self.times.append(time.perf_counter() - self._start)
        self.max_gb = max(self.max_gb, memory_gb(self.device))


def _trainer(
    config: RunConfig, model, tokenizer, rows, run_dir: Path, meter
) -> SFTTrainer:
    lora = config.lora
    args = SFTConfig(
        output_dir=str(run_dir / "trainer"),
        per_device_train_batch_size=lora.batch_size,
        learning_rate=lora.learning_rate,
        num_train_epochs=lora.epochs,
        max_steps=lora.max_steps,
        max_length=lora.max_length,
        completion_only_loss=True,
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        seed=config.seed,
    )
    peft_config = LoraConfig(
        r=lora.r,
        lora_alpha=lora.alpha,
        lora_dropout=lora.dropout,
        target_modules=lora.target_modules,
        task_type="CAUSAL_LM",
    )
    return SFTTrainer(
        model=model,
        args=args,
        train_dataset=Dataset.from_list(rows),
        processing_class=tokenizer,
        peft_config=peft_config,
        callbacks=[meter],
    )


def base_weights_sha256(model: PreTrainedModel) -> str:
    """sha256 of every non-LoRA weight, named as in the model before PEFT wraps it."""
    weights = {
        name.removeprefix("base_model.model.").replace(".base_layer", ""): param
        for name, param in model.named_parameters()
        if "lora_" not in name
    }
    digest = hashlib.sha256()
    for name in sorted(weights):
        digest.update(name.encode())
        tensor = weights[name].detach().cpu().contiguous()
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def _save_reference(model, tokenizer, prompts, run_dir: Path, device) -> None:
    """Store adapted and base next-token logits for the fresh-process reload check."""
    saved: dict[str, list[torch.Tensor]] = {"input_ids": [], "adapted": [], "base": []}
    for prompt in prompts:
        ids = tokenizer.apply_chat_template(
            prompt, add_generation_prompt=True, return_dict=True, return_tensors="pt"
        )["input_ids"].to(device)
        with torch.no_grad():
            saved["adapted"].append(model(ids).logits[0, -1].float().cpu())
            with model.disable_adapter():
                saved["base"].append(model(ids).logits[0, -1].float().cpu())
        saved["input_ids"].append(ids.cpu())
    torch.save(saved, run_dir / "reference.pt")


def train_lora(
    config: RunConfig, rows: list[dict[str, Any]], run_dir: Path, device: torch.device
) -> dict[str, Any]:
    """Train a LoRA adapter on prompt/completion rows and save it in run_dir/adapter."""
    model, tokenizer = load_model(config, device)
    before = base_weights_sha256(model)
    meter = StepMeter(device)
    trainer = _trainer(config, model, tokenizer, rows, run_dir, meter)
    trainer.train()
    adapted = trainer.model.eval()
    adapted.save_pretrained(run_dir / "adapter")
    prompts = [row["prompt"] for row in rows[:REFERENCE_PROBES]]
    _save_reference(adapted, tokenizer, prompts, run_dir, device)
    trainable = [
        (n, p.numel()) for n, p in adapted.named_parameters() if p.requires_grad
    ]
    adapter_file = run_dir / "adapter" / "adapter_model.safetensors"
    warm = meter.times[3:] or meter.times  # the first steps include warm-up
    return {
        "steps": len(meter.times),
        "seconds_per_step": round(statistics.median(warm), 3),
        "max_memory_gb_at_step_end": round(meter.max_gb, 2),
        "trainable_params": sum(size for _, size in trainable),
        "total_params": sum(p.numel() for p in adapted.parameters()),
        "only_lora_trainable": all("lora_" in name for name, _ in trainable),
        "base_weights_unchanged": before == base_weights_sha256(adapted),
        "adapter_sha256": hashlib.sha256(adapter_file.read_bytes()).hexdigest(),
        "train_losses": [
            log["loss"] for log in trainer.state.log_history if "loss" in log
        ],
    }
