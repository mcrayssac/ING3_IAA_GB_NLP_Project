"""The replay timeline on small hand-written races: progress, clock cutoff, cards, angles."""

from __future__ import annotations

import dataclasses
import itertools

import gradio as gr
import numpy as np
import pandas as pd
import pytest

from boxbox.app import icons as I
from boxbox.app import replay as R
from boxbox.app.replay import _named, circle, clock, lap_start
from boxbox.data import (
    cards_at,
    flags_at,
    frame,
    pit_state,
    standings,
    tyre_at,
    tyre_options,
)
from boxbox.data.cards_v2 import RaceContext
from boxbox.data.replay import (
    SECTORS,
    Car,
    Timeline,
    _pits,
    build_timeline,
    lap_on,
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
    line = build_timeline(table, raw, "Test Grand Prix", "03:00:00")
    return dataclasses.replace(line, cards_v2=cards or {})


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
        assert standings(other, t) == standings(line, t)
        for driver in line.cars:
            assert frame(other, driver, t) == frame(line, driver, t)
            assert lap_on(other, driver, t) == lap_on(line, driver, t)


def test_the_card_shown_was_built_before_the_clock() -> None:
    laps = [EVEN, UNEVEN, EVEN, UNEVEN]
    cards = {
        ("1", lap): {"lap": lap, "as_of_completed_lap": lap - 1} for lap in (2, 3, 4)
    }
    line = race({"1": (0.0, laps), "2": (3.0, laps)}, cards)
    car = line.cars["1"]
    for t in [*times(line), *car.end[:-1]]:  # no card for the final lap
        card, lap = cards_at(line, "1", t)
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


def test_the_card_of_the_lap_is_the_2_0_card() -> None:
    line = race({"1": (0.0, [EVEN] * 3)}, {("1", 2): {"schema_version": "2.0"}})
    card, lap = cards_at(line, "1", 100.0)
    assert (card["schema_version"], lap) == ("2.0", 2)


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
    assert ">44<" in svg and 'style="fill:#fff"' in svg  # the number, white on red
    assert "1 turn = 50 s" in svg  # 20 s apart: the ring zooms in


def test_the_circle_zooms_to_the_field_and_keeps_the_pit_window() -> None:
    assert R.turn(90.0, [3.0, -12.0], 20.0) == 50  # the rejoin point reaches farthest
    assert R.turn(90.0, [40.0], 20.0) == 90.0  # a spread field keeps the real lap
    assert R.turn(90.0, [], 20.0) == 90.0
    assert R.turn(None, [3.0], 20.0) is None
    assert R._ink("#ffffff") == "#000" and R._ink("#1d4ed8") == "#fff"
    assert R._ink("var(--bx-ink)") == "var(--block-background-fill)"


def test_the_call_panel_shows_pit_states_instead_of_a_call(monkeypatch) -> None:
    monkeypatch.setattr(R, "format_answer", lambda card: card["answer"])
    box = {"answer": "CALL: BOX\nWHY: The window is open."}
    assert R.call_state(box, 12, None) == "BOX"
    assert R.call_state(box, 12, "IN PIT") == "IN PIT"  # the in-lap's BOX card is done
    assert R.call_state(None, 13, "OUT LAP") == "OUT LAP"
    assert R.call_state(None, None, None) == "RETIRED"
    assert R.call_state(None, 13, None) == "NO CARD"
    in_pit = R.calls(box, 12, "1", "r|1|12", "IN PIT")
    assert "IN PIT" in in_pit and "data-box" not in in_pit and "NO CALL" not in in_pit
    assert 'class="banner box even"' in R.calls(box, 12, "1", "r|1|12")
    assert 'class="banner box odd"' in R.calls(box, 13, "1", "r|1|13")


@pytest.mark.parametrize(
    ("code", "day", "kind"),
    [
        (0, 1, "sun"),
        (0, 0, "moon"),
        (2, 1, "partly"),
        (3, 1, "cloud"),
        (45, 1, "fog"),
        (53, 1, "drizzle"),
        (63, 1, "rain"),
        (81, 0, "rain"),
        (95, 1, "storm"),
        (float("nan"), 1, "unknown"),
    ],
)
def test_weather_codes_pick_their_icon(code, day, kind) -> None:
    assert I.sky(code, day) == kind


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
    assert cards_at(line, "1", 181.0)[1] == 2  # car 1 crossed at 180 s, car 2 not yet
    assert cards_at(line, "1", 183.5)[1] == 3


def test_a_stopped_car_has_no_card() -> None:
    line = race({"1": (0.0, [EVEN] * 2), "2": (3.0, [EVEN] * 6)})
    assert cards_at(line, "1", 500.0) == (None, None)


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
    assert build_timeline(table, raw).first == 273.0  # car 2's first crossing


def test_flags_follow_sector_yellows_until_cleared_or_stale() -> None:
    line = race({"1": (0.0, [EVEN] * 12)})
    sc = START + pd.Timedelta(seconds=700)
    flags = [
        (10.0, "YELLOW", 4, None),
        (20.0, "DOUBLE YELLOW", 5, None),
        (30.0, "CLEAR", 4, None),
        (40.0, "CLEAR", None, None),  # TRACK CLEAR
        (50.0, "YELLOW", 7, None),
        (100.0, "BLUE", None, "1"),
    ]
    line = dataclasses.replace(
        line, flags=flags, windows=[("SC", sc, sc + pd.Timedelta(seconds=60))]
    )
    assert flags_at(line, "1", 15.0) == ("YELLOW", {4: "YELLOW"}, False)
    assert flags_at(line, "1", 25.0)[:2] == (
        "DOUBLE YELLOW",
        {4: "YELLOW", 5: "DOUBLE YELLOW"},
    )
    assert flags_at(line, "1", 35.0)[:2] == ("DOUBLE YELLOW", {5: "DOUBLE YELLOW"})
    assert flags_at(line, "1", 45.0)[:2] == ("GREEN", {})
    assert flags_at(line, "1", 105.0) == ("YELLOW", {7: "YELLOW"}, True)
    assert flags_at(line, "2", 105.0)[2] is False  # waved at car 1 only
    assert flags_at(line, "1", 115.0)[2] is False  # 15 s later
    assert flags_at(line, "1", 651.0)[:2] == ("GREEN", {})  # never cleared, stale
    assert flags_at(line, "1", 730.0)[0] == "SC"
    assert flags_at(line, "1", line.end)[0] == "CHEQUERED"


def test_pit_state_shows_the_pit_lane_then_the_out_lap() -> None:
    line = race({"1": (0.0, [EVEN] * 5)})  # crossings at 90, 180, 270...
    line = dataclasses.replace(
        line,
        pits={"1": [(2, 175.0, 200.0)]},
        tyres={("1", 2): ("MEDIUM", 20), ("1", 3): ("HARD", 1)},
    )
    assert pit_state(line, "1", 170.0, 2) is None
    assert pit_state(line, "1", 190.0, 2) == "IN PIT"
    assert pit_state(line, "1", 210.0, 3) == "OUT LAP"  # no card for the out-lap
    assert pit_state(line, "1", 280.0, 4) is None
    assert pit_state(line, "1", 210.0) is None  # without a card lap: the lane only
    assert tyre_at(line, "1", 170.0) == ("MEDIUM", 19)
    assert tyre_at(line, "1", 190.0) == ("HARD", 0)  # crossed in the lane: new set


def test_pit_windows_come_from_pit_data_or_the_in_lap_crossing() -> None:
    table = pd.DataFrame(
        {
            "driver_number": ["1", "2", "3"],
            "lap": [5, 7, 8],
            "pit_in": [True, True, False],
            "at_line": [START + pd.Timedelta(seconds=s) for s in (300, 400, 500)],
        }
    )
    date = (START + pd.Timedelta(seconds=320)).isoformat()
    rows = [{"driver_number": 1, "lap_number": 5, "date": date, "lane_duration": 23.0}]
    # car 2 has no pit row, as in 2023 rounds 1 to 6: lane from the crossing, 20 s
    assert _pits(table, rows, START) == {
        "1": [(5, 297.0, 320.0)],
        "2": [(7, 400.0, 420.0)],
    }


def test_standings_order_lapped_and_stopped_cars() -> None:
    line = race(
        {
            "1": (0.0, [EVEN] * 5),
            "2": (5.0, [EVEN] * 5),
            "3": (100.0, [EVEN] * 4),  # more than a lap down
            "4": (2.0, [EVEN] * 2),  # stops after lap 2
        }
    )
    rows = standings(line, 400.0)
    assert [r["driver"] for r in rows] == ["1", "2", "3", "4"]
    assert rows[1]["gap"] == rows[1]["interval"] == pytest.approx((5.0, 0))
    assert rows[2]["gap"] == rows[2]["interval"] == (None, 1)  # +1 LAP
    assert rows[0]["gap"] is None and rows[3]["gap"] is None
    assert [r["out"] for r in rows] == [False, False, False, True]


def test_a_slow_lap_without_pit_data_holds_the_car_at_the_line() -> None:
    slow = (60.0, 30.0, 30.0)  # 30 s slower, with no pit data to say why
    line = race({"1": (0.0, [EVEN] * 5), "2": (5.0, [EVEN] * 3 + [slow, EVEN])})
    # car 2 crossed lap 3 at 275 s and is predicted on the line from 365 s
    assert standings(line, 300.0)[1]["gap"] == pytest.approx((5.0, 0))
    assert standings(line, 380.0)[1]["gap"] == pytest.approx((20.0, 0))


def test_a_car_in_the_pit_lane_waits_at_the_line() -> None:
    in_lap, out_lap = (30.0, 30.0, 35.0), (45.0, 30.0, 30.0)  # 5 s, then 15 s lost
    line = race(
        {"1": (0.0, [EVEN] * 5), "2": (5.0, [EVEN, EVEN, in_lap, out_lap, EVEN])}
    )
    card = {
        "surface": "DRY",
        "compound": "MEDIUM",
        "pit_loss_seconds": 20.0,
        "pit_loss_condition": "GREEN",
    }
    line = dataclasses.replace(
        line, pits={"2": [(3, 277.0, 300.0)]}, cards_v2={("2", 3): card}
    )
    # car 2 crosses lap 3 at 280 s and lap 4 at 385 s, 25 s after car 1's 360 s
    assert standings(line, 300.0)[1]["gap"] == pytest.approx((25.0, 0))  # not 10
    assert frame(line, "1", 300.0)["angles"]["2"] == pytest.approx(-25 / 90 * 360)
    assert progress(line.cars["2"], 384.0, 1.0, 15.0) == pytest.approx(3 + 89 / 90)


def test_the_lap_slider_follows_the_race_and_jumps_to_the_last_lap(monkeypatch) -> None:
    state = {"lap": 7}
    assert R._follow(state, 7) == (state, gr.skip())  # same lap: nothing sent
    moved, bar = R._follow(state, 8)
    assert moved["lap"] == 8 and bar["value"] == 8
    line = race({"1": (0.0, [EVEN] * 5), "44": (2.0, [EVEN] * 5)})
    monkeypatch.setattr(R, "timeline", lambda race_id: line)
    state = {"race": "r", "driver": "1", "t": 100.0, "end": line.end, "wall": None}
    assert R.jump(state, 5)[0]["t"] == 360.0  # lap 5 of 5, the last one, from 360 s
    assert R.jump(state, 1)[0]["t"] == line.first  # typed 1 on the way to 12
    assert R.pick_race("r", "44")[0]["driver"] == "44"
    assert R.pick_race("r", "99")[0]["driver"] == "1"  # not in the race: the leader


def test_a_policy_2_box_marks_the_card_for_the_sound(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(R, "format_answer", lambda card: card["answer"])
    box = {"answer": "CALL: BOX\nWHY: The window is open."}
    stay = {"answer": "CALL: STAY OUT\nWHY: Young tyres."}
    assert 'data-box="r|1|12"' in R.calls(box, 12, "1", "r|1|12")
    assert "data-box" not in R.calls(stay, 12, "1", "r|1|12")
    assert "data-box" not in R.calls(None, None, "1", "r|1|None")
    assert "Policy 1.1" not in R.calls(stay, 12, "1", "r|1|12")
    assert R.sound_head(tmp_path / "missing.wav") == ""
    sound = tmp_path / "box.wav"
    sound.write_bytes(b"RIFF")
    head = R.sound_head(sound)
    assert head.startswith("<script>") and "data:audio/wav;base64,UklGRg==" in head


def test_the_best_compound_is_the_softest_that_lasts_with_two_compounds() -> None:
    slopes = {"SOFT": (0.05, "race"), "MEDIUM": (0.06, "race"), "HARD": (0.03, "race")}
    options = {
        "slopes": slopes,
        "laps_left": 12,
        "used": {"SOFT", "HARD"},
        "wet": False,
    }
    # lives: SOFT 0.62 / 0.05 = 12, MEDIUM 1.08 / 0.06 = 18, HARD 1.38 / 0.03 = 46
    assert R.tyre_life("SOFT", 0.05) == 12 and R.tyre_life("HARD", None) is None
    assert R.best_compound(options) == "SOFT"
    assert R.best_compound({**options, "laps_left": 15}) == "MEDIUM"
    assert R.best_compound({**options, "laps_left": 60}) == "HARD"  # none lasts
    assert R.best_compound({**options, "used": {"SOFT"}}) == "MEDIUM"  # a second one
    assert R.best_compound({**options, "wet": True}) is None
    assert R.best_compound({**options, "slopes": {}}) is None


def test_tyre_options_read_the_card_lap_the_laps_left_and_the_sets_used() -> None:
    line = race({"1": (0.0, [EVEN] * 5)})  # crossings at 90, 180, 270...
    slopes = {"SOFT": (0.05, "global"), "MEDIUM": (0.08, "circuit"), "HARD": None}
    line = dataclasses.replace(
        line,
        degradation={2: slopes, 3: {**slopes, "MEDIUM": (0.09, "race")}},
        tyres={("1", lap): ("MEDIUM", lap) for lap in (1, 2, 3)}
        | {("1", 4): ("HARD", 1)},
    )
    options = tyre_options(line, "1", 200.0)  # on lap 3, two laps done
    assert options["lap"] == 3 and options["slopes"]["MEDIUM"] == (0.09, "race")
    assert options["laps_left"] == 3 and options["used"] == {"MEDIUM"}
    assert not options["wet"]
    assert tyre_options(line, "1", 280.0)["used"] == {"MEDIUM", "HARD"}
    assert tyre_options(line, "1", 280.0)["slopes"]["MEDIUM"] == (0.09, "race")


def test_the_inner_arc_shows_the_way_to_the_rejoin_window() -> None:
    line = race({"1": (0.0, [EVEN] * 3), "44": (20.0, [EVEN] * 3)})
    svg = circle(line, "1", frame(line, "1", 150.0), (20.0, "GREEN"))
    assert 'class="loss"' in svg and 'class="window"' in svg and ">rejoin<" in svg
    assert 'class="band"' not in svg  # the ring itself carries no rejoin any more
    readout = svg.split('class="readout">')[1]
    assert "behind" not in readout and "44 20.0 s behind" not in readout
    assert "car 44 20.0 s behind" in svg.split("</title>")[0]  # still read aloud
    red = circle(line, "1", frame(line, "1", 150.0), (None, "RED"))
    assert 'class="loss"' not in red and ">rejoin<" not in red
    assert 'local</div><div class="mono">UTC+3<' in R.clock_text(line, 2, 150.0)
    assert R._utc(pd.Timedelta(hours=-8)) == "UTC-8"
    assert R._utc(pd.Timedelta(hours=5, minutes=30)) == "UTC+5:30"


def test_the_tiles_show_each_reading_with_its_icon() -> None:
    line = race({"1": (0.0, [EVEN] * 3)})
    weather = pd.DataFrame(
        {
            "at": [START],
            "air_temperature": [26.4],
            "track_temperature": [31.2],
            "humidity": [61.0],
            "wind_speed": [1.6],
            "rainfall": [0.0],
        }
    )
    steps = pd.DataFrame(
        {
            "at": [START + pd.Timedelta(minutes=m) for m in (0, 15, 30)],
            "weather_code": [0, 3, 61],
            "is_day": [0, 0, 0],
            "temperature_2m": [24.0, 23.6, 23.1],
            "precipitation": [0.0, 0.0, 0.4],
            "wind_speed_10m": [2.0, 2.4, 3.1],
        }
    )
    context = RaceContext(pd.DataFrame(), [], {}, weather, [], {}, {})
    line = dataclasses.replace(line, context=context, forecast=steps)
    strip = R.status_strip(line, "1", 100.0)
    assert strip.count('class="icon metric"') == 4
    for value in ("26°C", "31°C", "61%", "1.6 m/s"):
        assert value in strip
    assert '<table class="steps">' in strip and '<th scope="col">Wind</th>' in strip
    assert "0.4 mm" in strip and "Weather data by Open-Meteo.com" in strip
    gone = R.status_strip(dataclasses.replace(line, forecast=None), "1", 100.0)
    assert "Forecast unavailable" in gone
    assert "tyre" not in R.driver_tile(line, "1")
