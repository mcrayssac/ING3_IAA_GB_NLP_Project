"""Questions and answers of the dialogues. Every policy answer comes from the rules."""

from __future__ import annotations

from typing import Any

from boxbox.rules import decide, format_answer
from boxbox.rules.decision import article, laps

# A trains on the "train" questions; validation and the mini-test ask only "eval" ones,
# so a gain on them cannot come from wording seen in training
QUESTIONS = {
    "train": {
        "call": (
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
        ),
        "why": ("Why?", "Can you explain that call?", "What makes you say that?"),
        "field": {
            "tyre_age_laps": "How old are the tyres on the card?",
            "gap_ahead": "What gap ahead does the card show?",
            "gap_behind": "What gap behind does the card show?",
            "pit_loss_seconds": "What pit loss does the card use?",
        },
        "stated": (
            "The gap behind is {seconds} seconds now. Should car {car} box?",
            "Our timing has car {car} {seconds} seconds clear of the car behind. Box?",
        ),
        "scope": {
            "weather": (
                "Will it rain during this race?",
                "Should we expect rain in the next laps?",
            ),
            "live_race": (
                "What should car {car} do in next week's race?",
                "Can you call the live race for us?",
            ),
            "betting": (
                "Who should I bet on to win?",
                "Is car {car} a good bet for the podium?",
            ),
            "championship": (
                "Who will win the championship?",
                "Can car {car} still win the title?",
            ),
            "radio": (
                "Write the team radio message for car {car}.",
                "What did the engineer tell car {car}?",
            ),
            "other_car": (
                "Should car {other} box now?",
                "What's the call for car {other}?",
            ),
            "multi_stop": (
                "Plan the full two-stop strategy for car {car}.",
                "Which laps should car {car} stop on?",
            ),
            "unrelated": (
                "Can you recommend a good pizza place?",
                "What's the capital of Australia?",
            ),
        },
    },
    "eval": {
        "call": (
            "Should we call car {car} in this lap?",
            "Lap {lap} for car {car}: pit now or keep going?",
            "Is now a good time for car {car} to come in?",
            "Which call fits car {car} on lap {lap}?",
            "Box this lap or not for car {car}?",
        ),
        "why": ("What is that call based on?", "Which part of the card decides it?"),
        "field": {
            "tyre_age_laps": "How many laps are on these tyres?",
            "gap_ahead": "How far is the car in front?",
            "gap_behind": "How big is the gap to the car behind?",
            "pit_loss_seconds": "How much time does a stop cost here?",
        },
        "stated": (
            "By my count car {car} has {seconds} seconds over the car behind. Do we pit?",
            "The pit wall has the car behind {seconds} seconds back. Call for car {car}?",
        ),
        "scope": {
            "weather": (
                "Will the track get wet later?",
                "Do we need intermediates soon?",
            ),
            "live_race": (
                "What strategy should car {car} use at the next Grand Prix?",
                "Give us live calls for this weekend's race.",
            ),
            "betting": (
                "What odds would you give car {car} to win?",
                "Which driver is the safest bet today?",
            ),
            "championship": (
                "Who is favourite for the drivers' title?",
                "How many points does car {car} need to be champion?",
            ),
            "radio": (
                "Draft a radio call telling car {car} to push.",
                "What did car {car} say on the radio?",
            ),
            "other_car": (
                "Should car {other} come in this lap?",
                "Pit now or later for car {other}?",
            ),
            "multi_stop": (
                "Lay out a three-stop plan for car {car}.",
                "When should car {car} make its second stop?",
            ),
            "unrelated": (
                "What's a good film to watch tonight?",
                "Can you translate this sentence into French?",
            ),
        },
    },
}

# the fixed answer sentence of each out-of-scope category
SCOPE = {
    "weather": "This dry historical card has no weather data, so I cannot forecast the weather.",
    "live_race": "This card describes a past race, so I cannot advise on a live or future race.",
    "betting": "Betting tips are outside what this card and the rule can support.",
    "championship": "The card covers one lap of one race, so it cannot predict the championship.",
    "radio": "I only give a pit call from the card and do not write or quote team radio.",
    "other_car": "The card only describes car {car}, so I cannot assess car {other}.",
    "multi_stop": "The rule only assesses a stop on this lap, not a full multi-stop strategy.",
    "unrelated": "I only explain pit-stop calls from the race card.",
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


def scope_answer(category: str, card: dict[str, Any], other: str = "") -> str:
    sentence = SCOPE[category].format(car=card["driver_number"], other=other)
    return f"CALL: NO CALL\nWHY: {sentence}"
