"""Offline scoring, metadata-only review selection, and a synthetic worked run."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import platform
import subprocess
import sys
import time
from pathlib import Path

from boxbox.config import RunConfig, load_config
from boxbox.runs import config_toml, source_sha256

from ._io import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    loads,
    read_jsonl,
    sha256,
    write_json,
    write_jsonl,
)
from .metrics import observations, summarize, validate_rating
from .parsing import parse_response
from .records import PairingError, pair_outputs, prepare_case, validate_cases
from .review import SamplingError, export_review, select_review_cases
from .statistics import bootstrap_compare


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"cannot record Git provenance: {result.stderr.strip()}")
    return result.stdout.strip()


def _gate(args: argparse.Namespace, config: RunConfig) -> None:
    if args.split == "final" and not (
        config.final_test_open and args.freeze_record and args.acceptance_record
    ):
        raise ValueError(
            "final_split_closed: require final_test_open plus actual freeze and acceptance references"
        )


def _check_normative_files(args: argparse.Namespace) -> None:
    protocol = Path(args.protocol).read_text(encoding="utf-8")
    fixture = loads(Path(args.fixtures).read_text(encoding="utf-8"))
    if (
        f"**version:** {chr(96)}{PROTOCOL_VERSION}{chr(96)}" not in protocol
        or fixture["protocol"]["id"] != PROTOCOL_ID
        or fixture["protocol"]["version"] != PROTOCOL_VERSION
    ):
        raise ValueError("unsupported protocol/fixture version")
    policy = Path(__file__).resolve().parents[1] / "rules/decision.py"
    if fixture["revision"]["policy_source_sha256"] != sha256(policy.read_bytes()):
        raise ValueError("fixture policy source pin mismatch")


def _split_membership(args: argparse.Namespace) -> dict | None:
    if args.split == "synthetic":
        return None
    if not args.split_manifest:
        raise ValueError("real splits require the accepted --split-manifest")
    # Only real-data integration needs the existing loader and its project environment.
    from boxbox.data import load_splits

    return load_splits(Path(args.split_manifest))


def calibration_checks(fixture: dict) -> tuple[list[dict], dict]:
    if fixture["protocol"] != {
        "id": PROTOCOL_ID,
        "version": PROTOCOL_VERSION,
        "status": "proposed",
    }:
        raise ValueError("unsupported calibration protocol/status")
    cards = {row["card_id"]: row["card"] for row in fixture["cards"]}
    cases = [prepare_case(row, cards[row["card_id"]]) for row in fixture["cases"]]
    index = validate_cases(cases)
    responses = set()
    for row in fixture["responses"]:
        rid = row["fixture_response_id"]
        if rid in responses:
            raise ValueError("duplicate calibration response")
        responses.add(rid)
        parsed = parse_response(row["raw_response"], row["status"])
        expected = row["expected"]
        if parsed != {key: expected[key] for key in parsed}:
            raise ValueError(f"calibration parser mismatch: {rid}")
        case = index[row["case_id"]]
        validate_rating(
            {
                "rating_status": "synthetic_expected",
                "annotation_kind": "synthetic_expected",
                "rater_id": None,
                "rated_at": None,
                "applicability": case["applicability"],
                "scores": expected["scores"],
                "reasons": expected["reasons"],
            },
            case,
            allow_synthetic=True,
        )
    return cases, {
        "annotation_kind": "synthetic_expected",
        "cards": len(cards),
        "cases": len(cases),
        "responses": len(responses),
        "checks": [
            "policy_references",
            "structural_parser",
            "score_ranges_and_applicability",
        ],
        "limitation": "Expected semantic scores are validated as annotations, not automatically judged.",
    }


def _manifest(
    args: argparse.Namespace,
    config: RunConfig,
    folder: Path,
    *,
    cases_hash: str | None,
    outputs_hash: str | None,
    versions: list[str],
    sampling_hash: str | None = None,
    illustrative: bool = False,
) -> dict:
    root = Path(__file__).resolve().parents[2]
    protocol = Path(args.protocol).read_bytes()
    fixture = Path(args.fixtures).read_bytes()
    for name, data in (
        ("evaluation-protocol.md", protocol),
        ("evaluation-fixtures.json", fixture),
    ):
        with (folder / name).open("xb") as stream:
            stream.write(data)
    config_bytes = config_toml(config).encode("utf-8")
    with (folder / "config.toml").open("xb") as stream:
        stream.write(config_bytes)
    packages = {}
    for name in ("pytest", "ruff"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    evaluation = {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": sha256(protocol),
        "fixtures_sha256": sha256(fixture),
        "protocol_status": "proposed"
        if b"proposed for review" in protocol
        else "see_snapshot",
        "acceptance_record": args.acceptance_record or None,
        "policy_git_commit": _git("rev-parse", "HEAD"),
        "policy_source_sha256": sha256(
            (root / "boxbox/rules/decision.py").read_bytes()
        ),
        "cases_sha256": cases_hash,
        "input_ledger_sha256": cases_hash,
        "outputs_sha256": outputs_hash,
        "config_sha256": sha256(config_bytes),
        "input_ledger_file": "cases.jsonl",
        "data_manifest_sha256": sha256(Path(args.split_manifest).read_bytes())
        if args.split_manifest
        else None,
        "sampling_manifest_sha256": sampling_hash,
        "history_mode": "fixed_supplied",
        "retained_versions": versions,
        "freeze_record": args.freeze_record or None,
        "drop_b_record": getattr(args, "drop_b_record", None),
        "split": args.split,
        "illustrative": illustrative,
        "not_applicable": ["real_data_manifest"] if args.split == "synthetic" else [],
        "bootstrap": {
            "seed": 2026,
            "replications": 10000,
            "confidence_level": 0.95,
            "method": "paired_whole_race_percentile",
            "quantiles": "linear_type_7",
        },
    }
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "source_sha256": source_sha256(root),
        "command": sys.argv,
        "started": args.started,
        "duration_seconds": round(time.time() - args.started, 6),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "test_tools": packages,
        },
        "model_executed": False,
        "extra": {"evaluation": evaluation},
    }


def _results(
    folder: Path, observed: dict, contrasts: list[tuple[str, str]], human: bool
) -> None:
    write_json(
        folder / "metrics.json",
        {v: summarize(rows, human) for v, rows in observed.items()},
    )
    comparisons = [bootstrap_compare(observed, old, new) for old, new in contrasts]
    if human:
        for old, new in contrasts:
            reviewed = bootstrap_compare(observed, old, new, human=True)
            reviewed["metrics"] = {
                key: metric
                for key, metric in reviewed["metrics"].items()
                if key.rsplit("/", 1)[-1].startswith("human_")
                or key.rsplit("/", 1)[-1]
                in {"why_supported_rate", "justified_abstention_review_rate"}
            }
            comparisons.append(reviewed)
    for comparison in comparisons:
        pair = (comparison["old"], comparison["new"])
        comparison["contrast_role"] = (
            "principal"
            if pair in {("baseline", "A"), ("A", "B")}
            else "exploratory_or_synthetic"
        )
    write_json(folder / "comparisons.json", comparisons)
    with (folder / "paired.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "old",
                "new",
                "analysis_population",
                "metric",
                "old_numerator",
                "old_denominator",
                "old_value",
                "new_numerator",
                "new_denominator",
                "new_value",
                "new_minus_old",
                "gain",
                "difference_interval",
                "interval_status",
                "valid_replications",
            ]
        )
        for contrast in comparisons:
            for name, row in contrast["metrics"].items():
                writer.writerow(
                    [
                        contrast["old"],
                        contrast["new"],
                        contrast["analysis_population"],
                        name,
                        dumps(row["old"]["numerator"]),
                        row["old"]["denominator"],
                        row["old"]["value"],
                        dumps(row["new"]["numerator"]),
                        row["new"]["denominator"],
                        row["new"]["value"],
                        row["difference"],
                        row["gain"],
                        dumps(row["difference_interval"]),
                        row["interval_status"],
                        row["valid_replications"],
                    ]
                )


def run_fixtures(args: argparse.Namespace, config: RunConfig) -> None:
    if args.split != "synthetic":
        raise ValueError("fixtures command only accepts split=synthetic")
    fixture = loads(Path(args.fixtures).read_text(encoding="utf-8"))
    policy = Path(__file__).resolve().parents[1] / "rules/decision.py"
    if sha256(policy.read_bytes()) != fixture["revision"]["policy_source_sha256"]:
        raise ValueError("fixture policy source pin mismatch")
    cases, checks = calibration_checks(fixture)
    index = {case["case_id"]: case for case in cases}
    toy = fixture["paired_example"]
    toy_cases = [index[row["case_id"]] for row in toy["rows"]]
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    cases_hash = write_jsonl(folder / "cases.jsonl", toy_cases)
    config_hash = sha256(config_toml(config))
    outputs = []
    for row in toy["rows"]:
        for version in toy["versions"]:
            supplied = row[version]
            label = supplied["extracted_call"]
            outputs.append(
                {
                    "response_id": f"syn:output:{version}:{row['case_id']}",
                    "case_id": row["case_id"],
                    "version_id": version,
                    "run_id": "syn:run:worked-example",
                    "cases_sha256": cases_hash,
                    "config_sha256": config_hash,
                    "protocol_id": PROTOCOL_ID,
                    "protocol_version": PROTOCOL_VERSION,
                    "input_sha256": index[row["case_id"]]["input_sha256"],
                    "status": supplied["status"],
                    "raw_response": f"CALL: {label}\nWHY: This is a synthetic label-only example."
                    if label is not None
                    else None,
                    "error": {
                        "code": "synthetic_error",
                        "message": "Illustrative generation failure.",
                    }
                    if supplied["status"] != "ok"
                    else None,
                }
            )
    outputs_hash = write_jsonl(folder / "outputs.jsonl", outputs)
    paired = pair_outputs(toy_cases, outputs, toy["versions"], cases_hash)
    observed = observations(toy_cases, paired)
    _results(folder, observed, [tuple(toy["versions"])], False)
    write_json(folder / "calibration-checks.json", checks)
    sampling = select_review_cases(fixture["quota_witness"]["cases"])
    write_json(folder / "quota-witness-selection.json", sampling)
    export_review(
        folder / "review",
        toy_cases,
        paired,
        list(paired[toy["versions"][0]]),
        illustrative=True,
    )
    manifest = _manifest(
        args,
        config,
        folder,
        cases_hash=cases_hash,
        outputs_hash=outputs_hash,
        versions=toy["versions"],
        illustrative=True,
    )
    manifest["extra"]["evaluation"]["construction_note"] = (
        "The toy supplies CALL classifications only. Raw strings here are declared synthetic "
        "wrappers for the CLI example; their format metrics are not observations from the toy. "
        "The review sheet is a six-target/twelve-response excerpt. The separate 40-target "
        "quota witness contains metadata only, not complete final cases."
    )
    write_json(folder / "manifest.json", manifest)
    print(
        f"Synthetic fixture checks passed: {checks['cases']} targets, {checks['responses']} annotations."
    )
    print(
        f"Saved paired table, 10000-draw intervals and illustrative review excerpt to {folder}"
    )


def _load_cases(
    args: argparse.Namespace, config: RunConfig
) -> tuple[list[dict], str, dict | None]:
    _gate(
        args, config
    )  # Before any case/output reads, including nonexistent input paths.
    cases, cases_hash = read_jsonl(args.cases)
    if any(case.get("split") != args.split for case in cases):
        raise ValueError("case-ledger split does not match the declared split")
    if type(config.history_turns) is not int or config.history_turns < 0:
        raise ValueError("invalid common history_turns")
    for case in cases:
        full = case.get("full_history", case["history"])
        bounded = full[-2 * config.history_turns :] if config.history_turns else []
        if bounded != case["history"]:
            raise ValueError(
                "saved inputs disagree with the declared common history bound"
            )
    membership = _split_membership(args)
    validate_cases(cases, membership)
    return cases, cases_hash, membership


def _copy_pinned(source: str, target: Path, expected: str) -> None:
    data = Path(source).read_bytes()
    if sha256(data) != expected:
        raise ValueError(f"ledger changed during evaluation: {source}")
    with target.open("xb") as stream:
        stream.write(data)


def run_sample(args: argparse.Namespace, config: RunConfig) -> None:
    cases, cases_hash, _ = _load_cases(args, config)
    sampling = select_review_cases(cases)
    sampling["cases_sha256"] = cases_hash
    sampling.pop("sampling_manifest_sha256")
    sampling["sampling_manifest_sha256"] = sha256(dumps(sampling))
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    _copy_pinned(args.cases, folder / "cases.jsonl", cases_hash)
    write_json(folder / "selection.json", sampling)
    manifest = _manifest(
        args,
        config,
        folder,
        cases_hash=cases_hash,
        outputs_hash=None,
        versions=[],
        sampling_hash=sampling["sampling_manifest_sha256"],
    )
    write_json(folder / "manifest.json", manifest)
    print(
        f"Selected the same 40 target IDs for all retained versions: {folder / 'selection.json'}"
    )


def run_score(args: argparse.Namespace, config: RunConfig) -> None:
    cases, cases_hash, membership = _load_cases(args, config)
    outputs, outputs_hash = read_jsonl(args.outputs)
    paired = pair_outputs(cases, outputs, args.versions, cases_hash, membership)
    selection, selected = None, None
    if args.selection:
        selection = loads(Path(args.selection).read_text(encoding="utf-8"))
        stated = selection["sampling_manifest_sha256"]
        if (
            sha256(
                dumps(
                    {
                        k: v
                        for k, v in selection.items()
                        if k != "sampling_manifest_sha256"
                    }
                )
            )
            != stated
        ):
            raise ValueError("sampling manifest hash mismatch")
        expected = select_review_cases(cases)
        if (
            selection.get("cases_sha256") != cases_hash
            or selection["selected_in_slot_order"] != expected["selected_in_slot_order"]
            or selection["candidate_metadata_sha256"]
            != expected["candidate_metadata_sha256"]
        ):
            raise ValueError("sampling manifest does not match the common case ledger")
        selected = selection["selected_case_ids"]
    ratings, ratings_hash = read_jsonl(args.ratings) if args.ratings else (None, None)
    observed = observations(
        cases, paired, ratings, selected, rating_phase=args.rating_phase
    )
    contrasts = (
        [tuple(pair) for pair in args.contrast]
        if args.contrast
        else [
            pair
            for pair in (("baseline", "A"), ("A", "B"))
            if all(version in paired for version in pair)
        ]
    )
    if not contrasts and len(paired) > 1:
        contrasts = [(args.versions[0], args.versions[1])]
    if any(old not in paired or new not in paired for old, new in contrasts):
        raise ValueError("unknown contrast version")
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    _copy_pinned(args.cases, folder / "cases.jsonl", cases_hash)
    _copy_pinned(args.outputs, folder / "outputs.jsonl", outputs_hash)
    if args.ratings:
        _copy_pinned(args.ratings, folder / "ratings.jsonl", ratings_hash)
    if selection is not None:
        write_json(folder / "selection.json", selection)
    _results(folder, observed, contrasts, ratings is not None)
    if selected is not None:
        export_review(
            folder / "review",
            cases,
            paired,
            selected,
            ratings,
            drop_b_record=args.drop_b_record,
            rating_phase=args.rating_phase,
        )
    manifest = _manifest(
        args,
        config,
        folder,
        cases_hash=cases_hash,
        outputs_hash=outputs_hash,
        versions=args.versions,
        sampling_hash=selection["sampling_manifest_sha256"] if selection else None,
    )
    manifest["extra"]["evaluation"]["rating_phase"] = args.rating_phase
    manifest["extra"]["evaluation"]["version_runs"] = {
        version: {
            "run_id": next(iter(rows.values()))["run_id"],
            "config_sha256": next(iter(rows.values()))["config_sha256"],
        }
        if rows
        else None
        for version, rows in paired.items()
    }
    manifest["extra"]["evaluation"]["ratings_sha256"] = (
        sha256((folder / "ratings.jsonl").read_bytes()) if args.ratings else None
    )
    write_json(folder / "manifest.json", manifest)
    print(f"Scored {len(cases)} paired targets for {len(paired)} version(s): {folder}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("fixtures", "sample", "score"):
        command = commands.add_parser(name)
        command.add_argument(
            "--output", required=True, help="new output directory; never overwritten"
        )
        command.add_argument("--protocol", default="docs/evaluation-protocol.md")
        command.add_argument("--fixtures", default="reference/evaluation-fixtures.json")
        command.add_argument("--config", help="existing RunConfig TOML")
        command.add_argument(
            "--split",
            choices=["synthetic", "validation", "mini_test", "final"],
            default="synthetic",
        )
        command.add_argument("--split-manifest")
        command.add_argument("--freeze-record")
        command.add_argument("--acceptance-record")
        if name != "fixtures":
            command.add_argument("--cases", required=True)
        if name == "score":
            command.add_argument("--outputs", required=True)
            command.add_argument("--versions", nargs="+", required=True)
            command.add_argument("--contrast", nargs=2, action="append", default=[])
            command.add_argument(
                "--selection", help="40-target manifest selected before model outputs"
            )
            command.add_argument(
                "--ratings", help="supplied rating rows, not synthetic expectations"
            )
            command.add_argument(
                "--drop-b-record",
                help="actual B-drop decision required for the 80-response review",
            )
            command.add_argument(
                "--rating-phase", choices=["initial", "adjudicated"], default="initial"
            )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.started = time.time()
    try:
        config = load_config(args.config) if args.config else RunConfig()
        _gate(args, config)
        _check_normative_files(args)
        {"fixtures": run_fixtures, "sample": run_sample, "score": run_score}[
            args.command
        ](args, config)
    except (ValueError, KeyError, TypeError, OSError, ImportError) as error:
        diagnostic = {"status": "pipeline_error", "message": str(error)}
        if isinstance(error, PairingError):
            diagnostic["defective_pairs"] = error.errors
        if isinstance(error, SamplingError):
            diagnostic["sampling_diagnostics"] = error.diagnostics
        print(dumps(diagnostic), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
