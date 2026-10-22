"""Offline checks of the OpenF1 loader, the race cards and the splits (task 2.1)."""

from __future__ import annotations

import http.client
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
from boxbox.data.cards import cutoff_facts, pit_loss, timing_gaps
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


START = pd.Timestamp("2024-03-02T15:00:00+00:00")


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
                    "neutralised_in_lap": lap in (status or {}),
                    "at_line": START + pd.Timedelta(seconds=end),
                    "pit_status": "GREEN" if lap == pits.get(driver) else None,
                    "lane_seconds": None,
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
    later.loc[after, "neutralised_in_lap"] = True
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


def test_each_card_reads_its_own_driver_status() -> None:
    laps = table()
    row = (laps["driver_number"] == "2") & (laps["lap"] == 19)
    laps.loc[row, ["status", "neutralised_in_lap"]] = ["SC", True]
    assert card_at(laps, "2")["track_status"] == "SC"
    assert card_at(laps, "3")["track_status"] == "GREEN"
    laps.loc[row, "status"] = "RED"
    with pytest.raises(CardNotEligible, match="red flag"):
        card_at(laps, "2")
    assert card_at(laps, "3")["track_status"] == "GREEN"


def test_neutralised_laps_stay_out_of_the_reference_lap() -> None:
    laps = table(status={15: "SC", 16: "SC"})
    laps.loc[laps["lap"].isin([15, 16]), "lap_seconds"] = 140.0
    assert cutoff_facts(laps, 19).reference_lap == 90.0


def test_stops_count_only_once_the_leader_has_crossed_after_them() -> None:
    # car 4's out-lap 19 ends 9 s after the leader's lap-19 crossing
    laps = table(pits={"2": 6, "3": 7, "4": 18})
    assert cutoff_facts(laps, 19).pit_loss is None
    assert cutoff_facts(laps, 20).pit_loss_stops == 3


def test_reference_lap_and_status_come_from_the_cutoff() -> None:
    laps = table(status={19: "VSC"})
    assert cutoff_facts(laps, 19).reference_lap == 90.0
    assert card_at(laps)["track_status"] == "VSC"


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


def rc(minute: int, message: str, **fields) -> dict:
    """A race-control message at 15:MM on race day."""
    return {
        "date": f"2024-03-02T15:{minute:02d}:00+00:00",
        "message": message,
        **fields,
    }


def at(minute: float) -> pd.Timestamp:
    return pd.Timestamp("2024-03-02T15:00:00+00:00") + pd.Timedelta(minutes=minute)


def test_track_windows_follow_race_control_timestamps() -> None:
    windows = openf1.track_windows(
        [
            rc(3, "YELLOW IN TRACK SECTOR 4", flag="YELLOW"),
            rc(7, "SAFETY CAR DEPLOYED"),
            rc(9, "SAFETY CAR IN THIS LAP"),
            rc(10, "CLEAR IN TRACK SECTOR 4", flag="CLEAR", scope="Sector"),
            rc(11, "TRACK CLEAR", flag="CLEAR", scope="Track"),
            rc(20, "VIRTUAL SAFETY CAR DEPLOYED"),
            rc(21, "VIRTUAL SAFETY CAR ENDING"),
            rc(22, "TRACK CLEAR", flag="CLEAR", scope="Track"),
        ]
    )
    states = [
        openf1.status_at(windows, at(m)) for m in (3, 8, 10, 11.5, 20.5, 21.5, 22)
    ]
    assert states == ["GREEN", "SC", "SC", "GREEN", "VSC", "VSC", "GREEN"]
    assert openf1.neutralised_between(windows, at(20.2), at(20.8))  # a one-lap VSC
    assert not openf1.neutralised_between(windows, at(12), at(19))


def test_a_safety_car_closes_an_open_virtual_safety_car() -> None:
    windows = openf1.track_windows(
        [
            rc(10, "VIRTUAL SAFETY CAR DEPLOYED"),
            rc(11, "SAFETY CAR DEPLOYED"),
            rc(14, "SAFETY CAR IN THIS LAP"),
            rc(16, "TRACK CLEAR", flag="CLEAR", scope="Track"),
        ]
    )
    states = [openf1.status_at(windows, at(m)) for m in (10.5, 12, 15, 17, 40)]
    assert states == ["VSC", "SC", "SC", "GREEN", "GREEN"]


