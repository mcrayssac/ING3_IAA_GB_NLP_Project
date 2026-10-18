# Data protocol (task 2.1)

The rebuild turns historical race timing into race cards in the 1.0 shape of `docs/race-card-contract.md`, and freezes the race-level splits before any dialogue is generated.

## Source

OpenF1 has been the source since 18 October 2026. FastF1's live-timing files now answer 401 for historical races, while OpenF1 serves the same kind of data from the 2023 season onwards. Each race uses four OpenF1 endpoints: `laps`, `stints` (compound and `tyre_age_at_start`), `pit` and `race_control`. Jolpica gives the official round number and event name. A race is matched to its OpenF1 Race session by date, allowing one day of difference because some races start late at night local time. Cancelled sessions are skipped, and a race without exactly one match stops the rebuild. Only the `pit` endpoint may be empty. Any other empty or failed response is a failure and is never cached.

`boxbox/data/openf1.py` turns one race into the per-lap table that every loader returns. It has one row per driver and lap, with these columns: `driver_number`, `lap`, `lap_seconds`, `end_s` (time at the line from the race start), `pit_in`, `pit_out`, `compound`, `tyre_age_end` and `status`. The cards read only this table.

OpenF1's licence (CC BY-NC-SA 4.0) covers our non-commercial academic use. Raw responses stay in `data/cache/openf1/` and cards in `data/cards/`, and neither is committed. The repository ships the rebuild script.

## Commands

From the repository root:

```text
python -m scripts.rebuild_data splits --seasons 2023 2024 2025 --seed 2026
python -m scripts.rebuild_data card --race 2024-01 --driver 1 --lap 20
python -m scripts.rebuild_data cards
python -m pytest tests/test_data.py
```

`splits` writes `data/splits.json` once and refuses to overwrite it. `card` prints one card and its SHA-256 for the double-rebuild check. `cards` writes one JSONL file per race and `data/cards/manifest.json`. A failed request raises `DataUnavailableError`, whatever the network error. `cards` records the race under `failures`, and every command exits with code 2.

## Splits

The unit is a whole race. The 70 races of 2023 to 2025 are shuffled with seed 2026 and split 70/10/10/10 into `train`, `validation`, `mini_test` and `final`, with at least 5 races per evaluation split. `data/splits.json` stores the races, their session keys, the settings, a SHA-256 of the splits and a SHA-256 of the whole file. The loader refuses overlapping splits and any hand edit, including a changed session key. The 2026 season stays out.

## Card for lap L

A card is a snapshot at the start of lap L, so every value comes from laps up to L - 1, the cutoff.

| Field | How it is computed |
|---|---|
| `race`, `lap`, `total_laps`, `driver_number` | Jolpica round and event name. `total_laps` is the race's last lap in OpenF1, which is also the scheduled distance unless the race was shortened. |
| `track_status` | Status at the end of lap L - 1 from race control. SC and VSC run from the lap they are deployed until the lap they come in. A red flag marks its lap and ends any SC or VSC still open. Sector yellows stay GREEN, because they do not neutralise the race. Laps are the leader's laps. |
| `compound`, `tyre_age_laps` | The stint that contains lap L - 1. Age is `tyre_age_at_start` plus the laps run in the stint, so it counts earlier sessions. |
| `gap_ahead`, `gap_behind` | Time at the line at the end of lap L - 1, against the neighbours in running order, with the neighbour's `driver_number`. The leader has NONE ahead and the last runner NONE behind. A gap of at least the driver's own lap time is UNKNOWN, because the neighbour is a lap or more away. If a car timed at the end of lap L - 2 has no time at the end of lap L - 1, its place is unknown, so both gaps are UNKNOWN without a neighbour number. The gap behind is the time the car behind takes to reach the line after the car, so it is known once that car crosses, in the first seconds of lap L, as on a timing screen. |
| `pit_loss_seconds`, `pit_loss_as_of_completed_lap` | An in-lap comes from the `pit` endpoint or is the lap before an out-lap, because the `pit` endpoint is empty for 2023 rounds 1 to 6. OpenF1 stores the out-lap flag on lap L, but the car is already in the pit lane when lap L - 1 ends, so this is known at the cutoff. Median of the field's green stops whose in-lap and out-lap are completed by L - 1: in-lap + out-lap minus twice the driver's median of their last 5 clean green laps (at least 2). Values outside 5 to 60 s are dropped as data errors. Fewer than 3 stops gives null. The second field is the latest out-lap used. |
| `reference_lap_seconds` | Median of the field's clean green laps up to L - 1, null with fewer than 5. |

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

- `total_laps` is the race's last lap in OpenF1. For a race stopped early it would be the distance actually run, which is not known before the start. `decide` only checks that `lap` does not exceed it, so no call depends on it.
- `surface` is DRY because the rebuild skips every card from the first intermediate or wet tyre on. A damp track where every car stays on slicks still counts as dry.

## Deviation from the research plan

The research plan allowed a pit loss estimated from the previous season at the same circuit. The rebuild uses only stops in the same race, because the previous race at that circuit can sit in another split. Before the first three green stops of a race are completed, a card with an opportunity and a car behind therefore gets NO CALL. The first pit-loss estimate of a race comes at lap 14 (median over the non-final races).

## For the corpus (tasks 2.2 and 3.1)

A complete card has a known pit loss, no UNKNOWN gap and green running. `train` has 29,644 of them: 28,989 STAY OUT and 655 BOX. Under the 1.4 policy most BOX cards have no car behind: 497 of the 783 BOX cards in `train`, from 127 race-driver pairs. The corpus should take BOX cards with a car behind (286 in `train`) and cap the cards per race and driver, so neighbouring laps of one stint do not dominate. Real cards whose pit loss is missing are natural material for the NO CALL variants of corpus B.

## Rebuild of 18 October 2026

| Split | Races | Races with cards | Cards | BOX | STAY OUT | NO CALL |
|---|---:|---:|---:|---:|---:|---:|
| train | 49 | 46 | 46,018 | 783 | 38,515 | 6,720 |
| validation | 7 | 7 | 7,155 | 77 | 6,780 | 298 |
| mini_test | 7 | 5 | 5,214 | 80 | 4,888 | 246 |
| final | 7 | 7 | 7,517 | closed | closed | closed |

All 70 races were rebuilt without a source failure, and `decide` rejected none of the 65,904 cards as malformed. Two rebuilds from the cache gave identical card files for all 70 races. Five wet races give no card, two of them in `mini_test`.

In `train`, NO CALL comes from a missing pit-loss estimate (3,697 cards), SC or VSC running (2,442) and unknown gaps (581). Four non-final races never get a pit-loss estimate: Australia 2023, where only two stops were made under green flag, the Netherlands 2023 and Britain 2024, where rain stops the cards early, and Miami 2025, where OpenF1 has only 51% of the laps.
