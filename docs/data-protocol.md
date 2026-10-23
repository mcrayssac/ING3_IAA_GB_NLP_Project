# Data protocol (task 2.1)

The rebuild turns historical race timing into race cards in the 1.0 shape of `docs/race-card-contract.md`, and freezes the race-level splits before any dialogue is generated. The sections up to the rebuild of 18 October 2026 cover the v1 data behind the frozen study, 1.0 cards and `data/splits.json`. The card table gives the current rules and notes the earlier ones under it. The Experimental milestone added a second version, described in "Data v2 (Experimental milestone)" at the end.

## Source

OpenF1 has been the source since 18 October 2026. FastF1's live-timing files now answer 401 for historical races, while OpenF1 serves the same kind of data from the 2023 season onwards. A 1.0 card uses four OpenF1 endpoints: `laps`, `stints` (compound and `tyre_age_at_start`), `pit` and `race_control`. The 2.0 rebuild adds `weather` and `drivers` (see Data v2). Jolpica gives the official round number and event name. A race is matched to its OpenF1 Race session by date, allowing one day of difference because some races start late at night local time. Cancelled sessions are skipped, and a race without exactly one match stops the rebuild. Only the `pit` endpoint may be empty. Any other empty or failed response is a failure and is never cached.

`boxbox/data/openf1.py` turns one race into the per-lap table that every loader returns. It has one row per driver and lap, with these columns: `driver_number`, `lap`, `lap_seconds`, `end_s` (time at the line from the race start), `pit_in`, `pit_out`, `compound`, `tyre_age_end`, `status` (when the driver crosses the line), `neutralised_in_lap` (a SC, VSC or red flag during the lap), `at_line` (the crossing time as a timestamp), `pit_status` (the status when the car enters the pit lane, from the `pit` timestamp, or the line status without one) and `lane_seconds` (time in the pit lane, from the `pit` endpoint). The last four came with the Experimental milestone. 1.0 cards read only this table, and 2.0 cards also read race control and weather.

OpenF1's licence (CC BY-NC-SA 4.0) covers our non-commercial academic use. Raw responses stay in `data/cache/openf1/` and cards in `data/cards/`, and neither is committed. The repository ships the rebuild script.

## Commands

From the repository root:

```text
python -m scripts.rebuild_data splits --seasons 2023 2024 2025 --seed 2026
python -m scripts.rebuild_data card --race 2024-01 --driver 1 --lap 20
python -m scripts.rebuild_data cards
python -m pytest tests/test_data.py
```

`splits` writes `data/splits.json` once and refuses to overwrite it. `card` prints one card and its SHA-256 for the double-rebuild check. `cards` writes one JSONL file per race and `data/cards/manifest.json`. A failed request raises `DataUnavailableError`, whatever the network error. `cards` records the race under `failures`, and every command exits with code 2. Since the Experimental milestone, `cards` builds with the corrected track status and no longer gives the frozen cards (see Data v2).

## Splits

The unit is a whole race. The 70 races of 2023 to 2025 are shuffled with seed 2026 and split 70/10/10/10 into `train`, `validation`, `mini_test` and `final`, with at least 5 races per evaluation split. `data/splits.json` stores the races, their session keys, the settings, a SHA-256 of the splits and a SHA-256 of the whole file. The loader refuses overlapping splits and any hand edit, including a changed session key. The 2026 season stays out of this file, and `data/splits-v2.json` adds it (see Data v2).

Later tasks read cards only through `boxbox.data.load_cards(split, config)`. It refuses the closed splits, `final` and the `test_2026` split of the v2 file, with `FinalSplitClosedError` while `config.final_test_open` is false, so their cards stay unread until the versions are frozen.

## Card for lap L

A card is a snapshot at the start of lap L, so every value comes from laps up to L - 1, the cutoff.

The table describes the current code, which includes the track-status rewrite of the Experimental milestone (`docs/4bis-decisions.md`, D3). The frozen cards were built with the earlier rules, at commit `631b783` and before: `total_laps` was the race's last lap in OpenF1, the status was read at the end of the leader's lap L - 1, a SC or VSC ran from the lap it was deployed to the lap it came in, and pit loss and reference lap used the green stops and clean green laps completed by L - 1.

