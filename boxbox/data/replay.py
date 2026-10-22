"""Race replay: where each car is on the lap at a clock time, from data timed up to it.

The clock counts seconds from the race start. A car's progress is its completed laps
plus the share of the lap it is driving, interpolated over the sector times of its
previous lap, each sector counting as a third of a lap. Every value at clock t comes
from line crossings at or before t.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import median
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from .cards import build_race_cards
from .cards_v2 import (
    MARGIN,
    _pit_condition,
    build_race_cards_v2,
    pit_loss_now,
    race_context,
)
from .openf1 import (
    CACHE_DIR,
    OPENF1,
    Window,
    fetch_json,
    race_control,
    race_extras,
    race_table,
    status_at,
    track_windows,
)
from .priors import PRIORS_FILE, load_reference

SECTORS = ["duration_sector_1", "duration_sector_2", "duration_sector_3"]
THIRDS = np.array([0, 1 / 3, 2 / 3, 1])
OUT_AFTER = 2.0  # predicted laps without a crossing before a car counts as stopped
RECENT = 15.0  # seconds: crossings this recent tell the field's current pace


class Car(NamedTuple):
    """One car's line crossings: lap number, clock time and that lap's sector times."""

    lap: np.ndarray
    end: np.ndarray
    sectors: np.ndarray


@dataclass(frozen=True)
class Timeline:
    """One race on the replay clock, with its 1.0 and 2.0 cards keyed by (driver, lap)."""

    event: str
    start: pd.Timestamp  # race start, UTC
    utc_offset: pd.Timedelta  # local time of the track
    first: float  # replay start: the last lap-1 crossing, as cards start at lap 2
    end: float  # chequered flag: the leader's last crossing
    total_laps: int
    cars: dict[str, Car]
    cards: dict[tuple[str, int], dict[str, Any]]  # 1.0, what the trained model reads
    cards_v2: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    drivers: dict[str, dict[str, str]] = field(default_factory=dict)
    windows: list[Window] = field(default_factory=list)
    context: Any = None  # stops and priors, for the pit loss at the clock
    race: dict[str, Any] = field(default_factory=dict)


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
    # every car has crossed once: 2025-06 has no timing before lap 25
    first = rows.groupby("driver_number")["end"].min().max()
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


def _drivers(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Acronym, team and team colour of each car number, for display only."""
    return {
        str(r["driver_number"]): {
            "acronym": r.get("name_acronym") or str(r["driver_number"]),
            "team": r.get("team_name") or "",
            "colour": f"#{r['team_colour']}" if r.get("team_colour") else "",
        }
        for r in rows
    }


def load_timeline(
    race: dict[str, Any], cache_dir: Path = CACHE_DIR, priors_file: Path = PRIORS_FILE
) -> Timeline:
    """The timeline of a cached race with its 1.0 and 2.0 cards rebuilt from the same
    table, the drivers, the neutralisations and the pit-loss context."""
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
    cards = {
        (r["card"]["driver_number"], r["card"]["lap"]): r["card"]
        for r in build_race_cards(table, race)[0]
    }
    messages, extras = race_control(race, cache_dir), race_extras(race, cache_dir)
    priors = json.loads(priors_file.read_text(encoding="utf-8"))["races"]
    context = race_context(
        race, table, messages, extras["weather"], priors, load_reference()
    )
    line = build_timeline(table, raw, cards, race["event"], offset)
    cards_v2 = build_race_cards_v2(table, race, context)[0]
    return replace(
        line,
        cards_v2={
            (r["card"]["driver_number"], r["card"]["lap"]): r["card"] for r in cards_v2
        },
        drivers=_drivers(extras["drivers"]),
        windows=track_windows(messages, sorted(table["at_line"].dropna())),
        context=context,
        race=race,
    )


def _seen(car: Car, t: float) -> Car:
    """The crossings at or before t: nothing timed later is read."""
    n = int(np.searchsorted(car.end, t, side="right"))
    return Car(car.lap[:n], car.end[:n], car.sectors[:n])


def _times(sectors: np.ndarray) -> np.ndarray:
    return np.cumsum([0, *sectors])


