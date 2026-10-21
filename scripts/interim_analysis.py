"""Audit the retained 3.2 evidence for the 3.3 interim analysis, without inference.

From the repository root, use ``python -m scripts.interim_analysis`` with:
    --runs-root PATH_TO_EXTRACTED_3_2_RUNS --output NEW_JSON

The selected mini-test is fixed before this analysis: 2026-10-21_3-2-mini-test-r2.
Missing A validation ledgers remain an explicit limit of the retained summary.
No final case, model weight, network service or human rating is read or created.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

from boxbox.corpus import check_corpus_b
from boxbox.evaluation import (
    bootstrap_compare,
    observations,
    pair_outputs,
    select_prompt,
    summarize,
)
from boxbox.evaluation._io import dumps, loads, read_jsonl, sha256
from scripts.train_adapter import METRICS, seed_interval

ROOT = Path(__file__).resolve().parents[1]
MINI = "2026-10-21_3-2-mini-test-r2"
SUMMARY = "2026-10-21_3-2-adapter-b-summary.json"
SEEDS = (2026, 2027, 2028)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def same(actual: object, expected: object, context: str) -> None:
    """Compare JSON values without rounding metric counts or fractions."""
    require(dumps(actual) == dumps(expected), f"{context}: retained value differs")


class Evidence:
    """Read named evidence and retain byte hashes without machine-specific paths."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def file(self, root: Path, relative: str, namespace: str = "runs") -> Path:
        path = (root / relative).resolve()
        require(path.is_relative_to(root.resolve()), "evidence path escapes its root")
        require("final" not in Path(relative).parts, "final evidence is forbidden")
        self.files[f"{namespace}/{relative}"] = sha256(path.read_bytes())
        return path

    def json(self, root: Path, relative: str, namespace: str = "runs") -> dict:
        return loads(self.file(root, relative, namespace).read_text(encoding="utf-8"))


def trace_checks(cases: list[dict], paired: dict, attempts: list[dict]) -> dict:
    """Check the complete trace matrix, raw answers and common prompts."""
    traces = {a["response_id"]: a for a in attempts}
    expected = {r["response_id"] for rows in paired.values() for r in rows.values()}
    require(len(traces) == len(attempts) and traces.keys() == expected, "trace matrix")
    tokens, durations, cuts, reduced = {}, {}, {}, {}
    common_settings = None
    for version, rows in paired.items():
        tokens[version], durations[version], cuts[version], reduced[version] = (
            [],
            [],
            [],
            [],
        )
        for case in cases:
            row = rows[case["case_id"]]
            attempt = traces[row["response_id"]]
            for key in ("case_id", "version_id", "input_sha256"):
                same(attempt[key], row[key], f"trace {key}")
            trace = attempt["trace"]
            same(trace["raw_response"], row["raw_response"], "trace raw response")
            require(bool(trace["prompt_token_ids_sha256"]), "missing token hash")
            same(
                sha256(trace["instructions"]),
                trace["instructions_sha256"],
                "instructions hash",
            )
            same(
                sha256(dumps(trace["messages"])),
                trace["prompt_messages_sha256"],
                "messages hash",
            )
            same(
                len(trace["generated_token_ids"]),
                trace["generated_tokens"],
                "generated tokens",
            )
            settings = {
                k: v for k, v in trace["generation_settings"].items() if k != "seed"
            }
            if common_settings is None:
                common_settings = settings
            same(settings, common_settings, "generation settings")
            same(trace["history"]["retained"], case["history"], "fixed history")
            tokens[version].append(trace["prompt_token_ids_sha256"])
            durations[version].append(trace["duration_seconds"])
            if trace["possibly_truncated"]:
                cuts[version].append(case["case_id"])
            if trace["history"]["was_reduced"]:
                reduced[version].append(case["case_id"])
    versions = list(paired)
    same_prompt = {
        v: sum(a == b for a, b in zip(tokens[versions[0]], tokens[v])) for v in versions
    }
    # Different validation epochs of B and different mini-test versions must share inputs.
    require(all(n == len(cases) for n in same_prompt.values()), "prompt tokens differ")
    return {
        "traces": len(attempts),
        "same_prompt_tokens": same_prompt,
        "possibly_truncated_case_ids": cuts,
        "reduced_history_case_ids": reduced,
        "generation_seconds": {v: sum(ds) for v, ds in durations.items()},
    }


