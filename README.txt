BoxBox run guide
================

Run every command from the repository root.

1. Install
----------

Python 3.13 and uv are required.

    uv venv --python 3.13 .venv
    uv pip install --python .venv/bin/python -r requirements.txt

The first model load downloads HuggingFaceTB/SmolLM3-3B at revision
a07cc9a04f16550a088caea529712d1d335b0ac1 (Apache 2.0, about 6.2 GB of weights).

2. Tests
--------

    .venv/bin/python -m pytest -q

3. Race data (task 2.1)
-----------------------

The race-level splits are frozen in data/splits.json (committed). The cards are
rebuilt from OpenF1 and Jolpica. Responses are cached in data/cache/openf1/ and
cards written to data/cards/; neither is committed. Without a cache the
rebuild makes 286 requests, one every 2.1 s at OpenF1's free rate, so at least
10 minutes. From the cache it took 77 s on an M3 Max.

    .venv/bin/python -m scripts.rebuild_data cards
    .venv/bin/python -m scripts.rebuild_data card --race 2024-01 --driver 1 --lap 20

The splits were made once with the command below, which refuses to overwrite
the existing file:

    .venv/bin/python -m scripts.rebuild_data splits --seasons 2023 2024 2025 --seed 2026

4. Corpus (task 2.2)
--------------------

Corpus A, validation and mini-test dialogues are committed in data/corpus/
(CC BY-NC-SA 4.0, see data/corpus/NOTICE). They are rebuilt from the cards in
about 2 s. Build also refreshes the review summary; use the second command
to refresh it after editing verdicts or notes:

    .venv/bin/python -m scripts.build_corpus build
    .venv/bin/python -m scripts.build_corpus review

Corpus B (task 3.1) is derived from the committed A_train.jsonl without cards.
The token counts of A and B need the model tokenizer (downloaded once):

    .venv/bin/python -m scripts.build_corpus build-b
    .venv/bin/python -m scripts.build_corpus exposure

In review_sheet.csv, use ok or fix in verdict and prefix the reason in note
with automatic: or confirmed:. Leave unresolved judgments blank. The review
command summarises existing decisions; it does not review or approve rows.
review.json separates automatic, confirmed, unattributed and pending counts.
The retained read count includes all completed decisions, not just human ones.
Review is complete when pending is zero and the fix list is empty.

5. Feasibility check (task 1.5)
-------------------------------

This trains a disposable LoRA adapter for a few steps, reloads it in a fresh
process and prints GO or NO-GO. It is not adapter A.

    .venv/bin/python -m scripts.feasibility configs/feasibility.toml

It writes runs/<date>_<config name>/ with a reloadable config.toml, the
manifest (git commit and dirty state, source fingerprint, device, dtype,
hardware and library versions), metrics.json with every check, and the
adapter. A failed stage is recorded there as a NO-GO reason. Delete the folder
before running the same config again on the same day.

If it prints NO-GO, run the fallback with SmolLM2-1.7B-Instruct:

    .venv/bin/python -m scripts.feasibility configs/feasibility-smollm2.toml

Only MPS with bf16 has been measured. On CUDA the code uses bf16 when the GPU
supports it and fp16 otherwise, and fp32 on CPU, but none of these was tested.

Measured on 18 October 2026 at commit 94aa4ca (clean tree) on an Apple M3 Max
(38.7 GB, MPS, bf16), LoRA r 16 on all linear layers, batch 4, 30 steps, MPS
memory capped at 20 GB:

                                       SmolLM3-3B    SmolLM2-1.7B
    seconds per step (median, step 4+)       3.82            2.48
    max memory at a step end (GB)           12.37            8.90
    trainable / total parameters        30.2 M/3.11 B  18.1 M/1.73 B
    all base weights unchanged                yes             yes
    reload: same adapter file and argmax      yes             yes
    reload: largest probability gap      0.000033        0.00097
    reload: smallest gap to the base         0.21            0.45
    one adapter, extrapolated (min)          19.1            12.4

Step time is measured between synchronised step boundaries. Memory is the
Metal driver allocation read at the end of each step, so it can miss a peak
inside a step. The reload compares eight prompts in a fresh process with the
same memory cap.

