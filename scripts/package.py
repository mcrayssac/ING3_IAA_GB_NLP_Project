"""Package the retained adapters and check the delivery as a reader gets it (task 5.2).

Usage, from the repository root:
    python -m scripts.package adapters --from-a DIR --from-b DIR --output FILE.zip
    python -m scripts.package check [--adapters FILE.zip] [--offline]
    python -m scripts.package rebuilt --root DIR

`adapters` copies the two checkpoints of `configs/freeze.json` from local copies of
their Hub repos into one zip, at the run paths `selected_adapter()` reads first, with
their cards, licence notice and hashes. A browser download may add " (1)" to a file
name, so each folder must hold exactly one weights file and one config. It refuses
weights whose hash differs from the freeze, a LoRA config that does not match the
frozen settings, and an existing output. The same inputs give the same bytes.

`check` looks at the delivery without any Hugging Face token: the freeze, the
installed versions against requirements.txt, raw timing data kept out of Git, the
licence notices and cards, the anonymous Hub links of the base model and both
adapters, and the adapter archive when given. A private Hub repo is reported, not
failed, when the archive gives the reader the same weights. It prints one JSON report
and exits with 1 when a check fails. It loads no model.

`rebuilt` compares a checkout where the frozen cards, corpus and final cases were
rebuilt (README.txt, "Rebuild the submitted data") with the committed files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

FREEZE = Path("configs/freeze.json")
REQUIREMENTS = Path("requirements.txt")
PYTHON = "3.13"
ADAPTERS = ("A", "B")
CARDS = {"A": Path("docs/adapter-a-card.md"), "B": Path("docs/adapter-b-card.md")}
ADAPTER_LICENCE = "cc-by-nc-sa-4.0"
BASE_LICENCE = "apache-2.0"
NC_SA = "CC BY-NC-SA 4.0"
NOTICES = (
    Path("data/corpus/NOTICE"),
    Path("data/demo/NOTICE"),
    Path("data/final/NOTICE"),
)
RAW = ("data/cache", "data/cards", "data/cards-v2", "runs")
HUB = "https://huggingface.co"
PACKAGE = PurePosixPath("runs/boxbox-adapters")
STAMP = (2026, 10, 21, 0, 0, 0)  # the freeze day, so the zip never depends on today
CORPUS_FILES = (
    "A_train.jsonl",
    "B_train.jsonl",
    "B_pairs.json",
    "validation.jsonl",
    "mini_test.jsonl",
    "manifest.json",
)
FINAL_FILES = ("final.jsonl", "cases.jsonl", "review-selection.json")
# fields of data/final/manifest.json that name the build, not its content; the card
# file hashes are compared with the card files themselves
BUILD_FIELDS = ("created_at", "git_commit", "git_dirty", "card_files")

Fetch = Callable[[str, str], tuple[int, dict[str, str], bytes]]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def frozen(path: Path = FREEZE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _one(folder: Path, pattern: str) -> Path:
    """The single file matching pattern, whatever suffix a download added."""
    found = sorted(p for p in folder.glob(pattern) if p.is_file())
    if len(found) != 1:
        raise ValueError(f"{folder}: expected one {pattern}, found {len(found)}")
    return found[0]


def lora_problems(config: dict[str, Any], record: dict[str, Any], version: str) -> list:
    """Differences between an adapter_config.json and the frozen LoRA settings."""
    lora = record["versions"][version]["lora"]
    expected = {
        "peft_type": "LORA",
        "base_model_name_or_path": record["model"]["id"],
        "r": lora["r"],
        "lora_alpha": lora["alpha"],
        "lora_dropout": lora["dropout"],
    }
    return [
        f"{version}: adapter_config {key} is {config.get(key)!r}, frozen {value!r}"
        for key, value in expected.items()
        if config.get(key) != value
    ]


def adapter_files(version: str, source: Path, record: dict[str, Any]) -> dict:
    """Weights and config of one retained checkpoint, refused unless they are frozen."""
    entry = record["versions"][version]
    folder = source / entry["hub"]["folder"]
    weights = _one(folder, "adapter_model*.safetensors").read_bytes()
    if sha256(weights) != entry["adapter_sha256"]:
        raise ValueError(f"{version}: {folder} does not hold the frozen weights")
    config = _one(folder, "adapter_config*.json").read_bytes()
    problems = lora_problems(json.loads(config), record, version)
    if problems:
        raise ValueError("\n".join(problems))
    run = PurePosixPath("runs") / entry["checkpoint"]
    return {
        str(run / "adapter_model.safetensors"): weights,
        str(run / "adapter_config.json"): config,
    }


def notice() -> str:
    return (
        "BoxBox adapters A and B, the two LoRA checkpoints retained by the freeze of\n"
        "configs/freeze.json, for HuggingFaceTB/SmolLM3-3B (Apache 2.0, not included).\n\n"
        "They are trained on dialogues derived from timing data published by OpenF1\n"
        "(https://openf1.org), with round numbers and event names from Jolpica-F1\n"
        "(https://github.com/jolpica/jolpica-f1), and are released under the Creative\n"
        "Commons Attribution-NonCommercial-ShareAlike 4.0 International licence\n"
        f"({NC_SA}), as OpenF1's licence requires, not under the Apache License 2.0\n"
        "of the code.\n\n"
        "The timing data belongs to the Formula 1 companies. BoxBox is an unofficial,\n"
        "non-commercial student project with no link to them.\n"
    )


def archive_entries(sources: dict[str, Path], record: dict[str, Any]) -> dict:
    """Every file of the adapter archive, by its path in the zip."""
    entries: dict[str, bytes] = {}
    versions = {}
    for version in ADAPTERS:
        files = adapter_files(version, sources[version], record)
        entries |= files
        entry = record["versions"][version]
        versions[version] = {
            key: entry[key]
            for key in ("version", "seed", "epoch", "step", "adapter_sha256", "hub")
        } | {"files": {path: sha256(data) for path, data in files.items()}}
        card = CARDS[version]
        entries[str(PACKAGE / card.name)] = card.read_bytes()
    entries[str(PACKAGE / "NOTICE")] = notice().encode()
    manifest = {
        "task": "5.2",
        "freeze_sha256": sha256(FREEZE.read_bytes()),
        "frozen_at": record["frozen_at"],
        "model": record["model"],
        "licence": NC_SA,
        "versions": versions,
    }
    entries[str(PACKAGE / "manifest.json")] = (
        json.dumps(manifest, indent=2) + "\n"
    ).encode()
    return entries


def write_archive(entries: dict[str, bytes], output: Path) -> str:
    """A zip with fixed times and order, never over an existing file."""
    with (
        output.open("xb") as stream,
        zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entries[name])
    return sha256(output.read_bytes())


def check_archive(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """The archive holds the frozen weights where selected_adapter() finds them."""
    from boxbox.model import selected_adapter

    problems = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        unsafe = [
            n
            for n in names
            if not n.startswith("runs/") or ".." in PurePosixPath(n).parts
        ]
        if unsafe:
            return {"status": "fail", "problems": [f"unsafe paths: {unsafe}"]}
        manifest = json.loads(archive.read(str(PACKAGE / "manifest.json")))
        if NC_SA not in archive.read(str(PACKAGE / "NOTICE")).decode():
            problems.append(f"the notice does not name {NC_SA}")
        for version in ADAPTERS:
            entry = record["versions"][version]
            run = PurePosixPath("runs") / entry["checkpoint"]
            weights = archive.read(str(run / "adapter_model.safetensors"))
            if sha256(weights) != entry["adapter_sha256"]:
                problems.append(f"{version}: weights differ from the freeze")
            config = json.loads(archive.read(str(run / "adapter_config.json")))
            problems += lora_problems(config, record, version)
            for name, digest in manifest["versions"][version]["files"].items():
                if sha256(archive.read(name)) != digest:
                    problems.append(f"{name}: differs from the archive manifest")
        with tempfile.TemporaryDirectory() as folder:
            archive.extractall(folder)
            for version in ADAPTERS:
                selection = Path(record["versions"][version]["selection_file"])
                try:
                    _, found, _ = selected_adapter(selection, Path(folder) / "runs")
                except (ValueError, FileNotFoundError) as error:
                    problems.append(f"{version}: selected_adapter refused it: {error}")
                    continue
                if not found.is_relative_to(folder):
                    problems.append(f"{version}: selected_adapter looked elsewhere")
    return {
        "status": "fail" if problems else "ok",
        "sha256": sha256(path.read_bytes()),
        "bytes": path.stat().st_size,
        "problems": problems,
    }


def anonymous(url: str, method: str) -> tuple[int, dict[str, str], bytes]:
    """One request without credentials or redirects, as a reader without a token."""

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    request = urllib.request.Request(url, method=method)
    opener = urllib.request.build_opener(Stay)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), b""


def _lower(headers: dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def check_links(record: dict[str, Any], fetch: Fetch = anonymous) -> dict[str, Any]:
    """Anonymous Hub access to the pinned base model and to both adapters."""
    model = record["model"]
    status, _, body = fetch(
        f"{HUB}/api/models/{model['id']}/revision/{model['revision']}", "GET"
    )
    licence = json.loads(body).get("cardData", {}).get("license") if body else None
    base = {
        "url": f"{HUB}/{model['id']}/tree/{model['revision']}",
        "http": status,
        "licence": licence,
        "status": "ok" if status == 200 and licence == BASE_LICENCE else "fail",
    }
    adapters = {}
    for version in ADAPTERS:
        hub = record["versions"][version]["hub"]
        url = (
            f"{HUB}/{hub['repo']}/resolve/{hub['revision']}/{hub['folder']}"
            "/adapter_model.safetensors"
        )
        status, headers, _ = fetch(url, "HEAD")
        etag = _lower(headers).get("x-linked-etag", "").strip('"')
        public = status in (200, 302, 307)
        frozen_sha = record["versions"][version]["adapter_sha256"]
        adapters[version] = {
            "url": f"{HUB}/{hub['repo']}/tree/{hub['revision']}/{hub['folder']}",
            "http": status,
            "reader_access": public,
            "sha256_matches": public and etag == frozen_sha,
        }
    return {"base_model": base, "adapters": adapters}


def requirement_problems(requirements: Path = REQUIREMENTS) -> list[str]:
    problems = []
    if platform.python_version().rsplit(".", 1)[0] != PYTHON:
        problems.append(f"python {platform.python_version()}, the guide pins {PYTHON}")
    for line in requirements.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, pinned = line.split("==")
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != pinned:
            problems.append(f"{name} {installed}, requirements.txt pins {pinned}")
    return problems


def raw_data_problems() -> list[str]:
    """Raw timing data and run folders must stay local: ignored and never tracked."""
    tracked = git("ls-files", "--", *RAW).stdout.split()
    problems = [f"tracked by Git: {path}" for path in tracked]
    for path in RAW:
        if git("check-ignore", "-q", f"{path}/x").returncode != 0:
            problems.append(f"not ignored by .gitignore: {path}/")
    return problems


def front_matter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").split("---\n")[1].splitlines()
    return dict(line.split(": ", 1) for line in lines if ": " in line)


def licence_problems(record: dict[str, Any]) -> list[str]:
    problems = []
    if "Apache License" not in Path("LICENSE").read_text(encoding="utf-8")[:200]:
        problems.append("LICENSE is not the Apache License 2.0")
    for path in NOTICES:
        if not path.exists() or NC_SA not in path.read_text(encoding="utf-8"):
            problems.append(f"{path} missing or without {NC_SA}")
    for card in CARDS.values():
        fields = front_matter(card)
        if fields.get("license") != ADAPTER_LICENCE:
            problems.append(f"{card} licence {fields.get('license')}")
        if fields.get("base_model") != record["model"]["id"]:
            problems.append(f"{card} names another base model")
    return problems


def _result(problems: list[str]) -> dict[str, Any]:
    return {"status": "fail" if problems else "ok", "problems": problems}


def check(
    adapters: Path | None, offline: bool, fetch: Fetch = anonymous
) -> dict[str, Any]:
    from scripts import freeze

    record = frozen()
    report: dict[str, Any] = {
        "freeze": _result(freeze.check()),
        "versions": _result(requirement_problems()),
        "raw_data": _result(raw_data_problems()),
        "licences": _result(licence_problems(record)),
    }
    if offline:
        report["links"] = {"status": "skipped", "reason": "--offline"}
    else:
        try:
            report["links"] = check_links(record, fetch)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            report["links"] = {"status": "fail", "problems": [repr(error)]}
    if adapters is None:
        report["archive"] = {"status": "skipped", "reason": "no --adapters"}
    else:
        report["archive"] = check_archive(adapters, record)
    hub = report["links"].get("adapters", {})
    archive_ok = report["archive"]["status"] == "ok"
    report["reader_access"] = {
        version: {
            "hub": bool(hub.get(version, {}).get("sha256_matches")),
            "archive": archive_ok,
            "status": "ok"
            if archive_ok or hub.get(version, {}).get("sha256_matches")
            else "fail",
        }
        for version in ADAPTERS
    }
    return report


def failed(report: dict[str, Any]) -> list[str]:
    """Names of the failed parts, the reader access of each adapter included."""
    names = [k for k, v in report.items() if v.get("status") == "fail"]
    names += [
        f"reader_access {version}"
        for version, value in report["reader_access"].items()
        if value["status"] == "fail"
    ]
    if report["links"].get("base_model", {}).get("status") == "fail":
        names.append("base model link")
    return names


def line_ends(data: bytes, digest: str) -> str | None:
    """How a rebuilt card file matches a recorded hash: as is, or with CRLF line ends.

    Path.write_text writes CRLF on Windows, so a card file built there has another
    hash for the same cards.
    """
    if sha256(data) == digest:
        return "same bytes"
    if sha256(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")) == digest:
        return "same cards, CRLF line ends in the record"
    return None


def rebuilt(root: Path) -> dict[str, Any]:
    """Rebuilt corpus, final cases and final cards against the committed files."""
    problems = []
    corpus, again = Path("data/corpus"), root / "data/corpus"
    for name in CORPUS_FILES:
        if (again / name).read_bytes() != (corpus / name).read_bytes():
            problems.append(f"data/corpus/{name} differs")
    final, again = Path("data/final"), root / "data/final"
    for name in FINAL_FILES:
        if (again / name).read_bytes() != (final / name).read_bytes():
            problems.append(f"data/final/{name} differs")
    committed = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
    rebuilt_manifest = json.loads((again / "manifest.json").read_text(encoding="utf-8"))
    for key in sorted(set(committed) | set(rebuilt_manifest)):
        if key not in BUILD_FIELDS and committed.get(key) != rebuilt_manifest.get(key):
            problems.append(f"data/final/manifest.json {key} differs")
    cards = {}
    for name, digest in committed["card_files"].items():
        card = root / "data/cards" / name
        cards[name] = line_ends(card.read_bytes(), digest) if card.exists() else None
        if cards[name] is None:
            problems.append(f"final card file {name} differs")
    return _result(problems) | {"final_card_files": cards}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("adapters", help="zip the two retained checkpoints")
    pack.add_argument("--from-a", required=True, type=Path)
    pack.add_argument("--from-b", required=True, type=Path)
    pack.add_argument("--output", required=True, type=Path)
    look = commands.add_parser("check", help="check the delivery as a reader")
    look.add_argument("--adapters", type=Path, help="the zip made by `adapters`")
    look.add_argument("--offline", action="store_true", help="skip the Hub links")
    again = commands.add_parser("rebuilt", help="compare rebuilt data with Git")
    again.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "adapters":
            entries = archive_entries({"A": args.from_a, "B": args.from_b}, frozen())
            digest = write_archive(entries, args.output)
            print(json.dumps({"output": str(args.output), "sha256": digest}, indent=2))
            return 0
        if args.command == "check":
            report = check(args.adapters, args.offline)
        else:
            report = rebuilt(args.root)
    except (ValueError, FileExistsError, FileNotFoundError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    if args.command == "check":
        problems = failed(report)
        if problems:
            print("failed: " + ", ".join(problems), file=sys.stderr)
        return 1 if problems else 0
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
