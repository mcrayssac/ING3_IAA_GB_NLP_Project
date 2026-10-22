"""Race replay: where each car is on the lap at a clock time, from data timed up to it.

The clock counts seconds from the race start. A car's progress is its completed laps
plus the share of the lap it is driving, interpolated over the sector times of its
previous lap, each sector counting as a third of a lap. Every value at clock t comes
from line crossings at or before t.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from .openf1 import CACHE_DIR, OPENF1, fetch_json, race_table
from .splits import CARDS_DIR

SECTORS = ["duration_sector_1", "duration_sector_2", "duration_sector_3"]
THIRDS = np.array([0, 1 / 3, 2 / 3, 1])
OUT_AFTER = 2.0  # predicted laps without a crossing before a car counts as stopped


class Car(NamedTuple):
    """One car's line crossings: lap number, clock time and that lap's sector times."""

    lap: np.ndarray
    end: np.ndarray
    sectors: np.ndarray


@dataclass(frozen=True)
class Timeline:
    """One race on the replay clock, with its cards keyed by (driver, lap)."""

    event: str
    start: pd.Timestamp  # race start, UTC
    utc_offset: pd.Timedelta  # local time of the track
    first: float  # replay start: the last lap-1 crossing, as cards start at lap 2
    end: float  # chequered flag: the leader's last crossing
    total_laps: int
    cars: dict[str, Car]
    cards: dict[tuple[str, int], dict[str, Any]]


def build_timeline(
    table: pd.DataFrame,
    raw: pd.DataFrame,
    cards: dict[tuple[str, int], dict[str, Any]],
    event: str = "",
    utc_offset: str = "0s",
) -> Timeline:
    """The timeline of a race from its per-lap table and its raw OpenF1 laps."""
    dates = pd.to_datetime(raw["date_start"], utc=True, format="ISO8601")
    modes = dates[raw["lap_number"] == 1].mode()
    start = modes.iloc[0] if len(modes) else dates.min()  # no lap-1 start: table origin
    sectors = raw.assign(driver_number=raw["driver_number"].astype(str))
    sectors = sectors.rename(columns={"lap_number": "lap"})[
        ["driver_number", "lap", *SECTORS]
    ]
    rows = table[table["end_s"].notna()].merge(sectors, how="left")
    rows = rows.sort_values(["driver_number", "lap"])
    # end_s counts from the earliest date_start of the race, not from the start
    rows["end"] = rows["end_s"] - (start - dates.min()).total_seconds()
    lap_time = rows["lap_seconds"].fillna(
        rows.groupby("driver_number")["end"].diff().fillna(rows["end"])
    )
    rows[SECTORS] = rows[SECTORS].apply(lambda s: s.fillna(lap_time / 3))
    # sectors keep their shares but sum to the lap time: some sector times are glitched
    rows[SECTORS] = rows[SECTORS].mul(lap_time / rows[SECTORS].sum(axis=1), axis=0)
    cars = {
        driver: Car(
            laps["lap"].to_numpy(), laps["end"].to_numpy(), laps[SECTORS].to_numpy()
        )
        for driver, laps in rows.groupby("driver_number")
    }
    total = int(table["lap"].max())
    first = rows.loc[rows["lap"] == 1, "end"].max()
    flag = rows.loc[rows["lap"] == total, "end"].min()
    return Timeline(
        event,
        start,
        pd.Timedelta(utc_offset),
        float(first),
        float(flag),
        total,
        cars,
        cards,
    )


def load_timeline(
    race: dict[str, Any], cache_dir: Path = CACHE_DIR, cards_dir: Path = CARDS_DIR
) -> Timeline:
    """The timeline of a cached race, with its cards and the track's UTC offset."""
    table = race_table(race, cache_dir)  # reads laps.json through the cache first
    folder = cache_dir / str(race["session_key"])
    raw = pd.DataFrame(json.loads((folder / "laps.json").read_text(encoding="utf-8")))
    sessions = fetch_json(
        f"{OPENF1}/sessions?year={race['season']}&session_name=Race",
        cache_dir / f"sessions_{race['season']}.json",
    )
    offset = next(
        s["gmt_offset"] for s in sessions if s["session_key"] == race["session_key"]
    )
    path = cards_dir / f"{race['race_id']}.jsonl"
    records = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    cards = [json.loads(line)["card"] for line in records]
    cards = {(card["driver_number"], card["lap"]): card for card in cards}
    return build_timeline(table, raw, cards, race["event"], offset)


