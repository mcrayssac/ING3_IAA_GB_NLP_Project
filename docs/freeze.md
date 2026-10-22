# Freeze of the retained versions (task 3.5)

The freeze fixes what the final evaluation (4.x) runs and how it scores it, before any final card is opened. It is recorded once in `configs/freeze.json` and checked by every later step.

## Commands

From the repository root, on a clean checkout of `main`:

```text
python -m scripts.freeze record --decision URL --acceptance URL --reviewer NAME
python -m scripts.freeze check
```

- `record` writes `configs/freeze.json` and refuses to overwrite it. `--decision` links the team decision on #19 (which versions are retained), `--acceptance` the team's acceptance of evaluation protocol `boxbox-eval` 1.1.0 for the final test, and `--reviewer` names the teammate who reviews the freeze. It refuses a dirty working tree, versions that differ in model, prompt, history or decoding, and a config with `final_test_open = true`. It loads no model and reads no final card.
- `check` recomputes every hash of the record and lists each difference. It exits with 1 when something changed, so 4.1 and 4.2 can run it first.

## What is frozen

| Part | Frozen identity |
|---|---|
| Model | SmolLM3-3B at `a07cc9a04f16`, frozen base for every version |
| Baseline | `configs/baseline-selected.toml`, prompt `p01-policy-first`, chat template hash, from `configs/baseline-selection.json` (2.5b) |
| Adapter A | seed 2028, epoch 1, `checkpoint-120`, weights `3322b5b3158e`, Hub `ING3NLPProject/boxbox-adapter-a` at `ece13db9ea17`, from `configs/adapter-a-selection.json` (2.6) |
| Adapter B | seed 2027, epoch 3, `checkpoint-360`, weights `70423a7d4aa7`, Hub `ING3NLPProject/boxbox-adapter-b` at `f182f8e9150f`, from `configs/adapter-b-selection.json` (3.2) |
| Shared inference | same prompt file, fixed history of 3 exchanges, greedy decoding, 64 new tokens, context 8,192 tokens, template date 2026-10-19 |
| Training settings | each adapter's LoRA settings and `abstention_share` (0 for A, 0.15 for B) |
| Data | `data/splits.json`, corpus manifest, A, B, B pairs, validation, mini-test and exposure files |
| Evaluation | `docs/evaluation-protocol.md` (1.1.0), `reference/evaluation-fixtures.json`, `reference/fixtures.json`, `boxbox/rules/decision.py`, `docs/race-card-contract.md` |

The record also keeps the time (Europe/Paris), the commit, the decision and acceptance links and the reviewer. The protocol file still says "proposed": its acceptance is recorded in the freeze, not by editing the file, so the hash sealed by earlier runs stays valid.

## Rules after the freeze

- No new experiment: no new corpus, prompt, checkpoint, decoding or protocol choice.
- A correction that changes outputs needs an explicit team decision and a new freeze before any final evaluation. The old record is kept.
- The final test stays closed until 4.1 opens it under this freeze.

## Experimental milestone

The freeze covers the A/B study. The Experimental milestone, merged into `main` in PR #69, edits none of the sealed files:

- `boxbox.rules.decide` now goes through `policy2.decide`. It sends 2.0 cards to policy 2.0 and leaves every 1.0 card to the sealed policy 1.1 in `boxbox/rules/decision.py`, which gives the same calls as before.
- The 2.0 files (cards, priors, policy 2.0, replay) and `data/splits-v2.json` sit outside the freeze.
- `python -m scripts.freeze check` still reports "freeze intact".
- `python -m scripts.rebuild_data cards` now rebuilds the 1.0 cards with the corrected track status: 65,656 cards instead of 65,904. The 1.0 cards behind the frozen corpus and results can be rebuilt exactly only from commit `631b783`, the last commit before the merge.

## Known limits carried into the final evaluation

- B trades fewer unjustified decisions for more excessive refusals on usable incomplete cards ([interim analysis](interim-ab-analysis.md)); it is a research arm, not a product upgrade.
- The human 0–2 rating of the mini-test answers has not been done; the final human review (4.3) is the first one.
- Answers can differ slightly between machines (M3 Max MPS and Colab L4): the final scoring runs all retained versions in one process on one machine.
- The 64-token limit cuts some answers of every version; it is frozen as is.
