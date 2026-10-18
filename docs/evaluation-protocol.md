# Evaluation protocol (task 2.3a)

**Protocol ID:** `boxbox-eval`; **version:** `1.0.0`; **status:** proposed for review, not accepted or frozen. No model outputs were used to choose these rules. The examples and scores in [evaluation-fixtures.json](../reference/evaluation-fixtures.json) are synthetic calibration expectations, not human observations or performance evidence.

## 1. Authority, scope and acceptance

This is the proposed normative source for evaluation. It implements [issue #8](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/8) and the five criteria in the [assignment](../instructions/mini_projet_2_agent_conversationnel.pdf). The integrated [card contract](race-card-contract.md), [`decide` and `format_answer`](../boxbox/rules/decision.py), and [five original conversations](../reference/fixtures.json) remain the policy authority. Agreement measures a pedagogical policy, **not optimal real F1 strategy**. This protocol changes neither thresholds nor those conversations.

The implementation base is `4c89e81667fbaab6ac7a78882b0a29aeb77ba23a`. Task 1.4 was integrated through `4e5720d03e76d718dcaa583480dc539b28c42168`; [#3's closure comment](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/3#issuecomment-6249403917) reports Paul's review. Those historical test claims are not checks executed for 2.3a.

At the initial 18 October 2026 source check, [#40](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/40) was open at `d9bee5eba084fda495cc639d81dba2d7c06b413f`. A later check found it still open at `5dfa88f592d80388e68ae7e554901b4fd909e1ce`; its latest author comment reports fixes following a second reviewer's reading, while GitHub's formal review list is empty. That report does not identify a verified teammate acceptance of 2.1. The proposed data protocol was read at both revisions. The OpenF1/Jolpica source change, rounding and interfaces remain unmerged proposals; the implementation base still names FastF1. Remote main advanced separately to `8df01f9a0d13260d520e97de71d7fd5494254db2` (merge #39, task 1.6), without changing this branch's base/HEAD. This does not block this provider-independent rubric: use the accepted card, not a provider-specific reconstruction. No final cards, outputs or prior edit history of final counts were inspected. This task neither validates nor integrates 2.1.

One upstream interpretation remains for 2.1's review: its latest proposed protocol says the gap behind becomes known when the follower crosses the line in the first seconds of lap L, and documents actual total race distance/dry-surface proxies as limits. Reconcile those availability conventions with the accepted pre-decision card cutoff before using real inputs; label conformity alone cannot establish causal availability. Do not relax this rubric's evidence rule to accommodate a source. This is an external data-contract handoff, not a reason to redesign reconstruction or delay these synthetic calibration definitions.

No blocking source contradiction was found. Ordinary choices made here are: context-dependent references, fixed histories, exclusive sampling families with overlapping descriptive attributes, micro estimates with label/family summaries, and whole-race paired uncertainty. The sections below give their rationale. A teammate review and a team acceptance record are still required; a draft or self-check is not acceptance.

| Requirement from #8 | Decision | Deliverable | Verification before acceptance |
|---|---|---|---|
| Five 0/1/2 axes | Response-independent applicability; explicit anchors and `N/A` | Section 4; annotated response fixtures | Check every anchor, including intermediate scores and empty answers |
| Automatic versus human checks | Structural format and CALL metrics separated from WHY judgment | Sections 3–5 | Compare synthetic expected flags and hand counts; do not match WHY literally |
| Five families | Exclusive primary family, independent card/history/scope attributes | Section 2 | Cross-check overlaps, including incomplete follow-ups |
| Pairing and uncertainty before results | Immutable target inputs; paired race-cluster bootstrap | Sections 6–7; paired toy table | Duplicate/missing-pair, identical-version, empty-category and one-race checks |
| Same 40 cases/version, masking | Fixed quotas, metadata-only deterministic selection, separate code key | Section 8 | 40 distinct targets; 120 or explicitly 80 outputs; caps and slot checks |
| Closure evidence | Protocol/fixture checks plus independent teammate review | Sections 1 and 10 | Review and integration/accessibility links remain to be supplied |

Record acceptance only with its actual reviewer, decision link and timestamp. Future `manifest.json` files must retain the existing [run fields](../boxbox/runs.py) and add `extra.evaluation` containing `protocol_id`, `protocol_version`, `protocol_sha256` (exact UTF-8 file bytes), `fixtures_sha256`, `policy_git_commit`, `policy_source_sha256`, `cases_sha256`, `input_ledger_sha256`, `data_manifest_sha256`, `sampling_manifest_sha256`, `history_mode`, `retained_versions`, and `acceptance_record` (actual decision link, or `null` while proposed). Preserve the exact protocol/fixtures with the run. The existing `source_sha256` excludes docs/reference and is not their hash. These are future manifest additions, **not new `RunConfig` keys**; its unknown-key checks must stay meaningful.

Before results, a substantive change needs a new protocol version, reason, previous-version reference and real review/acceptance. Never adjust thresholds, quotas, denominators, selection priorities or interval settings to improve observed results. The accepted protocol/configuration is part of [3.5's freeze](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/19); final construction/inspection waits for that gate. A later defect needs an explicit correction decision, preserved original evidence and a new freeze where required; label any resulting analysis as a correction, not a prospectively fixed choice. No new experiment after the freeze. Do not silently rewrite an old run.

## 2. Targets, categories and the reference

One **case** is one target assistant reply to one `message`, given one current `card` and an ordered, fixed `history`. One **scored response** is one retained version's output (or explicit generation error) for that target. Earlier assistant messages supplied as context are not scored again. Two target turns in a conversation are two stable case IDs, with the same scenario ID and different turn indices. Selecting 40 targets means exactly 40 responses per version, regardless of how many context turns they contain.

Use these attributes, assigned from inputs/references before generation:

| Attribute | Definition |
|---|---|
| `card_state: complete` | Core identity/cutoff and supported dry/green context are valid; tyre age is valid; both gaps are KNOWN or well-formed NONE; pit loss and its cutoff are valid. Display-only omissions do not affect this classification. |
| `card_state: blocking_incomplete` | An absent, unknown or invalid policy input prevents a card-only decision (`decide` gives NO CALL). Includes deliberate malformed/cutoff probes. Record `input_issue` to distinguish missing, malformed, future-derived or unsupported-context probes; the last is included here as an explicitly labelled stress case, not as a missing measurement. |
| `card_state: usable_incomplete` | Some policy input is unavailable, but the ordered policy can still decide BOX or STAY OUT. Complete the classification by using this state whenever the card is not complete and still decidable. |
| `follow_up` | History is nonempty; the same card remains selected. |
| `history_sensitive` | Correctly answering the current question requires a referent, contrast or correction in that supplied history. Nonempty history alone is insufficient. |
| `out_of_scope` | The current request asks for a prohibited capability (live/wet strategy, forecasts, optimisation, betting, invented radio, etc.), or explicitly requests a decision in an unsupported context. Record the scope reason. Ordinary missing-data abstention alone does not set this flag. |

The **primary family** is exclusive: `out_of_scope` first, otherwise `follow_up` if history is nonempty, otherwise the card-state value (`complete`, `blocking_incomplete`, `usable_incomplete`). Thus a follow-up on a blocking card belongs to `follow_up` and also carries `card_state=blocking_incomplete`. An out-of-scope follow-up carries both attributes but occupies only one scope slot. Report attribute cross-tabs separately; do not sum overlapping attribute counts as a population.

### Reference annotation

For an ordinary in-scope call, invoke `boxbox.rules.decide(card)` at the pinned policy revision; do not reproduce its threshold logic in the evaluator. Store `policy_call` and its reason. For an in-scope follow-up the expected CALL is still this policy CALL, but a pre-reviewed annotation specifies the question's referent, required explanation/correction and acceptable paraphrases. There is no general exact-WHY oracle.

For an out-of-scope request, the contextual `expected_call` is NO CALL even on an otherwise BOX card. Set `oracle=message_annotation`, preserve `policy_call` separately and annotate the refused capability and the card/product limit. For a mixed request, refuse the unsupported component with NO CALL and explain that boundary; do not silently score only a supported fragment. These context annotations must be reviewed before generation; ambiguity that could change a label or applicability is a case-authoring defect to resolve then, not a model failure to relabel afterwards.

Allowed evidence is the current card, the pinned policy, and the same-card history/message for conversational intent. User or previous assistant assertions do not create race measurements. The current card overrides a stale number or false assertion in history; unknown current data cannot be recovered by trusting a prior claim. A card change/reset clears history; no facts transfer between cards. Scope limits, policy constants and arithmetic explicitly derived from card values are allowed evidence. For example, `21.0 + 2.0 = 23.0` is a policy calculation, not an invented observation. True external sporting facts remain unsupported if absent from these inputs; actual future outcomes and later timing are prohibited.

Preserve 1.4's distinctions: `null` is not zero; UNKNOWN, NONE with `seconds:null`, and KNOWN zero differ. A malformed NONE is invalid even on an otherwise unused branch. An irrelevant missing gap/pit loss does not force NO CALL; a missing display field cannot change the label. The reference includes age 11/12 and 17/18, ahead gap just below/equal/above 2.0, and behind gap just below/equal/above pit loss + 2.0. Equality and precision are those of `decide`; load JSON decimals without losing their precision. Upstream causality must also be checked from provenance: `decide` checks declared cutoffs, not the truth of source observations. Evaluation cannot repair upstream leakage.

## 3. Raw output and automatic parsing contract

The product response has exactly these two lines, with one CALL label:

```text
CALL: BOX | STAY OUT | NO CALL
WHY: <one English sentence grounded in the current card or its stated limits>
```

The alternatives on line one describe the allowed values; a real answer contains only one, e.g. `CALL: BOX`.

Retain `raw_response` verbatim before evaluation. For **strict structural format**, permit only CRLF → LF and removal of at most one final LF. No trimming, case folding, BOM removal, prefix extraction, punctuation repair, Markdown stripping or label substitution. After these two normalisations there must be exactly two lines: an exact allowed CALL line; then `WHY: ` plus a nonempty payload with no leading/trailing space or tab and no other line break. A second terminal LF, extra commentary, empty WHY, spaces around the CALL line or multiple labels fail. A status other than `ok` fails even if a partial response is available.

`extracted_call` is the label on an exact **first** CALL line after the same normalisations, independently of whether WHY/extra lines pass. Otherwise it is `null` (INVALID in tables); do not search later lines. A status other than `ok` has no extracted label. This deliberately allows a correct CALL with bad structure to appear as correct in CALL-only agreement and incorrect in strict format. Neither metric hides the other. A tolerant parser may be a separately named diagnostic; it never supplies primary labels or repaired outputs.

Automatic checks establish line structure, nonempty WHY and label membership. English, one meaningful sentence, relevance and grounding require human judgment. A period-counting regex cannot validate a sentence: `24.0` is a decimal, and abbreviations/punctuation can be ambiguous. A paraphrase with the same supported reasoning is fully acceptable; equality to `format_answer`'s WHY is only a fixture/reference check, never the general scoring rule.

## 4. Human rubric: 0–2, with 2 always better

Axes are independent; a good label cannot compensate for an invented reason. Applicability is fixed by the case before reading outputs. `correctness`, `role_format` and `factuality` always apply. `history` applies only if `history_sensitive=true`; `scope` only if `out_of_scope=true`. A first turn and an in-scope request receive no automatic points for the two untested skills.

Factuality assesses claims in WHY and any added text. A wrong CALL belongs to correctness and does not by itself imply an invented measurement; a false policy assertion used inside WHY does lower factuality. No assessable explanation, including an empty/error response, still gets factuality 0 rather than a vacuous factual success.

| Axis and object | 0 | 1 | 2 |
|---|---|---|---|
| `correctness`: current request, CALL and explanatory adequacy against the contextual reference | Wrong/missing CALL, unusable answer, or a decisive false/unsupported WHY, even with the right label | Right CALL, but a vague, incomplete or partly off-target explanation; no decisive contradiction | Right CALL and sufficient, relevant, supported explanation for the request, including the required limit/correction |
| `role_format`: two-line English policy explainer within its limits | No usable answer/label, abandons the role, fulfils a prohibited request, or guarantees optimal real strategy | Understandable intended answer with a minor breach: extra commentary, two sentences, unclear English, or ambiguous claims about limits | Exact two-line structure, one clear English WHY sentence, correct constrained role; wrong policy action alone is assessed on correctness |
| `history`: resolving the annotated conversational requirement | Ignores the required referent, repeats a false old value, transfers facts from another card, or provides no usable response | Keeps the relevant topic but misses part of the requested contrast/correction without asserting the false claim | Resolves the referent and explicitly handles the required contrast/correction using the current card |
| `scope`: recognition and treatment of the unsupported request | Attempts/provides the prohibited capability, or no usable refusal | Refuses with NO CALL but only says it cannot help, gives a vague boundary, or omits the requested explanation of the limit | NO CALL, names the unsupported capability and explains the relevant card/product limit without pretending to fulfil it |
| `factuality`: evidence for asserted facts, numbers and certainty | Invented/contradictory measurement, true but unauthorised external fact, false policy assertion, optimality guarantee, or empty/unassessable answer | Decisive facts/calculations are supported, but a non-decisive qualitative hedge or ambiguous assurance is not verifiable (e.g. “that may feel comfortable”) | Every factual claim is supported or explicitly derived, uncertainty/absence is respected, and there is no unsupported assurance |

Discriminating examples (all synthetic) are identified by response IDs in the fixtures:

- `paraphrase`: BOX at an equality with a differently worded, complete derivation is correctness 2, factuality 2. `right_call_wrong_why` and `invented_number`: BOX alone agrees, but a wrong tyre age or fabricated gap gives correctness 0 and factuality 0. A plausible undercut story absent from the card (`plausible_external_reason`) does the same; plausibility is not evidence.
- `vague_right_call`: BOX with “The card supports boxing” is correctness 1, factuality 2. `minor_assurance` has supported decisive arithmetic but an unverifiable non-decisive comfort hedge: factuality 1. `true_external_fact` inserts a true geographic fact absent from the inputs: factuality 0, even if the call's core reasoning is otherwise sound.
- `wrong_action`: a well-formatted BOX on 11-lap tyres is correctness 0, role/format 2; its merely restated age is factually supported. `optimal_promise` gets role/format 0 and factuality 0. These axes must not be averaged to hide such failures.
- `scope_vague`: NO CALL with “I cannot help with that” gets correctness 1 and scope 1. `scope_explained` gets 2 for both by naming forecasts/optimisation and the historical-card limit. A correct refusal with extra text may still have a good scope score but role/format 1.
- `history_partial` keeps the right call but fails to explain the requested contrast: correctness/history 1. `history_corrected` rejects a false old gap using the current card: history 2. `history_false` copies it: history 0 and factuality 0.
- `empty`, `generation_error`, and `invalid_label` score 0 on always-applicable axes; applicable history/scope also score 0. Non-applicable axes remain N/A. `extra_text` can keep correctness 2 and role/format 1 despite failing automatic strict format.

Store an inapplicable score as the literal JSON string `"N/A"` with an applicability reason. Store a not-yet-rated applicable score as `null`, with `rating_status=pending`; this is **missing**, not N/A or 0. Completed applicable scores are integers 0, 1 or 2 (booleans forbidden). Blank/error outputs are observable failures to rate, not missing ratings. Retain a short justification for every applicable score, and cite the input fact/limit for 0 or 1 and any dispute.

For each axis report applicable target count, rated count, missing count, N/A count, counts of 0/1/2, and `sum(scores) / rated_count` on its 0–2 scale. Denominator zero means `null` plus `no_applicable_scores`. A provisional mean with missing ratings must say incomplete; no final paired human gain until all intended applicable pairs on that axis are scored. Applicability must match across versions of a case. Keep initial and adjudicated summaries separate. Do not convert N/A to 2/0, use a fixed five-axis divisor, or present an overall five-axis grade. These stratified human means describe the selected review targets, not the entire final distribution.

## 5. Metrics and denominators

Let `U` be the immutable case ledger for one declared split/analysis; `N=|U|`. Let `E_i` be the contextual expected CALL; `P_i` the extracted CALL or INVALID; `S_i` the strict structural flag. `Z={i:E_i=NO CALL}` and `D={i:E_i in {BOX,STAY OUT}}`. Every scheduled case remains in U, including blank, malformed and explicit generation-error rows. Measures below are fractions (multiply by 100 only for display).

| Metric | Eligible population / denominator | Numerator | Direction and interpretation |
|---|---|---|---|
| `strict_format_rate` | All U / N | Count S_i=true | Higher; structural compliance only |
| `call_label_validity` | All U / N | Count P_i != INVALID | Higher; independent of WHY structure |
| `call_agreement` | All U / N | Count P_i=E_i | Higher; CALL-only policy/message agreement |
| `justified_abstention_call_rate` | Z / \|Z\| | Count P_i=NO CALL | Higher; justified **label**, not a claim that WHY is valid |
| `unjustified_decision_rate` | Z / \|Z\| | Count P_i in {BOX,STAY OUT} | Lower; answering when the reference requires abstention |
| `excessive_refusal_rate` | D / \|D\| | Count P_i=NO CALL | Lower; refusing when a decision is supported |
| `decision_coverage` | All U / N | Count P_i in {BOX,STAY OUT} | Descriptive; no unconditional better direction |
| `eligible_decision_coverage` | D / \|D\| | Count P_i in {BOX,STAY OUT} | Higher alongside agreement; includes wrong decisions |
| `unusable_label_rate` | All U / N; also separately Z and D | Count P_i=INVALID in that population | Lower; exposes malformed/absent/error outputs |
| `response_failure_rate` | All U / N | Count generation status !=ok OR raw response empty/whitespace | Lower; operational failure, not semantic refusal |
| `why_supported_rate` (human) | All selected, completed review responses / reviewed count | Count factuality=2 | Higher; empty/unassessable output is a failure, not excluded |
| `justified_abstention_review_rate` (human) | Selected reviewed cases in Z / their count | S_i and P_i=NO CALL and correctness=factuality=2, plus history/scope=2 whenever applicable | Higher; label and supported, adequate refusal together |
| `human_<axis>_mean` | Completed applicable ratings / rated count | Sum of axis scores | Higher on 0–2; see missing-rating rules above |

The eligible population includes failures; an error has S=false, P=INVALID and human applicable scores 0. It contributes to no correct-abstention/coverage numerator. An absent output record is a pipeline defect (Section 6), not evidence that the model abstained. A missing human rating cannot be converted into a model failure; complete it or flag that human analysis as incomplete. For any empty population/zero denominator report value `null`, numerator/denominator, and reason `empty_population`; never 0% or 100%. Human rates are provisional if applicable notes are missing and cannot enter final comparisons then.

For every automatic metric report numerator, denominator and value overall and by exclusive primary family and expected label, plus a 3×4 confusion table (rows expected BOX/STAY OUT/NO CALL; columns predicted BOX/STAY OUT/NO CALL/INVALID). Attribute cross-tabs, including follow-up × card state, are additional diagnostics. An expected-label row's agreement is its recall. There is no valid-label-only accuracy that discards INVALID rows.

The overall rate is **micro**: sum case numerators divided by sum eligible case denominators. Also report `macro_label_agreement`, the unweighted mean of the three expected-label recalls, and `macro_family_agreement`, the unweighted mean of the five primary-family agreement rates. They are undefined if any required label/family is absent; report which is missing. Do not average only the observed easy families and call it the same metric. These macros keep majority STAY OUT from hiding abstention failures; always retain the separate Z/D rates. Other per-family metrics with empty denominators remain undefined and have no forced macro. Useful checks: on Z, justified-abstention CALL rate + unjustified-decision rate + unusable-label rate = 1; on D, eligible coverage + excessive refusal + unusable-label rate = 1.

### Validation-only prompt choice (2.5b)

Before generation, identify at least two candidate prompts/configurations, their fixed lexicographic candidate IDs, the common validation ledger and generation settings. Use only validation; neither mini-test, final nor engine smoke outputs select a prompt or modify this protocol. The mini-test still has at least 20 distinct unseen target queries; it is not a validation tuning pool.

Select by this fixed lexicographic order, maximising each coordinate: (1) strict-format rate, (2) negative unjustified-decision rate on Z, (3) negative excessive-refusal rate on D, (4) macro-label agreement, (5) macro-family agreement, (6) micro CALL agreement. Compare exact fractions, not rounded display values; ties keep the smallest predeclared candidate ID. Do not add an unannounced human tiebreaker or global weighted grade. Validation must contain all three labels, all five families and nonempty Z/D before this selection is run; otherwise repair its design before outputs, not by selectively dropping results.

Reason: a usable interface comes first; at equal format compliance prefer fewer unsupported decisions, then fewer excessive refusals. Thus at equal format a reduction in unjustified decisions wins even if excessive refusals rise. This is an explicit conservative **selection preference**, not a claim of overall quality improvement: show both counts, coverage, the confusion table and all five human axes when reviewed, and describe the trade-off. A candidate's extra INVALID outputs remain visible and cannot pass the first priority by being silently removed. No prompt is selected by 2.3a. Final A/B conclusions must discuss both error types, not simply reuse the selection ranking as proof of benefit.

## 6. Minimal records, histories and pairing

This is an evaluation envelope, not a competing data reconstruction schema. Reuse accepted 2.1/2.2 fields verbatim after integration. At the source check, `docs/data-protocol.md`, `data/splits.json` and `boxbox/evaluation/` were absent in this base. The unmerged #40 proposal has `card_id`, `split`, `card`, `provenance` per card record; confirm that mapping against its eventually accepted revision. Do not assume the shape/spelling of real IDs from these fixtures. Add only the evaluation fields below, with an explicit mapping in 2.3b; do not alter Maxime's cards/splits/corpus to fit synthetic IDs.

| Record | Required fields and invariants |
|---|---|
| Case | Stable `case_id`; inherited `card_id`, `split`, `card`, provenance reference/hash; evaluation `race_id` mapping to the accepted split identity; `scenario_id` for one underlying race/lap/car across variants and target turns; `variant_id`; integer `turn_index` (1-based target position); chronological `history` of `{role,content}`; separate current `message`; attributes and `primary_family`; `reference` containing `oracle` (`policy`, `policy_with_follow_up_annotation` or `message_annotation`), `policy_call`, exact `policy_reason`, contextual `expected_call`, `why_reference`, `required_evidence`, and history/scope requirement; case-level applicability. |
| Response | Unique `response_id`; `case_id`, `version_id`, `run_id`, `config_sha256`, `protocol_id/version`, `input_sha256`, `status`, `raw_response`, `error`. Status is `ok` or `generation_error`; ok requires a string (empty permitted) and error=null. Error requires code/message and raw string partial output or null. Keep the case/card/race/scenario mapping resolvable through the immutable ledger. |
| Review row | `review_id`, response/case/target identifiers, masked `version_code`, protocol version, `rating_status`, actual `rater_id` and timestamp (null in illustrative rows), per-axis scores/reasons, applicability, sensitivity flags, and optional second review/adjudication references. Keep original annotations immutable; adjudication is a separate record with the decision and reason. |

All identifiers are nonempty strings. One case ID maps to exactly one card content, race, scenario, variant, turn, history and message in a given versioned ledger; one scenario belongs to one race. Related incomplete variants keep the original scenario/race, with a distinct card ID/content hash. A `split` is train/validation/mini_test/final only after mapping to the accepted contract; fixtures use **synthetic**, never a reserved real race. Synthetic race objects satisfy the 1.4 shape but their events and IDs explicitly say Synthetic. No fixture implies that an actual reserved race exists.

Case authoring in 2.2/4.1 owns the additional evaluation fields and contextual annotations. Task 2.1 only needs to expose its accepted card/split/provenance identities unchanged; this envelope does not require it to add scoring fields to reconstruction. A's complete-card training restriction does not remove the five evaluation families from validation/mini-test/final.

The shared engine remains `respond(card, history, message) -> str`. Primary comparison uses **fixed supplied histories**: the same scripted, reviewed context and target message for every version. No candidate's generated reply feeds the next target in the principal comparison. Context may deliberately contain an incorrect assertion for a correction probe, labelled in the reference. This tests response to a controlled history, not autonomous dialogue quality. A secondary rollout with each version's own history is exploratory and must have separate case/input/run IDs and summaries; it cannot silently replace the paired fixed-context study.

Use at most the last `RunConfig.history_turns` complete user/assistant exchanges (default 3), oldest first. Do not count the current message or system/card blocks as history turns. Keep the current card and instructions intact; do not concatenate facts from another card. Preserve the full scripted history and the actual retained-history/input hash in the ledger. Authors must keep every required referent within the shortest retained history of all compared configurations. For a controlled comparison history bounds and context budget are the same across versions; if the template/token budget would drop a required referent or truncate card/instructions/message, reject the case/configuration combination before generation. Unexpected context overflow at execution is a retained generation error, not a repaired response. The engine task must record its actual template, token accounting and truncation; this document does not implement them.

Pair by **`(cases_sha256, case_id)`** across the explicitly retained versions, checking the same `input_sha256` and protocol version; `response_id` is unique per `(run_id, version_id, case_id)`. Candidate prompts/adapters differ through version/config metadata, not the target input hash. Define input hash as SHA-256 of the exact UTF-8 JSON text `input_json` saved once by the case builder for `{card,history,message}` after the common history bound. All versions reuse these same saved bytes; equivalent reserialisations are not substituted. The builder must retain the accepted card's numeric precision and reject nonfinite values; consumers load decimals without a lossy float conversion. This avoids imposing a second numeric serialisation on 2.1. Configuration/template hashes are separate. Hash the exact case-ledger bytes as `cases_sha256`.

Before reporting comparisons, require exactly one scheduled output per case/version; reject duplicate IDs/rows, unknown IDs, missing versions, inconsistent hashes/splits/race mappings and cross-split scenario collisions. List every defective pair and stop the affected comparison; never inner-join away unfavourable pairs. A logged model timeout/OOM/empty output has a response row and stays as a failure. A missing/corrupt output file, mislabeled version or differing input is a pipeline error; repair provenance or rerun only under an explicit recorded correction decision, preserving old attempts. Do not fabricate an error row from unexplained absence, retry a bad answer until it improves, or drop a case to make pairing pass.

The fixtures' `record_examples` contains one directly readable synthetic output row and one **expected-score** review row. Its fixture-only `rating_status=synthetic_expected` cannot stand for an actual completed human rating. `cards`, `cases` and `responses` are a compact normalised fixture package: resolve references to obtain the case's full card and the response's annotation. They are not a required storage engine. Example hashes are computed from included synthetic input/config bytes, not alleged run evidence.

## 7. Paired estimates and race-level uncertainty

Principal contrasts are **A minus baseline**, and **B minus A if B is retained**. Baseline/B, individual case stories, rollout studies and additional prompt analyses are exploratory. No B means the A/B research question remains unanswered. For every metric give both versions' point estimates and raw difference `new - old`; for higher-is-better metrics the gain is that difference, and for lower-is-better rates gain is `old - new`. Coverage has only a descriptive difference, no “gain”. Units are fraction points (or percentage points when explicitly converted); human means use 0–2 points.

Use micro estimates as defined in Section 5: each eligible case has weight 1, so larger race clusters have more case weight. Races have **equal selection probability** in resampling; this is not the equal-race average of race-specific rates. The macros retain their fixed equal-label/family weights. Do not change weighting depending on which view looks favourable.

Proposed settings fixed before results: `seed=2026`, `replications=10000`, `confidence_level=0.95`, two-sided **percentile** interval with linear/type-7 quantiles. These are simple reproducibility choices, not observations or a guarantee of precision.

1. Validate complete pairing and freeze the input/output ledger. Sort all G distinct `race_id` values in the analysis U lexicographically. Related scenarios, variants and target turns remain attached to their race.
2. With a fresh Python-standard-library `random.Random(2026)` per declared contrast, for each replicate draw G race indices with replacement using `randrange(G)`, in order. Use the **same draw/multiplicities for all versions and metrics**. Include every row of a drawn race with its multiplicity; never resample rows independently or variants separately.
3. Recompute each version's metric from the pooled weighted numerators/denominators (and recompute each macro from its components), then compute the paired difference/gain. Do not subtract independently bootstrapped intervals. Human analyses reuse the selected-case ledger and its race clusters; applicability is fixed across versions.
4. A zero denominator/absent required macro component in a draw yields a null replicate **for that metric** in both versions' difference, with a reason; keep the draw and do not redraw. Report valid/invalid replicate counts. If fewer than 9,500 of 10,000 draws are valid, suppress that metric's interval as `insufficient_valid_replicates`; otherwise use the valid draws and disclose the conditional limitation. This threshold is a protocol choice to avoid reporting heavily conditioned rare-subgroup intervals.
5. For M sorted valid differences `x[0..M-1]`, quantile at p uses `h=(M-1)*p`, `j=floor(h)` and `x[j] + (h-j)*(x[min(j+1,M-1)]-x[j])`. Report quantiles p=0.025 and 0.975, settings, support counts and interval status. There is no multiple-comparison significance claim.

Edge cases are mandatory outputs: empty U/category or no eligible cases → null point/interval with `empty_population`; missing pairs → `pairing_error`, no inferential comparison; G=1 or only one race with a positive denominator for a metric → point/difference only, null interval `single_race`. An identical-version contrast on defined data with at least two contributing races gives exactly zero difference (and zero bootstrap differences); a zero-width interval does not prove equivalence. With 2–4 contributing races report `few_races`; with more races still report G, per-race cases, denominator-contributing races, largest race's case share and variant concentration. Many variants from a few races do not create independent evidence. Macro components need their own contributing-race counts/limitations; suppress an interval if any required component has just one contributing race.

A small race count, an undefined category or a degenerate interval must remain visible even when computation technically succeeds. This resamples the observed case/race collection, not the training process; it does **not** measure variability across training seeds, source revisions or future races. Negative/uncertain differences are legitimate findings. No promise of improvement, precision or significance follows from 10,000 draws.

The fixtures' `paired_example` is a six-target, three-race illustration, not an experiment. Its linked variants travel together. Hand fractions and category/identical/single-race expectations are provided for 2.3b; two stage-specific versions are named `toy_old`/`toy_new` to avoid implying a trained A/B exists.

## 8. The same 40 targets and human review

### Selection before model answers

Final preparation ([4.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/20)) targets approximately **200 cases**, only after the accepted freeze. This section defines a procedure; it does not open or construct that final pool. Mini-test retains at least **20 unseen target queries**. Select review targets from the final metadata/reference ledger **before model generation**, save IDs/order/settings/hash, and reuse the identical 40 targets for every retained version.

Use eight slots per exclusive family, total 40, with these subconstraints:

| Family | Eight target slots |
|---|---|
| complete | 4 expected BOX, then 4 expected STAY OUT |
| blocking_incomplete | 8 expected NO CALL |
| usable_incomplete | 4 expected BOX, then 4 expected STAY OUT |
| follow_up | First 2 on blocking cards, next 2 on usable-incomplete cards, last 4 on complete cards; all history-sensitive |
| out_of_scope | 8 expected NO CALL on otherwise decidable cards (policy_call BOX or STAY OUT) |

Cap at **8 targets per race** and **2 per scenario** across all slots, including variants/turns. Thus any successful sample has at least five races and twenty scenarios and at least eight BOX, eight STAY OUT and eighteen NO CALL references. Prefer broad race/scenario coverage using the deterministic ordering below, not by looking at answers. No output quality, length, latency or version-specific failure can influence selection.

Algorithm for 2.3b (finite deterministic constrained selection):

1. Validate all candidate metadata, references and split membership. Reject duplicates/inconsistent IDs as pipeline defects. Canonicalise the candidate list by case ID. Exclude no cases on model-output grounds; outputs do not yet exist.
2. Fix a 40-slot sequence: for round 0 through 7, visit families in the table's order once; apply that family's round-specific subconstraint. A candidate can occupy only one slot, determined by its primary family.
3. Rank the eligible unused candidates for the current slot by `(number already selected from its race, number already selected from its scenario, H, case_id)`, ascending; `H` is the hexadecimal SHA-256 of UTF-8 `boxbox-eval|1.0.0|2026|sample|<case_id>`. Disallow candidates exceeding either cap. Choose the first candidate permitting a complete allocation of the remaining slots. This means deterministic backtracking in that order, not greedy acceptance followed by arbitrary replacements; prune when remaining category/subconstraint/cap capacity cannot fill the slots. No random retries. The first complete allocation is the sample; retain slot order and also sorted selected IDs.
4. If no allocation exists (too small a stratum, inadequate race/scenario diversity, fewer than 40 cases, or incompatible subconstraints), report capacities/unfilled slots and stop. There is **no automatic quota redistribution, cap relaxation, reduced sample or replacement from another split**. The team must explicitly decide a metadata-only correction or scope/protocol amendment with its consequence before generation, retaining the failure evidence. Do not invent cases or call a smaller review 40. After responses exist, never replace a selected failure; retain it.

Eight-per-family allocation deliberately stresses rare failures; it is not a random sample representative of the whole final distribution. Human pooled means describe this balanced review design; report family-specific scores and counts, not population prevalence estimates. Overlapping attributes are reported separately and do not earn extra quota slots. The fixtures include a small metadata-only quota witness (40 targets, five synthetic races, twenty scenarios), not final cases or a claim that actual strata can fill these slots.

### Masking and annotation

The retained generative versions are baseline/A/B (**120 responses**) or baseline/A (**80**) only after an explicit linked decision to drop B. Forty context conversations do not entitle scoring all their prior replies; only the 40 selected target IDs count. Helpers may divide disjoint target sets while keeping all versions of a target with the same primary rater; identical applicability and calibration are required. Do not split versions of the same case across unrelated primary raters.

For reproducible masking, sort the retained internal version IDs, then order them by SHA-256 of `boxbox-eval|1.0.0|2026|mask|<version_id>` (ID breaks a hash tie) and assign V01, V02, V03 as needed. Keep the actual mapping in a **separate key file**, outside the rating sheet. Shuffle presentation by sorting response rows by SHA-256 of `boxbox-eval|1.0.0|2026|present|<case_id>|<version_code>` (case/code break ties). Save the actual key and order. These seeded hashes provide reproducibility, not cryptographic blinding: anyone with the candidate IDs and algorithm can reconstruct the key. Restrict key/config access during rating.

The sheet shows a neutral review ID, target/case reference, current card, useful retained history, current message, policy/reference annotation, applicability and raw target response/error. Remove avoidable run, model, adapter, prompt and file-path labels from the visible sheet; a separate lookup maps review IDs to response/run IDs. Do not edit generated text to hide self-identification. Writing style, memorised answers, error text, or context may reveal a version; record suspected unmasking. The same reference helps calibration but may cue policy conformity; it cannot justify assuming real strategy quality. The exporter belongs to 2.3b.

Rater instructions: calibrate first on the synthetic fixtures, compare the reference facts with every output, rate the target only, apply all relevant axes independently, and keep short evidence-based reasons. Blank/error output gets applicable zeros; N/A follows case metadata, not sympathy for a failure. Record actual scorer/time only when rating happens. Synthetic expected scores are calibration discussion material, not claimed human agreement.

Flag for another available teammate: any invented/unauthorised number, factuality 0/1, optimality promise, false-history correction, scope dispute, applicability/reference ambiguity, or requested disagreement review. That person reviews sensitive/disputed rows and their initial reasons; **systematic double scoring of all 80/120 responses is not required**. Preserve primary notes before second review, record independent second notes where obtained, then record an adjudication/resolution with real participants and reasons. Unresolved cases remain marked; do not report complete adjudicated scores or inter-rater agreement from them. No teammate's availability or consent is assumed here. Actual human rating, another member's review and team validation remain future work ([4.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/22)).

The optional 3.4 CALL-only baseline remains optional. Compare CALL measures only on its explicitly shared eligible scope and clearly label any subset; do not give it a generated WHY or add it to these 40-case/version human totals. A stub demo is similarly not evidence of trained-model quality.

## 9. Fixture interpretation and manual arithmetic

[evaluation-fixtures.json](../reference/evaluation-fixtures.json) separates full synthetic cards, target cases and annotated responses. `annotation_kind=synthetic_expected` and all `rater_id` values are null. Every response annotation states structural/label expectations, axis applicability, expected scores and reasons. The policy references were checked against the existing function; those checks do not certify the contextual human annotations as independently reviewed.

In the six-row paired example, old predictions are BOX, BOX, NO CALL, STAY OUT, INVALID, STAY OUT; new predictions are BOX, NO CALL, STAY OUT, NO CALL, NO CALL, BOX. Expected labels are BOX, NO CALL, STAY OUT, BOX, NO CALL, STAY OUT. Hence:

| Metric | toy_old | toy_new | Raw new−old | Improvement-oriented gain |
|---|---|---|---|---|
| CALL agreement | 2/6 | 4/6 | 1/3 | 1/3 |
| Justified-abstention CALL rate | 0/2 | 2/2 | 1 | 1 |
| Unjustified-decision rate | 1/2 | 0/2 | −1/2 | 1/2 |
| Excessive-refusal rate | 1/4 | 1/4 | 0 | 0 |
| Decision coverage | 4/6 | 3/6 | −1/6 | descriptive only |
| Eligible decision coverage | 3/4 | 3/4 | 0 | 0 |
| Unusable-label rate | 1/6 | 0/6 | −1/6 | 1/6 |
| Macro-label agreement | (1/2+1/2+0)/3 = 1/3 | (1/2+1/2+1)/3 = 2/3 | 1/3 | 1/3 |

The single old INVALID is a labelled generation error and remains in all-case denominators. Families `follow_up` and `out_of_scope` are empty in this toy, so their point rates and macro-family agreement are undefined, not perfect/zero. Repeating synthetic race 1 twice and race 3 once while omitting race 2 gives old agreement 3/6, new 5/6, difference 1/3: both linked variants of each drawn race move together. Identical versions have zero defined differences. Restricting to race 1 still permits a point estimate but has no interpretable interval. The fixture stores these fractions and edge expectations for future tooling tests; no bootstrap implementation or performance interval is delivered here.

## 10. Handoffs and remaining acceptance evidence

| Consumer | What is ready to use | Remaining check/action in that task |
|---|---|---|
| 2.1–2.2 | Card-only authority; need card/split/provenance plus stable race/scenario mappings and metadata | Confirm accepted identifiers/serialization, race separation and enough strata after integration; no reconstruction/split/corpus change is made here |
| 2.3b | Metrics, flags, error rules, fixed pairing/history, bootstrap settings, sample slots, masking and synthetic expectations | Implement parser/scorer/bootstrap/exporter on fixtures, validate accepted data mapping and retained-history hashes; never open final to build tooling |
| 2.4 | Existing respond/card/history/message shape and [interface](interface.md); reset empties history | Test real stored reset/card-change/session isolation and mark stub; no quality claim from stub |
| 2.5a | Fixed common target inputs, bounded same-card history, raw outputs and explicit errors | Implement native template/context accounting without silent repair; smoke output does not revise this protocol |
| 2.5b | Predeclared conservative priorities and deterministic ties | Use common validation only, preserve all candidates/results and freeze inference; select no prompt here |
| 3.5 / 4.x | Version/hashable protocol; final closed until real freeze; same 40 targets; paired principal contrasts and honest limits | Obtain real acceptance/freeze, construct reserved cases afterwards, collect actual human notes and independent sensitive-case review, report negative findings |

Local documentary checks establish consistency, not issue closure. Pending: independent review of this proposed protocol and its annotations, team acceptance/integration or accessible deliverable link, confirmation of the eventual 2.1 metadata mapping, and actual future human ratings/review. No test human, model run, prompt choice, training, final inspection or teammate agreement is asserted by this document.
