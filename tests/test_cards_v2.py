import pandas as pd
from test_data import RACE, START, table

from boxbox.data.cards import cutoff_facts
from boxbox.data.cards_v2 import (
    LapFacts,
    RaceContext,
    build_card_v2,
    cars_in_pit_window,
    lap_facts,
    mandatory_stop_pending,
    pit_loss_now,
    surface,
    weather_at,
)
from boxbox.rules import decide

RACE_V2 = {**RACE, "circuit_key": 1, "date_end": "2024-03-02T17:00:00+00:00"}


def readings(*rain_minutes: int) -> pd.DataFrame:
    rows = [
        {
            "at": START + pd.Timedelta(minutes=m),
            "air_temperature": 20.0,
            "track_temperature": 30.0,
            "humidity": 50.0,
            "wind_speed": 1.0,
            "rainfall": 1 if m in rain_minutes else 0,
        }
        for m in range(60)
    ]
    return pd.DataFrame(rows)


def context(losses=None, past=None) -> RaceContext:
    empty = pd.DataFrame(columns=["condition", "in_lap", "loss", "known_at"])
    return RaceContext(
        losses=empty if losses is None else losses,
        awards=[],
        stop_times={},
        weather=readings(),
        past=past or [],
        reference={},
        ratios={"GREEN": 1.0, "SC": 0.5},
    )


def facts_with(inflation=None, wet_share=0.0) -> LapFacts:
    return LapFacts(cutoff_facts(table(), 19), {}, wet_share, inflation)


def test_surface_turns_wet_with_rain_wet_tyres_or_slow_laps() -> None:
    at = START + pd.Timedelta(minutes=30)
    assert surface(facts_with(), readings(), at) == "DRY"
    assert surface(facts_with(), readings(25), at) == "WET"
    assert surface(facts_with(), readings(15), at) == "DRY"  # rain stopped 15 min ago
    assert surface(facts_with(wet_share=0.5), readings(), at) == "WET"
    assert surface(facts_with(inflation=1.10), readings(), at) == "WET"
    # once lap times are known, a drying track is dry even if most cars are on inters
    assert surface(facts_with(inflation=1.04, wet_share=0.8), readings(), at) == "DRY"


def test_the_weather_is_the_last_reading_before_the_card() -> None:
    weather = readings(10)
    assert (
        weather_at(weather, START + pd.Timedelta(minutes=10, seconds=30))["rainfall"]
        == 1
    )
    assert weather_at(weather, START - pd.Timedelta(minutes=1)) is None


def test_a_dry_race_needs_two_dry_compounds() -> None:
    laps = table()
    assert mandatory_stop_pending(laps, "2", 19)
    laps.loc[(laps["driver_number"] == "2") & (laps["lap"] >= 8), "compound"] = "HARD"
    assert not mandatory_stop_pending(laps, "2", 19)
    laps.loc[(laps["driver_number"] == "3") & (laps["lap"] == 4), "compound"] = (
        "INTERMEDIATE"
    )
    assert not mandatory_stop_pending(laps, "3", 19)


def test_the_pit_window_counts_cars_behind_within_the_loss_and_margin() -> None:
    facts = cutoff_facts(table(pits={}), 19)  # cars cross 3 s apart
    assert cars_in_pit_window(facts, "1", 4.0, 90.0) == 2  # 3 s and 6 s <= 6.0
    assert cars_in_pit_window(facts, "1", 3.9, 90.0) == 1
    assert cars_in_pit_window(facts, "1", None, 90.0) is None


def test_pit_loss_falls_back_from_the_race_to_the_priors() -> None:
    known = START + pd.Timedelta(hours=1)
    green = pd.DataFrame(
        {
            "condition": ["GREEN"] * 3,
            "in_lap": [5, 6, 7],
            "loss": [20.0, 21.0, 22.0],
            "known_at": [START] * 3,
        }
    )
    past = [
        {
            "season": 2023,
            "circuit_key": 1,
            "date_end": "2023-03-01",
            "pit_loss": {"GREEN": 24.0, "SC": 12.0},
            "degradation": {},
        }
    ]
    assert pit_loss_now(context(green, past), RACE_V2, "GREEN", known) == (
        21.0,
        8,
        "race",
    )
    assert pit_loss_now(context(green, past), RACE_V2, "SC", known) == (
        10.5,
        8,
        "race scaled",
    )
    assert pit_loss_now(context(None, past), RACE_V2, "SC", known) == (
        12.0,
        0,
        "circuit",
    )
    assert pit_loss_now(context(None, []), RACE_V2, "GREEN", known) == (
        None,
        None,
        None,
    )


def test_a_2_0_card_is_decided_by_policy_2_0() -> None:
    laps = table()
    lap = lap_facts(laps, 19)
    card, _ = build_card_v2(laps, RACE_V2, "2", 20, lap, context())
    assert card["schema_version"] == "2.0"
    assert (
        card["as_of"]
        == laps.set_index(["driver_number", "lap"])["at_line"][("2", 19)].isoformat()
    )
    assert card["mandatory_stop_pending"] and card["surface"] == "DRY"
    assert card["gap_ahead"]["compound"] == "MEDIUM"
    assert decide(card)[0] in {"BOX", "STAY OUT", "NO CALL"}
    assert not decide(card)[1].startswith("The card schema")


def test_lap_l_and_later_never_change_a_2_0_card() -> None:
    later = table()
    after = later["lap"] >= 20
    later.loc[after, ["lap_seconds", "end_s", "compound", "status"]] = [
        1.0,
        1.0,
        "HARD",
        "SC",
    ]
    later.loc[after, "neutralised_in_lap"] = True
    build = lambda laps: build_card_v2(
        laps, RACE_V2, "2", 20, lap_facts(laps, 19), context()
    )[0]
    assert build(later) == build(table())
