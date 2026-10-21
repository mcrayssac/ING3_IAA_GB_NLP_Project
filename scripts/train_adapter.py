"""Train adapter A (task 2.6) or B (task 3.2) over several seeds, choose checkpoints on
validation, summarise.

Usage, from the repository root:
    python -m scripts.train_adapter smoke [--adapter B]
    python -m scripts.train_adapter train [--adapter B] --seed 2026
    python -m scripts.train_adapter seeds [--adapter B]
    python -m scripts.train_adapter validate runs/<date>_2-6-adapter-a-s2026
    python -m scripts.train_adapter summarize RUN_DIR [RUN_DIR ...] [--baseline OUTPUTS [--rebuilt]]
        [--against-a SUMMARY_A]
    python -m scripts.train_adapter curves RUN_DIR [RUN_DIR ...] [--out PNG]
    python -m scripts.train_adapter push SUMMARY --repo ORG/NAME

A and B share every setting except their corpus (configs/adapter-a.toml and
configs/adapter-b.toml). The commands after train read the adapter from the run's own
config.toml.

Training and validation use the inference prompt chosen in task 2.5b
(configs/baseline-selection.json), so the adapter learns from the exact tokens it sees
in use. `validate` runs in a fresh process, which is the reload check. The final split
is never read.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from boxbox.config import load_config
from boxbox.evaluation import (
    adapt_validation,
    bootstrap_compare,
    observations,
    pair_outputs,
    select_prompt,
    summarize,
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
from boxbox.runs import finish_run, start_run

ROOT = Path(__file__).resolve().parents[1]
SELECTION = Path("configs/baseline-selection.json")
# Per adapter: its task, its settings, its corpus, the file that records the selected
# checkpoint for later tasks, and the Hub model card.
ADAPTERS = {
    "A": {
        "task": "2.6",
        "config": Path("configs/adapter-a.toml"),
        "corpus": "A_train",
        "selection": Path("configs/adapter-a-selection.json"),
        "card": Path("docs/adapter-a-card.md"),
    },
    "B": {
        "task": "3.2",
        "config": Path("configs/adapter-b.toml"),
        "corpus": "B_train",
        "selection": Path("configs/adapter-b-selection.json"),
        "card": Path("docs/adapter-b-card.md"),
    },
}
SEEDS = (2026, 2027, 2028)
METRICS = (
    "overall/strict_format_rate",
    "overall/call_agreement",
    "overall/unjustified_decision_rate",
    "overall/excessive_refusal_rate",
    "overall/macro_label_agreement",
    "overall/macro_family_agreement",
)
T_95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776}  # two-sided 95% Student t by run count
SMOKE_STEPS = 10
SMOKE_GENERATIONS = 3
BUDGET_HOURS = 5.0  # above this for all seeds, the gate stops before training
# Update-end reads miss the peak inside an update: the batch-4 run read 0.89 of the cap.
MEMORY_SHARE = 0.85


def task_slug(letter: str) -> str:
    """The adapter's task as it appears in run names, such as 3-2."""
    return ADAPTERS[letter]["task"].replace(".", "-")


def run_name(letter: str, suffix: str) -> str:
    """A run or summary name such as 3-2-adapter-b-s2026, from the adapter's task."""
    return f"{task_slug(letter)}-adapter-{letter.lower()}-{suffix}"


def seed_of(run: str) -> int:
    """The seed in a run name such as 2026-10-19_2-6-adapter-a-s2028."""
    return int(run.rsplit("-s", 1)[1])


def selected_prompt() -> str:
    """The 2.5b inference prompt, checked against the hash it was selected with."""
    selection = loads(SELECTION.read_text())
    text = Path(selection["prompt_file"]).read_bytes()
    if sha256(text) != selection["prompt_sha256"]:
        raise ValueError("the selected prompt changed since task 2.5b")
    return text.decode("utf-8")


