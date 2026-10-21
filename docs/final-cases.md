# Final cases (task 4.1)

The final cases come from the 7 reserved final races of `data/splits.json`, and are built only under the freeze of 3.5. No model is loaded and no answer is generated here; scoring is 4.2.

## Commands

From the repository root, on `main` with `configs/freeze.json`:

```text
python -m scripts.final_cases cards    # rebuild the final races' cards from OpenF1
python -m scripts.final_cases build    # dialogues, cases and the 40 review targets
```

Both commands first run the freeze check of 3.5 and stop on any difference. They open the final split for themselves only (`final_test_open` stays false in every config file). `cards` writes `data/cards/<race>.jsonl` and `data/cards/final-manifest.json`; the cards are not committed, like the other splits'. `build` writes `data/final/` once and refuses to rebuild it.

## What `build` makes

| File | Content |
|---|---|
| `final.jsonl` | 200 dialogues, made by the corpus code of 2.2 with the held-out wordings of validation and the mini-test |
| `cases.jsonl` | one evaluation case per dialogue, its last assistant turn the target, with provenance, reference and input hash |
| `review-selection.json` | the 40 human-review targets of protocol section 8, chosen from case metadata before any answer, for every retained version |
| `manifest.json` | freeze hash and commit, split document, card file hashes, file hashes, coverage and review-target counts |

The 200 dialogues are twice the validation set: 60 complete calls, 40 blocking (20 real incomplete cards, 20 with a required field removed), 30 usable incomplete (15 real, 15 with an ignored field removed), 40 with a follow-up and 30 out of scope, 8 of them safety-car or VSC calls.

Protocol section 8 fills 8 follow-up slots with history-sensitive targets: 2 on blocking cards, 2 on usable incomplete cards and 4 on complete cards. The 2.2 generator only asks follow-ups on complete cards, so the final set adds 16 of its 40 follow-ups as a "why?" on an incomplete card: 8 with a required field removed (the rule answers NO CALL) and 8 with an ignored field removed (the call stays). Both answers are the rule's answer on the changed card, as for every "why" follow-up. They are built last, and take a card only from a race and driver still under the cap of 6 cards. This was decided before building the final set, from the protocol only. Validation and the mini-test are unchanged: the addition is used for the final split only.

## Checks

`build` stops, and writes nothing in `data/final/`, when:

- the freeze check fails;
- a dialogue fails the checks of validation and the mini-test: categories, at most 6 cards per race and driver, the rule's answers, one sentence per WHY, safety-car items on neutral cards;
- the incomplete "why" follow-ups are not 8 blocking and 8 usable;
- a question has the wording of a corpus A question, numbers aside;
- a card comes from a race of another split;
- the cases fail the evaluator's validation.

If the 40 targets cannot be selected, it writes the diagnostics and coverage to `data/final-sampling-failure-<time>.json`, one file per attempt, and stops. Section 8 forbids moving quotas, relaxing caps or replacing targets: the team decides, before any generation.

If the final races do not have enough cards for 200 dialogues, `build` stops with the number it found. A smaller set needs a recorded team decision, with at least 20 unseen queries and every category kept.

## Limits

- The questions use the held-out wordings of 2.2, which validation and the mini-test use too. The cards and races are new; the wordings are not new to prompt and checkpoint selection, which saw validation. Only wordings of corpus A are refused.
- The dialogues' references are the rule's answers and the corpus templates, checked automatically as in 2.2. They are not read by hand before scoring.
- The final races keep the data limits of 2.1: strict-cutoff availability of the gap behind, actual race distance and the slick-tyre proxy for a dry track.