| Field | How it is computed |
|---|---|
| `race`, `lap`, `total_laps`, `driver_number` | Jolpica round and event name. `total_laps` is the last lap started before the leader takes the chequered flag, which is also the scheduled distance unless the race was shortened. OpenF1 often keeps the leader's lap after the flag (lap 51 of the 50-lap 2023 Saudi race), so that lap and every lap started after it are dropped. Without a flag message (2023-14) the session end stands in for it. |
| `track_status` | Status at the moment the driver crosses the line at the end of lap L - 1, from race-control timestamps. A SC or VSC runs from its deployment to the "TRACK CLEAR" that follows its "IN THIS LAP" or "ENDING" message. A SC deployed during a VSC ends the VSC. A red flag ends both and lasts until the race resumes ("SESSION STARTED"); in 2026 its "TRACK CLEAR" comes minutes earlier. A restart behind the SC runs from "SESSION STARTED" to the next line crossing after the SC enters the pits. Sector yellows stay GREEN, because they do not neutralise the race. Each lap also records whether any of these periods overlapped it. |
| `compound`, `tyre_age_laps` | The stint that contains lap L - 1. Age is `tyre_age_at_start` plus the laps run in the stint, so it counts earlier sessions. |
| `gap_ahead`, `gap_behind` | Time at the line at the end of lap L - 1, against the neighbours in running order, with the neighbour's `driver_number`. The leader has NONE ahead and the last runner NONE behind. A gap of at least the driver's own lap time is UNKNOWN, because the neighbour is a lap or more away. If a car timed at the end of lap L - 2 has no time at the end of lap L - 1, its place is unknown, so both gaps are UNKNOWN without a neighbour number. The gap behind is the time the car behind takes to reach the line after the car, so it is known once that car crosses, in the first seconds of lap L, as on a timing screen. |
| `pit_loss_seconds`, `pit_loss_as_of_completed_lap` | An in-lap comes from the `pit` endpoint or is the lap before an out-lap, because the `pit` endpoint is empty for 2023 rounds 1 to 6. OpenF1 stores the out-lap flag on lap L, but the car is already in the pit lane when lap L - 1 ends, so this is known at the cutoff. Median of the field's green stops, with no SC, VSC or red flag during the in-lap or the out-lap, whose out-lap ends before the leader crosses the line at the end of L - 1: in-lap + out-lap minus twice the driver's median of their last 5 clean green laps (at least 2). Values outside 5 to 60 s are dropped as data errors. Fewer than 3 stops gives null. The second field is the latest out-lap used. |
| `reference_lap_seconds` | Median of the field's clean laps that end before the leader crosses the line at the end of L - 1, null with fewer than 5. A clean lap has no pit entry or exit, no neutralisation and no wet tyre. |

Each JSONL record holds `card_id`, `split`, `card` and `provenance` (source, session key, cutoff lap, stops and laps used). The model only ever sees `card`.

## Situations without a card

These are counted under `skipped` in the manifest:

- lap 1 and the final lap
- a driver with no timing at the end of lap L - 1
- a driver who starts lap L in the pit lane
- a red flag at the cutoff
- any car on intermediate or wet tyres by the cutoff, because BoxBox covers dry races only

In-laps are kept, because the snapshot at the start of the lap is a valid moment to call a stop.

## Checks

`tests/test_data.py` runs offline on a synthetic table. It checks that:

- the card keys match the contract and the cards hold plain JSON values
- lap L and later never change the card
- every gap state is handled, including a car missing at the cutoff
- tyre age counts earlier sessions
- pit loss uses only green stops completed by the cutoff, and an in-lap is found from the out-lap when the pit data is missing
- skipped situations, race-control parsing, date matching, explicit network failures and the split rules all behave as documented
- the call counts of `final` stay out of the manifest
- every network error, an empty endpoint other than `pit`, missing race control, an unmatched race and an edited split manifest all fail explicitly
- multi-lap timing holes are counted

The `cards` command also runs `boxbox.rules.decide` on every card. It counts the cards that `decide` rejects as malformed, which must be 0. It also counts the calls per split, except for `final`, which stays closed until the final test. For each race, the manifest records the SHA-256 of every raw OpenF1 response and the timed-lap share, so a later rebuild shows whether OpenF1 revised its data. It also counts the times a car loses timing for two laps or more and then reappears. That count must be 0, because the cutoff check only sees a car missing on one lap.

## Manual checks

Two real cards were read against what happened in the race. The final split was not opened.

- Bahrain 2024, car 1, lap 17: SOFT tyres aged 19 laps, a 30.4-second gap behind and a 23.1-second pit loss give BOX. The car pitted at the end of that lap. Its lap 18 and lap 38 cards are skipped, because it starts those laps in the pit lane.
- Saudi Arabia 2024: the safety car deployed on lap 7 and came in on lap 9. The cards for laps 8 and 9 show SC and the card for lap 10 shows GREEN. Lap 8 has only 4 cards, because most cars pitted under the safety car.

