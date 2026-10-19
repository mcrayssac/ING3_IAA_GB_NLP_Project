# Evaluation tooling (2.3b)

The shared evaluator implements the [boxbox-eval/1.1.0 proposal](evaluation-protocol.md). The proposal and its [calibration fixtures](../reference/evaluation-fixtures.json) remain normative. Testing them does not accept or freeze the protocol, supply independent review, or establish model performance.

The core uses the Python standard library and existing rule/config helpers. Importing `boxbox.evaluation` does not import pandas, torch or transformers. Real-split CLI integration lazily calls the existing checked split loader in the normal project environment.

## Worked synthetic example

From the repository root, with Python 3.13:

```sh
python -m boxbox.evaluation fixtures --output runs/2026-10-19_evaluation-fixtures
```

Choose a fresh run name: existing output directories are never overwritten. To test without the model stack, install only the tools already pinned in `requirements.txt` in a separate environment:

```sh
python3.13 -m venv /tmp/boxbox-evaluation-env
/tmp/boxbox-evaluation-env/bin/python -m pip install pytest==9.1.1 ruff==0.17.1
/tmp/boxbox-evaluation-env/bin/python -m pytest -q tests/test_evaluation.py tests/test_race_card.py
/tmp/boxbox-evaluation-env/bin/ruff check boxbox/evaluation tests/test_evaluation.py
/tmp/boxbox-evaluation-env/bin/ruff format --check boxbox/evaluation tests/test_evaluation.py
```

The fixture command checks all 27 cards, 35 targets and 55 response annotations: current policy references, exact structural flags, score types and applicability. It validates supplied semantic annotations; it does not judge their English or factual grounding automatically.

The output contains:

- `cases.jsonl`, `outputs.jsonl`: six synthetic paired targets and twelve explicit synthetic outputs;
- `metrics.json`, `comparisons.json`, `paired.csv`: counts, exact point fractions, differences/gains and 10,000-draw race-cluster intervals with limitations;
- `calibration-checks.json` and `quota-witness-selection.json`: calibration checks and selection of forty metadata-only targets;
- `review/review.csv`: a six-target/twelve-response illustrative excerpt with pending scores;
- `review/version-key.json` and `review/response-lookup.json`: separate identity keys; restrict access during actual rating;
- `manifest.json`, `config.toml` and exact protocol/fixture snapshots.

The toy table supplies CALL classifications, not complete generated strings. The command adds explicitly synthetic two-line wrappers to exercise ordinary scoring; structural metrics describe those wrappers. They are not observed model responses or original calibration WHY annotations. The quota witness is not a complete final pool. None of these outputs contains actual human ratings.

## Shared records and API

Public functions are exported by `boxbox.evaluation`. Their fields extend the evaluation envelope, without changing upstream card/corpus schemas.

`prepare_case(annotation, card, history_turns=3)` retains `full_history`, bounds complete chronological user/assistant exchanges, and saves exact UTF-8 `input_json` for `{card, history, message}` with `input_sha256`. Serialize once and reuse the same bytes across versions. Decimal numbers remain numbers without a lossy float conversion. Consumers verify saved bytes instead of substituting equivalent serializations.

`validate_cases(cases, race_splits=None)` checks identifiers, scenario/race/split consistency, turn position, applicability, family priority, policy references and input hashes. Pass the already checked full split document for real cases; its split mapping alone cannot check session keys. Synthetic fixtures use `split=synthetic` and `syn:` race identities.

For real cases, each source race/lap/car maps to one scenario across variants and target turns, and one scenario cannot combine distinct source situations. This uses the checked source `card_id`, including when a probe transforms the card's identity fields. Synthetic calibration and metadata-only quota witnesses retain their explicitly declared scenario identities.

Real records retain source `provenance`, `provenance_sha256` and `source_card_sha256`. Transformed cases also retain `source_card`: source IDs are checked against the original card even for malformed-input probes. `card_content_sha256` identifies the evaluation variant. These content hashes use the evaluator's finite-number JSON encoding and differ from raw timing-file hashes. Strict-cutoff availability remains an upstream responsibility.

`corpus_case(item, annotation, split, history_turns=3, source_record=record)` adapts a supplied item without corpus-file I/O. The source record comes unchanged from `load_cards`. Only the last assistant turn is scored; previous exchanges are fixed history and the last user entry is the current message. The target reference answer never becomes input. Supply reviewed contextual annotations and scenario/variant identities. Item ID, kind, scope, follow-up and transformation metadata are retained.

`pair_outputs(cases, outputs, versions, cases_sha256, race_splits=None)` requires exactly one scheduled output per case/version. Each output includes `cases_sha256` in addition to the protocol's response fields. `config_sha256` identifies that version's saved effective generation configuration. One version has one run/config identity; attempts are not silently combined.

Pairing checks protocol/input/ledger hashes, identifiers and explicit error records. It lists defects in `PairingError`, without inner joins, duplicate selection, fabricated error rows or retries. An `ok` output can be empty. `generation_error` requires code/message and preserves partial raw text or null.

Conflicting case metadata repeated in an output is a pairing error. Observations take references, race/scenario identities and applicability only from the case ledger; only declared response fields and parsed format/CALL results are merged from outputs. JSONL records are separated by physical LF characters, preserving Unicode separators inside raw strings.