def load_engine(config) -> tuple[Any, Any]:
    """The base model on the configured device, wrapped in the inference engine."""
    from boxbox.model import (
        ConversationEngine,
        cap_mps_memory,
        get_device,
        load_model,
        model_dtype,
    )

    device = get_device()
    if device.type == "mps":
        cap_mps_memory(config.mps_memory_cap_gb)
    model, tokenizer = load_model(config, device)
    engine = ConversationEngine(
        model,
        tokenizer,
        config,
        instructions=selected_prompt(),
        device=device,
        dtype=model_dtype(device),
    )
    return engine, device


def validation_cases(config) -> tuple[list[dict], dict]:
    """The 100 validation targets of task 2.5b, refused if their hash differs."""
    from boxbox.data import load_splits

    splits = load_splits()
    items, _ = read_jsonl(Path("data/corpus/validation.jsonl"))
    records = []
    for race in splits["splits"]["validation"]:
        records.extend(read_jsonl(Path("data/cards") / f"{race}.jsonl")[0])
    cases = adapt_validation(items, records, splits, config.history_turns)
    if (
        sha256("".join(dumps(case) + "\n" for case in cases))
        != loads(SELECTION.read_text())["cases_sha256"]
    ):
        raise ValueError("validation cases differ from the 2.5b baseline cases")
    return cases, splits


def training_rows(engine, config) -> tuple[list[dict], list[dict]]:
    """The adapter's corpus rows for training, and validation rows for the epoch loss."""
    from boxbox.corpus import load_corpus
    from boxbox.training import build_rows

    limit = config.lora.max_length
    train = build_rows(engine, load_corpus(ADAPTERS[config.adapter]["corpus"]), limit)
    return train, build_rows(engine, load_corpus("validation"), limit)


def generate(
    engine, cases, cases_hash, run_id, version, identity
) -> tuple[list[dict], list[dict]]:
    """One answer per validation target, kept raw with its trace, never retried (2.5b)."""
    from boxbox.model import ConversationEngineError

    rows, attempts = [], []
    for case in cases:
        try:
            raw, trace = engine.respond_with_trace(
                **loads(case["input_json"]),
                fixed_history=True,
                required_history_turns=int(case["attributes"]["history_sensitive"]),
            )
            error = None
        except ConversationEngineError as failure:
            raw, trace, error = (
                failure.partial_response,
                failure.trace,
                failure.as_record(),
            )
        rows.append(
            {
                "response_id": f"{run_id}:{version}:{case['case_id']}",
                "case_id": case["case_id"],
                "version_id": version,
                "run_id": run_id,
                "config_sha256": identity,
                "protocol_id": PROTOCOL_ID,
                "protocol_version": PROTOCOL_VERSION,
                "cases_sha256": cases_hash,
                "input_sha256": case["input_sha256"],
                "status": "generation_error" if error else "ok",
                "raw_response": raw,
                "error": error,
            }
        )
        attempts.append(
            {
                "response_id": rows[-1]["response_id"],
                "case_id": case["case_id"],
                "version_id": version,
                "input_sha256": case["input_sha256"],
                "trace": trace,
            }
        )
    return rows, attempts


def planned_updates(config, rows: int) -> int:
    lora = config.lora
    return (
        math.ceil(rows / (lora.batch_size * lora.gradient_accumulation)) * lora.epochs
    )


def train(seed: int, letter: str = "A") -> Path:
    """Train one seed and keep a checkpoint per epoch with its validation loss."""
    from boxbox.training import train_lora

    config = replace(load_config(ADAPTERS[letter]["config"]), seed=seed)
    engine, device = load_engine(config)
    rows, eval_rows = training_rows(engine, config)
    extra = {
        "task": ADAPTERS[letter]["task"],
        "prompt_sha256": loads(SELECTION.read_text())["prompt_sha256"],
        "train_rows": len(rows),
        "eval_rows": len(eval_rows),
        "planned_updates": planned_updates(config, len(rows)),
    }
    run = start_run(
        run_name(letter, f"s{seed}"), config, str(device), engine.dtype, extra=extra
    )
    loaded = (engine.model, engine.tokenizer)
    metrics = train_lora(config, rows, run, device, eval_rows, loaded=loaded)
    losses = metrics["train_losses"] + [e["eval_loss"] for e in metrics["eval_losses"]]
    metrics["finite_losses"] = all(math.isfinite(value) for value in losses)
    metrics["planned_updates"] = extra["planned_updates"]
    finish_run(run, metrics)
    print(f"trained {run}: {metrics['steps']} updates")
    return run


