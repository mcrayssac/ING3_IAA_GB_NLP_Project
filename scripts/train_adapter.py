"""Train adapter A over several seeds, choose checkpoints on validation, summarise (task 2.6).

Usage, from the repository root:
    python -m scripts.train_adapter smoke
    python -m scripts.train_adapter train --seed 2026
    python -m scripts.train_adapter validate runs/<date>_2-6-adapter-a-s2026
    python -m scripts.train_adapter summarize RUN_DIR [RUN_DIR ...] [--baseline OUTPUTS]

Training and validation use the inference prompt chosen in task 2.5b
(configs/baseline-selection.json), so the adapter learns from the exact tokens it sees
in use. `validate` runs in a fresh process, which is the reload check. The final split
is never read.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import replace
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

CONFIG = Path("configs/adapter-a.toml")
SELECTION = Path("configs/baseline-selection.json")
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
    """Corpus A rows for training and validation rows for the loss after each epoch."""
    from boxbox.corpus import load_corpus
    from boxbox.training import build_rows

    limit = config.lora.max_length
    train = build_rows(engine, load_corpus("A_train"), limit)
    return train, build_rows(engine, load_corpus("validation"), limit)


def generate(engine, cases, cases_hash, run_id, version, identity) -> list[dict]:
    """One answer per validation target, kept raw, never retried (2.5b protocol)."""
    from boxbox.model import ConversationEngineError

    rows = []
    for case in cases:
        try:
            raw, _ = engine.respond_with_trace(
                **loads(case["input_json"]),
                fixed_history=True,
                required_history_turns=int(case["attributes"]["history_sensitive"]),
            )
            error = None
        except ConversationEngineError as failure:
            raw, error = failure.partial_response, failure.as_record()
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
    return rows


def planned_updates(config, rows: int) -> int:
    lora = config.lora
    return (
        math.ceil(rows / (lora.batch_size * lora.gradient_accumulation)) * lora.epochs
    )


def train(seed: int) -> Path:
    """Train one seed and keep a checkpoint per epoch with its validation loss."""
    from boxbox.training import train_lora

    config = replace(load_config(CONFIG), seed=seed)
    engine, device = load_engine(config)
    rows, eval_rows = training_rows(engine, config)
    extra = {
        "task": "2.6",
        "prompt_sha256": loads(SELECTION.read_text())["prompt_sha256"],
        "train_rows": len(rows),
        "eval_rows": len(eval_rows),
        "planned_updates": planned_updates(config, len(rows)),
    }
    name = f"2-6-adapter-a-s{seed}"
    run = start_run(name, config, str(device), engine.dtype, extra=extra)
    loaded = (engine.model, engine.tokenizer)
    metrics = train_lora(config, rows, run, device, eval_rows, loaded=loaded)
    losses = metrics["train_losses"] + [e["eval_loss"] for e in metrics["eval_losses"]]
    metrics["finite_losses"] = all(math.isfinite(value) for value in losses)
    metrics["planned_updates"] = extra["planned_updates"]
    finish_run(run, metrics)
    print(f"trained {run}: {metrics['steps']} updates")
    return run


def smoke() -> int:
    """Time a few generations and 10 updates, then project the 3-seed budget."""
    from boxbox.training import train_lora

    config = load_config(CONFIG)
    engine, device = load_engine(config)
    cases, _ = validation_cases(config)
    started = time.perf_counter()
    for case in cases[:SMOKE_GENERATIONS]:
        engine.respond_with_trace(**loads(case["input_json"]), fixed_history=True)
    generation = (time.perf_counter() - started) / SMOKE_GENERATIONS
    rows, _ = training_rows(engine, config)
    short = replace(config, lora=replace(config.lora, max_steps=SMOKE_STEPS))
    run = start_run("2-6-smoke", short, str(device), engine.dtype)
    metrics = train_lora(
        short, rows, run, device, loaded=(engine.model, engine.tokenizer)
    )
    updates = planned_updates(config, len(rows))
    per_seed = metrics["seconds_per_step"] * updates + generation * len(cases) * 3
    metrics |= {
        "seconds_per_generation": round(generation, 2),
        "planned_updates_per_seed": updates,
        "projected_hours_all_seeds": round(per_seed * len(SEEDS) / 3600, 2),
    }
    over_memory = metrics["max_memory_gb_at_step_end"] > config.mps_memory_cap_gb
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
    model, outputs, versions, reloads = None, [], [], {}
    for checkpoint in metrics["checkpoints"]:
        version = f"A-s{config.seed}-e{checkpoint['epoch']}"
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
        outputs += generate(adapted, cases, cases_hash, run.name, version, identity)
        versions.append(version)
        print(f"answered validation with {version}", flush=True)
    write_jsonl(run / "validation-outputs.jsonl", outputs)
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


def _seed_result(run: Path) -> dict[str, Any]:
    selection = loads((run / "selection.json").read_text())
    summaries = loads((run / "validation-summaries.json").read_text())
    version = selection["selected_candidate"]
    return {
        "run": run.name,
        "version": version,
        "summary": summaries[version],
        "metrics": {m: summaries[version]["metrics"][m]["value"] for m in METRICS},
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


def summarise(runs: list[Path], baseline_file: Path | None) -> Path:
    """Seed means and intervals, A minus baseline per seed, and the median seed as A."""
    seeds = [_seed_result(run) for run in runs]
    stats = {m: seed_interval([s["metrics"][m] for s in seeds]) for m in METRICS}
    versions = [s["version"] for s in seeds]
    ranking = select_prompt({s["version"]: s["summary"] for s in seeds}, versions)
    median = ranking["ranked_candidate_ids"][len(seeds) // 2]
    chosen = runs[versions.index(median)]
    baseline, bootstraps = None, {}
    if baseline_file is not None:
        baseline, digest = read_jsonl(baseline_file)
        if digest != loads(SELECTION.read_text())["baseline_outputs_sha256"]:
            raise ValueError("baseline outputs differ from the 2.5b selection")
        bootstraps = {
            s["version"]: against_baseline(r, s["version"], baseline)
            for s, r in zip(seeds, runs)
        }
    result = {
        "seeds": [{k: v for k, v in s.items() if k != "summary"} for s in seeds],
        "seed_intervals": stats,
        "interval_note": "95% Student t over training seeds; wide with this few runs",
        "ranking": ranking,
        "adapter_a": {"run": chosen.name, "version": median},
        "against_baseline": bootstraps or "pending: no baseline outputs given",
    }
    out = chosen.parent / f"{chosen.name.split('_')[0]}_2-6-adapter-a-summary.json"
    out.write_text(dumps(result) + "\n")
    print(f"adapter A is {median} from {chosen.name}; summary in {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("smoke")
    commands.add_parser("train").add_argument(
        "--seed", type=int, required=True, choices=SEEDS
    )
    commands.add_parser("validate").add_argument("run", type=Path)
    summary = commands.add_parser("summarize")
    summary.add_argument("runs", type=Path, nargs="+")
    summary.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    if args.command == "smoke":
        return smoke()
    if args.command == "train":
        train(args.seed)
    elif args.command == "validate":
        validate(args.run)
    else:
        summarise(args.runs, args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
