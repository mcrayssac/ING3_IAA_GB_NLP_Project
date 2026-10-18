# Data protocol (task 2.1)

The rebuild turns historical race timing into race cards in the 1.0 shape of `docs/race-card-contract.md`, and freezes the race-level splits before any dialogue is generated.

## Source

OpenF1 has been the source since 18 October 2026. FastF1's live-timing files now answer 401 for historical races, while OpenF1 serves the same kind of data from the 2023 season onwards. Each race uses four OpenF1 endpoints: `laps`, `stints` (compound and `tyre_age_at_start`), `pit` and `race_control`. Jolpica gives the official round number and event name. A race is matched to its OpenF1 Race session by date, allowing one day of difference because some races start late at night local time. Cancelled sessions are skipped.

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

`splits` writes `data/splits.json` once and refuses to overwrite it. `card` prints one card and its SHA-256 for the double-rebuild check. `cards` writes one JSONL file per race and `data/cards/manifest.json`. A failed request raises `DataUnavailableError`, and the command records the race under `failures` and exits with code 2.

## Splits

The unit is a whole race. The 70 races of 2023 to 2025 are shuffled with seed 2026 and split 70/10/10/10 into `train`, `validation`, `mini_test` and `final`, with at least 5 races per evaluation split. `data/splits.json` stores the races, their session keys, the settings and a SHA-256 of the splits. The loader refuses overlapping splits and a hand-edited file. The 2026 season stays out.

## Card for lap L

A card is a snapshot at the start of lap L, so every value comes from laps up to L - 1, the cutoff.

| Field | How it is computed |
|---|---|
| `race`, `lap`, `total_laps`, `driver_number` | Jolpica round and event name. `total_laps` is the race's last lap in OpenF1, which is also the scheduled distance unless the race was shortened. |
| `track_status` | Status at the end of lap L - 1 from race control. SC and VSC run from the lap they are deployed until the lap they come in. A red flag marks its lap. Sector yellows stay GREEN, because they do not neutralise the race. Laps are the leader's laps. |
| `compound`, `tyre_age_laps` | The stint that contains lap L - 1. Age is `tyre_age_at_start` plus the laps run in the stint, so it counts earlier sessions. |
| `gap_ahead`, `gap_behind` | Time at the line at the end of lap L - 1, against the neighbours in running order, with the neighbour's `driver_number`. The leader has NONE ahead and the last runner NONE behind. A gap of at least the driver's own lap time is UNKNOWN, because the neighbour is a lap or more away. |
| `pit_loss_seconds`, `pit_loss_as_of_completed_lap` | Median of the field's green stops whose in-lap and out-lap are completed by L - 1: in-lap + out-lap minus twice the driver's median of their last 5 clean green laps (at least 2). Values outside 5 to 60 s are dropped as data errors. Fewer than 3 stops gives null. The second field is the latest out-lap used. |
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

- the card keys match the contract
- lap L and later never change the card
- every gap state is handled, and tyre age counts earlier sessions
- pit loss uses only green stops completed by the cutoff
- skipped situations, race-control parsing, date matching, explicit network failures and the split rules all behave as documented

The `cards` command also runs `boxbox.rules.decide` on every card. It counts the calls per split and the cards that `decide` rejects as malformed, which must be 0.

## First rebuild (18 October 2026)

| Split | Races | Races with cards | Cards | BOX | STAY OUT | NO CALL |
|---|---:|---:|---:|---:|---:|---:|
| train | 49 | 46 | 46,163 | 658 | 35,865 | 9,640 |
| validation | 7 | 7 | 7,205 | 72 | 6,701 | 432 |
| mini_test | 7 | 5 | 5,214 | 83 | 4,904 | 227 |
| final | 7 | 7 | 7,517 | 168 | 6,717 | 632 |

All 70 races were rebuilt without a source failure, and `decide` rejected none of the 66,099 cards as malformed. Two rebuilds from the cache gave identical card files for all 70 races. Five wet races give no card, two of them in `mini_test`.

In `train`, NO CALL comes from a missing pit-loss estimate (5,490 cards, before three green stops are completed) and from SC or VSC running (4,138). BOX is about 1.4% of the cards, so task 2.2 has to sample by call instead of taking cards at random.
