# Corpus (task 2.2)

The dialogues for adapter A, validation and the mini-test come from the race cards of 2.1. Every answer follows the two-line CALL/WHY format of `docs/race-card-contract.md`, under policy 1.1 with per-compound tyre ages, and the manifest records that version. Cards are read only through `boxbox.data.load_cards`, so the final split stays closed.

## Commands

From the repository root:

```text
python -m scripts.build_corpus build
python -m scripts.build_corpus review
```

`build` writes `data/corpus/A_train.jsonl`, `validation.jsonl`, `mini_test.jsonl`, `manifest.json` and `review_sheet.csv` in a few seconds, then refreshes `review.json` from the rebuilt sheet. It stops if a check fails, and it gives the same files every time for the same cards and seed (2026). After editing verdicts or notes, `review` reads the filled sheet and refreshes `review.json`.

## How answers are written

The rule writes every policy answer: `format_answer(card)` from `boxbox.rules`. The other answers are fixed templates in `boxbox/corpus/templates.py`:

- A follow-up asks why (the same answer again), asks for a field of the card ("The card shows ..., and the call for this lap stays ..."), or states an explicit assumption ("What if the gap behind were X seconds?"). The assumption is answered by the rule on the card with that gap, and the answer starts with "Assuming a X-second gap behind".
- An out-of-scope request gets NO CALL and one fixed sentence per category: weather, a live or future race, betting, the championship, team radio, a car not on the card, a multi-stop plan, or an unrelated topic.
- A call question on a card under a safety car or VSC gets the rule's answer: NO CALL, because the card does not show green-flag running. These items count as out of scope, with `scope` set to `track_status`. Other out-of-scope items carry their request category in `scope`.

Questions come from 15 call phrasings with the car number and lap filled in. Cards contain car numbers only, never names, so the corpus holds no personal data. If the 1.4 rule changes, `build` gives the new corpus in seconds.

## Corpus A (400 items, train races)

A uses complete cards (a known pit loss, no UNKNOWN gap and green running), except for the 15 track status items.

| Kind | Items | Content |
|---|---:|---|
| complete | 260 | One call. Balanced over the six paths of the rule, then over SOFT, MEDIUM and HARD inside each path. |
| multi | 80 | A call, then one follow-up: 20 why, 20 field, 20 what-if, 20 out of scope. Cards chosen the same way. |
| out_of_scope | 60 | 45 out-of-scope requests on a complete card, and 15 call questions under a safety car (7) or VSC (8). |

A race and driver gives at most 2 cards to the whole of A, since neighbouring laps of one stint are nearly the same example. The cap is the reason for the selection order: the smallest pools of a path and compound pick first, so the large pools do not use up the race and driver pairs that the small ones need.

Complete items per path and compound:

| Path | Items | SOFT | MEDIUM | HARD |
|---|---:|---:|---:|---:|
| young tyres | 48 | 16 | 16 | 16 |
| gap ahead over 2 s | 47 | 16 | 16 | 15 |
| rejoin behind the car behind | 47 | 16 | 16 | 15 |
| no car behind | 49 | 17 | 16 | 16 |
| gap covers the loss on old tyres | 47 | 12 | 18 | 17 |
| gap ahead within 2 s | 22 | 5 | 4 | 13 |

The last path is rare in the races, so it gives every card it can and the other paths fill the rest. Its 4 MEDIUM items are all the MEDIUM cards it has in the train races. Every other compound holds at least a fifth of its path's items. Over the 400 items the calls are 190 STAY OUT, 150 BOX and 60 NO CALL, from 42 races and 288 race-driver pairs, with 296 distinct first questions.

60 complete items carry `swap_field`, 10 per path. It names a field the rule needs on that path. Task 3.1 removes it to build the matched B item, whose rule answer is NO CALL.

## Validation (100 items, 7 races) and mini-test (40 items, 5 races)

| Kind | Validation | Mini-test |
|---|---:|---:|
| complete | 30 | 12 |
| missing (a required field is unknown) | 20 | 8 |
| decidable (a field is unknown but the rule still decides) | 15 | 6 |
| multi | 20 | 8 |
| out_of_scope | 15 | 6 |

