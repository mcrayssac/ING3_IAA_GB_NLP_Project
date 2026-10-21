# OpenJev zero-shot baseline (task 3.4)

This study asks whether a recent zero-shot decision model can make BoxBox's pit call as well as, or better than, the fine-tuned adapters A and B, without any training. The model is OpenJev Flash 9B (`openjev/OpenJev-Flash-9B-MLX-4bit`), run locally on the M3 Max. It answers the CALL line on the same validation and mini-test targets as baseline, A and B.

It is an exploratory study, as decided on #35 on 21 October. It stays outside the 3.5 freeze. If the team later wants OpenJev in the final comparison, its configuration is frozen first, and that is recorded as an exception to the passed freeze before 4.2 scores its CALL line.

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
| Limits | up to 52 options per pass, prompts up to 16,384 tokens |
| Licence | weights under CC BY-NC 4.0 (non-commercial use with attribution), helper and serving files under Apache 2.0 |

The model's authors report:
- 186 of 231 public JevBench items (80.5%) for this build
- on their 10,000 text decisions, 84.0% for OpenJev against 80.4% for the same base model before their tuning
- a Brier score of 0.19 on their own evaluation
- answers that change when the options are shuffled in 2.3% of 2,000 tests, down from 18.5% before tuning

No paper or independent evaluation is cited for these figures. Part of this study is to see whether they hold on our cards.

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
   - Hypothesis: A and B keep a higher CALL agreement than OpenJev on complete cards, where the rule is applied to numbers they were trained on.
   - Measured by CALL agreement by family on validation and the mini-test.
2. **Is a threshold on calibrated probabilities a better way to abstain than B's learnt NO CALL?**
   - Abstention methods usually set a threshold on a calibrated confidence (Wen et al., survey in TACL). But that survey notes that whether a query "is answerable at all" is "difficult to model in terms of model confidence". In BoxBox, NO CALL has two causes: a missing required field, which is about answerability, and an out-of-scope request.
   - Hypothesis: the threshold lowers unjustified decisions on out-of-scope requests more easily than on cards with a missing required field. Unlike B, OpenJev does not refuse the usable incomplete cards, because it was never trained to link an unknown field with NO CALL.
   - Measured by the risk and coverage curve against baseline, A and B, with each NO CALL cause and the usable incomplete cards reported apart.
3. **Are its probabilities calibrated on our cards?**
   - Hypothesis: calibration is worse on our cards than the Brier of 0.19 its authors report, since race cards are far from their data.
   - Measured by Brier, ECE and the reliability diagram on validation, then on the mini-test with nothing refitted.
4. **Does option order change its calls?**
   - Large language models favour some option letters when answering multiple-choice questions, whatever the options say (Zheng et al. 2024). OpenJev also reads its answer from option letters, and its authors report fixing most of that bias.
   - Hypothesis: the share of changed calls on our cards stays close to the reported 2.3%.
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

## References

- Bucher, M. J. J. and Martini, M. (2024). Fine-Tuned "Small" LLMs (Still) Significantly Outperform Zero-Shot Generative AI Models in Text Classification. [arXiv:2406.08660](https://arxiv.org/abs/2406.08660)
- Gondara, L. et al. (2025). Small or Large? Zero-Shot or Finetuned? Guiding Language Model Choice for Specialized Applications in Healthcare. [arXiv:2504.21191](https://arxiv.org/abs/2504.21191)
- Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. ICML. [arXiv:1706.04599](https://arxiv.org/abs/1706.04599)
- Lepagnol, P. et al. (2024). Small Language Models are Good Too: An Empirical Study of Zero-Shot Classification. LREC-COLING. [arXiv:2404.11122](https://arxiv.org/abs/2404.11122)
- Vajjala, S. and Shimangaud, S. (2025). Text Classification in the LLM Era: Where do we stand? [arXiv:2502.11830](https://arxiv.org/abs/2502.11830)
- Wen, B. et al. Know Your Limits: A Survey of Abstention in Large Language Models. TACL. [arXiv:2407.18418](https://arxiv.org/abs/2407.18418)
- Zheng, C. et al. (2024). Large Language Models Are Not Robust Multiple Choice Selectors. ICLR. [arXiv:2309.03882](https://arxiv.org/abs/2309.03882)
- OpenJev model cards: [OpenJev](https://huggingface.co/openjev/openjev) and [OpenJev Flash 9B, MLX 4-bit](https://huggingface.co/openjev/OpenJev-Flash-9B-MLX-4bit)
