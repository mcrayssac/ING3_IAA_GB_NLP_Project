"""Read a built corpus file once it matches its manifest and the current rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from boxbox.rules import POLICY_VERSION

CORPUS_DIR = Path("data/corpus")


def load_corpus(name: str, folder: Path = CORPUS_DIR) -> list[dict[str, Any]]:
    """Items of `A_train`, `validation` or `mini_test`; raises if the file or policy differ."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["policy_version"] != POLICY_VERSION:
        raise ValueError(
            f"corpus built on policy {manifest['policy_version']}, the rule is "
            f"{POLICY_VERSION}: run python -m scripts.build_corpus build"
        )
    data = (folder / f"{name}.jsonl").read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["files"][f"{name}.jsonl"]["sha256"]:
        raise ValueError(f"{name}.jsonl differs from manifest.json: rebuild the corpus")
    return [json.loads(line) for line in data.decode("utf-8").splitlines()]
