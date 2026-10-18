"""Corpus A and the evaluation sets, with the checks every build runs."""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from typing import Any

from boxbox.rules import decide, format_answer

from .build import (
    IRRELEVANT,
    PATHS,
    PER_RACE_DRIVER,
    REQUIRED,
    call_item,
    complete,
    multi_item,
    path_of,
    remove_field,
    removed_item,
    scope_item,
    select_cards,
)

A_KINDS = {"complete": 260, "multi": 80, "out_of_scope": 60}
SWAPS = 60  # complete A items that 3.1 turns into missing-field variants for corpus B
EVAL_KINDS = {
    "validation": {
        "complete": 30,
        "missing": 20,
        "decidable": 15,
        "multi": 20,
        "out_of_scope": 15,
    },
    "mini_test": {
        "complete": 12,
        "missing": 8,
        "decidable": 6,
        "multi": 8,
        "out_of_scope": 6,
    },
}
CALLS = {"CALL: BOX", "CALL: STAY OUT", "CALL: NO CALL"}


def _numbered(
    items: list[dict[str, Any]], prefix: str, split: str
) -> list[dict[str, Any]]:
    return [
        {"id": f"{prefix}-{i:03d}", "split": split, **item}
        for i, item in enumerate(items, 1)
    ]


def tag_swaps(items: list[dict[str, Any]], count: int) -> None:
    """Mark `count` complete items, spread over the paths, with a field the rule needs."""
    pools = defaultdict(list)
    for item in items:
        pools[item["path"]].append(item)
    tagged = 0
    while tagged < count:
        if not any(pools.values()):
            raise ValueError(f"only {tagged} items can carry a swap field")
        for path in PATHS:
            if not pools[path] or tagged == count:
                continue
            item = pools[path].pop(0)
            for field in (
                REQUIRED[path][tagged % len(REQUIRED[path]) :] + REQUIRED[path]
            ):
                if decide(remove_field(item["card"], field))[0] == "NO CALL":
                    item["swap_field"] = field
                    tagged += 1
                    break


