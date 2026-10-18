"""Offline checks of the OpenF1 loader, the race cards and the splits (task 2.1)."""

from __future__ import annotations

import json
import urllib.error

import pandas as pd
import pytest

from boxbox.data import (
    CardNotEligible,
    DataUnavailableError,
    build_card,
    check_disjoint,
    freeze_splits,
    load_splits,
    make_splits,
    openf1,
)
from boxbox.data.cards import cutoff_facts, pit_loss
from boxbox.rules import decide

RACE = {
    "race_id": "2024-01",
    "season": 2024,
    "round": 1,
    "event": "Test GP",
    "session_key": 1,
}
CONTRACT_KEYS = {
    "schema_version",
    "race",
    "lap",
    "total_laps",
    "driver_number",
    "as_of_completed_lap",
    "surface",
    "track_status",
    "compound",
    "tyre_age_laps",
    "gap_ahead",
    "gap_behind",
    "pit_loss_seconds",
    "pit_loss_as_of_completed_lap",
    "reference_lap_seconds",
}


def table(
    laps: int = 30, pits: dict[str, int] | None = None, status=None
) -> pd.DataFrame:
    """Four drivers 3 s apart, 90 s laps, a used set (3 laps old) and optional stops."""
    pits = {"2": 6, "3": 7, "4": 8} if pits is None else pits
    rows = []
    for rank, driver in enumerate(("1", "2", "3", "4")):
        end = 3.0 * rank
        for lap in range(1, laps + 1):
            seconds = 90.0 + (
                12.0 if lap in (pits.get(driver), (pits.get(driver) or -9) + 1) else 0
            )
            end += seconds
            rows.append(
                {
                    "driver_number": driver,
                    "lap": lap,
                    "lap_seconds": seconds,
                    "end_s": end,
                    "pit_in": lap == pits.get(driver),
                    "pit_out": lap == (pits.get(driver) or -9) + 1,
                    "compound": "MEDIUM",
                    "tyre_age_end": 3 + lap,
                    "status": (status or {}).get(lap, "GREEN"),
                }
            )
    return pd.DataFrame(rows)


def card_at(laps: pd.DataFrame, driver: str = "2", lap: int = 20) -> dict:
    return build_card(laps, RACE, driver, lap, None)[0]


def test_cards_hold_plain_json_values() -> None:
    laps = table()
    for driver in ("1", "2", "3", "4"):
        for lap in (5, 12, 20, 29):
            card = card_at(laps, driver, lap)
            assert decide(card) == decide(json.loads(json.dumps(card)))
            seconds = [card["pit_loss_seconds"], card["reference_lap_seconds"]]
            seconds += [card[gap]["seconds"] for gap in ("gap_ahead", "gap_behind")]
            assert all(value is None or type(value) is float for value in seconds)


def test_card_follows_the_contract() -> None:
    card = card_at(table())
    assert set(card) == CONTRACT_KEYS
    assert (card["lap"], card["as_of_completed_lap"], card["schema_version"]) == (
        20,
        19,
        "1.0",
    )
    assert decide(card)[0] in {"BOX", "STAY OUT", "NO CALL"}
    assert not decide(card)[1].startswith(("The card schema", "The card identity"))


def test_lap_l_and_later_never_change_the_card() -> None:
    later = table()
    after = later["lap"] >= 20
    later.loc[after, ["lap_seconds", "end_s", "compound", "status"]] = [
        1.0,
        1.0,
        "HARD",
        "SC",
    ]
    assert card_at(later) == card_at(table())


def test_gap_states() -> None:
    laps = table(pits={})
    assert card_at(laps, "1")["gap_ahead"] == {"state": "NONE", "seconds": None}
    assert card_at(laps, "4")["gap_behind"] == {"state": "NONE", "seconds": None}
    assert card_at(laps, "2")["gap_ahead"] == {
        "state": "KNOWN",
        "seconds": 3.0,
        "driver_number": "1",
    }
    laps.loc[laps["driver_number"] == "4", "end_s"] += 200.0  # more than a lap behind
    assert card_at(laps, "3")["gap_behind"]["state"] == "UNKNOWN"


