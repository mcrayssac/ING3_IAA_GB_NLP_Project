# Frozen final scoring (task 4.2)

`python -m scripts.final_scoring` runs the retained baseline, A and B on the
200 cases delivered by [4.1](final-cases.md). It reuses the shared conversation
engine and evaluator. The [freeze](freeze.md), final cases, prompt, decoding,
selection files and policy are checked before any model call. It neither rebuilds
cards nor selects a prompt or checkpoint.

## Run once

Use the project environment from `README.txt`, from the repository root on the
`main` branch. This runner supports macOS and Linux (including Colab); its process
lock uses `fcntl`. First make both pinned adapters accessible through the selected
local checkpoint folders or authenticated Hugging Face access, as described in
[adapter A](adapter-a.md) and [adapter B](adapter-b.md). Keep tokens outside Git and
outside run artifacts.

```sh
python -m scripts.freeze check
python -m scripts.final_scoring prepare
```

`prepare` prints the run directory. For the integrated freeze and case ledger it is:

```text
runs/4-2-final-50067b54741c-49b4aea370af
```

The deterministic name deliberately does not include today's date: a second
preparation cannot silently create a new final experiment in the same checkout.
Only this prepared directory should be used by the team; independent clones cannot
enforce a shared execution lock. Do not prepare another run to improve answers.

```sh
python -m scripts.final_scoring run \
  --run-dir runs/4-2-final-50067b54741c-49b4aea370af
python -m scripts.final_scoring seal \
  --run-dir runs/4-2-final-50067b54741c-49b4aea370af
python -m scripts.final_scoring verify \
  --run-dir runs/4-2-final-50067b54741c-49b4aea370af
```

The baseline runs first with no adapter attached, then A and B use the same base
model, tokenizer and machine in that process. Model/tokenizer revision, native
chat template, fixed template date, prompt, history and effective generation
settings remain frozen. The adapter weights must match the selected SHA-256;
the saved PEFT configuration is checked against the frozen LoRA settings and
copied into the run before loading. The adapter's selected seed is recorded in
its version entry and generation trace. `config_sha256` hashes the exact saved
effective `versions/<version>/config.toml`, including the selected checkpoint
seed. `frozen_config_sha256` and `frozen-config.toml` separately retain the source
TOML from the freeze. Greedy decoding does not use that seed.

All 200 inputs are prepared before generation. They contain only the card, fixed
history and current message, never the target reference answer. Each version sees
the same tokens. No history reduction, raw-response repair or quality retry is
performed. The frozen 64-token and cooperative 30-second limits apply unchanged;
the time limit cannot interrupt a blocked backend operation.

## Technical interruption

Each request has a durable `start.json` written before inference, followed by an
atomically published `result.json` (raw output and trace together) and a hash
receipt. A concurrent process is refused. Files are never replaced by the runner.
A session records its environment, start, readiness, completion or exception.

After investigating an interruption, continue the **same** directory:

```sh
python -m scripts.final_scoring run \
  --run-dir runs/4-2-final-50067b54741c-49b4aea370af \
  --resume-reason 'Describe the actual technical interruption and recovery'
```

A reason is mandatory after the first session. Code, configs, machine, libraries,
generation settings, prepared tokens and history must match. Existing results,
including generation errors, are retained without another call. A request that
started but has no durable result becomes `generation_error` with code
`interrupted_request`; it is not generated again. This records a known interrupted
attempt, not an invented model response. A saved result whose receipt was interrupted
receives a recovery receipt without regeneration. Only untouched requests run.
A setup failure is logged at session level and does not fabricate 600 model errors.

A successful uninterrupted run uses one process. An explicit technical resume uses
a new process on the same host and is visible in `sessions/`; it must be disclosed
with the final results. Missing request records prevent sealing. A failed request
remains in the 200-case denominator for its version.

## Evidence and handover

The run holds:

- `plan.json`, `manifest.json`, `sources/`, `versions/`, `cases.jsonl` and
  `inputs.jsonl`: frozen identifiers, byte copies, actual source fingerprint and
  Git state (including an uncommitted implementation).
- `runtime.json`, `preflight.jsonl`, `sessions/` and `requests/`: effective settings,
  prepared messages/tokens, explicit resume reasons, individual raw results,
  generation traces, failures and checksums. The immutable preparation manifest
  points to `runtime.json` for device/dtype and `complete.json` for wall time since
  preparation, including interruptions; this is not summed inference latency.
