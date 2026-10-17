"""Deterministic BoxBox race-card policy, version 1.0.

The contract and ordered rules are in docs/race-card-contract.md. This module
uses only the Python standard library and does not reconstruct real race data.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


YOUNG_AGE_LIMIT = 12
OLD_AGE_LIMIT = 18
AHEAD_OPPORTUNITY_SECONDS = Decimal("2.0")
REJOIN_MARGIN_SECONDS = Decimal("2.0")
DRY_COMPOUNDS = frozenset({"SOFT", "MEDIUM", "HARD"})


def _integer(value: Any, minimum: int | None = None) -> bool:
    return type(value) is int and (minimum is None or value >= minimum)


def _seconds(value: Any) -> Decimal | None:
    if type(value) not in (int, float, Decimal):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _gap(card: dict[str, Any], field: str) -> tuple[str, Decimal | None]:
    gap = card.get(field)
    if not isinstance(gap, dict):
        return "UNKNOWN", None
    state = gap.get("state")
    seconds = gap.get("seconds")
    if state == "NONE" and "seconds" in gap and seconds is None:
        return "NONE", None
    if state == "KNOWN":
        amount = _seconds(seconds)
        if amount is not None:
            return "KNOWN", amount
    return "UNKNOWN", None


def _malformed_none(card: dict[str, Any], field: str) -> bool:
    gap = card.get(field)
    return isinstance(gap, dict) and gap.get("state") == "NONE" and (
        "seconds" not in gap or gap["seconds"] is not None
    )


def _number(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered if "." in rendered else f"{rendered}.0"


def _rejoin_threshold(pit_loss: Decimal) -> Decimal:
    """Add the margin without rounding a precise pit-loss estimate."""
    least_place = min(pit_loss.as_tuple().exponent, REJOIN_MARGIN_SECONDS.as_tuple().exponent)
    highest_place = max(pit_loss.adjusted(), REJOIN_MARGIN_SECONDS.adjusted()) + 1
    with localcontext() as context:
        context.prec = max(context.prec, highest_place - least_place + 2)
        return pit_loss + REJOIN_MARGIN_SECONDS


def _opportunity(tyre_age: int, gap_ahead: Decimal | None) -> str:
    if tyre_age >= OLD_AGE_LIMIT:
        return f"tyres aged {tyre_age} laps"
    assert gap_ahead is not None
    return f"tyres aged {tyre_age} laps and a {_number(gap_ahead)}-second gap ahead"


def decide(card: Any) -> tuple[str, str]:
    """Return the policy call and a single English reason for a JSON card.

    Invalid or absent decision inputs produce NO CALL. The order of checks is
    intentional: fields are validated when their rule branch needs them.
    """
    if not isinstance(card, dict) or card.get("schema_version") != "1.0":
        return "NO CALL", "The card schema is missing or unsupported, so the rule cannot assess a pit stop."

    race = card.get("race")
    lap = card.get("lap")
    total_laps = card.get("total_laps")
    driver = card.get("driver_number")
    cutoff = card.get("as_of_completed_lap")
    if (
        not isinstance(race, dict)
        or not _integer(race.get("season"), 1950)
        or not _integer(race.get("round"), 1)
        or not isinstance(race.get("event"), str)
        or not race["event"].strip()
        or not _integer(lap, 1)
        or not _integer(total_laps, 1)
        or lap > total_laps
        or not isinstance(driver, str)
        or re.fullmatch(r"[1-9][0-9]?", driver) is None
        or not _integer(cutoff, 0)
        or cutoff != lap - 1
    ):
        return "NO CALL", "The card identity or observation cutoff is incomplete or invalid, so the rule cannot assess a pit stop."
    if race.get("completed") is not True:
        return "NO CALL", "The card does not confirm a completed historical race, so the rule cannot assess a pit stop."
    if card.get("surface") != "DRY":
        return "NO CALL", "The card does not confirm a dry track, so the rule cannot assess a pit stop."
    if card.get("track_status") != "GREEN":
        return "NO CALL", "The card does not show green-flag running, so the rule cannot assess a pit stop."
    if not isinstance(card.get("compound"), str) or card["compound"] not in DRY_COMPOUNDS:
        return "NO CALL", "The card does not show a supported dry tyre compound, so the rule cannot assess a pit stop."

    tyre_age = card.get("tyre_age_laps")
    if not _integer(tyre_age, 0) or tyre_age > cutoff:
        return "NO CALL", "The card is missing a valid tyre age, so the rule cannot assess a pit stop."
    for field in ("gap_ahead", "gap_behind"):
        if _malformed_none(card, field):
            return "NO CALL", f"The card has an incomplete {field} absence claim, so the rule cannot assess a pit stop."
    if tyre_age < YOUNG_AGE_LIMIT:
        return "STAY OUT", f"The card shows tyres aged {tyre_age} laps, below the 12-lap trigger, so the rule is to stay out."

    ahead: Decimal | None = None
    if tyre_age < OLD_AGE_LIMIT:
        ahead_state, ahead = _gap(card, "gap_ahead")
        if ahead_state == "UNKNOWN":
            return "NO CALL", "The card is missing the gap to the car ahead, so the rule cannot assess a pit stop."
        if ahead_state == "NONE":
            return "STAY OUT", f"The card shows tyres aged {tyre_age} laps and no car ahead, so the rule is to stay out."
        assert ahead is not None
        if ahead > AHEAD_OPPORTUNITY_SECONDS:
            return "STAY OUT", f"The card shows a {_number(ahead)}-second gap ahead, above the 2.0-second opportunity threshold, so the rule is to stay out."

    behind_state, behind = _gap(card, "gap_behind")
    if behind_state == "UNKNOWN":
        return "NO CALL", "The card is missing the gap to the car behind, so the rule cannot assess a pit stop."
    if behind_state == "NONE":
        return "BOX", f"The card shows {_opportunity(tyre_age, ahead)} and no car behind, so the rule calls for boxing."

    pit_loss = _seconds(card.get("pit_loss_seconds"))
    pit_loss_cutoff = card.get("pit_loss_as_of_completed_lap")
    if pit_loss is None:
        return "NO CALL", "The card is missing a valid pit-loss estimate, so the rule cannot assess a pit stop."
    if not _integer(pit_loss_cutoff, 0) or pit_loss_cutoff > cutoff:
        return "NO CALL", "The card does not provide a valid pre-lap pit-loss cutoff, so the rule cannot assess a pit stop."
    assert behind is not None

    opportunity = _opportunity(tyre_age, ahead)
    if behind >= _rejoin_threshold(pit_loss):
        if ahead is None:
            why = (
                f"With {opportunity}, the {_number(behind)}-second gap behind covers the "
                f"{_number(pit_loss)}-second pit loss plus the 2.0-second margin, so the rule calls for boxing."
            )
        else:
            why = (
                f"With {opportunity}, the {_number(behind)}-second gap behind covers "
                "pit loss plus the 2.0-second margin, so the rule calls for boxing."
            )
        return "BOX", why
    return (
        "STAY OUT",
        f"With {opportunity}, the {_number(behind)}-second gap behind is below the "
        f"{_number(pit_loss)}-second pit loss plus the 2.0-second margin, so the rule is to stay out.",
    )


def format_answer(card: Any) -> str:
    """Render a card-only decision in the required two-line response format."""
    call, why = decide(card)
    return f"CALL: {call}\nWHY: {why}"
