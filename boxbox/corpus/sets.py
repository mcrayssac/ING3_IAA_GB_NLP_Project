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
    _take,
    call_item,
    complete,
    multi_item,
    path_of,
    remove_field,
    removed_item,
    scope_item,
    select_cards,
    track_item,
    why_item,
)
from .templates import stated_answer

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
    "final": {  # task 4.1: about 200 targets, twice validation
        "complete": 60,
        "missing": 40,
        "decidable": 30,
        "multi": 40,
        "out_of_scope": 30,
    },
}
TRACK_ITEMS = {"train": 15, "validation": 4, "mini_test": 2, "final": 8}
# Inside "multi" of the final set: a "why" follow-up on a blocking card, then on a usable
# incomplete card, so the 40-target review of protocol section 8 can fill its follow-up
# slots (2 blocking, 2 usable, 4 complete, all history-sensitive).
INCOMPLETE_WHY = {"final": {"blocking": 8, "usable": 8}}
PREFIXES = {"validation": "V", "mini_test": "M", "final": "F"}
EVAL_CAP = 6  # cards per race and driver in an evaluation set: three capped pools of 2
# The final races have SC/VSC cards but none with every other decision field known
# (team decision on #20): their track-status items take any SC/VSC card that the rule
# stops on the track status, even with another field unknown.
ANY_TRACK_CARD = {"final"}
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


def _rest(records: list[dict[str, Any]], *chosen: list[dict]) -> list[dict[str, Any]]:
    """The records not chosen yet."""
    ids = {r["card_id"] for group in chosen for r in group}
    return [r for r in records if r["card_id"] not in ids]


def _pick(records, keep, count, rng, used) -> list[dict[str, Any]]:
    """Random cards whose card passes `keep`, under the race and driver cap in `used`."""
    pool = [r for r in sorted(records, key=lambda r: r["card_id"]) if keep(r["card"])]
    rng.shuffle(pool)
    chosen = []
    while len(chosen) < count and (record := _take(pool, used)):
        chosen.append({**record, "path": path_of(record["card"])})
    return chosen


def _neutral(card: dict[str, Any]) -> bool:
    """A safety car or VSC card whose decision fields are all known, so only rule 1 decides."""
    known = (
        complete({**card, "track_status": "GREEN"})
        and card["tyre_age_laps"] is not None
    )
    return card["track_status"] != "GREEN" and known


def track_card(card: dict[str, Any]) -> bool:
    """An SC or VSC card that the rule answers NO CALL because of the track status."""
    return card["track_status"] != "GREEN" and decide(card)[1].startswith(
        "The card does not show green-flag running"
    )


def track_rule(split: str):
    """The card test of a split's track-status items: neutral, or any SC/VSC card."""
    return track_card if split in ANY_TRACK_CARD else _neutral


