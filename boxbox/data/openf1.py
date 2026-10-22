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


def _download(url: str, empty_on_404: bool, timeout: float = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "boxbox-rebuild"})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
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


def fetch_json(
    url: str, cache_file: Path, empty_on_404: bool = False, timeout: float = 60
) -> Any:
    """Read `url` through the disk cache; a failure raises and caches nothing."""
    if not cache_file.exists():
        body = _download(url, empty_on_404, timeout)
        time.sleep(PAUSE_SECONDS)
        if body.strip() == b"[]" and not empty_on_404:  # a race not loaded yet
            raise DataUnavailableError(f"{url}: empty response")
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
                # event names change (the Spanish GP moved to Madrid in 2026)
                "circuit_key": matches[0].get("circuit_key"),
                "date_end": matches[0].get("date_end"),
            }
        )
    return races


ENDPOINTS = ("laps", "stints", "pit", "race_control")
EXTRAS = ("weather", "drivers")
ENDPOINTS_V2 = ENDPOINTS + EXTRAS


def raw_sha256(
    race: dict[str, Any], cache_dir: Path = CACHE_DIR, names=ENDPOINTS
) -> dict[str, str]:
    """SHA-256 of each cached OpenF1 response of a race, to detect source revisions."""
    folder = cache_dir / str(race["session_key"])
    return {
        name: hashlib.sha256((folder / f"{name}.json").read_bytes()).hexdigest()
        for name in names
    }


def race_control(race: dict[str, Any], cache_dir: Path = CACHE_DIR) -> list[dict]:
    """Race-control messages of a race, through the disk cache."""
    return _endpoint("race_control", race["session_key"], cache_dir)


