"""Run the frozen final comparison once (4.2), with explicit technical resumes.

python -m scripts.final_scoring prepare
python -m scripts.final_scoring run --run-dir RUN
python -m scripts.final_scoring run --run-dir RUN --resume-reason 'technical reason'
python -m scripts.final_scoring seal --run-dir RUN
python -m scripts.final_scoring verify --run-dir RUN

A durable start record reserves each request before inference. A started request is
never generated again, including after a crash. Unfinished requests become explicit
interruption failures on resume; untouched requests continue with identical settings.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import os
import platform
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from boxbox.evaluation import (
    export_review,
    pair_outputs,
    select_review_cases,
    validate_cases,
)
from boxbox.evaluation._io import dumps, loads, read_jsonl, sha256
from boxbox.runs import config_toml, environment, source_sha256
from scripts import final_cases, freeze, mini_test

ROOT = Path(__file__).resolve().parents[1]
FINAL = Path("data/final")
VERSIONS = ["baseline", "A", "B"]


def now() -> str:
    return datetime.now(UTC).isoformat()


def read(path: Path):
    return loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return sha256(path.read_bytes())


def put_bytes(path: Path, content: bytes) -> None:
    """Publish a complete file atomically, refusing replacement; fsync before linking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # atomic and fails if path already exists
    finally:
        os.unlink(temporary)


def put(path: Path, value) -> None:
    put_bytes(path, (dumps(value) + "\n").encode())