def transitions(rows: dict, old: str, new: str) -> dict:
    """Pair outcomes by target, preserving every regression and invalid label."""
    same(len(rows[old]), len(rows[new]), "transition matrix size")
    changes: dict[str, list[str]] = {
        "both_correct": [],
        "new_only_correct": [],
        "old_only_correct": [],
        "both_wrong": [],
    }
    labels: Counter = Counter()
    for a, b in zip(rows[old], rows[new]):
        same(a["case_id"], b["case_id"], "transition case")
        expected = a["reference"]["expected_call"]
        ac, bc = a["extracted_call"] == expected, b["extracted_call"] == expected
        key = (
            ("both_correct" if bc else "old_only_correct")
            if ac
            else ("new_only_correct" if bc else "both_wrong")
        )
        changes[key].append(a["case_id"])
        labels[
            (
                expected,
                a["extracted_call"] or "INVALID",
                b["extracted_call"] or "INVALID",
            )
        ] += 1
    return {
        "counts": {k: len(v) for k, v in changes.items()},
        "case_ids": changes,
        "label_transitions": [
            {"expected": e, "old": a, "new": b, "count": n}
            for (e, a, b), n in sorted(labels.items())
        ],
    }


def compact_bootstrap(result: dict) -> dict:
    return {
        key: value
        if key != "metrics"
        else {k: v for k, v in value.items() if k.startswith("overall/")}
        for key, value in result.items()
    }


def mini_test(evidence: Evidence, runs: Path) -> dict:
    run = runs / MINI
    plan = evidence.json(runs, f"{MINI}/plan.json")
    same(plan["version_ids"], ["baseline", "A", "B"], "retained versions")
    same(plan["split"], "mini_test", "analysis split")
    expected_normative = {
        "boxbox/rules/decision.py",
        "data/corpus/manifest.json",
        "data/corpus/mini_test.jsonl",
        "data/splits.json",
        "docs/evaluation-protocol.md",
        "reference/evaluation-fixtures.json",
        "reference/fixtures.json",
    }
    same(sorted(plan["normative_files"]), sorted(expected_normative), "normative scope")
    split_ids = loads((ROOT / "data/splits.json").read_text())["splits"]["mini_test"]
    allowed = (
        {"cases.jsonl", "inputs.jsonl"}
        | {f"sources/{p}" for p in expected_normative}
        | {f"sources/data/cards/{race}.jsonl" for race in split_ids}
        | {"sources/data/cards/mini_test-manifest.json"}
        | {
            f"versions/{v}/{p}"
            for v in ("baseline", "A", "B")
            for p in ("config.toml", "prompt.txt", "adapter_config.json")
        }
    )
    require(set(plan["sealed_files"]) <= allowed, "sealed file outside mini-test scope")
    for relative, digest in plan["sealed_files"].items():
        path = evidence.file(run, relative, MINI)
        same(sha256(path.read_bytes()), digest, f"sealed {relative}")
    for relative, digest in plan["normative_files"].items():
        path = evidence.file(ROOT, relative, "repository")
        same(sha256(path.read_bytes()), digest, f"normative {relative}")
    manifest = evidence.json(runs, f"{MINI}/manifest.json")
    same(
        manifest["extra"]["mini_test"]["plan_sha256"],
        sha256((run / "plan.json").read_bytes()),
        "plan hash",
    )
    complete = evidence.json(runs, f"{MINI}/attempt-complete.json")
    for name in ("outputs", "attempts"):
        path = evidence.file(run, f"{name}.jsonl", MINI)
        same(sha256(path.read_bytes()), complete[f"{name}_sha256"], f"{name} hash")
    cases, digest = read_jsonl(run / "cases.jsonl")
    outputs = read_jsonl(run / "outputs.jsonl")[0]
    same(digest, plan["cases_sha256"], "case hash")
    same(
        [loads(c["input_json"]) for c in cases],
        read_jsonl(run / "inputs.jsonl")[0],
        "input ledger",
    )
    splits = loads((run / "sources/data/splits.json").read_text())
    require(all(c["split"] == "mini_test" for c in cases), "non-mini-test case")
    paired = pair_outputs(cases, outputs, plan["version_ids"], digest, splits)
    for version, records in paired.items():
        for row in records.values():
            same(
                row["config_sha256"],
                plan["versions"][version]["config_sha256"],
                "output config",
            )
    rows = observations(cases, paired)
    summaries = {v: summarize(rs) for v, rs in rows.items()}
    same(
        summaries, evidence.json(runs, f"{MINI}/summaries.json"), "mini-test summaries"
    )
    contrasts = {}
    retained_b = evidence.json(runs, f"{MINI}/bootstrap-B.json")
    for old, new, saved in (
        ("baseline", "A", evidence.json(runs, f"{MINI}/bootstrap.json")),
        ("A", "B", retained_b["B_minus_A"]),
        ("baseline", "B", retained_b["B_minus_baseline"]),
    ):
        calculated = bootstrap_compare(rows, old, new)
        same(
            calculated,
            {k: v for k, v in saved.items() if k != "contrast_role"},
            f"{new}-{old} bootstrap",
        )
        contrasts[f"{new}_minus_{old}"] = compact_bootstrap(calculated) | {
            "transitions": transitions(rows, old, new)
        }
    traces = trace_checks(cases, paired, read_jsonl(run / "attempts.jsonl")[0])
    with evidence.file(run, "review/review.csv", MINI).open(newline="") as stream:
        rating_status = Counter(r["rating_status"] for r in csv.DictReader(stream))
    original = runs / "2026-10-21_3-2-mini-test"
    repeat = None
    if original.exists():
        prior = read_jsonl(evidence.file(original, "outputs.jsonl", original.name))[0]
        fields = ("case_id", "version_id", "raw_response", "status", "error")
        same(
            [{k: r[k] for k in fields} for r in outputs],
            [{k: r[k] for k in fields} for r in prior],
            "original versus r2 answers",
        )
        repeat = (
            "all 120 raw answers/status/errors identical; not an independent sample"
        )
    return {
        "run": MINI,
        "verification": "recomputed_from_retained_outputs",
        "plan_head": plan["head_sha"],
        "population": plan["population"],
        "versions": plan["versions"],
        "summaries": {
            v: {
                "metrics": {
                    k: m
                    for k, m in s["metrics"].items()
                    if k.startswith("overall/")
                    or k.startswith(("family/", "label/"))
                    and k.endswith("/call_agreement")
                },
                "confusion": s["confusion"],
            }
            for v, s in summaries.items()
        },
        "contrasts": contrasts,
        "trace_checks": traces,
        "human_rating_status": dict(rating_status),
        "original_run_comparison": repeat,
        "duration_seconds": manifest["duration_seconds"],
        "protocol": manifest["extra"]["evaluation"],
    }


