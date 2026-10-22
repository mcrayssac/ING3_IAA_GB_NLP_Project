"""Open-Meteo archived forecast at a circuit, for the replay's weather panel only.

The Historical Forecast API stitches the first hours of each weather-model run into
one series in 15-minute steps, so it is close to the weather that came, not exactly
the forecast a team saw live. No card or call reads it. Weather data by
Open-Meteo.com, CC BY 4.0.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from . import openf1
from .openf1 import JOLPICA, DataUnavailableError, fetch_json

FORECAST = "https://historical-forecast-api.open-meteo.com/v1/forecast"
CACHE_DIR = Path("data/cache/open-meteo")
VARIABLES = "temperature_2m,precipitation,rain,weather_code,wind_speed_10m,is_day"
HORIZONS = (5, 15, 30)  # minutes ahead shown on the panel
TIMEOUT = 10.0  # seconds: a cut network must not hold a race pick for a minute


def circuit_location(
    race: dict[str, Any], cache_dir: Path = openf1.CACHE_DIR
) -> tuple[float, float]:
    """Latitude and longitude of the race's circuit from the Jolpica schedule, matched
    by date, since the 2026 rounds were renumbered after two cancellations."""
    season = race["season"]
    schedule = fetch_json(
        f"{JOLPICA}/{season}.json?limit=100", cache_dir / f"jolpica_{season}.json"
    )
    day = date.fromisoformat(race["date_end"][:10])
    for official in schedule["MRData"]["RaceTable"]["Races"]:
        if abs((date.fromisoformat(official["date"]) - day).days) <= 1:
            where = official["Circuit"]["Location"]
            return float(where["lat"]), float(where["long"])
    raise DataUnavailableError(f"{race['race_id']}: no circuit in the schedule")


def load_forecast(
    race: dict[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache_dir: Path = CACHE_DIR,
    openf1_cache: Path = openf1.CACHE_DIR,
) -> pd.DataFrame | None:
    """The 15-minute steps from an hour before the start to an hour after the end,
    through the disk cache; None when they cannot be had, so the replay still runs."""
    try:
        lat, lon = circuit_location(race, openf1_cache)
        first = (start - pd.Timedelta(hours=1)).floor("15min")
        last = (end + pd.Timedelta(hours=1)).ceil("15min")
        url = (
            f"{FORECAST}?latitude={lat}&longitude={lon}&minutely_15={VARIABLES}"
            f"&start_minutely_15={first:%Y-%m-%dT%H:%M}"
            f"&end_minutely_15={last:%Y-%m-%dT%H:%M}&timezone=GMT&wind_speed_unit=ms"
        )
        body = fetch_json(url, cache_dir / f"{race['race_id']}.json", timeout=TIMEOUT)
        steps = pd.DataFrame(body["minutely_15"])
        steps["at"] = pd.to_datetime(steps.pop("time"), utc=True)
        return steps
    except (DataUnavailableError, KeyError, ValueError):
        return None


def forecast_at(
    steps: pd.DataFrame | None, at: pd.Timestamp, minutes: tuple[int, ...] = HORIZONS
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The step under way at `at`, for the sky now, and for each horizon the nearest
    step strictly after `at`. A step serves one horizon only and keeps its own time."""
    if steps is None or steps.empty:
        return None, []
    past = steps[steps["at"] <= at]
    later = steps[steps["at"] > at]
    ahead, used = [], set()
    for m in minutes:
        if later.empty:
            break
        i = (later["at"] - (at + pd.Timedelta(minutes=m))).abs().idxmin()
        if i not in used:
            used.add(i)
            ahead.append(later.loc[i].to_dict())
    return (past.iloc[-1].to_dict() if len(past) else None), ahead
