"""Paired gains and race-level uncertainty on the frozen final outputs (task 4.4).

Usage, from the repository root:
    python -m scripts.final_analysis run --run-dir runs/4-2-final-50067b54741c-49b4aea370af

The sealed 4.2 run is checked first: the freeze gate, its completion record against the
hash 4.2 published in docs/final-scoring-results.json, its file inventory, and its cases
against data/final. The analysis then follows protocol 1.1.0 and makes no choice of its
own. A minus baseline and B minus A are the principal contrasts and B minus baseline is
exploratory, each with the whole-race bootstrap of the shared evaluator (seed 2026,
10,000 draws, 95% type-7 percentile interval). Every automatic measure comes from the
shared evaluator, overall, by family and by expected label. The results go to a new run
folder and are never overwritten. Nothing is generated again; the final outputs are
only read.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path

from boxbox.data import load_splits
from boxbox.evaluation import bootstrap_compare, observations, pair_outputs, summarize
from boxbox.evaluation._io import dumps, loads, read_jsonl, sha256, write_json
from boxbox.runs import source_sha256
from scripts.final_cases import gate
from scripts.final_scoring import inventory
from scripts.interim_analysis import transitions
from scripts.mini_test import git

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path("runs")
FINAL_CASES = Path("data/final/cases.jsonl")
RESULTS_4_2 = Path("docs/final-scoring-results.json")
VERSIONS = ["baseline", "A", "B"]
# Protocol 1.1.0, section 6: principal contrasts first, the third is exploratory.
CONTRASTS = {
    "A_minus_baseline": ("baseline", "A", "principal"),
    "B_minus_A": ("A", "B", "principal"),
    "B_minus_baseline": ("baseline", "B", "exploratory"),
}


def check_run(run: Path, results: Path | None = None) -> dict:
    """The sealed 4.2 run, refused unless it is byte for byte the one 4.2 published."""
    gate()  # the freeze must hold before any final file is read
    recorded = loads((results or RESULTS_4_2).read_text(encoding="utf-8"))
    complete = run / "complete.json"
    if sha256(complete.read_bytes()) != recorded["complete_sha256"]:
        raise ValueError("complete.json is not the record 4.2 published")
    found = inventory(run)
    found.pop("complete.json", None)
    if found != loads(complete.read_text(encoding="utf-8"))["files"]:
        raise ValueError("the run's files differ from its completion record")
    cases, cases_hash = read_jsonl(run / "cases.jsonl")
    if cases_hash != sha256(FINAL_CASES.read_bytes()):
        raise ValueError("the run's cases are not data/final/cases.jsonl")
    return {
        "recorded": recorded,
        "cases": cases,
        "cases_sha256": cases_hash,
        "outputs": read_jsonl(run / "outputs.jsonl")[0],
        "attempts": read_jsonl(run / "attempts.jsonl")[0],
    }


def identities(summary: dict) -> dict:
    """Protocol section 5: on Z and on D, the three outcomes cover every target."""
    m = summary["metrics"]
    z = (
        m["overall/justified_abstention_call_rate"]["numerator"]
        + m["overall/unjustified_decision_rate"]["numerator"]
        + m["eligibility/Z/unusable_label_rate"]["numerator"]
    )
    d = (
        m["overall/eligible_decision_coverage"]["numerator"]
        + m["overall/excessive_refusal_rate"]["numerator"]
        + m["eligibility/D/unusable_label_rate"]["numerator"]
    )
    return {
        "Z": [z, m["overall/unjustified_decision_rate"]["denominator"]],
        "D": [d, m["overall/excessive_refusal_rate"]["denominator"]],
    }


def truncation(attempts: list[dict], paired: dict) -> dict:
    """Stop conditions by version, and answers cut at the token limit yet well formed."""
    result = {}
    for v in VERSIONS:
        traces = [
            (a["case_id"], a["trace"] or {}) for a in attempts if a["version_id"] == v
        ]
        cut = [cid for cid, t in traces if t.get("possibly_truncated")]
        result[v] = {
            "stop_conditions": dict(
                Counter(str(t.get("stop_condition")) for _, t in traces)
            ),
            "possibly_truncated": len(cut),
            "cut_but_strict_format": sum(
                paired[v][cid]["strict_format_valid"] for cid in cut
            ),
        }
    return result


def analyse(checked: dict, replications: int = 10000) -> dict:
    """Summaries, the three contrasts, paired transitions and truncation, from the evaluator."""
    cases, cases_hash = checked["cases"], checked["cases_sha256"]
    paired = pair_outputs(
        cases, checked["outputs"], VERSIONS, cases_hash, load_splits()
    )
    rows = observations(cases, paired)
    summaries = {v: summarize(rows[v]) for v in VERSIONS}
    recorded = checked["recorded"].get("evaluator_summaries")
    if recorded is not None and loads(dumps(summaries)) != recorded:
        raise ValueError("the summaries differ from those 4.2 recorded")
    contrasts = {}
    for name, (old, new, role) in CONTRASTS.items():
        result = bootstrap_compare(rows, old, new, replications=replications)
        contrasts[name] = result | {
            "contrast_role": role,
            "transitions": transitions(rows, old, new),
        }
    return {
        "task": "4.4",
        "cases_sha256": cases_hash,
        "versions": VERSIONS,
        "response_ids": {
            v: sorted(r["response_id"] for r in paired[v].values()) for v in VERSIONS
        },
        "summaries": summaries,
        "identities": {v: identities(s) for v, s in summaries.items()},
        "contrasts": contrasts,
        "truncation": truncation(checked["attempts"], paired),
    }


def compact(analysis: dict) -> dict:
    """The committed evidence: overall, family and label measures, and the contrasts' cores."""
    keep = ("overall/", "family/", "label/", "eligibility/")
    fields = (
        "difference",
        "difference_interval",
        "interval_status",
        "contributing_races",
    )
    return {
        "cases_sha256": analysis["cases_sha256"],
        "summaries": {
            v: {
                "metrics": {
                    k: {
                        f: m[f] for f in ("numerator", "denominator", "value", "status")
                    }
                    for k, m in s["metrics"].items()
                    if k.startswith(keep)
                },
                "confusion": s["confusion"],
            }
            for v, s in analysis["summaries"].items()
        },
        "identities": analysis["identities"],
        "contrasts": {
            name: {
                "old": c["old"],
                "new": c["new"],
                "contrast_role": c["contrast_role"],
                "settings": c["settings"],
                "draws_sha256": c["draws_sha256"],
                "race_case_counts": c["race_case_counts"],
                "largest_race_case_share": c["largest_race_case_share"],
                "transitions": c["transitions"]["counts"],
                "metrics": {
                    k: {f: m[f] for f in fields}
                    | {"valid_draws": m["valid_replications"]}
                    for k, m in c["metrics"].items()
                    if k.startswith(keep)
                },
            }
            for name, c in analysis["contrasts"].items()
        },
        "truncation": analysis["truncation"],
    }


