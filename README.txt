BoxBox run guide
================

Run every command from the repository root.

Start here: package, reload and reproduction (task 5.2)
-------------------------------------------------------

What is delivered. The Git repository holds the code, configs, tests, the
notebook agent.ipynb, this guide and the data the project created:
data/splits.json (frozen race splits), data/corpus/ (corpora A and B,
validation, mini-test), data/final/ (the 200 final cases and the 40 review
targets) and data/demo/ (the demo cards). Raw OpenF1 and Jolpica responses
(data/cache/), race cards (data/cards/, data/cards-v2/) and run folders
(runs/) are never committed: a script rebuilds them (section C).

The two retained adapters are outside Git, with the same bytes in two places:

    boxbox-adapters.zip, 224,010,171 bytes
    SHA-256 984bd6ad254d2903a360ba0ab51099df760961d420457f20b88f70689a7dc7a6

    A  https://huggingface.co/ING3NLPProject/boxbox-adapter-a, revision
       ece13db9ea1770a338156250501bc7a17d327235, folder s2028-e1
    B  https://huggingface.co/ING3NLPProject/boxbox-adapter-b, revision
       f182f8e9150fa518576eb99c0785bae5dd3ed5f8, folder s2027-e3

The Hub repos are private: without the token of a member of ING3NLPProject
they answer 401 (checked on 23 October 2026). A reader uses the zip. Unzipped
at the repository root, it puts the two checkpoints where selected_adapter()
looks first, runs/2026-10-19_2-6-adapter-a-s2028/trainer/checkpoint-120 and
runs/2026-10-21_3-2-adapter-b-s2027/trainer/checkpoint-360, with their cards,
licence notice and hashes in runs/boxbox-adapters/. Either way, the loader
refuses weights whose SHA-256 differs from configs/freeze.json. The zip was
made from local copies of the two Hub repos, and it can be made again, byte
for byte, from such copies (a browser download may add " (1)" to file names):

    .venv/bin/python -m scripts.package adapters --from-a DIR_A --from-b DIR_B --output boxbox-adapters.zip

Other study artifacts stay outside Git, kept by the team. The notebook
(section 6) reads the first three; 4.4 and 4.5 (section B) read the 4.2 run
folder, and 4.5 also the 4.3 review sheet with its second reviews and the
initial ratings, whose hashes are in docs/final-findings-evidence.json
(provenance).

    4.2-final-delivery.zip   the 4.2 run folder, with the final answers
    SHA-256 2993ac76fe620d3aaf3df811369fdd88a4fbdd1911e0c8582318b6af99896a2b
    2-6-logs.zip             console logs of the three training runs of A
    SHA-256 661b1673828bd00e5849062e4c8b6997f34281a07616c07b6d6c5310ba967898
    3-2-runs.zip             run folders of B's three seeds and of the 3.2
                             mini-test, without the adapter weights
    SHA-256 c335689384bfe155f2fa9b24e57a701674933c7a5c3083411a54d2e01f75a04c

A. Requirements, versions and resources

Python 3.13 and uv, with the exact versions of requirements.txt (torch 2.14.1,
transformers 5.20.1, peft 0.21.2, trl 1.16.0, gradio 6.30.0). Only macOS on
Apple silicon with MPS and bf16 was measured; CUDA and CPU were not tested.
Sizes and times measured on 23 October 2026, except the final scoring (21
October) and the training (19 to 21 October):

    base model SmolLM3-3B in the Hub cache      6.15 GB (downloaded once)
    .venv after installing requirements.txt     1.2 GB
    boxbox-adapters.zip / unzipped              224 MB / 242 MB
    OpenF1 cache and 1.0 cards, 70 races        38 MB and 40 MB
    data rebuild from the network (section C)   32.8 min on an Apple M1
    load one adapter, then answer one card      10 to 13 s each, Apple M1 16 GB
    final scoring, 600 answers (4.2)            6,068.5 s of generation, Apple M1
    training, one seed (sections 11 and 12)     about 72 min, Apple M3 Max 38.7 GB
    notebook, clean execution (section 6)       6 min 43 s, Apple M1 16 GB

