"""One folder per run with the config used, a manifest and the metrics."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .config import RunConfig

RUNS_DIR = Path("runs")
SPLITS_FILE = Path("data/splits.json")


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True
    )
    return result.stdout.strip() or None


def _splits_hash() -> str | None:
    if not SPLITS_FILE.exists():
        return None
    return hashlib.sha256(SPLITS_FILE.read_bytes()).hexdigest()


def start_run(
    name: str,
    config: RunConfig,
    config_path: Path,
    device: str,
    runs_dir: Path = RUNS_DIR,
) -> Path:
    """Create runs/<date>_<name>/; an existing run folder is never overwritten."""
    run_dir = runs_dir / f"{date.today().isoformat()}_{name}"
    run_dir.mkdir(parents=True)
    shutil.copyfile(config_path, run_dir / "config.toml")
    manifest = {
        "git_commit": _git_commit(),
        "seed": config.seed,
        "model_id": config.model_id,
        "model_revision": config.model_revision,
        "split_manifest_sha256": _splits_hash(),
        "device": device,
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
