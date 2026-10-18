"""Questions and answers of the dialogues. Every policy answer comes from the rules."""

from __future__ import annotations

import copy
from typing import Any

from boxbox.rules import decide, format_answer
from boxbox.rules.decision import article, laps

CALL_QUESTIONS = (
    "Should car {car} box now?",
    "Box or stay out for car {car} at lap {lap}?",
    "What is the call for car {car} on lap {lap}?",
    "Is it time to pit car {car}?",
    "Should car {car} stay out this lap?",
    "Do we bring car {car} in at the end of lap {lap}?",
    "Pit or stay out?",
    "What's the strategy call for car {car} right now?",
    "Would you box car {car} here?",
    "Is lap {lap} the right moment for car {car} to stop?",
    "Should car {car} make a pit stop on this lap?",
    "Car {car}, lap {lap}: box or stay out?",
    "What do you recommend for car {car}, box or stay out?",
    "Is a pit stop justified for car {car} now?",
    "What's the call for car {car} at the start of lap {lap}?",
)

WHY_QUESTIONS = ("Why?", "Can you explain that call?", "What makes you say that?")

FIELD_QUESTIONS = {
    "tyre_age_laps": "How old are the tyres on the card?",
    "gap_ahead": "What gap ahead does the card show?",
    "gap_behind": "What gap behind does the card show?",
    "pit_loss_seconds": "What pit loss does the card use?",
}

WHAT_IF_QUESTION = "What if the gap behind were {seconds} seconds?"

# out-of-scope requests and their fixed answer, one sentence each
SCOPE = {
    "weather": (
        ("Will it rain during this race?", "Should we expect rain in the next laps?"),
        "This dry historical card has no weather data, so I cannot forecast the weather.",
    ),
    "live_race": (
        (
            "What should car {car} do in next week's race?",
            "Can you call the live race for us?",
        ),
        "This card describes a past race, so I cannot advise on a live or future race.",
    ),
    "betting": (
        ("Who should I bet on to win?", "Is car {car} a good bet for the podium?"),
        "Betting tips are outside what this card and the rule can support.",
    ),
    "championship": (
        ("Who will win the championship?", "Can car {car} still win the title?"),
        "The card covers one lap of one race, so it cannot predict the championship.",
    ),
    "radio": (
        (
            "Write the team radio message for car {car}.",
            "What did the engineer tell car {car}?",
        ),
        "I only give a pit call from the card and do not write or quote team radio.",
    ),
    "other_car": (
        ("Should car {other} box now?", "What's the call for car {other}?"),
        "The card only describes car {car}, so I cannot assess car {other}.",
    ),
    "multi_stop": (
        (
            "Plan the full two-stop strategy for car {car}.",
            "Which laps should car {car} stop on?",
        ),
        "The rule only assesses a stop on this lap, not a full multi-stop strategy.",
    ),
    "unrelated": (
        ("Can you recommend a good pizza place?", "What's the capital of Australia?"),
        "I only explain pit-stop calls from the race card.",
    ),
}


def _seconds(value: float) -> str:
    return f"{float(value):.1f}"


def _gap_phrase(gap: dict[str, Any], side: str) -> str:
    if gap["state"] == "NONE":
        return f"no car {side}"
    if gap["state"] == "UNKNOWN":
        return f"an unknown gap {side}"
    seconds = _seconds(gap["seconds"])
    return f"{article(seconds)} {seconds}-second gap {side}"


def field_phrase(card: dict[str, Any], field: str) -> str:
    """How a field of the card reads in a WHY sentence."""
    if field == "tyre_age_laps":
        return f"{card['compound']} tyres aged {laps(card['tyre_age_laps'])}"
    if field == "pit_loss_seconds":
        loss = _seconds(card["pit_loss_seconds"])
        return f"{article(loss)} {loss}-second pit-loss estimate"
    return _gap_phrase(card[field], "ahead" if field == "gap_ahead" else "behind")


def call_answer(card: dict[str, Any]) -> str:
    return format_answer(card)


def field_answer(card: dict[str, Any], field: str) -> str:
    call, _ = decide(card)
    return f"CALL: {call}\nWHY: The card shows {field_phrase(card, field)}, and the call for this lap stays {call}."


def what_if_card(card: dict[str, Any], seconds: float) -> dict[str, Any]:
    """The card with an explicitly assumed gap behind, everything else unchanged."""
    changed = copy.deepcopy(card)
    neighbour = card["gap_behind"].get("driver_number")
    changed["gap_behind"] = {"state": "KNOWN", "seconds": round(float(seconds), 1)}
    if neighbour:
        changed["gap_behind"]["driver_number"] = neighbour
    return changed


def what_if_answer(card: dict[str, Any], seconds: float) -> str:
    call, why = decide(what_if_card(card, seconds))
    assumed = _seconds(seconds)
    prefix = f"Assuming {article(assumed)} {assumed}-second gap behind"
    return f"CALL: {call}\nWHY: {prefix}, {why[0].lower()}{why[1:]}"


def scope_answer(category: str, card: dict[str, Any], other: str = "") -> str:
    sentence = SCOPE[category][1].format(car=card["driver_number"], other=other)
    return f"CALL: NO CALL\nWHY: {sentence}"