def _seen(car: Car, t: float) -> Car:
    """The crossings at or before t: nothing timed later is read."""
    n = int(np.searchsorted(car.end, t, side="right"))
    return Car(car.lap[:n], car.end[:n], car.sectors[:n])


def _times(sectors: np.ndarray) -> np.ndarray:
    return np.cumsum([0, *sectors])


def progress(car: Car, t: float) -> float | None:
    """Laps covered at clock t, or None before the first crossing or once the car stops."""
    car = _seen(car, t)
    if not len(car.end):
        return None
    elapsed, times = t - car.end[-1], _times(car.sectors[-1])
    # shortcut: a car stopped longer than OUT_AFTER laps is hidden, even under a red flag
    if elapsed > OUT_AFTER * times[-1]:
        return None
    return float(car.lap[-1] + np.interp(elapsed, times, THIRDS))


def reached(car: Car, laps: float, t: float) -> float | None:
    """The earliest clock time, up to t, at which the car had covered `laps`."""
    car = _seen(car, t)
    lap = math.ceil(laps) - 1  # `laps` lies in the stretch (lap, lap + 1]
    i = int(np.searchsorted(car.lap, lap))
    if i == len(car.lap) or car.lap[i] != lap:
        on_line = car.end[car.lap == laps]  # lap 1 has no crossing before it
        return float(on_line[0]) if len(on_line) else None
    done = i + 1 < len(car.end) and car.lap[i + 1] == lap + 1
    # a completed lap uses its own sectors, the lap being driven its previous lap's
    times = _times(car.sectors[i + 1 if done else i])
    when = car.end[i] + np.interp(laps - lap, THIRDS, times)
    return float(min(when, car.end[i + 1]) if i + 1 < len(car.end) else when)


def gap(ahead: Car, behind: Car, t: float) -> float | None:
    """Seconds since the car ahead was where the car behind is at t."""
    where = progress(behind, t)
    when = None if where is None else reached(ahead, where, t)
    return None if when is None else t - when


def _wrap(degrees: float) -> float:
    return (degrees + 180) % 360 - 180


def frame(timeline: Timeline, driver: str, t: float) -> dict[str, Any]:
    """The replay at clock t: race lap, lap scale and every car's angle from `driver`.

    Angles are degrees clockwise, ahead positive: gap / median current lap time x 360.
    """
    covered = {d: progress(car, t) for d, car in timeline.cars.items()}
    running = {d: p for d, p in covered.items() if p is not None}
    lap = min(int(max(running.values(), default=0)) + 1, timeline.total_laps)
    lap_times = [_seen(timeline.cars[d], t).sectors[-1].sum() for d in running]
    scale = float(median(lap_times)) if lap_times else None
    angles = {}
    if driver in running:
        mine = timeline.cars[driver]
        for other, laps in running.items():
            if other == driver:
                continue
            car = timeline.cars[other]
            ahead = laps > running[driver]
            seconds = gap(car, mine, t) if ahead else gap(mine, car, t)
            if seconds is not None:
                angles[other] = _wrap((seconds if ahead else -seconds) / scale * 360)
    return {"lap": lap, "scale": scale, "angles": angles}


def card_at(
    timeline: Timeline, driver: str, t: float
) -> tuple[dict | None, int | None]:
    """The card of the lap the driver is on, as of its last crossing (lap L-1 end)."""
    seen = _seen(timeline.cars[driver], t)
    if not len(seen.lap):
        return None, None
    lap = int(seen.lap[-1]) + 1
    return timeline.cards.get((driver, lap)), lap
