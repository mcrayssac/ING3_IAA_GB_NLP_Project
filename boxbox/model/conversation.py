"""Shared, stateless conversation preparation and controlled generation."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import torch
from transformers import GenerationConfig

from boxbox.config import RunConfig
from boxbox.model.loading import cap_mps_memory, get_device, load_model, model_dtype
from boxbox.rules import (
    AHEAD_OPPORTUNITY_SECONDS,
    POLICY_VERSION,
    REJOIN_MARGIN_SECONDS,
    TYRE_LIMITS,
)

SYSTEM_INSTRUCTIONS = """You are a baseline pit-strategy conversation assistant for pit strategists and paddock team members reviewing completed historical Formula 1 races on a dry track. This is a policy-training and debriefing aid, not a live-race or real-world strategy optimizer.

Use the current race card as the sole authority for race measurements and current facts. The card is authoritative over any contradictory number or claim in the user's message or earlier conversation. Never treat an earlier assistant answer as a measurement. You may explain the current card, apply the policy thresholds, and state arithmetic explicitly derived from card values. Policy compliance does not prove that a stop is strategically optimal in a real race.

Apply BoxBox policy version {policy_version} in its documented order. First require a supported, completed historical race; a valid lap and lap-minus-one observation cutoff; dry surface; green flag; supported compound; and valid tyre age. Supported dry compounds have these (opportunity age, always-opportunity age) lap limits: {tyre_limits}. Below the first age, STAY OUT. At or above the second age there is always a pit opportunity, regardless of the gap ahead. Between those ages, a known gap ahead at or below {ahead} seconds is an opportunity; a larger gap or no car ahead means STAY OUT, and an unknown gap means NO CALL. Once an opportunity exists, no car behind means BOX. A known car behind means BOX only when its gap covers the card's valid pit-loss estimate plus {margin} seconds; equality is sufficient. An unknown required gap, missing required pit loss, or invalid cutoff means NO CALL. Do not require a field that the current ordered branch does not use.

Treat null as missing, never as zero. UNKNOWN means unavailable; a well-formed NONE means no car; a known zero is a measured zero. A malformed NONE claim means NO CALL. Do not conflate these states. Missing information requires NO CALL only when the ordered decision branch needs it. Missing display-only information and fields irrelevant to the current branch do not change the call. Do not invent values or derive them from the user's assertions.

Answer follow-up questions using the current card and supplied same-card history. Correct prior assistant mistakes and explicitly identify contradictory user assertions using the card. If a request is outside this tool's scope (including live-race advice, forecasts, wet or neutralised-race strategy, betting, or claims of real-world optimality), refuse briefly with NO CALL while still following the required format. Never invent radio messages or facts.

