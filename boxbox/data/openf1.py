"""OpenF1 loader: one historical race becomes the shared per-lap table.

Jolpica gives the official round number and event name. Every response is cached
on disk, so a rebuild from the cache needs no network.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

OPENF1 = "https://api.openf1.org/v1"
JOLPICA = "https://api.jolpi.ca/ergast/f1"
CACHE_DIR = Path("data/cache/openf1")
PAUSE_SECONDS = 2.1  # free OpenF1 access allows 30 requests per minute
RETRIES = 3


class DataUnavailableError(RuntimeError):
    """A source could not be reached or returned unusable data."""


def _download(url: str, empty_on_404: bool) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "boxbox-rebuild"})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404 and empty_on_404:  # OpenF1's answer for "no results"
                return b"[]"
            if error.code != 429 or attempt == RETRIES - 1:
                raise DataUnavailableError(f"{url}: HTTP {error.code}") from error
            time.sleep(60)
        except (
            OSError,
            http.client.HTTPException,
        ) as error:  # resets, timeouts, cut reads
            raise DataUnavailableError(f"{url}: {error!r}") from error
    raise DataUnavailableError(url)


def fetch_json(url: str, cache_file: Path, empty_on_404: bool = False) -> Any:
    """Read `url` through the disk cache; a failure raises and caches nothing."""
    if not cache_file.exists():
        body = _download(url, empty_on_404)
        time.sleep(PAUSE_SECONDS)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(body)
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DataUnavailableError(f"{cache_file}: invalid JSON") from error


def season_races(season: int, cache_dir: Path = CACHE_DIR) -> list[dict[str, Any]]:
    """Races of a season that OpenF1 covers, with Jolpica's round and event name."""
    schedule = fetch_json(
        f"{JOLPICA}/{season}.json?limit=100", cache_dir / f"jolpica_{season}.json"
    )
    sessions = fetch_json(
        f"{OPENF1}/sessions?year={season}&session_name=Race",
        cache_dir / f"sessions_{season}.json",
    )
    races = []
    for official in schedule["MRData"]["RaceTable"]["Races"]:
        day = date.fromisoformat(official["date"])
        matches = [
            s
            for s in sessions
            if not s.get("is_cancelled")
            and abs((date.fromisoformat(s["date_start"][:10]) - day).days) <= 1
        ]
        round_number = int(official["round"])
        if len(matches) != 1:  # a local race date can be the next day in UTC
            raise DataUnavailableError(
                f"{season} round {round_number}: {len(matches)} OpenF1 Race sessions"
            )
        races.append(
            {
                "race_id": f"{season}-{round_number:02d}",
                "season": season,
                "round": round_number,
                "event": official["raceName"],
                "session_key": matches[0]["session_key"],
            }
        )
    return races


ENDPOINTS = ("laps", "stints", "pit", "race_control")


def raw_sha256(race: dict[str, Any], cache_dir: Path = CACHE_DIR) -> dict[str, str]:
    """SHA-256 of each cached OpenF1 response of a race, to detect source revisions."""
    folder = cache_dir / str(race["session_key"])
    return {
        name: hashlib.sha256((folder / f"{name}.json").read_bytes()).hexdigest()
        for name in ENDPOINTS
    }


def _endpoint(name: str, session_key: int, cache_dir: Path) -> list[dict[str, Any]]:
    url = f"{OPENF1}/{name}?session_key={session_key}"
    # only the pit endpoint may be empty: it is for 2023 rounds 1 to 6
    empty = name == "pit"
    return fetch_json(url, cache_dir / str(session_key) / f"{name}.json", empty)


