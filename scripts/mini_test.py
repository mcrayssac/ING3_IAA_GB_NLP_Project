"""Run the MVP mini-test: the baseline and adapter A on the same 40 targets (task 2.7),
and adapter B with them once B is trained (task 3.2, `prepare --with-b`).

Usage, from the repository root:
    python -m scripts.mini_test cards        # only if data/cards/ lacks the mini-test
    python -m scripts.mini_test prepare --name 2-7-mini-test [--with-b]
    python -m scripts.mini_test run --run-dir runs/<date>_2-7-mini-test
    python -m scripts.mini_test score --run-dir runs/<date>_2-7-mini-test
    python -m scripts.mini_test rated --run-dir runs/<date>_2-7-mini-test --sheet FILLED.csv

`cards` rebuilds the card files of the 7 mini-test races from OpenF1, as
`scripts.rebuild_data cards` does for every split, without building the final cards.
`prepare` seals the 40 mini-test targets, both versions and the checks of query and
race separation before any model is loaded. `run` answers every target once with the
baseline (2.5b) and then with adapter A (2.6), in one process on one machine, and keeps
every raw answer with its generation trace. Nothing is retried. `score` pairs the
answers, computes the automatic measures with A minus baseline over a race bootstrap,
and exports the masked rating sheet of all 80 answers. `rated` reads the filled sheet
and adds the five-axis human means. With `--with-b`, B answers after A in the same
process, `score` and `rated` add B minus A and B minus baseline in `bootstrap-B.json`,
and the sheet holds 120 answers. `bootstrap.json` keeps A minus baseline in every run.
The final split is never read.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from boxbox.config import load_config
from boxbox.evaluation import (
    adapt_split,
    bootstrap_compare,
    export_review,
    import_review,
    observations,
    pair_outputs,
    summarize,
    validate_cases,
)
from boxbox.evaluation._io import (
    FAMILIES,
    LABELS,
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    loads,
    read_jsonl,
    sha256,
    write_jsonl,
)
from boxbox.runs import finish_run, source_sha256, start_run

ROOT = Path(__file__).resolve().parents[1]
SPLIT = "mini_test"
VERSIONS = ("baseline", "A")  # the evaluator's names for the principal contrast
BASELINE = Path("configs/baseline-selection.json")
ADAPTER_A = Path("configs/adapter-a-selection.json")
ADAPTER_B = Path("configs/adapter-b-selection.json")
SELECTIONS = {"A": ADAPTER_A, "B": ADAPTER_B}
CORPUS = Path("data/corpus")
PROTOCOL = Path("docs/evaluation-protocol.md")
FIXTURES = Path("reference/evaluation-fixtures.json")
POLICY = Path("boxbox/rules/decision.py")
SPLITS = Path("data/splits.json")
# The files that define how the answers are scored: protocol section 1 asks to keep
# exact copies with the run. Each is copied to sources/ and must stay unchanged.
NORMATIVE = (
    PROTOCOL,
    FIXTURES,
    Path("reference/fixtures.json"),
    POLICY,
    SPLITS,
    CORPUS / "manifest.json",
    CORPUS / f"{SPLIT}.jsonl",
)
MIN_TARGETS = 20  # roadmap 2.7: at least 20 unseen queries
# export_review asks why B is missing from a baseline/A sheet; at the MVP it does not
# exist yet. This records that reason; it is not the 3.2 decision to drop B.
NO_B_YET = (
    "Task 2.7 (#14): the MVP mini-test compares baseline and A only, because adapter "
    "B is trained later in 3.2. This is not a decision to drop B."
)


def git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(dumps(value) + "\n")


def _checked(selection_file: Path) -> dict:
    """A recorded selection whose config and prompt files still have their hashes."""
    selection = loads(selection_file.read_text(encoding="utf-8"))
    for key in ("config", "prompt"):
        path = Path(selection[f"{key}_file"])
        if sha256(path.read_bytes()) != selection[f"{key}_sha256"]:
            raise ValueError(f"{path} changed since {selection_file} was recorded")
    return selection


def resolve_adapter(letter: str = "A") -> tuple[Any, Path, str]:
    """Config, folder and prompt of adapter A or B, as the model code selects it."""
    from boxbox.model import selected_adapter

    # refuses weights other than the selected ones
    return selected_adapter(SELECTIONS[letter])


def _seal_adapter(run: Path, letter: str, selection: dict) -> dict:
    """Copy the adapter's PEFT configuration into the run and describe the adapter."""
    # PEFT reads lora_alpha and the target modules from adapter_config.json, so the
    # configuration is sealed with the weights; `run` loads the adapter with this copy.
    _, adapter_dir, _ = resolve_adapter(letter)
    adapter_config = (adapter_dir / "adapter_config.json").read_bytes()
    (run / "versions" / letter / "adapter_config.json").write_bytes(adapter_config)
    local = Path("runs") / selection["run"] / selection["checkpoint"]
    return {
        "adapter_sha256": selection["adapter_sha256"],
        "adapter_config_sha256": sha256(adapter_config),
        "adapter_source": "local run folder"
        if adapter_dir == local
        else "pinned Hub revision",
        "checkpoint": f"{selection['run']}/{selection['checkpoint']}",
        "hub": selection.get("hub"),
        "version_name": selection["version"],
    }


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _masked(text: str) -> str:
    """A question with its numbers and car numbers hidden, to compare wordings."""
    return re.sub(r"\d+(\.\d+)?", "#", text.strip().lower())


