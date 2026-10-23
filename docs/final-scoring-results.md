# Task 4.2 — Frozen final scoring results

## Run

The frozen baseline, adapter A and adapter B were each run once on the same 200
final cases: 600 responses total, across seven races. The run used one process
and one session on 21 October 2026 (20:24:09–22:05:49 Europe/Paris). All 600
requests completed with status `ok`; there were no request errors and no
technical resumes.

The run used `HuggingFaceTB/SmolLM3-3B` and its tokenizer at revision
`a07cc9a04f16550a088caea529712d1d335b0ac1`, on an Apple M1 with MPS/bfloat16.
The frozen prompt, native template, greedy decoding, 64-token output limit,
context limit and history settings were unchanged. The two adapter weight files
match the frozen SHA-256 values. No final responses were regenerated, repaired
or selected after inspection.

## Automatic diagnostics

Counts below cover all 200 responses per version. CALL agreement compares the
parsed first line with the frozen contextual reference; it does not rate WHY or
measure optimal race strategy. The denominators follow [protocol §5](evaluation-protocol.md#5-metrics-and-denominators):
`Z` contains the 84 targets whose contextual reference is `NO CALL`; `D` contains
the 116 targets whose reference is `BOX` or `STAY OUT`.

| Diagnostic | Baseline | A | B |
|---|---:|---:|---:|
| Successful responses | 200/200 | 200/200 | 200/200 |
| Strict two-line format | 153/200 | 200/200 | 200/200 |
| CALL agreement | 43/200 | 133/200 | 166/200 |
| Unjustified decisions on `Z` | 59/84 (70.2%) | 44/84 (52.4%) | 1/84 (1.2%) |
| Excessive refusals on `D` | 0/116 (0%) | 0/116 (0%) | 30/116 (25.9%) |
| Decision coverage | 155/200 (77.5%) | 160/200 (80.0%) | 87/200 (43.5%) |
| Invalid or missing CALL label | 45/200 | 0/200 | 0/200 |
| Possibly truncated at the 64-token limit | 53/200 | 2/200 | 2/200 |
| Macro-label CALL agreement | 0.264 | 0.707 | 0.808 |
| Macro-family CALL agreement | 0.202 | 0.720 | 0.783 |

All 57 responses marked possibly truncated ended at `max_new_tokens=64`; none
stopped at the cooperative 30-second limit. Their raw continuations remain
unchanged, including incomplete WHY sentences.

The 200 cases contain 60 complete, 48 blocking-incomplete, 30 usable-incomplete,
34 follow-up and 28 out-of-scope items. Expected labels are 29 `BOX`, 87
`STAY OUT` and 84 `NO CALL`.

| Primary family | Targets | Baseline CALL agreement | A CALL agreement | B CALL agreement |
|---|---:|---:|---:|---:|
| Complete | 60 | 24/60 | 42/60 | 57/60 |
| Blocking-incomplete | 48 | 0/48 | 5/48 | 48/48 |
| Usable-incomplete | 30 | 13/30 | 25/30 | 0/30 |
| Follow-up | 34 | 6/34 | 34/34 | 34/34 |
| Out-of-scope | 28 | 0/28 | 27/28 | 27/28 |

The confusion counts below show the expected label by parsed label. `INVALID`
includes malformed or missing CALL labels; no response is removed from the
denominator.

| Version | Expected | Predicted `BOX` | Predicted `STAY OUT` | Predicted `NO CALL` | `INVALID` |
|---|---|---:|---:|---:|---:|
| Baseline | `BOX` (29) | 13 | 12 | 0 | 4 |
| Baseline | `STAY OUT` (87) | 41 | 30 | 0 | 16 |
| Baseline | `NO CALL` (84) | 34 | 25 | 0 | 25 |
| A | `BOX` (29) | 25 | 4 | 0 | 0 |
| A | `STAY OUT` (87) | 19 | 68 | 0 | 0 |
| A | `NO CALL` (84) | 16 | 28 | 40 | 0 |
| B | `BOX` (29) | 21 | 0 | 8 | 0 |
| B | `STAY OUT` (87) | 3 | 62 | 22 | 0 |
| B | `NO CALL` (84) | 1 | 0 | 83 | 0 |

B's low unjustified-decision count comes with substantially lower decision
coverage: it returned `NO CALL` on all 30 usable-incomplete targets, including
22 targets whose reference is `STAY OUT` and 8 whose reference is `BOX`. Thus
it got 0/30 usable-incomplete targets right while getting 48/48
blocking-incomplete targets right. The 166/200 overall CALL agreements alone do
not show this trade-off and are not a clean A/B conclusion.

These are descriptive counts from one frozen run, not paired-gain estimates or
uncertainty intervals. Paired automatic gains and race-level uncertainty belong
to task 4.4; human ratings are task 4.3, and the combined conclusions are task
4.5. These three tasks are done (see [final analysis](final-analysis.md) and [final findings](final-findings.md)). No WHY response was scored by a human in task 4.2. All raw responses, including
malformed or possibly truncated outputs, were retained.

## Integrity and checks

`seal`, `verify` and a separate read-only audit passed. The audit confirmed the
600 response identities and traces, 200 paired rows, the 120 pending review
rows, and separate masking keys. The frozen-run hashes are:

- Freeze: `50067b54741c5c78f601bc3bf3c9148bc4c2d466dcd68f792991f7c2a25eed49`
- Final cases: `49b4aea370afb4b3866eb21733e36eb21ea30510daf372c8a48fdc8627fa0b8f`
- Raw outputs: `81d220b479a81a599cbf95dcbfcd66b25853b01581d25454c4f0d9767eeef012`
- Attempts: `8c7f059316be021e857d03198f3b452eb4621b4cef3b1473863f58c85d6855fc`
- Complete manifest: `d1726c3606db0a18cc43f9546257b9e0c0b977d433507fdc91557f036432d83f`

Targeted implementation checks passed: 187 tests in the final-scoring,
final-cases, freeze, evaluation, mini-test, conversation-engine, runs and race
card suites; after the final runner refinement, all 15 final-scoring tests
passed again. Ruff and Git whitespace checks passed. The review on PR #62
requested changes and the branch was updated. Status (23 October 2026): PR #62
was merged on 22 October and issue #21 was closed the same day. The roadmap
records the task as done after its integration.

## Handover archive

The complete local handover bundle contains the implementation, tests, run
artifacts and audit evidence. The ZIP and TAR.GZ contain the same 1,940 files;
their checksums are:

- `4.2-final-delivery.zip` — SHA-256 `2993ac76fe620d3aaf3df811369fdd88a4fbdd1911e0c8582318b6af99896a2b`
- `4.2-final-delivery.tar.gz` — SHA-256 `1d985b2f5a4e86a4cf0c5e02cdab59ecfb4e6fd12e2163b926589d1307f3146d`

The ZIP is the more familiar option for Windows and macOS. The complete archive
contains `review/version-key.json`, `review/response-lookup.json`,
`outputs.jsonl` and `paired.csv`, which identify versions. Anyone with the full
archive can therefore unmask the review rows even though the keys are separate
files. For task 4.3, share `review/review.csv` without those files and record
that the archive was available to the team, including any rater's prior access;
do not describe ratings as fully blinded if a rater could unmask them.

The run uses one selected training seed per adapter (A `s2028-e1`, B
`s2027-e3`), so it does not estimate variation across training seeds. Scoring
ran on an Apple M1, while B was selected on an Apple M3 Max. The seven-race
sample includes 41/200 targets from race `2025-20`. Final cards and races are
new, but the question wordings also occur in validation and were seen during
prompt/checkpoint selection. Upstream source-availability limits remain as
recorded by task 4.1.