def all_seeds(letter: str = "A") -> dict[int, str]:
    """Train then validate every seed, each step in a fresh process; status per seed.

    A failed seed is logged and the next one still runs, so one stall does not cost
    the others. Each seed's output goes to runs/<task>-logs/seed-<seed>.log.
    """
    import subprocess
    import sys

    logs = Path("runs") / f"{task_slug(letter)}-logs"
    logs.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "scripts.train_adapter"]
    statuses = {}
    for seed in SEEDS:
        with (logs / f"seed-{seed}.log").open("a", encoding="utf-8") as log:

            def step(*args: str) -> bool:
                done = subprocess.run(
                    [*command, *args], check=False, stdout=log, stderr=log
                )
                return done.returncode == 0

            status = "train failed"
            if step("train", "--adapter", letter, "--seed", str(seed)):
                folder = max(Path("runs").glob(f"*_{run_name(letter, f's{seed}')}"))
                status = "ok" if step("validate", str(folder)) else "validate failed"
        statuses[seed] = status
        line = f"{datetime.now():%Y-%m-%d %H:%M} seed {seed}: {status}"
        print(line, flush=True)
        with (logs / "status.txt").open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    return statuses


def smoke(letter: str = "A") -> int:
    """Time a few generations and 10 updates, then project the 3-seed budget."""
    from boxbox.training import train_lora

    config = load_config(ADAPTERS[letter]["config"])
    engine, device = load_engine(config)
    cases, _ = validation_cases(config)
    started = time.perf_counter()
    for case in cases[:SMOKE_GENERATIONS]:
        engine.respond_with_trace(**loads(case["input_json"]), fixed_history=True)
    generation = (time.perf_counter() - started) / SMOKE_GENERATIONS
    rows, _ = training_rows(engine, config)
    short = replace(config, lora=replace(config.lora, max_steps=SMOKE_STEPS))
    needed = SMOKE_STEPS * config.lora.batch_size * config.lora.gradient_accumulation
    longest = sorted(rows, key=lambda row: len(row["input_ids"]), reverse=True)
    run = start_run(f"{task_slug(letter)}-smoke", short, str(device), engine.dtype)
    metrics = train_lora(
        short, longest[:needed], run, device, loaded=(engine.model, engine.tokenizer)
    )
    updates = planned_updates(config, len(rows))
    per_seed = metrics["seconds_per_step"] * updates + generation * len(cases) * 3
    metrics |= {
        "seconds_per_generation": round(generation, 2),
        "planned_updates_per_seed": updates,
        "projected_hours_all_seeds": round(per_seed * len(SEEDS) / 3600, 2),
    }
    limit = MEMORY_SHARE * config.mps_memory_cap_gb
    over_memory = metrics["max_memory_gb_at_step_end"] > limit
    metrics["gate"] = (
        "stop"
        if over_memory or metrics["projected_hours_all_seeds"] > BUDGET_HOURS
        else "go"
    )
    finish_run(run, metrics)
    print(
        json.dumps({k: v for k, v in metrics.items() if k != "train_losses"}, indent=2)
    )
    return 0 if metrics["gate"] == "go" else 2