Training was measured only on the M3 Max with the MPS memory capped at 20 GB.

Check the installation, the freeze, the licences, raw data kept out of Git and
the adapter links as a reader without a token:

    .venv/bin/python -m scripts.package check --adapters boxbox-adapters.zip

It prints a JSON report and exits with 1 when a check fails. A Hub link that
answers 401 is reported, not failed, when the zip holds the frozen weights.
--offline skips the Hub. It loads no model.

B. Reload path: the frozen versions without training

    git clone https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project.git
    cd ING3_IAA_GB_NLP_Project
    uv venv --python 3.13 .venv
    uv pip install --python .venv/bin/python -r requirements.txt
    unzip /path/to/boxbox-adapters.zip
    .venv/bin/python -m pytest -q tests
    .venv/bin/python -m boxbox.app -A

-B answers with adapter B (section 8). The notebook (section 6) loads adapter A
the same way. The first model load downloads the public base model; no token
is needed. On 23 October 2026, in a fresh clone of main at f45946c with the zip
unzipped, A and B loaded from runs/ with HF_HUB_OFFLINE=1 and no token, and
each answered one fixture card in the strict two-line format. In a new .venv
installed from requirements.txt, the full test suite of this task's branch
passed (543 tests, 2 min 53 s).

With the 4.2 run folder copied intact into runs/, the paired analysis of 4.4
runs again without a model, and the 4.2 run verifies at the commit that
merged its runner (757df9d); later commits change the sources it seals:

    .venv/bin/python -m scripts.final_analysis run --run-dir runs/4-2-final-50067b54741c-49b4aea370af
    git worktree add --detach ../boxbox-4-2 757df9d
    (in ../boxbox-4-2, with the run folder copied into its runs/)
    ../ING3_IAA_GB_NLP_Project/.venv/bin/python -m scripts.final_scoring verify --run-dir runs/4-2-final-50067b54741c-49b4aea370af

On 23 October 2026 the analysis rerun gave a docs/final-analysis-evidence.json
equal to the committed one, and verify passed at 757df9d. The findings of 4.5
also need the two review files above; they were not run again.

Reloading shows what the frozen adapters answer. It is not training evidence:
the losses, the three seeds, the checkpoint choice and the stopping rule come
from the training runs (sections 11 and 12, docs/adapter-a.md, docs/adapter-b.md).

C. Rebuild the submitted data

The cards behind the frozen corpus and final cases rebuild exactly only at
commit 631b783 (section 3). Rebuild them in a separate worktree, with the
.venv of the repository, then compare with the committed files. From the
repository root, with the repository folder named ING3_IAA_GB_NLP_Project:

    git worktree add --detach ../boxbox-frozen 631b783
    cd ../boxbox-frozen
    ../ING3_IAA_GB_NLP_Project/.venv/bin/python -m scripts.rebuild_data cards
    ../ING3_IAA_GB_NLP_Project/.venv/bin/python -m scripts.build_corpus build
    git status --porcelain
    ../ING3_IAA_GB_NLP_Project/.venv/bin/python -c "from boxbox.config import load_config; from scripts.train_adapter import validation_cases; validation_cases(load_config('configs/baseline-selected.toml'))"
    mv data/final data/final-committed
    ../ING3_IAA_GB_NLP_Project/.venv/bin/python -m scripts.final_cases build
    cd ../ING3_IAA_GB_NLP_Project
    .venv/bin/python -m scripts.package rebuilt --root ../boxbox-frozen

git status prints nothing when the corpus is rebuilt byte for byte; the
one-line check stops if the 100 validation cases differ from those of 2.5b.
rebuilt compares the corpus, the final dialogues, cases, review targets and
manifest (build time and commit aside), and the final card files with the
hashes of data/final/manifest.json.

