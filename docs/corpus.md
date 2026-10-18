# Corpus (task 2.2)

The dialogues for adapter A, validation and the mini-test come from the race cards of 2.1. Every answer follows the two-line CALL/WHY format of `docs/race-card-contract.md`, under policy 1.1 with per-compound tyre ages, and the manifest records that version. Cards are read only through `boxbox.data.load_cards`, so the final split stays closed.

## Commands

From the repository root:

```text
python -m scripts.build_corpus build
python -m scripts.build_corpus review
```

`build` writes `data/corpus/A_train.jsonl`, `validation.jsonl`, `mini_test.jsonl`, `manifest.json` and `review_sheet.csv` in about 2 seconds. It stops if a check fails, and it gives the same files every time for the same cards and seed (2026). `review` reads the filled sheet and writes `review.json`.

## How answers are written

The rule writes every policy answer: `format_answer(card)` from `boxbox.rules`. The other answers are fixed templates in `boxbox/corpus/templates.py`:

- A follow-up asks why (the same answer again), asks for a field of the card ("The card shows ..., and the call for this lap stays ..."), or states an explicit assumption ("What if the gap behind were X seconds?"). The assumption is answered by the rule on the card with that gap, and the answer starts with "Assuming a X-second gap behind".
- An out-of-scope request gets NO CALL and one fixed sentence per category: weather, a live or future race, betting, the championship, team radio, a car not on the card, a multi-stop plan, or an unrelated topic.

Questions come from 15 call phrasings with the car number and lap filled in. Cards contain car numbers only, never names, so the corpus holds no personal data. If the 1.4 rule changes, `build` gives the new corpus in seconds.

## Corpus A (400 items, train races)

A uses only complete cards: a known pit loss, no UNKNOWN gap and green running.

| Kind | Items | Content |
|---|---:|---|
| complete | 260 | One call. Balanced over the six paths of the rule, at most 2 cards per race and driver. |
| multi | 80 | A call, then one follow-up: 20 why, 20 field, 20 what-if, 20 out of scope. |
| out_of_scope | 60 | An out-of-scope request on a valid card. |

The complete items per path are: young tyres 54, rejoin behind the car behind 52, gap ahead over 2 s 54, no car behind 47, gap covers the loss on old tyres 42, gap ahead within 2 s 11. The last path is rare in the races, so it gives every card it has and the other paths fill the rest. Over the 400 items the calls are 206 STAY OUT, 134 BOX and 60 NO CALL, from 41 races and 288 race-driver pairs, with 295 distinct first questions. The tyres are HARD on 223 items, MEDIUM on 127 and SOFT on 50, since the selection balances rule paths and not compounds.

60 complete items carry `swap_field`, 10 per path. It names a field the rule needs on that path. Task 3.1 removes it to build the matched B item, whose rule answer is NO CALL.

## Validation (100 items, 7 races) and mini-test (40 items, 5 races)

| Kind | Validation | Mini-test |
|---|---:|---:|
| complete | 30 | 12 |
| missing (a required field is unknown) | 20 | 8 |
| decidable (a field is unknown but the rule still decides) | 15 | 6 |
| multi | 20 | 8 |
| out_of_scope | 15 | 6 |

About half of the missing and decidable items are real cards whose field OpenF1 could not give: 10 and 8 in validation, 4 and 3 in the mini-test. The others are complete cards with one field made unknown, recorded as `removed_field`.

## Checks

Every `build` checks the following:

- each answer has two lines, a valid CALL and a one-sentence WHY
- the first answer is the rule's answer on the card
- A uses only complete cards from train races, and each set only its own races
- the counts per kind match, no card is used twice, and A has at most 2 cards per race and driver
- a missing item gets NO CALL and a decidable item keeps a call
- the 60 swap fields each turn the card into NO CALL

`tests/test_corpus.py` repeats these checks on synthetic cards. It also checks that `build` never opens the final split, and that review verdicts survive a rebuild only for unchanged items.

## Corpus review

The review checks every row of `review_sheet.csv` against its full source card and conversation, matched by ID and digest. It covers the call, English explanation, numbers, units, car references, follow-ups and scope limits. A correct example agrees with the documented policy; it need not be the best real-world strategy. Historical source-data accuracy is outside this corpus review.

An automatic pre-check gives clear cases `ok` with an `automatic:` note explaining the decision. Ambiguous cases keep an empty verdict until Maxime confirms or rejects them in batches of up to five. His decisions receive `ok` or `fix` with a `confirmed:` note, and a group decision names the shared concern.

On 18 October Maxime read all 540 rows. 504 rows carry the note of the automatic pre-check, 36 carry his group decision on late-race BOX calls, and none needed a fix. With a single reader there is no agreement measure.

`review` summarises completed decisions as `automatic`, `confirmed` or `unattributed` (an earlier verdict without either prefix). `pending` counts empty verdicts, even when a note is present. `read` counts completed decisions; the human read of every row is recorded here and on #7. `ok` counts accepted rows and `fix` lists unresolved defects. The review is complete only when no row is pending and no fix remains.

The 36 late-race rows are BOX calls with 1 or 2 laps left. They stay in the corpus. The policy has no rule on laps remaining, and a late stop can make sense: very worn tyres risk a puncture and lose pace, and until the end of 2024 a fresh set could also chase the fastest-lap point. Their WHY still gives only the rule's reason, the gap behind against the pit loss.

A recurring defect is corrected in the templates or selection, never in one generated dialogue by hand. After a rebuild, verdicts and notes survive only when the card and messages have the same digest. Changed examples are reviewed again. The final test stays closed.

## Licence

The corpus is derived from OpenF1 data. `data/corpus/NOTICE` puts it under CC BY-NC-SA 4.0 with attribution, not under the repository's Apache 2.0 licence.
