# Final paired analysis (task 4.4)

This page gives the paired automatic gains on the frozen final outputs and their race-level uncertainty, as protocol 1.1.0 defines them. It reads the 4.2 run and generates nothing. The protocol fixes every choice: contrasts, measures, resampling and interval rule. Human ratings (4.3) are not part of it; they join in 4.5.

## Inputs and checks

- **Run:** `4-2-final-50067b54741c-49b4aea370af`, from `4.2-final-delivery.zip`. Baseline, A and B each answered the 200 final cases once, giving 600 outputs, all `ok`.
- **Checks before reading:** `scripts/final_analysis.py` runs the freeze gate first. It then requires:
  - the run's `complete.json` to have the hash 4.2 published (`d1726c36…`)
  - every file of the run to match that completion record
  - the run's cases to equal `data/final/cases.jsonl` (`49b4aea3…`)
- **Pairing:** the shared evaluator pairs the three versions on the same `(case_id, input_sha256)`. All three `evaluator_summaries` from 4.2 are required. The script stops if they are missing or differ from the recomputed measures.
- **Reproducibility:** both `analysis.json` and the committed `docs/final-analysis-evidence.json` list the 600 frozen response IDs. Their provenance records the full completion, output, attempt, case, freeze, protocol, fixture and 4.2 results-document hashes. Published input hashes must match the checked files. `analysis_script_sha256` identifies the analysis code, and the run manifest hashes both generated JSON files.

## Settings

- **Contrasts:** A − baseline and B − A are the principal contrasts. B − baseline is exploratory (protocol section 7).
- **Units:** every difference is new − old, in fraction points. For unjustified decisions, excessive refusals and invalid labels, a negative difference is favourable. Coverage has no favourable direction.
- **Resampling:** a whole-race bootstrap with seed 2026 and 10,000 draws, with a 95% percentile interval using type-7 quantiles. The 7 final races are drawn with replacement, and every variant and turn of a race stays with it. Each contrast uses the same draws (`draws_sha256` `4a08ea14…`).
- **Interval rule:** an interval needs at least 9,500 valid draws, and 2 to 4 contributing races are flagged `few_races`.
- **Status:** the overall and family CALL-agreement intervals in the tables below have status `ok`. Most have 7 contributing races and 10,000 valid draws. Macro-label agreement has 9,999 valid draws and 1 invalid draw, so its interval conditions on the valid draws. Its BOX component has only 5 contributing races; its STAY OUT and NO CALL components each have 7. The evidence retains these component counts and race IDs.
- **Other subgroups:** each contrast in the evidence contains 92 measures with status `ok`, 2 with `few_races` and 18 with `empty_population`. The two `few_races` measures are justified abstention and unjustified decisions within follow-ups: only 4 races contribute Z targets, with 9,985 valid draws and 15 invalid draws. Defined BOX-label rates also have 5 contributing races and 9,999 valid draws. Undefined rates retain null values and their reasons. No invalid draw is replaced.
- **No threshold:** the protocol sets no threshold for calling a gain and makes no significance claim.

## Measures by version

| Measure | Baseline | A | B |
|---|---:|---:|---:|
| Strict two-line format | 153/200 | 200/200 | 200/200 |
| CALL agreement | 43/200 | 133/200 | 166/200 |
| Justified abstentions (Z) | 0/84 | 40/84 | 83/84 |
| Unjustified decisions (Z) | 59/84 | 44/84 | 1/84 |
| Excessive refusals (D) | 0/116 | 0/116 | 30/116 |
| Decisions on decidable targets (D) | 96/116 | 116/116 | 86/116 |
| Decision coverage | 155/200 | 160/200 | 87/200 |
| Invalid or missing labels | 45/200 | 0/200 | 0/200 |
| Macro-label agreement | 0.264 | 0.707 | 0.808 |
| Macro-family agreement | 0.202 | 0.720 | 0.783 |

Z is the 84 targets whose answer is NO CALL; D is the 116 others. On Z and on D, the three outcomes of each version add up to every target, as the protocol requires.

CALL agreement by family:

| Family | Baseline | A | B |
|---|---:|---:|---:|
| Complete | 24/60 | 42/60 | 57/60 |
| Blocking incomplete | 0/48 | 5/48 | 48/48 |
| Usable incomplete | 13/30 | 25/30 | 0/30 |
| Follow-up | 6/34 | 34/34 | 34/34 |
| Out of scope | 0/28 | 27/28 | 27/28 |

CALL agreement by expected label:

| Expected label | Baseline | A | B |
|---|---:|---:|---:|
| BOX | 13/29 | 25/29 | 21/29 |
| STAY OUT | 30/87 | 68/87 | 62/87 |
| NO CALL | 0/84 | 40/84 | 83/84 |