Done on 23 October 2026 from the network: 70 races, 0 failures, 32.8 min.
The corpus files and their manifest were identical, and so were the 100
validation cases (ba30d2a6832b) and the 40 mini-test cases (144c48b86b55).
final.jsonl, cases.jsonl and review-selection.json were identical, at 631b783
and at ddda0f3, the commit recorded in data/final/manifest.json. The 7 final
card files hold the same cards, but their recorded hashes are those of the
same files with CRLF line ends: Path.write_text writes CRLF on Windows, where
the final cards were built. rebuilt accepts both and says which. The rebuild
keeps OpenF1 and Jolpica data on the machine; do not publish data/cache/ or
data/cards/.

D. Full reproduction, in order

    1. Install and test (sections 1 and 2), then rebuild the data (section C).
    2. Feasibility check, optional (section 5).
    3. Baseline prompts on validation (section 10).
    4. Adapter A, three seeds (section 11), then adapter B (section 12).
    5. Interim A/B analysis (section 13); OpenJev, exploratory (section 14).
    6. Freeze: python -m scripts.freeze check (docs/freeze.md). The record of
       21 October is never written again.
    7. Final cases (docs/final-cases.md), as rebuilt in section C.
    8. Final scoring (4.2, below). The retained run is the only final run; do
       not generate another final comparison.
    9. Human review (4.3), paired gains (4.4) and findings (4.5), below.
    10. The notebook (section 6), which shows the whole study in one run and
        launches the screen.

Steps 3 to 5 regenerate model answers and train new adapters. They were not
run again in task 5.2, so whether a new training gives the same weights byte
for byte is not known. The study's results are those of the frozen
checkpoints, identified by their hashes in configs/freeze.json.

E. Licences

    code, docs, notebook       Apache 2.0 (LICENSE)
    SmolLM3-3B, base model     Apache 2.0 (Hub card), not redistributed
    OpenF1 data                CC BY-NC-SA 4.0, non-commercial
    Jolpica-F1 data            CC BY-NC-SA 4.0 (its terms of use), non-commercial
    data/corpus, data/final,
    data/demo                  CC BY-NC-SA 4.0 (NOTICE in each folder)
    adapters A and B           CC BY-NC-SA 4.0 (Hub cards, NOTICE in the zip)
    OpenJev Flash 9B           CC BY-NC 4.0, optional, not included
    Open-Meteo forecast        CC BY 4.0, Replay tab only, cached locally
    boxbox.wav                 third-party clip, terms not checked (README.md)

The timing data belongs to the Formula 1 companies. The raw responses and
cards stay local, and only the script that rebuilds them is shared.

1. Install
----------

Python 3.13 and uv are required.

    uv venv --python 3.13 .venv
    uv pip install --python .venv/bin/python -r requirements.txt

The first model load downloads HuggingFaceTB/SmolLM3-3B at revision
a07cc9a04f16550a088caea529712d1d335b0ac1 (Apache 2.0, about 6.2 GB of weights).

2. Tests
--------

    .venv/bin/python -m pytest -q tests

Always pass the tests folder: without it, pytest also searches runs/, whose
run folders keep copies of the sources, and fails on their imports.

3. Race data (task 2.1)
-----------------------

The race-level splits are frozen in data/splits.json (committed). The cards are
rebuilt from OpenF1 and Jolpica. Responses are cached in data/cache/openf1/ and
cards written to data/cards/; neither is committed. Without a cache the
rebuild makes 286 requests, one every 2.1 s at OpenF1's free rate, so at least
10 minutes. From the cache it took 77 s on an M3 Max.

    .venv/bin/python -m scripts.rebuild_data cards
    .venv/bin/python -m scripts.rebuild_data card --race 2024-01 --driver 1 --lap 20

