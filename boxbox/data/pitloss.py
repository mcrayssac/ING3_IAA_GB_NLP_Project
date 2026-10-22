"""Pit loss per track condition: what each stop cost, and the value a card can use.

A stop costs its in-lap plus out-lap, minus the median in-lap plus out-lap of the cars
that did not stop on those two laps, minus the penalty seconds served at the stop.
Comparing with the field on the same laps works under green, SC, VSC and rain alike.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any

import pandas as pd

WET_COMPOUNDS = {"INTERMEDIATE", "WET"}
CONDITIONS = ("GREEN", "SC", "VSC", "WET")
LOSS_BOUNDS = (3.0, 60.0)  # data-cleaning bounds; a stop under a SC can cost ~10 s
RECENT, MIN_STOPS = 5, 3  # the last 5 stops of a condition, at least 3
MIN_FREE = 3  # cars that did not stop, for the comparison laps of a stop
DECIMALS = 1
TIME_PENALTY = re.compile(r"(\d+) SECOND TIME PENALTY FOR CAR (\d{1,2})\b")


def penalty_awards(
    messages: list[dict[str, Any]],
) -> list[tuple[pd.Timestamp, str, int]]:
    """(time, car, seconds) of each time penalty the stewards award during the race."""
    awards = []
    for message in messages:
        text = (message.get("message") or "").upper()
        found = TIME_PENALTY.search(text)
        # "PENALTY SERVED - 10 SECOND TIME PENALTY FOR CAR 23" is not an award
        if found and "SERVED" not in text:
            awards.append(
                (pd.Timestamp(message["date"]), found.group(2), int(found.group(1)))
            )
    return awards


def pending_penalty(
    awards: list[tuple[pd.Timestamp, str, int]],
    stop_times: list[pd.Timestamp],
    driver: str,
    at: pd.Timestamp,
) -> int:
    """Penalty seconds awarded to `driver` by `at` and not served at a stop before it."""
    served_until = max((t for t in stop_times if t < at), default=None)
    return sum(
        seconds
        for when, car, seconds in awards
        if car == driver
        and when <= at
        and (served_until is None or when > served_until)
    )


def condition(in_lap: pd.Series, out_lap: pd.Series) -> str | None:
    """GREEN, SC, VSC or WET for one stop; None for a red-flag or mixed stop."""
    status = in_lap["pit_status"]
    if status in ("SC", "VSC"):
        return status
    if status != "GREEN" or out_lap["neutralised_in_lap"]:
        return None  # a red flag, or a SC that came out during the out-lap
    tyres = {in_lap["compound"], out_lap["compound"]}
    return "WET" if tyres & WET_COMPOUNDS else "GREEN"


def _field_pairs(table: pd.DataFrame) -> dict[int, tuple[float, pd.Timestamp]]:
    """Per in-lap number: median in-lap + out-lap time of the cars that did not stop,
    and when the last of those laps ends, since a stop is only known after it."""
    seconds = table.pivot(index="driver_number", columns="lap", values="lap_seconds")
    ends = table.pivot(index="driver_number", columns="lap", values="at_line")
    busy = table.assign(busy=table["pit_in"] | table["pit_out"]).pivot(
        index="driver_number", columns="lap", values="busy"
    )
    pairs = {}
    for lap in seconds.columns:
        if lap + 1 not in seconds.columns:
            continue
        free = ~(
            busy[lap].fillna(True).astype(bool)
            | busy[lap + 1].fillna(True).astype(bool)
        )
        both = (seconds[lap] + seconds[lap + 1])[free].dropna()
        # one or two cars still running are not a field (Monaco 2026, lap 59)
        if len(both) >= MIN_FREE:
            pairs[lap] = (float(both.median()), ends[lap + 1][both.index].max())
    return pairs


_COLUMNS = [
    "driver_number",
    "in_lap",
    "condition",
    "loss",
    "penalty_served",
    "known_at",
    "lane_seconds",
]


def stop_losses(table: pd.DataFrame, messages: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per usable stop: driver, in-lap, condition, loss and when it is known."""
    rows = table.set_index(["driver_number", "lap"])
    pairs = _field_pairs(table)
    awards = penalty_awards(messages)
    stops = table[table["pit_in"]]
    times = stops.groupby("driver_number")["at_line"].apply(list).to_dict()
    losses = []
    for _, stop in stops.iterrows():
        key = (stop["driver_number"], stop["lap"] + 1)
        if key not in rows.index or not rows.loc[key, "pit_out"]:
            continue
        out = rows.loc[key]
        kind = condition(stop, out)
        own = stop["lap_seconds"] + out["lap_seconds"]
        if kind is None or pd.isna(own) or stop["lap"] not in pairs:
            continue
        served = pending_penalty(
            awards, times[stop["driver_number"]], stop["driver_number"], stop["at_line"]
        )
        field, field_known = pairs[stop["lap"]]
        loss = own - field - served
        if LOSS_BOUNDS[0] <= loss <= LOSS_BOUNDS[1]:
            losses.append(
                {
                    "driver_number": stop["driver_number"],
                    "in_lap": int(stop["lap"]),
                    "condition": kind,
                    "loss": float(loss),
                    "penalty_served": served,
                    "known_at": max(out["at_line"], field_known),
                    "lane_seconds": stop["lane_seconds"],
                }
            )
    return pd.DataFrame(losses, columns=_COLUMNS)


def race_estimate(
    losses: pd.DataFrame, kind: str, known_by: pd.Timestamp
) -> tuple[float | None, int | None, int]:
    """Median of the last stops of one condition known by `known_by`.

    Returns (seconds, latest out-lap used, stops used); seconds is None with fewer than
    three stops.
    """
    usable = losses[(losses["condition"] == kind) & (losses["known_at"] <= known_by)]
    recent = usable.sort_values("known_at").tail(RECENT)
    if len(recent) < MIN_STOPS:
        return None, None, len(recent)
    value = round(float(median(recent["loss"])), DECIMALS)
    return value, int(recent["in_lap"].max()) + 1, len(recent)
