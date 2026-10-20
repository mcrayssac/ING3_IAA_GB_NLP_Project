"""Find a selected adapter, locally or on the Hub, and check it is the one recorded."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from boxbox.config import RunConfig, load_config

ADAPTER_A = Path("configs/adapter-a-selection.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_adapter(
    selection_file: Path = ADAPTER_A, runs_dir: Path = Path("runs")
) -> tuple[RunConfig, Path, str]:
    """Config, checkpoint folder and prompt of a selected adapter, refused if a hash differs.

    The local run folder is used when it exists, otherwise the recorded Hub revision.
    The config carries the adapter's own seed, so run records name the right one. The
    prompt is the one the adapter was trained on: without it the engine would fall back
    to the default instructions.
    """
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    config_file = Path(selection["config_file"])
    prompt_file = Path(selection["prompt_file"])
    if _sha256(config_file) != selection["config_sha256"]:
        raise ValueError(f"{config_file} changed since the adapter was selected")
    if _sha256(prompt_file) != selection["prompt_sha256"]:
        raise ValueError(f"{prompt_file} changed since the adapter was trained")
    folder = runs_dir / selection["run"] / selection["checkpoint"]
    if not folder.is_dir():
        hub = selection.get("hub")
        if not hub:
            raise FileNotFoundError(f"{folder} is missing and no Hub copy is recorded")
        from huggingface_hub import snapshot_download

        local = snapshot_download(
            hub["repo"], revision=hub["revision"], allow_patterns=f"{hub['folder']}/*"
        )
        folder = Path(local) / hub["folder"]
    if _sha256(folder / "adapter_model.safetensors") != selection["adapter_sha256"]:
        raise ValueError(f"the adapter in {folder} is not the selected one")
    config = replace(load_config(config_file), seed=selection["seed"])
    return config, folder, prompt_file.read_text(encoding="utf-8")
