"""The replay timeline on small hand-written races: progress, clock cutoff, cards, angles."""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pandas as pd
import pytest

from boxbox.app import replay as R
from boxbox.app.replay import _named, circle, clock, lap_start
from boxbox.data import card_at, frame
from boxbox.data.cards_v2 import RaceContext
from boxbox.data.replay import (
    SECTORS,
    Car,
    Timeline,
    build_timeline,
    cards_at,
    pace,
    pit_window,
    progress,
    status_now,
)

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


def test_both_cards_of_the_lap_are_shown() -> None:
    laps = [EVEN, EVEN, EVEN]
    one = {("1", 2): {"schema_version": "1.0", "lap": 2}}
    line = race({"1": (0.0, laps)}, one)
    line = dataclasses.replace(line, cards_v2={("1", 2): {"schema_version": "2.0"}})
    card, card_v2, lap = cards_at(line, "1", 100.0)
    assert (card["schema_version"], card_v2["schema_version"], lap) == ("1.0", "2.0", 2)


def test_the_pit_window_follows_the_track_status_at_the_clock() -> None:
    line = race({"1": (0.0, [EVEN] * 4)})
    sc = START + pd.Timedelta(seconds=200)
    losses = pd.DataFrame(columns=["condition", "in_lap", "loss", "known_at"])
    past = [
        {
            "season": 2023,
            "circuit_key": 1,
            "date_end": "2023-03-01",
            "pit_loss": {"GREEN": 22.0},
            "degradation": {},
        }
    ]
    context = RaceContext(
        losses, [], {}, pd.DataFrame(), past, {}, {"GREEN": 1.0, "SC": 0.5}
    )
    card = {
        "surface": "DRY",
        "compound": "MEDIUM",
        "pit_loss_seconds": 21.0,
        "pit_loss_condition": "GREEN",
    }
    line = dataclasses.replace(
        line,
        windows=[
            ("SC", sc, sc + pd.Timedelta(seconds=120)),
            ("RED", START + pd.Timedelta(seconds=330), None),
        ],
        context=context,
        race={"circuit_key": 1, "season": 2024},
        cards_v2={("1", lap): card for lap in (2, 3, 4)},
    )
    assert pit_window(line, "1", 150.0) == (21.0, "GREEN")  # the card's own pit loss
    assert pit_window(line, "1", 250.0) == (11.0, "SC")  # mid-lap, before any card
    assert status_now(line, 250.0) == "SC"
    assert pit_window(line, "1", 335.0) == (None, "RED")


def test_cars_wear_their_team_colour_and_acronym() -> None:
    line = race({"1": (0.0, [EVEN] * 3), "44": (20.0, [EVEN] * 3)})  # 80 degrees back
    line = dataclasses.replace(
        line, drivers={"44": {"acronym": "HAM", "team": "Ferrari", "colour": "#e8002d"}}
    )
    svg = circle(line, "1", frame(line, "1", 150.0), (20.0, "GREEN"))
    assert "HAM" in svg and 'fill="#e8002d"' in svg and "car 1" in svg
    assert "GREEN pit window 20.0 to 22.0 s back" in svg


def test_jump_goes_to_the_leader_starting_the_lap() -> None:
    line = race({"1": (0.0, [EVEN] * 4), "2": (5.0, [EVEN] * 4)})
    assert lap_start(line, 3) == 180.0  # car 1 ends lap 2 at 180 s
    assert lap_start(line, 2) == line.first  # car 2 has not crossed at car 1's 90 s
    assert lap_start(line, 9) == line.first  # a lap nobody reached


def test_bunched_cars_keep_their_dots_but_not_all_their_labels() -> None:
    angles = {"2": -3.0, "3": -20.0, "4": -24.0, "5": -40.0, "6": 15.0}
    # 2 is too close to the car on top, 3 too close to 4, which is named first
    assert _named(angles) == {"4", "5", "6"}


def test_a_slower_lap_slows_the_cars_still_on_it() -> None:
    slow = (40.0, 40.0, 40.0)  # a safety-car lap after 90-second laps
    line = race(
        {"1": (0.0, [EVEN, EVEN, slow, slow]), "2": (10.0, [EVEN, EVEN, slow, slow])}
    )
    t = 300.0  # car 1 has crossed its slow lap 3 at 300 s, car 2 is still on it
    assert pace(line, t) == 1.0  # no factor under green
    sc = START + pd.Timedelta(seconds=185)
    line = dataclasses.replace(line, windows=[("SC", sc, None)])
    assert pace(line, t) == pytest.approx(120 / 90)
    angle = frame(line, "1", t)["angles"]["2"]
    assert -90 < angle < -5  # behind car 1 on the track, not piled on the line


def test_a_card_waits_for_the_car_behind_to_cross() -> None:
    laps = [EVEN] * 4
    cards = {
        ("1", lap): {"lap": lap, "gap_behind": {"seconds": 3.0}} for lap in (2, 3, 4)
    }
    line = race({"1": (0.0, laps), "2": (3.0, laps)}, cards)
    assert cards_at(line, "1", 181.0)[2] == 2  # car 1 crossed at 180 s, car 2 not yet
    assert cards_at(line, "1", 183.5)[2] == 3


def test_a_stopped_car_has_no_card() -> None:
    line = race({"1": (0.0, [EVEN] * 2), "2": (3.0, [EVEN] * 6)})
    assert cards_at(line, "1", 500.0) == (None, None, None)


def test_the_replay_starts_once_every_car_has_crossed() -> None:
    # car 2 has no timing before lap 3, as 2025-06 before lap 25
    table = pd.DataFrame(
        [["1", lap, 90.0, 90.0 * lap] for lap in range(1, 5)]
        + [["2", lap, 90.0, 3.0 + 90.0 * lap] for lap in (3, 4)],
        columns=["driver_number", "lap", "lap_seconds", "end_s"],
    )
    raw = pd.DataFrame(
        [[1, 1, START.isoformat(), *EVEN]],
        columns=["driver_number", "lap_number", "date_start", *SECTORS],
    )
    assert build_timeline(table, raw, {}).first == 273.0  # car 2's first crossing


def test_a_policy_2_box_marks_the_card_for_the_sound(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(R, "format_answer", lambda card: card["answer"])
    box = {"answer": "CALL: BOX\nWHY: The window is open."}
    stay = {"answer": "CALL: STAY OUT\nWHY: Young tyres."}
    assert 'data-box="r|1|12"' in R.calls(stay, box, 12, "1", "r|1|12")
    assert "data-box" not in R.calls(box, stay, 12, "1", "r|1|12")  # 1.1 does not ring
    assert "data-box" not in R.calls(None, None, None, "1", "r|1|None")
    assert R.sound_head(tmp_path / "missing.wav") == ""
    sound = tmp_path / "box.wav"
    sound.write_bytes(b"RIFF")
    head = R.sound_head(sound)
    assert head.startswith("<script>") and "data:audio/wav;base64,UklGRg==" in head