def _basis(sectors: np.ndarray, i: int) -> np.ndarray:
    """Sectors to predict the lap after lap i: the faster of laps i and i - 1, so an
    out-lap or a safety-car lap does not slow the next prediction."""
    if i >= 1 and sectors[i - 1].sum() < sectors[i].sum():
        return sectors[i - 1]
    return sectors[i]


def pace(timeline: Timeline, t: float) -> float:
    """How much slower the latest laps ran than the laps before, under a SC or VSC.

    A car is placed on the pace of a recent lap, so when a safety car slows the field
    it would wait on the line until its crossing shows up. The freshest crossings tell
    the new pace first: those of the last 15 s, or else the latest one. Under green
    the factor stays 1, so one car's slow lap never pulls the field back.
    """
    if status_now(timeline, t) not in ("SC", "VSC"):
        return 1.0
    seen = [_seen(car, t) for car in timeline.cars.values()]
    seen = [car for car in seen if len(car.end) >= 2]
    if not seen:
        return 1.0
    latest = max(car.end[-1] for car in seen)
    recent = [car for car in seen if car.end[-1] >= min(t - RECENT, latest)]
    ratios = [car.sectors[-1].sum() / car.sectors[-2].sum() for car in recent]
    return max(1.0, float(median(ratios))) if ratios else 1.0


def progress(car: Car, t: float, slower: float = 1.0) -> float | None:
    """Laps covered at clock t, or None before the first crossing or once the car stops."""
    car = _seen(car, t)
    if not len(car.end):
        return None
    elapsed = t - car.end[-1]
    times = _times(_basis(car.sectors, len(car.end) - 1)) * slower
    # shortcut: a car stopped longer than OUT_AFTER laps is hidden, even under a red flag
    if elapsed > OUT_AFTER * times[-1]:
        return None
    return float(car.lap[-1] + np.interp(elapsed, times, THIRDS))


def reached(car: Car, laps: float, t: float, slower: float = 1.0) -> float | None:
    """The earliest clock time, up to t, at which the car had covered `laps`."""
    car = _seen(car, t)
    lap = math.ceil(laps) - 1  # `laps` lies in the stretch (lap, lap + 1]
    i = int(np.searchsorted(car.lap, lap))
    if i == len(car.lap) or car.lap[i] != lap:
        on_line = car.end[car.lap == laps]  # lap 1 has no crossing before it
        return float(on_line[0]) if len(on_line) else None
    done = i + 1 < len(car.end) and car.lap[i + 1] == lap + 1
    # a completed lap uses its own sectors, the lap being driven a prediction
    times = (
        _times(car.sectors[i + 1]) if done else _times(_basis(car.sectors, i)) * slower
    )
    when = car.end[i] + np.interp(laps - lap, THIRDS, times)
    return float(min(when, car.end[i + 1]) if i + 1 < len(car.end) else when)


def gap(ahead: Car, behind: Car, t: float, slower: float = 1.0) -> float | None:
    """Seconds since the car ahead was where the car behind is at t."""
    where = progress(behind, t, slower)
    when = None if where is None else reached(ahead, where, t, slower)
    return None if when is None else t - when


def _wrap(degrees: float) -> float:
    return (degrees + 180) % 360 - 180


def race_lap(timeline: Timeline, t: float) -> int:
    """The lap the leader is on: one more than the latest lap anyone has completed,
    which stays right while the race is suspended and no car is running."""
    done = [
        int(_seen(car, t).lap[-1])
        for car in timeline.cars.values()
        if (car.end <= t).any()
    ]
    return min(max(done, default=0) + 1, timeline.total_laps)


