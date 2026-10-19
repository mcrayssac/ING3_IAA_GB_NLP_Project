"""Deterministic BoxBox race-card policy 1.1, on race-card schema 1.0.

The contract and ordered rules are in docs/race-card-contract.md. This module
uses only the Python standard library and does not reconstruct real race data.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

POLICY_VERSION = "1.1"
# (opportunity from, always from) in laps: the 25th percentile and the median tyre age
# at green-flag stops in the 2023-2025 train races (scripts/tyre_thresholds.py)
TYRE_LIMITS = {"SOFT": (8, 14), "MEDIUM": (12, 18), "HARD": (18, 24)}
AHEAD_OPPORTUNITY_SECONDS = Decimal("2.0")
REJOIN_MARGIN_SECONDS = Decimal("2.0")
DRY_COMPOUNDS = frozenset({"SOFT", "MEDIUM", "HARD"})
CANNOT_ASSESS = "so the rule cannot assess a pit stop."


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
    return (
        isinstance(gap, dict)
        and gap.get("state") == "NONE"
        and ("seconds" not in gap or gap["seconds"] is not None)
    )


def _number(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered if "." in rendered else f"{rendered}.0"


def article(number: str) -> str:
    """'an' before a number read with a vowel sound: 8, 11, 18, 80-89, 800-899."""
    whole = number.split(".")[0]
    return "an" if whole.startswith("8") or whole in ("11", "18") else "a"


def laps(count: int) -> str:
    return "1 lap" if count == 1 else f"{count} laps"


def _rejoin_threshold(pit_loss: Decimal) -> Decimal:
    """Add the margin without rounding a precise pit-loss estimate."""
    least_place = min(
        pit_loss.as_tuple().exponent, REJOIN_MARGIN_SECONDS.as_tuple().exponent
    )
    highest_place = max(pit_loss.adjusted(), REJOIN_MARGIN_SECONDS.adjusted()) + 1
    with localcontext() as context:
        context.prec = max(context.prec, highest_place - least_place + 2)
        return pit_loss + REJOIN_MARGIN_SECONDS


def _valid_identity(card: dict[str, Any]) -> bool:
    """Check race identity, lap, driver number and the lap - 1 observation cutoff."""
    race, lap, cutoff = (
        card.get("race"),
        card.get("lap"),
        card.get("as_of_completed_lap"),
    )
    driver = card.get("driver_number")
    return (
        isinstance(race, dict)
        and _integer(race.get("season"), 1950)
        and _integer(race.get("round"), 1)
        and isinstance(race.get("event"), str)
        and bool(race["event"].strip())
        and _integer(lap, 1)
        and _integer(card.get("total_laps"), 1)
        and lap <= card["total_laps"]
        and isinstance(driver, str)
        and re.fullmatch(r"[1-9][0-9]?", driver) is not None
        and _integer(cutoff, 0)
        and cutoff == lap - 1
    )


def _scope_reason(card: Any) -> str | None:
    """Rule 1: return the NO CALL reason, or None when the card is in scope."""
    if not isinstance(card, dict) or card.get("schema_version") != "1.0":
        return f"The card schema is missing or unsupported, {CANNOT_ASSESS}"
    if not _valid_identity(card):
        return f"The card identity or observation cutoff is incomplete or invalid, {CANNOT_ASSESS}"
    if card["race"].get("completed") is not True:
        return f"The card does not confirm a completed historical race, {CANNOT_ASSESS}"
    if card.get("surface") != "DRY":
        return f"The card does not confirm a dry track, {CANNOT_ASSESS}"
    if card.get("track_status") != "GREEN":
        return f"The card does not show green-flag running, {CANNOT_ASSESS}"
    if (
        not isinstance(card.get("compound"), str)
        or card["compound"] not in DRY_COMPOUNDS
    ):
        return f"The card does not show a supported dry tyre compound, {CANNOT_ASSESS}"
    if not _integer(card.get("tyre_age_laps"), 0):
        return f"The card is missing a valid tyre age, {CANNOT_ASSESS}"
    for field in ("gap_ahead", "gap_behind"):
        if _malformed_none(card, field):
            return f"The card has an incomplete {field} absence claim, {CANNOT_ASSESS}"
    return None


def _opportunity(card: dict[str, Any], tyre_age: int) -> tuple[str | None, str]:
    """Rules 2 to 4: a final (call, why), or (None, the opportunity in words)."""
    compound = card["compound"]
    young, old = TYRE_LIMITS[compound]
    tyres = f"{compound} tyres aged {laps(tyre_age)}"
    if tyre_age < young:
        why = f"The card shows {tyres}, below the {young}-lap trigger for {compound} tyres"
        return "STAY OUT", f"{why}, so the rule is to stay out."
    if tyre_age >= old:
        return None, tyres
    state, ahead = _gap(card, "gap_ahead")
    if state == "UNKNOWN":
        return (
            "NO CALL",
            f"The card is missing the gap to the car ahead, {CANNOT_ASSESS}",
        )
    if state == "NONE":
        why = f"The card shows {tyres} and no car ahead"
        return "STAY OUT", f"{why}, so the rule is to stay out."
    if ahead > AHEAD_OPPORTUNITY_SECONDS:
        gap = f"{article(_number(ahead))} {_number(ahead)}-second gap ahead"
        why = f"The card shows {gap}, above the 2.0-second opportunity threshold"
        return "STAY OUT", f"{why}, so the rule is to stay out."
    gap = f"{article(_number(ahead))} {_number(ahead)}-second gap ahead"
    return None, f"{tyres} and {gap}"


def _rejoin(card: dict[str, Any], opportunity: str) -> tuple[str, str]:
    """Rules 5 and 6: compare the gap behind with the pit loss plus the margin."""
    state, behind = _gap(card, "gap_behind")
    if state == "UNKNOWN":
        return (
            "NO CALL",
            f"The card is missing the gap to the car behind, {CANNOT_ASSESS}",
        )
    if state == "NONE":
        return (
            "BOX",
            # "tyres aged 14 laps and a 0.4-second gap ahead" becomes a list before "and no car behind"
            f"The card shows {opportunity.replace(' and ', ', ')} and no car behind, so the rule calls for boxing.",
        )
    pit_loss = _seconds(card.get("pit_loss_seconds"))
    pit_loss_cutoff = card.get("pit_loss_as_of_completed_lap")
    if pit_loss is None:
        return (
            "NO CALL",
            f"The card is missing a valid pit-loss estimate, {CANNOT_ASSESS}",
        )
    if (
        not _integer(pit_loss_cutoff, 0)
        or pit_loss_cutoff > card["as_of_completed_lap"]
    ):
        return (
            "NO CALL",
            f"The card does not provide a valid pre-lap pit-loss cutoff, {CANNOT_ASSESS}",
        )
    gap_text = f"the {_number(behind)}-second gap behind"
    loss_text = f"the {_number(pit_loss)}-second pit loss plus the 2.0-second margin"
    if behind >= _rejoin_threshold(pit_loss):
        return (
            "BOX",
            f"With {opportunity}, {gap_text} covers {loss_text}, so the rule calls for boxing.",
        )
    return (
        "STAY OUT",
        f"With {opportunity}, {gap_text} is below {loss_text}, so the rule is to stay out.",
    )


def decide(card: Any) -> tuple[str, str]:
    """Return the policy call and a single English reason for a JSON card.

    Rules run in contract order, and each step validates only the fields it needs.
    Display-only fields such as reference_lap_seconds are never read.
    """
    reason = _scope_reason(card)
    if reason is not None:
        return "NO CALL", reason
    call, text = _opportunity(card, card["tyre_age_laps"])
    if call is not None:
        return call, text
    return _rejoin(card, text)


def format_answer(card: Any) -> str:
    """Render a card-only decision in the required two-line response format."""
    call, why = decide(card)
    return f"CALL: {call}\nWHY: {why}"