The decision is GO for this disposable workload. The time for 400 dialogues
over 3 epochs (300 steps) is extrapolated from 30 steps on examples of about
304 tokens; it was not measured. Task 2.6 must measure it on the real corpus,
whose multi-turn dialogues are longer.

6. Notebook
-----------

    .venv/bin/jupyter notebook agent.ipynb

To execute it from the command line:

    .venv/bin/jupyter nbconvert --to notebook --execute --inplace agent.ipynb

7. Evaluation tooling (task 2.3b)
--------------------------------

Run the synthetic worked example with a fresh output directory:

    .venv/bin/python -m boxbox.evaluation fixtures --output runs/2026-10-19_evaluation-fixtures

It checks the 35 calibration targets and 55 synthetic annotations, then writes
the paired table, race-cluster intervals, a 40-target metadata quota witness
and an illustrative six-target/twelve-response review excerpt. The separate
version key and response lookup are outside the review CSV. Pending score
fields are not human ratings, and no model or race reconstruction is run.

The evaluator core uses the Python standard library. To test it separately
without the training stack, see docs/evaluation-tooling.md. Targeted checks:

    .venv/bin/python -m pytest -q tests/test_evaluation.py tests/test_race_card.py
    .venv/bin/ruff check boxbox/evaluation tests/test_evaluation.py
    .venv/bin/ruff format --check boxbox/evaluation tests/test_evaluation.py

The guide documents sample-before-generation, score, input/output ledgers,
the real-split integration and the final-test gate. Default final_test_open
stays false. Existing run directories are never overwritten.

8. Demo (task 2.4)
------------------

The Gradio pit-wall screen opens in the browser. Until task 2.8 it answers
with a stub that returns the rule's answer, and the screen says so:

    .venv/bin/python -m boxbox.app

The real race cards of the picker are committed in data/demo/ (CC BY-NC-SA
4.0, see data/demo/NOTICE). They come from validation races and are rebuilt
with:

    .venv/bin/python -m scripts.demo_cards

9. Conversation engine (task 2.5a)
----------------------------------

The shared conversation engine is implemented in boxbox/model/conversation.py.
It uses the pinned SmolLM3 tokenizer's native chat template, preserves the
current card and a bounded complete-turn history, and returns the unmodified
generated continuation. It is callable by the demo and evaluation code; the
demo keeps its explicit stub until task 2.8.

Run deterministic engine, demo-contract, config/run, policy and evaluator tests
without loading weights:

    .venv/bin/python -m pytest -q tests/test_conversation_engine.py tests/test_app.py tests/test_runs.py tests/test_race_card.py tests/test_evaluation.py

Run the real-model smoke using the pinned baseline and synthetic cases only:

    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.smoke_conversation --config configs/conversation-smoke.toml --name 2-5a-smollm3-smoke-repeat

The smoke creates a new ignored runs/<date>_2-5a-smollm3-smoke/ directory with
fixed case and input ledgers, output/error records, raw text, generated token
IDs, prompt/context traces and effective generation settings. It does not read
real validation, mini-test or final cases. Protocol 1.1.0 remains proposed;
automatic parser/agreement diagnostics are not human ratings. See
docs/conversation-engine.md for template, token/time bounds, errors and 2.5b,
2.6 and 2.8 handoffs.

10. Baseline prompt comparison (task 2.5b)
-----------------------------------------

Prepare the two declared zero-shot instruction orders on all 100 validation
targets. Validation source cards must be available locally in data/cards/;
the comparison never rebuilds data or opens mini-test/final cases.

    .venv/bin/python -m scripts.compare_prompts prepare --config configs/baseline-prompts.toml --name 2-5b-validation-prompts

Use the dated run path printed by prepare in both commands below:

    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.compare_prompts run --run-dir runs/2026-10-19_2-5b-validation-prompts
    .venv/bin/python -m scripts.compare_prompts score --run-dir runs/2026-10-19_2-5b-validation-prompts

Every candidate uses the same fixed input ledger and generation settings.
The run preserves raw outputs, failures, native-tokenizer preflight and traces.
Selection follows the proposed protocol's exact-fraction priorities; it saves
both candidates and the selected prompt/configuration for the baseline/A
handoff. An interrupted attempt cannot be silently resumed or selected.

    .venv/bin/python -m pytest -q tests/test_prompt_selection.py tests/test_compare_prompts.py tests/test_conversation_engine.py tests/test_evaluation.py tests/test_runs.py tests/test_race_card.py tests/test_app.py