Out of scope includes 4 track status items in validation and 2 in the mini-test.

About half of the missing and decidable items are real cards whose field OpenF1 could not give: 10 and 8 in validation, 4 and 3 in the mini-test. The others are complete cards with one field made unknown, recorded as `removed_field`.

## Checks

Every `build` checks the following:

- each answer has two lines, a valid CALL and a one-sentence WHY
- the first answer is the rule's answer on the card
- A uses only train races and complete cards, except for its track status items, and each set uses only its own races
- the counts per kind match, no card is used twice, and A has at most 2 cards per race and driver
- a missing item gets NO CALL and a decidable item keeps a call
- the 60 swap fields each turn the card into NO CALL
- each set has its number of track status items, and each one has a card under a safety car or VSC

`tests/test_corpus.py` repeats these checks on synthetic cards. It also checks the compound balance, that `build` never opens the final split, that two card builds with the same cards give the same manifest, that the loader refuses a changed file, and that review verdicts survive a rebuild only for unchanged items.

## Reading the corpus

Tasks 2.5 and 2.6 read a set with `load_corpus("A_train")`, `load_corpus("validation")` or `load_corpus("mini_test")` from `boxbox.corpus`. It raises an error when the file's SHA-256 differs from `manifest.json`, or when the manifest's policy version is not the rule's current `POLICY_VERSION`. A corpus edited by hand or built on an older rule then stops the run before training.

The manifest also records the seed, the hash of the split document and `cards_sha256`. That last hash covers the card files of the train, validation and mini-test races, and not the time the cards were built, so rebuilding identical cards keeps the manifest identical.

## Corpus review

The review checks every row of `review_sheet.csv` against its full source card and conversation, matched by ID and digest. It covers the call, English explanation, numbers, units, car references, follow-ups and scope limits. A correct example agrees with the documented policy; it need not be the best real-world strategy. Historical source-data accuracy is outside this corpus review.

Automatic review gives clear cases `ok` with an `automatic:` note explaining the decision. Ambiguous cases keep an empty verdict until Maxime confirms or rejects them in batches of up to five. His decisions receive `ok` or `fix` with a `confirmed:` note, and a group decision names the shared concern.

On 18 October Maxime read all 540 rows of the first build on policy 1.1. 504 rows carried the note of the automatic pre-check, 36 carried his group decision on late-race BOX calls, and none needed a fix. With a single reader there is no agreement measure.

The rebuild that balanced compounds and added the track status items invalidated 539 of the 540 row verdicts. A fresh review on 18 October checked all 648 answers against their cards and the policy, including the 21 SC/VSC cases and 37 late-race BOX cases. The 539 changed rows received automatic acceptance; V-055 retained its unchanged automatic verdict and note. The current summary has 540 automatic acceptances, no new human confirmations, no pending rows and no fixes. Maxime's complete manual read applies to the first build only.

`review` summarises completed decisions as `automatic`, `confirmed` or `unattributed` (an earlier verdict without either prefix). `pending` counts empty verdicts, even when a note is present. `read` counts completed decisions, not human reading; the first build's human review is recorded here and on #7. `ok` counts accepted rows and `fix` lists unresolved defects. The review is complete only when no row is pending and no fix remains.

The late-race rows are BOX calls with 1 or 2 laps left, 37 in the current build. They stay in the corpus. The policy has no rule on laps remaining, and a late stop can make sense: very worn tyres risk a puncture and lose pace, and until the end of 2024 a fresh set could also chase the fastest-lap point. Their WHY gives only the policy grounds: tyre age, relevant gaps and pit loss when required. Maxime's earlier acceptance of this limitation guides the fresh automatic review; it does not count as individual human confirmation of the rebuilt rows.

A recurring defect is corrected in the templates or selection, never in one generated dialogue by hand. After a rebuild, verdicts and notes survive only when the card and messages have the same digest. Changed examples are reviewed again. The final test stays closed.

## Licence

The corpus is derived from OpenF1 data. `data/corpus/NOTICE` puts it under CC BY-NC-SA 4.0 with attribution, not under the repository's Apache 2.0 licence.
