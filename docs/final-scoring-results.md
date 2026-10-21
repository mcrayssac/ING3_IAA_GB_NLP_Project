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

Counts below are over 200 responses per version. CALL agreement compares the
parsed first line with the frozen contextual reference; it is not a human
rating of the explanation or a measure of optimal race strategy.

| Diagnostic | Baseline | A | B |
|---|---:|---:|---:|
| Successful responses | 200 | 200 | 200 |
| Strict two-line format | 153 | 200 | 200 |
| CALL agreement | 43 | 133 | 166 |
| Invalid or missing CALL label | 45 | 0 | 0 |
| Possibly truncated at 64 tokens | 53 | 2 | 2 |

The 200 cases contain 60 complete, 48 blocking-incomplete, 30 usable-incomplete,
34 follow-up and 28 out-of-scope items. Reference labels are 29 `BOX`, 87
`STAY OUT` and 84 `NO CALL`. All raw responses, including malformed or possibly
truncated outputs, were retained. The human review export contains 120 rows for
the preselected 40 targets; every rating remains pending. No WHY response has
been scored by a human.

These are descriptive diagnostics only. Paired gains, uncertainty estimates
and conclusions belong to tasks 4.3–4.5. Upstream source-availability limits
remain as recorded by task 4.1.

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
passed again. Ruff and Git whitespace checks passed. No human rating or
independent teammate review is claimed here; review is still required before
issue #21 can be closed.

## Handover archive

The complete local handover bundle contains the implementation, tests, run
artifacts and audit evidence. The ZIP and TAR.GZ contain the same 1,940 files;
their checksums are:

- `4.2-final-delivery.zip` — SHA-256 `2993ac76fe620d3aaf3df811369fdd88a4fbdd1911e0c8582318b6af99896a2b`
- `4.2-final-delivery.tar.gz` — SHA-256 `1d985b2f5a4e86a4cf0c5e02cdab59ecfb4e6fd12e2163b926589d1307f3146d`

The ZIP is the more familiar option for Windows and macOS. Keep the masking keys
separate from the blinded review CSV when sharing it with raters.
