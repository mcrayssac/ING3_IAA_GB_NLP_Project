# Baseline prompt comparison (task 2.5b)

The validation runner compares two unadapted baseline prompts through the shared [conversation engine](conversation-engine.md), retains every raw answer or explicit error, and selects an inference configuration using the previously declared [evaluation protocol](evaluation-protocol.md#validation-only-prompt-choice-25b). It does not train a model or open mini-test or final cases.

## Declared comparison

[`configs/baseline-prompts.toml`](../configs/baseline-prompts.toml) declares the candidates before generation:

| Candidate ID | Instructions |
|---|---|
| `p01-policy-first` | [Policy-first formulation](../configs/prompts/p01-policy-first.txt): authority and policy precede the final output-format instruction. |
| `p02-format-first` | [Format-first formulation](../configs/prompts/p02-format-first.txt): the output format follows the role, with authority and follow-up instructions later. |

Both zero-shot candidates contain the same six instruction paragraphs in different orders. They contain no validation examples or target answers. This tests instruction order without changing the policy, scope or required response format.

The model and tokenizer are `HuggingFaceTB/SmolLM3-3B` at revision `a07cc9a04f16550a088caea529712d1d335b0ac1`, with `adapter="none"`. Shared settings are three history exchanges, greedy decoding, 64 new tokens, an 8,192-token total context cap, a cooperative 30-second generation limit, seed 2026 and native template date `2026-10-19`. The existing device/dtype loader and 20 GB MPS allocation cap are reused. Temperature 1.0, top-p 1.0 and the seed do not affect greedy decoding. The engine's native template, attention mask, EOS/padding settings and unmodified continuation decoding remain in use.

These bounds preserve the existing engine configuration for a controlled comparison. The 64-token cap can cut an answer short; the time limit is checked between generation steps and cannot interrupt a stalled backend. Truncated, malformed, empty and incorrect answers remain results, without repair, label substitution, rule fallback or automatic retry.

## Common validation inputs

Use all 100 integrated validation corpus items, one target per item's final assistant turn, across seven validation races. The documented families are 30 complete, 24 blocking-incomplete, 15 usable-incomplete, 15 follow-up and 16 out-of-scope targets. Preparation validates all three expected labels, all five families and nonempty abstention/decision populations before generation.

The checked corpus and source-card loaders remain authoritative. The runner preserves source provenance, transformation metadata, original card hashes and exact decimal values. Existing target answers supply references only. Earlier exchanges are fixed context, shared by both candidates; no generated answer feeds another target. Only the corpus's why follow-ups require an earlier referent. Contextual references and family mapping follow the integrated corpus and protocol; this adaptation does not establish a new human annotation review.

The common `cases.jsonl` retains exact `input_json` bytes for card, history and current message, with separate input and candidate-configuration hashes. Native-tokenizer preflight checks every input against both prompts before the first generation. Fixed-history calls reject further context reduction. Executed token hashes and retained history must match preflight; a mismatch preserves the raw evidence and prevents selection.

The original ignored source-card files were absent from this checkout. The authorized October 19 recovery used the existing reconstruction functions for only the seven validation races, producing 7,155 source records that match all 100 validation items, including their declared transformations. Its `validation-recovery-manifest.json` and source files are retained locally and copied into the prepared run. This is an identified recovered source snapshot, not a claim that the original aggregate card manifest was reproduced. The comparison runner itself never reconstructs data or changes corpus, splits or reconstruction code.

## Commands and saved evidence

Run from the repository root in the project environment, with validation source cards present in `data/cards/` and the pinned model cached:

```sh
python -m scripts.compare_prompts prepare \
  --config configs/baseline-prompts.toml --name 2-5b-validation-prompts

HF_HUB_OFFLINE=1 python -m scripts.compare_prompts run \
  --run-dir runs/2026-10-19_2-5b-validation-prompts

python -m scripts.compare_prompts score \
  --run-dir runs/2026-10-19_2-5b-validation-prompts
```

`prepare` prints the actual dated path; use that path for both following commands. Choose a fresh `--name` for any distinct attempt. Existing runs and attempts cannot be overwritten or silently resumed. A technical correction requires a separately identified attempt with the original evidence retained.

Preparation seals source snapshots, the common ledger, candidate prompts and effective configurations in `plan.json`, whose hash is recorded in the manifest. Before running, these files and the current executable source are checked. The model loads once; both candidate wrappers share its weights and tokenizer. Responses are generated in target order, with candidate IDs in their declared order, and flushed to disk after each call.

The run retains:

- `plan.json`, `config.toml`, `manifest.json`, `cases.jsonl`, `inputs.jsonl` and `sources/`: the declaration, exact common inputs, source/configuration snapshots and their hashes;
- `candidates/<id>/config.toml` and `prompt.txt`: both effective inference configurations and exact instructions;
- `preflight.jsonl`, `runtime.json`, `chat-template.txt` and `attempts.jsonl`: native template, effective generation settings, hardware and per-call input/token/history observations;
- `outputs.jsonl`: every generated raw response or explicit generation error, using the shared evaluator envelope;
- `attempt-start.json`, then `attempt-complete.json` or `attempt-failure.json`: attempt identity and actual completion or failure evidence;
- after successful scoring, `comparison.json`, `paired.csv`, `race-bootstrap.json`, `selection.json` and `metrics.json`: full paired automatic results and the selection rationale;
- `selected/config.toml`, `selected/prompt.txt` and `selected/inference-lock.json`: the retained inference settings and links to their source evidence. The selected candidate's baseline answers remain identifiable in the complete `outputs.jsonl`.

Scoring requires a completed, unchanged response ledger and exactly one response per case/candidate. A missing row is a pipeline defect, never a manufactured model error or abstention. Runs, caches and recovered cards remain ignored local artifacts; a local path is not automatically accessible from another clone.

## Selection and interpretation

The fixed lexicographic rule maximizes, in order:

1. Strict structural format rate.
2. Negative unjustified-decision rate where the reference is NO CALL.
3. Negative excessive-refusal rate where the reference supports BOX or STAY OUT.
4. Macro-label CALL agreement.
5. Macro-family CALL agreement.
6. Micro CALL agreement.

Fractions are compared exactly; a complete tie keeps the smallest predeclared candidate ID. Every planned target, including model failures, remains in the denominators. The report keeps counts, family/label summaries, confusion and coverage so the conservative ranking does not hide trade-offs. Race-cluster uncertainty uses the unchanged protocol settings; this prompt contrast is exploratory and is not the principal baseline/A or A/B study.

The parser establishes structure and CALL agreement, not the English quality, relevance or factual support of WHY. Human ratings are not supplied here. The final study's 40-target human sample is not a requirement for this automatic prompt-selection task; no fictitious ratings or decision to drop B is introduced.

## Reuse the selected inference

Load both saved artifacts: a `prompt_variant` label alone does not replace the engine's default instructions. For example, after successful scoring:

```python
import hashlib
import json
from pathlib import Path

from boxbox.config import load_config
from boxbox.model import load_conversation_engine

lock = json.loads(Path("configs/baseline-selection.json").read_text())
for file_key, hash_key in (("config_file", "config_sha256"), ("prompt_file", "prompt_sha256")):
    path = Path(lock[file_key])
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock[hash_key]:
        raise ValueError(f"Selected inference artifact changed: {path}")
config = load_config(lock["config_file"])
instructions = Path(lock["prompt_file"]).read_text(encoding="utf-8")
engine = load_conversation_engine(config, instructions=instructions)
# engine.respond(card, history, message) returns the unmodified response.
```

For baseline/A, retain this prompt, native template/date, history and decoding configuration, and verify runtime identity against the recorded evidence. Task 2.6 supplies its separately loaded adapter through the same engine; the baseline loader continues to reject adapted configurations. Cross-device identity is not guaranteed.

The protocol was **proposed** at that point, with `acceptance_record=null`. This inference handoff does not accept the protocol or perform task 3.5's collective freeze. Status (23 October 2026): the team accepted protocol 1.1.0 unchanged in the 3.5 freeze on 21 October, and the freeze record holds the acceptance ([freeze](freeze.md)). The strict-cutoff gap-behind defect and proposed corpus A SC/VSC exception remain upstream limitations: agreement on supplied cards does not establish causal validity or optimal real strategy. No human rating, independent teammate review, team acceptance or issue closure follows from an automatic result.

## Observed validation run: 19 October 2026

Run `2026-10-19_2-5b-validation-prompts` completed all 200 planned calls and pairings, with zero generation errors, on an Apple M1 (17.2 GB RAM), MPS and bf16. All 200 executed prompt-token hashes and retained histories match the common preflight. The run manifest duration is 2,385.1 seconds, including preparation, loading, generation and scoring; summed per-call generation time is about 2,308.6 seconds. No answer was repaired or rerun.

| Automatic measure | p01-policy-first | p02-format-first |
|---|---:|---:|
| Strict format | 75/100 (75.00%) | 7/100 (7.00%) |
| Unjustified decisions on Z | 28/40 (70.00%) | 1/40 (2.50%) |
| Excessive refusal on D | 0/60 (0.00%) | 0/60 (0.00%) |
| Macro-label agreement | 370/2337 (15.83%) | 224/2337 (9.58%) |
| Macro-family agreement | 23/150 (15.33%) | 2/25 (8.00%) |
| Micro CALL agreement | 16/100 (16.00%) | 6/100 (6.00%) |
| Decision coverage | 75/100 (75.00%) | 8/100 (8.00%) |
| Eligible decision coverage | 47/60 (78.33%) | 7/60 (11.67%) |
| Unusable label | 25/100 (25.00%) | 92/100 (92.00%) |
| Justified abstention CALL rate on Z | 0/40 (0.00%) | 0/40 (0.00%) |

`p01-policy-first` is selected by the first priority, strict format: 75/100 versus 7/100. The exact later coordinates remain in `selection.json`; they do not override this priority. Its CALL agreement is only 16/100, and it makes a BOX/STAY OUT call on 28/40 targets requiring NO CALL. Neither candidate produces an extracted NO CALL, so both correct-abstention CALL rates are 0/40. The format-first candidate's lower unjustified-decision count accompanies 39 INVALID outputs on those 40 abstention targets; it is not evidence of successful refusal. Both zero excessive-refusal counts also require this context.

Policy-first has 25 unusable labels; format-first has 92. The 64-token limit is reached on 24 and 16 answers respectively, all retained as possibly truncated; the remaining calls end on EOS. Strict format does not assess WHY's sentence count or factual support. Inspection found contradictory policy assertions in preserved responses; this is an automatic-run observation, not a completed human rating. No semantic quality or overall strategic adequacy is established by this selection.

The paired 10,000-draw race bootstrap is retained in `race-bootstrap.json`, using all seven races (largest race share 23%). For format-first minus policy-first, strict-format difference is -0.68 with a 95% percentile interval [-0.7957, -0.5195], based on 10,000 valid draws. Other measures retain their own contributing-race and invalid-draw limits. This exploratory contrast does not measure training-seed variation or remove upstream source limitations.

The selected configuration is versioned as [`configs/baseline-selected.toml`](../configs/baseline-selected.toml), with [`configs/baseline-selection.json`](../configs/baseline-selection.json) recording the prompt path, configuration/prompt/template/generation settings, environment and source-run hashes. These two derived handoff files were created after scoring; the executed sources remain preserved in the run. The 100 selected baseline answers are byte-identical records filtered into `selected/baseline-outputs.jsonl`, preserving their original IDs; the full 200-record ledger remains unchanged.

The selected configuration hash is `3c409cef46c1daac6305aa4842f25212a23027e6f4fa74582425d80c75672585`, and its instruction hash is `00cf2bcd7c2198e26f8170a9595117849016f559af9496cc342398ac7564a82e`. The original cases hash is `ba30d2a6832bea4749c017671c7536dd94b51ff63e7d33c6445972a8316e1a9c`; complete raw outputs hash is `6283439360332bde46baee64e702bf6ded5e3d75044461749cb3558937fbc3c6`.

233 targeted tests passed. Ruff check/format, Git whitespace checks and new-file/link checks passed. The full suite was excluded because one corpus test reads the real mini-test. At delivery, independent teammate review, human response ratings and team acceptance were unperformed, and #12 was not declared closed. Status (23 October 2026): PR #50 was merged and issue #12 closed on 19 October, and the team accepted protocol 1.1.0 in the 3.5 freeze on 21 October.
