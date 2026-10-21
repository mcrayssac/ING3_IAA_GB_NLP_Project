"""Freeze of the retained versions (3.5), on the repository's own files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import freeze

DECISION = (
    "https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/19#issuecomment-1"
)


@pytest.fixture
def clean_git(monkeypatch):
    answers = {
        ("status", "--porcelain", "--untracked-files=no"): "",
        ("rev-parse", "HEAD"): "c0ffee",
    }
    monkeypatch.setattr(freeze, "git", lambda *args: answers[args])


@pytest.fixture
def copy(tmp_path, monkeypatch) -> Path:
    """A copy of the frozen files and configs, so tests can change them."""
    for folder in ("configs", "reference", "data/corpus", "boxbox/rules", "docs"):
        shutil.copytree(folder, tmp_path / folder, dirs_exist_ok=True)
    shutil.copy("data/splits.json", tmp_path / "data/splits.json")
    (tmp_path / freeze.FREEZE).unlink(missing_ok=True)  # each test records its own
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_record_names_every_version_file_and_rule(clean_git, copy) -> None:
    out = freeze.record(DECISION, DECISION, "Maxime")
    frozen = json.loads(out.read_text(encoding="utf-8"))
    assert set(frozen["versions"]) == {"baseline", "A", "B"}
    assert frozen["versions"]["A"]["adapter_sha256"].startswith("3322b5b3158e")
    assert frozen["versions"]["B"]["adapter_sha256"].startswith("70423a7d4aa7")
    assert frozen["versions"]["B"]["abstention_share"] == 0.15
    assert frozen["shared_inference"]["decoding"]["max_new_tokens"] == 64
    assert frozen["final_test_open"] is False
    assert frozen["frozen_at"].endswith("+02:00") or frozen["frozen_at"].endswith(
        "+01:00"
    )
    assert set(frozen["files"]) == {p.as_posix() for p in freeze.FROZEN_FILES}
    assert freeze.check(out) == []
    with pytest.raises(FileExistsError):
        freeze.record(DECISION, DECISION, "Maxime")


def test_check_reports_a_changed_file_or_config(clean_git, copy) -> None:
    out = freeze.record(DECISION, DECISION, "Maxime")
    protocol = Path("docs/evaluation-protocol.md")
    protocol.write_text(
        protocol.read_text(encoding="utf-8") + "\nlater rule\n", encoding="utf-8"
    )
    config = Path("configs/adapter-b.toml")
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "max_new_tokens = 64", "max_new_tokens = 96"
        ),
        encoding="utf-8",
    )
    problems = freeze.check(out)
    assert "docs/evaluation-protocol.md changed since the freeze" in problems
    assert any(p.startswith("B:") and "changed since" in p for p in problems)


def test_record_refuses_a_dirty_tree_bad_links_or_an_open_final(
    copy, monkeypatch
) -> None:
    monkeypatch.setattr(freeze, "git", lambda *args: " M scripts/x.py")
    with pytest.raises(ValueError, match="clean tree"):
        freeze.build(DECISION, DECISION, "Maxime")
    monkeypatch.setattr(freeze, "git", lambda *args: "")
    with pytest.raises(ValueError, match="GitHub link"):
        freeze.build("team said yes", DECISION, "Maxime")
    with pytest.raises(ValueError, match="reviewer"):
        freeze.build(DECISION, DECISION, " ")
    selection = Path("configs/adapter-a-selection.json")
    config = Path("configs/adapter-a.toml")
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "final_test_open = false", "final_test_open = true"
        ),
        encoding="utf-8",
    )
    data = json.loads(selection.read_text(encoding="utf-8"))
    data["config_sha256"] = freeze.sha256(config)
    selection.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="opens the final test"):
        freeze.build(DECISION, DECISION, "Maxime")


def test_the_three_versions_share_inference_settings() -> None:
    from boxbox.config import load_config

    configs = [
        load_config(f)
        for f in (
            "configs/baseline-selected.toml",
            "configs/adapter-a.toml",
            "configs/adapter-b.toml",
        )
    ]
    assert len({(c.prompt_variant, c.history_turns, c.decoding) for c in configs}) == 1
