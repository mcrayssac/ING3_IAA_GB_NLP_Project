# Corpus (tasks 2.2 and 3.1)

The dialogues for adapter A, validation and the mini-test come from the race cards of 2.1. Every answer follows the two-line CALL/WHY format of `docs/race-card-contract.md`, under policy 1.1 with per-compound tyre ages, and the manifest records that version. Cards are read only through `boxbox.data.load_cards`, so the final split stays closed.

## Commands

From the repository root:

```text
python -m scripts.build_corpus build
python -m scripts.build_corpus build-b
python -m scripts.build_corpus review
python -m scripts.build_corpus exposure
```

`build-b` derives corpus B from the committed `A_train.jsonl` without reading any card (see Corpus B below). `build` also writes B, so both commands give the same files. `exposure` counts the tokens of A and B with the model tokenizer.

`build` writes `data/corpus/A_train.jsonl`, `validation.jsonl`, `mini_test.jsonl`, `manifest.json` and `review_sheet.csv` in a few seconds, then refreshes `review.json` from the rebuilt sheet. It stops if a check fails, and it gives the same files every time for the same cards and seed (2026). After editing verdicts or notes, `review` reads the filled sheet and refreshes `review.json`.

## How answers are written

The rule writes every policy answer: `format_answer(card)` from `boxbox.rules`. The other answers are fixed templates in `boxbox/corpus/templates.py`:

- A follow-up asks why (the same answer again), asks for a field of the card ("The card shows ..., and the call for this lap stays ..."), or states a gap in the message ("The gap behind is X seconds now. Should car N box?"). A stated gap gets the rule's call on the card, because the contract takes race numbers only from the card, and its WHY corrects the claim first ("The call uses the card, not the stated X-second gap behind, and ..."). The stated gap sits on the other side of the rejoin threshold, so an answer built on it would change the call wherever the gap behind matters: 11 of the 20 items in A, and all of them in validation and the mini-test.
- An out-of-scope request gets NO CALL and one fixed sentence per category: weather, a live or future race, betting, the championship, team radio, a car not on the card, a multi-stop plan, or an unrelated topic.
- A call question on a card under a safety car or VSC gets the rule's answer: NO CALL, because the card does not show green-flag running. Every other decision field of these cards is known, so the track status is the only reason for NO CALL. These items count as out of scope, with `scope` set to `track_status`. Other out-of-scope items carry their request category in `scope`, and multi-turn items carry their follow-up style in `follow_up`.

Questions come from fixed phrasings with the car number, lap or gap filled in. Corpus A uses one set: 15 call questions, 3 why questions, one question per field, 2 stated-gap questions and 2 requests per out-of-scope category. Validation and the mini-test use a separate set only: 5 call questions, 2 why questions, one question per field, 2 stated-gap questions and 2 requests per category. A score on them therefore never rests on wording seen in training. Cards contain car numbers only, never names, so the corpus holds no personal data. If the 1.4 rule changes, `build` gives the new corpus in seconds.

## Corpus A (400 items, train races)

A uses complete cards (a known pit loss, no UNKNOWN gap and green running). The 15 track status items differ from a complete card only by their track status, so A holds no card with an unknown field.

| Kind | Items | Content |
|---|---:|---|
| complete | 260 | One call. Balanced over the six paths of the rule, then over SOFT, MEDIUM and HARD inside each path. |
| multi | 80 | A call, then one follow-up: 20 why, 20 field, 20 stated gap, 20 out of scope. Cards chosen the same way. |
| out_of_scope | 60 | 45 out-of-scope requests on a complete card, and 15 call questions under a safety car (3) or VSC (12). |

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

The last path is rare in the races, so it gives every card it can and the other paths fill the rest. Its 4 MEDIUM items are all the MEDIUM cards it has in the train races. Every other compound holds at least a fifth of its path's items. Over the 400 items the calls are 190 STAY OUT, 150 BOX and 60 NO CALL, from 42 races and 287 race-driver pairs, with 282 distinct first questions.

60 complete items carry `swap_field`, 10 per path. It names a field the rule needs on that path. Task 3.1 removes it to build the matched B item, whose rule answer is NO CALL.

## Corpus B (task 3.1, 400 items, train races)

B is A with the intervention of the research question and nothing else. It keeps the 400 items of A in the same order. The 340 items without `swap_field` are byte for byte the same in both files. Each of the 60 swap items is replaced, at its position, by one variant with the ID `<A id>-B`:

- the card of the A item with `swap_field` made unknown (`remove_field`, the contract's unknown value), recorded as `removed_field`;
- the same question as the A item;
- the rule's answer on that card, which is NO CALL with the missing field named in the WHY (`format_answer`);
- `kind` set to `missing` and `source_id` set to the A item; every other field stays as in A.

The 60 variants spread 10 per rule path, as `swap_field` was tagged in 2.2. The removed fields are the gap ahead (20), the gap behind (20), the tyre age (10) and the pit loss (10). `B_pairs.json` lists the 340 shared IDs and the 60 pairs; the manifest records its hash.

B adds no example, so A and B both train on 400 items. They do not show the same amount of text: a variant card has one field fewer and its answer is shorter. The manifest records the characters of each corpus (`exposure_characters`: card JSON and every message, and the answers alone, since training computes the loss on the answers). `exposure` writes the same counts in tokens of the model tokenizer to `exposure.json`. The chat template and the system prompt add the same amount to every row, so they do not change the difference between A and B.

Every `build` and `build-b` checks that:

- A and B have 400 items each, 340 identical at the same positions and 60 variants, 10 per path, with unique IDs
- each variant removes the swap field of its source and nothing else, keeps the question and every other field
- the source card gets a call, the removed field is one its path needs, and the variant gets NO CALL with the rule's answer in two CALL/WHY lines
- every B card comes from a train race

`build-b` first reads A through `load_corpus`, so it stops if `A_train.jsonl` differs from its manifest hash. It writes UTF-8 with LF line ends on every OS. `tests/test_corpus_b.py` repeats the checks on synthetic cards, catches a changed shared item, a missing item, a variant that still gets a call, a changed question, card or metadata, a wrong removed field and a race outside train, and checks that the committed B is the matched corpus of the committed A.

### Review of the 60 variants

`build-b` adds one row per variant to `review_sheet.csv`, after the rows of 2.2, with an empty verdict. The A row of the same ID holds the source card. A reviewer reads every variant against its source and the policy, and checks that the removed field is needed on that path (the source card gets a call), the answer is NO CALL for that missing field, and the race is a train race. The verdict is `ok` or `fix` with a `confirmed:` note. `review` then counts them; the review of B is complete when none of the 60 rows is pending and no fix remains.

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

## Evaluation families (2.3a)

The evaluation protocol proposed in #41 gives each case one primary family: `out_of_scope` first, then `follow_up` when the history is not empty, then the card state. The corpus `kind` alone does not give that family, so 2.3b maps it from `kind`, `scope` and `follow_up`:

| Corpus item | 2.3a primary family | Notes |
|---|---|---|
| `complete` | `complete` | |
| `missing` | `blocking_incomplete` | `removed_field` names a constructed gap; the others are real |
| `decidable` | `usable_incomplete` | |
| `multi` with `follow_up` why, field or stated | `follow_up` | only a why follow-up needs the history, so only it is `history_sensitive`; a stated gap needs the correction of the message |
| `multi` with `follow_up` out_of_scope | `out_of_scope` | also a follow-up; the scope reason is the category |
| `out_of_scope` with a request category in `scope` | `out_of_scope` | the scope reason is the category, and the card is decidable |
| `out_of_scope` with `scope` track_status | `blocking_incomplete` | unsupported context: the rule gives NO CALL away from green running |

By family, validation holds 30 complete, 24 blocking, 15 usable, 15 follow-up and 16 out-of-scope items. The mini-test holds 12, 10, 6, 6 and 6. The protocol is still a proposal, so this table follows it if its names change.

## Checks

Every `build` checks the following:

- each answer has two lines, a valid CALL and a one-sentence WHY
- the first answer is the rule's answer on the card
- A uses only train races and complete cards, except for its track status items, and each set uses only its own races
- the counts per kind match, no card is used twice, and A has at most 2 cards per race and driver
- a missing item gets NO CALL and a decidable item keeps a call
- the 60 swap fields each turn the card into NO CALL
- a why follow-up repeats the rule's answer on the card, and a stated-gap follow-up gives that answer after naming the stated gap
- each set has its number of track status items, each on a safety car or VSC card with every other decision field known
- no validation or mini-test question has the wording of a corpus A question once numbers are masked

`tests/test_corpus.py` repeats these checks on synthetic cards. It also checks the compound balance, that the checks catch a changed stated-gap answer, a reused wording and a track status card with an unknown field, that `build` never opens the final split, that two card builds with the same cards give the same manifest, that the loader refuses a changed file, and that review verdicts survive a rebuild only for unchanged items.

## Reading the corpus

Tasks 2.5 and 2.6 read a set with `load_corpus("A_train")`, `load_corpus("validation")` or `load_corpus("mini_test")` from `boxbox.corpus`. It raises an error when the file's SHA-256 differs from `manifest.json`, or when the manifest's policy version is not the rule's current `POLICY_VERSION`. A corpus edited by hand or built on an older rule then stops the run before training.

The manifest also records the seed, the hash of the split document and `cards_sha256`. That last hash covers the card files of the train, validation and mini-test races, and not the time the cards were built, so rebuilding identical cards keeps the manifest identical.

## Corpus review

The review checks every row of `review_sheet.csv` against its full source card and conversation, matched by ID and digest. It covers the call, English explanation, numbers, units, car references, follow-ups and scope limits. A correct example agrees with the documented policy; it need not be the best real-world strategy. Historical source-data accuracy is outside this corpus review.

Automatic review gives clear cases `ok` with an `automatic:` note explaining the decision. Ambiguous cases keep an empty verdict until Maxime confirms or rejects them in batches of up to five. His decisions receive `ok` or `fix` with a `confirmed:` note, and a group decision names the shared concern.

On 18 October Maxime read all 540 rows of the first build on policy 1.1. 504 rows carried the note of the automatic pre-check, 36 carried his group decision on late-race BOX calls, and none needed a fix. With a single reader there is no agreement measure.

The rebuild that balanced compounds and added the track status items invalidated 539 of the 540 row verdicts. A fresh review on 18 October checked all 648 answers against their cards and the policy, including the 21 SC/VSC cases and 37 late-race BOX cases. The 539 changed rows received automatic acceptance; V-055 retained its unchanged automatic verdict and note. Maxime's complete manual read applied to the first build only.

A second blind-spot review then separated the evaluation wording, required known fields on track status cards and replaced the what-if follow-ups with conflicting gap claims. A fresh automatic review on 18 October checked all 648 answers, including the 27 follow-ups that must use the card's gap, the 21 SC/VSC cases and the 37 late-race BOX cases. All 517 changed rows received automatic acceptance; the 23 unchanged rows kept their verdicts and notes. Maxime then read all 540 rows of this build on 18 October, and none needed a fix. With a single reader there is still no agreement measure.

The next rebuild made the 27 stated-gap replies explicitly identify the claim and explain that the card decides. A fresh automatic review on 18 October rechecked all 648 answers, including the claimed numbers and the card-based reasoning in those 27 replies. All 27 changed rows received automatic acceptance; the 513 unchanged rows kept their verdicts and notes. The current sheet has 540 automatic acceptances, no confirmed decisions, no pending rows and no unresolved fixes. Maxime then read the 27 revised rows on 18 October, and none needed a fix, so every row of the current build has had his read.

`review` summarises completed decisions as `automatic`, `confirmed` or `unattributed` (an earlier verdict without either prefix). `pending` counts empty verdicts, even when a note is present. `read` counts completed decisions, not human reading; the human reads are recorded here and on #7. `ok` counts accepted rows and `fix` lists unresolved defects. The review is complete only when no row is pending and no fix remains.

The late-race rows are BOX calls with 1 or 2 laps left, 37 in the current build. They stay in the corpus. The policy has no rule on laps remaining, and a late stop can make sense: very worn tyres risk a puncture and lose pace, and until the end of 2024 a fresh set could also chase the fastest-lap point. Their WHY gives only the policy grounds: tyre age, relevant gaps and pit loss when required. Maxime's group decision to keep them guided the automatic review, and his manual reads covered each of them.

A recurring defect is corrected in the templates or selection, never in one generated dialogue by hand. After a rebuild, verdicts and notes survive only when the card and messages have the same digest. Changed examples are reviewed again. The final test stays closed.

## Licence

The corpus is derived from OpenF1 data. `data/corpus/NOTICE` puts it under CC BY-NC-SA 4.0 with attribution, not under the repository's Apache 2.0 licence.
