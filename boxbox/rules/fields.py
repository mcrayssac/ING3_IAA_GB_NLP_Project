"""Card edits that follow the contract, kept apart from the pinned policy source."""

from __future__ import annotations

import copy
from typing import Any


def remove_field(card: dict[str, Any], field: str) -> dict[str, Any]:
    """The card with one field made unknown, as the contract writes an unknown value."""
    changed = copy.deepcopy(card)
    if field in ("gap_ahead", "gap_behind"):
        changed[field] = {"state": "UNKNOWN", "seconds": None}
    elif field == "pit_loss_seconds":
        changed["pit_loss_seconds"] = changed["pit_loss_as_of_completed_lap"] = None
    else:
        changed[field] = None
    return changed