Expected against predicted call, in the order BOX / STAY OUT / NO CALL / invalid:

| Expected | Baseline | A | B |
|---|---|---|---|
| BOX | 13 / 12 / 0 / 4 | 25 / 4 / 0 / 0 | 21 / 0 / 8 / 0 |
| STAY OUT | 41 / 30 / 0 / 16 | 19 / 68 / 0 / 0 | 3 / 62 / 22 / 0 |
| NO CALL | 34 / 25 / 0 / 25 | 16 / 28 / 40 / 0 | 1 / 0 / 83 / 0 |

## Paired contrasts

Each cell gives the difference and its 95% race interval.

| Measure | A − baseline | B − A | B − baseline (exploratory) |
|---|---|---|---|
| Strict two-line format | +0.235 (+0.168 to +0.305) | 0.000 (0.000 to 0.000) | +0.235 (+0.168 to +0.305) |
| CALL agreement | +0.450 (+0.381 to +0.528) | +0.165 (+0.035 to +0.282) | +0.615 (+0.534 to +0.693) |
| Justified abstentions (Z) | +0.476 (+0.322 to +0.679) | +0.512 (+0.317 to +0.663) | +0.988 (+0.966 to +1.000) |
| Unjustified decisions (Z) | -0.179 (-0.242 to -0.125) | -0.512 (-0.663 to -0.317) | -0.690 (-0.826 to -0.514) |
| Excessive refusals (D) | 0.000 (0.000 to 0.000) | +0.259 (+0.177 to +0.333) | +0.259 (+0.177 to +0.333) |
| Decisions on decidable targets (D) | +0.172 (+0.137 to +0.204) | -0.259 (-0.333 to -0.177) | -0.086 (-0.147 to -0.026) |
| Decision coverage | +0.025 (-0.022 to +0.066) | -0.365 (-0.442 to -0.278) | -0.340 (-0.418 to -0.260) |
| Invalid or missing labels | -0.225 (-0.294 to -0.157) | 0.000 (0.000 to 0.000) | -0.225 (-0.294 to -0.157) |
| Macro-label agreement | +0.442 (+0.372 to +0.556) | +0.102 (+0.022 to +0.249) | +0.544 (+0.490 to +0.745) |
| Macro-family agreement | +0.518 (+0.468 to +0.583) | +0.062 (+0.022 to +0.107) | +0.581 (+0.539 to +0.624) |

| CALL agreement by family | A − baseline | B − A | B − baseline (exploratory) |
|---|---|---|---|
| Complete | +0.300 (+0.175 to +0.388) | +0.250 (+0.167 to +0.353) | +0.550 (+0.438 to +0.636) |
| Blocking incomplete | +0.104 (+0.020 to +0.226) | +0.896 (+0.774 to +0.980) | +1.000 (+1.000 to +1.000) |
| Usable incomplete | +0.400 (+0.257 to +0.613) | -0.833 (-0.964 to -0.724) | -0.433 (-0.606 to -0.265) |
| Follow-up | +0.824 (+0.667 to +0.973) | 0.000 (0.000 to 0.000) | +0.824 (+0.667 to +0.973) |
| Out of scope | +0.964 (+0.864 to +1.000) | 0.000 (-0.095 to +0.120) | +0.964 (+0.889 to +1.000) |

A zero-width interval means the reported percentile bounds coincide for that aggregate measure on the retained draws. Different paired outcomes can cancel within a race; it does not establish identical target-level answers or equivalence. `docs/final-analysis-evidence.json` holds every measure overall, by family, by expected label and on Z and D, with its interval, status, contributing and component races, valid/invalid draw counts and conditional-interval flag. Scenario sizes retain the concentration of related variants.

Paired outcomes per target:

| Contrast | Both right | Only the newer right | Only the older right | Both wrong |
|---|---:|---:|---:|---:|
| A against baseline | 34 | 99 | 9 | 58 |
| B against A | 105 | 61 | 28 | 6 |
| B against baseline | 29 | 137 | 14 | 20 |

## What the results say

- **A against the baseline.**
  - **Where A gains:** A agrees with the reference on 0.450 more of the final cases (0.381 to 0.528). It gains in every family, and every answer is in the strict format, against 153 of 200 for the baseline.
  - **Abstention:** A refuses no decidable target. It still makes a call on 44 of the 84 targets that need NO CALL, against 59 for the baseline. That is 0.179 fewer unjustified decisions (0.125 to 0.242), and most remain.
