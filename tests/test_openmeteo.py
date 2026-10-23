"""The archived forecast: read through the cache, quiet on failure, never at the clock."""

from __future__ import annotations

import json

import pandas as pd

from boxbox.data import openf1
from boxbox.data.openmeteo import forecast_at, load_forecast

RACE = {"race_id": "2024-02", "season": 2024, "date_end": "2024-03-09T19:00:00+00:00"}
START = pd.Timestamp("2024-03-09T17:00:00Z")


def steps(*minutes: int) -> pd.DataFrame:
    """Forecast steps at START plus each number of minutes."""
    at = [START + pd.Timedelta(minutes=m) for m in minutes]
    return pd.DataFrame({"at": at, "weather_code": range(len(at))})


def test_the_forecast_is_read_through_the_cache_and_fails_quietly(
    monkeypatch, tmp_path
) -> None:
    schedule = {
        "MRData": {
            "RaceTable": {
                "Races": [
                    {
                        "date": "2024-03-09",
                        "Circuit": {"Location": {"lat": "21.6319", "long": "39.1044"}},
                    }
                ]
            }
        }
    }
    (tmp_path / "jolpica_2024.json").write_text(json.dumps(schedule), encoding="utf-8")
    cache = tmp_path / "open-meteo"
    cache.mkdir()
    body = {
        "minutely_15": {
            "time": ["2024-03-09T16:00", "2024-03-09T16:15"],
            "temperature_2m": [27.1, 26.8],
            "weather_code": [0, 1],
        }
    }
    (cache / "2024-02.json").write_text(json.dumps(body), encoding="utf-8")

    def offline(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(openf1.urllib.request, "urlopen", offline)
    end = START + pd.Timedelta(hours=2)
    forecast = load_forecast(RACE, START, end, cache, tmp_path)
    assert list(forecast["at"]) == list(
        pd.to_datetime(["2024-03-09T16:00Z", "2024-03-09T16:15Z"])
    )
    assert list(forecast["temperature_2m"]) == [27.1, 26.8]
    (cache / "2024-02.json").unlink()
    assert load_forecast(RACE, START, end, cache, tmp_path) is None  # no cache, no net
    assert (
        load_forecast({**RACE, "date_end": "2024-06-01"}, START, end, cache, tmp_path)
        is None
    )


def test_forecast_steps_come_strictly_after_the_clock() -> None:
    series = steps(0, 15, 30, 45)  # 17:00 to 17:45
    at = START + pd.Timedelta(minutes=15)  # on the 17:15 step
    now, ahead = forecast_at(series, at)
    assert now["at"] == at
    # +5 and +15 both land on 17:30, which serves once; 17:15 is never a forecast
    assert [s["at"].strftime("%H:%M") for s in ahead] == ["17:30", "17:45"]
    _, ahead = forecast_at(series, at - pd.Timedelta(minutes=1))
    assert [s["at"].strftime("%H:%M") for s in ahead] == ["17:15", "17:30", "17:45"]
    assert forecast_at(series, START + pd.Timedelta(minutes=50))[1] == []
    assert forecast_at(None, at) == (None, [])