def separation(cases: list[dict], splits: dict) -> dict:
    """Race and query separation of the mini-test from training and validation."""
    races = {name: set(ids) for name, ids in splits["splits"].items()}
    mine = {case["race_id"] for case in cases}
    if not mine <= races[SPLIT]:
        raise ValueError(
            f"targets outside the {SPLIT} races: {sorted(mine - races[SPLIT])}"
        )
    shared = {n: sorted(races[SPLIT] & races[n]) for n in ("train", "validation")}
    if any(shared.values()):
        raise ValueError(f"mini-test races also in other splits: {shared}")
    seen = {}
    for name in ("A_train", "validation"):
        items, _ = read_jsonl(CORPUS / f"{name}.jsonl")
        seen[name] = {
            "cards": {item["card_id"] for item in items},
            "questions": {
                _masked(m["content"])
                for item in items
                for m in item["messages"]
                if m["role"] == "user"
            },
        }
    cards = {case["card_id"] for case in cases}
    questions = {_masked(case["message"]) for case in cases}
    overlap = {
        name: {
            "cards": len(cards & s["cards"]),
            "questions": len(questions & s["questions"]),
        }
        for name, s in seen.items()
    }
    if any(o["cards"] for o in overlap.values()) or overlap["A_train"]["questions"]:
        raise ValueError(f"mini-test targets seen before: {overlap}")
    return {
        "mini_test_races": sorted(mine),
        "races_shared_with_train_or_validation": 0,
        "cards_shared": {n: o["cards"] for n, o in overlap.items()},
        "questions_shared_with_A_train": overlap["A_train"]["questions"],
        # validation and the mini-test draw on the same held-out phrasing set (2.2)
        "questions_shared_with_validation": overlap["validation"]["questions"],
        "question_rule": "user turns compared with numbers masked",
    }


def population(cases: list[dict]) -> dict:
    labels = {label: 0 for label in LABELS}
    families = {family: 0 for family in FAMILIES}
    for case in cases:
        labels[case["reference"]["expected_call"]] += 1
        families[case["primary_family"]] += 1
    missing = [k for k, v in {**labels, **families}.items() if not v]
    if len(cases) < MIN_TARGETS or missing:
        raise ValueError(f"mini-test too small or incomplete: {len(cases)}, {missing}")
    return {
        "targets": len(cases),
        "labels": labels,
        "families": families,
        "Z": labels["NO CALL"],
        "D": labels["BOX"] + labels["STAY OUT"],
        "races": {
            race: sum(c["race_id"] == race for c in cases)
            for race in sorted({c["race_id"] for c in cases})
        },
    }