def test_tyre_age_counts_earlier_sessions() -> None:
    card = card_at(table())
    assert card["tyre_age_laps"] == 22 > card["as_of_completed_lap"]
    assert decide(card)[0] != "NO CALL" or "tyre age" not in decide(card)[1]


def test_pit_loss_uses_only_green_stops_completed_by_the_cutoff() -> None:
    laps = table()
    assert pit_loss(laps[laps["lap"] <= 19]) == (24.0, 9, 3)
    assert (
        pit_loss(laps[laps["lap"] <= 8])[0] is None
    )  # the third stop ends after lap 8
    neutralised = table(status={7: "SC", 8: "SC"})
    assert pit_loss(neutralised[neutralised["lap"] <= 19])[0] is None


def test_reference_lap_and_status_come_from_the_cutoff() -> None:
    facts = cutoff_facts(table(status={19: "VSC"}), 19)
    assert (facts.reference_lap, facts.status) == (90.0, "VSC")


@pytest.mark.parametrize(
    ("laps", "driver", "lap", "reason"),
    [
        (table(), "2", 1, "first or final lap"),
        (table(), "2", 30, "first or final lap"),
        (table(pits={"2": 19}), "2", 20, "pit lane"),
        (table(status={19: "RED"}), "2", 20, "red flag"),
    ],
)
def test_out_of_scope_situations(laps, driver, lap, reason) -> None:
    with pytest.raises(CardNotEligible, match=reason):
        build_card(laps, RACE, driver, lap, None)


def test_wet_running_is_skipped() -> None:
    laps = table()
    laps.loc[(laps["driver_number"] == "3") & (laps["lap"] == 4), "compound"] = (
        "INTERMEDIATE"
    )
    with pytest.raises(CardNotEligible, match="wet"):
        card_at(laps)


def test_lap_status_from_race_control() -> None:
    messages = [
        {
            "date": "1",
            "lap_number": 3,
            "message": "YELLOW IN TRACK SECTOR 4",
            "flag": "YELLOW",
        },
        {"date": "2", "lap_number": 7, "message": "SAFETY CAR DEPLOYED"},
        {"date": "3", "lap_number": 9, "message": "SAFETY CAR IN THIS LAP"},
        {"date": "4", "lap_number": 12, "message": "VIRTUAL SAFETY CAR DEPLOYED"},
        {"date": "5", "lap_number": 13, "message": "VIRTUAL SAFETY CAR ENDING"},
        {
            "date": "6",
            "lap_number": 15,
            "message": "RED FLAG",
            "flag": "RED",
            "scope": "Track",
        },
    ]
    status = openf1.lap_status(messages, 16)
    assert [status[lap] for lap in (3, 7, 8, 9, 12, 13, 15)] == [
        "GREEN",
        "SC",
        "SC",
        "GREEN",
        "VSC",
        "GREEN",
        "RED",
    ]


def test_network_failure_is_explicit_and_the_cache_needs_no_network(
    monkeypatch, tmp_path
) -> None:
    def offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(openf1.urllib.request, "urlopen", offline)
    with pytest.raises(DataUnavailableError):
        openf1.fetch_json("https://example.invalid/laps", tmp_path / "laps.json")
    (tmp_path / "cached.json").write_text("[1]", encoding="utf-8")
    assert openf1.fetch_json(
        "https://example.invalid/laps", tmp_path / "cached.json"
    ) == [1]


def test_season_races_match_dates_and_skip_cancelled(tmp_path) -> None:
    schedule = [
        {"round": "1", "raceName": "A GP", "date": "2024-03-02"},
        {"round": "2", "raceName": "B GP", "date": "2024-11-23"},
    ]
    sessions = [
        {
            "session_key": 10,
            "date_start": "2024-03-02T15:00:00+00:00",
            "is_cancelled": False,
        },
        {
            "session_key": 11,
            "date_start": "2024-11-24T06:00:00+00:00",
            "is_cancelled": False,
        },
        {
            "session_key": 12,
            "date_start": "2024-05-19T13:00:00+00:00",
            "is_cancelled": True,
        },
    ]
    doc = {"MRData": {"RaceTable": {"Races": schedule}}}
    (tmp_path / "jolpica_2024.json").write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "sessions_2024.json").write_text(json.dumps(sessions), encoding="utf-8")
    races = openf1.season_races(2024, tmp_path)
    assert [(r["race_id"], r["session_key"]) for r in races] == [
        ("2024-01", 10),
        ("2024-02", 11),
    ]


