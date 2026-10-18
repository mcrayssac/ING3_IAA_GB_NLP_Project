"""Device choice, dtype and model loading at the pinned revision."""

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


def model_dtype(device: torch.device) -> torch.dtype:
    """bf16 on MPS and on CUDA GPUs that support it, fp16 on older CUDA GPUs, fp32 on CPU.

    Only MPS with bf16 has been measured (task 1.5).
    """
    if device.type == "cuda":
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    return torch.bfloat16 if device.type == "mps" else torch.float32


def cap_mps_memory(gigabytes: float) -> None:
    """Make MPS allocations fail above `gigabytes` instead of swapping."""
    if torch.backends.mps.is_available():
        fraction = gigabytes * 1e9 / torch.mps.recommended_max_memory()
        torch.mps.set_per_process_memory_fraction(fraction)


def synchronize(device: torch.device) -> None:
    """Wait for queued accelerator work, so a timer measures finished work."""
    if device.type == "mps":
        torch.mps.synchronize()
    elif device.type == "cuda":
        torch.cuda.synchronize()


def memory_gb(device: torch.device) -> float:
    """MPS: memory the Metal driver holds now. CUDA: highest allocation so far. In GB."""
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
    """Load the tokenizer and the causal model at the config's revision."""
    device = device or get_device()
    tokenizer = AutoTokenizer.from_pretrained(
        config.model_id, revision=config.model_revision
    )
    model = AutoModelForCausalLM.from_pretrained(
        config.model_id,
        revision=config.model_revision,
        dtype=model_dtype(device),
        attn_implementation=attn_implementation,
    )
    return model.to(device).eval(), tokenizer
