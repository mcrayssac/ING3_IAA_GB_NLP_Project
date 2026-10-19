"""Every setting the study varies. The defaults describe the baseline."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Decoding:
    max_new_tokens: int = 64
    do_sample: bool = False
    temperature: float = 1.0
    top_p: float = 1.0
    max_context_tokens: int = 8192
    max_generation_seconds: float = 30.0


@dataclass(frozen=True)
class Lora:
    r: int = 16
    alpha: int = 32
    dropout: float = 0.0
    target_modules: str = "all-linear"
    learning_rate: float = 2e-4
    epochs: int = 3
    batch_size: int = 4
    max_length: int = 1024
    max_steps: int = -1  # -1 trains for `epochs`


@dataclass(frozen=True)
class RunConfig:
    model_id: str = "HuggingFaceTB/SmolLM3-3B"
    model_revision: str = "a07cc9a04f16550a088caea529712d1d335b0ac1"
    data_source: str = "openf1"
    abstention_share: float = 0.0  # 0 for A, 0.15 for B
    prompt_variant: str = "zero-shot"
    history_turns: int = 3
    decoding: Decoding = field(default_factory=Decoding)
    adapter: str = "none"  # none, A or B
    lora: Lora = field(default_factory=Lora)
    seed: int = 2026
    final_test_open: bool = False
    mps_memory_cap_gb: float = 20.0
    # Reference date used for reproducible template metadata.
    chat_template_date: str = "2026-10-19"


def build_config(overrides: dict[str, Any]) -> RunConfig:
    """Apply nested overrides to the defaults; an unknown key raises TypeError."""
    values = dict(overrides)
    for section in ("decoding", "lora"):
        if section in values:
            values[section] = replace(getattr(RunConfig(), section), **values[section])
    return replace(RunConfig(), **values)


def load_config(path: str | Path) -> RunConfig:
    """Read a TOML file that sets only what differs from the baseline."""
    return build_config(tomllib.loads(Path(path).read_text(encoding="utf-8")))


def load_run_settings(
    path: str | Path, section: str
) -> tuple[RunConfig, dict[str, Any]]:
    """Read a TOML file whose `section` table holds settings outside RunConfig."""
    values = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    extra = values.pop(section, {})
    return build_config(values), extra