def test_splits_are_disjoint_complete_and_deterministic() -> None:
    ids = [f"{season}-{n:02d}" for season in (2023, 2024, 2025) for n in range(1, 24)]
    splits = make_splits(ids, 2026)
    assert splits == make_splits(list(reversed(ids)), 2026)
    assert sorted(race for races in splits.values() for race in races) == sorted(ids)
    assert all(len(splits[name]) >= 5 for name in ("validation", "mini_test", "final"))
    with pytest.raises(ValueError):
        check_disjoint({"train": ["2024-01"], "final": ["2024-01"]})
    with pytest.raises(ValueError):
        make_splits(ids[:12], 2026)


def test_frozen_splits_refuse_overwrite_and_hand_edits(tmp_path) -> None:
    path = tmp_path / "splits.json"
    freeze_splits({"splits": {"train": ["2024-01"], "final": ["2024-02"]}}, path)
    assert load_splits(path)["splits"]["final"] == ["2024-02"]
    with pytest.raises(FileExistsError):
        freeze_splits({"splits": {"train": []}}, path)
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["splits"]["final"] = ["2024-03"]
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(ValueError, match="edited by hand"):
        load_splits(path)


def test_in_lap_comes_from_the_out_lap_when_pit_data_is_missing(tmp_path) -> None:
    laps = [
        {
            "driver_number": 1,
            "lap_number": lap,
            "date_start": f"2024-03-02T15:{lap:02d}:00+00:00",
            "lap_duration": 60.0,
            "is_pit_out_lap": lap == 4,
        }
        for lap in range(1, 7)
    ]
    stints = [{"driver_number": 1, "lap_start": 1, "lap_end": 6, "compound": "HARD"}]
    for name, rows in {
        "laps": laps,
        "stints": stints,
        "pit": [],
        "race_control": [],
    }.items():
        (tmp_path / "7" / f"{name}.json").parent.mkdir(exist_ok=True)
        (tmp_path / "7" / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    laps_table = openf1.race_table({"session_key": 7}, tmp_path)
    assert list(laps_table.loc[laps_table["pit_in"], "lap"]) == [3]


def test_a_car_missing_at_the_cutoff_makes_the_gaps_unknown() -> None:
    laps = table(pits={})
    laps = laps[~((laps["driver_number"] == "3") & (laps["lap"] == 19))]
    card = card_at(laps, "2")
    assert (
        card["gap_ahead"] == card["gap_behind"] == {"state": "UNKNOWN", "seconds": None}
    )


def test_final_call_counts_stay_closed(monkeypatch, tmp_path) -> None:
    from scripts import rebuild_data

    races = {rid: {**RACE, "race_id": rid} for rid in ("2024-01", "2024-02")}
    splits = {"train": ["2024-01"], "final": ["2024-02"]}
    monkeypatch.setattr(
        rebuild_data,
        "load_splits",
        lambda: {"splits": splits, "races": races, "splits_sha256": "x"},
    )
    monkeypatch.setattr(rebuild_data, "race_table", lambda race: table())
    monkeypatch.setattr(rebuild_data, "raw_sha256", lambda race: {})
    monkeypatch.setattr(rebuild_data, "CARDS_DIR", tmp_path)
    assert rebuild_data.main(["cards"]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["labels"]) == {"train"}
    assert manifest["races"]["2024-02"]["cards"] > 0


def test_a_red_flag_ends_an_open_safety_car() -> None:
    messages = [
        {"date": "1", "lap_number": 1, "message": "SAFETY CAR DEPLOYED"},
        {
            "date": "2",
            "lap_number": 2,
            "message": "RED FLAG",
            "flag": "RED",
            "scope": "Track",
        },
    ]
    status = openf1.lap_status(messages, 5)
    assert [status[lap] for lap in range(1, 6)] == [
        "SC",
        "RED",
        "GREEN",
        "GREEN",
        "GREEN",
    ]
