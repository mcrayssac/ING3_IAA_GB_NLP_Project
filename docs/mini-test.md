# MVP mini-test (task 2.7)

The mini-test compares the baseline of 2.5b with adapter A of 2.6 on targets that neither has seen. Validation chose both the prompt and A's checkpoint, so its numbers favour them; the mini-test is the fair comparison. It is exploratory: 40 targets from 5 races. The final test (4.x) stays closed.

## Commands

From the repository root, with adapter A reachable (local run folder, or `HF_TOKEN` of a member of `ING3NLPProject`):

```text
python -m scripts.mini_test cards        # only if data/cards/ lacks the mini-test races
python -m scripts.mini_test prepare --name 2-7-mini-test
python -m scripts.mini_test run --run-dir runs/<date>_2-7-mini-test
python -m scripts.mini_test score --run-dir runs/<date>_2-7-mini-test
python -m scripts.mini_test rated --run-dir runs/<date>_2-7-mini-test --sheet FILLED.csv
```

- `cards` rebuilds the card files of the 7 mini-test races from OpenF1, as `scripts.rebuild_data cards` does, without building the final cards. Two of the 7 races are wet and give no card.
- `prepare` loads no model. It turns the 40 items of `data/corpus/mini_test.jsonl` into evaluation cases with the 2.5b adapter, checks race and query separation, copies both versions' config and prompt, and seals all of it in `plan.json`.
- `run` answers every target once with the baseline, then once with A: the same base model with A's adapter loaded on top, in the same process. Each raw answer and its generation trace is written as soon as it exists. A generation error stays an answer, and nothing is retried. A second `run` on the same folder is refused.
- `score` pairs the 80 answers, computes the automatic measures of the protocol and the race bootstrap of A minus baseline, and writes `paired.csv` and the masked rating sheet `review/review.csv`.
- `rated` checks a filled sheet against the raw answers and the case applicability, then adds the five-axis human means. Each reading is kept in a new `human-NN/` folder.

Without a local GPU, the notebook `mini_test_colab.ipynb` runs the same commands on a Colab GPU. Machine, dtype and library versions go to `runtime.json`; answers can differ in text from one machine to another, so both versions always run in the same session.

## What is compared

| | Baseline | A |
|---|---|---|
| Model | SmolLM3-3B at `a07cc9a0`, frozen | the same, with LoRA adapter A |
| Adapter | none | seed 2028, epoch 1, `checkpoint-120`, hash `3322b5b3158e` |
| Config | `configs/baseline-selected.toml` | `configs/adapter-a.toml` |
| Prompt | `p01-policy-first` | the same file, which A was trained on |
| Decoding | greedy, 64 new tokens, fixed history | the same |

`prepare` refuses the run when the two prompts, the model revision, the history length or the decoding settings differ. `run` stops when, on any target, A and the baseline do not see the same prompt tokens, or when their generation settings differ other than by the unused seed.

## Targets and separation

The 40 targets are the last assistant turn of each mini-test item, as in validation: 12 BOX, 12 STAY OUT and 16 NO CALL; 12 complete, 10 blocking, 6 usable, 6 follow-up and 6 out-of-scope.

`prepare` checks and records in `plan.json`:

- every target comes from one of the 7 mini-test races, and none of them is a train or validation race;
- no mini-test card is a card of corpus A or validation;
- no mini-test question has the wording of a corpus A question once numbers are masked. Validation and the mini-test share the held-out phrasings of 2.2, so that count is recorded but not refused.

## Human rating

Section 8 of the protocol samples 40 targets with 8 per family for the final test. The mini-test has only 6 usable, 6 follow-up and 6 out-of-scope targets, so that sample is impossible. Every target is rated instead: 40 targets, 80 masked answers, all five axes with their applicability. This was set before generation (#14). The rater fills `review/review.csv` without opening `review/version-key.json`, then runs `rated`.

## Results

To be filled from the run: automatic table with A minus baseline, the human means, the answers cut at 64 tokens, and at least five discussed cases, including follow-up and out-of-scope answers and the failures that contradict the hypothesis.