def run(run_dir: Path, replications: int = 10000, runs_dir: Path = RUNS) -> Path:
    """Check the 4.2 run, analyse it, and write a new 4.4 run folder."""
    started = time.time()
    checked = check_run(run_dir)
    analysis = analyse(checked, replications)
    folder = runs_dir / f"{date.today().isoformat()}_4-4-final-analysis"
    folder.mkdir(parents=True)  # an existing analysis is never overwritten
    write_json(folder / "analysis.json", analysis)
    write_json(folder / "evidence.json", compact(analysis))
    write_json(
        folder / "manifest.json",
        {
            "task": "4.4",
            "git_commit": git("rev-parse", "HEAD") or None,
            "git_dirty": bool(git("status", "--porcelain")),
            "source_sha256": source_sha256(),
            "input_run": run_dir.name,
            "complete_sha256": checked["recorded"]["complete_sha256"],
            "outputs_sha256": sha256((run_dir / "outputs.jsonl").read_bytes()),
            "cases_sha256": checked["cases_sha256"],
            "replications": replications,
            "protocol_settings": all(
                c["settings"]["protocol_settings"]
                for c in analysis["contrasts"].values()
            ),
            "duration_seconds": round(time.time() - started, 1),
        },
    )
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run_args = commands.add_parser("run")
    run_args.add_argument("--run-dir", type=Path, required=True)
    run_args.add_argument("--replications", type=int, default=10000)
    args = parser.parse_args(argv)
    # configs/, data/final and runs/ are relative to the repository root
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    folder = run(args.run_dir, args.replications)
    print(
        json.dumps(loads((folder / "manifest.json").read_text()), indent=2, default=str)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
