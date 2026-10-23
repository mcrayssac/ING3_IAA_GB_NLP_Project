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

from .cards import WET_COMPOUNDS, build_race_cards
from .cards_v2 import (
    MARGIN,
    _pit_condition,
    build_race_cards_v2,
    lap_facts,
    pit_loss_now,
    race_context,
    slope_now,
)
from .openf1 import (
    CACHE_DIR,
    OPENF1,
    Window,
    _endpoint,
    fetch_json,
    race_control,
    race_extras,
    race_table,
    status_at,
    track_windows,
)
from .openmeteo import load_forecast
from .priors import PRIORS_FILE, load_reference
from .tyres import DRY

SECTORS = ["duration_sector_1", "duration_sector_2", "duration_sector_3"]
THIRDS = np.array([0, 1 / 3, 2 / 3, 1])
OUT_AFTER = 2.0  # predicted laps without a crossing before a car counts as stopped
RECENT = 15.0  # seconds: crossings this recent tell the field's current pace
LANE_AFTER = 20.0  # median seconds from the in-lap crossing to the pit exit
# shortcut: a sector yellow with no CLEAR is dropped after 10 min (most clear far
# sooner); upgrade if race control ever sends an end for every yellow
YELLOW_KEPT = 600.0
BLUE_SHOWN = 10.0  # seconds a blue flag stays up for the driver it was waved at
FLAGS = ("YELLOW", "DOUBLE YELLOW", "CLEAR", "BLUE")
Flag = tuple[float, str, int | None, str | None]  # clock s, flag, sector, car


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
    # in-lap, pit-lane entry and exit of each stop, in clock seconds
    pits: dict[str, list[tuple[int, float, float]]] = field(default_factory=dict)
    # compound and tyre age at the end of each (driver, lap)
    tyres: dict[tuple[str, int], tuple[str | None, int | None]] = field(
        default_factory=dict
    )
    flags: list[Flag] = field(default_factory=list)  # yellow, clear and blue flags
    forecast: pd.DataFrame | None = None  # Open-Meteo steps, for display only
    # each dry compound's degradation on each card lap: (s per lap of age, source)
    degradation: dict[int, dict[str, tuple[float | None, str | None]]] = field(
        default_factory=dict
    )


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


def _pits(
    table: pd.DataFrame, rows: list[dict[str, Any]], start: pd.Timestamp
) -> dict[str, list[tuple[int, float, float]]]:
    """In-lap, pit-lane entry and exit of every stop, in clock seconds.

    The pit endpoint's date is the lane exit, about 20 s after the in-lap crossing, so
    the entry is that date minus the lane time. Without pit data (2023 rounds 1 to 6)
    the car is in the lane from its in-lap crossing for the usual 20 s."""
    stops = {
        (str(r["driver_number"]), r["lap_number"]): r for r in rows if r.get("date")
    }
    pits: dict[str, list[tuple[int, float, float]]] = {}
    in_laps = table.loc[table["pit_in"], ["driver_number", "lap", "at_line"]]
    for driver, lap, at in in_laps.itertuples(index=False):
        crossing = None if pd.isna(at) else (at - start).total_seconds()
        stop = stops.get((driver, lap))
        if stop:
            out = (pd.Timestamp(stop["date"]) - start).total_seconds()
            entry = (
                out - stop["lane_duration"] if stop.get("lane_duration") else crossing
            )
        else:
            entry = crossing
            out = None if crossing is None else crossing + LANE_AFTER
        if entry is not None and out is not None:
            pits.setdefault(driver, []).append((int(lap), entry, out))
    return pits


def _flags(messages: list[dict[str, Any]], start: pd.Timestamp) -> list[Flag]:
    """Yellow, clear and blue flags in clock seconds, in the order race control sent
    them; a CLEAR with no sector is the TRACK CLEAR that lifts every yellow."""
    flags = [
        (
            (pd.Timestamp(m["date"]) - start).total_seconds(),
            m["flag"],
            m.get("sector") if m.get("scope") == "Sector" else None,
            str(m["driver_number"]) if m.get("driver_number") else None,
        )
        for m in messages
        if m.get("flag") in FLAGS
    ]
    return sorted(flags, key=lambda f: f[0])  # tuples with None do not compare


