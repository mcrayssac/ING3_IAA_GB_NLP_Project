"""LoRA training on a frozen base model."""

from __future__ import annotations

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
from boxbox.model import load_model, memory_gb

PROBE_WEIGHT = (
    "layers.0.mlp.down_proj"  # one base matrix, compared before and after training
)


class StepMeter(TrainerCallback):
    """Time every optimizer step and keep the highest accelerator memory."""

    def __init__(self, device: torch.device) -> None:
        self.device = device
        self.times: list[float] = []
        self.peak_gb = 0.0
        self._start = 0.0

    def on_step_begin(self, args, state, control, **kwargs) -> None:
        self._start = time.perf_counter()

    def on_step_end(self, args, state, control, **kwargs) -> None:
        if self.device.type == "mps":
            torch.mps.synchronize()
        self.times.append(time.perf_counter() - self._start)
        self.peak_gb = max(self.peak_gb, memory_gb(self.device))


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


def _probe(model: PreTrainedModel) -> torch.Tensor:
    name = next(
        n for n, _ in model.named_parameters() if PROBE_WEIGHT in n and "lora" not in n
    )
    return model.get_parameter(name).detach().cpu().clone()


def _save_reference_logits(model, tokenizer, prompt, run_dir: Path, device) -> None:
    """Store the adapted and base logits on one prompt for the fresh-process reload check."""
    ids = tokenizer.apply_chat_template(
        prompt, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    )["input_ids"].to(device)
    with torch.no_grad():
        adapted = model(ids).logits[0, -1].float().cpu()
        with model.disable_adapter():
            base = model(ids).logits[0, -1].float().cpu()
    torch.save(
        {"input_ids": ids.cpu(), "adapted": adapted, "base": base},
        run_dir / "reference.pt",
    )


def train_lora(
    config: RunConfig, rows: list[dict[str, Any]], run_dir: Path, device: torch.device
) -> dict[str, Any]:
    """Train a LoRA adapter on prompt/completion rows and save it in run_dir/adapter."""
    model, tokenizer = load_model(config, device)
    before = _probe(model)
    meter = StepMeter(device)
    trainer = _trainer(config, model, tokenizer, rows, run_dir, meter)
    trainer.train()
    adapted = trainer.model.eval()
    adapted.save_pretrained(run_dir / "adapter")
    _save_reference_logits(adapted, tokenizer, rows[0]["prompt"], run_dir, device)
    trainable = [
        (n, p.numel()) for n, p in adapted.named_parameters() if p.requires_grad
    ]
    warm = meter.times[3:] or meter.times  # the first steps include MPS warm-up
    return {
        "steps": len(meter.times),
        "seconds_per_step": round(statistics.median(warm), 3),
        "peak_memory_gb": round(meter.peak_gb, 2),
        "trainable_params": sum(size for _, size in trainable),
        "total_params": sum(p.numel() for p in adapted.parameters()),
        "only_lora_trainable": all("lora_" in name for name, _ in trainable),
        "base_weight_unchanged": torch.equal(before, _probe(adapted)),
        "train_losses": [
            log["loss"] for log in trainer.state.log_history if "loss" in log
        ],
    }
