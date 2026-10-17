# Code approach

The notebook tells the research story. The code it calls lives in one Python package, `boxbox`, with one subfolder per feature. Each experiment is a config file, and each run leaves a folder we can cite.

## Layout

```text
boxbox/                    Python package
  config.py                RunConfig: every setting the study varies
  runs.py                  creates a run folder and writes its manifest
  data/                    race data loaders, per-lap table, race cards, splits (2.1)
  rules/                   card contract and rule engine (1.4)
  corpus/                  training dialogues, A and B variants (2.2, 3.1)
  model/                   model loading, observation helpers, chat engine (1.5, 2.5a)
  training/                LoRA training, selection and reload (2.6, 3.2)
  evaluation/              scores, rubric sheets, paired statistics (2.3b, 4.x)
  app/                     Gradio interface (2.4), specs in docs/interface.md
configs/                   one TOML file per experiment
scripts/rebuild_data.py    rebuilds the race data from the command line
tests/                     pytest tests for deterministic code
agent.ipynb                executed notebook, from installation to interface
data/splits.json           race split manifest, committed
runs/                      one folder per run, not committed
data/cache/                downloaded race data, not committed
```

Numbers in parentheses are roadmap task IDs. A folder is created with its first task.

## Features

A feature is a subfolder of `boxbox`. Its `__init__.py` exports only the functions that other code or the notebook use, for example `from boxbox.rules import decide`.

Imports go one way. `rules` imports no other feature. `data` and `corpus` may use `rules`. `evaluation` and `app` may use `model` and `rules`. No feature imports `app` or the notebook.

Each data source has its own loader in `data/`, and every loader returns the same per-lap table. The rest of the code reads only that table.

## Configs

`RunConfig` in `boxbox/config.py` lists every setting the study varies:

- data source
- share of abstention examples (0 for A, 0.15 for B)
- prompt variant, zero-shot or few-shot
- number of history turns kept
- decoding settings
- adapter: none, A or B
- LoRA settings
- seed
- `final_test_open`, false until the freeze

The defaults describe the baseline. A file in `configs/` sets only what differs, and `tomllib` from the standard library reads it. We turn a feature off with a config value.

## Runs

Every run writes a new folder `runs/<date>_<name>/` and never overwrites an old one. It holds:

- `config.toml`, the exact config used
- `manifest.json` with git commit, seed, model revision, split manifest hash, device and duration
- `metrics.json`
- `outputs.jsonl` with every raw answer

These folders are our research log. A result or a gate decision in a GitHub issue cites its run ID.

## Protocol checks in code

Loading the splits checks that no race appears in two splits and that training dialogues come only from training races. The final-test loader stops with an error while `final_test_open` is false.

## Notebook

`agent.ipynb` follows the seven steps of the assignment. Each block is a short markdown cell saying what we do and why, a code cell of about 15 lines that calls `boxbox`, its output, and a comment on that output. The notebook defines no reusable function.

Training cells check a `RUN_TRAINING` flag. When it is false they load a saved run folder, so a clean full execution stays short and still shows the losses.

One person edits the notebook at a time. Outputs are committed only in the final executed version.

## Tests

We test deterministic code: rules, data, splits and the evaluator. Tests use small hand-written cases, especially threshold edges, missing fields and the exact `CALL:` and `WHY:` format. Model answers are scored in evaluation.

## Style

- English names, comments and docstrings
- type hints and short functions
- `ruff format` and `ruff check` with default settings
- exact versions pinned in `requirements.txt`
- `get_device()` picks CUDA, then MPS, then CPU, so the same code runs on a Mac or a cloud GPU
- fixed seeds

## Git

- one branch per issue, named after its task ID, for example `2.1-race-cards`
- a pull request reviewed by another member before merge
- `main` always runs
- no raw data, run folders, adapters or tokens in Git: adapters go to the Hugging Face Hub, tokens stay in a local `.env`
