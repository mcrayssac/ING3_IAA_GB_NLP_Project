"""Human scores beside the paired gains, and the discussed cases (task 4.5).

Usage, from the repository root:
    python -m scripts.final_findings run --run-dir runs/4-2-final-50067b54741c-49b4aea370af \
        --sheet review-rated.csv --initial ratings-initial.jsonl

The sealed 4.2 run is checked first, as in 4.4. The completed 4.3 sheet is then read
with the 4.3 checks, and its primary scores must equal the initial ratings 4.3
imported. The five-axis human means and the justified-refusal review use the shared
evaluator on the 40 reviewed targets, with the same whole-race bootstrap as 4.4. The
automatic summaries are reconciled with the 4.2 record and the committed 4.4
evidence. One case per mechanism is picked by a fixed hash among the reviewed
targets, so no one chooses a case after reading answers. Nothing is generated again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path

from boxbox.data import load_splits
from boxbox.evaluation import bootstrap_compare, observations, pair_outputs, summarize
from boxbox.evaluation._io import (
    dumps,
    loads,
    read_jsonl,
    sha256,
    write_json,
    write_jsonl,
)
from boxbox.runs import source_sha256
from scripts import human_review
from scripts.final_analysis import CONTRASTS, ROOT, RUNS, VERSIONS, check_run
from scripts.mini_test import git

EVIDENCE_4_4 = Path("docs/final-analysis-evidence.json")
DECISIONS = ("BOX", "STAY OUT")
HUMAN_RATES = ("why_supported_rate", "justified_abstention_review_rate")
PRIMARY_FIELDS = ("response_id", "scores", "reasons", "rater_id", "rated_at")
KEPT = ("difference", "difference_interval", "interval_status", "contributing_races")


def is_human(key: str) -> bool:
    last = key.rsplit("/", 1)[-1]
    return last.startswith("human_") or last in HUMAN_RATES


def reconcile(rows: dict, checked: dict) -> str:
    """Automatic summaries equal the 4.2 record and the committed 4.4 evidence."""
    summaries = loads(dumps({v: summarize(rows[v]) for v in VERSIONS}))
    if summaries != checked["recorded"]["evaluator_summaries"]:
        raise ValueError("the summaries differ from those 4.2 recorded")
    committed = loads(EVIDENCE_4_4.read_text(encoding="utf-8"))
    for v in VERSIONS:
        for key, metric in committed["summaries"][v]["metrics"].items():
            if summaries[v]["metrics"][key] != metric:
                raise ValueError(f"{v} {key} differs from {EVIDENCE_4_4}")
    return sha256(EVIDENCE_4_4.read_bytes())


def same_primary(notes: list[dict], initial: Path) -> str:
    """The second review changes no primary score: the sheet equals the 4.3 import."""
    saved, digest = read_jsonl(initial)

    def primary(items: list[dict]) -> list[dict]:
        keep = [{k: n[k] for k in PRIMARY_FIELDS} for n in items]
        return sorted(keep, key=lambda n: n["response_id"])

    if primary(notes) != primary(saved):
        raise ValueError("the sheet's primary scores differ from the initial ratings")
    return digest


def trimmed(measures: dict) -> dict:
    return {k: v for k, v in measures.items() if is_human(k)}


def human_analysis(rows: dict, replications: int) -> tuple[dict, dict]:
    """Human summaries by version and the three contrasts, human measures only."""
    summaries = {
        v: trimmed(summarize(rows[v], human=True)["metrics"]) for v in VERSIONS
    }
    contrasts = {}
    for name, (old, new, role) in CONTRASTS.items():
        result = bootstrap_compare(
            rows, old, new, human=True, replications=replications
        )
        contrasts[name] = {
            "contrast_role": role,
            "settings": result["settings"],
            "metrics": {
                k: {f: m[f] for f in KEPT} | {"valid_draws": m["valid_replications"]}
                for k, m in trimmed(result["metrics"]).items()
            },
        }
    return summaries, contrasts


def strata(by: dict, notes: dict, ids: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Candidate (case, version) pairs of each mechanism, among the reviewed targets."""

    def call(v: str, c: str) -> str | None:
        return by[v][c]["extracted_call"]

    def expected(c: str) -> str:
        return by["A"][c]["reference"]["expected_call"]

    def family(c: str) -> str:
        return by["A"][c]["primary_family"]

    def wrong_reason(c: str, v: str) -> bool:
        return call(v, c) == expected(c) and notes[(c, v)]["scores"]["correctness"] == 0

    return {
        "A decides where the policy refuses": [
            (c, "A")
            for c in ids
            if family(c) == "blocking_incomplete"
            and call("A", c) in DECISIONS
            and call("B", c) == "NO CALL"
        ],
        "B refuses a card that supports a decision": [
            (c, "B")
            for c in ids
            if family(c) == "usable_incomplete"
            and call("B", c) == "NO CALL"
            and call("A", c) == expected(c)
        ],
        "A and B succeed where the baseline fails": [
            (c, "A")
            for c in ids
            if family(c) in ("out_of_scope", "follow_up")
            and call("A", c) == call("B", c) == expected(c)
            and call("baseline", c) != expected(c)
        ],
        "The baseline gives no valid call on a NO CALL target": [
            (c, "baseline")
            for c in ids
            if expected(c) == "NO CALL"
            and call("baseline", c) not in (*DECISIONS, "NO CALL")
        ],
        "Right call, wrong reason": [
            (c, v) for c in ids for v in VERSIONS if wrong_reason(c, v)
        ],
    }


