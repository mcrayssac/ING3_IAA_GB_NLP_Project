"""Deterministic contract tests for the shared conversation engine."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import WhitespaceSplit
from transformers import GenerationConfig, PreTrainedTokenizerFast
from transformers.utils import chat_template_utils

from boxbox.app.session import send
from boxbox.config import Decoding, RunConfig
from boxbox.evaluation import pair_outputs, prepare_case, validate_cases
from boxbox.evaluation._io import PROTOCOL_ID, PROTOCOL_VERSION
from boxbox.model import (
    ConversationEngine,
    ConversationEngineError,
    baseline_instructions,
)
from scripts import smoke_conversation


def make_config(
    *,
    turns: int = 3,
    max_context: int = 100,
    max_new_tokens: int = 4,
    seconds: float = 5.0,
) -> RunConfig:
    return RunConfig(
        history_turns=turns,
        decoding=Decoding(
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=1.0,
            top_p=1.0,
            max_context_tokens=max_context,
            max_generation_seconds=seconds,
        ),
    )


class FakeTokenizer:
    model_max_length = 512
    eos_token_id = 2
    pad_token_id = 2
    chat_template = "native-test-template: {{ role }} {{ content }}"

    def __init__(self, token_count=None, response: str = "CALL: BOX\nWHY: From card."):
        self.token_count = token_count or (lambda messages: len(messages))
        self.response = response
        self.messages = None
        self.options = None
        self.decoded_ids = None
        self.decode_options = None

    def apply_chat_template(self, messages, **kwargs):
        self.messages = copy.deepcopy(messages)
        self.options = kwargs
        count = self.token_count(messages)
        ids = torch.arange(count, dtype=torch.long).reshape(1, count)
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids)}

    def decode(self, token_ids, **kwargs):
        self.decoded_ids = list(token_ids)
        self.decode_options = kwargs
        return self.response


class FakeModel(torch.nn.Module):
    def __init__(self, output_ids=(91, 2), fail: Exception | None = None):
        super().__init__()
        self.anchor = torch.nn.Parameter(torch.ones(1))
        self.config = SimpleNamespace(max_position_embeddings=256)
        self.generation_config = GenerationConfig(
            max_length=20, eos_token_id=2, pad_token_id=2, do_sample=True
        )
        self.output_ids = tuple(output_ids)
        self.fail = fail
        self.calls = 0
        self.kwargs = None
        self.inference_mode = None
        self.eval_when_called = None

    def generate(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        self.inference_mode = torch.is_inference_mode_enabled()
        self.eval_when_called = not self.training
        if self.fail:
            raise self.fail
        prompt = kwargs["input_ids"]
        tail = torch.tensor([self.output_ids], dtype=prompt.dtype, device=prompt.device)
        return torch.cat([prompt, tail], dim=1)


def engine(tokenizer=None, model=None, config=None):
    tokenizer = tokenizer or FakeTokenizer()
    model = model or FakeModel()
    return ConversationEngine(model, tokenizer, config or make_config())


def card() -> dict:
    return {
        "race": {"event": "Synthetic Example"},
        "gap_ahead": {"state": "KNOWN", "seconds": Decimal("1.250")},
    }


def history() -> list[dict[str, str]]:
    return [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]


def test_native_template_order_card_current_message_and_raw_continuation():
    tokenizer = FakeTokenizer(response="\nCALL: MAYBE\nWHY: raw text  ")
    model = FakeModel()
    subject = engine(tokenizer, model)
    original_card, original_history = card(), history()
    card_before, history_before = (
        copy.deepcopy(original_card),
        copy.deepcopy(original_history),
    )

    response, trace = subject.respond_with_trace(
        original_card, original_history, "Current question"
    )

    assert response == "\nCALL: MAYBE\nWHY: raw text  "
    assert [item["role"] for item in tokenizer.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert tokenizer.messages[-1]["content"] == "Current question"
    assert (
        sum(item["content"] == "Current question" for item in tokenizer.messages) == 1
    )
    assert "Current race card (authoritative JSON)" in tokenizer.messages[0]["content"]
    assert '"seconds":1.250' in tokenizer.messages[0]["content"]
    assert "policy version 1.1" in tokenizer.messages[0]["content"]
    assert "CALL: BOX | STAY OUT | NO CALL" in tokenizer.messages[0]["content"]
    assert tokenizer.options["add_generation_prompt"] is True
    assert tokenizer.options["enable_thinking"] is False
    assert tokenizer.options["truncation"] is False
    assert tokenizer.options["tokenize"] is True
    assert tokenizer.decoded_ids == [91, 2]
    assert tokenizer.decode_options == {
        "skip_special_tokens": True,
        "clean_up_tokenization_spaces": False,
    }
    assert trace["decode"]["generated_ids_include_special_tokens"] is True
    assert model.eval_when_called and model.inference_mode
    assert model.kwargs["attention_mask"].shape == model.kwargs["input_ids"].shape
    generation = model.kwargs["generation_config"]
    assert generation.do_sample is False
    assert generation.max_new_tokens == 4
    assert generation.max_time == 5.0
    assert generation.num_beams == 1
    assert generation.num_return_sequences == 1
    assert generation.use_cache is True
    assert generation.temperature == 1.0 and generation.top_p == 1.0
    assert generation.eos_token_id == 2 and generation.pad_token_id == 2
    assert original_card == card_before and original_history == history_before
    assert trace["generation_settings"]["seed_active"] is False
    assert trace["history"]["retained_turns"] == 1


def test_default_instructions_use_exported_policy_constants():
    instructions = baseline_instructions()
    assert "SOFT 8/14; MEDIUM 12/18; HARD 18/24" in instructions
    assert "2.0 seconds" in instructions
    assert "policy version 1.1" in instructions
    assert "null as missing, never as zero" in instructions


def clock_tokenizer() -> PreTrainedTokenizerFast:
    backend = Tokenizer(
        WordLevel({"[UNK]": 0, "2026-10-19": 1, "2026-10-20": 2}, unk_token="[UNK]")
    )
    backend.pre_tokenizer = WhitespaceSplit()
    return PreTrainedTokenizerFast(
        tokenizer_object=backend,
        unk_token="[UNK]",
        chat_template=(
            "{{ strftime_now('%Y-%m-%d') }} "
            "{% for message in messages %}{{ message.role }} {{ message.content }} {% endfor %}"
            "{% if add_generation_prompt %}assistant{% endif %}"
        ),
    )


def test_template_tokens_stay_identical_across_execution_dates(monkeypatch):
    prepared = []
    for day in (19, 20):

        class WallClock:
            @classmethod
            def now(cls, current_day=day):
                return datetime(2026, 10, current_day, 12)

        monkeypatch.setattr(chat_template_utils, "datetime", WallClock)
        subject = ConversationEngine(
            FakeModel(), clock_tokenizer(), make_config(), instructions="Use the card."
        )
        prepared.append(subject.prepare(card(), history(), "Now", fixed_history=True))
    first, second = prepared
    assert torch.equal(first.input_ids, second.input_ids)
    assert first.input_ids[0, 0].item() == 1  # the configured date, including on day 20
    assert (
        first.trace["prompt_token_ids_sha256"]
        == second.trace["prompt_token_ids_sha256"]
    )
    assert (
        first.trace["chat_template_context"]
        == second.trace["chat_template_context"]
        == {"strftime_now": "2026-10-19T00:00:00+00:00"}
    )
    assert (
        first.trace["chat_template_context_sha256"]
        == second.trace["chat_template_context_sha256"]
    )


def test_template_date_override_changes_tokens_and_recorded_context():
    prepared = []
    for template_date in ("2026-10-19", "2026-10-20"):
        subject = ConversationEngine(
            FakeModel(),
            clock_tokenizer(),
            replace(make_config(), chat_template_date=template_date),
            instructions="Use the card.",
        )
        prepared.append(subject.prepare(card(), [], "Now", fixed_history=True))
    first, second = prepared
    assert first.input_ids[0, 0].item() == 1 and second.input_ids[0, 0].item() == 2
    assert (
        first.trace["prompt_messages_sha256"] == second.trace["prompt_messages_sha256"]
    )
    assert (
        first.trace["prompt_token_ids_sha256"]
        != second.trace["prompt_token_ids_sha256"]
    )
    assert (
        first.trace["chat_template_context_sha256"]
        != second.trace["chat_template_context_sha256"]
    )
    assert (
        second.trace["chat_template_context"]["strftime_now"]
        == "2026-10-20T00:00:00+00:00"
    )


@pytest.mark.parametrize("template_date", ["20261019", "2026-02-30", "today", None])
def test_template_date_rejects_invalid_or_noncanonical_values(template_date):
    with pytest.raises(ValueError, match="chat_template_date"):
        engine(config=replace(make_config(), chat_template_date=template_date))


def test_history_turn_limit_keeps_newest_complete_exchanges_and_zero_is_empty():
    turns = history() + [
        {"role": "user", "content": "Later question"},
        {"role": "assistant", "content": "Later answer"},
    ]
    latest = engine(config=make_config(turns=1)).prepare(card(), turns, "Now")
    assert latest.trace["history"]["provided_turns"] == 2
    assert latest.trace["history"]["retained"] == turns[-2:]
    assert latest.trace["history"]["removed_by_turn_limit"] == turns[:2]
    empty = engine(config=make_config(turns=0)).prepare(card(), turns, "Now")
    assert empty.trace["history"]["retained"] == []
    assert empty.trace["history"]["retained_turns"] == 0


def test_token_budget_is_exact_and_removes_oldest_whole_exchange():
    turns = history() + [
        {"role": "user", "content": "Second question"},
        {"role": "assistant", "content": "Second answer"},
    ]
    subject = engine(config=make_config(turns=2, max_context=7, max_new_tokens=2))
    prepared = subject.prepare(card(), turns, "Now")
    assert prepared.trace["input_tokens"] == 4
    assert prepared.trace["context"]["usable_input_tokens"] == 5
    assert prepared.trace["history"]["removed_for_context"] == turns[:2]
    assert prepared.trace["history"]["retained"] == turns[-2:]
    exact = engine(config=make_config(max_context=4, max_new_tokens=2)).prepare(
        card(), [], "Now"
    )
    assert (
        exact.trace["input_tokens"]
        == exact.trace["context"]["usable_input_tokens"]
        == 2
    )


def test_mandatory_prompt_overflow_and_fixed_history_overflow_are_explicit():
    subject = engine(config=make_config(max_context=3, max_new_tokens=2))
    with pytest.raises(ConversationEngineError, match="context_overflow") as error:
        subject.prepare(card(), [], "Now")
    assert error.value.code == "context_overflow"
    assert (
        error.value.trace["context_failure"] == "mandatory_prompt_exceeds_input_budget"
    )
    assert error.value.trace["input_tokens"] == 2
    assert error.value.trace["history"]["retained"] == []
    assert error.value.trace["generation_attempted"] is False
    fixed = engine(config=make_config(turns=0, max_context=5, max_new_tokens=2))
    with pytest.raises(ConversationEngineError) as fixed_error:
        fixed.prepare(card(), history(), "Now", fixed_history=True)
    assert fixed_error.value.code == "history_limit_exceeded"
    assert fixed_error.value.trace["history"]["provided_turns"] == 1
    assert fixed_error.value.trace["history"]["retained"] == []
    assert fixed_error.value.trace["history"]["removed_by_turn_limit"] == history()


def test_fixed_history_never_silently_truncates_after_input_hash():
    tokenizer = FakeTokenizer(token_count=lambda messages: len(messages))
    subject = engine(
        tokenizer=tokenizer,
        config=make_config(turns=2, max_context=7, max_new_tokens=2),
    )
    with pytest.raises(ConversationEngineError) as error:
        subject.prepare(card(), history() + history(), "Now", fixed_history=True)
    assert error.value.code == "context_overflow"
    assert error.value.trace["fixed_history"] is True


def test_preflight_rejects_candidate_specific_history_reduction():
    tokenizer = FakeTokenizer(
        token_count=lambda messages: (
            len(messages)
            + (2 if "long prompt wording" in messages[0]["content"] else 0)
        )
    )
    subject = engine(
        tokenizer=tokenizer,
        config=make_config(turns=1, max_context=7, max_new_tokens=2),
    )
    report = subject.preflight_candidates(
        {"short": "short wording", "long": "long prompt wording"},
        card(),
        history(),
        "Now",
        fixed_history=False,
    )
    assert report["ready"] is False
    assert report["common_unreduced_history"] is False
    assert "common reduced ledger" in report["action"]


def test_required_referent_cannot_be_removed_to_make_room():
    tokenizer = FakeTokenizer(
        token_count=lambda messages: (
            len(messages)
            + (2 if "long prompt wording" in messages[0]["content"] else 0)
        )
    )
    subject = engine(
        tokenizer=tokenizer,
        config=make_config(turns=1, max_context=7, max_new_tokens=2),
    )
    with pytest.raises(ConversationEngineError) as error:
        subject.prepare(
            card(),
            history(),
            "Now",
            required_history_turns=1,
            instructions="long prompt wording",
        )
    assert error.value.code == "required_history_dropped"


@pytest.mark.parametrize(
    "raw", ["", "CALL: MAYBE\nWHY: broken", "extra\nCALL: BOX\nWHY: x"]
)
def test_empty_and_malformed_outputs_are_returned_unchanged(raw: str):
    tokenizer = FakeTokenizer(response=raw)
    subject = engine(tokenizer=tokenizer)
    response, trace = subject.respond_with_trace(card(), [], "Now")
    assert response == raw == trace["raw_response"]


def test_max_new_tokens_cutoff_is_retained_and_diagnosed():
    subject = engine(
        tokenizer=FakeTokenizer(response="unfinished"),
        model=FakeModel(output_ids=(91, 92, 93, 94)),
        config=make_config(max_new_tokens=4),
    )
    response, trace = subject.respond_with_trace(card(), [], "Now")
    assert response == "unfinished"
    assert trace["generated_token_ids"] == [91, 92, 93, 94]
    assert trace["stop_condition"] == "max_new_tokens"
    assert trace["possibly_truncated"] is True


def test_generation_failure_propagates_and_never_becomes_no_call():
    subject = engine(model=FakeModel(fail=RuntimeError("backend offline")))
    with pytest.raises(ConversationEngineError) as error:
        subject.respond(card(), [], "Now")
    assert error.value.code == "generation_error"
    assert "backend offline" in error.value.message
    assert error.value.partial_response is None
    assert error.value.partial_response != "CALL: NO CALL"


@pytest.mark.parametrize("failed_transfer", [1, 2])
def test_device_transfer_failure_keeps_original_error_and_prepared_trace(
    monkeypatch, failed_transfer
):
    subject = engine()
    original_to = torch.Tensor.to
    backend_error = RuntimeError("MPS allocation failed")
    transfers = 0

    def transfer(tensor, *args, **kwargs):
        nonlocal transfers
        transfers += 1
        if transfers == failed_transfer:
            raise backend_error
        return original_to(tensor, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "to", transfer)
    with pytest.raises(ConversationEngineError) as error:
        subject.respond_with_trace(card(), history(), "Now")
    assert error.value.code == "device_transfer_error"
    assert error.value.__cause__ is backend_error
    assert error.value.trace["history"]["retained"] == history()
    assert error.value.trace["input_tokens"] == 4
    assert error.value.trace["generation_error"] == {
        "type": "RuntimeError",
        "stage": "device_transfer",
    }
    assert error.value.trace["generation_settings"]["max_new_tokens"] == 4
    assert error.value.partial_response is None
    assert subject.model.calls == 0


def test_eval_failure_is_wrapped_before_generation(monkeypatch):
    subject = engine()
    backend_error = RuntimeError("could not enter evaluation mode")

    def fail_eval():
        raise backend_error

    monkeypatch.setattr(subject.model, "eval", fail_eval)
    with pytest.raises(ConversationEngineError) as error:
        subject.respond_with_trace(card(), [], "Now")
    assert error.value.code == "model_eval_error"
    assert error.value.__cause__ is backend_error
    assert error.value.trace["prompt_token_ids_sha256"]
    assert error.value.trace["generation_error"]["stage"] == "model_eval"
    assert subject.model.calls == 0


def test_smoke_saves_and_pairs_device_error_after_a_success(monkeypatch, tmp_path):
    config_path = Path("configs/conversation-smoke.toml")
    subject = engine(config=smoke_conversation.load_config(config_path))
    monkeypatch.setattr(
        smoke_conversation, "load_conversation_engine", lambda config: subject
    )
    original_to = torch.Tensor.to
    transfers = 0

    def transfer(tensor, *args, **kwargs):
        nonlocal transfers
        transfers += 1
        if transfers == 3:  # the second case's first input transfer
            raise RuntimeError("MPS allocation failed")
        return original_to(tensor, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "to", transfer)
    run = smoke_conversation.execute(config_path, "device-error-regression", tmp_path)
    outputs = [
        json.loads(line) for line in (run / "outputs.jsonl").read_text().splitlines()
    ]
    attempts = [
        json.loads(line) for line in (run / "attempts.jsonl").read_text().splitlines()
    ]
    metrics = json.loads((run / "metrics.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    assert outputs[0]["status"] == "ok"
    assert outputs[1]["status"] == "generation_error"
    assert outputs[1]["error"]["code"] == "device_transfer_error"
    assert outputs[1]["raw_response"] is None
    assert attempts[1]["trace"]["generation_error"]["stage"] == "device_transfer"
    assert attempts[1]["retained_history"] == attempts[1]["requested_history"]
    assert metrics["successful_generation_calls"] == subject.model.calls == 4
    assert metrics["generation_errors"] == 1 and metrics["paired_outputs"] == 5
    metadata = manifest["extra"]["conversation_engine"]
    assert metadata["chat_template_context"] == subject.template_context()
    assert (
        metadata["chat_template_context_sha256"]
        == attempts[0]["trace"]["chat_template_context_sha256"]
    )


def test_shared_engine_is_callable_by_demo_and_has_no_hidden_session_memory():
    tokenizer = FakeTokenizer()
    model = FakeModel()
    subject = engine(tokenizer, model)
    updated, error = send(card(), [], "Box?", subject.respond, turns=3)
    assert error is None
    assert len(updated) == 2 and updated[0]["content"] == "Box?"
    subject.respond({"race": {"event": "Another synthetic card"}}, [], "Independent")
    assert model.calls == 2
    assert all(item["content"] != "Box?" for item in tokenizer.messages)


def test_output_envelope_pairs_with_the_evaluator_without_changing_raw_response():
    fixture = json.loads(
        Path("reference/evaluation-fixtures.json").read_text(encoding="utf-8"),
        parse_float=Decimal,
    )
    case = next(
        row for row in fixture["cases"] if row["case_id"] == "syn:case:equality"
    )
    card_row = next(
        row for row in fixture["cards"] if row["card_id"] == case["card_id"]
    )
    prepared = prepare_case(case, card_row["card"], 3)
    validate_cases([prepared])
    raw = "\nCALL: BOX\nWHY: preserves leading whitespace  "
    cases_sha = "b" * 64
    output = {
        "response_id": "response:test:equality",
        "case_id": prepared["case_id"],
        "version_id": "baseline-test",
        "run_id": "2026-10-19_test",
        "config_sha256": "a" * 64,
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "input_sha256": prepared["input_sha256"],
        "cases_sha256": cases_sha,
        "status": "ok",
        "raw_response": raw,
        "error": None,
    }
    failure = {
        **output,
        "response_id": "response:test:equality-failure",
        "version_id": "failed-test",
        "run_id": "2026-10-19_failed_test",
        "status": "generation_error",
        "raw_response": None,
        "error": {"code": "generation_error", "message": "backend unavailable"},
    }
    paired = pair_outputs(
        [prepared], [output, failure], ["baseline-test", "failed-test"], cases_sha
    )
    assert paired["baseline-test"][prepared["case_id"]]["raw_response"] == raw
    assert paired["failed-test"][prepared["case_id"]]["status"] == "generation_error"
    assert paired["failed-test"][prepared["case_id"]]["strict_format_valid"] is False