def _degradation(
    table: pd.DataFrame, context: Any, race: dict[str, Any]
) -> dict[int, dict[str, tuple[float | None, str | None]]]:
    """Each dry compound's degradation on each card lap, read as the 2.0 cards read
    their own compound's: this race's laps once reliable, else the circuit or global
    prior from earlier train races."""
    slopes = {}
    for lap in range(2, int(table["lap"].max())):
        facts = lap_facts(table, lap - 1)
        slopes[lap] = {c: slope_now(facts, context, race, c) for c in DRY}
    return slopes


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
    tyres = table[["driver_number", "lap", "compound", "tyre_age_end"]]
    return replace(
        line,
        cards_v2={
            (r["card"]["driver_number"], r["card"]["lap"]): r["card"] for r in cards_v2
        },
        drivers=_drivers(extras["drivers"]),
        windows=track_windows(messages, sorted(table["at_line"].dropna())),
        context=context,
        race=race,
        pits=_pits(table, _endpoint("pit", race["session_key"], cache_dir), line.start),
        tyres={
            (d, int(lap)): (
                c if isinstance(c, str) else None,
                None if pd.isna(a) else int(a),
            )
            for d, lap, c, a in tyres.itertuples(index=False)
        },
        flags=_flags(messages, line.start),
        forecast=load_forecast(
            race,
            line.start,
            line.start + pd.Timedelta(seconds=line.end),
            openf1_cache=cache_dir,
        ),
        degradation=_degradation(table, context, race),
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


def progress(
    car: Car, t: float, slower: float = 1.0, delay: float = 0.0
) -> float | None:
    """Laps covered at clock t, or None before the first crossing or once the car stops.
    A car on its out-lap waits `delay` seconds at the line first (`_pit_delay`)."""
    car = _seen(car, t)
    if not len(car.end):
        return None
    elapsed = max(t - car.end[-1] - delay, 0.0)
    times = _times(_basis(car.sectors, len(car.end) - 1)) * slower
    # shortcut: a car stopped longer than OUT_AFTER laps is hidden, even under a red flag
    if elapsed > OUT_AFTER * times[-1]:
        return None
    return float(car.lap[-1] + np.interp(elapsed, times, THIRDS))


def reached(
    car: Car, laps: float, t: float, slower: float = 1.0, delay: float = 0.0
) -> float | None:
    """The earliest clock time, up to t, at which the car had covered `laps`; the lap
    being driven starts `delay` seconds late on an out-lap."""
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
    when = car.end[i] + (0.0 if done else delay) + np.interp(laps - lap, THIRDS, times)
    return float(min(when, car.end[i + 1]) if i + 1 < len(car.end) else when)


def gap(
    ahead: Car,
    behind: Car,
    t: float,
    slower: float = 1.0,
    delays: tuple[float, float] = (0.0, 0.0),
) -> float | None:
    """Seconds since the car ahead was where the car behind is at t."""
    where = progress(behind, t, slower, delays[1])
    when = None if where is None else reached(ahead, where, t, slower, delays[0])
    return None if when is None else t - when


def _pit_delay(timeline: Timeline, driver: str, t: float) -> float:
    """Seconds a car on its out-lap waits at the line in the prediction: the pit loss
    at the clock, the one of the yellow window, less what its in-lap already lost.

    The pit lane runs beside the line, so the car stays there while it loses time,
    instead of running ahead of the field and jumping back at its next crossing."""
    seen = _seen(timeline.cars[driver], t)
    in_laps = {stop[0] for stop in timeline.pits.get(driver, [])}
    if not len(seen.lap) or int(seen.lap[-1]) not in in_laps:
        return 0.0
    loss = pit_window(timeline, driver, t)[0] or 0.0  # no window under a red flag
    i = len(seen.end) - 1
    lost = seen.sectors[i].sum() - _basis(seen.sectors, i).sum()
    return max(loss - float(lost), 0.0)


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
    delays = {d: _pit_delay(timeline, d, t) for d in timeline.cars}
    covered = {
        d: progress(car, t, slower, delays[d]) for d, car in timeline.cars.items()
    }
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
            pair = (delays[other], delays[driver])
            seconds = (
                gap(car, mine, t, slower, pair)
                if ahead
                else gap(mine, car, t, slower, pair[::-1])
            )
            if seconds is not None:
                angle = (seconds if ahead else -seconds) / scale * 360
                # within half a lap the laps covered give the side, so the ring keeps
                # the table's order while a car waits in the pit lane
                near = abs(laps - running[driver]) < 0.5
                angles[other] = min(max(angle, -179.9), 179.9) if near else _wrap(angle)
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


def flags_at(
    timeline: Timeline, driver: str, t: float
) -> tuple[str, dict[int | None, str], bool]:
    """The flag at clock t, the sectors under yellow, and whether the driver was shown
    a blue flag in the last 10 s.

    The flag is CHEQUERED once the leader has crossed it, else RED, SC or VSC while one
    runs, else the worst sector yellow, else GREEN."""
    yellow: dict[int | None, tuple[str, float]] = {}
    blue = False
    for at, kind, sector, car in timeline.flags:
        if at > t:
            break
        if kind == "BLUE":
            blue = blue or (car == driver and at >= t - BLUE_SHOWN)
        elif kind == "CLEAR" and sector is None:
            yellow.clear()
        elif kind == "CLEAR":
            yellow.pop(sector, None)
        else:
            yellow[sector] = (kind, at)
    sectors = {s: k for s, (k, at) in yellow.items() if at >= t - YELLOW_KEPT}
    status = status_now(timeline, t)
    if t >= timeline.end:
        status = "CHEQUERED"
    elif status == "GREEN" and sectors:
        status = "DOUBLE YELLOW" if "DOUBLE YELLOW" in sectors.values() else "YELLOW"
    return status, sectors, blue


def pit_state(
    timeline: Timeline, driver: str, t: float, lap: int | None = None
) -> str | None:
    """IN PIT while the car is in the pit lane, then OUT LAP until the card of the lap
    after its out-lap shows (`lap` is the card lap from cards_at), else None."""
    for in_lap, entry, out in timeline.pits.get(driver, []):
        if entry <= t < out:
            return "IN PIT"
        if lap is not None and out <= t and lap <= in_lap + 1:
            return "OUT LAP"
    return None


def tyre_at(timeline: Timeline, driver: str, t: float) -> tuple[str | None, int | None]:
    """Compound and laps done on the set of the lap being driven at clock t, so the
    new set as soon as the car has crossed the line in the pit lane."""
    seen = _seen(timeline.cars[driver], t)
    lap = int(seen.lap[-1]) + 1 if len(seen.lap) else 1
    compound, age = timeline.tyres.get((driver, lap), (None, None))
    if compound is None:  # a lap without timing, as the lap a car stops on track
        compound, age = timeline.tyres.get((driver, lap - 1), (None, None))
    return compound, None if age is None else age - 1


def tyre_options(timeline: Timeline, driver: str, t: float) -> dict[str, Any]:
    """What the dry compounds offer the driver at clock t: their degradation on the
    card lap shown, the laps left, the dry compounds used so far and a wet track."""
    _, card, lap = cards_at(timeline, driver, t)
    seen = _seen(timeline.cars[driver], t)
    done = int(seen.lap[-1]) if len(seen.lap) else 0
    lap = lap or done + 1  # a stopped car keeps its last lap
    known = [n for n in timeline.degradation if n <= lap]
    used = {
        c
        for (d, n), (c, _) in timeline.tyres.items()
        if d == driver and n <= done + 1 and c in DRY
    }
    current, _ = tyre_at(timeline, driver, t)
    surface = (card or _surface_card(timeline, driver, lap) or {}).get("surface")
    return {
        "lap": lap,
        "slopes": timeline.degradation[max(known)] if known else {},
        "laps_left": max(timeline.total_laps - done, 0),
        "used": used,
        "wet": surface == "WET" or current in WET_COMPOUNDS,
    }


def _behind(
    timeline: Timeline, ahead: str, behind: str, t: float, slower: float, live: dict
) -> tuple[float | None, int]:
    """How far `behind` is from `ahead` on the circle's estimate: (seconds, 0), or
    (None, laps down) once `ahead` has covered a lap more."""
    down = math.floor(live[ahead][0] - live[behind][0])
    if down >= 1:
        return None, down
    cars, delays = timeline.cars, (live[ahead][1], live[behind][1])
    return gap(cars[ahead], cars[behind], t, slower, delays), 0


def standings(timeline: Timeline, t: float) -> list[dict[str, Any]]:
    """The running order at clock t on the circle's estimate, so the table and the ring
    always agree: by laps covered, with the gap to the leader and to the car ahead.
    It updates every tick and settles at each line crossing. Stopped cars come last,
    by laps completed; under a red flag no car counts as stopped."""
    slower = pace(timeline, t)
    red = status_now(timeline, t) == "RED"
    live, out = {}, []
    for driver, car in timeline.cars.items():
        seen = _seen(car, t)
        if not len(seen.lap):
            continue
        delay = _pit_delay(timeline, driver, t)
        laps = progress(car, t, slower, delay)
        if laps is None and red:  # suspended: held where it last crossed
            laps = float(seen.lap[-1])
        if laps is None:
            out.append((-int(seen.lap[-1]), float(seen.end[-1]), driver))
        else:
            live[driver] = (laps, delay)
    order = sorted(live, key=lambda d: -live[d][0])
    rows = [
        {
            "driver": d,
            "laps": int(live[d][0]),
            "gap": None if i == 0 else _behind(timeline, order[0], d, t, slower, live),
            "interval": None
            if i == 0
            else _behind(timeline, order[i - 1], d, t, slower, live),
            "out": False,
        }
        for i, d in enumerate(order)
    ]
    rows += [
        {"driver": d, "laps": -laps, "gap": None, "interval": None, "out": True}
        for laps, _, d in sorted(out)
    ]
    return rows


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
