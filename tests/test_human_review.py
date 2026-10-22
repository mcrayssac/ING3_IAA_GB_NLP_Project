"""4.3 review page, checks and import on synthetic cases and outputs only."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess

import pytest
from test_evaluation import cases, output, quota_cases  # noqa: F401 - synthetic fixtures

from boxbox.evaluation import pair_outputs, select_review_cases
from boxbox.evaluation._io import AXES, loads, read_jsonl, sha256, write_jsonl
from boxbox.evaluation.review import export_review
from scripts import human_review

STAMP = "2026-10-22T12:00:00+02:00"


@pytest.fixture
def run(tmp_path, cases):  # noqa: F811 - imported fixture
    full = quota_cases(cases)
    chosen = select_review_cases(full)["selected_case_ids"]
    versions = ["baseline", "A", "B"]
    outputs = [output(case, version) for case in full for version in versions]
    folder = tmp_path / "run"
    folder.mkdir()
    write_jsonl(folder / "cases.jsonl", full)
    export_review(
        folder / "review", full, pair_outputs(full, outputs, versions, "a" * 64), chosen
    )
    return folder


def rows(sheet):
    with sheet.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write(sheet, table):
    with sheet.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=table[0].keys())
        writer.writeheader()
        writer.writerows(table)


def complete(row, rater="synthetic-rater-a", factuality="2"):
    for axis in AXES:
        if loads(row["applicability_json"])[axis]:
            row[axis] = factuality if axis == "factuality" else "2"
            row[axis + "_reason"] = "Synthetic test reason."
    row.update(rating_status="completed", rater_id=rater, rated_at=STAMP)


def filled(run, tmp_path, **changes):
    table = rows(run / "review" / "review.csv")
    for row in table:
        complete(row)
    for rid, change in changes.items():
        change(next(r for r in table if r["review_id"] == rid))
    tmp_path.mkdir(parents=True, exist_ok=True)
    sheet = tmp_path / "rated.csv"
    write(sheet, table)
    return sheet


def test_pending_sheet_reports_progress_and_import_refuses(run, tmp_path):
    report, notes = human_review.check(run, run / "review" / "review.csv")
    assert (report["rows"], report["targets"], report["statuses"]) == (
        120,
        40,
        {"pending": 120},
    )
    assert not report["ready"]["all_rows_completed"] and len(notes) == 120
    with pytest.raises(ValueError, match="incomplete"):
        human_review.import_ratings(
            run, run / "review" / "review.csv", tmp_path / "out.jsonl"
        )
    assert not (tmp_path / "out.jsonl").exists()


def test_completed_sheet_imports_once(run, tmp_path):
    sheet = filled(run, tmp_path)
    report, digest = human_review.import_ratings(run, sheet, tmp_path / "ratings.jsonl")
    saved, saved_digest = read_jsonl(tmp_path / "ratings.jsonl")
    assert digest == saved_digest and len(saved) == 120
    assert all(r["rating_status"] == "completed" for r in saved)
    assert report["targets_by_primary_rater"] == {"synthetic-rater-a": 40}
    assert all(report["ready"].values())
    with pytest.raises(FileExistsError):
        human_review.import_ratings(run, sheet, tmp_path / "ratings.jsonl")


def test_versions_of_one_target_keep_one_primary_rater(run, tmp_path):
    table = rows(run / "review" / "review.csv")
    case = table[0]["case_id"]
    sheet = filled(
        run,
        tmp_path,
        **{
            next(
                r["review_id"]
                for r in table
                if r["case_id"] == case and r is not table[0]
            ): (lambda row: row.update(rater_id="synthetic-rater-b"))
        },
    )
    report, _ = human_review.check(run, sheet)
    assert report["targets_split_across_raters"] == [case]
    with pytest.raises(ValueError, match="split"):
        human_review.import_ratings(run, sheet, tmp_path / "ratings.jsonl")


def test_altered_response_is_named(run, tmp_path):
    sheet = filled(
        run, tmp_path, R00007=lambda row: row.update(raw_response="CALL: BOX")
    )
    with pytest.raises(
        ValueError, match="R00007: review inputs/raw output were altered"
    ):
        human_review.check(run, sheet)


def test_sensitive_rows_need_another_reviewer_and_a_resolution(run, tmp_path):
    second = {
        "reviewer_id": "synthetic-rater-b",
        "reviewed_at": STAMP,
        "verdict": "disagrees",
        "scores": {"factuality": 0},
        "notes": "Synthetic second note.",
    }

    def flagged(row):
        complete(row, factuality="1")
        row["second_review_json"] = json.dumps(second)

    sheet = filled(
        run, tmp_path, R00001=flagged, R00002=lambda row: complete(row, factuality="0")
    )
    report, _ = human_review.check(run, sheet)
    assert report["awaiting_second_review"] == ["R00002"]
    assert report["disagreements_without_resolution"] == ["R00001"]
    assert not report["ready"]["sensitive_rows_second_reviewed"]

    def own(row):
        flagged(row)
        row["second_review_json"] = json.dumps(
            {**second, "reviewer_id": row["rater_id"]}
        )

    with pytest.raises(
        ValueError, match="R00001: second review must come from another"
    ):
        human_review.check(run, filled(run, tmp_path / "own", R00001=own))

    def resolved(row, people):
        flagged(row)
        row["adjudication_json"] = json.dumps(
            {
                "participants": people,
                "decided_at": STAMP,
                "status": "resolved",
                "decision": "Keep the primary score.",
                "reason": "Synthetic reason.",
            }
        )

    for folder, people in (
        ("none", []),
        ("ok", ["synthetic-rater-a", "synthetic-rater-b"]),
    ):
        sheet = filled(
            run, tmp_path / folder, R00001=lambda row, p=people: resolved(row, p)
        )
        if not people:
            with pytest.raises(ValueError, match="participants"):
                human_review.check(run, sheet)
        else:
            report, _ = human_review.check(run, sheet)
            assert report["disagreements_without_resolution"] == []


def test_unknown_flags_are_refused(run, tmp_path):
    sheet = filled(
        run, tmp_path, R00003=lambda row: row.update(sensitivity_flags='["guess"]')
    )
    with pytest.raises(ValueError, match="unknown sensitivity flags"):
        human_review.check(run, sheet)


def test_page_holds_masked_sheet_and_valid_suggestions(run, tmp_path):
    sheet = run / "review" / "review.csv"
    table = rows(sheet)
    target = next(r for r in table if not loads(r["applicability_json"])["scope"])
    applicable = [a for a, used in loads(target["applicability_json"]).items() if used]
    proposal = {
        target["review_id"]: {
            "scores": dict.fromkeys(applicable, 1),
            "reasons": dict.fromkeys(applicable, "Proposal."),
            "flags": [],
        }
    }
    (tmp_path / "suggest.json").write_text(json.dumps(proposal))
    result = human_review.page(
        run, sheet, tmp_path / "page.html", tmp_path / "suggest.json"
    )
    assert (result["rows"], result["suggestions"]) == (120, 1)
    html = (tmp_path / "page.html").read_text(encoding="utf-8")
    data = json.loads(
        re.search(r'id="boxbox-data"[^>]*>(.*?)</script>', html, re.DOTALL).group(1)
    )
    assert data["rows"] == table and data["sheet_sha256"] == sha256(sheet.read_bytes())
    lookup = loads((run / "review" / "response-lookup.json").read_text())
    assert not any(
        link["response_id"] in html or link["run_id"] in html
        for link in lookup.values()
    )
    with pytest.raises(FileExistsError):
        human_review.page(run, sheet, tmp_path / "page.html")
    proposal[target["review_id"]]["scores"]["scope"] = 2
    (tmp_path / "bad.json").write_text(json.dumps(proposal))
    with pytest.raises(ValueError, match="applicable axes"):
        human_review.page(run, sheet, tmp_path / "bad.html", tmp_path / "bad.json")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_csv_round_trip_is_byte_identical(run, tmp_path):
    sheet = filled(
        run,
        tmp_path,
        R00005=lambda row: row.update(raw_response='CALL: BOX\r\nWHY: "a, b"\n'),
    )
    core = re.search(
        r'<script id="boxbox-core">(.*?)</script>',
        human_review.PAGE.read_text(encoding="utf-8"),
        re.DOTALL,
    ).group(1)
    script = tmp_path / "round.js"
    script.write_text(
        core
        + """
const fs = require("fs"), R = globalThis.BoxBoxReview;
const text = fs.readFileSync(process.argv[2], "utf8"), columns = R.parseCSV(text)[0];
const rows = R.records(columns, text);
fs.writeFileSync(process.argv[3], R.toCSV(columns, rows));
const altered = rows.map(r => ({ ...r })); altered[0].message = "changed";
try { R.merge(rows, altered); console.log("merged"); } catch (e) { console.log(e.message); }
"""
    )
    done = subprocess.run(
        ["node", str(script), str(sheet), str(tmp_path / "again.csv")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "altered" in done.stdout
    assert (tmp_path / "again.csv").read_bytes() == sheet.read_bytes()


def test_cli_reports_errors_without_traceback(run, tmp_path, capsys):
    code = human_review.main(
        ["check", "--run-dir", str(run), "--sheet", str(tmp_path / "missing.csv")]
    )
    assert code == 1 and capsys.readouterr().out.startswith("error:")
