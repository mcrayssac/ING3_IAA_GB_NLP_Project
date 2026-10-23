# Conversation engine (task 2.5a)

`boxbox.model.ConversationEngine` is the shared, stateless baseline callable for the demo and future evaluation or adapter runners:

```python
from boxbox.model import load_conversation_engine
from boxbox.config import RunConfig

engine = load_conversation_engine(RunConfig())  # load the pinned model once
answer = engine.respond(card, history, message)  # -> raw str
```

`ConversationEngine.respond(card, history, message) -> str` keeps the app contract. `respond_with_trace` returns the same unmodified continuation plus technical observations; `prepare` exposes the actual template-tokenized input without generating. No card, history, or model answer is retained between calls. The caller owns the per-card history and clears it on reset or card change. The notebook demo has used it since task 2.8, and `python -m boxbox.app` keeps the explicit stub.

## Initial formulation and chat template

The identifiable initial formulation is `baseline-2.5a` (`RunConfig.prompt_variant`). `baseline_instructions()` renders it from the public policy 1.1 constants, including the compound windows and both 2.0-second margins. A caller can provide another instruction string to `ConversationEngine(..., instructions=...)`; no prompt comparison or selection is performed here.

The rendered system message contains the instructions followed by the complete current race card as authoritative JSON. The native tokenizer template receives messages in this order: system, retained chronological user/assistant exchanges, current user message, then the template's assistant generation prefix. The current message is added once. Decimal card values are serialized as exact JSON numbers. The tokenizer is called with `add_generation_prompt=True`, `enable_thinking=False`, `truncation=False`, and no padding. SmolLM3's own template emits its native `/no_think` metadata and empty reasoning prefix. The engine does not remove generated explanation, reasoning, comments, or other text.

The native template also calls `strftime_now` to insert a date. The engine supplies a fixed UTC clock from `RunConfig.chat_template_date` (default `"2026-10-19"`, midnight UTC), so preparing the same input on different execution dates produces the same tokens. This is a reference date for template metadata, not a current race measurement. Keep this setting identical across compared versions and prompt candidates. The effective clock and its hash are recorded in each successful preparation trace and the smoke manifest; the native Jinja source is unchanged. To reproduce the existing October 19 smoke, use its reference date. Those earlier run artifacts are preserved and predate explicit clock recording.

The instructions spell out policy order: validate the historical dry/green/race identity and the lap-minus-one cutoff first; stay out below the compound's opportunity age; require the ahead-gap opportunity in the middle window; treat the older threshold as an opportunity; then decide from the behind gap and pit-loss margin only when that branch requires them. They also call out malformed `NONE`, unknown required gaps, and fields that are unnecessary on a branch.

Generated IDs are saved in the smoke attempt trace. Text is decoded from only the continuation with `skip_special_tokens=True` and `clean_up_tokenization_spaces=False`; IDs, including generated special/EOS IDs, remain recorded. Leading/trailing whitespace and malformed or empty text are preserved. There is no output extraction, correction, retry, policy fallback, or label substitution.

## History and context

`RunConfig.history_turns` counts complete exchanges, not messages. The default is three. Interactive calls keep the newest complete exchanges; zero keeps none. When the template token count exceeds the usable input budget, interactive preparation removes oldest complete exchanges until the input fits or the mandatory system/card/current-message core still does not fit. It never asks the tokenizer to truncate. The trace records supplied, turn-limited, context-removed, and retained history separately.

The pinned SmolLM3 configuration declares 65,536 positions; the pinned tokenizer advertises 131,072, so the model limit governs. The operational `Decoding.max_context_tokens=8192` is a shorter total-context cap. `max_new_tokens=64` is reserved first, leaving 8,128 input tokens. `lora.max_length=1024` is a training setting and is not used for inference. If the mandatory prompt cannot fit, preparation raises `context_overflow`.

Evaluation must use each target's fixed `input_json` bytes from its prepared case ledger. Call `prepare(..., fixed_history=True)` or `respond_with_trace(..., fixed_history=True)` to reject any history reduction after the input hash. Do not feed an earlier target's generated response into another target. `preflight_candidates` can check prompt variants before generation; if a token budget would remove different history across candidates or a declared required turn, it refuses readiness. Prepare one common reduced ledger and re-hash it before generation, or reject that candidate set.

## Generation, bounds, and failures

The baseline uses `adapter="none"`, `eval()`, `torch.inference_mode()`, `do_sample=false`, `max_new_tokens=64`, a 30-second Transformers `max_time`, the model's loaded generation configuration, and seed 2026. Greedy decoding is deterministic within the same execution path; temperature, top-p and seed do not affect this greedy call. If sampling is explicitly configured, temperature/top-p and the seed are active, with RNG state restored after the call. Cross-device output identity is not guaranteed. The smoke manifest preserves the complete effective model generation configuration, explicit overrides, tokenizer EOS/pad IDs, device, dtype, library environment, exact prompt, and exact template.

