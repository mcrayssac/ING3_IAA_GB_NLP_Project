"""Training rows for an adapter, rendered by the conversation engine (task 2.6)."""

from __future__ import annotations

from typing import Any


def assistant_turns(item: dict[str, Any]) -> list[tuple[list[dict], str, str]]:
    """(history, user message, assistant answer) for every assistant turn of an item."""
    messages = item["messages"]
    return [
        (messages[:i], messages[i]["content"], messages[i + 1]["content"])
        for i in range(0, len(messages), 2)
    ]


def build_rows(engine: Any, items: list[dict[str, Any]], max_length: int) -> list[dict]:
    """One pre-tokenized row per assistant turn: the engine's prompt, then the answer.

    The loss falls on the answer only, through `completion_mask`.
    """
    rows = []
    for item in items:
        for history, message, answer in assistant_turns(item):
            prompt, completion = engine.training_ids(
                item["card"], history, message, answer
            )
            if len(prompt) + len(completion) > max_length:
                raise ValueError(
                    f"{item['id']}: {len(prompt) + len(completion)} tokens, "
                    f"over max_length {max_length}"
                )
            rows.append(
                {
                    "input_ids": prompt + completion,
                    "completion_mask": [0] * len(prompt) + [1] * len(completion),
                }
            )
    return rows
