"""Freeze the retained versions before the final test (task 3.5).

Usage, from the repository root:
    python -m scripts.freeze record --decision URL --acceptance URL --reviewer NAME
    python -m scripts.freeze check

`record` writes `configs/freeze.json` once: the time, the commit, and the hash of
every file that defines the retained versions and how they are scored (configs,
prompt, selection files, adapter weights and Hub revisions, corpora, splits,
evaluation protocol, fixtures and policy). It refuses a dirty working tree, an
existing freeze, versions that do not share the model, prompt, history and
decoding, and a config with the final test open. `check` recomputes every hash and
fails on any difference, so later tasks (4.x) can prove they use the frozen
versions. It loads no model and opens no final card.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from boxbox.config import load_config

FREEZE = Path("configs/freeze.json")
PARIS = ZoneInfo("Europe/Paris")
SELECTIONS = {
    "baseline": Path("configs/baseline-selection.json"),
    "A": Path("configs/adapter-a-selection.json"),
    "B": Path("configs/adapter-b-selection.json"),
}
PROTOCOL = Path("docs/evaluation-protocol.md")
# The files that decide what the retained versions see and how answers are scored.
FROZEN_FILES = (
    PROTOCOL,
    Path("reference/evaluation-fixtures.json"),
    Path("reference/fixtures.json"),
    Path("boxbox/rules/decision.py"),
    Path("docs/race-card-contract.md"),
    Path("data/splits.json"),
    Path("data/corpus/manifest.json"),
    Path("data/corpus/A_train.jsonl"),
    Path("data/corpus/B_train.jsonl"),
    Path("data/corpus/B_pairs.json"),
    Path("data/corpus/validation.jsonl"),
    Path("data/corpus/mini_test.jsonl"),
    Path("data/corpus/exposure.json"),
)
SHARED = ("model_id", "model_revision", "prompt_variant", "history_turns", "decoding")
URL = re.compile(r"https://github\.com/\S+")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _selection(version: str, path: Path) -> dict[str, Any]:
    """One retained version from its selection file, refused if a recorded hash differs."""
    selection = json.loads(path.read_text(encoding="utf-8"))
    for key in ("config", "prompt"):
        file = Path(selection[f"{key}_file"])
        if sha256(file) != selection[f"{key}_sha256"]:
            raise ValueError(f"{file} changed since {path} was recorded")
    config = load_config(selection["config_file"])
    if config.final_test_open:
        raise ValueError(f"{selection['config_file']} opens the final test")
    if config.adapter != ("none" if version == "baseline" else version):
        raise ValueError(f"{selection['config_file']} is not version {version}")
    entry = {
        "selection_file": path.as_posix(),
        "selection_sha256": sha256(path),
        "config_file": selection["config_file"],
        "config_sha256": selection["config_sha256"],
        "prompt_file": selection["prompt_file"],
        "prompt_sha256": selection["prompt_sha256"],
        "adapter": config.adapter,
        "abstention_share": config.abstention_share,
    }
    if version == "baseline":
        entry["chat_template_sha256"] = selection["chat_template_sha256"]
        entry["template_options"] = selection["template_options"]
    else:
        entry |= {
            key: selection[key]
            for key in ("version", "seed", "epoch", "step", "adapter_sha256", "hub")
        }
        entry["checkpoint"] = f"{selection['run']}/{selection['checkpoint']}"
        entry["lora"] = asdict(config.lora)
    return entry


def build(decision: str, acceptance: str, reviewer: str) -> dict[str, Any]:
    """The freeze record of the current checkout; nothing is written."""
    for name, link in (("decision", decision), ("acceptance", acceptance)):
        if not URL.fullmatch(link):
            raise ValueError(f"--{name} must be a GitHub link to the team decision")
    if not reviewer.strip():
        raise ValueError("--reviewer must name the teammate who reviews the freeze")
    status = git("status", "--porcelain", "--untracked-files=no")
    if status:
        raise ValueError(
            f"commit or stash first; the freeze needs a clean tree:\n{status}"
        )
    versions = {v: _selection(v, p) for v, p in SELECTIONS.items()}
    configs = {v: load_config(e["config_file"]) for v, e in versions.items()}
    for field in SHARED:
        values = {v: asdict(c)[field] for v, c in configs.items()}
        if len({json.dumps(x, sort_keys=True) for x in values.values()}) != 1:
            raise ValueError(f"the retained versions differ in {field}: {values}")
    if len({e["prompt_sha256"] for e in versions.values()}) != 1:
        raise ValueError("the retained versions do not share one prompt file")
    baseline = configs["baseline"]
    return {
        "task": "3.5",
        "frozen_at": datetime.now(PARIS).isoformat(timespec="seconds"),
        "git_commit": git("rev-parse", "HEAD"),
        "decision_record": decision,
        "protocol_acceptance_record": acceptance,
        "reviewer": reviewer.strip(),
        "model": {"id": baseline.model_id, "revision": baseline.model_revision},
        "shared_inference": {
            "prompt_variant": baseline.prompt_variant,
            "history_turns": baseline.history_turns,
            "history_mode": "fixed",
            "decoding": asdict(baseline.decoding),
            "chat_template_date": baseline.chat_template_date,
        },
        "versions": versions,
        "files": {path.as_posix(): sha256(path) for path in FROZEN_FILES},
        "final_test_open": False,
        "rules": [
            (
                "No new experiment after the freeze: no new corpus, prompt, "
                "checkpoint, decoding or protocol choice."
            ),
            (
                "A correction that changes outputs needs an explicit team decision "
                "and a new freeze before any final evaluation."
            ),
            "The final test stays closed until 4.1 opens it under this freeze.",
        ],
    }


def record(decision: str, acceptance: str, reviewer: str, out: Path = FREEZE) -> Path:
    if out.exists():
        raise FileExistsError(f"{out} exists; a freeze is never overwritten")
    frozen = build(decision, acceptance, reviewer)
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(frozen, indent=2) + "\n")
    return out


def check(path: Path = FREEZE) -> list[str]:
    """Every difference between the freeze record and the current files."""
    frozen = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for name, digest in frozen["files"].items():
        if not Path(name).exists():
            problems.append(f"{name} is missing")
        elif sha256(Path(name)) != digest:
            problems.append(f"{name} changed since the freeze")
    for version, entry in frozen["versions"].items():
        try:
            current = _selection(version, Path(entry["selection_file"]))
        except (OSError, ValueError) as error:
            problems.append(f"{version}: {error}")
            continue
        if current != entry:
            problems.append(f"{version}: its selection differs from the freeze")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record", help="write configs/freeze.json once")
    rec.add_argument("--decision", required=True, help="link to the team decision")
    rec.add_argument("--acceptance", required=True, help="link to protocol acceptance")
    rec.add_argument("--reviewer", required=True, help="teammate reviewing the freeze")
    commands.add_parser("check", help="verify the current files against the freeze")
    args = parser.parse_args(argv)
    if args.command == "record":
        print(
            json.dumps(
                json.loads(
                    record(args.decision, args.acceptance, args.reviewer).read_text()
                ),
                indent=2,
            )
        )
        return 0
    problems = check()
    for problem in problems:
        print(problem, file=sys.stderr)
    print("freeze intact" if not problems else f"{len(problems)} differences")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
