import numpy as np
import pandas as pd
from test_data import START, table

from boxbox.data.pitloss import (
    condition,
    penalty_awards,
    pending_penalty,
    race_estimate,
    stop_losses,
)
from boxbox.data.priors import (
    condition_ratio,
    degradation_prior,
    earlier,
    pit_loss_prior,
)
from boxbox.data.tyres import degradation


def at(minute: float) -> pd.Timestamp:
    return START + pd.Timedelta(minutes=minute)


def test_served_notices_are_not_awards_and_a_stop_serves_the_penalty() -> None:
    messages = [
        {
            "date": at(5).isoformat(),
            "message": "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 2 (X)",
        },
        {
            "date": at(9).isoformat(),
            "message": "PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 2 (X)",
        },
        {
            "date": at(20).isoformat(),
            "message": "FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 2",
        },
    ]
    awards = penalty_awards(messages)
    assert [(car, seconds) for _, car, seconds in awards] == [("2", 5), ("2", 10)]
    assert pending_penalty(awards, [at(8)], "2", at(8)) == 5  # served at this stop
    assert pending_penalty(awards, [at(8)], "2", at(25)) == 10
    assert pending_penalty(awards, [at(8)], "3", at(25)) == 0


def test_stop_conditions() -> None:
    lap = {"pit_status": "GREEN", "compound": "MEDIUM", "neutralised_in_lap": False}
    assert condition(pd.Series(lap), pd.Series(lap)) == "GREEN"
    assert condition(pd.Series({**lap, "pit_status": "SC"}), pd.Series(lap)) == "SC"
    assert condition(pd.Series({**lap, "pit_status": "RED"}), pd.Series(lap)) is None
    sc_out = pd.Series({**lap, "neutralised_in_lap": True})
    assert condition(pd.Series(lap), sc_out) is None
    inters = pd.Series({**lap, "compound": "INTERMEDIATE"})
    assert condition(pd.Series(lap), inters) == "WET"


def field_of_seven() -> pd.DataFrame:
    """The four-car table plus three cars without a stop, 20, 30 and 40 s behind car 1."""
    laps = table()  # each stop adds 12 s to the in-lap and 12 s to the out-lap
    copies = []
    for driver, behind in (("5", 20.0), ("6", 30.0), ("7", 40.0)):
        car = laps[laps["driver_number"] == "1"].copy()
        car["driver_number"] = driver
        car["end_s"] += behind
        car["at_line"] += pd.Timedelta(seconds=behind)
        copies.append(car)
    return pd.concat([laps, *copies], ignore_index=True)


def test_a_stop_costs_its_laps_against_the_field_minus_the_penalty() -> None:
    messages = [
        {"date": at(1).isoformat(), "message": "5 SECOND TIME PENALTY FOR CAR 3 (X)"}
    ]
    losses = stop_losses(field_of_seven(), messages).set_index("driver_number")
    assert losses["loss"].to_dict() == {"2": 24.0, "3": 19.0, "4": 24.0}
    assert losses.loc["3", "penalty_served"] == 5


def test_a_stop_is_known_once_its_comparison_laps_end() -> None:
    laps = field_of_seven()
    losses = stop_losses(laps, []).set_index("driver_number")
    crossing = laps.set_index(["driver_number", "lap"])["at_line"]
    # car 3's out-lap 8 ends at 750 s, car 7's lap 8 at 760 s
    assert losses.loc["3", "known_at"] == crossing[("7", 8)] > crossing[("3", 8)]


def test_one_or_two_cars_still_running_are_not_a_field() -> None:
    assert stop_losses(table(), []).empty  # at most two cars without a stop per lap


def test_the_race_estimate_takes_the_last_known_stops() -> None:
    losses = pd.DataFrame(
        {
            "condition": ["GREEN"] * 6 + ["SC"],
            "in_lap": [5, 6, 7, 8, 9, 10, 11],
            "loss": [30.0, 20.0, 21.0, 22.0, 23.0, 24.0, 10.0],
            "known_at": [at(m) for m in (6, 7, 8, 9, 10, 11, 12)],
        }
    )
    assert race_estimate(losses, "GREEN", at(30)) == (22.0, 11, 5)
    assert race_estimate(losses, "GREEN", at(7.5)) == (None, None, 2)
    assert race_estimate(losses, "SC", at(30)) == (None, None, 1)


