---
base_model: HuggingFaceTB/SmolLM3-3B
library_name: peft
license: cc-by-nc-sa-4.0
tags:
- lora
- peft
---

# BoxBox adapter A

LoRA adapters on SmolLM3-3B (revision `a07cc9a04f16550a088caea529712d1d335b0ac1`) for BoxBox, a student pit-call assistant built for the CY Tech NLP course. The model reads one race card in the system turn and answers a pit question with a `CALL:` line and a `WHY:` line.

| Folder | Seed | Epoch | Updates | Role |
|---|---:|---:|---:|---|
| `s2028-e1` | 2028 | 1 | 120 | adapter A |
| `s2026-e3` | 2026 | 3 | 360 | selected checkpoint of seed 2026 |
| `s2027-e3` | 2027 | 3 | 360 | selected checkpoint of seed 2027 |

Each folder holds `adapter_config.json` and `adapter_model.safetensors`. `summary.json` gives the seed means, the intervals, the ranking that made seed 2028 adapter A, and A minus the baseline for each seed.

## Loading

```python
from pathlib import Path
from huggingface_hub import snapshot_download

local = snapshot_download("ING3NLPProject/boxbox-adapter-a", revision=REVISION, allow_patterns="s2028-e1/*")
adapter_dir = Path(local) / "s2028-e1"
```

`REVISION` is the `hub.revision` recorded in `configs/adapter-a-selection.json` of the project repository. In the project, `selected_adapter()` from `boxbox.model` finds the checkpoint, checks its hash and returns the config with seed 2028. `adapter_dir` then goes to `load_conversation_engine` with the `p01-policy-first` prompt. The answers depend on that exact prompt and chat template settings.

## Training

- 480 rows from corpus A, one per assistant turn, with the inference prompt
- LoRA rank 16, alpha 32, dropout 0, on all linear layers, without quantization
- AdamW, learning rate 2e-4 with linear decay, effective batch 4, 3 epochs, loss on the answer tokens only
- bf16 on an Apple M3 Max

## Validation

On the 100 validation targets, the mean over the three selected checkpoints is:
- strict format 1.000
- CALL agreement 0.740, 95% interval over seeds 0.650 to 0.830
- unjustified decisions on the 40 NO CALL targets 0.567
- macro-label agreement 0.768 and macro-family agreement 0.780

## Limits

Adapter A still makes a call on 19 of the 20 validation targets with a missing field, because corpus A has no such example. Some stated-gap answers are longer than the 64 new tokens used at inference, so a few answers stop mid-sentence. It applies one fixed pit rule to the card it is given. It is not a race strategy tool.

## Data

The race cards are derived from timing data published by OpenF1 (https://openf1.org), with round numbers and event names from Jolpica-F1. They are under CC BY-NC-SA 4.0, as OpenF1's licence requires, and so are these adapters. The timing data belongs to the Formula 1 companies. BoxBox is an unofficial, non-commercial student project with no link to them.
