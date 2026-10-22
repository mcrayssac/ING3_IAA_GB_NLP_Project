"""Deterministic BoxBox race-card policy 2.0, on race-card schema 2.0.

Policy 2.0 covers safety cars, wet running, tyre wear and the undercut. Worn tyres
get BOX whatever the traffic; inside the wear window a stop needs an undercut or a
neutralisation, then a clean rejoin. It reads the card only: every learned value
(pit loss, degradation, its source) is written on the card by the data builder, and
the thresholds below are fixed constants.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import decision
from .decision import (
    AHEAD_OPPORTUNITY_SECONDS,
    CANNOT_ASSESS,
    DRY_COMPOUNDS,
    TYRE_LIMITS,
    _gap,
    _integer,
    _malformed_none,
    _number,
    _rejoin_threshold,
    _seconds,
    _valid_identity,
    article,
    laps,
)

POLICY_VERSION = "2.0"
# time lost per lap against a new set, from which a stop opens and always opens:
# the 25th percentile and the median on the cards of real green-flag stops in the
# train races (python -m scripts.reality_check --splits train --thresholds)
TYRE_LOSS_LIMITS = {
    "SOFT": (Decimal("0.34"), Decimal("0.62")),
    "MEDIUM": (Decimal("0.63"), Decimal("1.08")),
    "HARD": (Decimal("0.92"), Decimal("1.38")),
}
UNDERCUT_LAPS = 1  # laps before the rival can answer an undercut by stopping too
WET_COMPOUNDS = frozenset({"INTERMEDIATE", "WET"})
STATUSES = frozenset({"GREEN", "SC", "VSC"})
STAY = "so the rule is to stay out."
BOX = "so the rule calls for boxing."
# teams stop worn tyres and accept the places, so traffic only matters in the window
WORN = "so the rule calls for boxing whatever the traffic."


def _scope_reason(card: Any) -> str | None:
    """Return the NO CALL reason, or None when the card is in scope."""
    if not isinstance(card, dict) or card.get("schema_version") != "2.0":
        return f"The card schema is missing or unsupported, {CANNOT_ASSESS}"
    if not _valid_identity(card):
        return f"The card identity or observation cutoff is incomplete or invalid, {CANNOT_ASSESS}"
    if card["race"].get("completed") is not True:
        return f"The card does not confirm a completed historical race, {CANNOT_ASSESS}"
    if card.get("surface") not in ("DRY", "WET"):
        return f"The card does not show the track surface, {CANNOT_ASSESS}"
    if card.get("track_status") not in STATUSES:
        return f"The card does not show green, SC or VSC running, {CANNOT_ASSESS}"
    if card.get("compound") not in DRY_COMPOUNDS | WET_COMPOUNDS:
        return f"The card does not show a known tyre compound, {CANNOT_ASSESS}"
    if not _integer(card.get("tyre_age_laps"), 0):
        return f"The card is missing a valid tyre age, {CANNOT_ASSESS}"
    for field in ("gap_ahead", "gap_behind"):
        if _malformed_none(card, field):
            return f"The card has an incomplete {field} absence claim, {CANNOT_ASSESS}"
    return None


def _crossover(card: dict[str, Any]) -> tuple[str | None, str] | None:
    """A tyre that does not match the surface; None when they match on slicks."""
    compound, wet_track = card["compound"], card["surface"] == "WET"
    if wet_track and compound in DRY_COMPOUNDS:
        return None, f"{compound} tyres on a wet track"
    if not wet_track and compound in WET_COMPOUNDS:
        return None, f"{compound} tyres on a dry track"
    if compound in WET_COMPOUNDS:
        return "STAY OUT", f"The card shows {compound} tyres on a wet track, {STAY}"
    return None


def _age_rule(card: dict[str, Any]) -> tuple[str | None, str]:
    """(final call, text) from tyre age when wear is unknown; None inside the window."""
    compound, age = card["compound"], card["tyre_age_laps"]
    young, old = TYRE_LIMITS[compound]
    tyres = f"{compound} tyres aged {laps(age)}"
    if age < young:
        why = f"The card shows {tyres}, below the {young}-lap trigger for {compound} tyres"
        return "STAY OUT", f"{why}, {STAY}"
    if age >= old:
        why = f"The card shows {tyres}, at or above the {old}-lap limit for {compound} tyres"
        return "BOX", f"{why}, {WORN}"
    return None, tyres


def _wear_rule(card: dict[str, Any], loss: Decimal) -> tuple[str | None, str]:
    """(final call, text) from the time the tyres lose per lap; None in the window."""
    young, old = TYRE_LOSS_LIMITS[card["compound"]]
    tyres = f"{card['compound']} tyres losing {_number(loss)} s per lap to a new set"
    if loss < young:
        why = f"The card shows {tyres}, below the {_number(young)}-second trigger"
        return "STAY OUT", f"{why}, {STAY}"
    if loss >= old:
        why = f"The card shows {tyres}, at or above the {_number(old)}-second limit"
        return "BOX", f"{why}, {WORN}"
    return None, tyres


def _undercut(card: dict[str, Any], tyres: str) -> tuple[str | None, str]:
    """Inside the window, the car ahead must be close enough to pass in the stops."""
    state, ahead = _gap(card, "gap_ahead")
    if state == "UNKNOWN":
        return (
            "NO CALL",
            f"The card is missing the gap to the car ahead, {CANNOT_ASSESS}",
        )
    if state == "NONE":
        return "STAY OUT", f"The card shows {tyres} and no car ahead, {STAY}"
    rival = _seconds((card.get("gap_ahead") or {}).get("tyre_loss_s_per_lap"))
    reach = AHEAD_OPPORTUNITY_SECONDS if rival is None else rival * UNDERCUT_LAPS
    gap = f"{article(_number(ahead))} {_number(ahead)}-second gap ahead"
    if ahead > reach:
        why = f"The card shows {gap}, more than the {_number(reach)} seconds an undercut can win"
        return "STAY OUT", f"{why}, {STAY}"
    return None, f"{tyres} and {gap} within undercut reach"


def _opportunity(card: dict[str, Any]) -> tuple[str | None, str]:
    """A final (call, why), or (None, the opportunity in words)."""
    crossover = _crossover(card)
    if crossover is not None:
        return crossover
    loss = _seconds(card.get("tyre_loss_s_per_lap"))
    call, tyres = _age_rule(card) if loss is None else _wear_rule(card, loss)
    if _cheap_mandatory_stop(card):
        status = card["track_status"]
        return None, f"{tyres}, a {status} and the mandatory stop still to make"
    if call is not None:
        return call, tyres
    if card["track_status"] in ("SC", "VSC"):
        return None, f"{tyres} under a {card['track_status']}"
    return _undercut(card, tyres)


def _cheap_mandatory_stop(card: dict[str, Any]) -> bool:
    """A stop the dry-race rules require anyway costs less under a SC or VSC."""
    return (
        card["track_status"] in ("SC", "VSC")
        and card["surface"] == "DRY"
        and card.get("mandatory_stop_pending") is True
    )


def _pit_loss(card: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    """The pit loss plus any pending penalty, or a NO CALL reason."""
    loss = _seconds(card.get("pit_loss_seconds"))
    cutoff = card.get("pit_loss_as_of_completed_lap")
    if loss is None:
        return None, f"The card is missing a valid pit-loss estimate, {CANNOT_ASSESS}"
    if not _integer(cutoff, 0) or cutoff > card["as_of_completed_lap"]:
        return (
            None,
            f"The card does not provide a valid pre-lap pit-loss cutoff, {CANNOT_ASSESS}",
        )
    penalty = _seconds(card.get("penalty_pending_seconds")) or Decimal(0)
    return loss + penalty, None


def _rejoin(card: dict[str, Any], opportunity: str) -> tuple[str, str]:
    """Under a SC the window behind must be empty; otherwise the gap must cover the
    pit loss, any pending penalty and the 2.0-second margin."""
    if _cheap_mandatory_stop(card):
        return "BOX", f"With {opportunity}, the stop costs less now than later, {BOX}"
    if card["track_status"] == "SC":
        window = card.get("cars_in_pit_window")
        if not _integer(window, 0):
            return (
                "NO CALL",
                f"The card is missing the cars in the pit window, {CANNOT_ASSESS}",
            )
        if window == 0:
            return "BOX", f"With {opportunity}, no car sits in the pit window, {BOX}"
        cars = "1 car sits" if window == 1 else f"{window} cars sit"
        return "STAY OUT", f"With {opportunity}, {cars} in the pit window, {STAY}"
    state, behind = _gap(card, "gap_behind")
    if state == "UNKNOWN":
        return (
            "NO CALL",
            f"The card is missing the gap to the car behind, {CANNOT_ASSESS}",
        )
    if state == "NONE":
        return "BOX", f"The card shows {opportunity} and no car behind, {BOX}"
    cost, reason = _pit_loss(card)
    if reason is not None:
        return "NO CALL", reason
    gap_text = f"the {_number(behind)}-second gap behind"
    loss_text = f"the {_number(cost)}-second pit cost plus the 2.0-second margin"
    if behind >= _rejoin_threshold(cost):
        return "BOX", f"With {opportunity}, {gap_text} covers {loss_text}, {BOX}"
    return "STAY OUT", f"With {opportunity}, {gap_text} is below {loss_text}, {STAY}"


def decide_v2(card: Any) -> tuple[str, str]:
    """Return the policy 2.0 call and a single English reason for a 2.0 card."""
    reason = _scope_reason(card)
    if reason is not None:
        return "NO CALL", reason
    call, text = _opportunity(card)
    if call is not None:
        return call, text
    return _rejoin(card, text)


def decide(card: Any) -> tuple[str, str]:
    """Policy 2.0 for a 2.0 card, policy 1.1 for anything else."""
    if isinstance(card, dict) and card.get("schema_version") == "2.0":
        return decide_v2(card)
    return decision.decide(card)


def format_answer(card: Any) -> str:
    """Render the decision of either policy in the two-line response format."""
    call, why = decide(card)
    return f"CALL: {call}\nWHY: {why}"
