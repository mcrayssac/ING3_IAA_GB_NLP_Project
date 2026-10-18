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

4. Feasibility check (task 1.5)
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

5. Notebook
-----------

    .venv/bin/jupyter notebook agent.ipynb

To execute it from the command line:

    .venv/bin/jupyter nbconvert --to notebook --execute --inplace agent.ipynb