The cards command rebuilds the 1.0 cards with the corrected track status of
the Experimental milestone (last section): 65,674 cards instead of the 65,904
of 18 October, and 16 races get their real distance back. The frozen corpus and
results were built from the cards of 18 October, which only commit 631b783 (the
last commit before the milestone was merged) rebuilds exactly. Do not run this
command over a data/cards/ folder you still need. With rebuilt cards,
validation_cases and the steps built on it stop with "V-001: card differs from
its recorded source/transformation". Section C of "Start here" rebuilds the
frozen cards at 631b783 and compares them with the committed files.

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

agent.ipynb is the notebook of the submitted study: the installation (its
section 0), then the seven steps of the assignment, from the definition of the
agent to the Gradio screen. The committed file keeps the outputs of its clean
execution in task 5.4. The Experimental milestone does not change it.

It reads four archives kept outside Git ("Start here"). From the repository
root, with the archives in the folder above it:

    unzip -q -n ../boxbox-adapters.zip
    unzip -q -n ../2-6-logs.zip -x "__MACOSX/*" -d runs
    unzip -q -n ../3-2-runs.zip -d runs
    unzip -q ../4.2-final-delivery.zip "run/*" -d ../4-2-delivery
    mv ../4-2-delivery/run runs/4-2-final-50067b54741c-49b4aea370af
    rmdir ../4-2-delivery

-n never replaces a file: 3-2-runs.zip holds B's adapter_config.json again,
with the same bytes as boxbox-adapters.zip. Section 0 of the notebook names
the files that are missing, and the first cell that reads one stops with a
FileNotFoundError on its path. Section 0 also reads the model's licence on the
Hub, so the notebook needs network access. Then open it, or execute it from the
command line:

    .venv/bin/jupyter notebook agent.ipynb
    .venv/bin/jupyter nbconvert --to notebook --execute --inplace agent.ipynb

Two flags set what it runs. RUN_TRAINING, in section 5, is False: the cell
reads the losses of the real training runs from the archives above (A's logs
print them with four significant digits, B's run folders keep the exact
values). True runs the seeds command of section 11 for A, which trains and
validates three new seeds, each step in a fresh process (about 72 minutes of
training and 10 of validation per seed on the M3 Max), then reads their run
folders. It needs the memory of training beside the model the notebook holds,
and task 5.4 did not run it: a stand-in for the command checked only that the
cells read new run folders. RUN_DEMO, in section 7, is True: it launches the
screen with adapter A on 127.0.0.1, private (share=False), for as long as the
kernel runs. The notebook loads SmolLM3-3B once and puts adapter A on it, so it
holds one model in memory (6.5 GB in bf16). It never generates a final answer:
section 6 checks the sealed 4.2 run and computes the analysis of 4.4 again from
its answers.

Done on 23 October 2026 (task 5.4) on an Apple M1 with 16 GB, macOS 26.6.2, in
a new .venv installed from requirements.txt in a new worktree of main at
17e2113, with the four archives unpacked as above: the nbconvert command exited
with 0 in 403 s, the 29 code cells ran in order, and no output is an error. The
base model and the packages came from the local Hugging Face and uv caches.
The earlier executions of the task gave the same values, the sampled answers of
section 2 included, timings aside. Two warnings stay in the outputs, a
tokenizer note of transformers and the pop-up message of a refused upload. One
more execution, with the same outputs, kept its kernel running while a script
outside the repository drove
the screen from headless Chrome: a typed question, the quick questions "Why?"
and "Will it rain later?", Reset, a file that is not JSON and a change of card
gave the answers and messages of section 7, with no error in the page. No
person clicked through the screen for this check.

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

The Gradio pit-wall screen opens in the browser:

    .venv/bin/python -m boxbox.app

Started this way, the screen answers with a stub that returns the rule's
answer, and it says so. -A or -B answers with SmolLM3-3B and the selected
adapter A or B instead, with its training prompt and decoding:

    .venv/bin/python -m boxbox.app -B

