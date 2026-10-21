"""OpenJev Flash 9B as a zero-shot baseline for the CALL line (task 3.4, exploratory).

Usage, from the repository root:
    python -m scripts.openjev_baseline run --split validation [--shuffle SEED]
    python -m scripts.openjev_baseline run --split mini_test
    python -m scripts.openjev_baseline threshold RUN
    python -m scripts.openjev_baseline score RUN [--tau-from VALIDATION_RUN]
    python -m scripts.openjev_baseline compare RUN [--shuffled SHUFFLED_RUN]

`run` hashes every pinned file again, starts the server from its own environment, answers
each target once, then stops the server and reads its peak memory. Nothing is retried,
and a failed request stays an error. The targets are the 100 validation targets of 2.5b
or the 40 mini-test targets of run r2, so every answer pairs with baseline, A and B.
`--shuffle` sends only the CALL question, with its options in another order per target.

`threshold` applies the rule declared on #35 to the validation run. `score` scores the
argmax and thresholded calls with the shared evaluator, and adds the calibration of the
CALL probabilities and the diagnostic questions. `compare` gives OpenJev minus baseline,
A and B over the race bootstrap and, with `--shuffled`, the calls that change with the
option order. The final split is never read.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import re
import signal
import socket
import statistics
import subprocess
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from boxbox.config import load_config
from boxbox.data import load_splits
from boxbox.evaluation import bootstrap_compare, observations, pair_outputs, summarize
from boxbox.evaluation._io import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    loads,
    read_jsonl,
    sha256,
    write_json,
    write_jsonl,
)
from boxbox.model.openjev import (
    CONFIG,
    OpenJevError,
    ask,
    build_request,
    endpoint,
    load_settings,
    policy_instructions,
    references,
    server_version,
)
from boxbox.runs import environment, finish_run, source_sha256
from scripts.mini_test import _outputs, git, verify_plan
from scripts.train_adapter import (
    ADAPTERS,
    SELECTION,
    baseline_source,
    selected_prompt,
    validation_cases,
)

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path("runs")
BASELINE_CONFIG = Path("configs/baseline-selected.toml")
MINI_TEST_RUN = RUNS / "2026-10-21_3-2-mini-test-r2"
ARGMAX, TAU = "openjev-argmax", "openjev-tau"
RULE = (
    "Answer BOX or STAY OUT only when that option is the most probable and its "
    "probability reaches tau, otherwise NO CALL. Tau has the highest CALL agreement on "
    "validation over the grid 0 to 1 by 0.01; ties go to fewer unjustified decisions, "
    "then to the lower tau (#35, declared before any result)."
)
GRID = [step / 100 for step in range(101)]
CURVE = (
    "call_agreement",
    "unjustified_decision_rate",
    "excessive_refusal_rate",
    "decision_coverage",
)
DIAGNOSTICS = ("in_scope", "required_known", "missing_field")
ECE_BINS = 10


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_pins(settings: dict) -> dict:
    """Every pinned file hashed again; a changed or missing file stops the run."""
    pins = {}
    for part in ("model", "helper"):
        root = Path(settings[part]["local_dir"])
        for name, expected in settings[part]["sha256"].items():
            if file_sha256(root / name) != expected:
                raise ValueError(f"{part} file {name} differs from its pinned hash")
        pins[part] = {
            "repo": settings[part]["repo"],
            "revision": settings[part]["revision"],
            "files_checked": len(settings[part]["sha256"]),
        }
    return pins


def targets(split: str) -> tuple[list[dict], str, dict]:
    """The targets baseline, A and B answered, with their hash and origin."""
    if split == "validation":
        cases, _ = validation_cases(load_config(BASELINE_CONFIG))  # checks the hash
        digest = loads(SELECTION.read_text())["cases_sha256"]
        return cases, digest, {"source": "2.5b validation targets"}
    plan, cases, _ = verify_plan(MINI_TEST_RUN)
    return (
        cases,
        plan["cases_sha256"],
        {"source": f"mini-test run {MINI_TEST_RUN.name}"},
    )


def check_version(version: dict, settings: dict) -> None:
    """The served helper and calibration must be the pinned ones."""
    readout, flags = settings["readout"], version.get("flags", {})
    expected = {
        "T": float(readout["READOUT_T"]),
        "noul_t": float(readout["READOUT_NOUL_T"]),
        "noul_bias": float(readout["READOUT_NOUL_BIAS"]),
        "shim_sha256": settings["helper"]["sha256"]["helper/shim.py"],
    }
    if (
        any(version.get(key) != value for key, value in expected.items())
        or flags.get("targeted") is not True
        or flags.get("perms") != int(readout["READOUT_PERMS"])
        or flags.get("instr_style") != readout["READOUT_INSTR_STYLE"]
    ):
        raise ValueError(
            f"the server is not the pinned helper and calibration: {version}"
        )


def peak_memory(log: str) -> dict[str, float | None]:
    """Peak memory footprint and resident set size from `/usr/bin/time -l`, in GB."""
    labels = {
        "peak_memory_gb": "peak memory footprint",
        "max_resident_gb": "maximum resident set size",
    }
    found = {key: re.search(rf"(\d+)\s+{label}", log) for key, label in labels.items()}
    return {k: round(int(m.group(1)) / 1e9, 2) if m else None for k, m in found.items()}


def wait_ready(base: str, process: subprocess.Popen, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "the OpenJev server stopped while starting; see server.log"
            )
        try:
            return server_version(base)
        except OpenJevError:
            time.sleep(1)
    raise TimeoutError(f"the OpenJev server was not ready after {timeout} s")


def stop(process: subprocess.Popen) -> None:
    """SIGTERM to the server under `time`, since a background job ignores SIGINT."""
    children = subprocess.run(
        ["pgrep", "-P", str(process.pid)], capture_output=True, text=True, check=False
    ).stdout.split()
    for pid in children:
        os.kill(int(pid), signal.SIGTERM)
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@contextmanager
def served(settings: dict, log_file: Path):
    """The pinned server, offline and on loopback; stopped and measured afterwards."""
    server = settings["server"]
    model, helper = settings["model"]["local_dir"], settings["helper"]["local_dir"]
    with socket.socket() as probe:
        if probe.connect_ex((server["host"], server["port"])) == 0:
            raise RuntimeError(f"port {server['port']} is already in use")
    environment_variables = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZER": model,
        "SHIM_MODEL": model,
        **settings["readout"],
    }
    command = [
        "/usr/bin/time",
        "-l",
        server["python"],
        "-I",
        f"{helper}/helper/shim_mlx.py",
        "--helper",
        f"{helper}/helper/shim.py",
        "--model",
        model,
        "--host",
        server["host"],
        "--port",
        str(server["port"]),
    ]
    with log_file.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, env=environment_variables, stdout=log, stderr=subprocess.STDOUT
        )
    record: dict[str, Any] = {}
    try:
        record["version"] = wait_ready(
            endpoint(settings), process, server["start_timeout_seconds"]
        )
        check_version(record["version"], settings)
        yield record
    finally:
        stop(process)
        record |= peak_memory(log_file.read_text(encoding="utf-8"))


def shuffled_order(options: list[str], case_id: str, seed: int) -> list[str]:
    """A fixed reordering of the CALL options for one target, never the original."""
    orders = [list(p) for p in itertools.permutations(options) if list(p) != options]
    return random.Random(f"{seed}:{case_id}").choice(orders)


def answer(base: str, case: dict, request: dict, timeout: float) -> dict:
    """One timed request; a failure is kept with its reason and never retried."""
    row = {
        "case_id": case["case_id"],
        "input_sha256": case["input_sha256"],
        "call_order": list(request["questions"]["call"]["criteria"]),
        "request_sha256": sha256(dumps(request)),
    }
    started = time.perf_counter()
    try:
        reply = ask(base, request, timeout)
        tokens = (reply.get("usage") or {}).get("input_tokens")
        row |= {"status": "ok", "answers": reply["answers"], "input_tokens": tokens}
        row["error"] = None
    except OpenJevError as error:
        row |= {"status": "request_error", "answers": None, "input_tokens": None}
        row["error"] = error.as_record()
    return row | {"seconds": round(time.perf_counter() - started, 3)}


def run_metrics(rows: list[dict], server: dict) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    seconds = [r["seconds"] for r in rows]
    return {
        "targets": len(rows),
        "answered": len(ok),
        "request_errors": len(rows) - len(ok),
        "seconds_per_target": {
            "mean": statistics.fmean(seconds),
            "median": statistics.median(seconds),
            "max": max(seconds),
        },
        "input_tokens_per_target": statistics.fmean(r["input_tokens"] for r in ok)
        if ok
        else None,
        "argmax_calls": Counter(r["answers"]["call"]["choice"] for r in ok),
        "server": server,
    }


def run(split: str, shuffle: int | None = None) -> Path:
    """Answer every target once, with the server started and stopped around the run."""
    settings = load_settings()
    policy = policy_instructions(selected_prompt())
    cases, cases_hash, origin = targets(split)
    for case in cases:
        references(case)  # an unmapped NO CALL reason stops here, before the server
    pins = verify_pins(settings)
    name = f"3-4-openjev-{split.replace('_', '-')}"
    name += "" if shuffle is None else f"-shuffle-s{shuffle}"
    folder = RUNS / f"{date.today().isoformat()}_{name}"
    folder.mkdir(parents=True)  # an existing run is never overwritten
    if write_jsonl(folder / "cases.jsonl", cases) != cases_hash:
        raise ValueError("the written case ledger differs from its source")
    (folder / "openjev.toml").write_bytes(CONFIG.read_bytes())
    manifest = {
        "task": "3.4",
        "split": split,
        "shuffle_seed": shuffle,
        "git_commit": git("rev-parse", "HEAD") or None,
        "git_dirty": bool(git("status", "--porcelain")),
        "source_sha256": source_sha256(),
        "split_manifest_sha256": sha256(Path("data/splits.json").read_bytes()),
        "openjev_config_sha256": sha256(CONFIG.read_bytes()),
        "pins": pins,
        "prompt_sha256": loads(SELECTION.read_text())["prompt_sha256"],
        "cases_sha256": cases_hash,
        "targets": origin | {"count": len(cases)},
        "environment": environment(),
        "started": time.time(),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    options, base = settings["questions"]["call"]["options"], endpoint(settings)
    rows = []
    with served(settings, folder / "server.log") as server:
        for case in cases:
            order = options
            if shuffle is not None:
                order = shuffled_order(options, case["case_id"], shuffle)
            inputs = loads(case["input_json"])
            request = build_request(settings, policy, inputs, order, shuffle is None)
            timeout = settings["server"]["request_timeout_seconds"]
            rows.append(answer(base, case, request, timeout))
            print(f"{len(rows)}/{len(cases)} {rows[-1]['status']}", flush=True)
    write_jsonl(folder / "answers.jsonl", rows)
    config = sha256((folder / "openjev.toml").read_bytes())
    argmax = outputs_at(rows, cases, None, folder.name, cases_hash, config)
    write_jsonl(folder / "outputs.jsonl", argmax)
    finish_run(folder, run_metrics(rows, server))
    print(f"answered {len(rows)} targets in {folder}")
    return folder


def decided(call: dict, tau: float | None) -> str:
    """The argmax call, or NO CALL when BOX or STAY OUT stays below tau."""
    choice = call["choice"]
    if (
        tau is None
        or choice == "NO CALL"
        or float(call["probabilities"][choice]) >= tau
    ):
        return choice
    return "NO CALL"


def outputs_at(
    rows: list[dict],
    cases: list[dict],
    tau: float | None,
    run_id: str,
    cases_hash: str,
    config: str,
) -> list[dict]:
    """Evaluator records of one rule (argmax or tau); a failed request stays an error."""
    version = ARGMAX if tau is None else TAU
    rule = sha256(dumps({"openjev_config": config, "tau": tau}))
    out = []
    for case, row in zip(cases, rows, strict=True):
        if row["case_id"] != case["case_id"]:
            raise ValueError("answers are not in case order")
        call = decided(row["answers"]["call"], tau) if row["status"] == "ok" else None
        out.append(
            {
                "response_id": f"{run_id}:{version}:{case['case_id']}",
                "case_id": case["case_id"],
                "version_id": version,
                "run_id": run_id,
                "config_sha256": rule,
                "protocol_id": PROTOCOL_ID,
                "protocol_version": PROTOCOL_VERSION,
                "cases_sha256": cases_hash,
                "input_sha256": case["input_sha256"],
                "status": "ok" if call else "generation_error",
                "raw_response": f"CALL: {call}" if call else None,
                "error": None if call else row["error"],
            }
        )
    return out


def load_run(run: Path) -> tuple[dict, list[dict], str, list[dict]]:
    manifest = json.loads((run / "manifest.json").read_text())
    cases, cases_hash = read_jsonl(run / "cases.jsonl")
    if cases_hash != manifest["cases_sha256"]:
        raise ValueError(f"{run}: the case ledger changed")
    return manifest, cases, cases_hash, read_jsonl(run / "answers.jsonl")[0]


def measures(cases: list[dict], rows: list[dict], cases_hash: str, splits) -> dict:
    """The evaluator's summary of one version's records."""
    version = rows[0]["version_id"]
    paired = pair_outputs(cases, rows, [version], cases_hash, splits)
    return summarize(observations(cases, paired)[version])


def choose_tau(curve: list[dict]) -> dict:
    """Highest CALL agreement; ties to fewer unjustified decisions, then the lower tau."""
    return max(
        curve,
        key=lambda p: (p["call_agreement"], -p["unjustified_decision_rate"], -p["tau"]),
    )


def threshold(run: Path) -> Path:
    """The declared rule on every tau of the grid, and the chosen tau."""
    manifest, cases, cases_hash, answers = load_run(run)
    if manifest["split"] != "validation" or manifest["shuffle_seed"] is not None:
        raise ValueError("tau is chosen on the unshuffled validation run only")
    splits, config = load_splits(), sha256((run / "openjev.toml").read_bytes())
    curve = []
    for tau in GRID:
        rows = outputs_at(answers, cases, tau, run.name, cases_hash, config)
        metrics = measures(cases, rows, cases_hash, splits)["metrics"]
        curve.append(
            {"tau": tau} | {m: metrics[f"overall/{m}"]["value"] for m in CURVE}
        )
    chosen = choose_tau(curve)
    out = run / "threshold.json"
    write_json(
        out, {"rule": RULE, "tau": chosen["tau"], "chosen": chosen, "curve": curve}
    )
    print(json.dumps(chosen, indent=2))
    return out


def tau_of(run: Path) -> float:
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["split"] != "validation" or manifest["shuffle_seed"] is not None:
        raise ValueError(f"{run} is not the unshuffled validation run that sets tau")
    return float(loads((run / "threshold.json").read_text())["tau"])


def probabilities(call: dict) -> dict[str, float]:
    return {label: float(p) for label, p in call["probabilities"].items()}


def calibration(answers: list[dict], cases: list[dict]) -> dict:
    """Multi-class Brier score and ECE over equal-width confidence bins (Guo et al.)."""
    truth = {c["case_id"]: c["reference"]["expected_call"] for c in cases}
    scored = [
        (probabilities(a["answers"]["call"]), a["answers"]["call"]["choice"], a)
        for a in answers
        if a["status"] == "ok"
    ]
    brier = statistics.fmean(
        sum((p - (label == truth[a["case_id"]])) ** 2 for label, p in probs.items())
        for probs, _, a in scored
    )
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(ECE_BINS)]
    for probs, choice, a in scored:
        index = min(int(probs[choice] * ECE_BINS), ECE_BINS - 1)
        bins[index].append((probs[choice], choice == truth[a["case_id"]]))
    table = [
        {
            "low": i / ECE_BINS,
            "high": (i + 1) / ECE_BINS,
            "count": len(b),
            "confidence": statistics.fmean(c for c, _ in b) if b else None,
            "accuracy": statistics.fmean(ok for _, ok in b) if b else None,
        }
        for i, b in enumerate(bins)
    ]
    ece = sum(
        row["count"] / len(scored) * abs(row["accuracy"] - row["confidence"])
        for row in table
        if row["count"]
    )
    return {
        "targets": len(scored),
        "excluded_errors": len(answers) - len(scored),
        "brier": brier,
        "ece": ece,
        "bins": table,
        "definitions": {
            "brier": "mean over targets of the squared distance between the three "
            "CALL probabilities and the one-hot reference call (0 best, 2 worst)",
            "ece": f"{ECE_BINS} equal-width bins of the argmax probability; weighted "
            "gap between mean confidence and argmax accuracy",
        },
    }


def said(answers: dict) -> dict:
    """The diagnostic answers as labels: yes when the yes probability reaches 0.5."""
    return {
        "in_scope": float(answers["in_scope"]["noul"]) >= 0.5,
        "required_known": float(answers["required_known"]["noul"]) >= 0.5,
        "missing_field": answers["missing_field"]["choice"],
    }


def diagnostics(answers: list[dict], cases: list[dict]) -> dict:
    """Accuracy of each diagnostic question by family, and what they say on wrong calls."""
    by_case = {c["case_id"]: c for c in cases}
    right = {q: Counter() for q in DIAGNOSTICS}
    asked = Counter()
    blocking = Counter()
    for a in answers:
        if a["status"] != "ok":
            continue
        case, labels = by_case[a["case_id"]], said(a["answers"])
        expected, family = references(case), case["primary_family"]
        asked[family] += 1
        for q in DIAGNOSTICS:
            right[q][family] += labels[q] == expected[q]
        if (
            case["attributes"]["card_state"] == "blocking_incomplete"
            and expected["call"] == "NO CALL"
            and a["answers"]["call"]["choice"] != "NO CALL"
        ):
            blocking["unjustified_calls"] += 1
            blocking["required_known_said_no"] += not labels["required_known"]
            blocking["missing_field_right"] += (
                labels["missing_field"] == expected["missing_field"]
            )
    return {
        "yes_threshold": 0.5,
        "answered": sum(asked.values()),
        "questions": {
            q: {
                "right": sum(right[q].values()),
                "by_family": {
                    f: {"right": right[q][f], "of": n} for f, n in asked.items()
                },
            }
            for q in DIAGNOSTICS
        },
        "unjustified_calls_on_blocking_cards": blocking,
    }


def score(run: Path, tau_from: Path | None = None) -> Path:
    """Evaluator measures at argmax and at tau, calibration and diagnostics."""
    manifest, cases, cases_hash, answers = load_run(run)
    if manifest["shuffle_seed"] is not None:
        raise ValueError("a shuffled run is only read by compare --shuffled")
    tau = tau_of(tau_from or run)
    config = sha256((run / "openjev.toml").read_bytes())
    tau_rows = outputs_at(answers, cases, tau, run.name, cases_hash, config)
    write_jsonl(run / "outputs-tau.jsonl", tau_rows)
    splits = load_splits()
    summaries = {
        ARGMAX: measures(
            cases, read_jsonl(run / "outputs.jsonl")[0], cases_hash, splits
        ),
        TAU: measures(cases, tau_rows, cases_hash, splits),
    }
    write_json(run / "summaries.json", summaries)
    write_json(run / "tau.json", {"tau": tau, "from_run": (tau_from or run).name})
    write_json(run / "calibration.json", calibration(answers, cases))
    write_json(run / "diagnostics.json", diagnostics(answers, cases))
    table = {
        v: {m: s["metrics"][f"overall/{m}"]["value"] for m in CURVE}
        for v, s in summaries.items()
    }
    print(json.dumps({"tau": tau, "measures": table}, indent=2))
    return run


def reference_outputs(split: str) -> dict[str, list[dict]]:
    """Baseline, A and B answers on the same targets, from their own run folders."""
    if split == "mini_test":
        outputs = _outputs(MINI_TEST_RUN)  # refuses changed generation files
        return {
            v: [o for o in outputs if o["version_id"] == v]
            for v in ("baseline", "A", "B")
        }
    found = {}
    for letter in ("A", "B"):
        selection = json.loads(ADAPTERS[letter]["selection"].read_text())
        rows, _ = read_jsonl(RUNS / selection["run"] / "validation-outputs.jsonl")
        found[letter] = [r for r in rows if r["version_id"] == selection["version"]]
    # A's summary records the 2.5b baseline it was compared with; B's does not.
    summary = json.loads(ADAPTERS["A"]["selection"].read_text())["summary"]
    origin = loads(Path(summary).read_text())["baseline"]
    rebuilt = not origin["same_bytes_as_2_5b"]
    baseline, _ = baseline_source(Path(origin["file"]), rebuilt)
    return {"baseline": baseline} | found


def flips(
    answers: list[dict], cases: list[dict], manifest: dict, shuffled: Path
) -> dict:
    """Calls that change when only the order of the CALL options changes."""
    other, _, other_hash, reordered = load_run(shuffled)
    if (
        other["shuffle_seed"] is None
        or other["split"] != manifest["split"]
        or other_hash != manifest["cases_sha256"]
    ):
        raise ValueError(f"{shuffled} is not a shuffled run on the same targets")
    family = {c["case_id"]: c["primary_family"] for c in cases}
    both = []
    for a, b in zip(answers, reordered, strict=True):
        if a["case_id"] != b["case_id"]:
            raise ValueError("the two runs list the targets in different orders")
        if a["status"] == b["status"] == "ok":
            both.append((a, b))
    changed = [
        a["case_id"]
        for a, b in both
        if a["answers"]["call"]["choice"] != b["answers"]["call"]["choice"]
    ]
    return {
        "shuffled_run": shuffled.name,
        "shuffle_seed": other["shuffle_seed"],
        "compared": len(both),
        "excluded_errors": len(answers) - len(both),
        "changed": len(changed),
        "share": len(changed) / len(both),
        "by_family": Counter(family[c] for c in changed),
        "changed_cases": changed,
    }


def compare(run: Path, shuffled: Path | None = None) -> Path:
    """OpenJev at argmax and at tau minus baseline, A and B, over whole-race draws."""
    manifest, cases, cases_hash, answers = load_run(run)
    ours = (
        read_jsonl(run / "outputs.jsonl")[0] + read_jsonl(run / "outputs-tau.jsonl")[0]
    )
    others = reference_outputs(manifest["split"])
    names = {name: rows[0]["version_id"] for name, rows in others.items()}
    theirs = [row for rows in others.values() for row in rows]
    versions = [*names.values(), ARGMAX, TAU]
    paired = pair_outputs(cases, theirs + ours, versions, cases_hash, load_splits())
    rows = observations(cases, paired)
    contrasts = {
        f"{mine} minus {name}": bootstrap_compare(rows, old, mine)
        for name, old in names.items()
        for mine in (ARGMAX, TAU)
    }
    result: dict[str, Any] = {"split": manifest["split"], "versions": names}
    if manifest["split"] == "validation":
        result["note"] = "tau was chosen on these targets, so its contrasts favour it"
    result["contrasts"] = contrasts
    if shuffled is not None:
        result["option_order"] = flips(answers, cases, manifest, shuffled)
    write_json(run / "compare.json", result)
    headline = {
        name: {
            m: [
                c["metrics"][f"overall/{m}"][k]
                for k in ("difference", "difference_interval")
            ]
            for m in CURVE[:3]
        }
        for name, c in contrasts.items()
    }
    print(json.dumps(headline, indent=2))
    return run / "compare.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run_args = commands.add_parser("run")
    run_args.add_argument("--split", choices=("validation", "mini_test"), required=True)
    run_args.add_argument("--shuffle", type=int, help="seed of the CALL option orders")
    commands.add_parser("threshold").add_argument("run", type=Path)
    score_args = commands.add_parser("score")
    score_args.add_argument("run", type=Path)
    score_args.add_argument(
        "--tau-from", type=Path, help="the validation run (mini-test)"
    )
    compare_args = commands.add_parser("compare")
    compare_args.add_argument("run", type=Path)
    compare_args.add_argument(
        "--shuffled", type=Path, help="the shuffled validation run"
    )
    args = parser.parse_args(argv)
    # configs/, runs/ and the comparison runs are relative to the repository root
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    if args.command == "run":
        if args.shuffle is not None and args.split != "validation":
            parser.error("--shuffle is for the validation run")
        run(args.split, args.shuffle)
    elif args.command == "threshold":
        threshold(args.run)
    elif args.command == "score":
        score(args.run, args.tau_from)
    else:
        compare(args.run, args.shuffled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