def race_extras(
    race: dict[str, Any], cache_dir: Path = CACHE_DIR, intervals: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """Weather and drivers of a race, plus OpenF1 intervals for the gap check."""
    names = (*EXTRAS, "intervals") if intervals else EXTRAS
    return {name: _endpoint(name, race["session_key"], cache_dir) for name in names}


def _endpoint(name: str, session_key: int, cache_dir: Path) -> list[dict[str, Any]]:
    url = f"{OPENF1}/{name}?session_key={session_key}"
    # only the pit endpoint may be empty: it is for 2023 rounds 1 to 6
    empty = name == "pit"
    return fetch_json(url, cache_dir / str(session_key) / f"{name}.json", empty)


NEUTRAL = ("RED", "SC", "VSC")  # the first active one wins when windows overlap
Window = tuple[str, pd.Timestamp, pd.Timestamp | None]


def _when(message: dict[str, Any]) -> pd.Timestamp:
    return pd.Timestamp(message["date"])


def _event(message: dict[str, Any]) -> tuple[str | None, str | None]:
    """(kind, action) a race-control message carries for track status, if any."""
    text = (message.get("message") or "").upper()
    if text.startswith("VSC "):  # 2026 writes "VSC DEPLOYED" and "VSC ENDING"
        text = "VIRTUAL SAFETY CAR " + text[4:]
    # 2026 messages read "RED FLAG - RACE SUSPENDED" with no flag field
    if message.get("flag") == "RED" and message.get("scope") == "Track":
        return "RED", "open"
    if text.startswith("RED FLAG"):
        return "RED", "open"
    if "SAFETY CAR DEPLOYED" in text:
        return ("VSC" if "VIRTUAL" in text else "SC"), "open"
    if "SAFETY CAR ENDING" in text or "IN THIS LAP" in text:
        return ("VSC" if "VIRTUAL" in text else "SC"), "ending"
    if "SAFETY CAR WILL ENTER PITS" in text or text == "ROLLING START":
        return "SC", "rolling start"
    if any(
        cue in text
        for cue in ("BEHIND THE SAFETY CAR", "ROLLING START PROCEDURE", "WILL STAY OUT")
    ):
        return "SC", "start behind"
    if text == "TRACK CLEAR":
        return None, "clear"
    if text == "SESSION STARTED":
        return None, "started"
    if message.get("flag") == "CHEQUERED" or text == "SESSION FINISHED":
        return None, "finished"
    return None, None


def _order(message: dict[str, Any]) -> tuple[pd.Timestamp, bool]:
    # a red flag sent in the same second as a SC deployment ends that SC
    return _when(message), _event(message)[0] == "RED"


def track_windows(
    messages: list[dict[str, Any]], crossings: list[pd.Timestamp] = ()
) -> list[Window]:
    """Neutralisation windows (kind, start, end) from race-control timestamps.

    A SC or VSC ends at the first "TRACK CLEAR" after its "IN THIS LAP" or "ENDING"
    message. A SC deployed during a VSC ends the VSC. A red flag ends both and lasts
    until the race resumes ("SESSION STARTED"); in 2026 its "TRACK CLEAR" comes minutes
    before that. A restart behind the SC runs from "SESSION STARTED" to the next line
    crossing after the SC enters the pits. Messages after
    the chequered flag are ignored, so a race that ends neutralised keeps its status.
    """
    if not messages:
        raise DataUnavailableError("no race-control messages, so no track status")
    windows: list[Window] = []
    opened: dict[str, pd.Timestamp] = {}
    ending: set[str] = set()
    behind = False

    def close(kinds, at: pd.Timestamp) -> None:
        for kind in kinds:
            if kind in opened:
                windows.append((kind, opened.pop(kind), at))
            ending.discard(kind)

    for message in sorted(messages, key=_order):
        (kind, action), at = _event(message), _when(message)
        if action == "finished":
            break
        if action == "open":
            if kind == "RED":
                close(("SC", "VSC"), at)
            elif kind == "SC":
                close(("VSC",), at)
            opened.setdefault(kind, at)
        elif action == "ending" and kind in opened:
            ending.add(kind)
        elif action == "clear":
            close(set(ending), at)
        elif action == "rolling start":
            close(("SC",), _next_crossing(crossings, at))
        elif action == "start behind":
            behind = True
        elif action == "started":
            close(("RED",), at)
            if behind:
                opened.setdefault("SC", at)
                behind = False
    return windows + [(kind, start, None) for kind, start in opened.items()]


def _next_crossing(crossings: list[pd.Timestamp], at: pd.Timestamp) -> pd.Timestamp:
    later = [crossing for crossing in crossings if crossing > at]
    return min(later) if later else at


def status_at(windows: list[Window], at: pd.Timestamp) -> str:
    """Track status at one instant: RED, then SC, then VSC, otherwise GREEN."""
    active = {
        k for k, start, end in windows if start <= at and (end is None or at < end)
    }
    return next((kind for kind in NEUTRAL if kind in active), "GREEN")


def neutralised_between(
    windows: list[Window], first: pd.Timestamp, last: pd.Timestamp
) -> bool:
    """Whether any SC, VSC or red flag overlaps the interval from first to last."""
    return any(
        start < last and (end is None or end > first) for _, start, end in windows
    )


def chequered_at(messages: list[dict[str, Any]]) -> pd.Timestamp | None:
    """The chequered flag, or the session end when the flag is missing (2023-14)."""
    flags = [_when(m) for m in messages if m.get("flag") == "CHEQUERED"]
    flags = flags or [_when(m) for m in messages if _event(m)[1] == "finished"]
    return min(flags) if flags else None


def _raced(
    laps: pd.DataFrame, start: pd.Series, flag: pd.Timestamp | None
) -> pd.Series:
    """Rows of laps started before the leader took the chequered flag.

    The flag message comes within about 5 s of the leader's crossing, so a lap number
    first started from 5 s before the message is the leader's lap after the flag
    (2023-02 has a lap 51 in a 50-lap race) and its start is the real flag time.
    """
    if flag is None:
        return pd.Series(True, index=laps.index)
    first = start.groupby(laps["lap_number"]).transform("min")
    late = start[first >= flag - pd.Timedelta(seconds=5)]
    flag = min(late.min(), flag) if len(late) else flag
    return start.isna() | (start < flag)


def _tyres(
    stints: list[dict[str, Any]], driver: int, lap: int, in_lap: bool = False
) -> tuple[str | None, int | None]:
    """Compound and age at the end of `lap`; a stint without bounds is unknown.

    OpenF1 often starts the new stint on the in-lap, but the car still runs the old
    set on it, so an in-lap reads the earlier stint.
    """
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
    pick = min if in_lap else max  # otherwise a stint left open ends at the next one
    stint = pick(current, key=lambda s: s["lap_start"])
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
    stops = {
        (p["driver_number"], p["lap_number"]): p
        for p in _endpoint("pit", key, cache_dir)
    }
    pits = set(stops)
    # the pit endpoint is empty for some 2023 races, so a lap followed by an out-lap
    # is an in-lap too; the car is in the pit lane when that lap ends
    pits |= {
        (driver, lap - 1)
        for driver, lap, out in zip(
            laps["driver_number"], laps["lap_number"], laps["is_pit_out_lap"]
        )
        if out
    }
    messages = _endpoint("race_control", key, cache_dir)
    laps = laps.sort_values(["driver_number", "lap_number"])
    start = pd.to_datetime(laps["date_start"], utc=True, format="ISO8601")
    ends = _line_times(laps)
    status = _status_columns(laps, start, ends, messages, stops)
    keep = _raced(laps, start, chequered_at(messages))
    rows = _rows(laps[keep], ends[keep], stints, pits, status.loc[keep])
    table = pd.DataFrame(rows)
    lane = {(str(d), lap): p.get("lane_duration") for (d, lap), p in stops.items()}
    table["lane_seconds"] = [
        lane.get(k) for k in zip(table["driver_number"], table["lap"])
    ]
    return table


def _status_columns(
    laps: pd.DataFrame, start: pd.Series, ends: pd.Series, messages: list, stops: dict
) -> pd.DataFrame:
    """Per lap: the status at the line, any neutralisation, the crossing time, and the
    status when the car enters the pit lane, read from the pit endpoint's timestamp."""
    at_line = start.min() + pd.to_timedelta(ends, unit="s")
    windows = track_windows(messages, sorted(at_line.dropna()))
    # after a lap-1 red flag OpenF1 dates lap 1 from the restart, after its crossing
    begin = start.where(start < at_line)
    begin = begin.fillna(at_line - pd.to_timedelta(laps["lap_duration"], unit="s"))
    status = ["UNKNOWN" if pd.isna(at) else status_at(windows, at) for at in at_line]
    neutralised = [
        state != "GREEN" or neutralised_between(windows, first, at)
        for state, first, at in zip(status, begin.fillna(at_line), at_line)
    ]
    pit_status = [
        status_at(windows, pd.Timestamp(stops[key]["date"]))
        if key in stops and stops[key].get("date")
        else None
        for key in zip(laps["driver_number"], laps["lap_number"])
    ]
    return pd.DataFrame(
        {
            "status": status,
            "neutralised_in_lap": neutralised,
            "at_line": at_line,
            "pit_status": pit_status,
        },
        index=laps.index,
    )


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
    for (_, lap), end, (state, neutralised, at_line, pit_status) in zip(
        laps.iterrows(), line_times, status.itertuples(index=False)
    ):
        pit_in = (lap["driver_number"], lap["lap_number"]) in pits
        compound, age = _tyres(stints, lap["driver_number"], lap["lap_number"], pit_in)
        rows.append(
            {
                "driver_number": str(lap["driver_number"]),
                "lap": int(lap["lap_number"]),
                "lap_seconds": lap["lap_duration"],
                "end_s": None if pd.isna(end) else float(end),
                "pit_in": pit_in,
                "pit_out": bool(lap["is_pit_out_lap"]),
                "compound": compound,
                "tyre_age_end": age,
                "status": state,
                "neutralised_in_lap": bool(neutralised),
                "at_line": at_line,
                # without a pit timestamp (2023 rounds 1 to 6) the line status stands in
                "pit_status": (pit_status or state) if pit_in else None,
            }
        )
    return rows
