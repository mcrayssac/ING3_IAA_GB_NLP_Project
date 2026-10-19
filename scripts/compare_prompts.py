"""Prepare, run and select two baseline prompts on validation only (task 2.5b)."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from boxbox.config import load_config, load_run_settings
from boxbox.evaluation import (
    adapt_validation,
    bootstrap_compare,
    observations,
    pair_outputs,
    select_prompt,
    summarize,
    validate_candidate_ids,
    validate_validation_population,
)
from boxbox.evaluation._io import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    loads,
    read_jsonl,
    sha256,
    write_jsonl,
)
from boxbox.runs import config_toml, finish_run, source_sha256, start_run

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = Path("docs/evaluation-protocol.md")


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(dumps(value) + "\n")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def prepare(config_path: Path, name: str, cards_dir: Path, runs_dir: Path) -> Path:
    """Seal both candidates and the complete common ledger before model loading."""
    from boxbox.corpus import load_corpus
    from boxbox.data import load_cards, load_splits
    from boxbox.model import get_device, model_dtype

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("name must be a simple new run name")
    config, settings = load_run_settings(config_path, "prompt_comparison")
    if set(settings) != {"split", "candidates"} or settings["split"] != "validation":
        raise ValueError("prompt comparison accepts validation only")
    if config.final_test_open or config.adapter != "none":
        raise ValueError("the baseline must be unadapted and final must stay closed")
    candidates = settings["candidates"]
    versions = validate_candidate_ids(list(candidates))
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", v) for v in versions):
        raise ValueError("candidate IDs must be safe simple file names")
    if len(versions) != 2:
        raise ValueError("this declared experiment compares exactly two candidates")
    prompts = {v: Path(candidates[v]).read_text(encoding="utf-8") for v in versions}
    if (
        any(not text.strip() for text in prompts.values())
        or len(set(prompts.values())) != 2
    ):
        raise ValueError("two distinct nonempty prompt formulations are required")

    splits = load_splits()
    # Use the upstream guards, then preserve exact source decimals for the ledger.
    load_corpus("validation")
    load_cards("validation", config, cards_dir=cards_dir)
    corpus_path = Path("data/corpus/validation.jsonl")
    items, corpus_hash = read_jsonl(corpus_path)
    corpus_manifest = loads(Path("data/corpus/manifest.json").read_text())
    if corpus_hash != corpus_manifest["files"]["validation.jsonl"]["sha256"]:
        raise ValueError("validation changed after the upstream check")
    records, source_paths = [], []
    for race in splits["splits"]["validation"]:
        path = cards_dir / f"{race}.jsonl"
        rows, _ = read_jsonl(path)
        records.extend(rows)
        source_paths.append(path)
    cases = adapt_validation(items, records, splits, config.history_turns)
    if len(cases) != 100:
        raise ValueError(
            "the integrated validation experiment requires all 100 targets"
        )
    population = validate_validation_population(cases, splits)
    device = get_device()
    run = start_run(
        name, config, str(device), str(model_dtype(device)), runs_dir=runs_dir
    )
    (run / "sources").mkdir()
    copied = {}

    def snapshot(source: Path, relative: str) -> None:
        target = run / "sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        with target.open("xb") as stream:
            stream.write(data)
        copied[str(target.relative_to(run))] = sha256(data)

    for folder in ("boxbox", "scripts", "configs"):
        for source in sorted(Path(folder).rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                snapshot(source, str(source))
    for path in (
        PROTOCOL,
        Path("reference/evaluation-fixtures.json"),
        Path("data/splits.json"),
        Path("data/corpus/manifest.json"),
        corpus_path,
    ):
        snapshot(path, str(path))
    for path in source_paths:
        snapshot(path, f"data/cards/{path.name}")
    recovery = cards_dir / "validation-recovery-manifest.json"
    if recovery.exists():
        snapshot(recovery, "data/cards/validation-recovery-manifest.json")
    case_hash = write_jsonl(run / "cases.jsonl", cases)
    (run / "inputs.jsonl").write_text("".join(c["input_json"] + "\n" for c in cases))
    versions_info = {}
    for version in versions:
        folder = run / "candidates" / version
        folder.mkdir(parents=True)
        effective = replace(config, prompt_variant=version)
        (folder / "config.toml").write_text(config_toml(effective), encoding="utf-8")
        (folder / "prompt.txt").write_text(prompts[version], encoding="utf-8")
        versions_info[version] = {
            "config_sha256": sha256((folder / "config.toml").read_bytes()),
            "prompt_sha256": sha256((folder / "prompt.txt").read_bytes()),
        }
    sealed = {
        **copied,
        **{
            str(p.relative_to(run)): sha256(p.read_bytes())
            for p in (run / "candidates").rglob("*")
            if p.is_file()
        },
        "cases.jsonl": case_hash,
        "inputs.jsonl": sha256((run / "inputs.jsonl").read_bytes()),
        "config.toml": sha256((run / "config.toml").read_bytes()),
    }
    plan = {
        "task": "2.5b",
        "created_utc": datetime.now(UTC).isoformat(),
        "split": "validation",
        "candidate_ids": list(versions),
        "candidates": versions_info,
        "population": population,
        "planned_responses": len(cases) * len(versions),
        "cases_sha256": case_hash,
        "base_sha": git("merge-base", "origin/main", "HEAD"),
        "head_sha": git("rev-parse", "HEAD"),
        "git_status": git("status", "--porcelain", "--untracked-files=all"),
        "source_sha256": source_sha256(),
        "sealed_files": sealed,
        "history_mode": "fixed",
        "selection_rule": "boxbox-eval/1.1.0 section 5; exact fractions; lexical ID tie-break",
        "annotation_source": "Integrated corpus target references and documented family mapping; no new human ratings",
        "protocol_status": "proposed",
        "acceptance_record": None,
        "limitations": [
            "Policy agreement on supplied cards does not validate strict-cutoff availability.",
            "The corpus A SC/VSC exception remains an upstream team decision.",
            "This inference handoff is not the collective 3.5 freeze.",
        ],
    }
    write_json(run / "plan.json", plan)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["extra"] = {
        "prompt_comparison": {"plan_sha256": sha256((run / "plan.json").read_bytes())},
        "evaluation": {
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": sha256(PROTOCOL.read_bytes()),
            "fixtures_sha256": sha256(
                Path("reference/evaluation-fixtures.json").read_bytes()
            ),
            "policy_git_commit": git("rev-parse", "HEAD"),
            "policy_source_sha256": sha256(
                Path("boxbox/rules/decision.py").read_bytes()
            ),
            "cases_sha256": case_hash,
            "input_ledger_sha256": sealed["inputs.jsonl"],
            "data_manifest_sha256": sha256(
                Path("data/corpus/manifest.json").read_bytes()
            ),
            "sampling_manifest_sha256": None,
            "history_mode": "fixed",
            "retained_versions": list(versions),
            "protocol_status": "proposed",
            "acceptance_record": None,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return run


def verify_plan(run: Path) -> tuple[dict, list[dict], dict]:
    manifest = loads((run / "manifest.json").read_text())
    if (
        sha256((run / "plan.json").read_bytes())
        != manifest["extra"]["prompt_comparison"]["plan_sha256"]
    ):
        raise ValueError("the declared plan changed")
    plan = loads((run / "plan.json").read_text())
    if plan["split"] != "validation":
        raise ValueError("only validation is allowed")
    for relative, expected in plan["sealed_files"].items():
        path = run / relative
        if (
            not path.resolve().is_relative_to(run.resolve())
            or sha256(path.read_bytes()) != expected
        ):
            raise ValueError(f"sealed artifact changed: {relative}")
    cases, digest = read_jsonl(run / "cases.jsonl")
    if digest != plan["cases_sha256"]:
        raise ValueError("case ledger changed")
    splits = loads((run / "sources/data/splits.json").read_text())
    validate_validation_population(cases, splits)
    return plan, cases, splits


def generate(run: Path) -> None:
    """One attempt per planned cell; persist raw outputs immediately, never retry."""
    from boxbox.model import (
        ConversationEngine,
        ConversationEngineError,
        load_conversation_engine,
    )

    plan, cases, _ = verify_plan(run)
    if plan["source_sha256"] != source_sha256():
        raise ValueError("code/configs changed since preparation; make a new plan")
    # Exclusive marker prevents re-running or combining attempts after interruption.
    write_json(
        run / "attempt-start.json", {"started_utc": datetime.now(UTC).isoformat()}
    )
    versions = plan["candidate_ids"]
    prompts = {v: (run / "candidates" / v / "prompt.txt").read_text() for v in versions}
    configs = {v: load_config(run / "candidates" / v / "config.toml") for v in versions}
    try:
        primary = load_conversation_engine(
            configs[versions[0]], instructions=prompts[versions[0]]
        )
        engines = {versions[0]: primary}
        for v in versions[1:]:
            engines[v] = ConversationEngine(
                primary.model,
                primary.tokenizer,
                configs[v],
                instructions=prompts[v],
                device=primary.device,
                dtype=primary.dtype,
            )
            engines[v].attn_implementation = primary.attn_implementation
        preflight = []
        for case in cases:
            inputs = loads(case["input_json"])
            result = primary.preflight_candidates(
                prompts,
                **inputs,
                fixed_history=True,
                required_history_turns=int(case["attributes"]["history_sensitive"]),
            )
            preflight.append(
                {
                    "case_id": case["case_id"],
                    "input_sha256": case["input_sha256"],
                    **result,
                }
            )
        write_jsonl(run / "preflight.jsonl", preflight)
        if not all(row["ready"] for row in preflight):
            raise ValueError("context preflight failed; no generation attempted")
        settings = {v: engine.generation_settings() for v, engine in engines.items()}
        if any(dumps(s) != dumps(settings[versions[0]]) for s in settings.values()):
            raise ValueError("candidates have different effective generation settings")
        runtime = {
            "model_id": primary.config.model_id,
            "model_revision": primary.config.model_revision,
            "tokenizer_revision": primary.config.model_revision,
            "device": str(primary.device),
            "dtype": primary.dtype,
            "attn_implementation": primary.attn_implementation,
            "template_context": primary.template_context(),
            "template_options": {
                "enable_thinking": False,
                "add_generation_prompt": True,
                "padding": False,
                "truncation": False,
            },
            "generation_settings": settings,
        }
        template = primary.tokenizer.chat_template
        (run / "chat-template.txt").write_text(
            template if isinstance(template, str) else dumps(template)
        )
        runtime["chat_template_sha256"] = sha256(
            (run / "chat-template.txt").read_bytes()
        )
        write_json(run / "runtime.json", runtime)
        with (
            (run / "outputs.jsonl").open("x", encoding="utf-8") as outputs,
            (run / "attempts.jsonl").open("x", encoding="utf-8") as attempts,
        ):
            for index, case in enumerate(cases):
                inputs = loads(case["input_json"])
                for v in versions:
                    try:
                        raw, trace = engines[v].respond_with_trace(
                            **inputs,
                            fixed_history=True,
                            required_history_turns=int(
                                case["attributes"]["history_sensitive"]
                            ),
                        )
                        error = None
                    except ConversationEngineError as failure:
                        raw, trace, error = (
                            failure.partial_response,
                            failure.trace,
                            failure.as_record(),
                        )
                    row = {
                        "response_id": f"{run.name}:{v}:{case['case_id']}",
                        "case_id": case["case_id"],
                        "version_id": v,
                        "run_id": run.name,
                        "config_sha256": plan["candidates"][v]["config_sha256"],
                        "protocol_id": PROTOCOL_ID,
                        "protocol_version": PROTOCOL_VERSION,
                        "cases_sha256": plan["cases_sha256"],
                        "input_sha256": case["input_sha256"],
                        "status": "generation_error" if error else "ok",
                        "raw_response": raw,
                        "error": error,
                    }
                    outputs.write(dumps(row) + "\n")
                    outputs.flush()
                    attempts.write(
                        dumps(
                            {
                                "response_id": row["response_id"],
                                "case_id": case["case_id"],
                                "version_id": v,
                                "input_sha256": case["input_sha256"],
                                "trace": trace,
                            }
                        )
                        + "\n"
                    )
                    attempts.flush()
                    expected = preflight[index]["candidates"][v]
                    if (
                        trace.get("prompt_token_ids_sha256")
                        != expected["input_token_ids_sha256"]
                        or trace.get("history", {}).get("retained") != inputs["history"]
                    ):
                        raise ValueError(
                            "executed context differs from the common preflight; raw evidence retained"
                        )
                print(f"Completed target {index + 1}/{len(cases)}", flush=True)
    except Exception as error:
        write_json(
            run / "attempt-failure.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "error": error.as_record()
                if isinstance(error, ConversationEngineError)
                else None,
                "trace": error.trace
                if isinstance(error, ConversationEngineError)
                else None,
                "partial_response": error.partial_response
                if isinstance(error, ConversationEngineError)
                else None,
            },
        )
        raise
    write_json(
        run / "attempt-complete.json",
        {
            "outputs_sha256": sha256((run / "outputs.jsonl").read_bytes()),
            "attempts_sha256": sha256((run / "attempts.jsonl").read_bytes()),
        },
    )


def score(run: Path) -> dict:
    """Pair the entire experiment and save the chosen inference without rerunning it."""
    plan, cases, splits = verify_plan(run)
    complete = loads((run / "attempt-complete.json").read_text())
    outputs, output_hash = read_jsonl(run / "outputs.jsonl")
    if (
        output_hash != complete["outputs_sha256"]
        or sha256((run / "attempts.jsonl").read_bytes()) != complete["attempts_sha256"]
    ):
        raise ValueError("generation artifacts changed")
    versions = plan["candidate_ids"]
    paired = pair_outputs(cases, outputs, versions, plan["cases_sha256"], splits)
    rows = observations(cases, paired)
    summaries = {v: summarize(rows[v]) for v in versions}
    selection = select_prompt(summaries, versions)
    write_json(run / "comparison.json", summaries)
    write_json(run / "selection.json", selection)
    comparison = bootstrap_compare(rows, versions[0], versions[1])
    comparison["contrast_role"] = "exploratory_prompt_comparison_on_validation"
    write_json(run / "race-bootstrap.json", comparison)
    with (run / "paired.csv").open("x", newline="", encoding="utf-8") as stream:
        fields = ["case_id", "race_id", "primary_family", "expected_call"] + [
            f"{v}/{field}"
            for v in versions
            for field in ("status", "strict_format_valid", "extracted_call")
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "race_id": case["race_id"],
                    "primary_family": case["primary_family"],
                    "expected_call": case["reference"]["expected_call"],
                    **{
                        f"{v}/{field}": paired[v][case["case_id"]][field]
                        for v in versions
                        for field in ("status", "strict_format_valid", "extracted_call")
                    },
                }
            )
    chosen = selection["selected_candidate"]
    target = run / "selected"
    target.mkdir()
    for name in ("config.toml", "prompt.txt"):
        shutil.copyfile(run / "candidates" / chosen / name, target / name)
    write_json(
        target / "inference-lock.json",
        {
            "task": "2.5b",
            "selected_candidate": chosen,
            "source_run": run.name,
            "config_sha256": sha256((target / "config.toml").read_bytes()),
            "prompt_sha256": sha256((target / "prompt.txt").read_bytes()),
            "runtime_sha256": sha256((run / "runtime.json").read_bytes()),
            "plan_sha256": sha256((run / "plan.json").read_bytes()),
            "outputs_sha256": output_hash,
            "cases_sha256": plan["cases_sha256"],
            "protocol_status": "proposed",
            "acceptance_record": None,
            "final_test_open": False,
            "human_ratings": "not performed",
            "scope": "Selected inference for baseline/A handoff; not the collective 3.5 freeze",
        },
    )
    finish_run(
        run,
        {
            "planned_responses": plan["planned_responses"],
            "retained_responses": len(outputs),
            "generation_errors": sum(o["status"] != "ok" for o in outputs),
            "selected_candidate": chosen,
            "human_ratings": "not performed",
            "protocol_status": "proposed",
            "acceptance_record": None,
        },
    )
    return selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument(
        "--config", type=Path, default=Path("configs/baseline-prompts.toml")
    )
    prep.add_argument("--name", required=True)
    prep.add_argument("--cards-dir", type=Path, default=Path("data/cards"))
    prep.add_argument("--runs-dir", type=Path, default=Path("runs"))
    for name in ("run", "score"):
        sub.add_parser(name).add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        parser.error("run from this repository root")
    if args.command == "prepare":
        print(prepare(args.config, args.name, args.cards_dir, args.runs_dir))
    elif args.command == "run":
        generate(args.run_dir)
    else:
        print(dumps(score(args.run_dir)))


if __name__ == "__main__":
    main()