Return exactly two lines, with one label only and one English sentence grounded in the current card or its stated limits:
CALL: BOX | STAY OUT | NO CALL
WHY: <one English sentence grounded in the current card or its stated limits>"""

TEMPLATE_OPTIONS = {
    "add_generation_prompt": True,
    "enable_thinking": False,
    "padding": False,
    "truncation": False,
}
TEMPLATE_OPTION_NOTE = (
    "SmolLM3 native enable_thinking=False; the tokenizer template emits its "
    "native /no_think metadata and empty reasoning prefix. No generated text is removed."
)


class ConversationEngineError(RuntimeError):
    """A model-pipeline failure that must not be represented as a model answer."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        trace: dict[str, Any] | None = None,
        partial_response: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.trace = trace or {}
        self.partial_response = partial_response
        super().__init__(f"{code}: {message}")

    def as_record(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class PreparedConversation:
    """Rendered chat-template inputs and the messages actually supplied."""

    input_ids: torch.Tensor
    attention_mask: torch.Tensor
    messages: tuple[dict[str, str], ...]
    trace: dict[str, Any]


def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _json_text(value: Any) -> str:
    """Serialize JSON values while keeping Decimal values numeric and exact."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("race-card object keys must be strings")
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False) + ":" + _json_text(value[key])
                for key in sorted(value)
            )
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_json_text(item) for item in value) + "]"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("race card contains a non-finite Decimal")
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("race card contains a non-finite float")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _prompt(instructions: str, card: dict[str, Any]) -> str:
    return (
        instructions
        + "\n\nCurrent race card (authoritative JSON):\n"
        + _json_text(card)
    )


def _validate_history(history: Any) -> list[dict[str, str]]:
    if not isinstance(history, list) or len(history) % 2:
        raise ConversationEngineError(
            "invalid_history", "history must contain complete user/assistant exchanges"
        )
    copied: list[dict[str, str]] = []
    for index, item in enumerate(history):
        expected = "user" if index % 2 == 0 else "assistant"
        if (
            not isinstance(item, dict)
            or set(item) != {"role", "content"}
            or item["role"] != expected
            or not isinstance(item["content"], str)
        ):
            raise ConversationEngineError(
                "invalid_history",
                "history must be chronological same-card role/content exchanges",
            )
        copied.append({"role": expected, "content": item["content"]})
    return copied


def _limit_value(value: Any) -> int | None:
    return value if type(value) is int and 0 < value < 10**9 else None


@contextmanager
def _seeded_rng(device: torch.device, seed: int, active: bool):
    """Seed sampling locally and restore device RNG state after the call."""
    if not active:
        yield
        return
    cuda_devices = []
    if device.type == "cuda":
        cuda_devices = [
            device.index if device.index is not None else torch.cuda.current_device()
        ]
    mps_state = torch.mps.get_rng_state() if device.type == "mps" else None
    try:
        with torch.random.fork_rng(devices=cuda_devices):
            torch.manual_seed(seed)
            if device.type == "cuda":
                torch.cuda.manual_seed(seed)
            elif device.type == "mps":
                torch.mps.manual_seed(seed)
            yield
    finally:
        if mps_state is not None:
            torch.mps.set_rng_state(mps_state)


class ConversationEngine:
    """One loaded model/tokenizer pair; no cross-call or cross-card memory."""

    def __init__(
        self,
        model: Any,
        tokenizer: Any,
        config: RunConfig | None = None,
        *,
        instructions: str | None = None,
        device: torch.device | str | None = None,
        dtype: torch.dtype | str | None = None,
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.config = config or RunConfig()
        self.instructions = (
            instructions if instructions is not None else baseline_instructions()
        )
        self.prompt_variant = self.config.prompt_variant
        self.device = torch.device(device or getattr(model, "device", "cpu"))
        self.attn_implementation: str | None = None
        first_parameter = next(iter(model.parameters()), None)
        self.dtype = str(dtype or getattr(first_parameter, "dtype", "unknown"))
        self._generation_lock = threading.Lock()
        try:
            template_date = date.fromisoformat(self.config.chat_template_date)
            if template_date.isoformat() != self.config.chat_template_date:
                raise ValueError("noncanonical date")
        except (TypeError, ValueError) as error:
            raise ValueError(
                "chat_template_date must be a valid YYYY-MM-DD string"
            ) from error
        self._template_datetime = datetime(
            template_date.year,
            template_date.month,
            template_date.day,
            tzinfo=UTC,
        )
        if not isinstance(self.instructions, str) or not self.instructions:
            raise ValueError("instructions must be a nonempty string")
        if type(self.config.history_turns) is not int or self.config.history_turns < 0:
            raise ValueError("history_turns must be a nonnegative integer")
        if (
            type(self.config.decoding.max_new_tokens) is not int
            or self.config.decoding.max_new_tokens < 1
        ):
            raise ValueError("max_new_tokens must be a positive integer")
        if (
            type(self.config.decoding.max_context_tokens) is not int
            or self.config.decoding.max_context_tokens <= 0
        ):
            raise ValueError("max_context_tokens must be a positive integer")
        if (
            not math.isfinite(self.config.decoding.max_generation_seconds)
            or self.config.decoding.max_generation_seconds <= 0
        ):
            raise ValueError("max_generation_seconds must be positive")
        if (
            not math.isfinite(self.config.decoding.temperature)
            or self.config.decoding.temperature <= 0
            or not math.isfinite(self.config.decoding.top_p)
            or not 0 < self.config.decoding.top_p <= 1
        ):
            raise ValueError("temperature must be positive and top_p must be in (0, 1]")

    def _model_context_limits(self) -> dict[str, int | None]:
        model_config = getattr(self.model, "config", None)
        tokenizer_limit = _limit_value(
            getattr(self.tokenizer, "model_max_length", None)
        )
        model_limits = [
            _limit_value(getattr(model_config, name, None))
            for name in (
                "max_position_embeddings",
                "max_sequence_length",
                "n_positions",
            )
        ]
        model_limits = [value for value in model_limits if value is not None]
        hard_limit = min(
            model_limits + ([tokenizer_limit] if tokenizer_limit else []), default=None
        )
        configured = self.config.decoding.max_context_tokens
        usable = min(configured, hard_limit) if hard_limit is not None else configured
        return {
            "configured_max_context_tokens": configured,
            "model_position_limit": min(model_limits, default=None),
            "tokenizer_model_max_length": tokenizer_limit,
            "model_tokenizer_context_limit": hard_limit,
            "usable_context_tokens": usable,
            "reserved_new_tokens": self.config.decoding.max_new_tokens,
            "usable_input_tokens": usable - self.config.decoding.max_new_tokens,
        }

    def _messages(
        self,
        card: dict[str, Any],
        history: list[dict[str, str]],
        message: str,
        instructions: str,
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": _prompt(instructions, card)},
            *copy.deepcopy(history),
            {"role": "user", "content": message},
        ]

    def template_context(self) -> dict[str, str]:
        """Return the fixed clock passed to the native template renderer."""
        return {"strftime_now": self._template_datetime.isoformat()}

    def _template(
        self, messages: list[dict[str, str]]
    ) -> tuple[torch.Tensor, torch.Tensor]:
        try:
            rendered = self.tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                strftime_now=self._template_datetime.strftime,
                **TEMPLATE_OPTIONS,
            )
        except Exception as error:
            raise ConversationEngineError(
                "chat_template_error", f"native tokenizer chat template failed: {error}"
            ) from error
        if "input_ids" not in rendered:
            raise ConversationEngineError(
                "chat_template_error", "native chat template returned no input_ids"
            )
        input_ids = rendered["input_ids"]
        attention_mask = rendered.get("attention_mask")
        if not isinstance(input_ids, torch.Tensor):
            input_ids = torch.as_tensor(input_ids, dtype=torch.long)
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids)
        elif not isinstance(attention_mask, torch.Tensor):
            attention_mask = torch.as_tensor(attention_mask, dtype=torch.long)
        if input_ids.ndim == 1:
            input_ids = input_ids.unsqueeze(0)
        if attention_mask.ndim == 1:
            attention_mask = attention_mask.unsqueeze(0)
        if input_ids.ndim != 2 or attention_mask.shape != input_ids.shape:
            raise ConversationEngineError(
                "chat_template_error",
                "native chat template returned incompatible tensor shapes",
            )
        return input_ids, attention_mask

    def prepare(
        self,
        card: dict[str, Any],
        history: list[dict[str, str]],
        message: str,
        *,
        fixed_history: bool = False,
        required_history_turns: int | None = None,
        instructions: str | None = None,
    ) -> PreparedConversation:
        """Prepare exact template tokens; evaluation callers can forbid reduction."""
        if not isinstance(card, dict):
            raise ConversationEngineError("invalid_card", "card must be one object")
        if not isinstance(message, str):
            raise ConversationEngineError("invalid_message", "message must be text")
        supplied = _validate_history(copy.deepcopy(history))
        selected_instructions = (
            instructions if instructions is not None else self.instructions
        )
        if not isinstance(selected_instructions, str) or not selected_instructions:
            raise ConversationEngineError(
                "invalid_instructions", "instructions must be nonempty text"
            )
        if required_history_turns is not None and (
            type(required_history_turns) is not int or required_history_turns < 0
        ):
            raise ConversationEngineError(
                "invalid_history_requirement", "required turn count must be nonnegative"
            )
        limit = self._model_context_limits()
        input_limit = limit["usable_input_tokens"]
        requested_turns = len(supplied) // 2
        turns_allowed = min(requested_turns, self.config.history_turns)
        turn_limited = supplied[-2 * turns_allowed :] if turns_allowed else []
        removed_by_turn_limit = supplied[: len(supplied) - len(turn_limited)]

        def failed_history_trace(
            retained_history: list[dict[str, str]],
            removed_context: list[dict[str, str]],
            *,
            reason: str,
            messages: list[dict[str, str]] | None = None,
            input_ids: torch.Tensor | None = None,
            proposed_removal: list[dict[str, str]] | None = None,
        ) -> dict[str, Any]:
            result: dict[str, Any] = {
                **limit,
                "fixed_history": fixed_history,
                "generation_attempted": False,
                "context_failure": reason,
                "chat_template_context": self.template_context(),
                "history": {
                    "mode": "fixed" if fixed_history else "interactive",
                    "provided_turns": requested_turns,
                    "turn_limit": self.config.history_turns,
                    "after_turn_limit": turns_allowed,
                    "removed_by_turn_limit": copy.deepcopy(removed_by_turn_limit),
                    "removed_for_context": copy.deepcopy(removed_context),
                    "retained": copy.deepcopy(retained_history),
                    "retained_turns": len(retained_history) // 2,
                    "required_turns": required_history_turns,
                    "was_reduced": bool(removed_by_turn_limit or removed_context),
                    "reduction_refused": copy.deepcopy(proposed_removal or []),
                },
            }
            if messages is not None:
                result["messages"] = copy.deepcopy(messages)
                result["prompt_messages_sha256"] = _sha256(_json_text(messages))
            if input_ids is not None:
                result["input_tokens"] = int(input_ids.shape[-1])
                result["prompt_token_ids_sha256"] = _sha256(
                    input_ids.detach().cpu().numpy().tobytes()
                )
            return result

        if input_limit < 1:
            raise ConversationEngineError(
                "context_configuration_error",
                "generation reserve leaves no room for an input token",
                trace=failed_history_trace(
                    turn_limited, [], reason="generation_reserve_exhausts_context"
                ),
            )
        if fixed_history and requested_turns > self.config.history_turns:
            raise ConversationEngineError(
                "history_limit_exceeded",
                "fixed evaluation history exceeds RunConfig.history_turns; prepare a common ledger first",
                trace=failed_history_trace(
                    turn_limited, [], reason="fixed_history_exceeds_turn_limit"
                ),
            )
        if fixed_history and removed_by_turn_limit:
            raise ConversationEngineError(
                "history_limit_exceeded",
                "fixed evaluation history would be reduced by RunConfig.history_turns",
                trace=failed_history_trace(
                    turn_limited, [], reason="fixed_history_would_be_reduced"
                ),
            )
        if (
            required_history_turns is not None
            and turns_allowed < required_history_turns
        ):
            raise ConversationEngineError(
                "required_history_dropped",
                "RunConfig.history_turns is below the declared required history",
                trace=failed_history_trace(
                    turn_limited, [], reason="required_history_exceeds_turn_limit"
                ),
            )
        retained = copy.deepcopy(turn_limited)
        removed_for_context: list[dict[str, str]] = []
        template_messages: list[dict[str, str]] = []
        input_ids: torch.Tensor | None = None
        attention_mask: torch.Tensor | None = None
        while True:
            template_messages = self._messages(
                card, retained, message, selected_instructions
            )
            input_ids, attention_mask = self._template(template_messages)
            count = int(input_ids.shape[-1])
            if count <= input_limit:
                break
            if not retained or fixed_history:
                raise ConversationEngineError(
                    "context_overflow",
                    f"mandatory prompt and fixed history use {count} tokens; input budget is {input_limit}",
                    trace=failed_history_trace(
                        retained,
                        removed_for_context,
                        reason="mandatory_prompt_exceeds_input_budget",
                        messages=template_messages,
                        input_ids=input_ids,
                    ),
                )
            pair_to_remove = retained[:2]
            candidate_retained = retained[2:]
            if (
                required_history_turns is not None
                and len(candidate_retained) // 2 < required_history_turns
            ):
                raise ConversationEngineError(
                    "required_history_dropped",
                    "context budget would remove a declared required history turn",
                    trace=failed_history_trace(
                        retained,
                        removed_for_context,
                        reason="context_reduction_would_drop_required_history",
                        messages=template_messages,
                        input_ids=input_ids,
                        proposed_removal=pair_to_remove,
                    ),
                )
            removed_for_context.extend(pair_to_remove)
            retained = candidate_retained
        assert input_ids is not None and attention_mask is not None
        prompt_json = _json_text(template_messages)
        template = getattr(self.tokenizer, "chat_template", None)
        template_bytes = (
            template.encode("utf-8")
            if isinstance(template, str)
            else _json_text(template).encode("utf-8")
        )
        trace = {
            "prompt_variant": self.prompt_variant,
            "instructions": selected_instructions,
            "instructions_sha256": _sha256(selected_instructions),
            "chat_template": template,
            "chat_template_sha256": _sha256(template_bytes),
            "chat_template_context": self.template_context(),
            "chat_template_context_sha256": _sha256(
                _json_text(self.template_context())
            ),
            "template_options": TEMPLATE_OPTIONS.copy(),
            "template_option_note": TEMPLATE_OPTION_NOTE,
            "messages": copy.deepcopy(template_messages),
            "prompt_messages_sha256": _sha256(prompt_json),
            "prompt_token_ids_sha256": _sha256(
                input_ids.detach().cpu().numpy().tobytes()
            ),
            "input_tokens": int(input_ids.shape[-1]),
            "attention_mask_tokens": int(attention_mask.sum().item()),
            "context": limit,
            "history": {
                "mode": "fixed" if fixed_history else "interactive",
                "provided_turns": requested_turns,
                "turn_limit": self.config.history_turns,
                "after_turn_limit": turns_allowed,
                "removed_by_turn_limit": removed_by_turn_limit,
                "removed_for_context": removed_for_context,
                "retained": copy.deepcopy(retained),
                "retained_turns": len(retained) // 2,
                "required_turns": required_history_turns,
                "was_reduced": bool(removed_by_turn_limit or removed_for_context),
            },
        }
        return PreparedConversation(
            input_ids=input_ids,
            attention_mask=attention_mask,
            messages=tuple(copy.deepcopy(template_messages)),
            trace=trace,
        )

    def training_ids(
        self,
        card: dict[str, Any],
        history: list[dict[str, str]],
        message: str,
        answer: str,
    ) -> tuple[list[int], list[int]]:
        """Prompt and completion token ids for training, rendered like inference.

        The prompt is exactly what `prepare` sends to the model with a fixed history.
        The completion is the answer and the end-of-turn token that stops generation.
        """
        prompt = (
            self.prepare(card, history, message, fixed_history=True)
            .input_ids[0]
            .tolist()
        )
        messages = [
            *self._messages(card, history, message, self.instructions),
            {"role": "assistant", "content": answer},
        ]
        options = {**TEMPLATE_OPTIONS, "add_generation_prompt": False}
        full = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            return_dict=True,
            strftime_now=self._template_datetime.strftime,
            **options,
        )["input_ids"]
        if full[: len(prompt)] != prompt:
            raise ConversationEngineError(
                "training_prompt_mismatch",
                "the inference prompt is not a prefix of the answer",
            )
        completion = full[len(prompt) :]
        end = self.tokenizer.eos_token_id
        if end not in completion:
            raise ConversationEngineError(
                "training_answer_unterminated", "the answer has no end-of-turn token"
            )
        return prompt, completion[: completion.index(end) + 1]  # nothing after the stop

    def preflight_candidates(
        self,
        candidates: dict[str, str],
        card: dict[str, Any],
        history: list[dict[str, str]],
        message: str,
        *,
        required_history_turns: int | None = None,
        fixed_history: bool = True,
    ) -> dict[str, Any]:
        """Check prompt variants before generation and reject candidate-specific context."""
        if not candidates or any(
            not name or not text for name, text in candidates.items()
        ):
            raise ConversationEngineError(
                "invalid_candidates", "candidate prompts need names and text"
            )
        prepared: dict[str, dict[str, Any]] = {}
        failures: dict[str, dict[str, str]] = {}
        for name, text in candidates.items():
            try:
                item = self.prepare(
                    card,
                    history,
                    message,
                    fixed_history=fixed_history,
                    required_history_turns=required_history_turns,
                    instructions=text,
                )
                prepared[name] = {
                    "input_tokens": item.trace["input_tokens"],
                    "input_token_ids_sha256": item.trace["prompt_token_ids_sha256"],
                    "retained_history": item.trace["history"]["retained"],
                    "history_reduced": item.trace["history"]["was_reduced"],
                }
            except ConversationEngineError as error:
                failures[name] = {"code": error.code, "message": error.message}
        distinct_histories = {
            _json_text(value["retained_history"]) for value in prepared.values()
        }
        common_history = len(distinct_histories) <= 1 and not any(
            value["history_reduced"] for value in prepared.values()
        )
        return {
            "ready": not failures and common_history,
            "fixed_history": fixed_history,
            "candidates": prepared,
            "failures": failures,
            "common_unreduced_history": common_history,
            "action": (
                "Use the same supplied input ledger for every candidate."
                if not failures and common_history
                else "Prepare one common reduced ledger and re-hash it before generation, or reject this candidate set."
            ),
        }

    def generation_settings(self) -> dict[str, Any]:
        """Return the model's full loaded generation config plus explicit overrides."""
        config = self._generation_config()
        settings = config.to_dict()
        settings["seed"] = self.config.seed
        settings["seed_active"] = bool(self.config.decoding.do_sample)
        settings["explicit_overrides"] = {
            "do_sample": self.config.decoding.do_sample,
            "temperature": self.config.decoding.temperature,
            "top_p": self.config.decoding.top_p,
            "max_new_tokens": self.config.decoding.max_new_tokens,
            "max_time": self.config.decoding.max_generation_seconds,
            "num_beams": 1,
            "num_return_sequences": 1,
            "use_cache": True,
        }
        settings["tokenizer_eos_token_id"] = getattr(
            self.tokenizer, "eos_token_id", None
        )
        settings["tokenizer_pad_token_id"] = getattr(
            self.tokenizer, "pad_token_id", None
        )
        return settings

    def _generation_config(self) -> GenerationConfig:
        source = getattr(self.model, "generation_config", None)
        if source is None:
            raise ConversationEngineError(
                "generation_configuration_error", "model has no generation_config"
            )
        config = copy.deepcopy(source)
        overrides = {
            "do_sample": self.config.decoding.do_sample,
            "temperature": self.config.decoding.temperature,
            "top_p": self.config.decoding.top_p,
            "max_new_tokens": self.config.decoding.max_new_tokens,
            "max_time": self.config.decoding.max_generation_seconds,
            "num_beams": 1,
            "num_return_sequences": 1,
            "use_cache": True,
        }
        for key, value in overrides.items():
            setattr(config, key, value)
        return config

    def respond(
        self, card: dict[str, Any], history: list[dict[str, str]], message: str
    ) -> str:
        """Drop-in app/evaluator callable: return exactly decoded continuation text."""
        response, _trace = self.respond_with_trace(card, history, message)
        return response

    def __call__(
        self, card: dict[str, Any], history: list[dict[str, str]], message: str
    ) -> str:
        return self.respond(card, history, message)

    def respond_with_trace(
        self,
        card: dict[str, Any],
        history: list[dict[str, str]],
        message: str,
        *,
        fixed_history: bool = False,
        required_history_turns: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        prepared = self.prepare(
            card,
            history,
            message,
            fixed_history=fixed_history,
            required_history_turns=required_history_turns,
        )
        trace = copy.deepcopy(prepared.trace)
        try:
            generation_settings = self.generation_settings()
        except ConversationEngineError as error:
            error.trace = trace
            raise
        stage = "device_transfer"
        try:
            input_ids = prepared.input_ids.to(self.device)
            attention_mask = prepared.attention_mask.to(self.device)
            stage = "model_eval"
            self.model.eval()
            started = time.perf_counter()
            stage = "generation"
            with (
                self._generation_lock,
                torch.inference_mode(),
                _seeded_rng(
                    self.device, self.config.seed, self.config.decoding.do_sample
                ),
            ):
                generated = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    generation_config=self._generation_config(),
                )
            if hasattr(self.device, "type"):
                from boxbox.model.loading import synchronize

                stage = "device_synchronization"
                synchronize(self.device)
            duration = time.perf_counter() - started
            stage = "output_validation"
            sequences = getattr(generated, "sequences", generated)
            if (
                not isinstance(sequences, torch.Tensor)
                or sequences.ndim != 2
                or sequences.shape[0] != 1
                or sequences.shape[-1] < prepared.input_ids.shape[-1]
            ):
                raise ConversationEngineError(
                    "invalid_generation_output",
                    "generate returned an invalid single-sequence token result",
                    trace=trace,
                )
            if not torch.equal(
                sequences[0, : prepared.input_ids.shape[-1]].detach().cpu(),
                prepared.input_ids[0].detach().cpu(),
            ):
                raise ConversationEngineError(
                    "invalid_generation_output",
                    "generate changed the prepared input prefix",
                    trace=trace,
                )
            generated_ids = sequences[0, prepared.input_ids.shape[-1] :].detach().cpu()
            stage = "decoding"
            raw = self.tokenizer.decode(
                generated_ids.tolist(),
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            eos = generation_settings.get("eos_token_id")
            eos_ids = [eos] if isinstance(eos, int) else eos or []
            ended_eos = (
                bool(generated_ids.numel()) and int(generated_ids[-1]) in eos_ids
            )
            hit_token_limit = (
                int(generated_ids.numel()) >= self.config.decoding.max_new_tokens
                and not ended_eos
            )
            time_reached = (
                duration >= self.config.decoding.max_generation_seconds
                and not ended_eos
            )
            stop = (
                "eos_token"
                if ended_eos
                else "max_new_tokens"
                if hit_token_limit
                else "cooperative_max_time"
                if time_reached
                else "model_stop"
            )
            trace.update(
                {
                    "generation_settings": generation_settings,
                    "generated_token_ids": generated_ids.tolist(),
                    "generated_tokens": int(generated_ids.numel()),
                    "raw_response": raw,
                    "duration_seconds": duration,
                    "stop_condition": stop,
                    "possibly_truncated": hit_token_limit or time_reached,
                    "decode": {
                        "skip_special_tokens": True,
                        "clean_up_tokenization_spaces": False,
                        "text_is_unmodified_continuation": True,
                        "generated_ids_include_special_tokens": True,
                    },
                }
            )
            return raw, trace
        except ConversationEngineError:
            raise
        except Exception as error:
            trace["generation_settings"] = generation_settings
            trace["generation_error"] = {"type": type(error).__name__, "stage": stage}
            code = {
                "device_transfer": "device_transfer_error",
                "model_eval": "model_eval_error",
                "generation": "generation_error",
                "device_synchronization": "device_synchronization_error",
                "output_validation": "invalid_generation_output",
                "decoding": "continuation_decode_error",
            }.get(stage, "conversation_pipeline_error")
            raise ConversationEngineError(
                code, f"{stage} failed: {error}", trace=trace
            ) from error


def load_conversation_engine(
    config: RunConfig | None = None,
    *,
    device: torch.device | None = None,
    attn_implementation: str | None = None,
    instructions: str | None = None,
    adapter_dir: Path | None = None,
) -> ConversationEngine:
    """Load the pinned base model once using task 1.5 device and dtype choices.

    With `adapter_dir`, the saved LoRA adapter is loaded on top; `config.adapter` must
    then name it ("A" or "B"), and without it the config must say "none".
    """
    config = config or RunConfig()
    if (config.adapter == "none") != (adapter_dir is None):
        raise ConversationEngineError(
            "adapter_load_not_supported",
            "adapter='none' loads the base model only; adapter A or B needs its adapter_dir",
        )
    device = device or get_device()
    if device.type == "mps":
        if not math.isfinite(config.mps_memory_cap_gb) or config.mps_memory_cap_gb <= 0:
            raise ConversationEngineError(
                "device_configuration_error", "mps_memory_cap_gb must be positive"
            )
        try:
            cap_mps_memory(config.mps_memory_cap_gb)
        except Exception as error:
            raise ConversationEngineError(
                "device_configuration_error", f"could not set MPS memory cap: {error}"
            ) from error
    try:
        model, tokenizer = load_model(config, device, attn_implementation)
    except Exception as error:
        raise ConversationEngineError(
            "model_load_error",
            f"could not load {config.model_id}@{config.model_revision}: {error}",
        ) from error
    if adapter_dir is not None:
        from peft import PeftModel

        try:
            model = PeftModel.from_pretrained(model, adapter_dir).to(device)
        except Exception as error:
            raise ConversationEngineError(
                "adapter_load_error",
                f"could not load the adapter in {adapter_dir}: {error}",
            ) from error
    model.eval()
    engine = ConversationEngine(
        model,
        tokenizer,
        config,
        instructions=instructions,
        device=device,
        dtype=model_dtype(device),
    )
    engine.attn_implementation = attn_implementation
    return engine


def baseline_instructions() -> str:
    """Render the initial configurable formulation from the policy's exported constants."""
    limits = "; ".join(
        f"{compound} {window[0]}/{window[1]}"
        for compound, window in TYRE_LIMITS.items()
    )
    return SYSTEM_INSTRUCTIONS.format(
        policy_version=POLICY_VERSION,
        tyre_limits=limits,
        ahead=AHEAD_OPPORTUNITY_SECONDS,
        margin=REJOIN_MARGIN_SECONDS,
    )
