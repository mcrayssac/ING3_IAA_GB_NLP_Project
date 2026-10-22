"""The replay timeline on small hand-written races: progress, clock cutoff, cards, angles."""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pandas as pd
import pytest

from boxbox.app.replay import clock
from boxbox.data import card_at, frame
from boxbox.data.replay import SECTORS, Car, Timeline, build_timeline, progress

START = pd.Timestamp("2024-03-09T17:00:00Z")
EVEN, UNEVEN = (30.0, 30.0, 30.0), (36.0, 29.0, 25.0)


def race(cars: dict[str, tuple[float, list]], cards: dict | None = None) -> Timeline:
    """Each car crosses the line `delay` s after the start plus its laps' sector times."""
    table, raw = [], []
    for driver, (delay, laps) in cars.items():
        end = delay
        for lap, sectors in enumerate(laps, start=1):
            start = START if lap == 1 else START + pd.Timedelta(seconds=end)
            end += sum(sectors)
            table.append([driver, lap, sum(sectors), end])
            raw.append([int(driver), lap, start.isoformat(), *sectors])
    table = pd.DataFrame(
        table, columns=["driver_number", "lap", "lap_seconds", "end_s"]
    )
    raw = pd.DataFrame(
        raw, columns=["driver_number", "lap_number", "date_start", *SECTORS]
    )
    return build_timeline(table, raw, cards or {}, "Test Grand Prix", "03:00:00")


def times(line: Timeline, step: float = 0.25) -> np.ndarray:
    return np.arange(line.first, line.end, step)


def scrambled(line: Timeline, t: float) -> Timeline:
    """The same race with every crossing after t moved and its sectors reshaped."""
    cars = {}
    for driver, car in line.cars.items():
        later = car.end > t
        sectors = np.where(later[:, None], car.sectors[:, ::-1] * 1.4, car.sectors)
        cars[driver] = Car(car.lap, np.where(later, car.end + 9, car.end), sectors)
    return dataclasses.replace(line, cars=cars)


def test_progress_is_monotonic_through_faster_and_slower_laps() -> None:
    laps = [EVEN, EVEN, (25.0, 25.0, 25.0), (40.0, 40.0, 40.0), UNEVEN, EVEN]
    line = race({"1": (0.0, laps)})
    covered = [progress(line.cars["1"], t) for t in times(line)]
    assert all(b >= a for a, b in itertools.pairwise(covered))
    assert progress(line.cars["1"], 180.0) == 2.0  # on the line, exactly two laps
    assert progress(line.cars["1"], 200.0) == pytest.approx(2 + 20 / 90)


def test_nothing_timed_after_the_clock_is_read() -> None:
    laps = [EVEN, UNEVEN, (31.0, 30.0, 28.0), UNEVEN, EVEN]
    line = race({"1": (0.0, laps), "2": (1.5, laps), "3": (4.0, laps[::-1])})
    for t in (95.0, 180.0, 250.7, 333.3):
        other = scrambled(line, t)
        for driver in line.cars:
            assert frame(other, driver, t) == frame(line, driver, t)
            assert card_at(other, driver, t)[1] == card_at(line, driver, t)[1]


def test_the_card_shown_was_built_before_the_clock() -> None:
    laps = [EVEN, UNEVEN, EVEN, UNEVEN]
    cards = {
        ("1", lap): {"lap": lap, "as_of_completed_lap": lap - 1} for lap in (2, 3, 4)
    }
    line = race({"1": (0.0, laps), "2": (3.0, laps)}, cards)
    car = line.cars["1"]
    for t in [*times(line), *car.end[:-1]]:  # no card for the final lap
        card, lap = card_at(line, "1", t)
        as_of = card["as_of_completed_lap"]
        assert as_of == lap - 1 and car.end[car.lap == as_of][0] <= t


def test_angles_place_cars_by_time_gap() -> None:
    laps = [UNEVEN] * 5
    line = race({"1": (0.0, laps), "2": (2.0, laps), "3": (100.0, laps)})
    for t in (190.0, 215.0, 241.0, 268.5, 271.0):  # lap 2 to 3, every sector
        angles = frame(line, "1", t)["angles"]
        assert angles["2"] == pytest.approx(-2 / 90 * 360)  # 2 s behind
        assert angles["3"] == pytest.approx(-100 / 90 * 360 + 360)  # lapped, 10 s on
        assert frame(line, "2", t)["angles"]["1"] == pytest.approx(2 / 90 * 360)


def test_clock_runs_from_wall_time_and_stops_at_the_flag() -> None:
    state = {"t": 100.0, "end": 200.0, "wall": 10.0, "speed": "x4"}
    assert clock(state, 13.0) == 112.0  # however many ticks fired meanwhile
    assert clock(state, 60.0) == 200.0
    assert clock({**state, "wall": None}, 60.0) == 100.0
