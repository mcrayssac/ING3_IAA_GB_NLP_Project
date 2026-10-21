"""Mini-test runner (2.7, and 3.2 with B) on the real mini-test corpus, with stand-in
cards and engines.

No model weights are loaded. Source cards are rebuilt from the corpus items themselves:
the real ones come from `scripts.rebuild_data cards`, which needs OpenF1.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from boxbox.evaluation import adapt_split, adapt_validation
from boxbox.evaluation._io import dumps, loads, read_jsonl, sha256
from scripts import mini_test as runner

_STAND_IN = {
    "gap_ahead": {"driver_number": "99", "seconds": 4.0, "state": "KNOWN"},
    "gap_behind": {"driver_number": "98", "seconds": 30.0, "state": "KNOWN"},
    "tyre_age_laps": 5,
}


def _source_card(item: dict) -> dict:
    card = loads(dumps(item["card"]))
    field = item.get("removed_field")
    if field == "pit_loss_seconds":
        card["pit_loss_seconds"] = loads("22.0")
        card["pit_loss_as_of_completed_lap"] = card["as_of_completed_lap"] - 1
    elif field:
        card[field] = _STAND_IN[field]
    return card


def write_cards(folder: Path, split: str = "mini_test") -> Path:
    """One stand-in card file per race of the split, from the corpus items."""
    splits = json.loads(Path("data/splits.json").read_text())
    items, _ = read_jsonl(Path(f"data/corpus/{split}.jsonl"))
    records: dict[str, tuple[str, dict]] = {}
    for item in items:
        card = _source_card(item)
        race = f"{card['race']['season']}-{card['race']['round']:02d}"
        records[item["card_id"]] = (
            race,
            {
                "card_id": item["card_id"],
                "split": split,
                "card": card,
                "provenance": {
                    "source": "openf1",
                    "session_key": splits["races"][race]["session_key"],
                    "cutoff_lap": card["as_of_completed_lap"],
                },
            },
        )
    folder.mkdir(parents=True, exist_ok=True)
    for race in splits["splits"][split]:
        rows = [r for where, r in records.values() if where == race]
        (folder / f"{race}.jsonl").write_text(
            "".join(dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    return folder


@pytest.fixture(autouse=True)
def _no_installed_versions(monkeypatch):
    """Run records read installed package versions; the tests need no torch."""
    import boxbox.runs

    monkeypatch.setattr(boxbox.runs, "environment", lambda: {"python": "test"})


ADAPTER_CONFIG = b'{"lora_alpha": 32, "peft_type": "LORA", "r": 16}\n'


@pytest.fixture(autouse=True)
def adapter_folder(tmp_path, monkeypatch) -> Path:
    """A stand-in folder for adapter A: its weights are not the real ones."""
    folder = tmp_path / "adapter"
    folder.mkdir()
    (folder / "adapter_config.json").write_bytes(ADAPTER_CONFIG)
    (folder / "adapter_model.safetensors").write_bytes(b"stand-in weights")
    prompt = Path("configs/prompts/p01-policy-first.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(
        runner, "resolve_adapter", lambda letter="A": (None, folder, prompt)
    )
    return folder


def _accept_stand_in_weights(run: Path, folder: Path) -> dict:
    """The plan as if the stand-in weights were the selected ones (tests only)."""
    plan = loads((run / "plan.json").read_text())
    plan["versions"]["A"]["adapter_sha256"] = sha256(
        (folder / "adapter_model.safetensors").read_bytes()
    )
    return plan


@pytest.fixture
def cards(tmp_path) -> Path:
    return write_cards(tmp_path / "cards")


def test_validation_adaptation_is_unchanged_by_the_generalisation(tmp_path):
    folder = write_cards(tmp_path / "cards", "validation")
    splits = json.loads(Path("data/splits.json").read_text())
    items, _ = read_jsonl(Path("data/corpus/validation.jsonl"))
    records = [
        row
        for race in splits["splits"]["validation"]
        for row in read_jsonl(folder / f"{race}.jsonl")[0]
    ]
    assert adapt_validation(items, records, splits) == adapt_split(
        items, records, splits, "validation"
    )
    with pytest.raises(ValueError, match="belong to mini_test only"):
        adapt_split(items, records, splits, "mini_test")
    with pytest.raises(ValueError, match="adapted for"):
        adapt_split(items, records, splits, "final")


def test_prepare_seals_40_separated_targets_and_both_versions(cards, tmp_path):
    run = runner.prepare("mini", cards, tmp_path / "runs")
    plan = loads((run / "plan.json").read_text())
    assert plan["population"]["targets"] == 40 and plan["planned_responses"] == 80
    assert plan["population"]["labels"] == {"BOX": 12, "STAY OUT": 12, "NO CALL": 16}
    assert set(plan["population"]["families"].values()) == {12, 10, 6}
    assert len(plan["population"]["races"]) == 5
    sep = plan["separation"]
    assert sep["races_shared_with_train_or_validation"] == 0
    assert sep["cards_shared"] == {"A_train": 0, "validation": 0}
    assert sep["questions_shared_with_A_train"] == 0
    assert plan["versions"]["A"]["adapter_sha256"].startswith("3322b5b3158e")
    assert (
        plan["versions"]["baseline"]["prompt_sha256"]
        == plan["versions"]["A"]["prompt_sha256"]
    )
    assert plan["versions"]["A"]["adapter_config_sha256"] == sha256(ADAPTER_CONFIG)
    assert (run / "versions/A/adapter_config.json").read_bytes() == ADAPTER_CONFIG
    evaluation = loads((run / "manifest.json").read_text())["extra"]["evaluation"]
    for key in ("protocol_sha256", "fixtures_sha256", "policy_source_sha256"):
        assert len(evaluation[key]) == 64
    assert evaluation["cases_sha256"] == plan["cases_sha256"]
    assert evaluation["acceptance_record"] is None
    for name, digest in plan["normative_files"].items():
        assert sha256((run / "sources" / name).read_bytes()) == digest
    assert "sources/data/cards/2025-18.jsonl" in plan["sealed_files"]
    runner.verify_plan(run)
    (run / "versions/A/prompt.txt").write_text("changed")
    with pytest.raises(ValueError, match="sealed artifact changed"):
        runner.verify_plan(run)


def test_a_changed_protocol_after_preparation_is_refused(cards, tmp_path, monkeypatch):
    protocol = tmp_path / "evaluation-protocol.md"
    protocol.write_bytes(runner.PROTOCOL.read_bytes())
    normative = tuple(protocol if p == runner.PROTOCOL else p for p in runner.NORMATIVE)
    monkeypatch.setattr(runner, "PROTOCOL", protocol)
    monkeypatch.setattr(runner, "NORMATIVE", normative)
    run = runner.prepare("mini", cards, tmp_path / "runs")
    runner.verify_plan(run)
    protocol.write_text("a later rule", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since preparation"):
        runner.verify_plan(run)


def test_a_changed_peft_config_is_refused(cards, tmp_path, adapter_folder):
    run = runner.prepare("mini", cards, tmp_path / "runs")
    plan = _accept_stand_in_weights(run, adapter_folder)
    runner.check_adapter(plan, adapter_folder)
    config = adapter_folder / "adapter_config.json"
    config.write_bytes(ADAPTER_CONFIG.replace(b"32", b"64"))  # lora_alpha 32 -> 64
    with pytest.raises(ValueError, match="adapter_config.json of adapter A differs"):
        runner.check_adapter(plan, adapter_folder)
    config.write_bytes(ADAPTER_CONFIG)
    (adapter_folder / "adapter_model.safetensors").write_bytes(b"other weights")
    with pytest.raises(ValueError, match="adapter_model.safetensors of adapter A"):
        runner.check_adapter(plan, adapter_folder)


def test_prepare_refuses_a_changed_corpus(cards, tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for path in Path("data/corpus").iterdir():
        if path.is_file():
            (corpus / path.name).write_bytes(path.read_bytes())
    mini = corpus / "mini_test.jsonl"
    mini.write_bytes(mini.read_bytes().replace(b"\n", b"\r\n", 1))
    monkeypatch.setattr(runner, "CORPUS", corpus)
    with pytest.raises(ValueError, match="changed"):
        runner.mini_test_cases(
            runner.load_config("configs/baseline-selected.toml"), cards
        )


class _Device:
    type = "cpu"

    def __str__(self) -> str:
        return "cpu"


def _fake_stack(monkeypatch, adapter, *, a_prompt_differs=False):
    """Stand-ins for torch, transformers, peft and the conversation engine."""
    loaded = {}

    class Engine:
        def __init__(self, model, tokenizer, config, instructions, device, dtype):
            self.model, self.tokenizer, self.config = model, tokenizer, config
            self.instructions, self.device, self.dtype = instructions, device, dtype

        def generation_settings(self):
            return {"do_sample": False, "seed": self.config.seed, "seed_active": False}

        def preflight_candidates(self, prompts, card, history, message, **kw):
            return {"ready": True, "candidates": {}}

        def respond_with_trace(self, card, history, message, **kw):
            version = getattr(self.model, "active", "baseline")
            raw = {
                "baseline": "CALL: BOX\nWHY: Box now.",
                "A": "CALL: NO CALL\nWHY: Unknown.",
                "B": "CALL: STAY OUT\nWHY: Stay out.",
            }[version]
            prompt = sha256(dumps([card, history, message]))
            if version != "baseline" and a_prompt_differs:
                prompt = sha256(prompt)
            return raw, {"prompt_token_ids_sha256": prompt, "possibly_truncated": False}

    model = ModuleType("boxbox.model")
    model.ConversationEngine = Engine
    model.ConversationEngineError = type("ConversationEngineError", (Exception,), {})
    peft = ModuleType("peft")

    class Adapted:
        """The base model with adapters on top; the active one answers."""

        active = "A"

        def to(self, device):
            return self

        def eval(self):
            return self

        def add_adapter(self, name, config):
            loaded[f"{name}_config"] = config

        def load_adapter(self, folder, adapter_name):
            loaded[f"{adapter_name}_folder"] = folder

        def set_adapter(self, name):
            self.active = name

    def from_pretrained(base, folder, config=None):
        loaded.update(folder=folder, config=config)
        return Adapted()

    peft.PeftModel = SimpleNamespace(from_pretrained=from_pretrained)
    peft.PeftConfig = SimpleNamespace(
        from_pretrained=lambda folder: (
            Path(folder) / "adapter_config.json"
        ).read_bytes()
    )
    torch = ModuleType("torch")
    torch.__version__ = "stand-in"
    transformers = ModuleType("transformers")
    transformers.__version__ = "stand-in"
    for name, module in {
        "boxbox.model": model,
        "peft": peft,
        "torch": torch,
        "transformers": transformers,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    def engines(plan, run):
        config = runner.load_config(run / "versions/baseline/config.toml")
        prompt = (run / "versions/baseline/prompt.txt").read_text()
        device = _Device()
        tokenizer = SimpleNamespace(chat_template="template")
        base = Engine("base", tokenizer, config, prompt, device, "float32")
        return {"baseline": base} | {
            letter: (
                runner.load_config(run / f"versions/{letter}/config.toml"),
                adapter,
                prompt,
            )
            for letter in plan["version_ids"][1:]
        }

    monkeypatch.setattr(runner, "load_engines", engines)
    checked = []
    monkeypatch.setattr(
        runner,
        "check_adapter",
        lambda plan, folder, letter="A": checked.append((letter, folder)),
    )
    return loaded, checked


def test_run_score_and_sheet_on_stand_in_answers(
    cards, tmp_path, monkeypatch, adapter_folder
):
    loaded, checked = _fake_stack(monkeypatch, adapter_folder)
    run = runner.prepare("mini", cards, tmp_path / "runs")
    runner.generate(run)
    assert checked == [("A", adapter_folder)]  # checked right before PEFT reads it
    assert loaded == {"folder": adapter_folder, "config": ADAPTER_CONFIG}
    outputs, _ = read_jsonl(run / "outputs.jsonl")
    assert len(outputs) == 80
    assert [o["version_id"] for o in outputs] == ["baseline"] * 40 + ["A"] * 40
    assert loads((run / "runtime.json").read_text())["same_prompt_tokens"] == 40

    result = runner.score(run)
    head = result["headline"]
    assert head["call_agreement"]["baseline"] == 12 / 40  # BOX on every target
    assert head["call_agreement"]["A"] == 16 / 40  # NO CALL on every target
    assert result["metrics"]["generation_errors"] == 0
    bootstrap = loads((run / "bootstrap.json").read_text())  # the 2.7 single contrast
    assert bootstrap["contrast_role"] == "principal_mini_test_exploratory"
    assert "B_minus_A" not in result["headline"]["call_agreement"]
    with (run / "review/review.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 80 and {r["version_code"] for r in rows} == {"V01", "V02"}
    assert "baseline" not in (run / "review/review.csv").read_text()
    assert len(list(csv.DictReader((run / "paired.csv").open()))) == 40

    # a pending sheet is accepted, keeps the human interval out and counts the gaps
    pending = runner.rated(run, run / "review/review.csv")
    assert pending == {"folder": pending["folder"], "ratings": 80, "pending": 80}
    assert not (Path(pending["folder"]) / "bootstrap.json").exists()

    for row in rows:
        row.update(rating_status="completed", rater_id="Matthieu Brault")
        row["rated_at"] = "2026-10-20T15:00:00+02:00"
        for axis in ("correctness", "role_format", "history", "scope", "factuality"):
            if row[axis] != "N/A":
                row[axis], row[axis + "_reason"] = "1", "stand-in score for the test"
    filled = tmp_path / "filled.csv"
    with filled.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    done = runner.rated(run, filled)
    assert done["pending"] == 0
    assert (Path(done["folder"]) / "bootstrap.json").exists()

    rows[0]["raw_response"] = "CALL: BOX\nWHY: edited."
    with filled.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="altered"):
        runner.rated(run, filled)


def test_run_stops_when_a_and_the_baseline_see_different_prompts(
    cards, tmp_path, monkeypatch, adapter_folder
):
    _fake_stack(monkeypatch, adapter_folder, a_prompt_differs=True)
    run = runner.prepare("mini", cards, tmp_path / "runs")
    with pytest.raises(ValueError, match="different prompts on 40"):
        runner.generate(run)
    assert len(read_jsonl(run / "outputs.jsonl")[0]) == 80  # raw answers kept


def test_run_refuses_a_second_attempt(cards, tmp_path, monkeypatch, adapter_folder):
    _fake_stack(monkeypatch, adapter_folder)
    run = runner.prepare("mini", cards, tmp_path / "runs")
    runner.generate(run)
    with pytest.raises(FileExistsError):
        runner.generate(run)


def test_cards_rebuilds_the_mini_test_races_only(tmp_path, monkeypatch):
    from collections import Counter

    from scripts import rebuild_data

    built = []

    def rebuild(race, split):
        built.append((race["race_id"], split))
        return {"cards": 1}, Counter()

    monkeypatch.setattr(rebuild_data, "CARDS_DIR", tmp_path)
    monkeypatch.setattr(rebuild_data, "_rebuild_race", rebuild)
    splits = json.loads(Path("data/splits.json").read_text())["splits"]
    assert sorted(runner.rebuild_cards()) == splits["mini_test"]
    assert {split for _, split in built} == {"mini_test"}
    assert (tmp_path / "mini_test-manifest.json").exists()


def test_prepare_with_b_seals_three_versions(cards, tmp_path):
    run = runner.prepare("mini", cards, tmp_path / "runs", with_b=True)
    plan = loads((run / "plan.json").read_text())
    assert plan["task"] == "3.2" and plan["version_ids"] == ["baseline", "A", "B"]
    assert plan["planned_responses"] == 120
    assert plan["versions"]["B"]["adapter_sha256"].startswith("70423a7d4aa7")
    assert plan["versions"]["B"]["config_file"] == "configs/adapter-b.toml"
    assert {v["prompt_sha256"] for v in plan["versions"].values()} == {
        plan["versions"]["baseline"]["prompt_sha256"]
    }
    assert (run / "versions/B/adapter_config.json").read_bytes() == ADAPTER_CONFIG
    evaluation = loads((run / "manifest.json").read_text())["extra"]["evaluation"]
    assert evaluation["retained_versions"] == ["baseline", "A", "B"]
    runner.verify_plan(run)


def test_with_b_refuses_a_b_selected_on_other_cases(cards, tmp_path, monkeypatch):
    selection = loads(runner.ADAPTER_B.read_text())
    selection["cases_sha256"] = "0" * 64
    other = tmp_path / "adapter-b-selection.json"
    other.write_text(dumps(selection))
    monkeypatch.setitem(runner.SELECTIONS, "B", other)
    with pytest.raises(ValueError, match="B was selected on other validation cases"):
        runner.prepare("mini", cards, tmp_path / "runs", with_b=True)


def test_run_and_score_with_b(cards, tmp_path, monkeypatch, adapter_folder):
    loaded, checked = _fake_stack(monkeypatch, adapter_folder)
    run = runner.prepare("mini", cards, tmp_path / "runs", with_b=True)
    runner.generate(run)
    assert checked == [("A", adapter_folder), ("B", adapter_folder)]
    assert loaded["B_config"] == ADAPTER_CONFIG  # the sealed configuration
    outputs, _ = read_jsonl(run / "outputs.jsonl")
    versions = ["baseline"] * 40 + ["A"] * 40 + ["B"] * 40
    assert [o["version_id"] for o in outputs] == versions
    assert loads((run / "runtime.json").read_text())["same_prompt_tokens_B"] == 40

    result = runner.score(run)
    head = result["headline"]["call_agreement"]
    assert (head["A"], head["B"]) == (16 / 40, 12 / 40)  # NO CALL, then STAY OUT
    assert head["B_minus_A"] == pytest.approx(-4 / 40)
    bootstrap = loads((run / "bootstrap.json").read_text())
    assert set(bootstrap) == {"A_minus_baseline", "B_minus_A", "B_minus_baseline"}
    with (run / "review/review.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 120 and len({r["version_code"] for r in rows}) == 3
