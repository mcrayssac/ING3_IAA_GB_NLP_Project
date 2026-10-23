# OpenJev zero-shot baseline (task 3.4)

This study asks whether a recent zero-shot decision model can make BoxBox's pit call as well as, or better than, the fine-tuned adapters A and B, without any training. The model is OpenJev Flash 9B (`openjev/OpenJev-Flash-9B-MLX-4bit`), run locally on the M3 Max. It answers the CALL line on the same validation and mini-test targets as baseline, A and B.

It is an exploratory study, as decided on #35 on 21 October. It stays outside the 3.5 freeze. If the team later wants OpenJev in the final comparison, its configuration is frozen first, and that is recorded as an exception to the passed freeze before 4.2 scores its CALL line.

The runs of 21 October answer the main question. On the 40 unseen mini-test targets, OpenJev agrees with the reference call on 18 targets with its most probable option, and on 23 with the threshold. The untuned baseline gets 10, A 28 and B 33. OpenJev also refuses some of the usable incomplete cards, it changes 16 of 100 validation calls when only the option order changes, and its probabilities are poorly calibrated on our cards. The results and their reading are in [Results](#results) and [Answers to the research questions](#answers-to-the-research-questions).

## What OpenJev is

OpenJev describes itself as a decision model. A request names the options of each question. The model gives each option a letter, and the server reads the score of every letter at the first output position, so no text is generated. A fixed calibration then turns the scores into one probability per option. Questions can be a `choice` among options, a yes/no question (`noul`) or a `score` on ordered levels. One request can ask several named questions about the same `state`, through `POST /v1/systemone`.

The build used here:

| Fact | Value, from the model cards read on 21 October |
|---|---|
| Size | 9B parameters, MLX 4-bit, 5.04 GB on disk, text only |
| Base model | Qwen3.5-9B |
| Setup | Python 3.12 with `mlx==0.32.2`, `mlx-lm==0.31.3` and `transformers==5.17.0`, helper `shim_mlx.py` with `shim.py`, local server on port 3000 |
| Readout values for this build | `READOUT_T=1.07`, `READOUT_NOUL_T=1.074766`, `READOUT_NOUL_BIAS=0`, `READOUT_TARGETED=1`, `READOUT_INSTR_STYLE=pyrepr` |
| Self-check | `--selfcheck` prints a helper hash starting `81a22f1b` |
| Limits | up to 52 options per pass, prompts up to 16,384 tokens in the documented vLLM setup |
| Licence | weights under CC BY-NC 4.0 (non-commercial use with attribution), helper and serving files under Apache 2.0 |

For Flash 9B, its authors report:
- 186 of 231 public JevBench items (80.5%) for this 4-bit build, and 188 (81.4%) for the 8-bit MLX build
- 79.4% on their 10,000 text questions, against 84.1% for OpenJev 27B

The Flash 9B cards give no calibration score, no comparison with the untuned base model and no test with shuffled options.

The main OpenJev card describes the larger model of the family, which the Flash 9B card calls OpenJev 27B. On the same 10,000 questions it reports 84.0% for that model (84.1% on the Flash 9B card) against 80.4% for its base model before tuning. On 2,000 agent decisions, its answers change in 2.3% of cases when the options are shuffled, against 18.5% before tuning. These figures are not for Flash 9B.

No paper or independent evaluation is cited for any of these figures. Part of this study is to see what holds on our cards.

Correction, 21 October: the first version of this page gave the main card's figures (84.0% against 80.4%, and 2.3% against 18.5%) as if they were Flash 9B's. It also quoted a Brier score of 0.19, which neither card's text reports. Research questions 1, 3 and 4 below keep their hypotheses as declared, with a note where they relied on those figures.

## Why it fits BoxBox

The CALL line is a choice among three labels: BOX, STAY OUT and NO CALL. OpenJev answers exactly that kind of question, with a probability for each label, so a threshold on those probabilities gives an explicit way to abstain. It needs no training data and no training run, where A and B each took about four hours for three seeds.

It also targets the clearest weakness of B. Over its three seeds, B refused 44 of the 45 usable incomplete validation targets, the cards where a field is unknown but the rule does not need it. On the mini-test it refused all 6 of them (`docs/adapter-b.md`).

## Scope

In scope:
- **Targets:** the 100 validation targets (cases hash `ba30d2a6832b`) and the 40 mini-test targets of run `2026-10-21_3-2-mini-test-r2`, the same ones as baseline, A and B.
- **Input:** each card and conversation as the conversation engine renders it. The decision policy is the p01 prompt retained in 2.5b. The instructions are not tuned for OpenJev, so that validation is not used to fit them.
- **The CALL question:** one `choice` among BOX, STAY OUT and NO CALL, compared with baseline, A and B.
- **Three diagnostic questions,** reported apart and never used to make the call:
  - `in_scope`: the message asks for this car's call, its reason or a card field
  - `required_known`: every field the rule needs on this card is known
  - `missing_field`: gap ahead, gap behind, tyre age, pit loss, track status or none

  Their references come from the cases: the family (blocking incomplete, usable incomplete, out of scope), the request scope and the removed field.

Out of scope:
- **No WHY sentence.** OpenJev writes none, so it stays out of the human review (4.3) and the demo.
- **No final test.** It is not used unless the team decides otherwise, as described above.

The threshold rule was fixed on #35 before any result:
- OpenJev answers BOX or STAY OUT only when that option's probability reaches a threshold τ, and NO CALL otherwise.
- τ is chosen on validation, on a grid from 0 to 1 in steps of 0.01. It is the value with the highest CALL agreement. Ties go to fewer unjustified decisions, then to the lower τ.
- The whole curve of unjustified decisions against excessive refusals is reported, with baseline, A and B as points on it.

Measures:
- **From the shared evaluator,** on the CALL line: CALL agreement, unjustified decisions on Z (targets whose answer is NO CALL), excessive refusals on D (the others), macro-label and macro-family agreement, and decision coverage. Strict format and the human axes do not apply.
- **For the probabilities:** the Brier score, the expected calibration error over 10 equal bins with its reliability diagram (Guo et al. 2017), and the share of calls that change when the options are shuffled.
- **Cost:** latency per target and peak memory.

## Research questions

1. **Can a zero-shot model match the fine-tuned adapters on the call?**
   - Studies of text classification mostly find that fine-tuned small models beat zero-shot large ones. That holds across news, tweets and speeches (Bucher and Martini 2024) and on pathology reports (Gondara et al. 2025). Zero-shot methods lose on most tasks across 32 datasets in 8 languages (Vajjala and Shimangaud 2025).
   - Small models can still classify well zero-shot, and size alone does not decide (Lepagnol et al. 2024). OpenJev is also not a plain chat model: it is tuned for decisions, which gave it 3.6 points over its untuned base on its authors' benchmark.
   - Note: that gain belongs to the larger OpenJev, and its card gives 3.7 points (8,403 against 8,036 of 10,000). The 3.6 was the gap between the rounded percentages. The Flash 9B card gives no comparison with its untuned base.
   - Hypothesis: A and B keep a higher CALL agreement than OpenJev on complete cards, where the rule is applied to numbers they were trained on.
   - Measured by CALL agreement by family on validation and the mini-test.
2. **Is a threshold on calibrated probabilities a better way to abstain than B's learnt NO CALL?**
   - Abstention methods usually set a threshold on a calibrated confidence (Wen et al., survey in TACL). But that survey notes that whether a query "is answerable at all" is "difficult to model in terms of model confidence". In BoxBox, NO CALL has two causes: a missing required field, which is about answerability, and an out-of-scope request.
   - Hypothesis: the threshold lowers unjustified decisions on out-of-scope requests more easily than on cards with a missing required field. Unlike B, OpenJev does not refuse the usable incomplete cards, because it was never trained to link an unknown field with NO CALL.
   - Measured by the risk and coverage curve against baseline, A and B, with each NO CALL cause and the usable incomplete cards reported apart.
3. **Are its probabilities calibrated on our cards?**
   - Hypothesis: calibration is worse on our cards than the Brier of 0.19 its authors report, since race cards are far from their data.
   - Note: neither card's text reports a Brier score, so the 0.19 has no source. The hypothesis can only be read as "poorly calibrated on our cards", with no published figure to compare with.
   - Measured by Brier, ECE and the reliability diagram on validation, then on the mini-test with nothing refitted.
4. **Does option order change its calls?**
   - Large language models favour some option letters when answering multiple-choice questions, whatever the options say (Zheng et al. 2024). OpenJev also reads its answer from option letters, and its authors report fixing most of that bias.
   - Hypothesis: the share of changed calls on our cards stays close to the reported 2.3%.
   - Note: the 2.3% and the bias fix are reported for the larger OpenJev, on agent decisions. The Flash 9B cards report no shuffle test.
   - Measured by one validation run with the three options shuffled under a fixed seed.
5. **Do the diagnostic questions explain its errors?**
   - Hypothesis: on cards where OpenJev makes an unjustified call, it often still answers `required_known` correctly. That would mean it can see the missing field but does not draw the policy's conclusion from it.
   - Measured by the accuracy of each diagnostic question and their agreement with the call, by family.
6. **What does it cost?**
   - Measured by latency per target and peak memory on the M3 Max, set against A and B: about four hours of training each, and their answering time.

## Limits stated now

- **Complete systems:** this compares complete systems. OpenJev differs from baseline, A and B in size (9B against 3B), base model (Qwen3.5-9B against SmolLM3-3B), readout (scored options against generated text) and adaptation (zero-shot against LoRA). A gap cannot be put down to any one of them.
- **Validation choices:** τ is chosen on validation, where A's and B's checkpoints and the p01 prompt were also chosen. The mini-test is the fair comparison, and with 40 targets from 5 races its intervals are wide.
- **Diagnostic wording:** the diagnostic questions are our own wording, written once and not tuned.
- **Hardware:** the results hold for this 4-bit build on this Mac. Its authors report small differences between builds.

## Setup

- **Environment:** `~/openjev/mlx`, a Python 3.12.13 environment outside the repository, with the packages of the model card: mlx 0.32.2, mlx-lm 0.31.3, transformers 5.17.0, openai 3.16.2, httpx 0.28.1 and huggingface-hub 1.32.0. README section 14 has the commands.
- **Pinned files:** `configs/openjev.toml` records the model revision `33cbf372` and the helper revision `b77b0fff`, with the SHA-256 of 11 files. The two helper files match the repository's own `SHA256SUMS`, and the model file matches its LFS hash. Every run hashes the 11 files again before it starts the server.
- **Code reading:** both helper files were read in full before the first run.
  - The server binds to 127.0.0.1, writes no file and sends no telemetry.
  - Its only outbound code is a chat passthrough, which cannot run on the MLX path and which we never call.
  - The model folder holds no Python file, and its configuration names no custom code.
  - Runs set `HF_HUB_OFFLINE=1`, so any Hub access fails instead of downloading.
- **Server:** `scripts/openjev_baseline.py run` starts the server with the readout values of the model card. It checks `/v1/version` against the pinned helper hash and calibration, asks each target once and stops the server. A failed request stays an error and is never retried. There was none.
- **Request:** the state is the engine's system text, so the p01 policy and the card JSON exactly as `_prompt` writes them, then the conversation as `User:` and `Assistant:` lines.
  - p01's closing paragraph on the two-line answer format is left out, because the helper asks for one letter. The rest of p01 is unchanged.
  - The four questions are in `configs/openjev.toml`. Options come without descriptions, in the order of p01's CALL line for the call question.
  - For the first validation target, the runner's request is identical to the smoke request checked by hand.
- **Diagnostic references:** `in_scope` is the opposite of the case's out-of-scope flag. `required_known` and `missing_field` come from the reason `decide()` gives for a NO CALL. On the 4 validation and 2 mini-test cards under a safety car or VSC, track status counts as the field that stops the rule. A yes/no answer counts as yes when its probability is at least 0.5.

## Runs

All three runs come from commit `07850a9` with a clean tree. Every target got an answer, with no request error.

| Run | Targets | Questions per target | Seconds per target | Duration |
|---|---:|---|---:|---:|
| `2026-10-21_3-4-openjev-validation` | 100 | 4 | 7.3 | 12.3 min |
| `2026-10-21_3-4-openjev-validation-shuffle-s2026` | 100 | CALL only, options reordered | 1.7 | 2.9 min |
| `2026-10-21_3-4-openjev-mini-test` | 40 | 4 | 7.6 | 5.2 min |

The duration includes loading the model. With four questions, a target sends about 3,240 prompt tokens, one forward pass per question.

## Threshold

The rule of #35 gives τ = 0.59 on validation. CALL agreement reaches its maximum, 0.64, at τ 0.55, 0.58 and 0.59. The tie goes to fewer unjustified decisions: 2 of 40 at 0.59, against 4 at 0.58 and 6 at 0.55.

| τ | CALL agreement | Unjustified decisions | Excessive refusals | Decision coverage |
|---:|---:|---:|---:|---:|
| 0 (argmax) | 0.56 | 0.550 | 0.083 | 0.77 |
| 0.50 | 0.59 | 0.325 | 0.267 | 0.57 |
| 0.55 | 0.64 | 0.150 | 0.317 | 0.47 |
| 0.59 | 0.64 | 0.050 | 0.450 | 0.35 |
| 0.62 | 0.62 | 0.050 | 0.533 | 0.30 |
| 0.70 | 0.54 | 0.025 | 0.700 | 0.19 |
| 0.80 | 0.51 | 0.000 | 0.817 | 0.11 |

`threshold.json` in the validation run holds the 101 points. The peak is narrow. Above 0.59, unjustified decisions stay at 2 of 40 up to 0.62 while refusals keep rising.

## Results

### Validation

A's and B's checkpoints, the p01 prompt and τ were all chosen on these 100 targets, so this table favours each of them.

| Measure | Baseline | A | B | OpenJev argmax | OpenJev τ |
|---|---:|---:|---:|---:|---:|
| CALL agreement | 16/100 | 70/100 | 84/100 | 56/100 | 64/100 |
| Unjustified decisions (Z) | 28/40 | 23/40 | 0/40 | 22/40 | 2/40 |
| Excessive refusals (D) | 0/60 | 1/60 | 15/60 | 5/60 | 27/60 |
| Macro-label agreement | 0.158 | 0.714 | 0.870 | 0.562 | 0.603 |
| Macro-family agreement | 0.153 | 0.755 | 0.793 | 0.608 | 0.663 |
| Decision coverage | 75/100 | 82/100 | 45/100 | 77/100 | 35/100 |

CALL agreement by family:

| Family | Baseline | A | B | OpenJev argmax | OpenJev τ |
|---|---:|---:|---:|---:|---:|
| Blocking incomplete | 0/24 | 1/24 | 24/24 | 4/24 | 22/24 |
| Complete | 9/30 | 24/30 | 29/30 | 16/30 | 10/30 |
| Follow-up | 2/15 | 14/15 | 15/15 | 13/15 | 11/15 |
| Out of scope | 0/16 | 16/16 | 16/16 | 14/16 | 16/16 |
| Usable incomplete | 5/15 | 15/15 | 0/15 | 9/15 | 5/15 |

OpenJev minus the other versions, race bootstrap over the 7 validation races (10,000 draws, seed 2026):

| Contrast | CALL agreement | Unjustified decisions | Excessive refusals |
|---|---|---|---|
| argmax − baseline | +0.400 (+0.310 to +0.533) | -0.150 (-0.283 to -0.042) | +0.083 (+0.021 to +0.127) |
| argmax − A | -0.140 (-0.205 to -0.083) | -0.025 (-0.122 to +0.093) | +0.067 (+0.018 to +0.116) |
| argmax − B | -0.280 (-0.467 to -0.076) | +0.550 (+0.333 to +0.708) | -0.167 (-0.356 to -0.036) |
| τ − baseline | +0.480 (+0.343 to +0.644) | -0.650 (-0.771 to -0.481) | +0.450 (+0.306 to +0.585) |
| τ − A | -0.060 (-0.237 to +0.103) | -0.525 (-0.705 to -0.320) | +0.433 (+0.304 to +0.567) |
| τ − B | -0.200 (-0.290 to -0.102) | +0.050 (0.000 to +0.128) | +0.200 (+0.096 to +0.305) |

For unjustified decisions and excessive refusals, a negative difference favours OpenJev.

### Mini-test

The mini-test is the fair comparison. OpenJev answered the 40 targets of run `2026-10-21_3-2-mini-test-r2`, with the same case and input hashes, and τ stayed at 0.59. The baseline, A and B columns are that run's answers.

| Measure | Baseline | A | B | OpenJev argmax | OpenJev τ |
|---|---:|---:|---:|---:|---:|
| CALL agreement | 10/40 | 28/40 | 33/40 | 18/40 | 23/40 |
| Unjustified decisions (Z) | 11/16 | 9/16 | 1/16 | 10/16 | 4/16 |
| Excessive refusals (D) | 0/24 | 1/24 | 6/24 | 3/24 | 9/24 |
| Macro-label agreement | 0.278 | 0.729 | 0.812 | 0.458 | 0.556 |
| Macro-family agreement | 0.233 | 0.753 | 0.767 | 0.503 | 0.607 |
| Decision coverage | 31/40 | 32/40 | 19/40 | 31/40 | 19/40 |

CALL agreement by family:

| Family | Baseline | A | B | OpenJev argmax | OpenJev τ |
|---|---:|---:|---:|---:|---:|
| Blocking incomplete | 0/10 | 1/10 | 10/10 | 1/10 | 7/10 |
| Complete | 6/12 | 10/12 | 12/12 | 5/12 | 4/12 |
| Follow-up | 2/6 | 6/6 | 6/6 | 5/6 | 5/6 |
| Out of scope | 0/6 | 6/6 | 5/6 | 5/6 | 5/6 |
| Usable incomplete | 2/6 | 5/6 | 0/6 | 2/6 | 2/6 |

OpenJev minus the other versions, race bootstrap over the 5 mini-test races:

| Contrast | CALL agreement | Unjustified decisions | Excessive refusals |
|---|---|---|---|
| argmax − baseline | +0.200 (0.000 to +0.314) | -0.062 (-0.188 to +0.222) | +0.125 (0.000 to +0.368) |
| argmax − A | -0.250 (-0.348 to -0.159) | +0.062 (0.000 to +0.222) | +0.083 (0.000 to +0.211) |
| argmax − B | -0.375 (-0.533 to -0.235) | +0.562 (+0.273 to +0.833) | -0.125 (-0.226 to 0.000) |
| τ − baseline | +0.325 (0.000 to +0.568) | -0.438 (-0.632 to -0.143) | +0.375 (+0.118 to +0.560) |
| τ − A | -0.125 (-0.375 to +0.114) | -0.312 (-0.500 to 0.000) | +0.333 (+0.077 to +0.486) |
| τ − B | -0.250 (-0.467 to -0.053) | +0.188 (+0.059 to +0.444) | +0.125 (0.000 to +0.281) |

The 16 targets whose answer is NO CALL come from fewer than 5 races, so the intervals on unjustified decisions are rough. The largest race holds 35% of the targets.

### Calibration and diagnostics

| Measure | Validation | Mini-test |
|---|---:|---:|
| Brier score of the CALL probabilities (0 best, 2 worst) | 0.520 | 0.607 |
| Expected calibration error, 10 bins | 0.132 | 0.236 |
| `in_scope` right | 98/100 | 39/40 |
| `required_known` right | 62/100 | 24/40 |
| `missing_field` right | 25/100 | 10/40 |
| Blocking cards where OpenJev still decided | 20 | 9 |
| of which `missing_field` named the right field | 19 | 7 |
| of which `required_known` said a field is unknown | 16 | 7 |

On validation, the targets with a top probability from 0.4 to 0.6 have a mean confidence of 0.46 to 0.56 and an accuracy of 0.36 to 0.39. The 22 targets at 0.8 or more are all right.

## Answers to the research questions

### 1. Accuracy without training

The hypothesis holds. A and B keep a higher CALL agreement than OpenJev, and the gap is widest on complete cards.
- On the mini-test, OpenJev gets 5 of 12 complete cards at argmax and 4 at τ, against 10 for A and 12 for B.
- Overall, its argmax is 0.250 below A (-0.348 to -0.159) and 0.375 below B (-0.533 to -0.235). With τ, it stays 0.250 below B (-0.467 to -0.053). Against A the gap of 0.125 is not clear (-0.375 to +0.114).
- It gains on the untuned baseline: +0.200 at argmax and +0.325 at τ, though both intervals start at 0.

This matches the studies of Bucher and Martini (2024) and Gondara et al. (2025). The decision tuning of OpenJev does not make up for the missing fine-tuning on our rule. OpenJev handles the scope of a message well (`in_scope` 39 of 40) and the numeric branches of the rule poorly.

### 2. Threshold abstention against B's learnt NO CALL

The hypothesis does not hold, in either part.
- **Where the threshold helps:** most of its gain is on blocking cards (1 to 7 of 10 on the mini-test, 4 to 22 of 24 on validation). OpenJev already answers most out-of-scope requests with NO CALL at argmax (5 of 6, 14 of 16). Its probabilities are low on the cards with a missing field, which is what the threshold uses.
- **Usable incomplete cards:** OpenJev refuses some of them too. At argmax it answers NO CALL on 2 of 6 mini-test cards and 4 of 15 validation cards. With τ, that rises to 4 of 6 and 9 of 15. B refuses all of them. A refuses 1 of 6 on the mini-test and none on validation.
- **Against B:** on the mini-test, τ leaves OpenJev with more unjustified decisions than B (+0.188, +0.059 to +0.444) and more refusals of decidable targets (+0.125, 0.000 to +0.281). B's learnt NO CALL does better on both sides of the trade-off.

### 3. Calibration

The probabilities are poorly calibrated on our cards, and worse on unseen targets with nothing refitted: ECE 0.132 on validation and 0.236 on the mini-test. On validation, OpenJev is overconfident in the middle of the range and underconfident at the top. Neither card's text reports a Brier score, so our 0.520 on validation has no published figure to compare with. The 0.19 named in the hypothesis has no source.

### 4. Option order

The hypothesis does not hold. With the three options in another order, 16 of 100 validation calls change. The 2.3% the hypothesis named belongs to the larger OpenJev, on agent decisions, and the Flash 9B cards report no shuffle test. So there is no published figure for this model. Our 16% is far above the 2.3% reported for the larger OpenJev, and nearer the 18.5% its card gives for the untuned base, though that card measures agent decisions, not race cards. The changes come from every family: 5 complete, 4 blocking incomplete, 4 usable incomplete, 2 out of scope and 1 follow-up. The CALL prompt of the shuffled run differs only by the option order, so the order alone causes these changes. Zheng et al. (2024) describe this preference for some option letters or positions.

### 5. Diagnostics

The hypothesis holds in part. On the blocking cards where OpenJev still answered BOX or STAY OUT, `missing_field` named the right field 19 times of 20 on validation and 7 of 9 on the mini-test. `required_known` said a field was unknown 16 and 7 times. OpenJev sees the gap but does not draw the policy's conclusion from it.

The diagnostics also show a bias. `missing_field` never answers "none": it gets 0 of 30 complete and 0 of 15 usable validation cards. `required_known` is wrong on all usable cards (0 of 15, 0 of 6). OpenJev treats every unknown field as needed, so part of its right answers on blocking cards comes from that bias, and it does not follow the rule's order of branches.

### 6. Cost

OpenJev needs no training run. A and B each took about four hours for their three seeds. It answers in 7.3 to 7.6 seconds per target with four questions, about 1.7 seconds for the call question alone. A answers in about 2 seconds on the same Mac: 300 validation answers in about 10 minutes (README section 11).

Its memory is high. The peak memory footprint of the server was 29.6 GB on validation, 29.3 GB on the shuffled run and 29.4 GB on the mini-test, with 6.9 GB resident and no swap. After the single smoke request, it was 10.8 GB. The footprint grows over the requests, most likely through MLX's buffer cache, which these runs do not measure. It is above the 20 GB MPS cap set for the adapters (`mps_memory_cap_gb`).

## Limits found in the runs

- **Few races:** the mini-test has 5 races, and its NO CALL targets fewer than 5. Several intervals touch 0.
- **Option order on validation only:** the shuffled run was not repeated on the mini-test.
- **Our own references:** the diagnostic references are ours, including track status as the blocking field under a safety car or VSC.
- **Prompt change:** OpenJev saw p01 without its answer-format paragraph, which baseline, A and B saw.
- **Memory:** the cause of the 29 GB footprint is not established.

## Conclusion

Zero-shot OpenJev is clearly better than the untuned baseline on validation and ahead of it on the mini-test, but A and B stay ahead on the call. It does not solve the usable incomplete cards that motivated the study. A threshold on its probabilities trades unjustified decisions for refusals less well than B's learnt NO CALL, and 16 of 100 validation calls change with the option order.

An upgrade round with described options and three averaged option orders (U1, below) does not change this.

For the final comparison, these results support keeping A and B as the compared systems. The team decided this on 21 October (decision 3.4.8 on #35): OpenJev stays out of the final comparison and 3.4 closed as an exploratory study. Had OpenJev been kept, its configuration would have been frozen first: revisions, file hashes, readout values, questions and τ = 0.59.

## Upgrade round U1 (post hoc)

This round tests whether prompt and readout changes alone can close part of the gap to the adapters, with no training and no examples. It was declared on 21 October, in the commit that adds `configs/openjev-upgrade.toml` and before any U1 run.

U1 targets two weaknesses seen in the runs above:
- OpenJev picks the right direction, BOX against STAY OUT, on only 41 of the 60 decidable validation targets.
- 16 of 100 calls change with the option order.

The declaration:
- **Variant:** the three CALL options carry descriptions made of p01 clauses and their direct consequences, in `configs/openjev-upgrade.toml`. One clause, that a known car behind too close to cover the pit loss plus 2.0 seconds means STAY OUT, follows from p01's "BOX only when" and is not stated in p01. The CALL question is asked in one request in the three cyclic orders of p01's order: (BOX, STAY OUT, NO CALL), (STAY OUT, NO CALL, BOX) and (NO CALL, BOX, STAY OUT). Each option sits at each letter once.
- **Readout:** the probabilities are averaged per label over the three orders, and the call is the most probable label of that mean. A tie between labels gives NO CALL. There is no diagnostic question. Model, helper, readout values, state and question wording are unchanged.
- **Rules:** argmax, and the τ rule of #35 unchanged.
- **Validation judgement:** argmax, and τ chosen leave one race out. For each of the 7 races, τ is chosen by the #35 rule on the other 6 and applied to it, then the 100 targets are scored once.
  - The original run gets the same computation: 60/100, with τ 0.55 for two races and 0.59 for the five others. That is against 64/100 when τ is chosen in-sample.
  - The in-sample τ is reported but never used to judge.
- **Mini-test:** U1 runs once on the 40 targets, whatever validation shows, with τ chosen on all 7 validation races. It is post hoc, because the original mini-test results were read before U1 was designed.
- **Decomposition:** the first order alone (descriptions, no averaging) is reported beside the mean, as a description only. It is never a mini-test candidate.
- **Known selection:** the descriptions and the averaging were chosen after reading the original validation results, including an offline two-order average. Leaving one race out protects τ only, so U1's validation numbers are optimistic.

### U1 runs

Both runs come from commit `f225ab0`, the declaring commit, with a clean tree. Every target got an answer, with no request error.

| Run | Targets | Seconds per target | Duration |
|---|---:|---:|---:|
| `2026-10-21_3-4-openjev-upgrade-validation` | 100 | 5.7 | 9.6 min |
| `2026-10-21_3-4-openjev-upgrade-mini-test` | 40 | 5.8 | 3.9 min |

A target sends about 2,840 prompt tokens over its three questions. The peak memory footprint was 29.3 GB and 29.4 GB, as before.

### U1 results on validation

CALL agreement out of 100, with the τ chosen in brackets:

| Rule | Original | U1, first order only | U1, mean of 3 orders |
|---|---:|---:|---:|
| Argmax | 56 | 55 | 58 |
| τ chosen leaving one race out (the declared judgement) | 60 | 55 | 59 |
| τ chosen on all 7 races (reported only) | 64 (0.59) | 63 (0.66) | 66 (0.46) |

Leaving one race out, U1's mean chooses τ 0.46 for four races and 0.51, 0.54 and 0.61 for the others. At that τ, it makes unjustified decisions on 0.300 of the targets whose answer is NO CALL and refuses 0.317 of the decidable ones. The original makes 0.150 and 0.433.

Other measures, original against U1's mean:

| Measure | Original | U1, mean of 3 orders |
|---|---:|---:|
| Right direction (BOX against STAY OUT) on decidable targets | 41/60 | 44/60 |
| Best a NO CALL rule could reach on these probabilities | 81/100 | 84/100 |
| Expected calibration error / Brier score | 0.132 / 0.520 | 0.089 / 0.502 |
| Argmax, complete cards | 16/30 | 21/30 |
| Argmax, usable incomplete cards | 9/15 | 12/15 |
| Argmax, follow-ups | 13/15 | 9/15 |
| Argmax, out of scope | 14/16 | 12/16 |
| Argmax, blocking incomplete cards | 4/24 | 4/24 |

Within one U1 request, the three orders give different argmax calls on 38 of the 100 targets. This measure differs from the 16 of 100 calls that changed between the original and the shuffled run.

### U1 results on the mini-test

τ = 0.46, chosen on all 7 validation races. These numbers are post hoc.

| Measure | Original | U1 | A | B |
|---|---:|---:|---:|---:|
| CALL agreement, argmax | 18/40 | 18/40 | 28/40 | 33/40 |
| CALL agreement, τ rule | 23/40 | 21/40 | | |
| Unjustified decisions at τ (Z) | 4/16 | 7/16 | 9/16 | 1/16 |
| Excessive refusals at τ (D) | 9/24 | 4/24 | 1/24 | 6/24 |
| Complete cards at τ | 4/12 | 6/12 | 10/12 | 12/12 |
| Blocking incomplete cards at τ | 7/10 | 4/10 | 1/10 | 10/10 |
| Usable incomplete cards at τ | 2/6 | 2/6 | 5/6 | 0/6 |
| Expected calibration error | 0.236 | 0.176 | | |

For A and B, the table gives their own answers, which have no τ.

The race bootstrap puts U1 at τ 0.175 below A on CALL agreement (-0.289 to +0.037) and 0.300 below B (-0.357 to -0.194). It is 0.275 above the baseline (+0.040 to +0.488).

### What U1 shows

- **No gain under the declared judgement.** On validation, U1 reaches 59 against 60 when τ is chosen leaving one race out. On the mini-test, it gets the same 18 at argmax and 21 against 23 at τ. Its two gains on validation, 2 points at argmax and 2 with the in-sample τ, do not carry to the mini-test.
- **The descriptions help where the rule is numeric, and cost elsewhere.** U1 is right on more complete and usable incomplete cards, and on 3 more decidable targets in direction. But it loses on follow-ups and out-of-scope requests. The first order alone does no better than the original.
- **Averaging calibrates but flattens.** The calibration error falls on both splits (0.132 to 0.089, and 0.236 to 0.176). The mean probabilities are lower, so τ falls from 0.59 to 0.46 and U1 abstains less. It makes more unjustified decisions and fewer excessive refusals, and the two cancel out.
- **The option order still matters.** The three orders of one request disagree on 38 of 100 validation targets. Averaging hides this in one number. It does not remove it.
- **The ceiling barely moves.** The best a NO CALL rule could reach rises from 81 to 84 of 100 on validation, B's score, and stays at 31 of 40 on the mini-test, below B's 33.

Prompt and readout changes alone, within this round, do not bring zero-shot OpenJev to the level of A or B. The conclusion above stands.

## Licence and attribution

The OpenJev Flash 9B weights are under CC BY-NC 4.0, which allows non-commercial use with attribution. This course project is non-commercial, and the repository does not redistribute the weights. The helper and serving files are under Apache 2.0, as is the base model Qwen3.5-9B. The report credits the model as: OpenJev Flash 9B, MLX 4-bit (`openjev/OpenJev-Flash-9B-MLX-4bit`, revision `33cbf372`), CC BY-NC 4.0, based on Qwen/Qwen3.5-9B (Apache 2.0).

## Run files

Each run folder holds:
- `cases.jsonl`, with the same hash as the baseline, A and B
- `answers.jsonl`, every answer with its probabilities, diagnostics and latency
- `outputs.jsonl` and `outputs-tau.jsonl`, the calls at argmax and at τ in the evaluator's format
- `summaries.json`, `calibration.json`, `diagnostics.json`, `tau.json` and `compare.json`
- `threshold.json`, in the validation run
- `upgrade.json`, in the U1 validation run
- `manifest.json`, `metrics.json`, `server.log` and a copy of the config the run used

The run folders are not in Git.

## References

- Bucher, M. J. J. and Martini, M. (2024). Fine-Tuned "Small" LLMs (Still) Significantly Outperform Zero-Shot Generative AI Models in Text Classification. [arXiv:2406.08660](https://arxiv.org/abs/2406.08660)
- Gondara, L. et al. (2025). Small or Large? Zero-Shot or Finetuned? Guiding Language Model Choice for Specialized Applications in Healthcare. [arXiv:2504.21191](https://arxiv.org/abs/2504.21191)
- Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. ICML. [arXiv:1706.04599](https://arxiv.org/abs/1706.04599)
- Lepagnol, P. et al. (2024). Small Language Models are Good Too: An Empirical Study of Zero-Shot Classification. LREC-COLING. [arXiv:2404.11122](https://arxiv.org/abs/2404.11122)
- Vajjala, S. and Shimangaud, S. (2025). Text Classification in the LLM Era: Where do we stand? [arXiv:2502.11830](https://arxiv.org/abs/2502.11830)
- Wen, B. et al. Know Your Limits: A Survey of Abstention in Large Language Models. TACL. [arXiv:2407.18418](https://arxiv.org/abs/2407.18418)
- Zheng, C. et al. (2024). Large Language Models Are Not Robust Multiple Choice Selectors. ICLR. [arXiv:2309.03882](https://arxiv.org/abs/2309.03882)
- OpenJev model cards: [OpenJev](https://huggingface.co/openjev/openjev), the larger model; [OpenJev Flash 9B](https://huggingface.co/openjev/OpenJev-Flash-9B); and [OpenJev Flash 9B, MLX 4-bit](https://huggingface.co/openjev/OpenJev-Flash-9B-MLX-4bit)