See docs/baseline-prompts.md for the declared settings, result interpretation,
artifact hashes and selected-inference loading. Protocol acceptance, human
ratings, independent review and the collective 3.5 freeze are separate steps.

The retained inference uses configs/baseline-selected.toml and the exact prompt
identified in configs/baseline-selection.json. The policy-first candidate was
selected on strict format (75/100 versus 7/100); CALL agreement remained low
(16/100 versus 6/100). The guide records the raw results and limitations.

11. Adapter A (task 2.6)
------------------------

Adapter A is a LoRA adapter on the frozen SmolLM3-3B, trained on corpus A with
the inference prompt selected in 2.5b. It is trained with seeds 2026, 2027 and
2028. Check time and memory first, then train and validate each seed:

    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.train_adapter smoke
    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.train_adapter train --seed 2026
    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.train_adapter validate runs/2026-10-19_2-6-adapter-a-s2026

Each seed takes about 72 minutes of training and 10 of validation on an Apple
M3 Max. validate runs in a new process: it reloads the three epoch checkpoints,
answers the 100 validation targets and keeps one checkpoint. Then summarise
the three seeds and name adapter A, the median seed:

    .venv/bin/python -m scripts.train_adapter summarize runs/2026-10-19_2-6-adapter-a-s2026 runs/2026-10-19_2-6-adapter-a-s2027 runs/2026-10-19_2-6-adapter-a-s2028

Add --baseline with the 2.5b baseline answers to compare each seed with the
baseline through the race bootstrap. The original 2.5b run folder is not
available, so the baseline was re-run with scripts.compare_prompts (section 10)
and is passed with --rebuilt:

    .venv/bin/python -m scripts.train_adapter summarize runs/2026-10-19_2-6-adapter-a-s2026 runs/2026-10-19_2-6-adapter-a-s2027 runs/2026-10-19_2-6-adapter-a-s2028 --baseline runs/2026-10-20_2-5b-validation-prompts/selected/baseline-outputs.jsonl --rebuilt

--rebuilt accepts the re-run only when its prompt, cases and selection
measures equal the 2.5b record. Draw the loss curves into
docs/diagrams/adapter-a-losses.png with the same three run folders:

    .venv/bin/python -m scripts.train_adapter curves runs/2026-10-19_2-6-adapter-a-s2026 runs/2026-10-19_2-6-adapter-a-s2027 runs/2026-10-19_2-6-adapter-a-s2028
    .venv/bin/python -m pytest -q tests/test_training_rows.py tests/test_adapter_summary.py

summarize writes a new dated summary and configs/adapter-a-selection.json,
which records adapter A. push uploads the three selected checkpoints, the
summary and docs/adapter-a-card.md to the private repo of the team
organisation, then records the revision in that file:

    .venv/bin/python -m scripts.train_adapter push runs/2026-10-20_2-6-adapter-a-summary.json --repo ING3NLPProject/boxbox-adapter-a

Tasks 2.7 and 2.8 load adapter A with selected_adapter() from boxbox.model. It
returns the config, the adapter folder and the p01 prompt A was trained on, which
must be passed as instructions to load_conversation_engine. It uses the local
run folder or the recorded Hub revision, and refuses an adapter, config or prompt
whose hash differs. The Hub download needs a member's token in HF_TOKEN or
hf auth login.

Adapter A is seed 2028 at epoch 1. Over the three seeds, CALL agreement is
0.740 (95% interval 0.650 to 0.830) and every answer is in the strict format.
A still makes a call on 19 of the 20 targets with a missing field, which B
targets, and 4 or 5 answers per seed stop at the 64-token limit. See docs/adapter-a.md for the settings, the checkpoint table, the
seed intervals, the reload check and the incidents.

12. Adapter B (task 3.2)
------------------------