def lap_status(messages: list[dict[str, Any]], total_laps: int) -> dict[int, str]:
    """Track status at the end of each lap from race-control messages.

    SC and VSC run from the lap they are deployed until the lap they come in, so the
    end of that last lap is green again. A red flag marks its lap and ends any SC or
    VSC, which gets no "in this lap" message then. Sector yellow flags do not
    neutralise the race, so they stay GREEN.
    """
    if not messages:
        raise DataUnavailableError("no race-control messages, so no track status")
    status = {lap: "GREEN" for lap in range(1, total_laps + 1)}
    started: dict[str, int] = {}
    red_laps = []
    for message in sorted(messages, key=lambda m: m["date"]):
        text, lap = (message.get("message") or "").upper(), message.get("lap_number")
        if lap is None:
            if "SAFETY CAR" in text or message.get("flag") == "RED":
                raise DataUnavailableError(
                    f"race-control message without a lap: {text}"
                )
            continue
        kind = "VSC" if "VIRTUAL" in text else "SC"
        if "SAFETY CAR DEPLOYED" in text:
            started[kind] = lap
        elif ("SAFETY CAR ENDING" in text or "IN THIS LAP" in text) and kind in started:
            status.update(dict.fromkeys(range(started.pop(kind), lap), kind))
        elif message.get("flag") == "RED" and message.get("scope") == "Track":
            for open_kind, first in started.items():
                status.update(dict.fromkeys(range(first, lap), open_kind))
            started.clear()
            red_laps.append(lap)
    for kind, first in started.items():
        status.update(dict.fromkeys(range(first, total_laps + 1), kind))
    status.update(dict.fromkeys(red_laps, "RED"))
    return status


def _tyres(
    stints: list[dict[str, Any]], driver: int, lap: int
) -> tuple[str | None, int | None]:
    """Compound and age at the end of `lap`; a stint without bounds is unknown."""
    current = [
        s
        for s in stints
        if s["driver_number"] == driver
        and s.get("lap_start") is not None
        and s["lap_start"] <= lap
        and (s.get("lap_end") is None or lap <= s["lap_end"])
    ]
    if not current:
        return None, None
    stint = max(
        current, key=lambda s: s["lap_start"]
    )  # a stint left open ends at the next one
    start_age = stint.get("tyre_age_at_start")
    age = None if start_age is None else start_age + lap - stint["lap_start"] + 1
    return stint.get("compound"), age


def race_table(race: dict[str, Any], cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """One row per driver and lap with the columns every loader returns."""
    key = race["session_key"]
    laps = pd.DataFrame(_endpoint("laps", key, cache_dir))
    if laps.empty:
        raise DataUnavailableError(f"session {key}: no laps")
    stints = _endpoint("stints", key, cache_dir)
    pits = {
        (p["driver_number"], p["lap_number"]) for p in _endpoint("pit", key, cache_dir)
    }
    # the pit endpoint is empty for some 2023 races, so a lap followed by an out-lap
    # is an in-lap too; the car is in the pit lane when that lap ends
    pits |= {
        (driver, lap - 1)
        for driver, lap, out in zip(
            laps["driver_number"], laps["lap_number"], laps["is_pit_out_lap"]
        )
        if out
    }
    status = lap_status(
        _endpoint("race_control", key, cache_dir), int(laps["lap_number"].max())
    )
    laps = laps.sort_values(["driver_number", "lap_number"])
    return pd.DataFrame(_rows(laps, _line_times(laps), stints, pits, status))


def _line_times(laps: pd.DataFrame) -> pd.Series:
    """Seconds from the race start to the end of each lap, at the timing line.

    The next lap's start is the line crossing itself, so it is used whenever the next
    lap exists; the last lap falls back to start + duration. Both agree with OpenF1's
    official gap to the leader within 0.07 s (median, 38 laps of Bahrain 2024).
    """
    start = pd.to_datetime(laps["date_start"], utc=True, format="ISO8601")
    by_driver = laps.groupby("driver_number")
    is_next = by_driver["lap_number"].shift(-1) == laps["lap_number"] + 1
    next_start = start.groupby(laps["driver_number"]).shift(-1).where(is_next)
    finish = start + pd.to_timedelta(laps["lap_duration"], unit="s")
    return (next_start.fillna(finish) - start.min()).dt.total_seconds()


def _rows(laps, line_times, stints, pits, status) -> list[dict[str, Any]]:
    rows = []
    for (_, lap), end in zip(laps.iterrows(), line_times):
        compound, age = _tyres(stints, lap["driver_number"], lap["lap_number"])
        rows.append(
            {
                "driver_number": str(lap["driver_number"]),
                "lap": int(lap["lap_number"]),
                "lap_seconds": lap["lap_duration"],
                "end_s": None if pd.isna(end) else float(end),
                "pit_in": (lap["driver_number"], lap["lap_number"]) in pits,
                "pit_out": bool(lap["is_pit_out_lap"]),
                "compound": compound,
                "tyre_age_end": age,
                "status": status.get(int(lap["lap_number"]), "GREEN"),
            }
        )
    return rows
