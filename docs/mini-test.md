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

The five-axis scores below come from a human rating; see [Qualitative scores](#qualitative-scores-human-rating).

## Results

### Run

Run `2026-10-20_2-7-mini-test-r3`, on Colab with an NVIDIA L4 in bf16, plan `cases_sha256` `144c48b86b55`. All 80 answers were kept, with no generation error. Two earlier folders stay as traces: `…-2-7-mini-test` was only prepared, and `…-r2` stopped when loading A because of an incompatible `torchao`, after its 40 baseline answers. Those 40 answers are identical to the baseline answers of r3, so the baseline is reproducible on this machine. Each failed folder was left as it was; nothing was retried in place.

The run folders are not committed (`runs/` is ignored). They are shared with the review of #14.

### Automatic measures

All 40 targets, A minus baseline, with the race bootstrap of the protocol (seed 2026, 10,000 draws, percentile 95%). "Few races" marks intervals with 2 to 4 contributing races.

| Measure | Baseline | A | A − baseline | 95% interval |
|---|---|---|---|---|
| Strict two-line format | 31/40 | 40/40 | +0.225 | [0.095, 0.280] |
| CALL agreement | 10/40 | 29/40 | +0.475 | [0.286, 0.548] |
| Macro-label agreement | 0.278 | 0.757 | +0.479 | [0.278, 0.566], few races |
| Macro-family agreement | 0.233 | 0.770 | +0.537 | [0.408, 0.718], few races |
| CALL agreement, decision targets (D) | 10/24 | 22/24 | +0.500 | [0.294, 0.706] |
| Excessive refusals on D | 0/24 | 1/24 | +0.042 | [0.000, 0.176] |
| Justified NO CALL on NO CALL targets (Z) | 0/16 | 7/16 | +0.438 | [0.167, 0.727], few races |
| Unjustified decisions on Z | 11/16 | 9/16 | −0.125 | [−0.188, 0.000], few races |
| Answers cut at 64 new tokens | 9 | 2 | | |

CALL agreement by family:

| Family | Baseline | A |
|---|---|---|
| complete | 6/12 | 11/12 |
| blocking_incomplete | 0/10 | 1/10 |
| usable_incomplete | 2/6 | 5/6 |
| follow_up | 2/6 | 6/6 |
| out_of_scope | 0/6 | 6/6 |

A always answers in the two-line format, and its CALL matches the policy far more often than the baseline. The gain does not reach blocking cards: on 9 of the 10 cards where the policy refuses to decide (unknown gap or pit loss, safety car), A still gives BOX or STAY OUT. Its seven justified NO CALL answers on Z are the six out-of-scope questions and one blocking card.

The baseline's 9 cut answers are free-text or multi-sentence answers. A's 2 cut answers are the two follow-ups that correct a user's number (M-015, M-019): the WHY is long and stops before the end of its sentence.

### Qualitative scores (human rating)

The blind human rating planned above was completed in the 2.7 window. The 80 masked answers were scored with the same five axes and applicability by a human reviewer, from the masked rating workbook, which shows no version identity. **These are human ratings and satisfy the human review of the protocol**. The scores, their reasons and the summary are stored with the human review outputs of the run folder. The human reviewer flagged 37 of the 80 rows for a second reading.

Means on the 0–2 scale, pairs where the axis applies to the target, same race bootstrap:

| Axis | Pairs | Baseline | A | A − baseline | 95% interval | A better / tie / baseline better |
|---|---|---|---|---|---|---|
| correctness | 40 | 0.225 | 1.225 | +1.000 | [0.667, 1.267] | 22 / 17 / 1 |
| role_format | 40 | 1.525 | 1.950 | +0.425 | [0.250, 0.714] | 14 / 25 / 1 |
| factuality | 40 | 0.750 | 1.400 | +0.650 | [0.400, 0.889] | 17 / 19 / 4 |
| scope | 6 | 1.167 | 1.833 | +0.667 | [0.000, 2.000], 3 races | 2 / 4 / 0 |
| history | 2 | 2.000 | 2.000 | 0.000 | suppressed: 9,171 valid draws | 0 / 2 / 0 |

In the human review, A gains most on correctness and factuality, and both versions stay low on correctness because a right CALL with a wrong reason scores 0. The history axis applies to two targets only, so it says nothing.

### Discussed cases

1. **Blocking card, gap behind unknown (M-025, 2025-18).** The policy expects NO CALL. Both versions answer BOX, and A writes "no car behind" where the card says the gap behind is unknown. This contradicts the hypothesis: training on 400 dialogues did not teach A that an unknown value blocks the call, and A turns it into a favourable value. It is the main failure of A, repeated on 9 of the 10 blocking cards.
2. **Safety car (M-029, M-030, 2025-04).** The baseline answers BOX with a gap-ahead argument. A switches to STAY OUT with a correct sentence about tyre age, but never mentions the safety car that blocks the call. A's sentence is true and well formed, which makes the wrong decision look reliable: the human reviewer gives it 2 on factuality and 0 on correctness.
3. **Complete card, both wrong (M-012, 2025-18).** The policy expects BOX. The baseline finds BOX with a false threshold ("12 laps is above 18"). A answers STAY OUT by comparing the gap **ahead** with the pit loss, a comparison the policy makes only with the gap behind. It is A's only miss on complete cards, and a second failure against the hypothesis.
4. **Out of scope (M-016, M-020, M-021).** A gives NO CALL in the right format on all six out-of-scope questions; the baseline never does: it writes a bare NO CALL without the `CALL:` line four times, answers STAY OUT once (M-022) and gives a strategy for the next Grand Prix on M-020. A's reasons are partly a template: the same sentence about "a full multi-stop strategy" answers a question about the next Grand Prix (M-020) and one about intermediate tyres (M-021), where the limit is the weather. The human reviewer gives it 1 on correctness and scope there.
5. **Follow-up with a user's number (M-015, M-019).** The user gives a gap behind that differs from the card. The baseline uses the user's 20.4 s in M-015 and writes a false comparison ("20.4 covers 22.4 + 2.0"), and in M-019 refuses with a bare NO CALL outside the format. A keeps the card value and says so ("the call uses the card, not the stated gap"), which is the expected behaviour, but both answers are cut at 64 tokens before the end of the WHY.
6. **Excessive refusal (M-038, 2024-14) and wrong reason (M-037, 2025-04).** On a usable card with unknown gaps and pit loss but HARD tyres only 6 laps old, the policy still says STAY OUT. A answers NO CALL with "the card does not show green-flag running", while the flag is green; it is its only excessive refusal. On M-037 the same sentence gives the right NO CALL for the wrong reason (the real block is the unknown gap ahead). A seems to have learned a few fixed refusal sentences rather than the condition behind each one.

### Limitations

- Exploratory: 40 targets from 5 races (the two wet races give no card), up to 35% of the targets in one race, and several intervals with few contributing races. It is not an estimate for the final test.
- Human rating completed: the five-axis scores come from a human reviewer. A second reading may still be useful for the rows flagged during review.
- One training seed of A, one machine (L4, bf16); text can differ on another machine.
- The 64-token cap cuts 9 baseline answers and 2 of A, which lowers their format and possibly their correctness.
- Validation chose both the prompt and A's checkpoint; only these mini-test numbers are a fair comparison.

The MVP gate decision is recorded with task 2.8 (#15), as the roadmap requires.