def frame(timeline: Timeline, driver: str, t: float) -> dict[str, Any]:
    """The replay at clock t: race lap, lap scale and every car's angle from `driver`.

    Angles are degrees clockwise, ahead positive: gap / median current lap time x 360.
    """
    slower = pace(timeline, t)
    covered = {d: progress(car, t, slower) for d, car in timeline.cars.items()}
    running = {d: p for d, p in covered.items() if p is not None}
    lap_times = []
    for d in running:
        seen = _seen(timeline.cars[d], t)
        lap_times.append(_basis(seen.sectors, len(seen.end) - 1).sum() * slower)
    scale = float(median(lap_times)) if lap_times else None
    angles = {}
    if driver in running:
        mine = timeline.cars[driver]
        for other, laps in running.items():
            if other == driver:
                continue
            car = timeline.cars[other]
            ahead = laps > running[driver]
            seconds = gap(car, mine, t, slower) if ahead else gap(mine, car, t, slower)
            if seconds is not None:
                angles[other] = _wrap((seconds if ahead else -seconds) / scale * 360)
    return {"lap": race_lap(timeline, t), "scale": scale, "angles": angles}


def card_at(
    timeline: Timeline, driver: str, t: float
) -> tuple[dict | None, int | None]:
    """The card of the lap the driver is on, as of its last crossing (lap L-1 end)."""
    seen = _seen(timeline.cars[driver], t)
    if not len(seen.lap):
        return None, None
    lap = int(seen.lap[-1]) + 1
    return timeline.cards.get((driver, lap)), lap


def _ready(timeline: Timeline, driver: str, lap: int, card: dict | None) -> float:
    """When a lap's card can be shown: once the car behind and the cars it counts in
    its pit window have crossed the line too, as on a timing screen."""
    crossings = [car.end[car.lap == lap - 1] for car in timeline.cars.values()]
    crossings = [float(c[0]) for c in crossings if len(c)]
    mine = timeline.cars[driver]
    as_of = float(mine.end[mine.lap == lap - 1][0])
    loss = (card or {}).get("pit_loss_seconds") or 0.0
    counted = [c for c in crossings if as_of < c <= as_of + loss + MARGIN]
    behind = ((card or {}).get("gap_behind") or {}).get("seconds") or 0.0
    return max([as_of + behind, *counted])


def cards_at(
    timeline: Timeline, driver: str, t: float
) -> tuple[dict | None, dict | None, int | None]:
    """The 1.0 and 2.0 cards the driver has at clock t, or no card once it stopped.

    A lap's card shows once the cars it reads have crossed; until then the previous
    lap's card stays up."""
    if progress(timeline.cars[driver], t) is None:
        return None, None, None
    card, lap = card_at(timeline, driver, t)
    card_v2 = timeline.cards_v2.get((driver, lap))
    if lap and lap > 2 and t < _ready(timeline, driver, lap, card_v2 or card):
        lap -= 1
        card, card_v2 = (
            timeline.cards.get((driver, lap)),
            timeline.cards_v2.get((driver, lap)),
        )
    return card, card_v2, lap


def status_now(timeline: Timeline, t: float) -> str:
    """Track status at clock t, from race-control messages sent by then."""
    return status_at(timeline.windows, timeline.start + pd.Timedelta(seconds=t))


def _surface_card(timeline: Timeline, driver: str, lap: int | None) -> dict | None:
    """The driver's 2.0 card for the lap, else its latest earlier one, else any car's."""
    for back in range(lap or 0, max((lap or 0) - 4, 1), -1):
        if (driver, back) in timeline.cards_v2:
            return timeline.cards_v2[(driver, back)]
    field = [c for (d, n), c in timeline.cards_v2.items() if n == lap]
    return field[0] if field else None


def pit_window(timeline: Timeline, driver: str, t: float) -> tuple[float | None, str]:
    """(pit loss, condition) for the driver at clock t. It shrinks the moment a SC or
    VSC comes out, without waiting for the next card; while the condition is the
    card's own it is the card's pit loss, the one the call uses; no window under red."""
    status = status_now(timeline, t)
    if status == "RED":
        return None, "RED"
    _, own, lap = cards_at(timeline, driver, t)
    card = own or _surface_card(timeline, driver, lap)
    surface = card["surface"] if card else "DRY"
    kind = _pit_condition(status, surface, card["compound"] if own else None)
    if own and own.get("pit_loss_condition") == kind:
        return own.get("pit_loss_seconds"), kind
    if timeline.context is None:
        return (card or {}).get("pit_loss_seconds"), kind
    at = timeline.start + pd.Timedelta(seconds=t)
    return pit_loss_now(timeline.context, timeline.race, kind, at)[0], kind
