# Data protocol (M2.1)

Status: implemented, to review. Owner: Matthieu, reviewer: Maxime. Card field names and the pit-loss method are proposals until the M1.1 contract (`docs/race-card-policy.md`) is integrated.

## Source

FastF1 race sessions (`session 'R'`), laps only (no telemetry, weather or messages). Raw timing data stays in the local FastF1 cache `data/cache/` and generated cards in `data/cards/`; both are git-ignored and never redistributed. The repository ships the script that rebuilds them. OpenF1 is not used.

## Commands

Run from the repository root (launcher to be aligned with M1.2):

```text
python scripts/rebuild_data.py splits --seasons 2023 2024 2025 --seed 2026
python scripts/rebuild_data.py card --race 2024-01 --driver VER --lap 20
python scripts/rebuild_data.py cards
python -m pytest tests/test_data.py
```

## Splits (frozen before any dialogue)

- Unit: a whole race. Every championship race of the chosen seasons is shuffled with a fixed seed and assigned to `train`, `validation`, `mini_test` or `final` (70/10/10/10, at least 5 races per evaluation split so race-level bootstrap is possible).
- `data/splits.json` stores the seed, seasons, versions, the race list per split and its SHA-256. The `splits` command refuses to overwrite it; `cards` refuses to run if the file was edited by hand. Changing the splits needs an explicit team decision before M2.2 starts.
- A race that fails to load stays in its split, produces no card and is listed in `data/cards/manifest.json` under `failures`. It is never moved to another split.
- Option to decide as a team: keep the 2026 season out entirely, or use it as an extra regulation-shift test after the freeze.

## Card for (race, driver, lap L)

Every value is computed from laps with `LapNumber <= L` only. `build_card` truncates the table first; `test_no_future_lap_is_used` rewrites every lap after L and checks that the card is unchanged.

| Field | How it is computed |
|---|---|
| `position`, `car_ahead`, `car_behind` | Order in which cars crossed the line at the end of lap L (`Time`). |
| `gap_ahead_s`, `gap_behind_s` | Difference of `Time` at the end of lap L, in seconds, 3 decimals. |
| `compound`, `tyre_age_laps` | `Compound`, `TyreLife` of lap L. |
| `compounds_used` | Dry compounds used by the driver up to lap L. |
| `track_status` | Most severe status during lap L: RED > SC > VSC > YELLOW > GREEN. |
| `pit_loss_s` | Median green-flag pit loss of stops completed by lap L, all cars (below). |
| `total_laps`, `laps_remaining` | Scheduled race distance (known before the start). |

**Pit loss (proposal for M1.1):** for each stop whose in-lap and out-lap are both completed by lap L and fully green, `loss = in-lap + out-lap − 2 × reference pace`. The reference pace is the median of the driver's last 5 clean green laps before the stop (at least 2). Values outside 5–60 s are discarded as data errors (cleaning bounds, not F1 truths). With fewer than 3 usable stops, `pit_loss_s` is `null`. Stops under SC/VSC are excluded so the estimate is a green-flag loss; how SC/VSC changes the cost is a policy decision.

## Missing values

A value that cannot be computed is `null`, and `card["missing"][field]` says why (timing gap, leader, last runner, not enough stops...). Nothing is imputed. Whether a missing field blocks a call is decided by the M1.1 policy, not here.

## Situations without a card

Skipped and counted in the manifest (`skipped`): lap 1, final lap, in-laps and out-laps, red-flag laps, driver without timing at the end of the lap, and any driver who has used intermediate or wet tyres (BoxBox covers dry tracks only).

## Reproducibility

Each card carries `provenance` (source, laps used, stops used, schema and FastF1 versions). `data/cards/manifest.json` records the splits fingerprint, parameters, library versions, SHA-256 of each cards file, per-race counts and failures. The same parameters and cache give byte-identical card files; `card` prints a SHA-256 for the two-rebuild check.

## Network and cache

The first run downloads each race into `data/cache/` (slow, may hit rate limits). Later runs read the cache. A download or parsing failure raises `DataUnavailableError`: `card` exits with code 2, `cards` continues with the other races, records the failure and exits with code 2.

## Open points for review

1. Align field names and the blocking/non-blocking fields with M1.1.
2. Accept or change the pit-loss method and its thresholds (`CardParams`).
3. Confirm the seasons, seed and 2026 option before freezing `data/splits.json`.
4. The dependency file (fastf1, pandas, pytest) is coordinated with M1.2; versions tested: Python 3.13, FastF1 3.8.3, pandas 2.3.3 (offline tests only).
