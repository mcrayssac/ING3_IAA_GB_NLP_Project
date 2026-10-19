"""Session steps of the demo: cards, one exchange with the engine, reset and upload."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from boxbox.rules import format_answer

FIXTURES = Path("reference/fixtures.json")
DEMO_CARDS = Path("data/demo/cards.json")
Respond = Callable[[dict[str, Any], list[dict[str, str]], str], str]


def stub_respond(
    card: dict[str, Any], history: list[dict[str, str]], message: str
) -> str:
    """Preparation stub until task 2.8: the rule's answer, whatever the message says."""
    return format_answer(card)


def _label(card: dict[str, Any]) -> str:
    race = card["race"]
    return f"Real race: {race['season']} {race['event']}, lap {card['lap']}, car {card['driver_number']}"


def sample_cards(
    fixtures: Path = FIXTURES, demo: Path = DEMO_CARDS
) -> dict[str, dict[str, Any]]:
    """The cards of the picker by label: synthetic examples first, then real races."""
    examples = json.loads(fixtures.read_text(encoding="utf-8"))["conversations"]
    cards = {
        f"Synthetic example: {c['id'].replace('_', ' ')}": c["card"] for c in examples
    }
    if demo.exists():
        real = json.loads(demo.read_text(encoding="utf-8"))
        cards |= {_label(r["card"]): r["card"] for r in real}
    return cards


def send(
    card: dict[str, Any],
    history: list[dict[str, str]],
    message: str,
    respond: Respond,
    turns: int,
) -> tuple[list[dict[str, str]], str | None]:
    """The history after one exchange, or the same history and an error to show."""
    message = message.strip()
    if not message:
        return history, None
    try:  # the contract's bounded history; any engine failure is shown, never stored
        answer = respond(card, history[-2 * turns :], message)
    except Exception as error:  # noqa: BLE001
        return history, f"The engine failed: {error}. The conversation is unchanged."
    if not isinstance(answer, str):
        return history, "The engine returned no text. The conversation is unchanged."
    turn = [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    return history + turn, None


def load_upload(path: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """The uploaded card, or None and why it was refused."""
    try:
        card = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        return (
            None,
            f"The file could not be read as JSON ({error}), so the current card stays.",
        )
    if not isinstance(card, dict):
        return (
            None,
            "The file does not hold one JSON object, so the current card stays.",
        )
    return card, None


def latest_answer(history: list[dict[str, str]]) -> str | None:
    """The last assistant message, which the call banner shows."""
    answers = [m["content"] for m in history if m["role"] == "assistant"]
    return answers[-1] if answers else None
