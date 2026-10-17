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

3. Feasibility check (task 1.5)
-------------------------------

This trains a disposable LoRA adapter for a few steps, reloads it in a fresh
process and prints GO or NO-GO. It is not adapter A.

    .venv/bin/python -m scripts.feasibility configs/feasibility.toml

It writes runs/<date>_feasibility/ with config.toml, manifest.json,
metrics.json and the adapter. Delete that folder before running it again on
the same day.

Measured on 17 October 2026 on an Apple M3 Max (36 GB, MPS), with bf16 LoRA
(r 16, all linear layers, batch 4) and the MPS memory capped at 20 GB:

    3.68 s per step after warm-up, 13.44 GB peak memory
    30.2 M trainable parameters out of 3.11 B, base weight unchanged
    fresh-process reload: same argmax, probabilities within 0.00016
    one adapter (400 dialogues, 3 epochs, 300 steps): about 18.4 min
    decision: GO (limits: 60 min and 20 GB per adapter)

The estimate assumes examples as long as the disposable ones, about 290
tokens each. Multi-turn dialogues are longer and will take more time per step.

4. Notebook
-----------

    .venv/bin/jupyter notebook agent.ipynb

To execute it from the command line:

    .venv/bin/jupyter nbconvert --to notebook --execute --inplace agent.ipynb