def corpus_a(records: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """400 dialogues: 260 complete calls, 80 with a follow-up, 60 out of scope."""
    rng = random.Random(f"{seed}-A")
    cards = select_cards(records, sum(A_KINDS.values()), rng)
    rng.shuffle(cards)
    first, second = A_KINDS["complete"], A_KINDS["complete"] + A_KINDS["multi"]
    items = [call_item(r, "complete", rng) for r in cards[:first]]
    items += [multi_item(r, i, rng) for i, r in enumerate(cards[first:second])]
    items += [scope_item(r, i, rng) for i, r in enumerate(cards[second:])]
    tag_swaps(items[:first], SWAPS)
    return _numbered(items, "A", "train")


def _natural(records, used, wanted, rng, count) -> list[dict[str, Any]]:
    """Real incomplete green cards whose call matches `wanted`, at most 2 per race and driver."""
    pool = [
        r
        for r in sorted(records, key=lambda r: r["card_id"])
        if r["card_id"] not in used
        and not complete(r["card"])
        and r["card"]["track_status"] == "GREEN"
        and wanted(decide(r["card"]))
    ]
    rng.shuffle(pool)
    chosen, per = [], Counter()
    for record in pool:
        key = record["card_id"].rsplit("-", 1)[0]
        if per[key] < PER_RACE_DRIVER and len(chosen) < count:
            per[key] += 1
            chosen.append({**record, "path": path_of(record["card"])})
    return chosen


def _irrelevant(records, used, rng, count) -> list[dict[str, Any]]:
    """Complete cards on paths with a field the rule ignores, each with that field removed."""
    pool = [
        {**r, "path": path_of(r["card"])}
        for r in sorted(records, key=lambda r: r["card_id"])
        if r["card_id"] not in used
        and complete(r["card"])
        and path_of(r["card"]) in IRRELEVANT
    ]
    rng.shuffle(pool)
    items = []
    for i, record in enumerate(pool[:count]):
        fields = IRRELEVANT[record["path"]]
        items.append(removed_item(record, "decidable", fields[i % len(fields)], rng))
    return items


def eval_set(
    records: list[dict[str, Any]], split: str, seed: int
) -> list[dict[str, Any]]:
    """Every evaluation category, half real and half constructed for the incomplete ones."""
    kinds, rng = EVAL_KINDS[split], random.Random(f"{seed}-{split}")
    syn_missing, syn_decidable = kinds["missing"] // 2, kinds["decidable"] // 2
    n = kinds["complete"] + kinds["multi"] + kinds["out_of_scope"] + syn_missing
    cards = select_cards(records, n, rng)
    rng.shuffle(cards)
    a, b, c = kinds["complete"], kinds["complete"] + kinds["multi"], n - syn_missing
    items = [call_item(r, "complete", rng) for r in cards[:a]]
    items += [multi_item(r, i, rng) for i, r in enumerate(cards[a:b])]
    items += [scope_item(r, i, rng) for i, r in enumerate(cards[b:c])]
    for i, record in enumerate(cards[c:]):
        fields = REQUIRED[record["path"]]
        items.append(removed_item(record, "missing", fields[i % len(fields)], rng))
    used = {r["card_id"] for r in cards}
    items += _irrelevant(records, used, rng, syn_decidable)
    used |= {item["card_id"] for item in items}
    missing = _natural(
        records, used, lambda d: "missing" in d[1], rng, kinds["missing"] - syn_missing
    )
    items += [call_item(r, "missing", rng) for r in missing]
    used |= {r["card_id"] for r in missing}
    decided = _natural(
        records,
        used,
        lambda d: d[0] != "NO CALL",
        rng,
        kinds["decidable"] - syn_decidable,
    )
    items += [call_item(r, "decidable", rng) for r in decided]
    return _numbered(items, {"validation": "V", "mini_test": "M"}[split], split)


def _answer_errors(item: dict[str, Any]) -> list[str]:
    errors = []
    for message in item["messages"][1::2]:
        lines = message["content"].split("\n")
        why = lines[1] if len(lines) == 2 else ""
        if len(lines) != 2 or lines[0] not in CALLS or not why.startswith("WHY: "):
            errors.append("answer is not two CALL/WHY lines")
        elif not why.endswith(".") or re.search(r"\.\s+[A-Z]", why):
            errors.append("WHY is not one sentence")
    if item["kind"] != "out_of_scope" and item["messages"][1][
        "content"
    ] != format_answer(item["card"]):
        errors.append("first answer is not the rule's answer")
    return errors


def check_set(
    items: list[dict[str, Any]], kinds: dict[str, int], races: set[str], cap: int
) -> list[str]:
    """Every problem found in one set; an empty list means it passes."""
    errors = [f"{i['id']}: {e}" for i in items for e in _answer_errors(i)]
    counts = Counter(item["kind"] for item in items)
    if dict(counts) != kinds:
        errors.append(f"kinds {dict(counts)} instead of {kinds}")
    if len({i["card_id"] for i in items}) != len(items):
        errors.append("a card is used twice")
    per_race_driver = Counter(i["card_id"].rsplit("-", 1)[0] for i in items)
    if max(per_race_driver.values()) > cap:
        errors.append(
            f"a race and driver has {max(per_race_driver.values())} items (cap {cap})"
        )
    errors += [
        f"{i['id']}: race outside the split"
        for i in items
        if i["card_id"].rsplit("-", 2)[0] not in races
    ]
    for item in items:
        call = decide(item["card"])[0]
        if item["kind"] == "missing" and call != "NO CALL":
            errors.append(f"{item['id']}: missing item still gets {call}")
        if item["kind"] == "decidable" and call == "NO CALL":
            errors.append(f"{item['id']}: decidable item gets NO CALL")
    return errors


def check_corpus_a(items: list[dict[str, Any]], races: set[str]) -> list[str]:
    errors = check_set(items, A_KINDS, races, PER_RACE_DRIVER)
    errors += [
        f"{i['id']}: card not complete" for i in items if not complete(i["card"])
    ]
    swaps = [i for i in items if i["swap_field"]]
    if len(swaps) != SWAPS or any(i["kind"] != "complete" for i in swaps):
        errors.append(f"{len(swaps)} swap items instead of {SWAPS} complete ones")
    errors += [
        f"{i['id']}: removing {i['swap_field']} does not give NO CALL"
        for i in swaps
        if decide(remove_field(i["card"], i["swap_field"]))[0] != "NO CALL"
    ]
    return errors