def test_a_red_flag_ends_a_safety_car_and_lasts_until_the_restart() -> None:
    windows = openf1.track_windows(
        [
            rc(1, "SAFETY CAR DEPLOYED"),
            rc(2, "RED FLAG", flag="RED", scope="Track"),
            rc(28, "TRACK CLEAR", flag="CLEAR", scope="Track"),
            rc(30, "SESSION STARTED"),
            rc(50, "VIRTUAL SAFETY CAR DEPLOYED"),
            rc(52, "CHEQUERED FLAG", flag="CHEQUERED", scope="Track"),
        ]
    )
    # the race ends under the VSC, so it stays open after the flag
    states = [openf1.status_at(windows, at(m)) for m in (1.5, 10, 31, 51, 53)]
    assert states == ["SC", "RED", "GREEN", "VSC", "VSC"]
    suspended = openf1.track_windows([rc(5, "RED FLAG - RACE SUSPENDED")])
    assert openf1.status_at(suspended, at(6)) == "RED"


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
        "race_control": [
            rc(0, "GREEN LIGHT - PIT EXIT OPEN", flag="GREEN", scope="Track")
        ],
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


def test_line_time_is_the_next_lap_start(tmp_path) -> None:
    laps = [
        {
            "driver_number": 1,
            "lap_number": 1,
            "date_start": "2024-03-02T15:00:00+00:00",
        },
        {
            "driver_number": 1,
            "lap_number": 2,
            "date_start": "2024-03-02T15:01:00.5+00:00",
        },
        {
            "driver_number": 1,
            "lap_number": 4,
            "date_start": "2024-03-02T15:03:00+00:00",
        },
    ]
    for lap in laps:
        lap.update(lap_duration=60.0, is_pit_out_lap=False)
    for name, rows in {
        "laps": laps,
        "stints": [],
        "pit": [],
        "race_control": [
            rc(0, "GREEN LIGHT - PIT EXIT OPEN", flag="GREEN", scope="Track")
        ],
    }.items():
        (tmp_path / "8").mkdir(exist_ok=True)
        (tmp_path / "8" / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    end_s = list(openf1.race_table({"session_key": 8}, tmp_path)["end_s"])
    assert end_s == [60.5, 120.5, 240.0]  # lap 3 is missing, so lap 2 uses its duration


@pytest.mark.parametrize(
    "failure",
    [ConnectionResetError("reset"), http.client.IncompleteRead(b"")],
)
def test_every_network_failure_is_explicit(monkeypatch, tmp_path, failure) -> None:
    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(openf1.urllib.request, "urlopen", broken)
    with pytest.raises(DataUnavailableError):
        openf1.fetch_json("https://example.invalid/laps", tmp_path / "laps.json")
    assert not (tmp_path / "laps.json").exists()


def test_only_the_pit_endpoint_may_be_empty(monkeypatch, tmp_path) -> None:
    def not_found(url, *args, **kwargs):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(openf1.urllib.request, "urlopen", not_found)
    assert openf1._endpoint("pit", 9, tmp_path) == []
    with pytest.raises(DataUnavailableError):
        openf1._endpoint("laps", 9, tmp_path)
    assert not (tmp_path / "9" / "laps.json").exists()


def test_a_restart_behind_the_safety_car_ends_at_the_next_crossing() -> None:
    messages = [
        rc(0, "RED FLAG", flag="RED", scope="Track"),
        rc(20, "RACE WILL RESUME AT 17:14 - ROLLING START PROCEDURE"),
        rc(21, "TRACK CLEAR", flag="CLEAR", scope="Track"),
        rc(25, "SESSION STARTED"),
        rc(28, "SAFETY CAR WILL ENTER PITS: ROLLING START PROCEDURE"),
    ]
    windows = openf1.track_windows(messages, [at(26.5), at(29.5), at(31)])
    states = [openf1.status_at(windows, at(m)) for m in (10, 22, 26, 29, 30)]
    # the race is still suspended after TRACK CLEAR, until SESSION STARTED
    assert states == ["RED", "RED", "SC", "SC", "GREEN"]


def test_a_red_flag_in_the_same_second_as_a_safety_car_ends_it() -> None:
    windows = openf1.track_windows(
        [
            rc(1, "RED FLAG", flag="RED", scope="Track"),
            rc(1, "SAFETY CAR DEPLOYED"),
            rc(20, "SESSION STARTED"),
        ]
    )
    assert openf1.status_at(windows, at(30)) == "GREEN"


def test_the_session_end_stands_in_for_a_missing_chequered_flag() -> None:
    messages = [rc(0, "SESSION STARTED"), rc(50, "SESSION FINISHED")]
    assert openf1.chequered_at(messages) == at(50)


def test_status_is_read_when_each_driver_crosses_the_line(tmp_path) -> None:
    laps = [
        {
            "driver_number": driver,
            "lap_number": lap,
            "date_start": f"2024-03-02T15:{lap - 1:02d}:{offset:02d}+00:00",
            "lap_duration": 60.0,
            "is_pit_out_lap": False,
        }
        for driver, offset in ((1, 0), (2, 30))
        for lap in range(1, 6)
    ]
    messages = [
        rc(0, "GREEN LIGHT - PIT EXIT OPEN", flag="GREEN", scope="Track"),
        {"date": "2024-03-02T15:02:15+00:00", "message": "SAFETY CAR DEPLOYED"},
        {
            "date": "2024-03-02T15:04:01+00:00",  # 1 s after car 1 crosses
            "message": "CHEQUERED FLAG",
            "flag": "CHEQUERED",
            "scope": "Track",
        },
    ]
    for name, rows in {
        "laps": laps,
        "stints": [],
        "pit": [],
        "race_control": messages,
    }.items():
        (tmp_path / "9").mkdir(exist_ok=True)
        (tmp_path / "9" / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    result = openf1.race_table({"session_key": 9}, tmp_path).set_index(
        ["driver_number", "lap"]
    )
    # car 1 ends lap 2 at 15:02:00, before the SC; car 2 ends it at 15:02:30
    assert result.loc[("1", 2), "status"] == "GREEN"
    assert result.loc[("2", 2), "status"] == "SC"
    assert bool(result.loc[("1", 3), "neutralised_in_lap"])
    # car 1 takes the flag at 15:04:00, so lap 5 is dropped for both cars
    assert sorted(result.index.get_level_values("lap").unique()) == [1, 2, 3, 4]


def test_missing_race_control_fails_instead_of_green() -> None:
    with pytest.raises(DataUnavailableError):
        openf1.track_windows([])


def test_an_unmatched_race_fails(tmp_path) -> None:
    schedule = {
        "MRData": {
            "RaceTable": {
                "Races": [{"round": "1", "raceName": "A GP", "date": "2024-03-02"}]
            }
        }
    }
    (tmp_path / "jolpica_2024.json").write_text(json.dumps(schedule), encoding="utf-8")
    (tmp_path / "sessions_2024.json").write_text("[]", encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="0 OpenF1 Race sessions"):
        openf1.season_races(2024, tmp_path)


def test_edited_race_details_are_refused(tmp_path) -> None:
    path = tmp_path / "splits.json"
    races = {"2024-01": {"session_key": 1}}
    freeze_splits({"races": races, "splits": {"train": ["2024-01"]}}, path)
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["races"]["2024-01"]["session_key"] = 2
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(ValueError, match="edited by hand"):
        load_splits(path)


def test_timing_gaps_count_only_holes_of_two_laps_or_more() -> None:
    laps = table(pits={})
    one_hole = laps[~((laps["driver_number"] == "3") & (laps["lap"] == 10))]
    two_holes = one_hole[
        ~((one_hole["driver_number"] == "3") & (one_hole["lap"] == 11))
    ]
    assert (timing_gaps(laps), timing_gaps(one_hole), timing_gaps(two_holes)) == (
        0,
        0,
        1,
    )


def test_the_splits_command_refuses_a_frozen_file(monkeypatch, tmp_path) -> None:
    from scripts import rebuild_data

    frozen = tmp_path / "splits.json"
    frozen.write_text("{}", encoding="utf-8")

    def no_network(season):
        raise AssertionError("must not fetch anything")

    monkeypatch.setattr(rebuild_data, "SPLITS_FILE", frozen)
    monkeypatch.setattr(rebuild_data, "season_races", no_network)
    assert rebuild_data.main(["splits", "--seasons", "2024", "--seed", "1"]) == 1
    assert frozen.read_text(encoding="utf-8") == "{}"


def test_the_final_split_stays_closed_until_the_final_test(tmp_path) -> None:
    from boxbox.config import build_config
    from boxbox.data import FinalSplitClosedError, load_cards

    splits = tmp_path / "splits.json"
    freeze_splits({"splits": {"train": ["2024-01"], "final": ["2024-02"]}}, splits)
    for race_id, split in (("2024-01", "train"), ("2024-02", "final")):
        record = {"card_id": race_id, "split": split, "card": {}}
        (tmp_path / f"{race_id}.jsonl").write_text(
            json.dumps(record) + "\n", encoding="utf-8"
        )
    closed, opened = build_config({}), build_config({"final_test_open": True})
    assert [r["card_id"] for r in load_cards("train", closed, tmp_path, splits)] == [
        "2024-01"
    ]
    with pytest.raises(FinalSplitClosedError):
        load_cards("final", closed, tmp_path, splits)
    assert [r["card_id"] for r in load_cards("final", opened, tmp_path, splits)] == [
        "2024-02"
    ]


def test_the_2026_split_follows_time() -> None:
    from scripts.rebuild_data import split_2026

    races = [
        {"race_id": f"2026-{n:02d}", "date_end": f"2026-0{n}-01T15:00:00+00:00"}
        for n in (8, 1, 2, 3, 4, 5, 6, 7)
    ]
    assert split_2026(races) == {
        "train": ["2026-01", "2026-02"],
        "validation": ["2026-03", "2026-04", "2026-05"],
        "test_2026": ["2026-06", "2026-07", "2026-08"],
    }


def test_splits_v2_keep_the_v1_races_and_add_finished_2026_races(
    monkeypatch, tmp_path
) -> None:
    from scripts import rebuild_data

    def race(rid, key, end):
        return {
            "race_id": rid,
            "season": int(rid[:4]),
            "session_key": key,
            "circuit_key": key,
            "date_end": end,
        }

    old = race("2024-01", 1, "2024-03-02T17:00:00+00:00")
    new = [
        race(f"2026-{n:02d}", 10 + n, f"2026-0{n}-01T17:00:00+00:00")
        for n in range(1, 8)
    ]
    future = race("2026-08", 30, "2026-10-21T17:00:00+00:00")  # ended a day before
    v1 = {
        "splits": {"train": ["2024-01"]},
        "races": {"2024-01": old},
        "splits_sha256": "x",
    }
    monkeypatch.setattr(rebuild_data, "load_splits", lambda: v1)
    monkeypatch.setattr(
        rebuild_data,
        "season_races",
        lambda s: {2024: [old], 2026: [*new, future]}.get(s, []),
    )
    monkeypatch.setattr(rebuild_data, "SPLITS_V2_FILE", tmp_path / "splits-v2.json")
    assert rebuild_data.main(["splits-v2"]) == 0
    document = load_splits(tmp_path / "splits-v2.json")
    assert document["splits"]["train"] == ["2024-01", "2026-01"]
    assert document["splits"]["test_2026"] == ["2026-05", "2026-06", "2026-07"]
    assert "2026-08" not in document["races"]
    assert rebuild_data.main(["splits-v2"]) == 1  # frozen


def test_gap_differences_compare_with_the_interval_just_after_the_crossing() -> None:
    from scripts.rebuild_data import gap_differences

    laps = table(pits={})
    crossing = laps.set_index(["driver_number", "lap"])["at_line"][("2", 19)]
    intervals = [
        {
            "driver_number": 2,
            "date": (crossing + pd.Timedelta(seconds=2)).isoformat(),
            "interval": 3.2,
        },
        {
            "driver_number": 2,
            "date": (crossing - pd.Timedelta(seconds=2)).isoformat(),
            "interval": 9.0,
        },
        {"driver_number": 3, "date": crossing.isoformat(), "interval": "+1 LAP"},
    ]
    differences = gap_differences(laps[laps["lap"] <= 21], RACE, intervals)
    assert [round(d, 1) for d in differences] == [0.2]