Adapter B is trained like adapter A, with the same settings and seeds, on
corpus B: 60 of A's 400 items are replaced by cards where a required field is
unknown and the answer is NO CALL. configs/adapter-b.toml differs from
configs/adapter-a.toml only by adapter = "B" and abstention_share = 0.15.
Check time and memory, then train and validate the three seeds in one command:

    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.train_adapter smoke --adapter B
    HF_HUB_OFFLINE=1 caffeinate -i -s .venv/bin/python -m scripts.train_adapter seeds --adapter B

seeds trains each seed, then validates it in a new process, and goes on to
the next seed if one fails. Logs go to runs/3-2-logs/. The three seeds take
about 4 hours on an Apple M3 Max. Then summarise B, compare it with A seed by
seed, and draw the loss curves:

    .venv/bin/python -m scripts.train_adapter summarize runs/2026-10-20_3-2-adapter-b-s2026 runs/2026-10-21_3-2-adapter-b-s2027 runs/2026-10-21_3-2-adapter-b-s2028 --against-a runs/2026-10-20_2-6-adapter-a-summary.json
    .venv/bin/python -m scripts.train_adapter curves runs/2026-10-20_3-2-adapter-b-s2026 runs/2026-10-21_3-2-adapter-b-s2027 runs/2026-10-21_3-2-adapter-b-s2028

summarize writes configs/adapter-b-selection.json, which selected_adapter()
reads like the file of A. The three selected checkpoints are in the private
repo ING3NLPProject/boxbox-adapter-b, whose revision is in that file:

    .venv/bin/python -m scripts.train_adapter push runs/2026-10-21_3-2-adapter-b-summary.json --repo ING3NLPProject/boxbox-adapter-b

Adapter B is seed 2027 at epoch 3. Against A with the same seed, unjustified
decisions fall by 0.550 on average, CALL agreement rises by 0.070, and
excessive refusals rise by 0.239, all on cards where an unknown field is not
needed.

The mini-test of task 2.7 also runs with B as a third version, in one process
with the baseline and A (docs/mini-test.md):

    .venv/bin/python -m scripts.mini_test prepare --name 3-2-mini-test-r2 --with-b
    HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.mini_test run --run-dir runs/2026-10-21_3-2-mini-test-r2
    .venv/bin/python -m scripts.mini_test score --run-dir runs/2026-10-21_3-2-mini-test-r2

On the 40 mini-test targets, B makes 1 unjustified decision on 16 against 9
for A, and refuses 6 of 24 decidable targets against 1 for A. See
docs/adapter-b.md for the tables, the comparison at equal updates, the
mini-test and the reading of these results.

13. Interim A/B analysis (task 3.3)
----------------------------------

docs/interim-ab-analysis.md compares the retained validation and exploratory
mini-test evidence, including B's reduction in unjustified decisions and its
increase in excessive refusals. docs/interim-ab-evidence.json holds exact counts,
paired transitions, uncertainty support and source hashes. This is an interim
analysis; B retention, protocol acceptance and the final freeze remain team
decisions. Human scores are still pending.

To check the retained evidence without loading a model, extract 3-2-runs.zip
and 2-6-logs.zip into separate local folders. From the repository root:

    .venv/bin/python -m scripts.interim_analysis --runs-root /path/to/extracted-3-2 --a-logs /path/to/extracted-2-6/2-6-logs --output /path/to/new-analysis.json
    .venv/bin/python -m pytest -q tests/test_interim_analysis.py tests/test_evaluation.py tests/test_adapter_summary.py tests/test_mini_test.py tests/test_corpus_b.py

The first directory contains the dated B runs and 3-2-logs as direct children.
The output must be a new file. The script checks the complete mini-test and B
validation ledgers against their retained scores. A's raw validation answers
are absent from these archives: the A/B validation race intervals remain the
retained 3.2 summary, with their arithmetic checked where possible. A's logs do
not replace those answers. No training, inference, final-data access or rating
is performed. Share masked rating sheets separately from the run archive,
which contains version identities and the key.

14. OpenJev zero-shot baseline (task 3.4)
-----------------------------------------