At the pinned revision, the loaded generation config reports EOS `128012` and pad `128004`, while the tokenizer reports EOS and pad both as `128012`. The engine passes the template's attention mask and uses an unpadded single input; it does not overwrite either source's IDs. The actual generated IDs, including terminal EOS, are retained even though special tokens are omitted from decoded response text.

Transformers checks `max_time` between generation steps. It can finish the in-flight token computation after the limit and cannot forcibly interrupt a stalled kernel or a call blocked inside the backend. A call may therefore exceed the indicative 30-second limit; the demo remains in its busy state until the call returns. The token cap remains the hard generation-length bound. The engine forces one beam and one returned sequence, enables the model's KV cache, and preserves the loaded model EOS and padding IDs.

Load, template, context, and generation failures raise `ConversationEngineError` with a stable code and readable message. They are never converted to `CALL: NO CALL`. The smoke runner writes `generation_error`, its code/message, and only a partial response if the backend actually provided one. A genuine generated `NO CALL` is an ordinary model answer. A response ending at a token/time limit remains raw and carries a `possibly_truncated` diagnostic.

Failures while moving inputs to the device or entering evaluation mode use `device_transfer_error` and `model_eval_error`. Their traces retain the prepared input, generation settings and failure stage, so the smoke runner can save and pair the failed attempt alongside successful calls.

## Reproducible synthetic smoke

The technical settings are recorded in [`configs/conversation-smoke.toml`](../configs/conversation-smoke.toml). They reuse the pinned SmolLM3-3B revision, task 1.5 device/dtype selection, its 20 GB MPS allocation cap, greedy decoding, and the existing 64-token `RunConfig` default as an initial interactive cap. The real smoke reached that cap on two of five cases, so 64 tokens does not guarantee a complete two-line answer; those raw cutoffs remain in the run, and this task does not retune generation against them. The command is:

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.smoke_conversation --config configs/conversation-smoke.toml --name 2-5a-smollm3-smoke-repeat
```

It loads the model once and runs five synthetic targets from `reference/evaluation-fixtures.json`: an initial call, a same-card follow-up with fixed history, a blocking incomplete card, an out-of-scope request with the contextual annotation, and a contradictory numeric assertion. It saves exact case/input ledgers, raw response/error envelopes compatible with `boxbox.evaluation.pair_outputs`, generated token IDs, per-attempt prompt/history/context traces, parser-only format diagnostics, policy or scope reference provenance, configuration and source snapshots under a new ignored `runs/<date>_2-5a-smollm3-smoke/` directory. It never uses validation, mini-test, final, training, or real race cards. Existing run directories are not overwritten; use a new `--name` for a distinct attempt.

The strict parser checks only structure and extracts a label for diagnosis. `decide` supplies card-policy references; the synthetic contextual annotation supplies the out-of-scope reference. Neither is given to the model. Automatic agreement and self-inspection are not human ratings or a performance claim. Protocol `boxbox-eval/1.1.0` was proposed and `acceptance_record` was null at that point. Status (23 October 2026): the team accepted it unchanged in the 3.5 freeze on 21 October ([freeze](freeze.md)).

Run the deterministic tests and lint without loading a model:

```sh
.venv/bin/python -m pytest -q tests/test_conversation_engine.py tests/test_app.py tests/test_runs.py tests/test_race_card.py tests/test_evaluation.py
.venv/bin/ruff check boxbox/model boxbox/config.py boxbox/rules tests/test_conversation_engine.py scripts/smoke_conversation.py
.venv/bin/ruff format --check boxbox/model boxbox/config.py boxbox/rules tests/test_conversation_engine.py scripts/smoke_conversation.py
```

The complete suite is intentionally not the prescribed check because `tests/test_corpus.py::test_load_corpus_rejects_a_changed_file_or_policy` opens the real mini-test corpus.

## Handoffs

- **2.5b:** reuse the same callable, exact input ledger, `prepare`, and candidate preflight. Compare prompt variants on validation only in that task; do not silently drop history independently per candidate.
- **2.6:** reuse `prepare` and the generation path with a separately loaded adapter model. This baseline loader deliberately rejects `adapter != "none"`.
- **2.8:** pass `engine.respond` to `launch(respond=..., engine="Adapter A", turns=config.history_turns)`. The default app stub and notebook remain unchanged in 2.5a.
- **2.3b/4.x:** keep the raw response/error envelope, fixed input hashes, effective generation settings, prompt/template hashes and actual retained history. The final split stays closed.

Status (23 October 2026): 2.5b, 2.6 and 2.8 are done, and so are 4.1 to 4.5. The final split was opened in 4.1, under the freeze, and 4.2 scored the retained versions through this engine.
