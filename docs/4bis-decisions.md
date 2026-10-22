# Experimental milestone (4 bis) decisions

The Experimental milestone (4 bis) widens the race data and makes it match what happened on track. It sits outside the freeze of the A/B study. It was built on branch `main-experimental`, cut from `main` after task 4.4. The work was done on branch `4bis-experimental` with the task branches `4bis.1-data-v2`, `4bis.2-policy-2`, `4bis.3-replay-spike` and `4bis.3-replay-v2`, then merged into `main-experimental` and from there into `main` ([PR #69](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/69)). The results of the study do not depend on it, and the 1.0 cards of the study rebuild exactly only from commit `631b783`. Each decision below says what we chose, why, and how we check it. No trained model has read cards 2.0 or policy 2.0. The adapters A and B, and every result of the study, were trained and scored on 1.0 cards with policy 1.1, so the Replay tab shows the rule engine's calls and has no model chat. Training on 2.0 cards is future work.

## D1. The 2026 season is included

We add the 17 races run by 22 October 2026, from Melbourne to Singapore. Bahrain and Jeddah were cancelled: OpenF1 flags them `is_cancelled`, and Jolpica drops them and renumbers the rounds, so race ids and session keys are stored in the split file. The snapshot date is a constant. Later races go into a new split file.

The 70 races of 2023 to 2025 keep their split. The 2026 races are split in time order: the first 11 in `train`, the next 3 in `validation`, the last 3 (Baku, Kuala Lumpur, Singapore) in a closed `test_2026`. A time split matches how the product is used: learn from past races, then face the next ones. `test_2026` is the only test set no earlier version has seen.

Check: `data/splits-v2.json` was frozen on 22 October 2026 with 87 races: 60 in `train`, 10 in `validation`, 7 in `mini_test`, 7 in `final` and 3 in `test_2026`. The 70 older races keep their v1 split and session keys, and every race carries its `circuit_key`. All 87 races were downloaded without a failure. A network cut during the first download left nothing in the cache, because a failed or empty response is never cached.

## D2. Sprints stay out

A sprint has no mandatory stop, so it has almost no BOX situations to learn from.

## D3. Track status follows race-control timestamps

Neutralisation windows are built from race-control timestamps instead of lap numbers. A safety car deployed during a virtual safety car closes the VSC, a VSC that starts and ends in one lap is kept, and laps started after the chequered flag are dropped. Each row of the per-lap table gets the status at the moment that driver crosses the line, plus a flag for any neutralisation during the lap. A clean lap must be green and dry with no neutralisation inside it.

The old status kept a VSC open to the flag in three train races (2023-10, 2024-05, 2024-23) and missed seven one-lap VSCs. It also read the status at the leader's lap, so a car one lap behind could be given the wrong state.

A red flag lasts until the race resumes ("SESSION STARTED"): in 2026 its "TRACK CLEAR" comes two or three minutes after the flag, long before the restart. A restart behind the safety car has no deployment message. It runs from "SESSION STARTED" to the next line crossing after the safety car enters the pits. Messages after the chequered flag are ignored, so a race that ends under a safety car keeps that status on its last crossings. OpenF1 often keeps the leader's lap after the flag, so the last lap started before the leader's crossing at the flag sets the race distance. Pit-loss stops and reference laps now count only once the leader has crossed the line after them, because every card of that lap is built after that moment.

Check: rebuilding the 70 races of 2023 to 2025 from the cache gives 65,674 cards instead of 65,904. Sixteen races get their real distance back, for example 50 laps instead of 51 for Saudi Arabia 2023, so their last-lap cards go. In `train`, 875 NO CALL cards become STAY OUT and 17 become BOX. 436 STAY OUT cards become NO CALL, mostly because a pit-loss estimate now waits for the out-laps to end (448 of the 604 such cards across all splits) and the rest because a one-lap VSC or a SC that starts before the driver crosses is now seen. `train` moves from 39,263 / 6,128 / 627 (STAY OUT / NO CALL / BOX) to 39,548 / 5,644 / 629. A three-lens review checked every window of the 70 races: no VSC longer than 8 minutes, and every ENDING or IN THIS LAP reaches its "TRACK CLEAR". It found no SC longer than 25 minutes and no overlap, except at Great Britain 2025 (see Known limits). 2026 races write a red flag as "RED FLAG - RACE SUSPENDED" without a flag field, which the parser accepts. They also write the virtual safety car as "VSC DEPLOYED" and "VSC ENDING", and until the fix of 22 October 2026 the parser missed that wording and read 22 VSCs in 12 races of 2026 as green.

## D4. Calls under SC and VSC

Under a VSC the gaps hold, so the opportunity opens at the young tyre limit and the usual rejoin test applies with the VSC pit loss. Under a safety car the field bunches up. The card then counts the cars behind within the pit loss plus the 2-second margin, and the call is BOX only when that window is empty. A closed pit entry is shown but drives no rule, since it happened only four times in 70 races.

The first cards showed what the rule missed: in a dry race every car must use two dry compounds, so a car that has not made that stop will make it anyway, and a safety car makes it cheaper. Under a SC or VSC on a dry track, a car with the mandatory stop still to make gets BOX. Saudi Arabia 2024, where almost the whole field stopped under the lap-7 safety car, is the case that showed it.

Check: a card is taken when the driver crosses the line, so a safety car that comes out during the lap is not on it. 32 of the 54 stops made under a safety car in the evaluation races had a GREEN card. A live view needs a card refreshed when race control announces the neutralisation.

## D5. Pit loss per condition

A stop costs its in-lap plus out-lap, minus the median in-lap plus out-lap of the cars that did not stop on those laps, minus any penalty seconds served at the stop. This works for green, SC, VSC and wet stops alike. It needs at least three cars that did not stop: at Monaco 2026 one car still running made six safety-car stops cost 42 to 54 s. A stop is known only once its out-lap and those comparison laps have ended. The race estimate is the median of the last five stops of the same condition completed before the card's time, with at least three stops.

When the race has too few stops, the estimate falls back in this order:

1. a condition-to-green ratio learned on train races, times the race's green estimate;
2. a circuit prior from earlier train races, keyed by `circuit_key`, since event names change (the "Spanish Grand Prix" is Barcelona until 2025 and Madrid in 2026);
3. a published reference for circuits with no history (Madring, Kuala Lumpur), with its source, or the train median.

The card records the condition and the source of its pit loss.

Check: across the 60 train races, the median green pit loss is 22.0 s. The SC loss is 0.70 times the green one (18 races), the VSC loss 0.80 times (14 races) and the wet loss 1.36 times (3 races). The SC ratio is above the half that strategists usually quote: under a safety car the cars far back close up while the leaders slow down, so a stop compared with the field on the same laps costs between 10 and 41 s at Silverstone 2023. On the 90,868 cards, the pit loss comes from the race itself on 66%, from the race scaled to the condition on 1.9%, from the circuit on 23%, from the published reference on 1.1% and from the overall train median on 8%. 389 cards have none. The two references are Madring at 24.0 s (Pirelli's chief engineer, quoted by The Race on 12 September 2026) and Kuala Lumpur at 22.5 s (Pirelli estimate, AutoHebdo, 4 October 2026).

## D6. Wet running is included

The track is WET when rain was read in the last 10 minutes, or when the field's green laps run at 110% or more of the best dry pace so far, the point where slicks usually start to beat intermediates. When the lap times give no reference, as early in a race that starts wet, the track is WET when half the field is on wet tyres. One car on intermediates never sets it. A first version also used the share of wet tyres on a drying track, which kept the track wet until most cars were back on slicks, after the moment that pays. Slicks on a wet track, or wet tyres on a dry track, open a stop. Only eight races had wet running, so these settings are hand-made and reported race by race.

Check: 6,098 of the 90,868 cards are WET. The five wet races that gave no 1.0 card now have cards.

## D7. Tyre degradation per circuit

Degradation is estimated with lap fixed effects, which absorb fuel burn, and stint fixed effects, on clean dry laps. A race's own value is used once its standard error is below 0.03 s per lap, around lap 21 to 23. Before that, the card uses the circuit's value from earlier train races, then the compound's overall value. A missing degradation value never gives NO CALL, so the model cannot learn that early laps mean no call. Warm-up is not modelled: the out-lap is already in the pit loss, and laps 2 and 3 of a stint are not slower. Qatar 2023 is left out of the thresholds because of its 18-lap tyre limit, but it is still in the priors file (see Known limits).

The tyre rule becomes a time rule: box when the time lost per lap against a new set reaches a limit, taken from the cards of real green stops in train races. The limits differ by compound: a stop opens from 0.34, 0.63 and 0.92 s per lap and always opens from 0.62, 1.08 and 1.38 s per lap for SOFT, MEDIUM and HARD. Teams stop a soft set at a lower time loss than a hard one, so a single limit would delay soft stops and bring hard ones forward. A negative slope is never used: it means fresh sets were still coming in, as at Madring 2026, where the race's own fit gave -0.026 s per lap on HARD.

Check: the train medians are 0.058, 0.055 and 0.039 s per lap for SOFT, MEDIUM and HARD before 2026, and 0.045, 0.040 and 0.037 in 2026. A race's own value fits in 0.01 s.

## D8. Neighbours' tyres and the undercut

The gap ahead and the gap behind carry the neighbour's compound, tyre age and whether it is in the pit lane, read at the end of the previous lap and only for a known gap. An undercut on the car ahead opens an opportunity when the gap is smaller than what the rival loses on its old tyres over one lap. Without a degradation value the old 2.0-second window applies. The car behind on fresher tyres is shown but drives no rule: in 98.5% of cases it has already stopped.

## D9. Track conditions

The card carries the last weather reading taken before its time: air and track temperature, humidity, wind and rainfall. Rainfall feeds D6. The other readings are shown only, until we can measure an effect.

## D10. Card time and versions

Each card has an `as_of` time, the moment the driver crosses the line at the end of the previous lap. Weather, stops, status and penalties are read before that moment. The gap behind is the exception, as on a timing screen: it is known when the car behind crosses, a few seconds later. Cards move to schema 2.0 in `data/cards-v2/`. `decide()` reads the schema version: 1.0 cards keep policy 1.1, so the current corpus, evaluation and model still work, and 2.0 cards use policy 2.0. Driver names and team colours stay outside the card, as display context, because the training dialogues never name a driver.

## D11. Live replay

The replay runs a race clock and places every car on the circle from its last line crossing and the previous lap's sector times, without reading anything timed after the clock. The pit window is drawn in yellow from the current condition's pit loss, so it moves when a safety car comes out. The call panel shows the policy 2.0 call next to the policy 1.1 call on the 1.0 card. The model's chat returns once adapters are trained on 2.0 cards.

Check: a first replay on 1.0 cards (branch `4bis.3-replay-spike`) plays Saudi Arabia 2024 at x1, x2 and x4 with 9 to 16 ms from tick to render and no skipped tick, so a server-side SVG redrawn by `gr.Timer` is enough. The final replay (branch `4bis.3-replay-v2`), merged into `4bis-experimental` and then into `main-experimental`, reads the 2.0 cards, rebuilds the 1.0 cards from the same table and shows both calls side by side. Cars wear their team colour and acronym, and "Jump to lap" moves the clock. At Saudi Arabia 2024 the window shrinks from 21.5-23.5 s under green to 15.1-17.1 s when the lap-7 safety car comes out.

Two problems showed up on screen and were fixed. Cars placed on the pace of their previous lap piled up on the line when the safety car slowed them, until their own crossing came; the freshest crossings now set a pace factor (1.31 at Saudi Arabia 2024, lap 8). The SC-to-green pit-loss ratio was taken from the few train races before each race, and early in 2024 it came out at 1.11, a SC stop dearer than a green one; it is now a model constant over all train races, like the wear limits. This change leaves the evaluation results above unchanged.

## D12. Gap cross-check

OpenF1's `intervals` endpoint checks the computed gaps on validation and test races only. It never feeds a card.

Check: on 21,864 cards with a known gap ahead, the computed gap differs from OpenF1's interval read just after the crossing by 0.07 to 0.08 s (median per split). 2.3% to 4.4% of the cards differ by more than 0.5 s, and the worst reach 47 s, around pit stops and safety-car bunching.

## Agreement with the teams

`scripts/reality_check.py` asks, for every strategy stop, whether the card at the start of the stop lap says BOX (recall), and, for every BOX card, whether the car stops within two laps (precision). Red-flag tyre changes, retirements, damage stops and penalty stops are left out. A rule that said BOX at random would reach a precision of 8.1% on the evaluation races (`validation`, `mini_test` and `final`, 668 stops), the share of laps followed by a stop within two laps. The table comes from the first run; D13 gives the adopted rule after the causality fixes of the replay review and the 2026 VSC fix (D3), on 664 stops.

| Rule | Recall | Precision | BOX share of cards |
|---|---:|---:|---:|
| Policy 1.1 on 1.0 cards | 1.3% | 7.1% | 1.3% |
| Policy 2.0 with a rejoin test on every stop | 3.0% | 6.6% | 2.6% |
| Policy 2.0 without the rejoin test | 62.1% | 14.3% | 33.2% |
| Policy 2.0, rejoin only before the upper wear limit | 53.6% | 15.5% | 26.2% |
| Age only (BOX from the 1.1 upper age) | 49.0% | 14.7% | 24.7% |

The rejoin test is what kept the policy away from the teams. It gives BOX only when the gap behind covers the whole pit loss, which mid-field cars almost never have, while teams stop anyway and accept the places. Tyre wear carries the signal, and the best per-lap rule reaches about twice the precision of chance: stop timing also depends on things a card does not hold, such as each team's plan and its rivals' moves. These numbers are exploratory: the wear limits come from the train races, and the policy variant was chosen on the evaluation races (D13), so they are a selection result and not an independent test.

## D13. Worn tyres box whatever the traffic

Policy 2.0 keeps the rejoin test only inside the wear window, where a stop needs an undercut or a neutralisation. At or above the compound's upper wear limit (or the 1.1 upper age when wear is unknown) the call is BOX whatever sits behind. This is the variant with the best precision on the evaluation races, and it is how teams behave: they stop worn tyres and accept the places.

Check: on the evaluation races the adopted policy gives a recall of 53.6% and a precision of 15.6%, against 8.0% for chance (the share of laps followed by a stop within two laps, which `scripts/reality_check.py` does not print). `test_2026` was then opened with the policy frozen. It was run a second time after the causality fixes of the replay review (stops known only once their comparison laps end, at least three cars to compare with, the red flag lasting until the restart), which moved its figures by at most 0.1 point. It was run a third time after the 2026 VSC fix (D3), again with no change to the policy. With that fix, 12 stops count as VSC stops, four stops whose out-lap ran into a VSC are left out, and recall or precision moves by up to 3.3 points per race. The figures below are from the third run:

| Race | Stops | Recall | Precision | Chance precision |
|---|---:|---:|---:|---:|
| Azerbaijan 2026 | 36 | 52.8% | 17.0% | 11.9% |
| Malaysia 2026 | 64 | 31.2% | 25.0% | 18.4% |
| Singapore 2026 | 22 | 77.3% | 16.5% | 5.6% |
| All three | 122 | 45.9% | 18.9% | 11.6% |

On the same races the age-only rule gives 51.6% and 14.8%, and policy 1.1 gives 3.4% and 5.8%. The policy holds on races no version had seen, at 1.4 to 2.9 times the precision of chance. It misses most stops at Malaysia, a race of two and three stops on very abrasive asphalt, where cars stopped before their tyres reached the limits learned elsewhere. Three races are few, so each race is reported on its own.

## Known limits at the merge

Found in the review of the merge into `main` (PR #69). The line numbers are those of commit `56ad538`. None of them touches the frozen versions, their results or the policy 1.1 calls. They are listed to be fixed later, not fixed in the merge.

- Models: the adapters A and B, and every result of the study, are trained and scored on 1.0 cards with policy 1.1. No trained model has read a 2.0 card or policy 2.0. The Replay tab shows the rule engine's calls and has no model chat. Training on 2.0 cards is future work.
- 1.0 rebuild: `rebuild_data cards` now gives 65,674 cards, not the 65,904 behind the frozen corpus, and `validation_cases` refuses them with `V-001: card differs from its recorded source/transformation`. A fresh clone cannot run the steps that compare rebuilt cards with the committed corpus. The frozen cards rebuild exactly only from commit `631b783`.
- D6, `boxbox/data/cards_v2.py:115`: `_inflation` reads only laps known at the leader's crossing, so at most one car of the cutoff lap is present and the 110% pace rule never fires. The track is then WET only from rain or from the share of wet tyres, the first-version behaviour that D6 says the pace rule replaced. The test that covers the rule passes the value by hand.
- D3, `boxbox/data/openf1.py:228`: a formation-lap message "behind the safety car" arms the rule, and the race start then opens a safety-car window that nothing closes. At Great Britain 2025 (`2025-12`, a `mini_test` race) it gives a 35.4-minute SC window that overlaps two VSC windows. This is the only window of the 87 races that is longer than 25 minutes, so the D3 review claim holds for every other race. The 2.0 cards and the replay of this race are affected.
- Replay, `boxbox/data/replay.py:207`: `pace()` has no upper bound and counts the lap that holds a red-flag stoppage as a slow lap. After a restart behind the safety car (`2023-03`) the factor reaches 8 to 23 and the circle is wrong.
- Replay, `boxbox/data/replay.py:320`: `cards_at` decides that a car has stopped at normal pace, while the circle uses the safety-car pace, so the call panel can show no card for a car the circle still draws (Saudi Arabia 2024, lap 8).
- Replay, `boxbox/app/replay.py:196`: without the OpenF1 cache and without network, picking a race gives a generic Gradio error and not a clear message.
- Policy 2.0, `boxbox/rules/policy2.py:139`: with a mandatory stop pending and the tyres outside the wear window, the BOX sentence repeats the tyre sentence and contradicts itself. Lines 60 to 62 raise `TypeError` on an unhashable compound or track status, where policy 1.1 answers NO CALL. Lines 152 and 167 read a null `mandatory_stop_pending` as false and a null penalty as zero. Line 168 rounds `loss + penalty` to 28 digits, so an exact threshold can flip.
- D7, `scripts/rebuild_data.py:234`: the priors file keeps Qatar 2023 (`2023-17`, MEDIUM 0.0108 and HARD 0.0407 s per lap). Qatar 2024 and 2025 use these values as their circuit prior until their own fit is reliable. Only the thresholds of `reality_check` leave Qatar 2023 out.
- D7, wear limits: policy 2.0 keeps its frozen limits. On the train cards rebuilt after the 2026 VSC fix, `reality_check --splits train --thresholds` prints 0.37 and 0.64 s per lap for SOFT, 0.62 and 1.07 for MEDIUM and 0.94 and 1.42 for HARD, so the command no longer gives the limits it is cited for. The policy was not retuned.
- D12 and D13: the policy variant was chosen on the evaluation races, so 53.6% and 15.6% are a selection result. Only `test_2026` was opened after the choice. The chance precision is computed outside `reality_check`, which does not print it. In `reality_check.py:110`, the blocks per condition repeat the precision and BOX share of all conditions, and only recall and the number of stops differ.
- Tests: `test_neutralised_laps_stay_out_of_the_reference_lap` (`tests/test_data.py:168`) cannot fail, and no test checks that `test_2026` is closed.
