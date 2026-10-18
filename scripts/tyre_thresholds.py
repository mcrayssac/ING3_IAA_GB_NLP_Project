"""Tyre age at green-flag stops in the train races, per compound (policy 1.1).

Usage, from the repository root: python -m scripts.tyre_thresholds
The 25th percentile and the median become the rule's opportunity and always ages.
"""

from __future__ import annotations

import json
from collections import defaultdict
from statistics import median, quantiles

from boxbox.config import RunConfig
from boxbox.data import load_cards, load_splits, race_table


def stop_ages() -> dict[str, list[int]]:
    """Tyre age on every card of a lap that ended with a green-flag stop, train only."""
    document = load_splits()
    ages = defaultdict(list)
    cards = load_cards("train", RunConfig())
    by_race = defaultdict(list)
    for record in cards:
        by_race[record["card_id"].rsplit("-", 2)[0]].append(record["card"])
    for race_id, race_cards in by_race.items():
        table = race_table(document["races"][race_id])
        stops = {
            (driver, lap)
            for driver, lap, pit_in, status in zip(
                table["driver_number"], table["lap"], table["pit_in"], table["status"]
            )
            if pit_in and status == "GREEN"
        }
        for card in race_cards:
            if (card["driver_number"], card["lap"]) in stops and card[
                "track_status"
            ] == "GREEN":
                ages[card["compound"]].append(card["tyre_age_laps"])
    return ages


if __name__ == "__main__":
    table = {}
    for compound, values in sorted(stop_ages().items()):
        p25, _, p75 = quantiles(values, n=4)
        table[compound] = {
            "stops": len(values),
            "p25": p25,
            "median": median(values),
            "p75": p75,
        }
    print(json.dumps(table, indent=2))
