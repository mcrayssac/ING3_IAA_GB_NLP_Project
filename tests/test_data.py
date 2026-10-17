"""Offline tests for M2.1 (no network): synthetic FastF1-shaped laps tables.

The synthetic race below is a FIXTURE, not real timing data.
"""

import json

import pandas as pd
import pytest

from boxbox import data as D

TD = pd.Timedelta
META = {"season": 2099, "round": 1, "event": "Fixture Grand Prix", "total_laps": 12, "fastf1_version": "fixture"}
FRACTIONS = {"train": 0.7, "validation": 0.1, "mini_test": 0.1, "final": 0.1}


def make_laps(n_laps=12, pit=None, status=None, overrides=None):
    """Four cars, base pace 90 s + per-car offset; pit = {driver: in_lap} adds 22 s loss."""
    pit = pit or {}
    status = status or {}
    overrides = overrides or {}
    rows = []
    for k, drv in enumerate(["AAA", "BBB", "CCC", "DDD"]):
        t = 0.0
        stint, life = 1, 0
        for lap in range(1, n_laps + 1):
            life += 1
            lt = 90.0 + 0.5 * k + 0.05 * life
            pin = pout = pd.NaT
            if pit.get(drv) == lap:
                lt += 12.0
                pin = TD(t + lt - 5, unit='s')
            if pit.get(drv) is not None and pit[drv] + 1 == lap:
                lt += 10.0
                pout = TD(t + 5, unit='s')
                stint, life = 2, 1
            t += lt
            row = {
                "Driver": drv,
                "Team": f"Team {drv}",
                "LapNumber": float(lap),
                "LapTime": TD(lt, unit='s'),
                "Time": TD(t, unit='s'),
                "PitInTime": pin,
                "PitOutTime": pout,
                "Compound": "MEDIUM" if stint == 1 else "HARD",
                "TyreLife": float(life),
                "Stint": float(stint),
                "TrackStatus": status.get(lap, "1"),
                "Position": float(k + 1),
            }
            row.update(overrides.get((drv, lap), {}))
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- splits

def test_splits_disjoint_complete_and_deterministic():
    races = [f"20{y}-{r:02d}" for y in (23, 24, 25) for r in range(1, 23)]
    a = D.make_splits(races, 2026, FRACTIONS)
    b = D.make_splits(list(reversed(races)), 2026, FRACTIONS)
    assert a == b
    D.check_disjoint(a)
    assert sorted(sum(a.values(), [])) == sorted(races)
    assert all(len(a[n]) >= 5 for n in ("validation", "mini_test", "final"))
    assert D.make_splits(races, 7, FRACTIONS) != a


def test_splits_reject_overlap_and_too_few_races():
    with pytest.raises(ValueError):
        D.check_disjoint({"train": ["2024-01"], "final": ["2024-01"]})
    with pytest.raises(ValueError):
        D.make_splits([f"2024-{i:02d}" for i in range(1, 10)], 1, FRACTIONS)


def test_split_command_refuses_overwrite(tmp_path, monkeypatch):
    import rebuild_data as R

    monkeypatch.setattr(R, "DATA", tmp_path)
    monkeypatch.setattr(R, "SPLITS", tmp_path / "splits.json")
    monkeypatch.setattr(D, "list_races", lambda s: [{"race_id": f"{s}-{i:02d}", "event": f"E{i}"} for i in range(1, 23)])
    args = R.main.__globals__["argparse"].Namespace(seasons=[2023, 2024], seed=1, min_eval_races=5, exclude=None, force=False)
    assert R.cmd_splits(args) == 0
    first = (tmp_path / "splits.json").read_text()
    assert R.cmd_splits(args) == 1
    assert (tmp_path / "splits.json").read_text() == first


# ---------------------------------------------------------------- cards

def test_card_fields_gaps_and_order():
    laps = make_laps()
    card = D.build_card(laps, META, "BBB", 5)
    assert set(D.CARD_FIELDS) <= set(card)
    assert card["position"] == 2 and card["car_ahead"] == "AAA" and card["car_behind"] == "CCC"
    exp_ahead = sum(90.5 + 0.05 * i for i in range(1, 6)) - sum(90.0 + 0.05 * i for i in range(1, 6))
    assert card["gap_ahead_s"] == pytest.approx(exp_ahead, abs=1e-3)
    assert card["compound"] == "MEDIUM" and card["tyre_age_laps"] == 5
    assert card["track_status"] == "GREEN"
    json.dumps(card)  # serialisable