def validate(run: Path) -> Path:
    """Reload every checkpoint in this fresh process, answer validation, choose one."""
    import torch
    from peft import PeftModel

    from boxbox.model import ConversationEngine
    from boxbox.training.reload import compare_reference

    config = load_config(run / "config.toml")
    metrics = loads((run / "metrics.json").read_text())
    engine, device = load_engine(config)
    cases, splits = validation_cases(config)
    cases_hash = write_jsonl(run / "validation-cases.jsonl", cases)
    model, outputs, attempts, versions, reloads = None, [], [], [], {}
    for checkpoint in metrics["checkpoints"]:
        version = f"{config.adapter}-s{config.seed}-e{checkpoint['epoch']}"
        folder = run / checkpoint["folder"]
        if model is None:
            model = PeftModel.from_pretrained(
                engine.model, folder, adapter_name=version
            )
            model = model.to(device).eval()
        else:
            model.load_adapter(folder, adapter_name=version)
        model.set_adapter(version)
        reference = torch.load(folder / "reference.pt")
        reloads[version] = compare_reference(model, reference, device)
        adapter = sha256((folder / "adapter_model.safetensors").read_bytes())
        identity = sha256(
            dumps(
                {
                    "config": sha256((run / "config.toml").read_bytes()),
                    "adapter": adapter,
                }
            )
        )
        adapted = ConversationEngine(
            model,
            engine.tokenizer,
            config,
            instructions=engine.instructions,
            device=device,
            dtype=engine.dtype,
        )
        answers, traces = generate(
            adapted, cases, cases_hash, run.name, version, identity
        )
        outputs, attempts = outputs + answers, attempts + traces
        versions.append(version)
        print(f"answered validation with {version}", flush=True)
    write_jsonl(run / "validation-outputs.jsonl", outputs)
    write_jsonl(run / "validation-attempts.jsonl", attempts)
    return _choose(run, cases, outputs, versions, cases_hash, splits, reloads)


def _choose(run, cases, outputs, versions, cases_hash, splits, reloads) -> Path:
    """Score the checkpoints with the evaluator and pick one in the 2.3a order."""
    paired = pair_outputs(cases, outputs, versions, cases_hash, splits)
    rows = observations(cases, paired)
    summaries = {v: summarize(rows[v]) for v in versions}
    selection = select_prompt(summaries, versions)
    selection["reload"] = reloads
    selection["reload_ok"] = all(
        r["same_argmax_as_training"] and r["max_prob_diff_vs_training"] < 1e-3
        for r in reloads.values()
    )
    (run / "validation-summaries.json").write_text(dumps(summaries) + "\n")
    (run / "selection.json").write_text(dumps(selection) + "\n")
    print(
        f"selected {selection['selected_candidate']}, reload ok: {selection['reload_ok']}"
    )
    return run


def seed_interval(values: list[float]) -> dict[str, Any]:
    """Mean, standard deviation and a 95% t-interval over training seeds."""
    if any(value is None for value in values) or len(values) not in T_95:
        return {"values": values, "mean": None, "sd": None, "low": None, "high": None}
    values = [float(value) for value in values]  # run files are read back as Decimal
    mean, sd = statistics.fmean(values), statistics.stdev(values)
    half = T_95[len(values)] * sd / math.sqrt(len(values))
    return {
        "values": values,
        "mean": mean,
        "sd": sd,
        "low": mean - half,
        "high": mean + half,
    }


def cut_answers(attempts_file: Path, version: str) -> int | None:
    """Answers of one version stopped by the token limit, when traces were kept."""
    if not attempts_file.exists():
        return None
    return sum(
        a["trace"].get("possibly_truncated") is True
        for a in read_jsonl(attempts_file)[0]
        if a["version_id"] == version
    )


def prompt_hashes(attempts_file: Path, version: str) -> dict[str, str]:
    """Prompt-token hash of every case one version answered."""
    return {
        a["case_id"]: a["trace"].get("prompt_token_ids_sha256")
        for a in read_jsonl(attempts_file)[0]
        if a["version_id"] == version
    }


def _seed_result(run: Path) -> dict[str, Any]:
    selection = loads((run / "selection.json").read_text())
    summaries = loads((run / "validation-summaries.json").read_text())
    version = selection["selected_candidate"]
    return {
        "run": run.name,
        "version": version,
        "summary": summaries[version],
        "metrics": {m: summaries[version]["metrics"][m]["value"] for m in METRICS},
        "cut_at_limit": cut_answers(run / "validation-attempts.jsonl", version),
    }


def against_baseline(run: Path, version: str, baseline: list[dict]) -> dict:
    """Race-cluster bootstrap of this seed's selected checkpoint minus the baseline."""
    cases, cases_hash = read_jsonl(run / "validation-cases.jsonl")
    from boxbox.data import load_splits

    mine = [
        r
        for r in read_jsonl(run / "validation-outputs.jsonl")[0]
        if r["version_id"] == version
    ]
    old = baseline[0]["version_id"]
    paired = pair_outputs(
        cases, baseline + mine, [old, version], cases_hash, load_splits()
    )
    return bootstrap_compare(observations(cases, paired), old, version)