def validation(evidence: Evidence, runs: Path) -> dict:
    retained = evidence.json(runs, SUMMARY)
    same(len(retained["seeds"]), len(SEEDS), "three B seeds")
    splits = loads((ROOT / "data/splits.json").read_text())
    results = []
    a_metrics, b_metrics = [], []
    for seed, entry in zip(SEEDS, retained["seeds"]):
        run = runs / entry["run"]
        require(run.name.endswith(f"-s{seed}"), "unexpected seed ordering")
        cases, digest = read_jsonl(
            evidence.file(run, "validation-cases.jsonl", run.name)
        )
        require(all(c["split"] == "validation" for c in cases), "non-validation case")
        same(
            digest,
            loads((ROOT / "configs/adapter-b-selection.json").read_text())[
                "cases_sha256"
            ],
            "validation cases",
        )
        outputs = read_jsonl(evidence.file(run, "validation-outputs.jsonl", run.name))[
            0
        ]
        versions = [f"B-s{seed}-e{epoch}" for epoch in (1, 2, 3)]
        paired = pair_outputs(cases, outputs, versions, digest, splits)
        rows = observations(cases, paired)
        summaries = {v: summarize(rs) for v, rs in rows.items()}
        same(
            summaries,
            evidence.json(run, "validation-summaries.json", run.name),
            "B validation summaries",
        )
        selection = evidence.json(run, "selection.json", run.name)
        same(
            select_prompt(summaries, versions),
            {k: v for k, v in selection.items() if k not in {"reload", "reload_ok"}},
            "B checkpoint selection",
        )
        same(entry["version"], selection["selected_candidate"], "B selected checkpoint")
        contrast = retained["against_a"]["per_seed"][entry["version"]]
        bm = {k: summaries[entry["version"]]["metrics"][k]["value"] for k in METRICS}
        same(bm, entry["metrics"], "B seed metrics")
        am = {}
        for metric in METRICS:
            saved = contrast["bootstrap"]["metrics"][metric]
            same(
                saved["new"],
                {
                    k: v
                    for k, v in summaries[entry["version"]]["metrics"][metric].items()
                    if k not in {"direction", "missing_components"}
                },
                "B bootstrap point",
            )
            am[metric] = saved["old"]["value"]
            require(
                math.isclose(
                    float(saved["difference"]),
                    float(bm[metric]) - float(am[metric]),
                    abs_tol=1e-14,
                ),
                "retained validation difference",
            )
        a_metrics.append(am)
        b_metrics.append(bm)
        results.append(
            {
                "seed": seed,
                "run": run.name,
                "selected": entry["version"],
                "B_summaries": {
                    v: {k: s["metrics"][k] for k in METRICS}
                    for v, s in summaries.items()
                },
                "paired_A_version": contrast["against"],
                "retained_AB_bootstrap": compact_bootstrap(contrast["bootstrap"]),
                "trace_checks": trace_checks(
                    cases,
                    paired,
                    read_jsonl(
                        evidence.file(run, "validation-attempts.jsonl", run.name)
                    )[0],
                ),
                "training_metrics": {
                    k: v
                    for k, v in evidence.json(run, "metrics.json", run.name).items()
                    if k != "train_losses"
                },
                "manifest": evidence.json(run, "manifest.json", run.name),
                "reload": selection["reload"],
            }
        )
    for metric in METRICS:
        same(
            seed_interval([m[metric] for m in b_metrics]),
            retained["seed_intervals"][metric],
            "B seed interval",
        )
        same(
            seed_interval(
                [
                    float(b[metric]) - float(a[metric])
                    for a, b in zip(a_metrics, b_metrics)
                ]
            ),
            retained["against_a"]["over_seeds"][metric],
            "paired seed interval arithmetic",
        )
    return {
        "B_verification": "900 retained outputs rescored; all nine checkpoints reranked",
        "AB_verification": "A points and race intervals retained in 3.2 summary; paired seed arithmetic checked; A raw validation outputs unavailable",
        "seeds": results,
        "B_seed_intervals": retained["seed_intervals"],
        "paired_seed_intervals": retained["against_a"]["over_seeds"],
        "equal_updates_retained_summary_only": retained["against_a"]["equal_updates"],
        "same_prompts_AB_retained_summary_only": {
            k: v["same_prompts"] for k, v in retained["against_a"]["per_seed"].items()
        },
    }


