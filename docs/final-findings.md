# Final findings (task 4.5)

This page joins the human review of task 4.3 to the paired gains of task 4.4, gives a verdict on the two hypotheses and discusses five cases from the final answers. It reads the frozen outputs of 4.2 and generates nothing. Automatic measures come from [final-analysis-evidence.json](final-analysis-evidence.json). Human measures, the case records and the audit counts come from [final-findings-evidence.json](final-findings-evidence.json).

## Inputs and checks

- Run: `4-2-final-50067b54741c-49b4aea370af`. Baseline, A and B each answered the 200 final cases once, giving 600 outputs. `scripts/final_findings.py` runs the 4.4 checks first: the freeze gate, the completion record and the case hash.
- Ratings: 120 rows, the 40 targets selected in 4.1 for each of the three masked versions. Paul PITIOT is the primary rater of all 120 rows ([#22](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/22)). The sheet carries one timestamp, 22 October at 11:07, which stamps the sheet and not each row.
- Second review: 55 rows need one, because factuality is 0 or 1 or a sensitivity flag is set. Maxime CRAYSSAC confirmed the primary scores and reasons of all 55 on 22 October, with the verdict "agrees" and no independent scores. This page therefore reports no agreement rate and no adjudicated means. Every human number below uses the primary scores.
- Proposed scores: 4.3 showed proposed scores and reasons beside each row. The rater kept them on 107 of 120 rows and changed 13 ([#22](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/22)).
- Masking: the full 4.2 archive names the versions and was available to the team, so the ratings are not blind.
- Statistics: the whole-race bootstrap of 4.4 on the 40 reviewed targets (seed 2026, 10,000 draws, 95% type-7 percentile interval, 7 races). An interval with 2 to 4 contributing races is flagged `few_races`.
- Reconciliation: the script stops unless three checks pass.
  - The primary scores of the second-review sheet equal the initial ratings that 4.3 imported (`b72083e1…`).
  - The automatic summaries recomputed from the outputs equal the ones 4.2 recorded.
  - Every overall, family, label and eligibility measure in the 4.4 evidence equals the recomputed one.

## Automatic measures

These are the 4.4 results on the 200 final cases, with both principal contrasts. Z is the 84 targets whose reference is NO CALL and D is the 116 others.

| Measure | Baseline | A | B | A − baseline | B − A |
|---|---:|---:|---:|---|---|
| Strict two-line format | 153/200 | 200/200 | 200/200 | +0.235 (+0.168 to +0.305) | 0.000 (0.000 to 0.000) |
| CALL agreement | 43/200 | 133/200 | 166/200 | +0.450 (+0.381 to +0.528) | +0.165 (+0.035 to +0.282) |
| Justified abstentions (Z) | 0/84 | 40/84 | 83/84 | +0.476 (+0.322 to +0.679) | +0.512 (+0.317 to +0.663) |
| Unjustified decisions (Z) | 59/84 | 44/84 | 1/84 | -0.179 (-0.242 to -0.125) | -0.512 (-0.663 to -0.317) |
| Excessive refusals (D) | 0/116 | 0/116 | 30/116 | 0.000 (0.000 to 0.000) | +0.259 (+0.177 to +0.333) |
| Decision coverage | 155/200 | 160/200 | 87/200 | +0.025 (-0.022 to +0.066) | -0.365 (-0.442 to -0.278) |
| Invalid or missing labels | 45/200 | 0/200 | 0/200 | -0.225 (-0.294 to -0.157) | 0.000 (0.000 to 0.000) |

By family, CALL agreement on blocking-incomplete cards goes 0/48, 5/48 and 48/48 for baseline, A and B. On usable-incomplete cards it goes 13/30, 25/30 and 0/30.

## Human review of the 40 reviewed targets

The 40 targets are 8 per family, chosen from card metadata before any answer existed. The means describe this balanced design and not the whole final distribution. Axes score 0 to 2. History and scope apply to 8 targets each, and justified abstention covers the 18 reviewed targets whose reference is NO CALL.

| Measure (targets) | Baseline | A | B | A − baseline | B − A |
|---|---:|---:|---:|---|---|
| Correctness mean (40) | 0.300 | 1.175 | 1.375 | +0.875 (+0.675 to +1.079) | +0.200 (-0.108 to +0.538) |
| Role and format mean (40) | 1.000 | 1.925 | 2.000 | +0.925 (+0.756 to +1.079) | +0.075 (0.000 to +0.175) |
| Factuality mean (40) | 0.800 | 1.300 | 1.450 | +0.500 (+0.122 to +0.875) | +0.150 (-0.103 to +0.476) |
| History mean (8) | 1.625 | 1.875 | 2.000 | +0.250 (0.000 to +0.800), few races | +0.125 (0.000 to +0.400), few races |
| Scope mean (8) | 0.875 | 1.500 | 1.875 | +0.625 (0.000 to +1.125) | +0.375 (-0.286 to +1.000) |
| WHY supported (40) | 15/40 | 26/40 | 29/40 | +0.275 (+0.073 to +0.475) | +0.075 (-0.051 to +0.238) |
| Justified abstention (18) | 0/18 | 7/18 | 16/18 | +0.389 (+0.227 to +0.562) | +0.500 (+0.312 to +0.650) |

WHY supported counts the responses with factuality 2. Justified abstention counts a strict-format NO CALL with 2 on every applicable axis.

Correctness mean by family, 8 targets each:

| Family | Baseline | A | B |
|---|---:|---:|---:|
| Complete | 0.000 | 1.000 | 1.250 |
| Blocking incomplete | 0.000 | 0.000 | 1.750 |
| Usable incomplete | 0.125 | 1.500 | 0.000 |
| Follow-up | 0.500 | 1.875 | 2.000 |
| Out of scope | 0.875 | 1.500 | 1.875 |

On the 40 targets the parsed call matches the reference for 7 baseline answers, 28 from A and 32 from B. Among those matches, 4, 3 and 3 get 0 on correctness because the WHY is false. Three baseline answers have no matching call and still earn 2 on correctness. Ten baseline rows carry the invented-number flag, against 1 for A and none for B.

## Hypotheses

| Hypothesis | Measure | Result | Verdict |
|---|---|---|---|
| H1: B gives fewer unjustified answers than A on cards with insufficient information | Decisions on the 84 NO CALL targets, B − A | -0.512 (-0.663 to -0.317), 1/84 against 44/84 | Supported: the interval lies entirely below zero |
| H2: that gain keeps usefulness on cards that support a decision, within five percentage points | Excessive refusals on the 116 decidable targets, B − A | +0.259 (+0.177 to +0.333), 30/116 against 0/116 | Not supported: the interval lies entirely above 0.050 |

The human review points the same way on H1: 16 of 18 reviewed abstentions are justified for B, against 7 of 18 for A (+0.500, 0.312 to 0.650). On H2 it shows where the refusals fall. B scores 0.000 on correctness for the 8 reviewed usable-incomplete cards, against 1.500 for A, and none of its 8 WHY sentences is supported, against 6 of 8 for A. The validation runs of 3.2 gave the same direction over three seeds (see [final-analysis.md](final-analysis.md)).

## What the combined results say

- A over the baseline: CALL agreement rises by 0.450 and the human correctness mean by 0.875. Both intervals exclude zero, and the human factuality mean also rises (+0.500).
- B over A on abstention: B abstains on 83 of the 84 NO CALL targets, and the reviewers find a justified abstention on 16 of the 18 reviewed ones. A abstains on 40 of 84, and 7 of the 18 reviewed ones are justified.
- B over A on usefulness: B refuses 30 decidable targets, all 30 of the usable-incomplete family. They split into 22 STAY OUT and 8 BOX references.
- Overall quality: the pooled human means do not separate B from A (correctness +0.200, -0.108 to +0.538). B gains on blocking-incomplete cards (1.750 against 0.000) and loses on usable-incomplete cards (0.000 against 1.500). The pooled figure depends on giving each family the same weight.
- CALL agreement against human reading: a matching call can carry a false reason (3 of 28 for A, 3 of 32 for B), so agreement overstates quality a little for both. It does not change their order.
- The baseline and NO CALL: 4.4 states that the baseline answers NO CALL on none of the 200 cases. That holds for parsed labels. 19 of its 45 invalid answers open with NO CALL and no `CALL:` prefix, 15 of them on NO CALL targets. Strict parsing credits none, and crediting all 15 would give at most 15 of 84 against 40 for A and 83 for B.

## Five cases

One case per mechanism, among the 40 reviewed targets. The mechanisms come from the 4.4 findings. Within a mechanism the case is the first by SHA-256 of `boxbox-eval|1.1.0|2026|findings|<mechanism>|<case id>|<version>`. The rule was fixed in the script before any case was read, and `docs/final-findings-evidence.json` records how many candidates each mechanism had. Two cases contradict a hypothesis or a 4.4 statement (cases 2 and 4), and case 5 qualifies a headline measure.

### Case 1: A decides where the policy refuses

7 candidates. Case `F-114`, race 2023-14, blocking-incomplete.

- Input: car 27, lap 51 of 52, MEDIUM tyres aged 14 laps, green flag, gap ahead 0.0 s, gap behind UNKNOWN, pit loss 24.1 s. "Is now a good time for car 27 to come in?"
- Reference: NO CALL, because the gap behind is missing.
- Answers: A says "CALL: BOX" with "...a 0.0-second gap ahead and no car behind, so the rule calls for boxing." B gives NO CALL with the reference reason. The baseline says STAY OUT with a wrong threshold and is cut at the token limit.
- Human reading: A gets 0 on correctness and 0 on factuality ("Treats the UNKNOWN gap behind as 'no car behind'"). B gets 2, 2, 2. The baseline gets 0 and 0 and is flagged for an invented number.
- Likely cause: A trained on complete cards only, so a card with an unknown gap behind falls outside what it saw. It reads it as the no-car-behind case it knows.
- Limits: this pattern holds for 7 of the 8 reviewed blocking-incomplete cards and matches the 5 of 48 CALL agreement of A on that family. The cause is a reading of the training design, not a tested result.

### Case 2: B refuses a card that supports a decision

6 candidates. Case `F-135`, race 2025-20, usable-incomplete. This case contradicts H2.

- Input: car 43, lap 63 of 71, SOFT tyres aged 14 laps, green flag, gap ahead 4.9 s, no car behind, pit loss UNKNOWN. "Should we call car 43 in this lap?"
- Reference: BOX, because the tyres are past the SOFT trigger and no car is behind.
- Answers: A says BOX with the reference reason. B says "CALL: NO CALL" with "The card is missing a valid pit-loss estimate, so the rule cannot assess a pit stop." The baseline says BOX with a false comparison of 4.9 s against 2.0 s.
- Human reading: A gets 2, 2, 2. B gets 0 on correctness and 0 on factuality ("False policy claim that the missing pit loss blocks this branch", and with no car behind the pit loss is not needed). The baseline gets 0 and 0 despite the right label.
- Likely cause: the 15% of B examples that teach NO CALL link any missing field to a refusal. B applies it to a missing field the rule ignores in this branch.
- Limits: the usable-incomplete family has 15 real cards and 15 built by removing an ignored field, so it tests this situation more than real races would. B refuses all 30 of them, which matches the case. Six of the 8 reviewed cards fit the pattern where A is right.

### Case 3: A and B succeed where the baseline fails

13 candidates. Case `F-081` turn 2, race 2024-07, follow-up.

- Input: car 31, lap 23 of 63, MEDIUM tyres aged 22 laps, gap ahead 6.7 s, gap behind 0.2 s, pit loss 27.3 s. The earlier answer was STAY OUT with its reason. The user asks "What is that call based on?"
- Reference: STAY OUT, with the same reason as the earlier answer.
- Answers: B repeats the reference sentence. A opens with "The call uses the card and the rule, not a previous answer." and then gives the same reasoning. The baseline answers in free text without a CALL line and cites "22 laps (between 12 and 18 laps)".
- Human reading: B gets 2 on all four applicable axes. A gets 2 on correctness, factuality and history, and 1 on role and format because the WHY is cut before its last words. The baseline gets 0 on all four, with a flag for an invented number.
- Likely cause: both adapters saw follow-up dialogues in training and return to the card, while the baseline improvises.
- Limits: 13 of the 16 reviewed follow-up and out-of-scope targets fit this pattern. A's WHY stops before its last words here, and 2 of A's 200 final answers stop at the 64-token limit.

### Case 4: the baseline gives no valid call on a NO CALL target

6 candidates. Case `F-101`, race 2024-07, out-of-scope. This case qualifies a 4.4 statement.

- Input: lap 38 of 63, MEDIUM tyres aged 4 laps, green flag. "Will the track get wet later?"
- Reference: NO CALL, because the dry historical card has no weather data.
- Answers: A and B give the reference answer word for word. The baseline writes "NO CALL", a blank line, then "WHY: The current race card does not provide information about track conditions changing later in the race. Track conditions are not forecasted or indicated on the card."
- Human reading: the baseline gets 2 on correctness, 1 on factuality (the card does state the current surface and track status), 1 on role and format and 2 on scope. A and B get 2 on every applicable axis.
- Likely cause: the baseline follows the format only in part, and the parser requires the `CALL:` prefix.
- Limits: the parsed baseline has no NO CALL, so its automatic justified-abstention count is 0 of 84, and its human count is 0 of 18 because that measure also requires the strict format. 15 of its answers on NO CALL targets are of this kind.

### Case 5: right call, wrong reason

10 candidates. Case `F-058`, race 2023-16, complete.

- Input: car 55, lap 12 of 54, MEDIUM tyres aged 11 laps, green flag, gap ahead 1.4 s, gap behind 2.9 s, pit loss 20.2 s. "Should we call car 55 in this lap?"
- Reference: STAY OUT, because 11 laps is below the 12-lap trigger for MEDIUM tyres.
- Answers: A gives the reference answer. B says STAY OUT with "The card shows a 1.4-second gap ahead, above the 2.0-second opportunity threshold, so the rule is to stay out." The baseline says BOX, claims 11 laps is above 18 and says no car is behind.
- Human reading: A gets 2, 2, 2. B gets 0 on correctness and 0 on factuality ("1.4 s is below, not above, 2.0 s; age is decisive"). The baseline gets 0 and 0.
- Likely cause: B reproduces the shape of a decision sentence and attaches it to the wrong field.
- Limits: the call matches, so the automatic measures count B as right. Such rows are 3 of B's 32 matching calls on the reviewed targets and 3 of 28 for A.

## Scope changes and negative results

- H2 is not supported. B cuts unjustified decisions by 0.512 and refuses 0.259 more decidable targets.
- A still decides on 44 of the 84 NO CALL targets, and gets 5 of 48 blocking-incomplete cards right.
- The human review does not separate B from A on overall correctness or factuality. It separates them on abstention.
- B's gain on blocking-incomplete cards (+0.896 in CALL agreement) comes with a loss on usable-incomplete cards (-0.833).
- Data source: OpenF1 replaced FastF1 in 2.1, because the FastF1 source refused access ([#6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/6)).
- Audience: pit strategists and paddock team members replaced content creators and analysts ([#10](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/10)).
- Seeds: A and B were each trained with three seeds ([#13](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/13)). The final run scores one selected adapter each, A seed 2028 and B seed 2027. The second-checkpoint study stays deferred.
- Schedule: B trained overnight from 20 to 21 October and the freeze moved to 21 October, recorded at 14:49 ([#17](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/17), [#19](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/19)).
- OpenJev (3.4) ran as an exploratory study and sits outside this comparison ([#35](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/35)).
- B was kept, so the A/B hypotheses are tested.
- The Experimental milestone (data v2, policy 2.0, replay) lives on `main-experimental`. Nothing on this page uses it.

## Limits

- Few races: 7 final races, and 2025-20 holds 41 of the 200 cases (0.205). History and scope have 8 reviewed targets each.
- One rater: Paul PITIOT scored all 120 rows with proposed scores beside them and without masking. The second review is a confirmation with no independent scores.
- Balanced review sample: 8 targets per family. It stresses rare failures and does not estimate prevalence.
- One seed per adapter and one machine for scoring (an Apple M1). Intervals cover cases and races, not new training runs.
- Policy agreement: the reference is the stated rule. A matching call does not show that the decision is optimal in a real race.
- Shared wordings: the final questions reuse wordings that also appear in validation (4.1).
- Cases: five cases illustrate a mechanism. The candidate counts say how common each one is among the 40 targets.

## What 5.3, 5.4 and 5.5 can take

- The report and the notebook can use the two measure tables, the hypothesis table and the five cases. Numbers in the report must come from these tables or from the two evidence files.
- The video can state one result in each direction: B almost never decides when it should abstain, and it also refuses every usable-incomplete card.

## Reproduce

From the repository root, with the 4.2 run folder copied intact into `runs/`, the completed 4.3 sheet with its second reviews and the initial ratings of 4.3:

    .venv/bin/python -m scripts.final_findings run --run-dir runs/4-2-final-50067b54741c-49b4aea370af --sheet review-rated-second.csv --initial ratings-initial.jsonl
    .venv/bin/python -m pytest -q tests/test_final_findings.py tests/test_final_analysis.py tests/test_human_review.py tests/test_evaluation.py

The run takes about 12 seconds and writes a new dated folder, `runs/<date>_4-5-final-findings/`, with `evidence.json`, `ratings.jsonl` and `manifest.json`. It refuses to overwrite one. The committed evidence is a copy of `evidence.json`. Hashes of the run behind this page:

- Sheet with second reviews: `ab1f548b…c007` (primary sheet `792b9fcb…a297`)
- Initial ratings of 4.3: `b72083e1…2eaf`
- Ratings with second reviews: `c57677c0…5e17`
- 4.4 evidence file: `d6579ace…`
- Analysis script: `69a480cf…`
- Evidence file of this page: `dab86257…`
