"""Agreement of OpenJev with policy 2.0 on 2.0 cards, measured before the Replay shows it.

Usage, from the repository root:
    python -m scripts.replay_model_check sample [--per-cell N]
    python -m scripts.replay_model_check run [--per-cell N] [--tag TAG]
    python -m scripts.replay_model_check score RUN [--write]

One prompt, declared before any call (`boxbox.model.policy2_prompt`), and one question
asked in three orders and averaged (`configs/openjev-replay.toml`). The sample takes, in
`validation` and `mini_test` of `data/splits-v2.json` only, up to N cards per cell, a
cell being the policy 2.0 call by the track condition (green, SC, VSC, wet), in the
order of a SHA-256 of the card id. `final` and `test_2026` stay closed. `score` chooses
tau on the validation rows with the rule of #35, applies it to `mini_test` once, and
reports the agreement as it is, with no pass mark. The reference is the rule's call: it
shows consistency with policy 2.0, not the best real strategy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from boxbox.config import RunConfig
from boxbox.data.splits import SPLITS_V2_FILE, load_cards
from boxbox.evaluation._io import (
    dumps,
    loads,
    read_jsonl,
    sha256,
    write_json,
    write_jsonl,
)
from boxbox.model.openjev import (
    REPLAY_CONFIG,
    build_request,
    endpoint,
    load_settings,
    model_card,
    replay_message,
)
from boxbox.model.policy2_prompt import policy2_instructions
from boxbox.rules import decide
from boxbox.runs import environment, finish_run, source_sha256
from scripts.mini_test import git
from scripts.openjev_baseline import (
    GRID,
    RULE,
    answer,
    choose_tau,
    decided,
    served,
    verify_pins,
)

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path("runs")
CARDS_V2 = Path("data/cards-v2")
RESULT = Path("data/reference/replay-model-check.json")
SPLITS = ("validation", "mini_test")
PER_CELL = 25
CALLS = ("BOX", "STAY OUT", "NO CALL")


def condition(card: dict[str, Any]) -> str:
    """The track condition of a card: SC, VSC, else WET on a wet surface, else GREEN."""
    if card.get("track_status") in ("SC", "VSC"):
        return card["track_status"]
    return "WET" if card.get("surface") == "WET" else "GREEN"


def rank(card_id: str) -> str:
    return hashlib.sha256(f"boxbox-replay|check|{card_id}".encode()).hexdigest()


def pick(records: list[dict[str, Any]], per_cell: int) -> list[dict[str, Any]]:
    """Up to `per_cell` cards of each (policy 2.0 call, condition) cell, by hash order."""
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        card = model_card(
            record["card"]
        )  # a NaN reads as null, for the rule and the model
        cells[(decide(card)[0], condition(card))].append(record | {"card": card})
    return [
        record
        for key in sorted(cells)
        for record in sorted(cells[key], key=lambda r: rank(r["card_id"]))[:per_cell]
    ]


def sample(per_cell: int = PER_CELL) -> list[dict[str, Any]]:
    """The check sample: one row per card, with the rule's call as its reference."""
    rows = []
    for (
        split
    ) in SPLITS:  # load_cards refuses a closed split, so none is read by mistake
        records = load_cards(split, RunConfig(), CARDS_V2, SPLITS_V2_FILE)
        for record in pick(records, per_cell):
            card = record["card"]
            reference, _ = decide(card)
            rows.append(
                {
                    "card_id": record["card_id"],
                    "split": split,
                    "cell": f"{reference}|{condition(card)}",
                    "reference": reference,
                    "card": card,
                }
            )
    return rows


