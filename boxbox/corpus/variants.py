"""Corpus B: corpus A with its 60 swap items replaced by matched NO CALL variants (task 3.1).

B keeps every item of A at the same position. The 340 items without `swap_field` stay
byte for byte the same. Each of the 60 swap items becomes one variant: the same question
on the same card with the swap field made unknown, answered by the rule (NO CALL). The
variant keeps the source position, so A and B differ only by the intervention.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any

from boxbox.rules import decide, format_answer, remove_field

from .build import PATHS, REQUIRED
from .sets import SWAPS, _answer_errors

B_ITEMS = 400
B_SHARED = B_ITEMS - SWAPS  # 340 identical items, 85 %
VARIANT_SUFFIX = "-B"
# fields a variant may change; every other field must equal the source item
_CHANGED = {
    "id",
    "source_id",
    "kind",
    "card",
    "messages",
    "removed_field",
    "swap_field",
}


def variant(item: dict[str, Any]) -> dict[str, Any]:
    """The matched B item of a swap item: same question, swap field unknown, rule answer."""
    field = item["swap_field"]
    card = remove_field(item["card"], field)
    messages = copy.deepcopy(item["messages"])
    messages[1] = {"role": "assistant", "content": format_answer(card)}
    return {
        **copy.deepcopy(item),
        "id": item["id"] + VARIANT_SUFFIX,
        "source_id": item["id"],
        "kind": "missing",
        "card": card,
        "messages": messages,
        "removed_field": field,
        "swap_field": None,
    }


def corpus_b(a_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Corpus A with each swap item replaced by its variant, in the same order."""
    return [variant(i) if i["swap_field"] else copy.deepcopy(i) for i in a_items]


def pairs(b_items: list[dict[str, Any]]) -> dict[str, Any]:
    """The shared item IDs and every A/B pair, for the manifest and the review."""
    variants = [i for i in b_items if i.get("source_id")]
    return {
        "shared": [i["id"] for i in b_items if not i.get("source_id")],
        "pairs": [
            {"a": i["source_id"], "b": i["id"], "removed_field": i["removed_field"]}
            for i in variants
        ],
    }


def exposure(items: list[dict[str, Any]], count=len) -> dict[str, int]:
    """Size of what training shows: card and conversation, and the answers alone.

    `count` maps a text to its size: characters by default, a tokenizer's length for
    tokens. Training computes its loss on the answers only, hence the second total.
    The prompt template and system message add the same amount to every row.
    """
    total = completion = 0
    for item in items:
        total += count(json.dumps(item["card"], sort_keys=True))
        for message in item["messages"]:
            size = count(message["content"])
            total += size
            completion += size if message["role"] == "assistant" else 0
    return {"items": len(items), "total": total, "completion": completion}


def _variant_errors(source: dict[str, Any], item: dict[str, Any]) -> list[str]:
    field = item.get("removed_field")
    if field != source["swap_field"]:
        return [f"removes {field}, not the swap field {source['swap_field']}"]
    errors = []
    if source["kind"] != "complete" or item["kind"] != "missing":
        errors.append("is not a complete A item turned into a missing item")
    if field not in REQUIRED.get(source["path"], ()):
        errors.append(f"removes {field}, which the {source['path']} path does not need")
    if decide(source["card"])[0] == "NO CALL":
        errors.append("source card already gives NO CALL")
    if item["card"] != remove_field(source["card"], field):
        errors.append(f"card differs from the source by more than {field}")
    if decide(item["card"])[0] != "NO CALL":
        errors.append(f"still gets {decide(item['card'])[0]} without {field}")
    if item["messages"][0] != source["messages"][0] or len(item["messages"]) != 2:
        errors.append("question differs from the source item")
    if item["messages"][1]["content"] != format_answer(item["card"]):
        errors.append("answer is not the rule's answer on the variant card")
    others = {k: v for k, v in item.items() if k not in _CHANGED}
    if others != {k: v for k, v in source.items() if k not in _CHANGED}:
        errors.append("metadata differs from the source item")
    return errors + _answer_errors(item)


def check_corpus_b(
    a_items: list[dict[str, Any]], b_items: list[dict[str, Any]], races: set[str]
) -> list[str]:
    """Every problem in B against A; an empty list means B is the matched corpus."""
    if len(a_items) != B_ITEMS or len(b_items) != B_ITEMS:
        return [f"A has {len(a_items)} and B {len(b_items)} items instead of {B_ITEMS}"]
    errors = []
    shared = variants = 0
    for a, b in zip(a_items, b_items):
        if a["swap_field"]:
            variants += 1
            if b.get("source_id") != a["id"] or b["id"] != a["id"] + VARIANT_SUFFIX:
                errors.append(f"{a['id']}: B holds {b['id']} at its position")
                continue
            errors += [f"{b['id']}: {e}" for e in _variant_errors(a, b)]
        elif b == a:
            shared += 1
        else:
            errors.append(f"{a['id']}: B changes an item without a swap field")
    if (shared, variants) != (B_SHARED, SWAPS):
        errors.append(
            f"{shared} shared and {variants} variants instead of {B_SHARED} and {SWAPS}"
        )
    paths = Counter(b["path"] for b in b_items if b.get("source_id"))
    if set(paths) != set(PATHS) or len(set(paths.values())) != 1:
        errors.append(f"variants per path {dict(paths)} are not balanced")
    if len({b["id"] for b in b_items}) != B_ITEMS:
        errors.append("an ID is used twice in B")
    errors += [
        f"{b['id']}: race outside the train split"
        for b in b_items
        if b["card_id"].rsplit("-", 2)[0] not in races
    ]
    return errors
