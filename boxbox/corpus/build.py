"""Card selection, dialogues and their checks for corpus A and the evaluation sets."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from itertools import product
from typing import Any

from boxbox.rules import TYRE_LIMITS, decide, remove_field

from . import templates as T

PATHS = (
    "box_old_tyres",
    "box_gap_ahead",
    "box_no_car_behind",
    "stay_young_tyres",
    "stay_gap_ahead",
    "stay_rejoin",
)
COMPOUNDS = ("SOFT", "MEDIUM", "HARD")
PER_RACE_DRIVER = 2  # neighbouring laps of one stint must not dominate
# fields the rule needs on each path; removing one gives NO CALL
REQUIRED = {
    "box_old_tyres": ("gap_behind", "pit_loss_seconds"),
    "box_gap_ahead": ("gap_ahead",),
    "box_no_car_behind": ("gap_behind",),
    "stay_young_tyres": ("tyre_age_laps",),
    "stay_gap_ahead": ("gap_ahead",),
    "stay_rejoin": ("gap_behind", "pit_loss_seconds"),
}
# fields the rule ignores on a path; removing one keeps the call
IRRELEVANT = {
    "stay_young_tyres": ("gap_behind", "pit_loss_seconds", "gap_ahead"),
    "box_old_tyres": ("gap_ahead",),
    "box_no_car_behind": ("pit_loss_seconds",),
}


def complete(card: dict[str, Any]) -> bool:
    """Every decision field known and green running: the cards corpus A may use."""
    return (
        card["pit_loss_seconds"] is not None
        and card["gap_ahead"]["state"] != "UNKNOWN"
        and card["gap_behind"]["state"] != "UNKNOWN"
        and card["track_status"] == "GREEN"
    )


def path_of(card: dict[str, Any]) -> str | None:
    """The rule path a complete card follows, or None when the rule gives NO CALL."""
    call, _ = decide(card)
    age = card["tyre_age_laps"]
    young, old = TYRE_LIMITS[card["compound"]]
    if call == "BOX":
        if card["gap_behind"]["state"] == "NONE":
            return "box_no_car_behind"
        return "box_old_tyres" if age >= old else "box_gap_ahead"
    if call == "STAY OUT":
        if age < young:
            return "stay_young_tyres"
        ahead = card["gap_ahead"]
        if age < old and (ahead["state"] == "NONE" or ahead["seconds"] > 2.0):
            return "stay_gap_ahead"
        return "stay_rejoin"
    return None


def _race_driver(record: dict[str, Any]) -> str:
    return record["card_id"].rsplit("-", 1)[0]


def _take(pool: list[dict[str, Any]], used: Counter) -> dict[str, Any] | None:
    """Pop the next card whose race and driver is still under the cap."""
    while pool:
        record = pool.pop()
        if used[_race_driver(record)] < PER_RACE_DRIVER:
            used[_race_driver(record)] += 1
            return record
    return None


def _shares(total: int, capacity: dict) -> Counter:
    """Split total over the keys one at a time, as evenly as their capacities allow."""
    share = Counter()
    while sum(share.values()) < total and any(
        share[k] < c for k, c in capacity.items()
    ):
        for key, room in capacity.items():
            if share[key] < room and sum(share.values()) < total:
                share[key] += 1
    return share


def _quotas(
    pools: dict, used: Counter, total: int
) -> list[tuple[tuple[str, str], int]]:
    """Cards per (path, compound), balanced over paths then compounds, scarcest pool first."""
    room = {}
    for key in product(PATHS, COMPOUNDS):
        pairs = Counter(_race_driver(record) for record in pools[key])
        room[key] = sum(
            min(n, PER_RACE_DRIVER - used[pair]) for pair, n in pairs.items()
        )
    paths = _shares(total, {p: sum(room[(p, c)] for c in COMPOUNDS) for p in PATHS})
    quota = Counter()
    for path in PATHS:
        quota.update(
            _shares(paths[path], {(path, c): room[(path, c)] for c in COMPOUNDS})
        )
    # scarce pools pick first, so large pools do not use up their race and driver pairs
    return sorted(quota.items(), key=lambda item: room[item[0]])


def select_cards(
    records: list[dict[str, Any]], total: int, rng: random.Random, used: Counter
) -> list[dict]:
    """Complete cards balanced over rule paths, then compounds, at most 2 per race and driver.

    `used` counts the cards each race and driver already gave, so calls can share the cap.
    """
    pools = defaultdict(list)
    for record in sorted(records, key=lambda r: r["card_id"]):
        path = path_of(record["card"]) if complete(record["card"]) else None
        if path:
            pools[(path, record["card"]["compound"])].append(record)
    for pool in pools.values():
        rng.shuffle(pool)
    chosen = []
    while len(chosen) < total:  # a second pass fills what the cap took from a quota
        before = len(chosen)
        for key, count in _quotas(pools, used, total - len(chosen)):
            for _ in range(count):
                if record := _take(pools[key], used):
                    chosen.append({**record, "path": key[0]})
        if len(chosen) == before:
            raise ValueError(f"only {len(chosen)} cards for {total} items")
    return chosen


def _item(
    record: dict[str, Any], kind: str, messages: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": record.get("path"),
        "card_id": record["card_id"],
        "card": record["card"],
        "messages": messages,
        "scope": None,
        "follow_up": None,
        "swap_field": None,
    }


def _turns(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    turns = []
    for question, answer in pairs:
        turns += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    return turns


def _call_question(card: dict[str, Any], rng: random.Random, use: str) -> str:
    return rng.choice(T.QUESTIONS[use]["call"]).format(
        car=card["driver_number"], lap=card["lap"]
    )


def call_item(
    record: dict[str, Any], kind: str, rng: random.Random, use: str
) -> dict[str, Any]:
    card = record["card"]
    question = _call_question(card, rng, use)
    return _item(record, kind, _turns((question, T.call_answer(card))))


def _stated_seconds(card: dict[str, Any]) -> float:
    """A gap behind on the other side of the rejoin threshold, so it would flip that test."""
    loss = card["pit_loss_seconds"]
    behind = card["gap_behind"]
    covers = behind["state"] == "NONE" or behind["seconds"] >= loss + 2.0
    return round(max(0.5, loss + 2.0 - 4.0) if covers else loss + 2.0 + 4.0, 1)


def multi_item(
    record: dict[str, Any], turn: int, rng: random.Random, use: str
) -> dict[str, Any]:
    """A call, then one follow-up: why, a field, a gap stated in the message or out of scope.

    A gap stated in the message gets the rule's answer on the card, and the WHY says the card
    decides: the card is the only source of race numbers.
    """
    card, questions = record["card"], T.QUESTIONS[use]
    first = (_call_question(card, rng, use), T.call_answer(card))
    style = ("why", "field", "stated", "out_of_scope")[turn % 4]
    if style == "why":
        second = (rng.choice(questions["why"]), T.call_answer(card))
    elif style == "field":
        field = list(questions["field"])[turn // 4 % len(questions["field"])]
        second = (questions["field"][field], T.field_answer(card, field))
    elif style == "stated":
        seconds = f"{_stated_seconds(card):.1f}"
        question = rng.choice(questions["stated"])
        second = (
            question.format(car=card["driver_number"], seconds=seconds),
            T.stated_answer(card, seconds),
        )
    else:
        category = ("weather", "live_race", "championship", "multi_stop")[turn // 4 % 4]
        question = rng.choice(questions["scope"][category]).format(
            car=card["driver_number"], other=""
        )
        second = (question, T.scope_answer(category, card))
    return {**_item(record, "multi", _turns(first, second)), "follow_up": style}


def _other_car(card: dict[str, Any], rng: random.Random) -> str:
    on_card = {card["driver_number"]}
    on_card |= {card[g].get("driver_number") for g in ("gap_ahead", "gap_behind")}
    return rng.choice([str(n) for n in range(1, 100) if str(n) not in on_card])


def scope_item(
    record: dict[str, Any], turn: int, rng: random.Random, use: str
) -> dict[str, Any]:
    card, category = record["card"], list(T.SCOPE)[turn % len(T.SCOPE)]
    other = _other_car(card, rng)
    question = rng.choice(T.QUESTIONS[use]["scope"][category]).format(
        car=card["driver_number"], other=other
    )
    item = _item(
        record,
        "out_of_scope",
        _turns((question, T.scope_answer(category, card, other))),
    )
    return {**item, "scope": category}


def track_item(record: dict[str, Any], rng: random.Random, use: str) -> dict[str, Any]:
    """A call question under a safety car or VSC, which the rule answers with NO CALL."""
    return {**call_item(record, "out_of_scope", rng, use), "scope": "track_status"}


def removed_item(
    record: dict[str, Any], kind: str, field: str, rng: random.Random, use: str
) -> dict:
    """A complete card with one field made unknown: required ("missing") or not ("decidable")."""
    changed = {**record, "card": remove_field(record["card"], field)}
    item = call_item(changed, kind, rng, use)
    item["removed_field"] = field
    return item