The cards hold car numbers, timing and tyre data about public sporting events. They contain no personal data.

## Accuracy check

Card gaps were compared with OpenF1's official gap to the leader for car 11 right behind car 1 at Bahrain 2024. On the 38 laps where the leader does not pit, they differ by 0.07 s (median), and by 0.28 s at most. The line time is the start of the next lap. Start time plus lap duration gave the same accuracy. Gaps, pit loss and reference lap are rounded to 0.1 s to match.

## Known limits

- `total_laps` is the last lap started before the chequered flag. For a race stopped early it is the distance actually run, which is not known before the start. `decide` only checks that `lap` does not exceed it, so no call depends on it.
- `surface` is DRY because the rebuild skips every card from the first intermediate or wet tyre on. A damp track where every car stays on slicks still counts as dry.

## Deviation from the research plan

The research plan allowed a pit loss estimated from the previous season at the same circuit. The rebuild uses only stops in the same race, because the previous race at that circuit can sit in another split. Before the first three green stops of a race are completed, a card with an opportunity and a car behind therefore gets NO CALL. The first pit-loss estimate of a race comes at lap 14 (median over the non-final races). Card 2.0 falls back on priors from earlier train races instead (see Data v2).

## For the corpus (tasks 2.2 and 3.1)

A complete card has a known pit loss, no UNKNOWN gap and green running. On the cards of 18 October, `train` has 29,644 of them: 29,093 STAY OUT and 551 BOX under policy 1.1. Most BOX cards have no car behind: 385 of the 627 BOX cards in `train`, from 113 race-driver pairs. The corpus should take BOX cards with a car behind (242 in `train`) and cap the cards per race and driver, so neighbouring laps of one stint do not dominate. Real cards whose pit loss is missing are natural material for the NO CALL variants of corpus B.

## Rebuild of 18 October 2026 (frozen 1.0 cards)

This rebuild ran on `main` and gave the cards behind the frozen corpus and results.

| Split | Races | Races with cards | Cards | BOX | STAY OUT | NO CALL |
|---|---:|---:|---:|---:|---:|---:|
| train | 49 | 46 | 46,018 | 627 | 39,263 | 6,128 |
| validation | 7 | 7 | 7,155 | 53 | 6,744 | 358 |
| mini_test | 7 | 5 | 5,214 | 65 | 4,882 | 267 |
| final | 7 | 7 | 7,517 | closed | closed | closed |

All 70 races were rebuilt without a source failure, and `decide` rejected none of the 65,904 cards as malformed. Two rebuilds from the cache gave identical card files for all 70 races. Five wet races give no card, two of them in `mini_test`.

The calls are counted with policy 1.1 (per-compound tyre ages). In `train`, NO CALL comes from a missing pit-loss estimate (3,197 cards), SC or VSC running (2,442) and unknown gaps (489). Four non-final races never get a pit-loss estimate: Australia 2023, where only two stops were made under green flag, the Netherlands 2023 and Britain 2024, where rain stops the cards early, and Miami 2025, where OpenF1 has only 51% of the laps.

## Data v2 (Experimental milestone)

The Experimental milestone (4 bis, 22 October 2026) rebuilt the race data, outside the freeze of the A/B study. `docs/4bis-decisions.md` gives the reason for each choice below.

### Sources

2.0 cards read `laps`, `stints`, `pit` and `race_control`, plus `weather` and `drivers` for every race. Weather gives the card its `weather` field and the rain reading behind `surface`. `drivers` gives names and team colours to the Replay tab and stays outside the card. `intervals` is downloaded for the gap check only and never feeds a card. The cache and failure rules above still hold, so only `pit` may be empty.

The Replay tab also reads OpenF1's yellow and blue flags and the pit lane times from the cached `race_control` and `pit` responses, and an archived weather forecast from the [Open-Meteo](https://open-meteo.com/) Historical Forecast API. The forecast takes the circuit's latitude and longitude from the Jolpica schedule, asks for temperature, precipitation, rain, weather code, wind and day or night in 15-minute steps, and is cached per race in `data/cache/open-meteo/`. Open-Meteo data is CC BY 4.0 and free for non-commercial use. A failed call caches nothing and the tab shows the forecast as unavailable. None of this feeds a card (`docs/4bis-decisions.md`, D14).

### Splits