OpenJev Flash 9B, a decision model run without training, answers the CALL line
on the same validation and mini-test targets as the baseline, A and B. It is an
exploratory study. The model runs from its own environment, outside the
repository and outside the synced Documents folder:

    uv venv ~/openjev/mlx --python 3.12
    uv pip install --python ~/openjev/mlx/bin/python "mlx==0.32.2" "mlx-lm==0.31.3" "transformers==5.17.0" "openai==3.16.2" "httpx==0.28.1" "huggingface-hub==1.32.0"
    ~/openjev/mlx/bin/hf download openjev/OpenJev-Flash-9B-MLX-4bit --revision 33cbf3727276b3fc99a08104c33b22bf1c5f05dd --local-dir ~/openjev/OpenJev-Flash-9B-MLX-4bit
    ~/openjev/mlx/bin/hf download openjev/OpenJev-Flash-9B helper/shim.py helper/shim_mlx.py SHA256SUMS MANIFEST.json NOTICE LICENSE serve/SERVE.md README.md --revision b77b0fff67c77a76c16d4da50a66d2fdbc124fae --local-dir ~/openjev/openjev-flash-9b-api

The model is 5.04 GB. configs/openjev.toml pins both revisions, the hashes of
11 files, the readout values and the four questions. Each run hashes the files
again, starts the server on 127.0.0.1:3000 with HF_HUB_OFFLINE=1, checks its
version, answers every target once and stops it. Answer validation, the same
targets with the CALL options reordered, choose the threshold, score and
compare with the baseline, A and B:

    caffeinate -i .venv/bin/python -m scripts.openjev_baseline run --split validation
    caffeinate -i .venv/bin/python -m scripts.openjev_baseline run --split validation --shuffle 2026
    .venv/bin/python -m scripts.openjev_baseline threshold runs/2026-10-21_3-4-openjev-validation
    .venv/bin/python -m scripts.openjev_baseline score runs/2026-10-21_3-4-openjev-validation
    .venv/bin/python -m scripts.openjev_baseline compare runs/2026-10-21_3-4-openjev-validation --shuffled runs/2026-10-21_3-4-openjev-validation-shuffle-s2026

The validation run takes about 12 minutes on an Apple M3 Max, the reordered
run about 3. Then the mini-test, on the 40 targets of run r2 and with the
threshold of validation:

    caffeinate -i .venv/bin/python -m scripts.openjev_baseline run --split mini_test
    .venv/bin/python -m scripts.openjev_baseline score runs/2026-10-21_3-4-openjev-mini-test --tau-from runs/2026-10-21_3-4-openjev-validation
    .venv/bin/python -m scripts.openjev_baseline compare runs/2026-10-21_3-4-openjev-mini-test
    .venv/bin/python -m pytest -q tests/test_openjev.py

On the mini-test, OpenJev agrees with the reference call on 18 of 40 targets
with its most probable option and on 23 with the threshold of 0.59, against 10
for the baseline, 28 for A and 33 for B. 16 of 100 validation calls change
when only the option order changes. The weights are under CC BY-NC 4.0. See
docs/openjev.md for the research questions, the tables and the limits.

The upgrade round U1 uses configs/openjev-upgrade.toml: the CALL options get
descriptions from p01, and the question is asked in three option orders whose
probabilities are averaged. Run both splits, then compare U1 with the original
run, with τ chosen leaving one race out:

    caffeinate -i .venv/bin/python -m scripts.openjev_baseline run --split validation --config configs/openjev-upgrade.toml
    caffeinate -i .venv/bin/python -m scripts.openjev_baseline run --split mini_test --config configs/openjev-upgrade.toml
    .venv/bin/python -m scripts.openjev_baseline threshold runs/2026-10-21_3-4-openjev-upgrade-validation
    .venv/bin/python -m scripts.openjev_baseline score runs/2026-10-21_3-4-openjev-upgrade-validation
    .venv/bin/python -m scripts.openjev_baseline upgrade runs/2026-10-21_3-4-openjev-upgrade-validation --against runs/2026-10-21_3-4-openjev-validation
    .venv/bin/python -m scripts.openjev_baseline score runs/2026-10-21_3-4-openjev-upgrade-mini-test --tau-from runs/2026-10-21_3-4-openjev-upgrade-validation
    .venv/bin/python -m scripts.openjev_baseline compare runs/2026-10-21_3-4-openjev-upgrade-mini-test

U1 reaches 59 of 100 on validation with τ chosen leaving one race out, against
60 for the original. On the mini-test it gets 18 of 40 at argmax, as before,
and 21 with the threshold, against 23.