def corpus(evidence: Evidence) -> dict:
    splits = evidence.json(ROOT, "data/splits.json", "repository")
    items = {
        name: read_jsonl(
            evidence.file(ROOT, f"data/corpus/{name}.jsonl", "repository")
        )[0]
        for name in ("A_train", "B_train")
    }
    require(
        not check_corpus_b(
            items["A_train"], items["B_train"], set(splits["splits"]["train"])
        ),
        "matched corpus check failed",
    )
    result = {}
    for name, rows in items.items():
        result[name] = {
            "items": len(rows),
            "first_turn_calls": dict(
                Counter(r["messages"][1]["content"].splitlines()[0] for r in rows)
            ),
            "all_assistant_turn_calls": dict(
                Counter(
                    m["content"].splitlines()[0]
                    for r in rows
                    for m in r["messages"]
                    if m["role"] == "assistant"
                )
            ),
            "kinds": dict(Counter(r["kind"] for r in rows)),
        }
    result["exposure"] = evidence.json(ROOT, "data/corpus/exposure.json", "repository")
    return result


def training_logs(evidence: Evidence, runs: Path, a_logs: Path) -> dict:
    """Matching displayed logs do not prove identity of the unrounded weights."""
    result = {}
    for seed in SEEDS:
        logs = []
        for folder, namespace in ((a_logs, "A_logs"), (runs / "3-2-logs", "B_logs")):
            text = evidence.file(folder, f"seed-{seed}.log", namespace).read_text()
            entries = []
            for line in text.splitlines():
                match = re.search(r"\{'loss': .*", line)
                if match:
                    entries.append(ast.literal_eval(match[0]))
            same(len(entries), 360, f"{namespace} update count")
            require(
                all(math.isfinite(float(r["loss"])) for r in entries),
                "nonfinite displayed loss",
            )
            logs.append(entries)
        a, b = logs
        result[str(seed)] = {
            "A_updates": len(a),
            "B_updates": len(b),
            "first_different_displayed_loss_update": next(
                (i for i, (x, y) in enumerate(zip(a, b), 1) if x["loss"] != y["loss"]),
                None,
            ),
            "first_different_token_count_update": next(
                (
                    i
                    for i, (x, y) in enumerate(zip(a, b), 1)
                    if x["num_tokens"] != y["num_tokens"]
                ),
                None,
            ),
            "first_A": a[0],
            "first_B": b[0],
        }
    return result


def analyze(runs: Path, a_logs: Path | None = None) -> dict:
    """Recompute automatic evidence; never fill in absent A ledgers or human notes."""
    evidence = Evidence()
    result = {
        "task": "3.3",
        "study_status": "interim_exploratory_not_a_freeze",
        "corpus": corpus(evidence),
    }
    result["mini_test"] = mini_test(evidence, runs)
    result["validation"] = validation(evidence, runs)
    if a_logs is not None:
        result["training_log_comparison"] = training_logs(evidence, runs, a_logs)
    evidence.file(ROOT, "scripts/interim_analysis.py", "repository")
    result["input_sha256"] = evidence.files
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument(
        "--a-logs", type=Path, help="Optional extracted 2-6-logs directory."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="A new file; existing evidence is never overwritten.",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = analyze(args.runs_root, args.a_logs)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        # The exact count/fraction objects remain in the JSON alongside display values.
        stream.write(
            json.dumps(json.loads(dumps(result)), indent=2, ensure_ascii=False) + "\n"
        )
    print(
        f"Verified 120 mini-test and 900 B validation responses; evidence: {args.output}"
    )
    print(
        "A validation race contrasts remain retained-summary evidence; human ratings remain pending."
    )


if __name__ == "__main__":
    main()
