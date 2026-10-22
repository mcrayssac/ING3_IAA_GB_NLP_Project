"""Priors from earlier train races: pit loss per condition and tyre degradation.

A card only uses train races that ended before its own race, so a prior never comes
from the race itself, from a later race or from an evaluation race.
"""

from __future__ import annotations

import csv
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from .pitloss import MIN_STOPS, stop_losses
from .tyres import RELIABLE_SE, clean_dry_laps, degradation

PRIORS_FILE = Path("data/reference/priors-v2.json")
REFERENCE_FILE = Path("data/reference/pit-loss-reference.csv")
NEW_ERA = 2026  # new cars and narrower tyres
MIN_ERA_RACES = 3


def race_summary(
    race: dict[str, Any], table: pd.DataFrame, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """What one train race teaches: pit loss per condition and degradation slopes."""
    losses = stop_losses(table, messages)
    slopes = {
        compound: round(fit["b"], 4)
        for compound, fit in degradation(clean_dry_laps(table)).items()
        if fit["se"] < RELIABLE_SE and fit["b"] > 0  # as for the cards
    }
    return {
        "season": race["season"],
        "circuit_key": race["circuit_key"],
        "date_end": race["date_end"],
        "pit_loss": {
            kind: round(float(group.median()), 2)
            for kind, group in losses.groupby("condition")["loss"]
            if len(group) >= MIN_STOPS
        },
        "degradation": slopes,
    }


def earlier(priors: dict[str, dict[str, Any]], race: dict[str, Any]) -> list[dict]:
    """Summaries of the train races that ended before `race`."""
    return [
        summary
        for race_id, summary in priors.items()
        if race_id != race["race_id"] and summary["date_end"] < race["date_end"]
    ]


def load_reference(path: Path = REFERENCE_FILE) -> dict[int, float]:
    """Published green pit loss for circuits with no history, by `circuit_key`."""
    with path.open(encoding="utf-8") as file:
        return {
            int(r["circuit_key"]): float(r["green_pit_loss_s"])
            for r in csv.DictReader(file)
        }


def condition_ratio(summaries: list[dict], kind: str) -> float | None:
    """Median pit loss of a condition over the green one, across train races.

    It is a model constant learned on every train race, like the wear limits: a few
    early races alone are too noisy (Saudi Arabia 2023 alone gives a SC stop dearer
    than a green one)."""
    if kind == "GREEN":
        return 1.0
    ratios = [
        s["pit_loss"][kind] / s["pit_loss"]["GREEN"]
        for s in summaries
        if kind in s["pit_loss"] and "GREEN" in s["pit_loss"]
    ]
    return median(ratios) if ratios else None


def pit_loss_prior(
    past: list[dict],
    race: dict[str, Any],
    ratio: float | None,
    reference: dict[int, float],
) -> tuple[float | None, str | None]:
    """Green pit loss for this circuit from past races, scaled by the condition's
    ratio to green."""
    if ratio is None:
        return None, None
    greens = [s["pit_loss"]["GREEN"] for s in past if "GREEN" in s["pit_loss"]]
    here = [
        s["pit_loss"]["GREEN"]
        for s in past
        if s["circuit_key"] == race["circuit_key"] and "GREEN" in s["pit_loss"]
    ]
    if here:
        return round(median(here) * ratio, 1), "circuit"
    if race["circuit_key"] in reference:
        return round(reference[race["circuit_key"]] * ratio, 1), "reference"
    return (round(median(greens) * ratio, 1), "global") if greens else (None, None)


def degradation_prior(
    past: list[dict], race: dict[str, Any], compound: str
) -> tuple[float | None, str | None]:
    """Degradation slope for a compound at this circuit from past races.

    The 2026 cars differ, so a 2026 race shifts older values by the median gap
    between the 2026 slopes seen so far and the older ones, once three are known.
    """

    def slopes(rows):
        return [
            s["degradation"][compound] for s in rows if compound in s["degradation"]
        ]

    old = slopes(s for s in past if s["season"] < NEW_ERA)
    new = slopes(s for s in past if s["season"] >= NEW_ERA)
    shift = 0.0
    if race["season"] >= NEW_ERA and old and len(new) >= MIN_ERA_RACES:
        shift = median(new) - median(old)
    here = slopes(s for s in past if s["circuit_key"] == race["circuit_key"])
    if here:
        return round(median(here) + shift, 4), "circuit"
    recent = race["season"] >= NEW_ERA and len(new) >= MIN_ERA_RACES
    base = new if recent else old + new
    return (round(median(base), 4), "global") if base else (None, None)