def mini_test_cases(config, cards_dir: Path) -> tuple[list[dict], dict, str]:
    """The 40 targets, with the corpus and card guards, and exact source decimals."""
    from boxbox.corpus import load_corpus
    from boxbox.data import load_cards, load_splits

    splits = load_splits()
    load_corpus(SPLIT)  # refuses a corpus file whose hash differs from the manifest
    load_cards(SPLIT, config, cards_dir=cards_dir)  # refuses cards of another split
    items, digest = read_jsonl(CORPUS / f"{SPLIT}.jsonl")
    manifest = loads((CORPUS / "manifest.json").read_text())
    if digest != manifest["files"][f"{SPLIT}.jsonl"]["sha256"]:
        raise ValueError("the mini-test corpus changed after the upstream check")
    records = []
    for race in splits["splits"][SPLIT]:
        records.extend(read_jsonl(cards_dir / f"{race}.jsonl")[0])
    cases = adapt_split(items, records, splits, SPLIT, config.history_turns)
    return cases, splits, digest


def rebuild_cards() -> dict:
    """The mini-test races' card files only; prepare then checks them against the corpus."""
    from boxbox.data import load_splits
    from scripts import rebuild_data

    document = load_splits()
    cards_dir = rebuild_data.CARDS_DIR
    cards_dir.mkdir(parents=True, exist_ok=True)
    entries = {
        race: rebuild_data._rebuild_race(document["races"][race], SPLIT)[0]
        for race in document["splits"][SPLIT]
    }
    report = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "splits_sha256": document["splits_sha256"],
        "races": entries,
    }
    (cards_dir / "mini_test-manifest.json").write_text(dumps(report) + "\n")
    return {race: entry["cards"] for race, entry in entries.items()}


def check_versions(baseline: dict, adapters: dict[str, dict]) -> dict:
    """Configs of the baseline and adapters, refused unless only the adapter differs."""
    configs = {"baseline": load_config(baseline["config_file"])} | {
        letter: load_config(selection["config_file"])
        for letter, selection in adapters.items()
    }
    if configs["baseline"].adapter != "none" or any(
        configs[letter].adapter != letter for letter in adapters
    ):
        raise ValueError(
            f"the versions must be the unadapted baseline and adapters {list(adapters)}"
        )
    if any(c.final_test_open for c in configs.values()):
        raise ValueError("the final split must stay closed")
    for letter, adapter in adapters.items():
        if baseline["prompt_sha256"] != adapter["prompt_sha256"]:
            raise ValueError(
                f"{letter} was trained on another prompt than the baseline's"
            )
        for field in ("model_id", "model_revision", "history_turns", "decoding"):
            if getattr(configs["baseline"], field) != getattr(configs[letter], field):
                raise ValueError(f"baseline and {letter} differ in {field}")
        if adapter["cases_sha256"] != baseline["cases_sha256"]:
            raise ValueError(
                f"{letter} was selected on other validation cases than the baseline"
            )
    return configs


