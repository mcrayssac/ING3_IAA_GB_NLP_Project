"""Config overrides and run folders."""

from __future__ import annotations

import pytest

from boxbox.config import RunConfig, build_config, load_config
from boxbox.runs import finish_run, start_run


def test_defaults_describe_the_baseline() -> None:
    config = RunConfig()
    assert (config.adapter, config.abstention_share, config.final_test_open) == (
        "none",
        0.0,
        False,
    )


def test_overrides_change_only_what_they_set(tmp_path) -> None:
    path = tmp_path / "b.toml"
    path.write_text(
        'adapter = "B"\nabstention_share = 0.15\n\n[lora]\nr = 8\n', encoding="utf-8"
    )
    config = load_config(path)
    assert (config.adapter, config.abstention_share, config.lora.r) == ("B", 0.15, 8)
    assert config.lora.alpha == RunConfig().lora.alpha


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(TypeError):
        build_config({"lora": {"rank": 8}})


def test_run_folder_is_never_overwritten(tmp_path) -> None:
    path = tmp_path / "c.toml"
    path.write_text("", encoding="utf-8")
    run_dir = start_run("check", RunConfig(), path, "cpu", runs_dir=tmp_path / "runs")
    finish_run(run_dir, {"ok": 1})
    assert {p.name for p in run_dir.iterdir()} == {
        "config.toml",
        "manifest.json",
        "metrics.json",
    }
    with pytest.raises(FileExistsError):
        start_run("check", RunConfig(), path, "cpu", runs_dir=tmp_path / "runs")
