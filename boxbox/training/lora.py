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


class ReferenceSaver(TrainerCallback):
    """At every saved checkpoint, store the logits its fresh-process reload must match."""

    def __init__(self, tokenizer, rows, device) -> None:
        self.tokenizer, self.rows, self.device = tokenizer, rows, device

    def on_save(self, args, state, control, model=None, **kwargs) -> None:
        folder = Path(args.output_dir) / f"checkpoint-{state.global_step}"
        _save_reference(model, self.tokenizer, self.rows, folder, self.device)


def _trainer(
    config: RunConfig, model, tokenizer, rows, run_dir: Path, callbacks, eval_rows=None
) -> SFTTrainer:
    lora = config.lora
    every_epoch = (
        "epoch" if eval_rows else "no"
    )  # checkpoints only when they can be chosen
    args = SFTConfig(
        output_dir=str(run_dir / "trainer"),
        per_device_train_batch_size=lora.batch_size,
        per_device_eval_batch_size=lora.batch_size,
        gradient_accumulation_steps=lora.gradient_accumulation,
        learning_rate=lora.learning_rate,
        num_train_epochs=lora.epochs,
        max_steps=lora.max_steps,
        max_length=lora.max_length,
        completion_only_loss=True,
        logging_steps=1,
        eval_strategy=every_epoch,
        save_strategy=every_epoch,
        save_only_model=True,
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
        eval_dataset=Dataset.from_list(eval_rows) if eval_rows else None,
        processing_class=tokenizer,
        peft_config=peft_config,
        callbacks=callbacks,
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


def _prompt_ids(tokenizer, row: dict[str, Any]) -> torch.Tensor:
    """The prompt part of a row: the pre-tokenized one, or the template's rendering."""
    if "input_ids" in row:
        return torch.tensor([row["input_ids"][: row["completion_mask"].index(1)]])
    return tokenizer.apply_chat_template(
        row["prompt"], add_generation_prompt=True, return_dict=True, return_tensors="pt"
    )["input_ids"]


def _save_reference(model, tokenizer, rows, folder: Path, device) -> None:
    """Store adapted and base next-token logits for the fresh-process reload check."""
    saved: dict[str, list[torch.Tensor]] = {"input_ids": [], "adapted": [], "base": []}
    training = model.training
    model.eval()
    for row in rows[:REFERENCE_PROBES]:
        ids = _prompt_ids(tokenizer, row).to(device)
        with torch.no_grad():
            saved["adapted"].append(model(ids).logits[0, -1].float().cpu())
            with model.disable_adapter():
                saved["base"].append(model(ids).logits[0, -1].float().cpu())
        saved["input_ids"].append(ids.cpu())
    model.train(training)
    folder.mkdir(parents=True, exist_ok=True)
    torch.save(saved, folder / "reference.pt")


def _checkpoints(run_dir: Path, history: list[dict]) -> list[dict[str, Any]]:
    """Every saved checkpoint with its epoch, step and validation loss."""
    evals = {round(log["epoch"]): log for log in history if "eval_loss" in log}
    found = []
    for folder in sorted(
        (run_dir / "trainer").glob("checkpoint-*"),
        key=lambda f: int(f.name.split("-")[1]),
    ):
        step = int(folder.name.split("-")[1])
        epoch = len(found) + 1
        found.append(
            {
                "epoch": epoch,
                "step": step,
                "folder": str(folder.relative_to(run_dir)),
                "eval_loss": evals.get(epoch, {}).get("eval_loss"),
            }
        )
    return found


def train_lora(
    config: RunConfig,
    rows: list[dict[str, Any]],
    run_dir: Path,
    device: torch.device,
    eval_rows: list[dict[str, Any]] | None = None,
    loaded: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    """Train a LoRA adapter and save it in run_dir/adapter.

    Rows are TRL prompt/completion rows or pre-tokenized `input_ids` and
    `completion_mask`. With `eval_rows`, every epoch is evaluated and saved as a
    checkpoint with its reload reference. `loaded` reuses a loaded model and tokenizer.
    """
    model, tokenizer = loaded or load_model(config, device)
    before = base_weights_sha256(model)
    meter = StepMeter(device)
    callbacks = [meter] + (
        [ReferenceSaver(tokenizer, rows, device)] if eval_rows else []
    )
    trainer = _trainer(config, model, tokenizer, rows, run_dir, callbacks, eval_rows)
    trainer.train()
    adapted = trainer.model.eval()
    adapted.save_pretrained(run_dir / "adapter")
    _save_reference(adapted, tokenizer, rows, run_dir, device)
    trainable = [
        (n, p.numel()) for n, p in adapted.named_parameters() if p.requires_grad
    ]
    adapter_file = run_dir / "adapter" / "adapter_model.safetensors"
    warm = meter.times[3:] or meter.times  # the first steps include warm-up
    history = trainer.state.log_history
    return {
        "steps": len(meter.times),
        "seconds_per_step": round(statistics.median(warm), 3),
        "max_memory_gb_at_step_end": round(meter.max_gb, 2),
        "trainable_params": sum(size for _, size in trainable),
        "total_params": sum(p.numel() for p in adapted.parameters()),
        "only_lora_trainable": all("lora_" in name for name, _ in trainable),
        "base_weights_unchanged": before == base_weights_sha256(adapted),
        "adapter_sha256": hashlib.sha256(adapter_file.read_bytes()).hexdigest(),
        "train_losses": [log["loss"] for log in history if "loss" in log],
        "eval_losses": [
            {"epoch": log["epoch"], "step": log["step"], "eval_loss": log["eval_loss"]}
            for log in history
            if "eval_loss" in log
        ],
        "checkpoints": _checkpoints(run_dir, history) if eval_rows else [],
        "tokens_per_epoch": sum(len(row.get("input_ids", ())) for row in rows),
        "answer_tokens_per_epoch": sum(
            sum(row.get("completion_mask", ())) for row in rows
        ),
    }