`parse_response(raw_response, status="ok")` checks strict structure and extracts the first CALL independently. Only CRLF-to-LF and removal of at most one terminal LF are allowed. No semantic conclusion follows from structure. Partial error output never becomes a correct abstention.

`observations`, `summarize` and `bootstrap_compare` consume validated pairings. Reports retain counts and exact fractions before rounding, family/label and Z/D summaries, INVALID confusion counts and missing macro components. There is no exact-WHY scoring criterion or overall five-axis grade.

## Select before generation, score afterwards

For a reviewed authored ledger, select human-review targets before generation:

```sh
python -m boxbox.evaluation sample \
  --cases /path/to/cases.jsonl --split validation \
  --split-manifest data/splits.json \
  --output runs/2026-10-19_review-selection
```

This is an interface example, not an actual validation/final evaluation by 2.3b. Selection follows the exact quotas, caps, versioned hash prefixes and first-complete ranked backtracking allocation. It reads no model outputs. An infeasible pool returns capacities and stops without redistribution.

After the shared engine supplies the corresponding raw ledger:

```sh
python -m boxbox.evaluation score \
  --cases /path/to/cases.jsonl --outputs /path/to/outputs.jsonl \
  --versions baseline A B --split validation \
  --split-manifest data/splits.json \
  --selection runs/2026-10-19_review-selection/selection.json \
  --output runs/2026-10-19_evaluation
```

Omit `--selection` for automatic-only analysis. Use `--contrast OLD NEW` for additional comparisons. Baseline/A and A/B are principal; others are labelled exploratory or synthetic. Candidate prompt selection remains 2.5b's validation-only task, using the protocol's predeclared exact-fraction priorities and candidate IDs.

Actual forty-target review exports contain baseline/A/B (120 responses), or baseline/A with a real `--drop-b-record` reference (80). The illustrative excerpt and unit tests make no actual B-drop decision. The optional CALL-only baseline receives no invented WHY or human-review slots.

Scoring verifies both the slot-order and sorted selected-ID lists against the recomputed sample. Non-illustrative exports require exactly forty targets; an inconsistent manifest or missing B-drop declaration fails before creating the scoring output directory.

Final requests fail before reading case/output paths unless `RunConfig.final_test_open` is true and actual `--freeze-record` and `--acceptance-record` references are supplied. Those declarations still require team verification; the evaluator does not authenticate human acceptance. Task 2.3b keeps the default gate closed and never opens actual final cases.

Scoring saves byte-identical copies of case/output/rating ledgers, verifying their hashes again before copying. Its manifest separates evaluation settings from each version's declared generation run/config identity. The combined case ledger also serves as the input ledger because it contains exact `input_json` and input hashes. The evaluator cannot independently prove how a model was executed.

## Supplied ratings and masking

The CSV shows the card, message, useful history, contextual reference, raw response/error and applicability. Run/model/config identities stay in separate key/lookup files. Seeded masking is reproducible rather than cryptographic; prose, errors or context can reveal identity. Raw output is never edited to conceal it.

Axis columns accept integer 0/1/2, literal `N/A`, or blank for pending applicable scores. Keep reasons for completed applicable scores and N/A. Only actual human work supplies `rater_id` and a timezone-aware timestamp. Blank sheets remain pending. Empty/error output has zero anchors when rated; the exporter does not fabricate completed ratings.

`import_review(sheet, lookup, cases)` validates filled rows against immutable visible inputs, IDs and lookup. It returns notes without overwriting the sheet or initial ratings; save them to a new JSONL file. Invalid scores, applicability mismatches and synthetic expectations presented as human ratings are rejected.

Supply preselected IDs and notes to `observations`, or use `score --ratings /path/to/ratings.jsonl --selection ...`. Pending ratings remain in scope; means stay provisional and final human gains remain unavailable until applicable pairs are complete. `--rating-phase initial|adjudicated` keeps summaries separate. Second-review/adjudication metadata never silently replaces the initial score columns. Preserve both records and link resolutions to original notes.

Calibrate on synthetic fixtures and have another available member review sensitive cases/disagreements. Systematic double scoring is not required. No rater or reviewer is assumed available.

## Statistics and limitations

Automatic contrasts use the declared case ledger; human contrasts use selected review targets and their own race clusters. The paired table labels these populations separately. The balanced forty-target design does not estimate whole-pool prevalence.

Defaults: fresh Python `random.Random(2026)` per contrast, 10,000 whole-race draws, common multiplicities across versions/metrics, percentile 95% intervals, linear/type-7 quantiles. Larger clusters retain greater case weight. Zero denominators leave null draws without redrawing. Fewer than 9,500 valid draws suppresses the interval; valid/invalid counts and conditional interpretation remain explicit.

Empty populations, missing pairs, one contributing race, macro components with one contributing race and 2–4 contributing races remain visible. Identical outputs give zero defined differences; zero-width intervals do not establish equivalence. Small replication overrides in the API are marked non-protocol and used only in unit checks; the CLI has no statistical tuning flags.

This does not measure training-seed variation or real strategy optimality. The strict-cutoff defect and proposed A SC/VSC exception remain upstream limitations. No reconstruction, corpus or policy changes are made here.

Targeted tests are synthetic. Do not run the entire existing suite blindly under that restriction: `tests/test_corpus.py::test_load_corpus_rejects_a_changed_file_or_policy` opens the actual mini-test. Final-gate tests use temporary synthetic files/mocks.