def prepare(name: str, cards_dir: Path, runs_dir: Path, with_b: bool = False) -> Path:
    """Seal targets, versions and separation checks before any model is loaded."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("name must be a simple new run name")
    version_ids = ["baseline", "A", "B"] if with_b else list(VERSIONS)
    baseline = _checked(BASELINE)
    adapters = {letter: _checked(SELECTIONS[letter]) for letter in version_ids[1:]}
    configs = check_versions(baseline, adapters)

    cases, splits, corpus_hash = mini_test_cases(configs["baseline"], cards_dir)
    validate_cases(cases, splits)
    counts = population(cases)
    separated = separation(cases, splits)
    card_files = [cards_dir / f"{race}.jsonl" for race in splits["splits"][SPLIT]]
    if (cards_dir / "mini_test-manifest.json").exists():
        card_files.append(cards_dir / "mini_test-manifest.json")

    # No model is loaded here: the device and dtype of the answers are in runtime.json.
    run = start_run(
        name,
        configs["baseline"],
        "see runtime.json",
        "see runtime.json",
        runs_dir=runs_dir,
    )
    cases_hash = write_jsonl(run / "cases.jsonl", cases)
    (run / "inputs.jsonl").write_text(
        "".join(c["input_json"] + "\n" for c in cases), encoding="utf-8"
    )
    versions = {}
    for version, selection in [("baseline", baseline), *adapters.items()]:
        folder = run / "versions" / version
        folder.mkdir(parents=True)
        for key in ("config", "prompt"):
            source = Path(selection[f"{key}_file"])
            (folder / f"{key}{source.suffix}").write_bytes(source.read_bytes())
        versions[version] = {
            "config_file": selection["config_file"],
            "config_sha256": selection["config_sha256"],
            "prompt_sha256": selection["prompt_sha256"],
            "selected_in": selection["task"],
        }
    for letter, selection in adapters.items():
        versions[letter].update(_seal_adapter(run, letter, selection))
    normative = {}
    for source, copy_name in [(p, p.as_posix()) for p in NORMATIVE] + [
        (p, f"data/cards/{p.name}") for p in card_files
    ]:
        target = run / "sources" / copy_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        normative[copy_name] = sha256(target.read_bytes())
    sealed = {
        str(p.relative_to(run)).replace("\\", "/"): sha256(p.read_bytes())
        for folder in ("versions", "sources")
        for p in sorted((run / folder).rglob("*"))
        if p.is_file()
    }
    sealed |= {
        "cases.jsonl": cases_hash,
        "inputs.jsonl": sha256((run / "inputs.jsonl").read_bytes()),
    }
    plan = {
        "task": "3.2" if with_b else "2.7",
        "created_utc": datetime.now(UTC).isoformat(),
        "split": SPLIT,
        "versions": versions,
        "version_ids": version_ids,
        "population": counts,
        "separation": separated,
        "planned_responses": len(cases) * len(version_ids),
        "cases_sha256": cases_hash,
        "corpus_sha256": corpus_hash,
        "head_sha": git("rev-parse", "HEAD"),
        "git_status": git("status", "--porcelain", "--untracked-files=all"),
        "source_sha256": source_sha256(),
        "sealed_files": sealed,
        # exact copies in sources/; the repository files must also keep these hashes
        "normative_files": {p.as_posix(): normative[p.as_posix()] for p in NORMATIVE},
        "history_mode": "fixed",
        "human_review": {
            "targets": "all 40 mini-test targets, three versions: 120 masked answers"
            if with_b
            else "all 40 mini-test targets, both versions: 80 masked answers",
            "reason": "The 8-per-family quota of protocol section 8 is for the final "
            "pool; the mini-test has only 6 usable, follow-up and out-of-scope "
            "targets, so every target is rated instead of a sample.",
        },
        "protocol": {
            "id": PROTOCOL_ID,
            "version": PROTOCOL_VERSION,
            "sha256": sha256(PROTOCOL.read_bytes()),
            "status": "proposed",
        },
        "limitations": [
            "Policy agreement on supplied cards does not validate strict-cutoff availability.",
            "The mini-test is exploratory: 40 targets from 5 races with cards.",
            "Answers can differ in text between machines; both versions run in one process here.",
        ],
    }
    write_json(run / "plan.json", plan)
    manifest_path = run / "manifest.json"
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest["extra"] = {
        "mini_test": {"plan_sha256": sha256((run / "plan.json").read_bytes())},
        "evaluation": {  # protocol section 1
            "protocol_id": PROTOCOL_ID,
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": normative[PROTOCOL.as_posix()],
            "fixtures_sha256": normative[FIXTURES.as_posix()],
            "policy_git_commit": plan["head_sha"] or None,
            "policy_source_sha256": normative[POLICY.as_posix()],
            "cases_sha256": cases_hash,
            "input_ledger_sha256": sealed["inputs.jsonl"],
            "data_manifest_sha256": normative[(CORPUS / "manifest.json").as_posix()],
            "split_manifest_sha256": normative[SPLITS.as_posix()],
            # every target is rated, so there is no sampling manifest (plan.human_review)
            "sampling_manifest_sha256": None,
            "history_mode": "fixed",
            "retained_versions": version_ids,
            "protocol_status": "proposed",
            "acceptance_record": None,
            "git_dirty": bool(plan["git_status"]),
        },
    }
    _write_text(manifest_path, dumps(manifest) + "\n")
    return run


def verify_plan(run: Path) -> tuple[dict, list[dict], dict]:
    from boxbox.data import load_splits

    plan = loads((run / "plan.json").read_text())
    if plan["task"] not in ("2.7", "3.2") or plan["split"] != SPLIT:
        raise ValueError("not a mini-test run of 2.7 or 3.2")
    manifest = loads((run / "manifest.json").read_text(encoding="utf-8"))
    extra = manifest.get("extra", {})
    if "evaluation" not in extra or "normative_files" not in plan:
        raise ValueError("prepared without the evaluation record; prepare a new run")
    if sha256((run / "plan.json").read_bytes()) != extra["mini_test"]["plan_sha256"]:
        raise ValueError("plan.json changed since preparation")
    for relative, expected in plan["normative_files"].items():
        if (
            not Path(relative).exists()
            or sha256(Path(relative).read_bytes()) != expected
        ):
            raise ValueError(f"{relative} changed since preparation; prepare a new run")
    for relative, expected in plan["sealed_files"].items():
        if sha256((run / relative).read_bytes()) != expected:
            raise ValueError(f"sealed artifact changed: {relative}")
    cases, digest = read_jsonl(run / "cases.jsonl")
    if digest != plan["cases_sha256"]:
        raise ValueError("case ledger changed")
    splits = load_splits()
    validate_cases(cases, splits)
    return plan, cases, splits


def _answer(
    engine, case: dict, run_id: str, version: str, plan: dict
) -> tuple[dict, dict]:
    """One answer and its trace; a generation error is kept as an answer, never retried."""
    from boxbox.model import ConversationEngineError

    try:
        raw, trace = engine.respond_with_trace(
            **loads(case["input_json"]),
            fixed_history=True,
            required_history_turns=int(case["attributes"]["history_sensitive"]),
        )
        error = None
    except ConversationEngineError as failure:
        raw, trace, error = failure.partial_response, failure.trace, failure.as_record()
    row = {
        "response_id": f"{run_id}:{version}:{case['case_id']}",
        "case_id": case["case_id"],
        "version_id": version,
        "run_id": run_id,
        "config_sha256": plan["versions"][version]["config_sha256"],
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "cases_sha256": plan["cases_sha256"],
        "input_sha256": case["input_sha256"],
        "status": "generation_error" if error else "ok",
        "raw_response": raw,
        "error": error,
    }
    attempt = {
        "response_id": row["response_id"],
        "case_id": case["case_id"],
        "version_id": version,
        "input_sha256": case["input_sha256"],
        "trace": trace,
    }
    return row, attempt


def _settings(engine) -> str:
    """Generation settings without the seed, which greedy decoding never uses."""
    settings = engine.generation_settings()
    if settings.pop("seed_active"):
        raise ValueError("sampling is on; the comparison expects greedy decoding")
    settings.pop("seed")
    return dumps(settings)


def check_adapter(plan: dict, adapter_dir: Path, letter: str = "A") -> None:
    """Refuse an adapter folder unless its weights and PEFT configuration are sealed."""
    sealed = plan["versions"][letter]
    for name, key in (
        ("adapter_model.safetensors", "adapter_sha256"),
        ("adapter_config.json", "adapter_config_sha256"),
    ):
        if sha256((Path(adapter_dir) / name).read_bytes()) != sealed[key]:
            raise ValueError(
                f"{name} of adapter {letter} differs from the one sealed in the plan"
            )


def load_engines(plan: dict, run: Path) -> dict:
    """The baseline engine, then each adapter on the same base model."""
    from boxbox.model import load_conversation_engine

    baseline = load_config(run / "versions/baseline/config.toml")
    prompt = (run / "versions/baseline/prompt.txt").read_text(encoding="utf-8")
    engines = {"baseline": load_conversation_engine(baseline, instructions=prompt)}
    for letter in plan["version_ids"][1:]:
        config, adapter_dir, instructions = resolve_adapter(letter)
        check_adapter(plan, adapter_dir, letter)
        if instructions != prompt:
            raise ValueError(f"{letter}'s prompt differs from the baseline's")
        engines[letter] = (config, adapter_dir, instructions)
    return engines


def generate(run: Path) -> None:
    """Every target with the baseline, then A, then B if planned; rows flushed one by one."""
    plan, cases, _ = verify_plan(run)
    if plan["source_sha256"] != source_sha256():
        raise ValueError("code or configs changed since preparation; prepare a new run")
    write_json(
        run / "attempt-start.json", {"started_utc": datetime.now(UTC).isoformat()}
    )
    from peft import PeftConfig, PeftModel

    from boxbox.model import ConversationEngine

    loaded = load_engines(plan, run)
    base = loaded["baseline"]
    preflight = []
    for case in cases:
        result = base.preflight_candidates(
            {"common": base.instructions},
            **loads(case["input_json"]),
            fixed_history=True,
            required_history_turns=int(case["attributes"]["history_sensitive"]),
        )
        preflight.append({"case_id": case["case_id"], **result})
    write_jsonl(run / "preflight.jsonl", preflight)
    if not all(row["ready"] for row in preflight):
        raise ValueError("context preflight failed; no generation attempted")

    prompt_hashes: dict[str, dict[str, str]] = {}
    with (
        (run / "outputs.jsonl").open("x", encoding="utf-8", newline="\n") as outputs,
        (run / "attempts.jsonl").open("x", encoding="utf-8", newline="\n") as attempts,
    ):

        def answer_all(engine, version: str) -> None:
            prompt_hashes[version] = {}
            for index, case in enumerate(cases, 1):
                row, attempt = _answer(engine, case, run.name, version, plan)
                outputs.write(dumps(row) + "\n")
                attempts.write(dumps(attempt) + "\n")
                outputs.flush()
                attempts.flush()
                prompt_hashes[version][case["case_id"]] = (attempt["trace"] or {}).get(
                    "prompt_token_ids_sha256"
                )
                print(f"{version}: {index}/{len(cases)}", flush=True)

        answer_all(base, "baseline")
        config, adapter_dir, instructions = loaded["A"]
        check_adapter(plan, adapter_dir)  # again, right before PEFT reads the folder
        # PEFT gets the sealed configuration, not whatever the folder holds now
        sealed_config = PeftConfig.from_pretrained(str(run / "versions/A"))
        model = (
            PeftModel.from_pretrained(base.model, adapter_dir, config=sealed_config)
            .to(base.device)
            .eval()
        )
        adapted = ConversationEngine(
            model,
            base.tokenizer,
            config,
            instructions=instructions,
            device=base.device,
            dtype=base.dtype,
        )
        if _settings(adapted) != _settings(base):
            raise ValueError("baseline and A have different generation settings")
        answer_all(adapted, "A")
        if "B" in loaded:
            b_config, b_dir, b_instructions = loaded["B"]
            check_adapter(plan, b_dir, "B")  # again, right before PEFT reads it
            # B gets its sealed configuration first, so load_adapter reads only weights
            model.add_adapter("B", PeftConfig.from_pretrained(str(run / "versions/B")))
            model.load_adapter(b_dir, adapter_name="B")
            model.set_adapter("B")
            b_engine = ConversationEngine(
                model,
                base.tokenizer,
                b_config,
                instructions=b_instructions,
                device=base.device,
                dtype=base.dtype,
            )
            if _settings(b_engine) != _settings(base):
                raise ValueError("baseline and B have different generation settings")
            answer_all(b_engine, "B")

    same = {}
    for letter in plan["version_ids"][1:]:
        same[letter] = sum(
            prompt_hashes[letter][c] == prompt_hashes["baseline"][c] is not None
            for c in prompt_hashes["baseline"]
        )
        if same[letter] != len(cases):
            raise ValueError(
                f"{letter} and the baseline saw different prompts on "
                f"{len(cases) - same[letter]} targets"
            )
    import torch
    import transformers

    template = base.tokenizer.chat_template
    write_json(
        run / "runtime.json",
        {
            "device": str(base.device),
            "device_name": torch.cuda.get_device_name(0)
            if base.device.type == "cuda"
            else str(base.device),
            "dtype": str(base.dtype),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "model_revision": base.config.model_revision,
            "adapter_dir": str(adapter_dir),
            "adapter_config_sha256": plan["versions"]["A"]["adapter_config_sha256"],
            "chat_template_sha256": sha256(
                template if isinstance(template, str) else dumps(template)
            ),
            "generation_settings": loads(_settings(base)),
            "same_prompt_tokens": same["A"],
        }
        | (
            {
                "adapter_dir_B": str(loaded["B"][1]),
                "adapter_config_sha256_B": plan["versions"]["B"][
                    "adapter_config_sha256"
                ],
                "same_prompt_tokens_B": same["B"],
            }
            if "B" in loaded
            else {}
        ),
    )
    write_json(
        run / "attempt-complete.json",
        {
            "outputs_sha256": sha256((run / "outputs.jsonl").read_bytes()),
            "attempts_sha256": sha256((run / "attempts.jsonl").read_bytes()),
        },
    )


def _outputs(run: Path) -> list[dict]:
    complete = loads((run / "attempt-complete.json").read_text())
    outputs, digest = read_jsonl(run / "outputs.jsonl")
    if (
        digest != complete["outputs_sha256"]
        or sha256((run / "attempts.jsonl").read_bytes()) != complete["attempts_sha256"]
    ):
        raise ValueError("generation artifacts changed")
    return outputs


def cut_at_limit(run: Path, versions: list[str]) -> dict[str, int]:
    attempts, _ = read_jsonl(run / "attempts.jsonl")
    return {
        v: sum(
            a["version_id"] == v
            and (a["trace"] or {}).get("possibly_truncated") is True
            for a in attempts
        )
        for v in versions
    }


def b_contrasts(rows: dict, versions: list[str], human: bool = False) -> dict:
    """With B: B minus A (principal once B is retained) and B minus baseline."""
    if "B" not in versions:
        return {}
    pairs = {
        "B_minus_A": ("A", "principal_mini_test_exploratory"),
        "B_minus_baseline": ("baseline", "exploratory_mini_test"),
    }
    return {
        name: bootstrap_compare(rows, old, "B", human=human) | {"contrast_role": role}
        for name, (old, role) in pairs.items()
    }


def score(run: Path) -> dict:
    """Automatic measures, the contrasts over races, a paired table and the sheet."""
    plan, cases, splits = verify_plan(run)
    versions = plan["version_ids"]
    outputs = _outputs(run)
    paired = pair_outputs(cases, outputs, versions, plan["cases_sha256"], splits)
    rows = observations(cases, paired)
    summaries = {v: summarize(rows[v]) for v in versions}
    comparison = bootstrap_compare(rows, "baseline", "A")
    comparison["contrast_role"] = "principal_mini_test_exploratory"
    with_b = b_contrasts(rows, versions)
    write_json(run / "summaries.json", summaries)
    write_json(run / "bootstrap.json", comparison)
    if with_b:
        write_json(run / "bootstrap-B.json", with_b)
    with (run / "paired.csv").open("x", newline="", encoding="utf-8") as stream:
        fields = ["case_id", "race_id", "primary_family", "expected_call", "message"]
        fields += [
            f"{v}/{f}"
            for v in versions
            for f in ("extracted_call", "strict_format_valid", "raw_response")
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "race_id": case["race_id"],
                    "primary_family": case["primary_family"],
                    "expected_call": case["reference"]["expected_call"],
                    "message": case["message"],
                    **{
                        f"{v}/{f}": paired[v][case["case_id"]][f]
                        for v in versions
                        for f in (
                            "extracted_call",
                            "strict_format_valid",
                            "raw_response",
                        )
                    },
                }
            )
    export_review(
        run / "review",
        cases,
        paired,
        sorted(c["case_id"] for c in cases),
        drop_b_record=None if "B" in versions else NO_B_YET,
    )
    metrics = {
        "planned_responses": plan["planned_responses"],
        "retained_responses": len(outputs),
        "generation_errors": sum(o["status"] != "ok" for o in outputs),
        "cut_at_token_limit": cut_at_limit(run, versions),
        "human_ratings": "pending: fill review/review.csv, then run `rated`",
    }
    finish_run(run, metrics)
    headline_table = headline(summaries, comparison, with_b, versions)
    return {"metrics": metrics, "headline": headline_table}


def headline(
    summaries: dict, comparison: dict, with_b: dict, versions: list[str]
) -> dict:
    """The six selection measures of each version, and each contrast over races."""
    names = (
        "strict_format_rate",
        "call_agreement",
        "unjustified_decision_rate",
        "excessive_refusal_rate",
        "macro_label_agreement",
        "macro_family_agreement",
    )
    table = {}
    for name in names:
        key = f"overall/{name}"
        contrast = comparison["metrics"][key]
        table[name] = {v: summaries[v]["metrics"][key]["value"] for v in versions} | {
            "A_minus_baseline": contrast["difference"],
            "interval_95": contrast["difference_interval"],
            "interval_status": contrast["interval_status"],
        }
        for other, contrasted in with_b.items():
            extra = contrasted["metrics"][key]
            table[name] |= {
                other: extra["difference"],
                f"{other}_interval_95": extra["difference_interval"],
            }
    return table


def rated(run: Path, sheet: Path) -> dict:
    """Validate the filled sheet and add the five-axis human summaries."""
    plan, cases, splits = verify_plan(run)
    versions = plan["version_ids"]
    paired = pair_outputs(cases, _outputs(run), versions, plan["cases_sha256"], splits)
    lookup = loads((run / "review/response-lookup.json").read_text())
    ratings = import_review(sheet, lookup, cases)
    pending = sum(r["rating_status"] != "completed" for r in ratings)
    folder = run / f"human-{len(list(run.glob('human-*'))) + 1:02d}"
    folder.mkdir()  # each reading of a sheet is kept; none is overwritten
    (folder / "sheet.csv").write_bytes(sheet.read_bytes())
    write_json(folder / "read.json", {"read_utc": datetime.now(UTC).isoformat()})
    write_jsonl(folder / "ratings.jsonl", ratings)
    ids = sorted(c["case_id"] for c in cases)
    rows = observations(cases, paired, ratings, ids)
    summaries = {v: summarize(rows[v], human=True) for v in versions}
    write_json(folder / "summaries.json", summaries)
    if not pending:
        write_json(
            folder / "bootstrap.json",
            bootstrap_compare(rows, "baseline", "A", human=True),
        )
        with_b = b_contrasts(rows, versions, human=True)
        if with_b:
            write_json(folder / "bootstrap-B.json", with_b)
    return {"folder": str(folder), "ratings": len(ratings), "pending": pending}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cards", help="rebuild the mini-test card files from OpenF1")
    prep = commands.add_parser("prepare", help="seal targets, versions and checks")
    prep.add_argument("--name", required=True)
    prep.add_argument("--cards-dir", type=Path, default=Path("data/cards"))
    prep.add_argument("--runs-dir", type=Path, default=Path("runs"))
    prep.add_argument(
        "--with-b", action="store_true", help="add adapter B (task 3.2): 120 answers"
    )
    for name in ("run", "score", "rated"):
        command = commands.add_parser(name)
        command.add_argument("--run-dir", required=True, type=Path)
        if name == "rated":
            command.add_argument("--sheet", required=True, type=Path)
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != ROOT:
        parser.error("run from the repository root")
    if args.command == "cards":
        print(json.dumps(rebuild_cards(), indent=2))
    elif args.command == "prepare":
        print(prepare(args.name, args.cards_dir, args.runs_dir, args.with_b))
    elif args.command == "run":
        generate(args.run_dir)
    elif args.command == "score":
        print(json.dumps(score(args.run_dir), indent=2, default=str))
    else:
        print(json.dumps(rated(args.run_dir, args.sheet), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
