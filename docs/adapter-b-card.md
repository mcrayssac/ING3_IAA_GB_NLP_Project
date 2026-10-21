---
base_model: HuggingFaceTB/SmolLM3-3B
library_name: peft
license: cc-by-nc-sa-4.0
tags:
- lora
- peft
---

# BoxBox adapter B

These are LoRA adapters on SmolLM3-3B (revision `a07cc9a04f16550a088caea529712d1d335b0ac1`) for BoxBox, a student pit-call assistant built for the CY Tech NLP course. The model reads one race card in the system turn and answers a pit question with a `CALL:` line and a `WHY:` line.

B is the controlled variant of adapter A (`ING3NLPProject/boxbox-adapter-a`). It is trained with the same settings and seeds. In its corpus, 60 of the 400 items are replaced by cards where a field the rule needs is unknown, with the answer NO CALL.

| Folder | Seed | Epoch | Updates | Role |
|---|---:|---:|---:|---|
| `s2027-e3` | 2027 | 3 | 360 | adapter B |
| `s2026-e2` | 2026 | 2 | 240 | selected checkpoint of seed 2026 |
| `s2028-e3` | 2028 | 3 | 360 | selected checkpoint of seed 2028 |

Each folder holds `adapter_config.json` and `adapter_model.safetensors`. `summary.json` gives the seed means and intervals, the ranking that made seed 2027 adapter B, and the comparison with A for each seed.

## Loading

```python
from pathlib import Path
from huggingface_hub import snapshot_download

local = snapshot_download("ING3NLPProject/boxbox-adapter-b", revision=REVISION, allow_patterns="s2027-e3/*")
adapter_dir = Path(local) / "s2027-e3"
```

`REVISION` is the `hub.revision` recorded in `configs/adapter-b-selection.json` of the project repository. In the project, `selected_adapter(Path("configs/adapter-b-selection.json"))` from `boxbox.model` finds the checkpoint, checks its hash, and returns the config with seed 2027 and the prompt B was trained on. The answers depend on that exact prompt and chat template settings.

## Training

- 480 rows from corpus B, one per assistant turn, with the inference prompt
- LoRA rank 16, alpha 32, dropout 0, on all linear layers, without quantization
- AdamW with a learning rate of 2e-4 and linear decay
- effective batch 4, 3 epochs, loss on the answer tokens only
- bf16 on an Apple M3 Max

## Validation

On the 100 validation targets, the mean over the three selected checkpoints is:
- strict format 1.000
- CALL agreement 0.810 (95% interval over seeds 0.720 to 0.900)
- unjustified decisions on the 40 NO CALL targets 0.017
- excessive refusals on the 60 other targets 0.244
- macro-label agreement 0.827 and macro-family agreement 0.772

Against A with the same seed:
- unjustified decisions fall by 0.550 on average (0.386 to 0.714)
- excessive refusals rise by 0.239 (0.191 to 0.287)
- CALL agreement rises by 0.070 (0.020 to 0.120)

## Limits

B refuses almost every card that has an unknown field, even when the rule does not need that field. Its training corpus has no such card, which most likely taught it that any unknown field means NO CALL. Some long answers stop at the 64 new tokens used at inference. It applies one fixed pit rule to the card it is given and is not a race strategy tool.

## Data

The race cards are derived from timing data published by OpenF1 (https://openf1.org), with round numbers and event names from Jolpica-F1. They are under CC BY-NC-SA 4.0, as OpenF1's licence requires, and so are these adapters. The timing data belongs to the Formula 1 companies. BoxBox is an unofficial, non-commercial student project with no link to them.
