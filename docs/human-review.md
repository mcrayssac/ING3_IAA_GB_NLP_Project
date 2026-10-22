# Human review of the final targets (4.3)

Task [4.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/22) scores the
40 targets selected in 4.1 for baseline, A and B: 120 masked responses from the
retained 4.2 run. The rubric, applicability and masking rules are those of
[evaluation-protocol.md](evaluation-protocol.md) §4 and §8. This page describes the
tooling only; it does not record any rating.

## Files

Work in a folder outside the repository and outside the run, for example
`/private/tmp/boxbox-43-human-review-YYYYMMDD/`:

- `review-original.csv`: untouched copy of the run's `review/review.csv`.
- `review-rated.csv`: the copy raters fill.
- `review-manifest.json`: copy of the run's `review/manifest.json` (selection and order).
- `review-page.html`: offline rating page generated from the sheet.
- `reviewer-log.md`: raters, masking limits, sensitive cases and checks.

Share only `review-rated.csv` or `review-page.html` with raters. The run folder and the
4.2 handover archive contain `version-key.json`, `response-lookup.json`,
`outputs.jsonl` and `paired.csv`, which unmask the rows. Record each rater's prior
access to them; do not call the ratings blinded if a rater could unmask them.

## Commands

From the repository root, with `RUN` the 4.2 run folder:

    python -m scripts.human_review page --run-dir RUN --sheet review-rated.csv --output review-page.html
    python -m scripts.human_review check --run-dir RUN --sheet review-rated.csv
    python -m scripts.human_review import --run-dir RUN --sheet review-rated.csv --output ratings-initial.jsonl

`page` checks the sheet against the run before writing a self-contained page; it
holds the masked sheet columns only. An optional `--suggestions FILE` adds proposed
scores and reasons, keyed by review ID, shown beside each row. A proposal is copied
into the row only when the rater presses *Apply suggestion*, and the row counts as
rated only when the rater, having read it, presses *Mark completed*. Record in the log
whether proposals were used and where they came from.

`check` accepts a partly filled sheet. It refuses changed inputs or raw responses
(naming the rows), invalid scores, unknown flags and malformed second reviews, and
prints progress: completed and pending rows, targets per primary rater, targets split
across raters, rows that need a second review, and disagreements without a resolution.
It never prints version identities.

`import` requires all 120 rows completed and one primary rater per target. It writes
the validated ratings once (`ratings-initial.jsonl`, with internal version IDs) and
prints its SHA-256. Keep that file with the evidence, not with raters.

## Rating page

Open `review-page.html` in a browser; it needs no network. Enter your name, then for
each row read the card, history, message, reference and raw response (whitespace and
line breaks are shown), give 0, 1 or 2 with a short reason on each applicable axis,
and tick any flag. Non-applicable axes are already `N/A` with a reason.

- *Mark completed* records your name and a local ISO timestamp with timezone. Editing a
  completed row returns it to pending.
- All versions of a target must keep the same primary rater.
- Edits are kept in that browser only. Use *Export CSV* regularly and keep the latest
  export as `review-rated.csv`. *Load sheet CSV* resumes from an export or merges
  another rater's rows for disjoint targets; it refuses altered inputs and keeps local
  notes when both sheets annotate the same row.
- Do not edit the CSV in a spreadsheet application: re-saving can alter the quoted
  inputs, which `check` will then refuse.

## Second review and resolutions

A row needs a second review when its factuality is 0 or 1 or it carries a flag
(invented or unauthorised number, optimality promise, false history correction,
scope dispute, applicability or reference ambiguity, requested disagreement review,
suspected unmasking). Another teammate switches the page to *Second review*, enters
their own name, and records a verdict (agrees, disagrees, unsure), optional independent
scores and notes. The primary scores stay unchanged. A disagreement then gets a
resolution with its actual participants, status (resolved or unresolved), decision and
reason. Unresolved rows stay marked; do not report adjudicated scores or agreement
rates from them.

## Evidence for closure

Completed sheet, `ratings-initial.jsonl` and its SHA-256, `review-manifest.json`,
`reviewer-log.md`, the `check` output, and the second reviewer's confirmation. Human
means, paired gains and race-level uncertainty belong to 4.4.