def run(per_cell: int = PER_CELL, tag: str = "") -> Path:
    """Ask every sampled card once, with the server started and stopped around the run."""
    settings = load_settings(REPLAY_CONFIG)
    policy = policy2_instructions()
    pins = verify_pins(settings)
    rows = sample(per_cell)
    name = "replay-model-check" + (f"-{tag}" if tag else "")
    folder = RUNS / f"{date.today().isoformat()}_{name}"
    folder.mkdir(parents=True)  # an existing run is never overwritten
    sample_sha = write_jsonl(folder / "sample.jsonl", rows)
    (folder / "openjev-replay.toml").write_bytes(REPLAY_CONFIG.read_bytes())
    manifest = {
        "task": "4bis.4",
        "git_commit": git("rev-parse", "HEAD") or None,
        "git_dirty": bool(git("status", "--porcelain")),
        "source_sha256": source_sha256(),
        "config_sha256": sha256(REPLAY_CONFIG.read_bytes()),
        "prompt_sha256": sha256(policy),
        "sample_sha256": sample_sha,
        "per_cell": per_cell,
        "cards": len(rows),
        "pins": pins,
        "environment": environment(),
        "started": time.time(),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    base = endpoint(settings)
    timeout = settings["server"]["request_timeout_seconds"]
    answers = []
    with served(settings, folder / "server.log") as server:
        for row in rows:
            card = row["card"]
            inputs = {
                "card": card,
                "history": [],
                "message": replay_message(card["lap"], card["driver_number"]),
            }
            request = build_request(settings, policy, inputs, diagnostics=False)
            case = {"case_id": row["card_id"], "input_sha256": sha256(dumps(inputs))}
            reply = answer(base, case, request, timeout)
            answers.append(
                reply | {"split": row["split"], "reference": row["reference"]}
            )
            print(f"{len(answers)}/{len(rows)} {reply['status']}", flush=True)
    write_jsonl(folder / "answers.jsonl", answers)
    seconds = [a["seconds"] for a in answers]
    finish_run(
        folder,
        {
            "answered": sum(a["status"] == "ok" for a in answers),
            "request_errors": sum(a["status"] != "ok" for a in answers),
            "seconds_per_card": {
                "mean": statistics.fmean(seconds),
                "median": statistics.median(seconds),
                "max": max(seconds),
            },
            "server": server,
        },
    )
    print(f"answered {len(answers)} cards in {folder}")
    return folder


def predicted(row: dict[str, Any], tau: float | None) -> str | None:
    """The call at tau, or None for a request that failed (it counts as a miss)."""
    return decided(row["answers"]["call"], tau) if row["status"] == "ok" else None


def curve(rows: list[dict[str, Any]]) -> list[dict[str, float]]:
    """CALL agreement and unjustified decisions on every tau of the grid."""
    points = []
    for tau in GRID:
        calls = [predicted(r, tau) for r in rows]
        no_call = [c for c, r in zip(calls, rows) if r["reference"] == "NO CALL"]
        points.append(
            {
                "tau": tau,
                "call_agreement": sum(c == r["reference"] for c, r in zip(calls, rows))
                / len(rows),
                "unjustified_decision_rate": sum(c in CALLS[:2] for c in no_call)
                / max(len(no_call), 1),
            }
        )
    return points


def summary(rows: list[dict[str, Any]], tau: float | None) -> dict[str, Any]:
    """Agreement at tau on one split: overall, per reference call, per cell, confusion."""
    calls = [predicted(r, tau) for r in rows]
    by_cell: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    confusion: dict[str, Counter] = defaultdict(Counter)
    for call, row in zip(calls, rows):
        by_cell[row["cell"]][1] += 1
        by_cell[row["cell"]][0] += call == row["reference"]
        confusion[row["reference"]][call or "ERROR"] += 1
    recalls = [
        confusion[ref][ref] / sum(confusion[ref].values())
        for ref in CALLS
        if confusion[ref]
    ]
    return {
        "cards": len(rows),
        "agreed": sum(c == r["reference"] for c, r in zip(calls, rows)),
        "macro_label_agreement": statistics.fmean(recalls),
        "request_errors": sum(r["status"] != "ok" for r in rows),
        "by_cell": dict(sorted(by_cell.items())),
        "confusion": {ref: dict(counts) for ref, counts in sorted(confusion.items())},
    }


def score(run_dir: Path, write: bool = False) -> Path:
    """Choose tau on the validation rows, apply it once to mini_test, write the summary."""
    answers, _ = read_jsonl(run_dir / "answers.jsonl")
    manifest = loads((run_dir / "manifest.json").read_text())
    by_split = {s: [a for a in answers if a["split"] == s] for s in SPLITS}
    cell = {c["card_id"]: c["cell"] for c in read_jsonl(run_dir / "sample.jsonl")[0]}
    for rows in by_split.values():
        for row in rows:
            row["cell"] = cell[row["case_id"]]
    points = curve(by_split["validation"])
    tau = choose_tau(points)["tau"]
    result = {
        "run": run_dir.name,
        "rule": RULE,
        "tau": tau,
        "prompt_sha256": manifest["prompt_sha256"],
        "sample_sha256": manifest["sample_sha256"],
        "per_cell": manifest["per_cell"],
        "at_tau": {s: summary(rows, tau) for s, rows in by_split.items()},
        "most_probable": {s: summary(rows, None) for s, rows in by_split.items()},
        "curve": points,
    }
    out = run_dir / "score.json"
    write_json(out, result)
    if write:
        kept = {
            "run": run_dir.name,
            "tau": tau,
            "prompt_sha256": result["prompt_sha256"],
            "sample_sha256": result["sample_sha256"],
            "per_cell": result["per_cell"],
            "note": (
                "Agreement with the call of policy 2.0 at tau, on a sample by call and "
                "condition, not on race laps. Tau was chosen on validation."
            ),
            "agreement": {
                s: [result["at_tau"][s]["agreed"], result["at_tau"][s]["cards"]]
                for s in SPLITS
            },
        }
        write_json(RESULT, kept)
    print(json.dumps({k: result[k] for k in ("tau", "at_tau")}, indent=2, default=str))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sample").add_argument("--per-cell", type=int, default=PER_CELL)
    ran = commands.add_parser("run")
    ran.add_argument("--per-cell", type=int, default=PER_CELL)
    ran.add_argument(
        "--tag", default="", help="a suffix for the run folder, for a trial"
    )
    scored = commands.add_parser("score")
    scored.add_argument("run_dir", type=Path)
    scored.add_argument("--write", action="store_true", help=f"also write {RESULT}")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    if args.command == "sample":
        rows = sample(args.per_cell)
        print(json.dumps(Counter(f"{r['split']} {r['cell']}" for r in rows), indent=2))
    elif args.command == "run":
        run(args.per_cell, args.tag)
    else:
        score(args.run_dir, args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