- After `seal`: `outputs.jsonl`, `attempts.jsonl`, `paired.csv`, `coverage.json` and
  `complete.json`. The complete inventory detects changes and extra artifacts;
  `verify` checks it and revalidates all pairings and case-to-trace bindings.
- `review/review.csv`: the same 40 targets selected in 4.1 for all three versions,
  120 pending responses. `review/version-key.json` and `response-lookup.json` are
  separate identity keys. However, the complete handover archive also contains
  both keys plus version-labelled `outputs.jsonl` and `paired.csv`. Anyone with
  the full archive can unmask the review rows. For 4.3, distribute only
  `review/review.csv` to raters and record that the archive was available to the
  team, including any rater's prior access; do not call the ratings blinded if
  a rater could unmask them.

Keep the completed directory unchanged and copy it intact for handover. Run folders
remain ignored by Git; publishing the code alone does not deliver the results.
Checksums and exclusive writes provide integrity checks, not externally certified
or cryptographic write-once storage. `seal` may resume an interrupted export only
when every already existing export agrees byte for byte; it never calls a model.

The delivered 1,940-file archive is `4.2-final-delivery.zip` (SHA-256
`2993ac76fe620d3aaf3df811369fdd88a4fbdd1911e0c8582318b6af99896a2b`) or
`4.2-final-delivery.tar.gz` (SHA-256
`1d985b2f5a4e86a4cf0c5e02cdab59ecfb4e6fd12e2163b926589d1307f3146d`). Both
contain the retained run, implementation and audit evidence. The ZIP is stored
outside Git; copy it intact when handing the run to another machine.

Task 4.2 supplies raw outputs, pairing, coverage and blank review exports. Human
ratings belong to 4.3, paired gains and race bootstrap to 4.4, and conclusions to
4.5. No human judgment or performance is inferred from passing synthetic tests.
Policy agreement does not establish optimal race strategy or validate upstream
strict-cutoff availability. Final inputs retain the limitations recorded by 4.1.

## Executed final run (21 October 2026)

Run `runs/4-2-final-50067b54741c-49b4aea370af` completed locally from 20:24:09 to
22:05:49 Europe/Paris in one process/session on Apple M1 (17.2 GB RAM), MPS/bf16,
with the pinned libraries. It contains 600 successful requests, exactly 200 per
version, with zero request errors or technical resumes. The cumulative generation
time was 6,068.5 seconds; wall time from preparation to sealing was 6,132.0 seconds,
including preparation and the delay before sealing. These are measurements of this
machine/run, not general speed estimates.

The initial Hub access failure (HTTP 401, before preparation or generation) was
resolved using the local folders supplied by Paul. A `s2028-e1` and B `s2027-e3`
weights exactly match the frozen SHA-256 values. They were copied to the selected
ignored checkpoint paths; B's `(1)` filename suffix was normalized only in the
copy. The original folders and freeze were preserved. No response was generated
during the earlier access failure.

The same 200 cases cover seven final races, all five exclusive families and all
three labels (29 BOX, 87 STAY OUT, 84 NO CALL). Preflight inputs use 775–883 tokens,
with no history reduction. Sealing checked every trace against its prepared input,
all hashes and the complete matrix. The review sheet contains the original 40
selected targets for all three versions, 120 rows still pending.

The [4.2 results report](final-scoring-results.md) contains the full descriptive
table, Z/D rates, family and label breakdowns, confusion counts, trade-off and
limitations. The [machine-readable evidence](final-scoring-results.json)
contains the evaluator's per-version summaries, coverage, identifiers,
timestamps, settings and hashes. It reports no paired-gain estimate or
race-level uncertainty; those belong to 4.4. The 120 human-rating rows were
rated in 4.3, and no WHY was rated in task 4.2.

Raw-output SHA-256:
`81d220b479a81a599cbf95dcbfcd66b25853b01581d25454c4f0d9767eeef012`.
`seal`, `verify` and a read-only audit of the 200 paired rows, 120 pending
ratings, exact input/trace identities and exports passed. The complete run is
ignored/local; copy the archive intact to transfer it. The teammate review on
PR #62 requested changes. Status (23 October 2026): PR #62 was merged on 22
October and issue #21 was closed the same day.