@contextmanager
def locked(run: Path):
    """OS lock released even after a killed process; Mac/Linux runner."""
    with (run / ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another process holds this run") from error
        yield


def inventory(folder: Path) -> dict:
    return {
        p.relative_to(folder).as_posix(): digest(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
        and not any(x.startswith(".") for x in p.relative_to(folder).parts)
        and "__pycache__" not in p.parts
    }


def final_inputs() -> tuple[dict, list[dict], dict, dict]:
    frozen = final_cases.gate()  # must precede any final-case read
    if list(frozen["versions"]) != VERSIONS:
        raise ValueError("this final run requires frozen baseline/A/B")
    manifest = read(FINAL / "manifest.json")
    if manifest["freeze"]["sha256"] != digest(freeze.FREEZE):
        raise ValueError("final cases belong to another freeze")
    for name, expected in manifest["files"].items():
        if digest(FINAL / name) != expected:
            raise ValueError(f"final artifact changed: {name}")
    from boxbox.data import load_splits

    splits = load_splits()
    if splits["document_sha256"] != manifest["splits_document_sha256"]:
        raise ValueError("final split document changed")
    cases, cases_hash = read_jsonl(FINAL / "cases.jsonl")
    validate_cases(cases, splits)
    if len(cases) != 200 or any(c["split"] != "final" for c in cases):
        raise ValueError("expected exactly 200 final targets")
    counts = mini_test.population(cases)
    coverage = manifest["coverage"]
    for actual, expected in (
        (counts["families"], coverage["families"]),
        (counts["labels"], coverage["expected_calls"]),
        (counts["races"], coverage["races"]),
    ):
        if actual != expected:
            raise ValueError("final coverage differs from manifest")
    selection = read(FINAL / "review-selection.json")
    expected_selection = select_review_cases(cases)
    expected_selection["cases_sha256"] = cases_hash
    expected_selection.pop("sampling_manifest_sha256")
    expected_selection["sampling_manifest_sha256"] = sha256(dumps(expected_selection))
    if selection != expected_selection:
        raise ValueError("review selection differs from the predeclared allocation")
    if selection["sampling_manifest_sha256"] != manifest["sampling_manifest_sha256"]:
        raise ValueError("sampling manifest changed")
    return frozen, cases, splits, selection


def check_peft_config(content: bytes, entry: dict, model: dict) -> None:
    """Validate the saved PEFT inference fields against the selected frozen LoRA."""
    config = loads(content.decode("utf-8"))
    expected = {
        "r": entry["lora"]["r"],
        "lora_alpha": entry["lora"]["alpha"],
        "lora_dropout": entry["lora"]["dropout"],
        "base_model_name_or_path": model["id"],
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "bias": "none",
    }
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError("PEFT configuration differs from frozen LoRA")
    modules = {
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    }
    if (
        entry["lora"]["target_modules"] != "all-linear"
        or set(config.get("target_modules") or []) != modules
    ):
        raise ValueError(
            "PEFT target modules differ from frozen SmolLM3 all-linear LoRA"
        )
    for key in (
        "use_rslora",
        "use_dora",
        "lora_bias",
        "rank_pattern",
        "alpha_pattern",
        "modules_to_save",
        "layer_replication",
        "layers_to_transform",
        "fan_in_fan_out",
    ):
        if config.get(key):
            raise ValueError(f"unexpected PEFT inference override: {key}")
    if config.get("revision") not in (None, model["revision"]):
        raise ValueError("PEFT base revision differs from freeze")


def prepare(runs_dir: Path = Path("runs")) -> Path:
    frozen, cases, _, selection = final_inputs()
    # Stable across dates: a new name cannot silently create a second experiment.
    run = (
        runs_dir
        / f"4-2-final-{digest(freeze.FREEZE)[:12]}-{digest(FINAL / 'cases.jsonl')[:12]}"
    )
    if run.exists():
        raise FileExistsError(f"{run} exists; verify it or explicitly resume it")
    versions = {v: dict(frozen["versions"][v]) for v in VERSIONS}
    selections = {
        v: mini_test._checked(Path(e["selection_file"])) for v, e in versions.items()
    }
    configs = mini_test.check_versions(
        selections["baseline"], {v: selections[v] for v in VERSIONS[1:]}
    )
    baseline = configs["baseline"]
    if frozen["model"] != {
        "id": baseline.model_id,
        "revision": baseline.model_revision,
    }:
        raise ValueError("model differs from freeze")
    shared = {
        "prompt_variant": baseline.prompt_variant,
        "history_turns": baseline.history_turns,
        "history_mode": "fixed",
        "decoding": asdict(baseline.decoding),
        "chat_template_date": baseline.chat_template_date,
    }
    if dumps(shared) != dumps(frozen["shared_inference"]):
        raise ValueError("inference settings differ from freeze")
    adapter_files = {}
    for v in VERSIONS[1:]:
        effective, folder, _ = mini_test.resolve_adapter(v)
        expected = asdict(configs[v]) | {"seed": versions[v]["seed"]}
        if asdict(effective) != expected:
            raise ValueError(
                f"{v}: effective configuration differs from frozen selection"
            )
        configs[v] = effective
        adapter_files[v] = (folder / "adapter_config.json").read_bytes()
        check_peft_config(adapter_files[v], versions[v], frozen["model"])
        versions[v]["adapter_config_sha256"] = sha256(adapter_files[v])
    run.mkdir(parents=True)
    for v, entry in versions.items():
        put_bytes(
            run / f"versions/{v}/frozen-config.toml",
            Path(entry["config_file"]).read_bytes(),
        )
        put_bytes(
            run / f"versions/{v}/prompt.txt", Path(entry["prompt_file"]).read_bytes()
        )
        effective_bytes = config_toml(configs[v]).encode("utf-8")
        put_bytes(run / f"versions/{v}/config.toml", effective_bytes)
        entry["frozen_config_sha256"] = entry["config_sha256"]
        entry["config_sha256"] = sha256(effective_bytes)
        entry["effective_config_file"] = f"versions/{v}/config.toml"
        entry["effective_seed"] = configs[v].seed
        if v in adapter_files:
            put_bytes(run / f"versions/{v}/adapter_config.json", adapter_files[v])
    sources = {Path(name) for name in frozen["files"]} | {freeze.FREEZE}
    sources |= {p for p in FINAL.iterdir() if p.is_file()}
    sources |= {
        p
        for folder in ("boxbox", "scripts", "configs")
        for p in Path(folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    for p in sorted(sources):
        relative = Path("data/final") / p.name if p.parent == FINAL else p
        put_bytes(run / "sources" / relative, p.read_bytes())
    put_bytes(run / "cases.jsonl", (FINAL / "cases.jsonl").read_bytes())
    put_bytes(
        run / "inputs.jsonl", "".join(c["input_json"] + "\n" for c in cases).encode()
    )
    put(run / "review-selection.json", selection)
    put_bytes(run / "config.toml", config_toml(baseline).encode("utf-8"))
    plan = {
        "task": "4.2",
        "created_utc": now(),
        "version_ids": VERSIONS,
        "versions": versions,
        "cases_sha256": digest(run / "cases.jsonl"),
        "population": mini_test.population(cases),
        "planned_responses": len(cases) * len(VERSIONS),
        "freeze_sha256": digest(freeze.FREEZE),
        "source_sha256": source_sha256(),
        "head_sha": mini_test.git("rev-parse", "HEAD"),
        "git_status": mini_test.git("status", "--porcelain", "--untracked-files=all"),
        "sealed_files": inventory(run),
        "source_files": {p.as_posix(): digest(p) for p in sorted(sources)},
        "resume_policy": "Never retry a started request. Retain interrupted requests as errors; continue untouched requests only.",
    }
    put(run / "plan.json", plan)
    put(
        run / "manifest.json",
        {
            "task": "4.2",
            "plan_sha256": digest(run / "plan.json"),
            "git_commit": plan["head_sha"],
            "git_dirty": bool(plan["git_status"]),
            "source_sha256": plan["source_sha256"],
            "seed": baseline.seed,
            "version_seeds": {v: configs[v].seed for v in VERSIONS},
            "model_id": baseline.model_id,
            "model_revision": baseline.model_revision,
            "split_manifest_sha256": digest(Path("data/splits.json")),
            "device": "see runtime.json",
            "dtype": "see runtime.json",
            "environment": environment(),
            "started": time.time(),
            "duration_seconds": None,
            "duration_record": "complete.json (wall time since preparation, including interruptions)",
            "config": asdict(baseline),
            "model": frozen["model"],
            "shared_inference": shared,
            "extra": {
                "evaluation": {
                    "protocol_id": "boxbox-eval",
                    "protocol_version": "1.1.0",
                    "protocol_sha256": frozen["files"]["docs/evaluation-protocol.md"],
                    "fixtures_sha256": frozen["files"][
                        "reference/evaluation-fixtures.json"
                    ],
                    "policy_git_commit": plan["head_sha"],
                    "policy_source_sha256": frozen["files"]["boxbox/rules/decision.py"],
                    "cases_sha256": plan["cases_sha256"],
                    "input_ledger_sha256": digest(run / "inputs.jsonl"),
                    "data_manifest_sha256": digest(FINAL / "manifest.json"),
                    "split_manifest_sha256": digest(Path("data/splits.json")),
                    "sampling_manifest_sha256": selection["sampling_manifest_sha256"],
                    "history_mode": "fixed",
                    "retained_versions": VERSIONS,
                    "protocol_status": "accepted_in_freeze",
                    "acceptance_record": frozen["protocol_acceptance_record"],
                    "freeze_record": frozen["decision_record"],
                }
            },
        },
    )
    return run


def verify_plan(run: Path) -> tuple[dict, list[dict], dict]:
    final_cases.gate()
    plan = read(run / "plan.json")
    if (
        plan["task"] != "4.2"
        or digest(run / "plan.json") != read(run / "manifest.json")["plan_sha256"]
    ):
        raise ValueError("final plan changed")
    for relative, expected in plan["sealed_files"].items():
        if digest(run / relative) != expected:
            raise ValueError(f"sealed artifact changed: {relative}")
    for relative, expected in plan["source_files"].items():
        if digest(Path(relative)) != expected:
            raise ValueError(f"source changed: {relative}")
    if source_sha256() != plan["source_sha256"]:
        raise ValueError("code/configs changed since preparation")
    from boxbox.data import load_splits

    cases, cases_hash = read_jsonl(run / "cases.jsonl")
    if cases_hash != plan["cases_sha256"]:
        raise ValueError("case ledger changed")
    splits = load_splits()
    validate_cases(cases, splits)
    return plan, cases, splits


def request_path(run: Path, version: str, case: dict) -> Path:
    return run / "requests" / version / sha256(case["case_id"])


def failed(
    case: dict, version: str, run: Path, plan: dict, code: str, message: str
) -> dict:
    row = {
        "response_id": f"{run.name}:{version}:{case['case_id']}",
        "case_id": case["case_id"],
        "version_id": version,
        "run_id": run.name,
        "config_sha256": plan["versions"][version]["config_sha256"],
        "protocol_id": "boxbox-eval",
        "protocol_version": "1.1.0",
        "cases_sha256": plan["cases_sha256"],
        "input_sha256": case["input_sha256"],
        "status": "generation_error",
        "raw_response": None,
        "error": {"code": code, "message": message},
    }
    return {
        "output": row,
        "attempt": {
            "response_id": row["response_id"],
            "case_id": case["case_id"],
            "version_id": version,
            "input_sha256": case["input_sha256"],
            "trace": None,
        },
    }


def answer_once(
    engine, case: dict, version: str, run: Path, plan: dict, session: str
) -> None:
    folder = request_path(run, version, case)
    if (folder / "result.json").exists():
        if not (folder / "receipt.json").exists():
            put(
                folder / "receipt.json",
                {
                    "result_sha256": digest(folder / "result.json"),
                    "finished_utc": now(),
                    "recovered_receipt_in_session": session,
                },
            )
        return
    if (folder / "start.json").exists():
        result = failed(
            case,
            version,
            run,
            plan,
            "interrupted_request",
            "A prior process started this request without durably saving its result; not regenerated.",
        )
    else:
        put(
            folder / "start.json",
            {
                "case_id": case["case_id"],
                "version_id": version,
                "input_sha256": case["input_sha256"],
                "session": session,
                "started_utc": now(),
            },
        )
        try:
            row, attempt = mini_test._answer(engine, case, run.name, version, plan)
            result = {"output": row, "attempt": attempt}
        except Exception as error:  # noqa: BLE001 - retain unexpected per-request failures
            result = failed(
                case,
                version,
                run,
                plan,
                "unexpected_request_error",
                f"{type(error).__name__}: {error}",
            )
    put(folder / "result.json", result)
    put(
        folder / "receipt.json",
        {"result_sha256": digest(folder / "result.json"), "finished_utc": now()},
    )


def generate(run: Path, resume_reason: str | None = None) -> None:
    with locked(run):
        plan, cases, _ = verify_plan(run)
        if (run / "complete.json").exists():
            raise ValueError("completed final run cannot be generated again")
        sessions = sorted((run / "sessions").glob("*"))
        if sessions and not (resume_reason or "").strip():
            raise ValueError("technical resume requires --resume-reason")
        session = run / "sessions" / f"{len(sessions) + 1:03d}"
        put(
            session / "start.json",
            {
                "started_utc": now(),
                "pid": os.getpid(),
                "resume_reason": resume_reason,
                "prior_artifacts": inventory(run) if sessions else {},
                "host": platform.node(),
                "environment": environment(),
            },
        )
        try:
            _generate(run, plan, cases, session)
        except BaseException as error:
            put(
                session / "failure.json",
                {"at": now(), "type": type(error).__name__, "message": str(error)},
            )
            raise
        put(session / "complete.json", {"finished_utc": now()})


def _generate(run: Path, plan: dict, cases: list[dict], session: Path) -> None:
    from peft import PeftConfig, PeftModel

    from boxbox.model import ConversationEngine

    loaded = mini_test.load_engines(plan, run)
    base = loaded["baseline"]
    template = base.tokenizer.chat_template
    template_hash = sha256(template if isinstance(template, str) else dumps(template))
    if template_hash != plan["versions"]["baseline"]["chat_template_sha256"]:
        raise ValueError("native chat template differs from freeze")
    settings = mini_test._settings(base)
    runtime = {
        "environment": environment(),
        "host": platform.node(),
        "device": str(base.device),
        "dtype": str(base.dtype),
        "settings": loads(settings),
        "template_sha256": template_hash,
    }
    if (run / "runtime.json").exists():
        if read(run / "runtime.json") != loads(dumps(runtime)):
            raise ValueError(
                "technical resume changed machine/software/generation settings"
            )
    else:
        put(run / "runtime.json", runtime)
    prepared = []
    for case in cases:
        item = base.prepare(
            **loads(case["input_json"]),
            fixed_history=True,
            required_history_turns=int(case["attributes"]["history_sensitive"]),
        )
        prepared.append({"case_id": case["case_id"], "trace": item.trace})
    content = "".join(dumps(row) + "\n" for row in prepared).encode()
    if (run / "preflight.jsonl").exists():
        if (run / "preflight.jsonl").read_bytes() != content:
            raise ValueError("technical resume changed prepared tokens/history")
    else:
        put_bytes(run / "preflight.jsonl", content)

    put(
        session / "ready.json",
        {
            "runtime_sha256": digest(run / "runtime.json"),
            "preflight_sha256": digest(run / "preflight.jsonl"),
            "at": now(),
        },
    )

    def answer_all(engine, version):
        if mini_test._settings(engine) != settings:
            raise ValueError(f"{version}: generation settings differ from baseline")
        for i, case in enumerate(cases, 1):
            answer_once(engine, case, version, run, plan, session.name)
            print(f"{version}: {i}/{len(cases)}", flush=True)

    answer_all(base, "baseline")
    config, folder, prompt = loaded["A"]
    mini_test.check_adapter(plan, folder, "A")
    model = (
        PeftModel.from_pretrained(
            base.model,
            folder,
            config=PeftConfig.from_pretrained(str(run / "versions/A")),
        )
        .to(base.device)
        .eval()
    )
    answer_all(
        ConversationEngine(
            model,
            base.tokenizer,
            config,
            instructions=prompt,
            device=base.device,
            dtype=base.dtype,
        ),
        "A",
    )
    config, folder, prompt = loaded["B"]
    mini_test.check_adapter(plan, folder, "B")
    model.add_adapter("B", PeftConfig.from_pretrained(str(run / "versions/B")))
    model.load_adapter(folder, adapter_name="B")
    model.set_adapter("B")
    answer_all(
        ConversationEngine(
            model,
            base.tokenizer,
            config,
            instructions=prompt,
            device=base.device,
            dtype=base.dtype,
        ),
        "B",
    )


def collect(run: Path, plan: dict, cases: list[dict]) -> tuple[list[dict], list[dict]]:
    outputs, attempts = [], []
    ready_records = list((run / "sessions").glob("*/ready.json"))
    if not ready_records:
        raise ValueError("no recorded successful preflight")
    for path in ready_records:
        ready = read(path)
        if ready["runtime_sha256"] != digest(run / "runtime.json") or ready[
            "preflight_sha256"
        ] != digest(run / "preflight.jsonl"):
            raise ValueError("runtime/preflight changed after session readiness")
    preflight = {
        r["case_id"]: r["trace"] for r in read_jsonl(run / "preflight.jsonl")[0]
    }
    expected_paths = set()
    for version in plan["version_ids"]:
        for case in cases:
            folder = request_path(run, version, case)
            expected_paths.add(folder)
            start = read(folder / "start.json")
            if any(
                start[k] != value
                for k, value in (
                    ("case_id", case["case_id"]),
                    ("version_id", version),
                    ("input_sha256", case["input_sha256"]),
                )
            ):
                raise ValueError("request start identity mismatch")
            result = read(folder / "result.json")
            if (
                digest(folder / "result.json")
                != read(folder / "receipt.json")["result_sha256"]
            ):
                raise ValueError("request result changed")
            row, attempt = result["output"], result["attempt"]
            if (
                row["config_sha256"] != plan["versions"][version]["config_sha256"]
                or row["run_id"] != run.name
            ):
                raise ValueError("output configuration/run differs from plan")
            for record in (row, attempt):
                if (
                    record["case_id"] != case["case_id"]
                    or record["version_id"] != version
                    or record["input_sha256"] != case["input_sha256"]
                ):
                    raise ValueError("request result identity mismatch")
            if attempt["response_id"] != row["response_id"]:
                raise ValueError("response/trace identity mismatch")
            trace = attempt["trace"]
            if row["status"] == "ok" and trace is None:
                raise ValueError("successful request has no trace")
            if trace is not None:
                for key, value in preflight[case["case_id"]].items():
                    if dumps(trace.get(key)) != dumps(value):
                        raise ValueError(
                            f"request trace differs from case preflight: {key}"
                        )
            outputs.append(row)
            attempts.append(attempt)
    actual_paths = {p.parent for p in (run / "requests").rglob("start.json")}
    if actual_paths != expected_paths:
        raise ValueError("unexpected request records")
    return outputs, attempts


def seal(run: Path) -> dict:
    with locked(run):
        if (run / "complete.json").exists():
            return verify(run)
        plan, cases, splits = verify_plan(run)
        outputs, attempts = collect(run, plan, cases)
        paired = pair_outputs(
            cases, outputs, plan["version_ids"], plan["cases_sha256"], splits
        )
        # Exports can be resumed after disk failure, but existing bytes must agree.
        for name, rows in (("outputs.jsonl", outputs), ("attempts.jsonl", attempts)):
            content = "".join(dumps(row) + "\n" for row in rows).encode()
            path = run / name
            if path.exists():
                if path.read_bytes() != content:
                    raise ValueError(f"existing export differs: {name}")
            else:
                put_bytes(path, content)
        report = {
            "task": "4.2",
            "targets": len(cases),
            "responses": len(outputs),
            "population": plan["population"],
            "versions": {},
            "human_ratings": "pending",
            "sessions": len(list((run / "sessions").glob("*/start.json"))),
        }
        for v in VERSIONS:
            rows = list(paired[v].values())
            report["versions"][v] = {
                "responses": len(rows),
                "statuses": dict(Counter(r["status"] for r in rows)),
                "families": dict(Counter(c["primary_family"] for c in cases)),
                "races": dict(Counter(c["race_id"] for c in cases)),
                "possibly_truncated": sum(
                    bool(a["trace"] and a["trace"].get("possibly_truncated"))
                    for a in attempts
                    if a["version_id"] == v
                ),
            }
        with tempfile.TemporaryDirectory(prefix=".exports-", dir=run) as temporary:
            folder = Path(temporary)
            fields = ["case_id", "race_id", "primary_family", "expected_call"] + [
                f"{v}/{f}"
                for v in VERSIONS
                for f in (
                    "status",
                    "extracted_call",
                    "strict_format_valid",
                    "raw_response",
                )
            ]
            with (folder / "paired.csv").open(
                "w", encoding="utf-8", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fields, lineterminator="\n")
                writer.writeheader()
                for case in cases:
                    writer.writerow(
                        {
                            "case_id": case["case_id"],
                            "race_id": case["race_id"],
                            "primary_family": case["primary_family"],
                            "expected_call": case["reference"]["expected_call"],
                            **{
                                f"{v}/{f}": paired[v][case["case_id"]][f]
                                for v in VERSIONS
                                for f in (
                                    "status",
                                    "extracted_call",
                                    "strict_format_valid",
                                    "raw_response",
                                )
                            },
                        }
                    )
            export_review(
                folder / "review",
                cases,
                paired,
                read(run / "review-selection.json")["selected_case_ids"],
            )
            put(folder / "coverage.json", report)
            for p in sorted(folder.rglob("*")):
                if p.is_file():
                    dest = run / p.relative_to(folder)
                    if dest.exists():
                        if p.read_bytes() != dest.read_bytes():
                            raise ValueError("existing final export differs")
                    else:
                        put_bytes(dest, p.read_bytes())
        put(
            run / "complete.json",
            {
                "completed_utc": now(),
                "duration_seconds": time.time()
                - float(read(run / "manifest.json")["started"]),
                "files": inventory(run),
            },
        )
        return report


def verify(run: Path) -> dict:
    plan, cases, splits = verify_plan(run)
    complete = read(run / "complete.json")
    expected = complete["files"]
    actual = inventory(run)
    actual.pop("complete.json", None)
    if actual != expected:
        raise ValueError("completed run artifact inventory changed")
    outputs, _ = collect(run, plan, cases)
    pair_outputs(cases, outputs, plan["version_ids"], plan["cases_sha256"], splits)
    return read(run / "coverage.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    for command in ("run", "seal", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--run-dir", required=True, type=Path)
        if command == "run":
            sub.add_argument("--resume-reason")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    if args.command == "prepare":
        print(prepare())
    elif args.command == "run":
        generate(args.run_dir, args.resume_reason)
    else:
        print(
            dumps(
                seal(args.run_dir) if args.command == "seal" else verify(args.run_dir)
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