def check_rebuilt_baseline(records: list[dict], run: Path) -> None:
    """Accept a re-run of the 2.5b baseline only with its prompt, cases and measures."""
    selection = loads(SELECTION.read_text())
    chosen, cases = selection["selected_candidate"], selection["cases_sha256"]
    lock = loads((run / "selected" / "inference-lock.json").read_text())
    measures = loads((run / "selection.json").read_text())["exact_values"][chosen]
    ledger, ledger_hash = read_jsonl(run / "outputs.jsonl")
    checks = {
        "ledger": ledger_hash == lock["outputs_sha256"]
        and [r for r in ledger if r["version_id"] == chosen] == records,
        "selected prompt": lock["selected_candidate"] == chosen
        and lock["prompt_sha256"] == selection["prompt_sha256"],
        "cases": lock["cases_sha256"] == cases,
        "answers": len(records) == selection["baseline_output_count"]
        and all(
            r["version_id"] == chosen and r["cases_sha256"] == cases for r in records
        ),
        "measures": measures == selection["selection"]["exact_values"][chosen],
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError(f"rebuilt baseline differs from 2.5b: {', '.join(failed)}")


def baseline_source(baseline_file: Path, rebuilt: bool) -> tuple[list[dict], dict]:
    """The baseline answers and their origin, refused unless they are the 2.5b ones."""
    baseline, digest = read_jsonl(baseline_file)
    same = digest == loads(SELECTION.read_text())["baseline_outputs_sha256"]
    run = baseline_file.parent.parent
    if not same:
        if not rebuilt:
            raise ValueError(
                "baseline outputs differ from 2.5b; a re-run needs --rebuilt"
            )
        check_rebuilt_baseline(baseline, run)
    return baseline, {
        "file": str(baseline_file),
        "sha256": digest,
        "run": baseline[0]["run_id"],
        "same_bytes_as_2_5b": same,
        "cut_at_limit": cut_answers(run / "attempts.jsonl", baseline[0]["version_id"]),
    }


def same_prompts(
    mine_file: Path, version: str, theirs_file: Path, old: str
) -> dict | None:
    """How many validation prompts two versions saw token for token, from their traces."""
    if not (theirs_file.exists() and mine_file.exists()):
        return None
    theirs, mine = prompt_hashes(theirs_file, old), prompt_hashes(mine_file, version)
    same = sum(h is not None and theirs.get(c) == h for c, h in mine.items())
    return {"compared": len(mine), "same": same}


def median_version(seeds: list[dict]) -> tuple[dict, str]:
    """Rank the seeds' selected checkpoints in the 2.3a order and take the middle one."""
    versions = [s["version"] for s in seeds]
    ranking = select_prompt({s["version"]: s["summary"] for s in seeds}, versions)
    return ranking, ranking["ranked_candidate_ids"][len(seeds) // 2]


def paired_differences(mine: list[dict], theirs: list[dict]) -> dict[str, dict]:
    """Per metric, the seed-by-seed differences mine minus theirs and their t-interval."""
    return {
        m: seed_interval(
            [
                None if a[m] is None or b[m] is None else float(a[m]) - float(b[m])
                for a, b in zip(mine, theirs)
            ]
        )
        for m in METRICS
    }


def epoch_metrics(run: Path) -> dict[int, dict]:
    """The principal metrics of every validated checkpoint of a run, by epoch."""
    summaries = loads((run / "validation-summaries.json").read_text())
    return {
        int(version.rsplit("-e", 1)[1]): {
            m: summary["metrics"][m]["value"] for m in METRICS
        }
        for version, summary in summaries.items()
    }


def equal_updates(runs: list[Path], a_runs: list[Path]) -> dict[str, dict]:
    """B minus A at the same epoch, so at the same update count, seed by seed."""
    mine = [epoch_metrics(run) for run in runs]
    theirs = [epoch_metrics(run) for run in a_runs]
    epochs = sorted(mine[0])
    if any(sorted(e) != epochs for e in mine + theirs):
        raise ValueError("A and B runs must have validated the same epochs")
    return {
        f"epoch {k}": paired_differences([m[k] for m in mine], [t[k] for t in theirs])
        for k in epochs
    }


def against_a(runs: list[Path], seeds: list[dict], a_summary: Path) -> dict:
    """B minus A for each seed on the same validation targets, then over the seeds."""
    summary = loads(a_summary.read_text())
    if "adapter_a" not in summary:
        raise ValueError(f"{a_summary} is not a summary of adapter A")
    a_seeds = {seed_of(s["run"]): s for s in summary["seeds"]}
    b_seeds = [seed_of(r.name) for r in runs]
    if len(set(b_seeds)) != len(b_seeds):
        raise ValueError(f"one B run per seed is needed, got seeds {b_seeds}")
    missing = [seed for seed in b_seeds if seed not in a_seeds]
    if missing:
        raise ValueError(f"{a_summary} has no A run for seeds {missing}")
    per_seed, theirs = {}, []
    for s, run in zip(seeds, runs):
        a = a_seeds[seed_of(run.name)]
        a_run = a_summary.parent / a["run"]
        a_answers = [
            r
            for r in read_jsonl(a_run / "validation-outputs.jsonl")[0]
            if r["version_id"] == a["version"]
        ]
        per_seed[s["version"]] = {
            "against": a["version"],
            "bootstrap": against_baseline(run, s["version"], a_answers),
            "same_prompts": same_prompts(
                run / "validation-attempts.jsonl",
                s["version"],
                a_run / "validation-attempts.jsonl",
                a["version"],
            ),
        }
        theirs.append(a["metrics"])
    differences = paired_differences([s["metrics"] for s in seeds], theirs)
    a_runs = [a_summary.parent / a_seeds[seed_of(r.name)]["run"] for r in runs]
    return {
        "summary_a": str(a_summary),
        "per_seed": per_seed,
        "over_seeds": differences,
        "equal_updates": equal_updates(runs, a_runs),
    }


def summarise(
    runs: list[Path],
    baseline_file: Path | None,
    rebuilt: bool = False,
    a_summary: Path | None = None,
) -> Path:
    """Seed means and intervals, comparisons per seed, and the median seed as the adapter."""
    letters = {load_config(run / "config.toml").adapter for run in runs}
    if len(letters) != 1:
        raise ValueError(f"the runs mix adapters {sorted(letters)}")
    letter = letters.pop()
    if a_summary is not None and letter != "B":
        raise ValueError(f"--against-a compares B runs with A, not {letter} runs")
    name = run_name(letter, "summary")
    out = runs[0].parent / f"{date.today().isoformat()}_{name}.json"
    if out.exists():
        raise FileExistsError(f"{out} exists; a summary is never overwritten")
    seeds = [_seed_result(run) for run in runs]
    stats = {m: seed_interval([s["metrics"][m] for s in seeds]) for m in METRICS}
    ranking, median = median_version(seeds)
    chosen = runs[[s["version"] for s in seeds].index(median)]
    source, bootstraps, prompts = "pending: no baseline outputs given", {}, {}
    if baseline_file is not None:
        baseline, source = baseline_source(baseline_file, rebuilt)
        old = baseline[0]["version_id"]
        for s, r in zip(seeds, runs):
            bootstraps[s["version"]] = against_baseline(r, s["version"], baseline)
            prompts[s["version"]] = same_prompts(
                r / "validation-attempts.jsonl",
                s["version"],
                baseline_file.parent.parent / "attempts.jsonl",
                old,
            )
    result = {
        "seeds": [{k: v for k, v in s.items() if k != "summary"} for s in seeds],
        "seed_intervals": stats,
        "interval_note": "95% Student t over training seeds; wide with this few runs",
        "ranking": ranking,
        f"adapter_{letter.lower()}": {"run": chosen.name, "version": median},
        "baseline": source,
        "same_prompts_as_baseline": prompts or None,
        "against_baseline": bootstraps or "pending: no baseline outputs given",
    }
    if a_summary is not None:
        result["against_a"] = against_a(runs, seeds, a_summary)
    out.write_text(dumps(result) + "\n")
    write_selection(chosen, median, out, letter)
    print(f"adapter {letter} is {median} from {chosen.name}; summary in {out}")
    return out


def checkpoint_folder(run: Path, version: str) -> tuple[dict, Path]:
    """The saved checkpoint of a version such as A-s2028-e1, with its metrics entry."""
    epoch = int(version.rsplit("-e", 1)[1])
    checkpoints = loads((run / "metrics.json").read_text())["checkpoints"]
    checkpoint = next(c for c in checkpoints if c["epoch"] == epoch)
    return checkpoint, run / checkpoint["folder"]


def write_selection(run: Path, version: str, summary: Path, letter: str = "A") -> Path:
    """Record the selected adapter for later tasks; its Hub copy is kept if unchanged."""
    checkpoint, folder = checkpoint_folder(run, version)
    lock = loads(SELECTION.read_text())
    adapter = sha256((folder / "adapter_model.safetensors").read_bytes())
    config, file = ADAPTERS[letter]["config"], ADAPTERS[letter]["selection"]
    old = json.loads(file.read_text()) if file.exists() else {}
    selection = {
        "task": ADAPTERS[letter]["task"],
        "adapter": letter,
        "run": run.name,
        "version": version,
        "seed": load_config(run / "config.toml").seed,
        "epoch": checkpoint["epoch"],
        "step": checkpoint["step"],
        "checkpoint": checkpoint["folder"],
        "adapter_sha256": adapter,
        "config_file": str(config),
        "config_sha256": sha256(config.read_bytes()),
        "prompt_file": lock["prompt_file"],
        "prompt_sha256": lock["prompt_sha256"],
        "cases_sha256": lock["cases_sha256"],
        "summary": str(summary),
        "hub": old.get("hub") if old.get("adapter_sha256") == adapter else None,
    }
    file.write_text(json.dumps(selection, indent=2) + "\n")
    return file


def hub_token() -> str | None:
    """HF_TOKEN from the environment, else from the local .env file, which Git ignores."""
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    env = Path(".env")
    lines = env.read_text().splitlines() if env.exists() else []
    keys = (line.split("=", 1) for line in lines if line.startswith("HF_TOKEN="))
    return next((value.strip() for _, value in keys), None)


def push(summary_file: Path, repo: str) -> dict:
    """Upload the selected checkpoints, the summary and the card, then record the revision."""
    from huggingface_hub import CommitOperationAdd, HfApi

    summary = loads(summary_file.read_text())
    letter = summary["seeds"][0]["version"].split("-")[0]
    file = ADAPTERS[letter]["selection"]
    selection = json.loads(file.read_text())
    if summary[f"adapter_{letter.lower()}"]["version"] != selection["version"]:
        raise ValueError(f"{summary_file} and {file} name different adapters")
    ops = [
        CommitOperationAdd("README.md", str(ADAPTERS[letter]["card"])),
        CommitOperationAdd("summary.json", str(summary_file)),
    ]
    for seed in summary["seeds"]:
        _, folder = checkpoint_folder(
            summary_file.parent / seed["run"], seed["version"]
        )
        for name in ("adapter_config.json", "adapter_model.safetensors"):
            target = f"{seed['version'].removeprefix(f'{letter}-')}/{name}"
            ops.append(CommitOperationAdd(target, str(folder / name)))
    api = HfApi(token=hub_token())
    api.create_repo(repo, private=True, exist_ok=True)
    task = ADAPTERS[letter]["task"]
    message = f"Adapter {letter}, three seeds (task {task})"
    commit = api.create_commit(repo, ops, commit_message=message)
    hub = {
        "repo": repo,
        "revision": commit.oid,
        "folder": selection["version"].removeprefix(f"{letter}-"),
    }
    files = api.model_info(repo, revision=commit.oid, files_metadata=True).siblings
    remote = {f.rfilename: f.lfs.sha256 for f in files if f.lfs}
    if (
        remote.get(f"{hub['folder']}/adapter_model.safetensors")
        != selection["adapter_sha256"]
    ):
        raise ValueError(f"the Hub copy of adapter {letter} has a different hash")
    selection["hub"] = hub
    file.write_text(json.dumps(selection, indent=2) + "\n")
    print(f"pushed {repo}@{commit.oid}")
    return hub


def plot_losses(runs: list[Path], out: Path | None = None) -> Path:
    """Training loss per update and validation loss per epoch, one colour per seed."""
    import matplotlib

    letter = load_config(runs[0] / "config.toml").adapter.lower()
    out = out or Path(f"docs/diagrams/adapter-{letter}-losses.png")

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for run in runs:
        metrics = loads((run / "metrics.json").read_text())
        chosen = loads((run / "selection.json").read_text())["selected_candidate"]
        seed = run.name.rsplit("-s", 1)[1]
        losses = [float(x) for x in metrics["train_losses"]]
        smooth = [
            statistics.fmean(losses[max(0, i - 9) : i + 1]) for i in range(len(losses))
        ]
        steps = range(1, len(losses) + 1)
        (line,) = left.plot(steps, smooth, label=f"seed {seed}")
        left.plot(steps, losses, color=line.get_color(), alpha=0.2, linewidth=0.8)
        epochs = [int(e["epoch"]) for e in metrics["eval_losses"]]
        evals = [float(e["eval_loss"]) for e in metrics["eval_losses"]]
        right.plot(
            epochs, evals, marker="o", color=line.get_color(), label=f"seed {seed}"
        )
        best = int(chosen.rsplit("-e", 1)[1])
        right.scatter(
            [best],
            [evals[epochs.index(best)]],
            s=160,
            facecolors="none",
            edgecolors=line.get_color(),
            linewidths=2,
        )
    for step in (120, 240):
        left.axvline(step, color="grey", linestyle=":", linewidth=1)
    left.set(
        yscale="log",
        xlabel="update",
        ylabel="loss on answer tokens",
        title="Training loss (faint: per update, solid: mean of 10)",
    )
    right.set(
        xticks=[1, 2, 3],
        xlabel="epoch",
        ylabel="loss on answer tokens",
        title="Validation loss (ring: selected checkpoint)",
    )
    left.legend()
    right.legend()
    fig.savefig(out, dpi=150)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    smoke_args = commands.add_parser("smoke")
    smoke_args.add_argument("--adapter", choices=sorted(ADAPTERS), default="A")
    train_args = commands.add_parser("train")
    train_args.add_argument("--adapter", choices=sorted(ADAPTERS), default="A")
    train_args.add_argument("--seed", type=int, required=True, choices=SEEDS)
    seeds_args = commands.add_parser("seeds")
    seeds_args.add_argument("--adapter", choices=sorted(ADAPTERS), default="A")
    commands.add_parser("validate").add_argument("run", type=Path)
    summary = commands.add_parser("summarize")
    summary.add_argument("runs", type=Path, nargs="+")
    summary.add_argument("--baseline", type=Path)
    summary.add_argument(
        "--rebuilt",
        action="store_true",
        help="the baseline is a re-run of 2.5b: same prompt, cases and measures",
    )
    summary.add_argument(
        "--against-a", type=Path, help="summary of adapter A: B minus A for each seed"
    )
    upload = commands.add_parser("push")
    upload.add_argument("summary", type=Path)
    upload.add_argument("--repo", required=True)
    curves = commands.add_parser("curves")
    curves.add_argument("runs", type=Path, nargs="+")
    curves.add_argument(
        "--out", type=Path, help="default: docs/diagrams/adapter-<x>-losses.png"
    )
    args = parser.parse_args(argv)
    # configs/, runs/ and the seed processes are relative to the repository root
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    if args.command == "smoke":
        return smoke(args.adapter)
    if args.command == "seeds":
        statuses = all_seeds(args.adapter)
        return 0 if all(status == "ok" for status in statuses.values()) else 1
    if args.command == "train":
        train(args.seed, args.adapter)
    elif args.command == "validate":
        validate(args.run)
    elif args.command == "push":
        push(args.summary, args.repo)
    elif args.command == "curves":
        print(plot_losses(args.runs, args.out))
    else:
        summarise(args.runs, args.baseline, args.rebuilt, args.against_a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