The adapter comes from its local run folder or from the private Hub repo
recorded in configs/adapter-a-selection.json or adapter-b-selection.json, and
is refused if its hash differs. Unzipping boxbox-adapters.zip ("Start here")
fills both local run folders, so no token is needed. With -A or -B, the badge names the seed and
epoch of the adapter, and a line under the call gives the format
check, the generation time, the tokens, why generation stopped and how much of
the conversation was sent. A warning on the call says when the token or
time limit may have cut the answer. boxbox.wav in the project folder plays
on each new BOX answer of the Card tab, and on the Replay tab on each new
card whose policy 2.0 call is BOX. boxbox.wav comes from the YouTube video
"Box Box Ringtone" (https://www.youtube.com/watch?v=ec0Ku7YxdY0). It is third-party
material, not covered by the Apache License of this project, and its terms have not
been checked. The
notebook (see section 6 of this guide)
launches the same screen with adapter A in its section 7, connected in task 2.8.

-O answers with OpenJev Flash 9B, the zero-shot decision model of task 3.4,
once it is installed as section 14 shows:

    .venv/bin/python -m boxbox.app -O

The app hashes the pinned files again, starts the pinned server on
127.0.0.1:3000 from its own environment, offline, and stops it when the app
closes. Each message sends the request of the study and answers at
tau = 0.59. The badge reads "OpenJev Flash 9B · zero-shot". OpenJev writes no reason, so WHY gives its CALL probabilities and,
on NO CALL, the card field it names. The weights are under CC BY-NC 4.0.

-R starts the same server for the Replay tab only (see below) and combines
with -A or -B:

    .venv/bin/python -m boxbox.app -B -R

-O gives the Replay tab the same button. OpenJev peaks near 29.5 GB on the
M3 Max (docs/openjev.md), so -R with -A or -B needs the memory of both models.

The real race cards of the picker are committed in data/demo/ (CC BY-NC-SA
4.0, see data/demo/NOTICE). They come from validation races and are rebuilt
with:

    .venv/bin/python -m scripts.demo_cards

The screen has two tabs. The Card tab is the
screen above. The Replay tab (task 4bis.3) plays a race back on a circle
against a race clock, at x1, x2 or x4. It opens on Las Vegas 2024 with RUS (63).
One bar holds the pickers, a Play/Pause button, the speed, "Jump to lap" (which
follows the race lap) and the clock. For the chosen driver it shows the policy
2.0 call on the 2.0 card, or IN PIT and OUT LAP around a stop, its tyre, and a
pit window that follows the track status at the clock. Around the circle it
shows the flag, the weather, an archived forecast and the running order. The
tab has no chat. With -R or -O, a button "Ask the model" sends the 2.0 card on
screen to OpenJev with a policy 2.0 prompt (boxbox/model/policy2_prompt.py) and
shows, beside the rule's call, its call, its three probabilities and whether it
agrees with the rule. It is zero-shot and writes no reason, an answer takes
about four seconds (one order), and its agreement with policy 2.0 on a
sample of validation and mini-test cards is measured by
scripts/replay_model_check.py (docs/4bis-decisions.md, D15). The race list holds the races of the open splits of
data/splits-v2.json, so final and test_2026 stay out. Choosing a race rebuilds
its cards in memory in a few seconds. The tab needs:

    the OpenF1 cache in data/cache/openf1/, or network access to download it
    data/splits-v2.json, data/reference/priors-v2.json and
    data/reference/pit-loss-reference.csv (all committed)

and, optionally, network access to Open-Meteo for the forecast, cached in
data/cache/open-meteo/ (weather data by Open-Meteo.com, CC BY 4.0). Without
it the forecast panel says it is unavailable.

9. Conversation engine (task 2.5a)
----------------------------------

The shared conversation engine is implemented in boxbox/model/conversation.py.
It uses the pinned SmolLM3 tokenizer's native chat template, preserves the
current card and a bounded complete-turn history, and returns the unmodified
generated continuation. It is callable by the demo and evaluation code, and
the notebook demo has used it since task 2.8.

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
hf auth login; without one, unzip boxbox-adapters.zip ("Start here").

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

Frozen final scoring (4.2)
--------------------------
After the accepted freeze and integrated final cases, follow
  docs/final-scoring.md
from the repository root. The runner checks the frozen baseline/A/B, preserves
all raw results and errors, and supports explicitly logged technical resumes:
  python -m scripts.final_scoring prepare
  python -m scripts.final_scoring run --run-dir RUN_DIRECTORY_PRINTED_ABOVE
  python -m scripts.final_scoring seal --run-dir RUN_DIRECTORY_PRINTED_ABOVE
  python -m scripts.final_scoring verify --run-dir RUN_DIRECTORY_PRINTED_ABOVE
Do not create another run to improve final answers. Human review and statistical
analysis use the saved outputs in tasks 4.3 and 4.4. Run folders are local/ignored
and must be copied intact to hand over results. On 21 October, the initial Hub
access failure was resolved with locally supplied checkpoints matching the freeze.
Run runs/4-2-final-50067b54741c-49b4aea370af completed with 600 responses (200 each),
zero request errors and no technical resume; seal/verify passed. Its 120 review
rows remain pending. Counts and hashes: docs/final-scoring-results.json. Preserve
this run and reuse it; do not generate another final comparison.
The 4.2 results page includes the unjustified-decision and excessive-refusal
rates, decision coverage, family agreement and the expected/predicted CALL table.
These are descriptive counts; paired gains and race-level uncertainty belong to
task 4.4. The complete 1,940-file handover archive is 4.2-final-delivery.zip
(SHA-256 2993ac76fe620d3aaf3df811369fdd88a4fbdd1911e0c8582318b6af99896a2b).
The archive contains the run, code, tests and audit evidence; it is stored
outside Git and should be copied intact.

Paired gains and uncertainty (4.4)
----------------------------------
With the 4.2 run folder copied intact into runs/, compute the paired contrasts
of protocol 1.1.0 (A minus baseline and B minus A, plus B minus baseline as
exploratory) with the whole-race bootstrap (seed 2026, 10,000 draws):
  .venv/bin/python -m scripts.final_analysis run --run-dir runs/4-2-final-50067b54741c-49b4aea370af
The script checks the freeze, the run's completion record and its cases before
reading any output, and writes a new runs/<date>_4-4-final-analysis folder.
docs/final-analysis.md gives the tables and the reading, and
docs/final-analysis-evidence.json every measure with its interval.
Human review (4.3)
------------------
Copy review/review.csv from the 4.2 run to a folder outside the repository, then
generate the offline rating page, check progress and import the completed sheet:
  python -m scripts.human_review page --run-dir RUN --sheet review-rated.csv --output review-page.html
  python -m scripts.human_review check --run-dir RUN --sheet review-rated.csv
  python -m scripts.human_review import --run-dir RUN --sheet review-rated.csv --output ratings-initial.jsonl
See docs/human-review.md for masking limits, second reviews and closure evidence.
Do not edit the sheet in a spreadsheet application; use the page and its CSV export.

Findings and five cases (4.5)
-----------------------------
With the 4.2 run folder in runs/, the completed 4.3 sheet with its second reviews
and the initial ratings of 4.3 (both kept outside the repository), join the human
scores to the paired gains and pick the five cases:
  .venv/bin/python -m scripts.final_findings run --run-dir runs/4-2-final-50067b54741c-49b4aea370af --sheet review-rated-second.csv --initial ratings-initial.jsonl
The script runs the 4.4 checks, refuses a sheet whose primary scores differ from
the initial ratings, and stops unless the automatic summaries equal those of 4.2
and 4.4. It writes a new runs/<date>_4-5-final-findings folder. docs/final-findings.md
gives the tables, the verdicts on H1 and H2 and the five cases, and
docs/final-findings-evidence.json every number.

Experimental milestone (4 bis)
------------------------------

The Experimental milestone adds the 2026 season, track status read from
race-control timestamps, 2.0 race cards, policy 2.0 (calls under a safety car,
a virtual safety car and rain) and the Replay tab (section 8). The adapters A
and B, and every result of the study, were trained and scored on 1.0 cards with
policy 1.1: no trained model has read a 2.0 card or policy 2.0, and training on
2.0 cards is future work. The frozen versions and results are not re-run, and
the freeze check still passes (the known limits of the milestone are listed at
the end of docs/4bis-decisions.md):

    .venv/bin/python -m scripts.freeze check

docs/4bis-decisions.md records the decisions and their checks, and
docs/race-card-contract-v2.md the 2.0 card and policy 2.0. The data is built
in this order, from the OpenF1 cache or the network:

    .venv/bin/python -m scripts.rebuild_data splits-v2
    .venv/bin/python -m scripts.rebuild_data priors
    .venv/bin/python -m scripts.rebuild_data cards-v2
    .venv/bin/python -m scripts.rebuild_data quality

splits-v2 froze data/splits-v2.json once, on 22 October 2026 (87 races, with
the last three 2026 races in a closed test_2026), and refuses to overwrite it.
priors writes data/reference/priors-v2.json from the 60 train races. Both files
are committed, so a fresh checkout can start at cards-v2, which writes
data/cards-v2/ and its manifest (not committed). quality compares the computed
gap ahead with OpenF1's intervals on validation, mini_test, final and
test_2026; these intervals never feed a card. Section 3 explains why the cards
command gives corrected 1.0 cards on this branch.

reality_check measures how often a policy says BOX when cars really stopped.
It reads data/cards-v2/, so run cards-v2 first. Its default splits are
validation, mini_test and final, and --splits picks others. With --thresholds
it prints, per compound, the 25th percentile and the median tyre loss on the
cards of real green stops; the wear limits of policy 2.0 come from the train
races:

    .venv/bin/python -m scripts.reality_check
    .venv/bin/python -m scripts.reality_check --splits train --thresholds

On the evaluation races, policy 2.0 says BOX at the start of 53.6% of the
real stop laps (recall), and 15.6% of its BOX cards are followed by a stop
within two laps (precision), against 8.0% for a random BOX. Policy 1.1 reaches
1.5% and 7.2%. On test_2026, opened with the policy frozen, run again after the
replay's causality fixes and a third time after the 2026 VSC fix, each time
with no policy change, policy 2.0 gives 45.9% and 18.9% against 11.6%.
docs/4bis-decisions.md gives the race by race figures and the limits of this
comparison.

Any 1.0 or 2.0 card prints its CALL and WHY lines with the command below. A
1.0 card gets policy 1.1, a 2.0 card policy 2.0:

    .venv/bin/python -m boxbox.rules CARD.json

Targeted checks:

    .venv/bin/python -m pytest -q tests/test_cards_v2.py tests/test_policy2.py tests/test_priors.py tests/test_replay.py

Ask the model on the Replay (4bis.4)
------------------------------------
The Replay tile asks OpenJev (section 14) about the 2.0 card on screen, with the policy 2.0
prompt of boxbox/model/policy2_prompt.py and configs/openjev-replay.toml. Start it with -R
(section 8). Its agreement with policy 2.0 is measured on a sample of validation and
mini-test cards, by the call of policy 2.0 and the track condition, with the server started
and stopped by the script; final and test_2026 stay closed:
  .venv/bin/python -m scripts.replay_model_check sample
  caffeinate -i .venv/bin/python -m scripts.replay_model_check run
  .venv/bin/python -m scripts.replay_model_check score runs/<date>_replay-model-check --write
score chooses tau on validation with the rule of #35, applies it once to mini-test, keeps
three orders (the check always asks three) unless the first alone does as well, and writes
data/reference/replay-model-check.json, which the tile reads. Targeted checks:
  .venv/bin/python -m pytest -q tests/test_replay_model_check.py tests/test_policy2_prompt.py tests/test_openjev.py