def test_degradation_recovers_the_slope_whatever_the_fuel_effect() -> None:
    rng = np.random.default_rng(7)
    rows = []
    for driver, stop in (("1", 10), ("2", 15), ("3", 20), ("4", 25)):
        for lap in range(2, 40):
            age = lap if lap < stop else lap - stop
            compound = "MEDIUM" if lap < stop else "HARD"
            slope = 0.05 if compound == "MEDIUM" else 0.03
            seconds = 90 - 0.06 * lap + slope * age + rng.normal(0, 0.05)
            rows.append(
                {
                    "driver_number": driver,
                    "lap": lap,
                    "compound": compound,
                    "tyre_age_end": age,
                    "lap_seconds": seconds,
                }
            )
    fits = degradation(pd.DataFrame(rows))
    assert abs(fits["MEDIUM"]["b"] - 0.05) < 0.01
    assert abs(fits["HARD"]["b"] - 0.03) < 0.01


def summary(season, circuit, end, green=None, sc=None, medium=None) -> dict:
    pit_loss = {k: v for k, v in (("GREEN", green), ("SC", sc)) if v is not None}
    return {
        "season": season,
        "circuit_key": circuit,
        "date_end": end,
        "pit_loss": pit_loss,
        "degradation": {} if medium is None else {"MEDIUM": medium},
        "stop_tyre_loss": [],
    }


PRIORS = {
    "2024-01": summary(2024, 1, "2024-03-02", green=20.0, sc=10.0, medium=0.05),
    "2024-02": summary(2024, 2, "2024-03-09", green=24.0, sc=12.0, medium=0.07),
    "2026-01": summary(2026, 3, "2026-03-08", green=22.0, medium=0.10),
    "2026-02": summary(2026, 4, "2026-03-15", medium=0.11),
    "2026-03": summary(2026, 5, "2026-03-29", medium=0.12),
    "2026-09": summary(2026, 1, "2026-10-01", green=99.0),  # later than the races below
}


def test_priors_come_only_from_earlier_races_and_fall_back_in_order() -> None:
    race = {
        "race_id": "2026-04",
        "season": 2026,
        "circuit_key": 1,
        "date_end": "2026-04-12",
    }
    past = earlier(PRIORS, race)
    assert {s["date_end"] for s in past} == {
        "2024-03-02",
        "2024-03-09",
        "2026-03-08",
        "2026-03-15",
        "2026-03-29",
    }
    sc = condition_ratio(list(PRIORS.values()), "SC")
    assert sc == 0.5 and condition_ratio(past, "VSC") is None
    assert pit_loss_prior(past, race, 1.0, {}) == (20.0, "circuit")
    assert pit_loss_prior(past, race, sc, {}) == (10.0, "circuit")
    new = {**race, "circuit_key": 153}
    assert pit_loss_prior(past, new, 1.0, {153: 24.0}) == (24.0, "reference")
    assert pit_loss_prior(past, new, 1.0, {}) == (22.0, "global")
    assert pit_loss_prior(past, race, None, {}) == (None, None)


def test_2026_degradation_shifts_older_circuit_values() -> None:
    race = {
        "race_id": "2026-04",
        "season": 2026,
        "circuit_key": 1,
        "date_end": "2026-04-12",
    }
    past = earlier(PRIORS, race)
    # old median 0.06, new median 0.11: Barcelona-style circuit 1 had 0.05 in 2024
    assert degradation_prior(past, race, "MEDIUM") == (0.1, "circuit")
    assert degradation_prior(past, {**race, "circuit_key": 9}, "MEDIUM") == (
        0.11,
        "global",
    )
    assert degradation_prior(past, race, "SOFT") == (None, None)