def corpus_a(records: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """400 dialogues: 260 complete calls, 80 with a follow-up, 60 out of scope."""
    rng, used = random.Random(f"{seed}-A"), Counter()
    calls = select_cards(records, A_KINDS["complete"], rng, used)
    follows = select_cards(_rest(records, calls), A_KINDS["multi"], rng, used)
    rest = _rest(records, calls, follows)
    asked = A_KINDS["out_of_scope"] - TRACK_ITEMS["train"]
    requests = _pick(rest, complete, asked, rng, used)
    neutral = _pick(rest, _neutral, TRACK_ITEMS["train"], rng, used)
    rng.shuffle(calls)  # selection order groups the pools; swaps and styles must not
    rng.shuffle(follows)
    items = [call_item(r, "complete", rng, "train") for r in calls]
    items += [multi_item(r, i, rng, "train") for i, r in enumerate(follows)]
    items += [scope_item(r, i, rng, "train") for i, r in enumerate(requests)]
    items += [track_item(r, rng, "train") for r in neutral]
    tag_swaps(items[: A_KINDS["complete"]], SWAPS)
    return _numbered(items, "A", "train")


def _natural(records, used, wanted, rng, count) -> list[dict[str, Any]]:
    """Real incomplete green cards whose call matches `wanted`, at most 2 per race and driver."""
    rest = [r for r in records if r["card_id"] not in used]

    def keep(card):
        green = card["track_status"] == "GREEN"
        return green and not complete(card) and wanted(decide(card))

    return _pick(rest, keep, count, rng, Counter())


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
        field = fields[i % len(fields)]
        items.append(removed_item(record, "decidable", field, rng, "eval"))
    return items


def eval_set(
    records: list[dict[str, Any]], split: str, seed: int
) -> list[dict[str, Any]]:
    """Every evaluation category, half real and half constructed for the incomplete ones."""
    kinds, rng = EVAL_KINDS[split], random.Random(f"{seed}-{split}")
    syn_missing, syn_decidable = kinds["missing"] // 2, kinds["decidable"] // 2
    asked = kinds["out_of_scope"] - TRACK_ITEMS[split]
    extra = INCOMPLETE_WHY.get(split, {})
    multis = kinds["multi"] - sum(extra.values())
    n = kinds["complete"] + multis + asked + syn_missing
    capped = Counter()
    cards = select_cards(records, n, rng, capped)
    rng.shuffle(cards)
    a, b, c = kinds["complete"], kinds["complete"] + multis, n - syn_missing
    items = [call_item(r, "complete", rng, "eval") for r in cards[:a]]
    items += [multi_item(r, i, rng, "eval") for i, r in enumerate(cards[a:b])]
    items += [scope_item(r, i, rng, "eval") for i, r in enumerate(cards[b:c])]
    for i, record in enumerate(cards[c:]):
        fields = REQUIRED[record["path"]]
        field = fields[i % len(fields)]
        items.append(removed_item(record, "missing", field, rng, "eval"))
    neutral = _pick(
        _rest(records, cards), track_rule(split), TRACK_ITEMS[split], rng, capped
    )
    items += [track_item(r, rng, "eval") for r in neutral]
    used = {r["card_id"] for r in cards + neutral}
    items += _irrelevant(records, used, rng, syn_decidable)
    used |= {item["card_id"] for item in items}
    missing = _natural(
        records, used, lambda d: "missing" in d[1], rng, kinds["missing"] - syn_missing
    )
    items += [call_item(r, "missing", rng, "eval") for r in missing]
    used |= {r["card_id"] for r in missing}
    decided = _natural(
        records,
        used,
        lambda d: d[0] != "NO CALL",
        rng,
        kinds["decidable"] - syn_decidable,
    )
    items += [call_item(r, "decidable", rng, "eval") for r in decided]
    if extra:
        used |= {r["card_id"] for r in decided}
        taken = Counter(_race_driver_of(i) for i in items)  # what the cap still allows
        for state in ("blocking", "usable"):
            whys = _why_incomplete(records, used, rng, extra[state], state, taken)
            used |= {item["card_id"] for item in whys}
            items += whys
    return _numbered(items, PREFIXES[split], split)


def _race_driver_of(item: dict[str, Any]) -> str:
    return item["card_id"].rsplit("-", 1)[0]


def _why_incomplete(records, used, rng, count, state, taken) -> list[dict[str, Any]]:
    """A call then "why" on a complete card with one field removed: required ("blocking",
    the rule gives NO CALL) or ignored on its path ("usable", the call stays).

    A race and driver gives a card only while it is under EVAL_CAP, counting the items
    already in the set (`taken`, updated here), so the set passes `check_set`."""
    fields = REQUIRED if state == "blocking" else IRRELEVANT
    pool = [
        {**r, "path": path_of(r["card"])}
        for r in sorted(records, key=lambda r: r["card_id"])
        if r["card_id"] not in used
        and complete(r["card"])
        and path_of(r["card"]) in fields
    ]
    rng.shuffle(pool)
    chosen = []
    for record in pool:
        if len(chosen) == count:
            break
        if taken[_race_driver_of(record)] < EVAL_CAP:
            taken[_race_driver_of(record)] += 1
            chosen.append(record)
    if len(chosen) < count:
        raise ValueError(
            f"only {len(chosen)} cards under the cap for {count} {state} why follow-ups"
        )
    return [
        why_item(r, fields[r["path"]][i % len(fields[r["path"]])], rng, "eval")
        for i, r in enumerate(chosen)
    ]


def _answer_errors(item: dict[str, Any]) -> list[str]:
    errors = []
    for message in item["messages"][1::2]:
        lines = message["content"].split("\n")
        why = lines[1] if len(lines) == 2 else ""
        if len(lines) != 2 or lines[0] not in CALLS or not why.startswith("WHY: "):
            errors.append("answer is not two CALL/WHY lines")
        elif not why.endswith(".") or re.search(r"\.\s+[A-Z]", why):
            errors.append("WHY is not one sentence")
    rule = format_answer(item["card"])
    by_rule = item["kind"] != "out_of_scope" or item["scope"] == "track_status"
    if by_rule and item["messages"][1]["content"] != rule:
        errors.append("first answer is not the rule's answer")
    if item["follow_up"] == "why" and item["messages"][3]["content"] != rule:
        errors.append("why follow-up is not the rule's answer on the card")
    if item["follow_up"] == "stated":
        seconds = re.search(r"\d+\.\d", item["messages"][2]["content"]).group()
        if item["messages"][3]["content"] != stated_answer(item["card"], seconds):
            errors.append("stated follow-up is not the rule's answer on the card")
    return errors


def check_set(
    items: list[dict[str, Any]],
    kinds: dict[str, int],
    races: set[str],
    cap: int,
    track: int,
    track_ok=_neutral,
) -> list[str]:
    """Every problem found in one set; an empty list means it passes.

    `track_ok` tests the card of each track-status item (`track_rule(split)`).
    """
    errors = [f"{i['id']}: {e}" for i in items for e in _answer_errors(i)]
    counts = Counter(item["kind"] for item in items)
    if dict(counts) != kinds:
        errors.append(f"kinds {dict(counts)} instead of {kinds}")
    tracks = [i for i in items if i["scope"] == "track_status"]
    if len(tracks) != track or any(not track_ok(i["card"]) for i in tracks):
        errors.append(
            f"{len(tracks)} track status items instead of {track} with valid cards"
        )
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


def check_incomplete_whys(items: list[dict[str, Any]], split: str) -> list[str]:
    """The final set's "why" follow-ups on incomplete cards, by state and rule answer."""
    wanted = INCOMPLETE_WHY.get(split, {})
    whys = [i for i in items if i["kind"] == "multi" and i.get("removed_field")]
    blocking = [i for i in whys if decide(i["card"])[0] == "NO CALL"]
    errors = [
        f"{i['id']}: follow-up on an incomplete card is not a why"
        for i in whys
        if i["follow_up"] != "why"
    ]
    counts = {"blocking": len(blocking), "usable": len(whys) - len(blocking)}
    if counts != {k: wanted.get(k, 0) for k in ("blocking", "usable")}:
        errors.append(f"why follow-ups on incomplete cards {counts}, not {wanted}")
    return errors


def check_corpus_a(items: list[dict[str, Any]], races: set[str]) -> list[str]:
    errors = check_set(items, A_KINDS, races, PER_RACE_DRIVER, TRACK_ITEMS["train"])
    errors += [
        f"{i['id']}: card not complete"
        for i in items
        if not complete(i["card"]) and i["scope"] != "track_status"
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


def _wording(text: str) -> str:
    return re.sub(r"\d+(\.\d+)?", "#", text)  # car numbers, laps and seconds aside


def check_unseen(
    train: list[dict[str, Any]], *evaluation: list[dict[str, Any]]
) -> list[str]:
    """Evaluation items with a question whose wording, numbers aside, is also in corpus A."""
    seen = {_wording(m["content"]) for i in train for m in i["messages"][0::2]}
    return [
        f"{i['id']}: question wording also in corpus A"
        for items in evaluation
        for i in items
        if any(_wording(m["content"]) in seen for m in i["messages"][0::2])
    ]