`data/splits-v2.json` holds 87 races: 60 in `train`, 10 in `validation`, 7 in `mini_test`, 7 in `final` and 3 in `test_2026`. The 70 races of 2023 to 2025 keep their v1 split and session keys. The 2026 races that ended at least 3 days before the snapshot of 22 October 2026 go in time order: the last 3 (Baku, Kuala Lumpur, Singapore) to `test_2026`, the 3 before to `validation` and the other 11 to `train`. That makes 17 races, since Bahrain and Jeddah were cancelled. The file stores this rule, the snapshot date and the SHA-256 of the v1 splits it extends, and the loader refuses a hand edit as for v1. `test_2026` is closed like `final`: `load_cards` refuses it and the 2.0 manifest has no call counts for it.

### Commands

```text
python -m scripts.rebuild_data splits-v2
python -m scripts.rebuild_data priors
python -m scripts.rebuild_data cards-v2
python -m scripts.rebuild_data quality
python -m scripts.reality_check --splits validation mini_test final
python -m pytest -q tests
```

`splits-v2` freezes `data/splits-v2.json` once and refuses to overwrite it. It stops if a 2023 to 2025 session key differs from `data/splits.json`. `priors` writes `data/reference/priors-v2.json` from the 60 train races. `cards-v2` reads that file and `data/reference/pit-loss-reference.csv`, then writes one JSONL file per race to `data/cards-v2/` with a manifest. The manifest holds the call counts of the open splits, the malformed-card count and the SHA-256 of the six raw responses of each race. `quality` runs the gap check below. `reality_check` compares policy 2.0 on these cards, policy 1.1 on 1.0 cards rebuilt from the same table, and simple baselines with the teams' real stops. Its default splits are the three shown. `tests/test_cards_v2.py` and `tests/test_priors.py` check the 2.0 cards and the priors offline. Pass `tests` to pytest, because a bare run also collects the source copies under `runs/` and fails to import them.

### Card 2.0

A 2.0 card keeps every 1.0 field and adds the card time `as_of`, the surface, tyre wear, the neighbours' tyres, the cars in the pit window, the mandatory stop, pending penalties and the weather. `docs/race-card-contract-v2.md` defines each field and policy 2.0. The card is read at `as_of`, when the driver crosses the line at the end of lap L - 1. It skips lap 1 and the final lap, a driver with no timing at the cutoff, a driver who starts the lap in the pit lane and a red flag at the cutoff. Wet running now gives cards.

### Pit loss, degradation and priors

Pit loss is measured per condition (GREEN, SC, VSC, WET) against the cars that did not stop on the same laps (D5). With too few stops of that condition, the card scales the race's green estimate by the condition's ratio to green, then falls back on a circuit prior, then on a published reference or the train median. Across the 60 train races the median green pit loss is 22.0 s, and a stop under SC, VSC or on a wet track costs 0.70, 0.80 and 1.36 times as much. The two references, Madring at 24.0 s and Kuala Lumpur at 22.5 s, sit in `data/reference/pit-loss-reference.csv` with their sources.

Tyre degradation is fitted on clean dry laps with lap and stint fixed effects (D7). A card uses the race's own value once it is reliable, otherwise the circuit's value from earlier train races, then the compound's. The train medians are 0.058, 0.055 and 0.039 s per lap for SOFT, MEDIUM and HARD before 2026, and 0.045, 0.040 and 0.037 in 2026.

`data/reference/priors-v2.json` holds the pit loss per condition and the degradation of each train race. Circuit priors come only from train races that ended before the card's race. The condition ratios and the wear limits are constants learned on all train races (D11).

### Current rebuild

`rebuild_data cards` gives 65,674 1.0 cards instead of the 65,904 of 18 October. With the corrected track status, 16 races get their real distance back and lose their last-lap cards, and in `train` 875 NO CALL cards become STAY OUT (D3). `rebuild_data cards-v2` gives 90,868 2.0 cards for the 87 races, none of them malformed, and 6,098 of them are WET.

### Gap check

`quality` compares each known gap ahead with OpenF1's interval read just after the crossing, on `validation`, `mini_test`, `final` and `test_2026` (D12). It never runs `decide`, so the gap check reveals no call of the closed splits. On 21,864 cards the median difference is 0.07 to 0.08 s per split, and 2.3% to 4.4% of the cards differ by more than 0.5 s. The worst, up to 47 s, come around pit stops and safety-car bunching.

### Frozen 1.0 cards

The 1.0 cards behind the frozen corpus and results can be rebuilt exactly only from commit `631b783`, the last commit before the Experimental milestone was merged. From a later commit, `rebuild_data cards` overwrites `data/cards/` with the corrected cards, so do not run it there when you need the frozen ones. The code that compares rebuilt cards with the committed corpus, such as `validation_cases`, refuses the rebuilt cards with `V-001: card differs from its recorded source/transformation`.