def pick(name: str, candidates: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The first candidate by the hash of the stratum, case and version."""
    return min(
        candidates,
        key=lambda k: hashlib.sha256(
            f"boxbox-eval|1.1.0|2026|findings|{name}|{k[0]}|{k[1]}".encode()
        ).hexdigest(),
        default=None,
    )


def case_record(name: str, size: int, pair: tuple[str, str], by: dict, notes: dict):
    """Input, reference and every version's answer with its human reading."""
    cid, version = pair
    case = by["A"][cid]

    def reading(v: str) -> dict:
        n = notes[(cid, v)]
        second = n["second_review"]
        return {
            "scores": n["scores"],
            "reasons": n["reasons"],
            "flags": n["sensitivity_flags"],
            "second_review": second["verdict"] if second else None,
        }

    return {
        "mechanism": name,
        "candidates": size,
        "case_id": cid,
        "highlighted_version": version,
        "race_id": case["race_id"],
        "family": case["primary_family"],
        "card": case["card"],
        "history": case["history"],
        "message": case["message"],
        "expected_call": case["reference"]["expected_call"],
        "reference_why": case["reference"]["why_reference"],
        "versions": {
            v: {
                "call": by[v][cid]["extracted_call"],
                "strict_format": by[v][cid]["strict_format_valid"],
                "response": by[v][cid]["raw_response"],
                "human": reading(v),
            }
            for v in VERSIONS
        },
    }


def bare_no_call(rows: list[dict]) -> dict:
    """Invalid labels that still open with NO CALL, by expected label (strict parsing)."""
    invalid = [r for r in rows if r["extracted_call"] is None]
    bare = [
        r for r in invalid if r["raw_response"].lstrip().upper().startswith("NO CALL")
    ]
    return {
        "invalid_labels": len(invalid),
        "open_with_no_call": len(bare),
        "by_expected_call": dict(
            Counter(r["reference"]["expected_call"] for r in bare)
        ),
    }


def call_against_reading(by: dict, notes: dict, ids: list[str]) -> dict:
    """Per version, where the parsed call and the human reading disagree."""
    result = {}
    for v in VERSIONS:
        right = [
            c
            for c in ids
            if by[v][c]["extracted_call"] == by["A"][c]["reference"]["expected_call"]
        ]
        wrong = [c for c in ids if c not in right]
        result[v] = {
            "right_call": len(right),
            "right_call_wrong_reason": sum(
                notes[(c, v)]["scores"]["correctness"] == 0 for c in right
            ),
            "wrong_call_full_credit": sum(
                notes[(c, v)]["scores"]["correctness"] == 2 for c in wrong
            ),
            "invented_number_flags": sum(
                "invented_or_unauthorised_number" in notes[(c, v)]["sensitivity_flags"]
                for c in ids
            ),
        }
    return result


def analyse(checked: dict, notes: list[dict], ids: list[str], replications: int):
    cases = checked["cases"]
    paired = pair_outputs(
        cases, checked["outputs"], VERSIONS, checked["cases_sha256"], load_splits()
    )
    plain = observations(cases, paired)
    evidence_4_4 = reconcile(plain, checked)
    rows = observations(cases, paired, notes, ids)
    by = {v: {r["case_id"]: r for r in rows[v]} for v in VERSIONS}
    index = {(n["case_id"], n["version_id"]): n for n in notes}
    summaries, contrasts = human_analysis(rows, replications)
    candidates = strata(by, index, ids)
    picked = {name: pick(name, c) for name, c in candidates.items()}
    for name, pair in picked.items():
        if pair is None:
            print(f"warning: no candidate for {name!r}")
    second = [n["second_review"] for n in notes if n["second_review"]]
    return {
        "task": "4.5",
        "evidence_4_4_sha256": evidence_4_4,
        "reviewed_targets": len(ids),
        "human": {"summaries": summaries, "contrasts": contrasts},
        "call_against_reading": call_against_reading(by, index, ids),
        "baseline_bare_no_call": bare_no_call(plain["baseline"]),
        "second_review": {
            "rows": len(second),
            "verdicts": dict(Counter(s["verdict"] for s in second)),
            "reviewers": sorted({s["reviewer_id"] for s in second}),
            "with_independent_scores": sum(bool(s.get("scores")) for s in second),
            "primary_raters": sorted({n["rater_id"] for n in notes}),
        },
        "cases": [
            case_record(name, len(candidates[name]), pair, by, index)
            for name, pair in picked.items()
            if pair
        ],
    }


def run(
    run_dir: Path,
    sheet: Path,
    initial: Path,
    replications: int = 10000,
    runs_dir: Path = RUNS,
) -> Path:
    """Check the 4.2 run and the 4.3 sheet, analyse them, write a new 4.5 run folder."""
    started = time.time()
    checked = check_run(run_dir)
    report, notes = human_review.check(run_dir, sheet)
    if not all(report["ready"].values()):
        raise ValueError(f"the review is not complete: {report['ready']}")
    initial_sha = same_primary(notes, initial)
    ids = loads((run_dir / "review-selection.json").read_text())["selected_case_ids"]
    result = analyse(checked, notes, ids, replications)
    folder = runs_dir / f"{date.today().isoformat()}_4-5-final-findings"
    folder.mkdir(parents=True)  # an existing reading is never overwritten
    ratings_sha = write_jsonl(folder / "ratings.jsonl", notes)
    result["provenance"] = {
        "input_run": run_dir.name,
        "complete_sha256": checked["recorded"]["complete_sha256"],
        "sheet_sha256": report["sheet_sha256"],
        "initial_ratings_sha256": initial_sha,
        "ratings_with_second_review_sha256": ratings_sha,
    }
    result["analysis_script_sha256"] = sha256(Path(__file__).read_bytes())
    write_json(folder / "evidence.json", result)
    write_json(
        folder / "manifest.json",
        {
            "task": "4.5",
            "git_commit": git("rev-parse", "HEAD") or None,
            "git_dirty": bool(git("status", "--porcelain")),
            "source_sha256": source_sha256(),
            "provenance": result["provenance"],
            "analysis_script_sha256": result["analysis_script_sha256"],
            "evidence_sha256": sha256((folder / "evidence.json").read_bytes()),
            "replications": replications,
            "protocol_settings": all(
                c["settings"]["protocol_settings"]
                for c in result["human"]["contrasts"].values()
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
    run_args.add_argument("--sheet", type=Path, required=True)
    run_args.add_argument("--initial", type=Path, required=True)
    run_args.add_argument("--replications", type=int, default=10000)
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    folder = run(args.run_dir, args.sheet, args.initial, args.replications)
    print(
        json.dumps(loads((folder / "manifest.json").read_text()), indent=2, default=str)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
