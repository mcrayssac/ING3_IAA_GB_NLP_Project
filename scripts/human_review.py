"""Prepare, check and import the 4.3 review of the frozen final run.

python -m scripts.human_review page --run-dir RUN --sheet SHEET --output PAGE.html
python -m scripts.human_review check --run-dir RUN --sheet SHEET
python -m scripts.human_review import --run-dir RUN --sheet SHEET --output RATINGS.jsonl

The page and the sheet hold only the masked review columns. Version identities stay
in the run's lookup and key: the checks read them but never print them. Nothing here
scores a response. Scores, reasons and reviewer names come from the people who fill
the sheet; optional suggestions are shown beside a row and copied only on request.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from boxbox.evaluation import import_review
from boxbox.evaluation._io import AXES, loads, read_jsonl, sha256, write_jsonl

PAGE = Path(__file__).with_name("review_page.html")
FLAGS = (
    "invented_or_unauthorised_number",
    "optimality_promise",
    "false_history_correction",
    "scope_dispute",
    "applicability_or_reference_ambiguity",
    "disagreement_review_requested",
    "suspected_unmasking",
)
VERDICTS = {"agrees", "disagrees", "unsure"}


def read(path: Path):
    return loads(path.read_text(encoding="utf-8"))


def run_inputs(run: Path) -> tuple[dict, list[dict], list[str]]:
    lookup = read(run / "review" / "response-lookup.json")
    cases, _ = read_jsonl(run / "cases.jsonl")
    with (run / "review" / "review.csv").open(encoding="utf-8", newline="") as stream:
        columns = next(csv.reader(stream))
    return lookup, cases, columns


def sheet_rows(sheet: Path, columns: list[str]) -> list[dict]:
    with sheet.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != columns:
            raise ValueError("sheet columns differ from the exported review sheet")
        return list(reader)


def locate(sheet: Path, lookup: dict, cases: list[dict], columns: list[str]) -> list:
    """Name the rows the shared importer refuses, one row at a time."""
    problems = []
    with tempfile.TemporaryDirectory() as folder:
        for row in sheet_rows(sheet, columns):
            rid = row.get("review_id", "")
            if rid not in lookup:
                problems.append((rid, "unknown review ID"))
                continue
            single = Path(folder) / f"{rid}.csv"
            with single.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerow(row)
            try:
                import_review(single, {rid: lookup[rid]}, cases)
            except (ValueError, TypeError, KeyError) as error:
                problems.append((rid, str(error)))
    return problems


def stamp(value) -> None:
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("timestamp requires ISO format with a timezone")


def check_second(note: dict) -> None:
    second, decision = note["second_review"], note["adjudication"]
    if second is not None:
        reviewer = second.get("reviewer_id") if isinstance(second, dict) else None
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("second review requires an actual reviewer")
        if reviewer == note["rater_id"]:
            raise ValueError("second review must come from another teammate")
        stamp(second.get("reviewed_at"))
        if second.get("verdict") not in VERDICTS:
            raise ValueError("second review verdict must be agrees/disagrees/unsure")
        if not isinstance(second.get("notes"), str) or not second["notes"].strip():
            raise ValueError("second review requires notes")
        scores = second.get("scores", {})
        if not isinstance(scores, dict) or not set(scores) <= set(AXES):
            raise ValueError("second review scores use the five axes")
        for axis, score in scores.items():
            allowed = (0, 1, 2) if note["applicability"][axis] else ("N/A",)
            if score not in allowed or type(score) is bool:
                raise ValueError(f"invalid second review score for {axis}")
    if decision is not None:
        if second is None:
            raise ValueError("a resolution requires a recorded second review")
        if not isinstance(decision, dict):
            raise ValueError("resolution must be an object")
        people = decision.get("participants")
        if (
            not isinstance(people, list)
            or not people
            or any(not isinstance(p, str) or not p.strip() for p in people)
        ):
            raise ValueError("resolution requires its actual participants")
        stamp(decision.get("decided_at"))
        if decision.get("status") not in {"resolved", "unresolved"}:
            raise ValueError("resolution status must be resolved or unresolved")
        if (
            not isinstance(decision.get("reason"), str)
            or not decision["reason"].strip()
        ):
            raise ValueError("resolution requires a reason")


def triggers(note: dict) -> list[str]:
    found = list(note["sensitivity_flags"])
    if note["scores"]["factuality"] in (0, 1):
        found.append("factuality_0_1")
    return found


def check(run: Path, sheet: Path) -> tuple[dict, list[dict]]:
    lookup, cases, columns = run_inputs(run)
    sheet_rows(sheet, columns)
    try:
        notes = import_review(sheet, lookup, cases)
    except (ValueError, TypeError, KeyError) as error:
        detail = "; ".join(
            f"{rid}: {why}" for rid, why in locate(sheet, lookup, cases, columns)
        )
        raise ValueError(f"{error} ({detail or 'sheet-level problem'})") from error
    raters, statuses = defaultdict(set), Counter()
    queue = []
    for note in notes:
        statuses[note["rating_status"]] += 1
        unknown = set(note["sensitivity_flags"]) - set(FLAGS)
        if not isinstance(note["sensitivity_flags"], list) or unknown:
            raise ValueError(
                f"{note['review_id']}: unknown sensitivity flags {unknown}"
            )
        try:
            check_second(note)
        except ValueError as error:
            raise ValueError(f"{note['review_id']}: {error}") from error
        if note["rating_status"] == "completed":
            raters[note["case_id"]].add(note["rater_id"])
            reasons = triggers(note)
            if reasons:
                second, decision = note["second_review"], note["adjudication"]
                queue.append(
                    {
                        "review_id": note["review_id"],
                        "case_id": note["case_id"],
                        "triggers": reasons,
                        "second_review": second["verdict"] if second else "missing",
                        "resolution": decision["status"] if decision else None,
                    }
                )
    split = sorted(case for case, names in raters.items() if len(names) > 1)
    per_rater = Counter(
        next(iter(names)) for names in raters.values() if len(names) == 1
    )
    awaiting = [q["review_id"] for q in queue if q["second_review"] == "missing"]
    unresolved = [
        q["review_id"]
        for q in queue
        if q["second_review"] in {"disagrees", "unsure"} and q["resolution"] is None
    ]
    report = {
        "task": "4.3",
        "sheet_sha256": sha256(sheet.read_bytes()),
        "rows": len(notes),
        "statuses": dict(statuses),
        "targets": len({n["case_id"] for n in notes}),
        "targets_by_primary_rater": dict(per_rater),
        "targets_split_across_raters": split,
        "sensitive_rows": queue,
        "awaiting_second_review": awaiting,
        "disagreements_without_resolution": unresolved,
        "ready": {
            "all_rows_completed": statuses.get("completed", 0) == len(lookup),
            "one_primary_rater_per_target": not split,
            "sensitive_rows_second_reviewed": not awaiting,
            "disagreements_resolved_or_marked_unresolved": not unresolved,
        },
    }
    return report, notes


def import_ratings(run: Path, sheet: Path, output: Path) -> tuple[dict, str]:
    report, notes = check(run, sheet)
    ready = report["ready"]
    if not ready["all_rows_completed"]:
        raise ValueError(f"review is incomplete: {report['statuses']}")
    if not ready["one_primary_rater_per_target"]:
        raise ValueError(
            f"targets split across raters: {report['targets_split_across_raters']}"
        )
    return report, write_jsonl(output, notes)


def page(run: Path, sheet: Path, output: Path, suggestions: Path | None = None) -> dict:
    """Write a self-contained offline page holding the masked sheet only."""
    lookup, cases, columns = run_inputs(run)
    rows = sheet_rows(sheet, columns)
    import_review(sheet, lookup, cases)
    proposed = {}
    if suggestions is not None:
        proposed = read(suggestions)
        if not isinstance(proposed, dict) or not set(proposed) <= set(lookup):
            raise ValueError("suggestions must map known review IDs to proposals")
        by_id = {row["review_id"]: row for row in rows}
        for rid, item in proposed.items():
            applicable = {
                axis
                for axis, used in loads(by_id[rid]["applicability_json"]).items()
                if used
            }
            if set(item) - {"scores", "reasons", "flags"}:
                raise ValueError(f"{rid}: unexpected suggestion fields")
            if set(item["scores"]) != applicable or set(item["reasons"]) != applicable:
                raise ValueError(
                    f"{rid}: suggestions must cover the applicable axes only"
                )
            if any(score not in (0, 1, 2) for score in item["scores"].values()):
                raise ValueError(f"{rid}: suggested scores must be 0, 1 or 2")
            if set(item.get("flags", [])) - set(FLAGS):
                raise ValueError(f"{rid}: unknown suggested flags")
    data = {
        "columns": columns,
        "rows": rows,
        "sheet_name": sheet.name,
        "sheet_sha256": sha256(sheet.read_bytes()),
        "flags": list(FLAGS),
        "suggestions": json.loads(json.dumps(proposed, default=str)),
    }
    text = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = PAGE.read_text(encoding="utf-8").replace("/*BOXBOX_DATA*/null", text, 1)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(html)
    return {"page": str(output), "rows": len(rows), "suggestions": len(proposed)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("page", "check", "import"):
        sub = commands.add_parser(command)
        sub.add_argument("--run-dir", required=True, type=Path)
        sub.add_argument("--sheet", required=True, type=Path)
        if command != "check":
            sub.add_argument("--output", required=True, type=Path)
        if command == "page":
            sub.add_argument("--suggestions", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "page":
            result = page(args.run_dir, args.sheet, args.output, args.suggestions)
        elif args.command == "check":
            result, _ = check(args.run_dir, args.sheet)
        else:
            report, digest = import_ratings(args.run_dir, args.sheet, args.output)
            result = {"ratings": report["rows"], "ratings_sha256": digest, **report}
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(f"error: {error}")
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