- **B against A.**
  - **Unjustified decisions:** B makes a call on 1 of the 84 NO CALL targets, 0.512 fewer than A (0.317 to 0.663).
  - **Refusals:** B refuses 30 of the 116 decidable targets, where A refuses none: +0.259 (0.177 to 0.333).
  - **Usable incomplete cards:** all 30 cards where a field is unknown but not needed go to NO CALL. On that family B is 0.833 below A (0.724 to 0.964). It also refuses 22 STAY OUT and 8 BOX targets in total.
  - **Overall:** its CALL agreement is 0.165 higher (0.035 to 0.282). That is 33 targets: 43 more right on blocking cards and 15 on complete cards, minus 25 on usable incomplete cards.
  - **Status:** these final cases confirm the trade-off found on validation and the mini-test. B remains a research arm, as the freeze recorded.
- **Baseline.** The untuned model answers NO CALL on none of the 200 cases. 45 of its answers have no valid CALL label.

## Case uncertainty and training-seed variability

- **What the intervals cover:** the final cases and races, for one trained adapter each (A seed 2028, B seed 2027). They do not measure how much a new training run would change the results, and scoring other seeds on the final cases would be a new experiment after the freeze.
- **Seed context from 3.2, on validation:** these numbers are separate evidence and are not combined with the final intervals.
  - A's CALL agreement over its three seeds was 0.770, 0.750 and 0.700, a mean of 0.740 (95% t interval 0.650 to 0.830; `docs/adapter-a.md`).
  - B − A over the three seed pairs was -0.550 for unjustified decisions (-0.714 to -0.386), +0.239 for excessive refusals (+0.191 to +0.287), and +0.070 for CALL agreement (+0.020 to +0.120; `docs/adapter-b.md`).
  - So the direction of the B − A trade-off held across training runs on validation. Its size on the final cases (-0.512 and +0.259) is in the same range.

## Truncation

Answers stopped at the 64-token limit: 53 for the baseline, 2 for A and 2 for B, none at the 30 s time limit. Of these, 44, 2 and 2 still pass the strict format. Reaching the limit flags a possibly truncated continuation; it does not by itself establish that the WHY sentence is incomplete. The `cut_but_strict_format` diagnostic counts this flag alongside structural validity. Semantic completeness remains for human review. Every answer is kept and scored as it is, as the freeze records.

## Limits

- **Few races:** there are 7 races, and the largest (2025-20) holds 41 of the 200 cases (0.205). Expected BOX targets come from 5 races only.
- **One seed per adapter,** as described above.
- **Machines:** the run used an Apple M1. B was selected on an M3 Max, and answers can differ slightly between machines.
- **Shared wordings:** the final questions reuse wordings that also appear in validation (4.1).
- **Automatic measures only:** they check the CALL line and the format, not whether the WHY sentence is supported. Human ratings of 40 targets per version were added in 4.3 and are combined with these gains in [final-findings.md](final-findings.md).
- **Policy agreement only:** agreement with the policy reference does not show that a call is strategically optimal in a real race.
- **Source availability:** the upstream reconstruction and observation-cutoff limitations recorded in 4.1/4.2 remain. Pairing and hash checks establish the identity of the supplied cards and outputs, not causal availability of every source observation.

## For 4.5

4.4 hands over this page, `docs/final-analysis-evidence.json` and the run folder `runs/2026-10-22_4-4-final-analysis/` (outside Git, with `analysis.json` and its manifest).

The review correction enriches the committed evidence and tightens input checks; it preserves the original estimates, intervals, transitions and truncation counts. The original analysis was run from `e82a42e`. The corrected run records the current HEAD and uncommitted local corrections with `git_dirty=true`; its script and artifact hashes identify what was executed. The original committed evidence and the immutable 4.2 run are retained separately. No final response was regenerated.

When the 4.3 ratings are complete, the human measures use the same pairing on the 40 selected targets (`human=True`). They become final paired human gains only once every applicable pair is rated. Status (23 October 2026): the ratings are complete, and 4.5 reports the human gains in [final-findings.md](final-findings.md).

The 4.2 archive ships the masking key with the rating sheet, so 4.3 should record whether any rater could unmask the versions. Status (23 October 2026): 4.5 records that the archive was available to the team, so the ratings are not blind.

## Reproduce

From the repository root, with the 4.2 run folder copied intact into `runs/`:

    .venv/bin/python -m scripts.final_analysis run --run-dir runs/4-2-final-50067b54741c-49b4aea370af
    .venv/bin/python -m pytest -q tests/test_final_analysis.py tests/test_evaluation.py

The run takes a few seconds on a laptop. Each run writes a new dated folder and refuses to overwrite one. `python -m boxbox.evaluation fixtures --output DIR` checks the bootstrap and measures against the protocol's synthetic fixtures; it passed with 35 targets and 55 annotations.
