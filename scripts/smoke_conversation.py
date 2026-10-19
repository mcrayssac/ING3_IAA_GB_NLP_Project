"""Run the declared 2.5a baseline smoke cases on the real pinned model."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from boxbox.config import load_config
from boxbox.evaluation import pair_outputs, parse_response, prepare_case, validate_cases
from boxbox.evaluation._io import PROTOCOL_ID, PROTOCOL_VERSION, dumps, write_jsonl
from boxbox.model import (
    ConversationEngineError,
    baseline_instructions,
    get_device,
    load_conversation_engine,
    model_dtype,
)
from boxbox.rules import decide
from boxbox.runs import RUNS_DIR, finish_run, start_run

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "reference/evaluation-fixtures.json"
PROTOCOL = ROOT / "docs/evaluation-protocol.md"
POLICY = ROOT / "boxbox/rules/decision.py"
CASE_IDS = (
    "syn:case:equality",
    "syn:case:follow-explain",
    "syn:case:blocking",
    "syn:case:scope",
    "syn:case:stated-gap",
)
VERSION_ID = "smollm3-3b-baseline-2.5a"


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _write_text(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value)


def _source_case_rows(history_turns: int) -> tuple[list[dict[str, Any]], bytes]:
    fixture_bytes = FIXTURES.read_bytes()
    fixture = json.loads(
        fixture_bytes.decode("utf-8"), parse_float=Decimal, parse_int=int
    )
    cards = {row["card_id"]: row["card"] for row in fixture["cards"]}
    by_id = {row["case_id"]: row for row in fixture["cases"]}
    rows = [
        prepare_case(by_id[case_id], cards[by_id[case_id]["card_id"]], history_turns)
        for case_id in CASE_IDS
    ]
    validate_cases(rows)
    return rows, fixture_bytes


def _run_manifest(run_dir: Path, extra: dict[str, Any]) -> None:
    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(manifest["extra"].get(key), dict):
            manifest["extra"][key].update(value)
        else:
            manifest["extra"][key] = value
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _output_record(
    case: dict[str, Any],
    run_id: str,
    config_sha256: str,
    cases_sha256: str,
    raw_response: str | None,
    error: dict[str, str] | None,
) -> dict[str, Any]:
    return {
        "response_id": f"response:2.5a:{case['case_id'].split(':')[-1]}",
        "case_id": case["case_id"],
        "version_id": VERSION_ID,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "input_sha256": case["input_sha256"],
        "cases_sha256": cases_sha256,
        "status": "generation_error" if error is not None else "ok",
        "raw_response": raw_response,
        "error": error,
    }


def execute(config_path: Path, name: str, runs_dir: Path = RUNS_DIR) -> Path:
    config = load_config(config_path)
    rows, fixture_bytes = _source_case_rows(config.history_turns)
    run_dir = start_run(
        name,
        config,
        str(get_device()),
        str(model_dtype(get_device())),
        extra={
            "conversation_engine": {
                "protocol_id": PROTOCOL_ID,
                "protocol_version": PROTOCOL_VERSION,
                "protocol_status": "proposed",
                "acceptance_record": None,
                "fixtures_sha256": _sha256(fixture_bytes),
                "protocol_sha256": _sha256(PROTOCOL.read_bytes()),
                "policy_git_commit": _git("rev-parse", "HEAD"),
                "policy_source_sha256": _sha256(POLICY.read_bytes()),
                "history_mode": "fixed",
                "retained_versions": [VERSION_ID],
                "case_ids": [row["case_id"] for row in rows],
            }
        },
        runs_dir=runs_dir,
    )
    run_id = run_dir.name
    config_sha256 = _sha256((run_dir / "config.toml").read_bytes())
    cases_sha256 = write_jsonl(run_dir / "cases.jsonl", rows)
    input_data = "".join(row["input_json"] + "\n" for row in rows).encode("utf-8")
    with (run_dir / "inputs.jsonl").open("xb") as stream:
        stream.write(input_data)
    _write_text(run_dir / "prompt.txt", baseline_instructions())
    (run_dir / "fixtures.source.json").write_bytes(fixture_bytes)
    (run_dir / "evaluation-protocol.source.md").write_bytes(PROTOCOL.read_bytes())
    (run_dir / "policy-decision.source.py").write_bytes(POLICY.read_bytes())
    source_files = (
        "boxbox/config.py",
        "boxbox/model/conversation.py",
        "boxbox/model/loading.py",
        "boxbox/rules/__init__.py",
        "boxbox/runs.py",
        "boxbox/evaluation/_io.py",
        "boxbox/evaluation/parsing.py",
        "boxbox/evaluation/records.py",
        "scripts/smoke_conversation.py",
        "configs/conversation-smoke.toml",
    )
    source_dir = run_dir / "sources"
    source_dir.mkdir()
    for source in source_files:
        target = source_dir / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / source).read_bytes())
    _run_manifest(
        run_dir,
        {
            "conversation_engine": {
                "config_sha256": config_sha256,
                "prompt_sha256": _sha256((run_dir / "prompt.txt").read_bytes()),
                "cases_sha256": cases_sha256,
                "input_ledger_sha256": _sha256(input_data),
                "input_sha256_by_case": {
                    row["case_id"]: row["input_sha256"] for row in rows
                },
                "base_sha": _git("merge-base", "main", "HEAD"),
                "head_sha": _git("rev-parse", "HEAD"),
                "git_status_porcelain": _git("status", "--porcelain"),
            }
        },
    )

    outputs: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    started = time.perf_counter()
    engine = None
    load_error: ConversationEngineError | None = None
    try:
        engine = load_conversation_engine(config)
    except ConversationEngineError as error:
        load_error = error
    if engine is not None:
        _write_text(
            run_dir / "tokenizer-chat-template.source.txt",
            engine.tokenizer.chat_template
            if isinstance(engine.tokenizer.chat_template, str)
            else dumps(engine.tokenizer.chat_template),
        )
        generation_settings = engine.generation_settings()
        (run_dir / "generation-settings.json").write_text(
            json.dumps(generation_settings, indent=2, ensure_ascii=False, default=str)
            + "\n",
            encoding="utf-8",
        )
        _run_manifest(
            run_dir,
            {
                "conversation_engine": {
                    "model_id": config.model_id,
                    "model_revision": config.model_revision,
                    "tokenizer_id": config.model_id,
                    "tokenizer_revision": config.model_revision,
                    "device": str(engine.device),
                    "dtype": engine.dtype,
                    "attn_implementation": engine.attn_implementation,
                    "chat_template_context": engine.template_context(),
                    "chat_template_context_sha256": _sha256(
                        dumps(engine.template_context())
                    ),
                    "chat_template_sha256": _sha256(
                        (run_dir / "tokenizer-chat-template.source.txt").read_bytes()
                    ),
                    "generation_settings_sha256": _sha256(
                        (run_dir / "generation-settings.json").read_bytes()
                    ),
                }
            },
        )

    for case in rows:
        inputs = json.loads(case["input_json"], parse_float=Decimal, parse_int=int)
        card = inputs["card"]
        target_message = inputs["message"]
        policy_call, policy_why = decide(card)
        out_of_scope = case["attributes"]["out_of_scope"]
        expected_call = (
            case["reference"]["expected_call"] if out_of_scope else policy_call
        )
        if load_error is not None:
            error = load_error
            raw_response = error.partial_response
            trace = error.trace
        else:
            assert engine is not None
            try:
                raw_response, trace = engine.respond_with_trace(
                    card,
                    inputs["history"],
                    target_message,
                    fixed_history=True,
                    required_history_turns=int(case["attributes"]["history_sensitive"]),
                )
                error = None
            except ConversationEngineError as generation_error:
                error = generation_error
                raw_response = generation_error.partial_response
                trace = generation_error.trace
        record = _output_record(
            case,
            run_id,
            config_sha256,
            cases_sha256,
            raw_response,
            error.as_record() if error else None,
        )
        outputs.append(record)
        parse = parse_response(raw_response, record["status"])
        traces.append(
            {
                "response_id": record["response_id"],
                "case_id": case["case_id"],
                "input_sha256": case["input_sha256"],
                "input_json": case["input_json"],
                "requested_history": inputs["history"],
                "retained_history": trace.get("history", {}).get("retained"),
                "prompt_sha256": trace.get("prompt_messages_sha256"),
                "prompt_token_ids_sha256": trace.get("prompt_token_ids_sha256"),
                "input_tokens": trace.get("input_tokens"),
                "generated_token_ids": trace.get("generated_token_ids"),
                "generated_tokens": trace.get("generated_tokens"),
                "duration_seconds": trace.get("duration_seconds"),
                "stop_condition": trace.get("stop_condition"),
                "possibly_truncated": trace.get("possibly_truncated"),
                "trace": trace,
            }
        )
        diagnostics.append(
            {
                "case_id": case["case_id"],
                "response_id": record["response_id"],
                "expected_call": expected_call,
                "reference_source": (
                    "synthetic contextual scope annotation"
                    if out_of_scope
                    else "boxbox.rules.decide on the current card"
                ),
                "policy_call": policy_call,
                "policy_why": policy_why,
                "call_agrees_with_reference": (
                    parse["extracted_call"] == expected_call
                    if record["status"] == "ok"
                    else None
                ),
                "strict_format_valid": parse["strict_format_valid"],
                "qualitative_why_review": "not human-rated; inspect the preserved raw response",
                "generation_status": record["status"],
            }
        )

    write_jsonl(run_dir / "outputs.jsonl", outputs)
    write_jsonl(run_dir / "attempts.jsonl", traces)
    write_jsonl(run_dir / "smoke-diagnostics.jsonl", diagnostics)
    paired = pair_outputs(rows, outputs, [VERSION_ID], cases_sha256)
    ok_count = sum(row["status"] == "ok" for row in outputs)
    summary = {
        "planned_cases": len(rows),
        "successful_generation_calls": ok_count,
        "generation_errors": len(rows) - ok_count,
        "paired_outputs": len(paired[VERSION_ID]),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "protocol_status": "proposed",
        "acceptance_record": None,
        "model_quality_claim": None,
    }
    finish_run(run_dir, summary)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/conversation-smoke.toml")
    )
    parser.add_argument(
        "--name",
        required=True,
        help="fresh run name; existing runs are never overwritten",
    )
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args()
    run_dir = execute(args.config, args.name, args.runs_dir)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    print(json.dumps({"run_dir": str(run_dir), **metrics}, indent=2))
    if metrics["generation_errors"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
