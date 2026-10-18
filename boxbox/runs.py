"""One folder per run with the effective config, a manifest and the metrics."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .config import RunConfig

RUNS_DIR = Path("runs")
SPLITS_FILE = Path("data/splits.json")
SOURCE_DIRS = ("boxbox", "scripts", "configs")
LIBRARIES = ("torch", "transformers", "peft", "trl", "accelerate", "datasets")


def _command(*args: str) -> str:
    result = subprocess.run(list(args), check=False, capture_output=True, text=True)
    return result.stdout.strip()


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def source_sha256(root: Path = Path(".")) -> str:
    """Fingerprint of the code and configs a run uses, committed or not."""
    digest = hashlib.sha256()
    for folder in SOURCE_DIRS:
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def environment() -> dict[str, Any]:
    """Hardware, operating system and library versions of this machine."""
    cpu = platform.processor()
    if platform.system() == "Darwin":
        cpu = _command("sysctl", "-n", "machdep.cpu.brand_string") or cpu
    return {
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu": cpu,
        "ram_gb": round(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1
        ),
        "libraries": {name: importlib.metadata.version(name) for name in LIBRARIES},
    }


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value) if isinstance(value, str) else repr(value)


def config_toml(config: RunConfig) -> str:
    """The effective config as TOML that load_config reads back."""
    lines, tables = [], []
    for key, value in asdict(config).items():
        if isinstance(value, dict):
            tables += [
                "",
                f"[{key}]",
                *(f"{k} = {_toml_value(v)}" for k, v in value.items()),
            ]
        else:
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines + tables) + "\n"


def start_run(
    name: str,
    config: RunConfig,
    device: str,
    dtype: str,
    extra: dict[str, Any] | None = None,
    runs_dir: Path = RUNS_DIR,
) -> Path:
    """Create runs/<date>_<name>/; an existing run folder is never overwritten."""
    run_dir = runs_dir / f"{date.today().isoformat()}_{name}"
    run_dir.mkdir(parents=True)
    (run_dir / "config.toml").write_text(config_toml(config), encoding="utf-8")
    manifest = {
        "git_commit": _command("git", "rev-parse", "HEAD") or None,
        "git_dirty": bool(_command("git", "status", "--porcelain")),
        "source_sha256": source_sha256(),
        "seed": config.seed,
        "model_id": config.model_id,
        "model_revision": config.model_revision,
        "split_manifest_sha256": _sha256(SPLITS_FILE),
        "device": device,
        "dtype": dtype,
        "environment": environment(),
        "extra": extra or {},
        "started": time.time(),
        "config": asdict(config),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return run_dir


def finish_run(run_dir: Path, metrics: dict[str, Any]) -> None:
    """Write metrics.json and add the run duration to the manifest."""
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["duration_seconds"] = round(time.time() - manifest["started"], 1)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
