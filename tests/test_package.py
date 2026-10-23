"""Adapter archive and reader checks of the delivery (5.2), with small fake weights."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts import package

WEIGHTS = {"A": b"weights of A", "B": b"weights of B"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def repo(tmp_path, monkeypatch) -> dict:
    """A copy of the configs and cards whose freeze and selections name fake weights."""
    shutil.copytree("configs", tmp_path / "configs")
    shutil.copytree("docs", tmp_path / "docs")
    record = package.frozen()
    for version, data in WEIGHTS.items():
        record["versions"][version]["adapter_sha256"] = _sha(data)
        selection = tmp_path / record["versions"][version]["selection_file"]
        chosen = json.loads(selection.read_text(encoding="utf-8"))
        chosen["adapter_sha256"] = _sha(data)
        selection.write_text(json.dumps(chosen), encoding="utf-8")
    (tmp_path / package.FREEZE).write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return record


def _hub_copy(root: Path, record: dict, version: str, suffix: str = "") -> Path:
    """A local copy of a Hub repo, file names as a browser download may change them."""
    folder = root / version / record["versions"][version]["hub"]["folder"]
    folder.mkdir(parents=True)
    lora = record["versions"][version]["lora"]
    config = {
        "peft_type": "LORA",
        "base_model_name_or_path": record["model"]["id"],
        "r": lora["r"],
        "lora_alpha": lora["alpha"],
        "lora_dropout": lora["dropout"],
    }
    (folder / f"adapter_config{suffix}.json").write_text(json.dumps(config))
    (folder / f"adapter_model{suffix}.safetensors").write_bytes(WEIGHTS[version])
    return root / version


def _sources(tmp_path: Path, record: dict) -> dict:
    return {
        "A": _hub_copy(tmp_path / "hub", record, "A"),
        "B": _hub_copy(tmp_path / "hub", record, "B", " (1)"),
    }


def test_archive_puts_frozen_weights_where_selected_adapter_reads(
    repo, tmp_path
) -> None:
    entries = package.archive_entries(_sources(tmp_path, repo), repo)
    for version in package.ADAPTERS:
        run = f"runs/{repo['versions'][version]['checkpoint']}"
        assert entries[f"{run}/adapter_model.safetensors"] == WEIGHTS[version]
        assert f"{run}/adapter_config.json" in entries
    assert all(name.startswith("runs/") for name in entries)
    manifest = json.loads(entries["runs/boxbox-adapters/manifest.json"])
    assert manifest["licence"] == package.NC_SA
    assert manifest["versions"]["B"]["seed"] == 2027
    first = package.write_archive(entries, tmp_path / "one.zip")
    assert package.write_archive(entries, tmp_path / "two.zip") == first
    with pytest.raises(FileExistsError):
        package.write_archive(entries, tmp_path / "one.zip")
    report = package.check_archive(tmp_path / "one.zip", repo)
    assert report["status"] == "ok", report["problems"]
    assert report["sha256"] == first


def test_adapters_refuse_other_weights_two_candidates_or_another_lora(
    repo, tmp_path
) -> None:
    sources = _sources(tmp_path, repo)
    folder = sources["A"] / repo["versions"]["A"]["hub"]["folder"]
    (folder / "adapter_model.safetensors").write_bytes(b"other weights")
    with pytest.raises(ValueError, match="frozen weights"):
        package.adapter_files("A", sources["A"], repo)
    (folder / "adapter_model.safetensors").write_bytes(WEIGHTS["A"])
    (folder / "adapter_model (1).safetensors").write_bytes(WEIGHTS["A"])
    with pytest.raises(ValueError, match="expected one"):
        package.adapter_files("A", sources["A"], repo)
    (folder / "adapter_model (1).safetensors").unlink()
    config = folder / "adapter_config.json"
    config.write_text(json.dumps(json.loads(config.read_text()) | {"r": 8}))
    with pytest.raises(ValueError, match="adapter_config r"):
        package.adapter_files("A", sources["A"], repo)


def test_check_archive_reports_changed_weights(repo, tmp_path) -> None:
    entries = package.archive_entries(_sources(tmp_path, repo), repo)
    weights = f"runs/{repo['versions']['B']['checkpoint']}/adapter_model.safetensors"
    entries[weights] = b"changed"
    package.write_archive(entries, tmp_path / "changed.zip")
    report = package.check_archive(tmp_path / "changed.zip", repo)
    assert report["status"] == "fail"
    assert "B: weights differ from the freeze" in report["problems"]
    assert any("selected_adapter refused" in p for p in report["problems"])


def test_check_archive_refuses_paths_outside_runs(repo, tmp_path) -> None:
    with zipfile.ZipFile(tmp_path / "bad.zip", "w") as archive:
        archive.writestr("runs/../../evil.txt", "x")
    report = package.check_archive(tmp_path / "bad.zip", repo)
    assert report["status"] == "fail"
    assert "unsafe paths" in report["problems"][0]


def _fetch(adapters: tuple[int, str]):
    def fetch(url: str, method: str):
        if "/api/models/" in url:
            body = json.dumps({"cardData": {"license": "apache-2.0"}}).encode()
            return 200, {}, body
        status, etag = adapters
        return status, {"X-Linked-Etag": f'"{etag}"'}, b""

    return fetch


def test_links_tell_private_from_public_adapters(repo) -> None:
    private = package.check_links(repo, _fetch((401, "")))
    assert private["base_model"]["status"] == "ok"
    assert private["adapters"]["A"] == {
        "url": f"{package.HUB}/ING3NLPProject/boxbox-adapter-a/tree/"
        f"{repo['versions']['A']['hub']['revision']}/s2028-e1",
        "http": 401,
        "reader_access": False,
        "sha256_matches": False,
    }
    public = package.check_links(repo, _fetch((302, _sha(WEIGHTS["A"]))))
    assert public["adapters"]["A"]["sha256_matches"] is True
    assert public["adapters"]["B"]["sha256_matches"] is False  # A's etag on B


def test_requirements_compare_installed_versions(tmp_path) -> None:
    pins = tmp_path / "requirements.txt"
    pins.write_text("pytest==0.0.1\n")
    assert "pytest" in package.requirement_problems(pins)[-1]
    pins.write_text(f"pytest=={package.metadata.version('pytest')}\n")
    assert all("pytest" not in p for p in package.requirement_problems(pins))


def test_rebuilt_ignores_build_fields_and_accepts_crlf_cards(tmp_path) -> None:
    root = tmp_path / "rebuilt"
    shutil.copytree("data/corpus", root / "data/corpus")
    shutil.copytree("data/final", root / "data/final")
    manifest = json.loads((root / "data/final/manifest.json").read_text())
    manifest |= {"created_at": "later", "git_commit": "c0ffee"}
    (root / "data/final/manifest.json").write_text(json.dumps(manifest))
    report = package.rebuilt(root)
    assert report["problems"] == [
        f"final card file {name} differs" for name in manifest["card_files"]
    ]
    manifest["coverage"]["dialogues"] = 199
    (root / "data/final/manifest.json").write_text(json.dumps(manifest))
    problems = package.rebuilt(root)["problems"]
    assert "data/final/manifest.json coverage differs" in problems


def test_card_files_match_as_is_or_with_crlf_line_ends() -> None:
    lf = b'{"card_id": "x"}\n{"card_id": "y"}\n'
    crlf = lf.replace(b"\n", b"\r\n")
    assert package.line_ends(lf, _sha(lf)) == "same bytes"
    assert package.line_ends(lf, _sha(crlf)).startswith("same cards, CRLF")
    assert package.line_ends(crlf, _sha(crlf)) == "same bytes"
    assert package.line_ends(lf + b"{}\n", _sha(crlf)) is None


def test_repository_keeps_raw_data_out_and_names_its_licences() -> None:
    assert package.raw_data_problems() == []
    assert package.licence_problems(package.frozen()) == []