def test_card_is_reproducible():
    laps = make_laps(pit={"AAA": 3, "BBB": 4, "CCC": 5})
    c1 = D.build_card(laps, META, "DDD", 8)
    c2 = D.build_card(make_laps(pit={"AAA": 3, "BBB": 4, "CCC": 5}), META, "DDD", 8)
    assert D.card_fingerprint(c1) == D.card_fingerprint(c2)


def test_no_future_lap_is_used():
    """Changing everything after lap L must not change the card for lap L."""
    base = make_laps(pit={"AAA": 3, "BBB": 4, "CCC": 5})
    future = base.copy()
    late = future["LapNumber"] > 6
    future.loc[late, "LapTime"] = TD(200, unit='s')
    future.loc[late, "Time"] = future.loc[late, "Time"] + TD(999, unit='s')
    future.loc[late, "TrackStatus"] = "4"
    future.loc[(future["Driver"] == "DDD") & (future["LapNumber"] == 9), "PitInTime"] = TD(1, unit='s')
    assert D.build_card(base, META, "DDD", 6) == D.build_card(future, META, "DDD", 6)


def test_pit_loss_uses_only_completed_stops():
    laps = make_laps(pit={"AAA": 4, "BBB": 5, "CCC": 8})
    early = D.build_card(laps, META, "DDD", 7)   # 2 stops done (AAA, BBB)
    assert early["pit_loss_s"] is None and "pit_loss_s" in early["missing"]
    assert early["provenance"]["pit_stops_used"] == 2
    late = D.build_card(laps, META, "DDD", 10)   # 3 stops done
    assert late["pit_loss_s"] == pytest.approx(22.0, abs=0.5)
    assert late["provenance"]["pit_stops_used"] == 3


def test_stop_under_safety_car_is_not_used_for_pit_loss():
    laps = make_laps(pit={"AAA": 4, "BBB": 5, "CCC": 6}, status={5: "41"})
    card = D.build_card(laps, META, "DDD", 9)
    assert card["provenance"]["pit_stops_used"] == 1  # BBB in-lap and AAA out-lap under SC
    assert card["pit_loss_s"] is None


def test_missing_value_is_traced_not_invented():
    laps = make_laps(overrides={("BBB", 5): {"TyreLife": float("nan"), "Compound": None}})
    card = D.build_card(laps, META, "BBB", 5)
    assert card["tyre_age_laps"] is None and card["compound"] is None
    assert "tyre_age_laps" in card["missing"] and "compound" in card["missing"]


def test_leader_and_last_car_have_explicit_missing_gap():
    laps = make_laps()
    lead = D.build_card(laps, META, "AAA", 5)
    last = D.build_card(laps, META, "DDD", 5)
    assert lead["gap_ahead_s"] is None and "gap_ahead_s" in lead["missing"]
    assert last["gap_behind_s"] is None and "gap_behind_s" in last["missing"]


@pytest.mark.parametrize("code,label", [("1", "GREEN"), ("12", "YELLOW"), ("14", "SC"), ("167", "VSC"), ("15", "RED"), (None, None)])
def test_track_status_labels(code, label):
    assert D.track_status_label(code) == label


def test_ineligible_situations():
    laps = make_laps(pit={"AAA": 4}, status={7: "15"},
                     overrides={("CCC", 9): {"Compound": "INTERMEDIATE"}})
    for drv, lap in [("BBB", 1), ("BBB", 12), ("AAA", 4), ("AAA", 5), ("BBB", 7), ("CCC", 10)]:
        with pytest.raises(D.CardNotEligible):
            D.build_card(laps, META, drv, lap)
    cards, skipped = D.build_race_cards(laps, META)
    assert cards and sum(skipped.values()) > 0
    assert [c["card_id"] for c in cards] == sorted(c["card_id"] for c in cards)


def test_fetch_error_is_explicit(monkeypatch, tmp_path):
    import fastf1

    def boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(fastf1, "get_session", boom)
    with pytest.raises(D.DataUnavailableError, match="network down"):
        D.load_race(2024, 1, tmp_path / "cache")
