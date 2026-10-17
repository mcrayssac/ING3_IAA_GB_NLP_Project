"""Device choice and model loading at the pinned revision."""

from __future__ import annotations

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, PreTrainedModel

from boxbox.config import RunConfig


def get_device() -> torch.device:
    """Pick CUDA, then MPS, then CPU, so the same code runs on a Mac or a cloud GPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def cap_mps_memory(gigabytes: float) -> None:
    """Make MPS allocations fail above `gigabytes` instead of swapping."""
    if torch.backends.mps.is_available():
        fraction = gigabytes * 1e9 / torch.mps.recommended_max_memory()
        torch.mps.set_per_process_memory_fraction(fraction)


def memory_gb(device: torch.device) -> float:
    """Memory currently held by the accelerator driver, in GB."""
    if device.type == "mps":
        return torch.mps.driver_allocated_memory() / 1e9
    if device.type == "cuda":
        return torch.cuda.max_memory_allocated() / 1e9
    return 0.0


def load_model(
    config: RunConfig,
    device: torch.device | None = None,
    attn_implementation: str | None = None,
) -> tuple[PreTrainedModel, AutoTokenizer]:
    """Load the tokenizer and the bf16 causal model at the config's revision."""
    tokenizer = AutoTokenizer.from_pretrained(
        config.model_id, revision=config.model_revision
    )
    model = AutoModelForCausalLM.from_pretrained(
        config.model_id,
        revision=config.model_revision,
        dtype=torch.bfloat16,
        attn_implementation=attn_implementation,
    )
    return model.to(device or get_device()).eval(), tokenizer
