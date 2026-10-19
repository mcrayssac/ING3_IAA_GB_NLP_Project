"""Write the real race cards of the demo picker (task 2.4).

Usage, from the repository root:
    python -m scripts.demo_cards

Cards are read only through boxbox.data.load_cards, from validation races, so the final split
stays closed and adapter A never trained on them. It keeps one card per rule path, one under a
safety car or VSC with every other field known, and one green card with a real missing field.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from boxbox.config import RunConfig
from boxbox.corpus import complete, path_of
from boxbox.corpus.build import PATHS
from boxbox.data import load_cards
from boxbox.rules import decide

OUT = Path("data/demo/cards.json")


def _pool(card: dict[str, Any]) -> str | None:
    if card["reference_lap_seconds"] is None:
        return None  # the circle of doom needs a lap time
    if complete(card):
        return path_of(card)
    if card["track_status"] != "GREEN":
        return "track_status" if complete({**card, "track_status": "GREEN"}) else None
    return "missing" if decide(card)[0] == "NO CALL" else None


def pick(records: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """One record per rule path, then a neutralised track and a real missing field."""
    pools = {name: [] for name in (*PATHS, "track_status", "missing")}
    for record in sorted(records, key=lambda r: r["card_id"]):
        name = _pool(record["card"])
        if name:
            pools[name].append(record)
    rng = random.Random(f"{seed}-demo")
    return [
        {"card_id": r["card_id"], "card": r["card"]}
        for r in map(rng.choice, pools.values())
    ]


def main() -> int:
    config = RunConfig()
    cards = pick(load_cards("validation", config), config.seed)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cards, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(cards)} cards written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
