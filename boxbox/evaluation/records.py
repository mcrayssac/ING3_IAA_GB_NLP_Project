"""Immutable case inputs, source-ID adapters and complete output pairing."""

from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal
from typing import Any

from boxbox.rules import decide

from ._io import (
    AXES,
    FAMILIES,
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    loads,
    sha256,
)
from .parsing import parse_response


class PairingError(ValueError):
    """Every diagnosed pairing defect, with no inner-joined fallback."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("pairing_error: " + "; ".join(errors))


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def card_state(card: dict) -> str:
    """Classify availability after consulting the policy; do not copy its thresholds."""
    if decide(card)[0] == "NO CALL":
        return "blocking_incomplete"

    def seconds(value: Any) -> bool:
        return (
            type(value) in (int, float, Decimal)
            and Decimal(str(value)).is_finite()
            and Decimal(str(value)) >= 0
        )

    def known_gap(field: str) -> bool:
        gap = card.get(field)
        return isinstance(gap, dict) and (
            gap.get("state") == "KNOWN"
            and seconds(gap.get("seconds"))
            or gap.get("state") == "NONE"
            and "seconds" in gap
            and gap["seconds"] is None
        )

    cutoff = card.get("pit_loss_as_of_completed_lap")
    complete = (
        known_gap("gap_ahead")
        and known_gap("gap_behind")
        and seconds(card.get("pit_loss_seconds"))
        and type(cutoff) is int
        and 0 <= cutoff <= card["as_of_completed_lap"]
    )
    return "complete" if complete else "usable_incomplete"


def check_history(history: list[dict]) -> None:
    if not isinstance(history, list) or len(history) % 2:
        raise ValueError("history must contain complete user/assistant exchanges")
    for index, entry in enumerate(history):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"role", "content"}
            or entry["role"] != ("user" if index % 2 == 0 else "assistant")
            or not isinstance(entry["content"], str)
        ):
            raise ValueError(
                "history must be chronological same-card role/content exchanges"
            )


def prepare_case(case: dict, card: dict, history_turns: int = 3) -> dict:
    """Save common input bytes once; retain the full supplied history separately."""
    if type(history_turns) is not int or history_turns < 0:
        raise ValueError("history_turns must be a nonnegative integer")
    row = deepcopy(case)
    full = row.get("full_history", row["history"])
    check_history(full)
    needed = row.get(
        "required_history_turns", int(row["attributes"]["history_sensitive"])
    )
    if type(needed) is not int or needed < 0 or history_turns < needed:
        raise ValueError("history bound drops a declared required referent")
    row["full_history"] = full
    row["history"] = full[-2 * history_turns :] if history_turns else []
    row["card"] = deepcopy(card)
    row["input_json"] = dumps(
        {"card": row["card"], "history": row["history"], "message": row["message"]}
    )
    row["input_sha256"] = sha256(row["input_json"])
    row["card_content_sha256"] = sha256(dumps(card))
    return row


def validate_cases(
    cases: list[dict], race_splits: dict | None = None
) -> dict[str, dict]:
    """Validate the envelope and policy references without interpreting English."""
    by_id: dict[str, dict] = {}
    scenarios: dict[str, tuple[str, str]] = {}
    for case in cases:
        for key in ("case_id", "card_id", "race_id", "scenario_id", "variant_id"):
            if not _id(case.get(key)):
                raise ValueError(f"missing case identifier: {key}")
        cid = case["case_id"]
        if cid in by_id:
            raise ValueError(f"duplicate case_id: {cid}")
        split, race = case["split"], case["race_id"]
        if split not in {"synthetic", "train", "validation", "mini_test", "final"}:
            raise ValueError(f"{cid}: unknown split")
        if split == "synthetic":
            if not race.startswith("syn:"):
                raise ValueError(f"{cid}: synthetic race must use syn: namespace")
        else:
            card = case.get("source_card", case["card"])
            expected_race = f"{card['race']['season']}-{card['race']['round']:02d}"
            expected_card = f"{race}-{card['driver_number']}-L{card['lap']:02d}"
            if race != expected_race or case["card_id"] != expected_card:
                raise ValueError(f"{cid}: inconsistent source race/card identity")
            membership = (race_splits or {}).get("splits", race_splits or {})
            if race not in membership.get(split, []):
                raise ValueError(f"{cid}: race is not in the supplied accepted split")
            provenance = case.get("provenance")
            if not isinstance(provenance, dict) or not provenance:
                raise ValueError(f"{cid}: missing source provenance")
            if case.get("provenance_sha256") != sha256(dumps(provenance)) or case.get(
                "source_card_sha256"
            ) != sha256(dumps(card)):
                raise ValueError(f"{cid}: source provenance/card hash mismatch")
            metadata = (race_splits or {}).get("races", {}).get(race)
            if metadata and provenance.get("session_key") != metadata["session_key"]:
                raise ValueError(
                    f"{cid}: source session disagrees with the split manifest"
                )
        identity = (race, split)
        if scenarios.setdefault(case["scenario_id"], identity) != identity:
            raise ValueError(f"{cid}: scenario crosses races or splits")
        if type(case["turn_index"]) is not int or case["turn_index"] < 1:
            raise ValueError(f"{cid}: invalid target turn")
        check_history(case["history"])
        full = case.get("full_history", case["history"])
        check_history(full)
        if case["turn_index"] != len(full) // 2 + 1:
            raise ValueError(
                f"{cid}: target turn does not match the full supplied history"
            )
        if not _id(case["message"]):
            raise ValueError(f"{cid}: empty target message")
        attrs = case["attributes"]
        for flag in ("follow_up", "history_sensitive", "out_of_scope"):
            if type(attrs[flag]) is not bool:
                raise ValueError(f"{cid}: {flag} is not boolean")
        if attrs["follow_up"] != bool(full) or (
            attrs["history_sensitive"] and not case["history"]
        ):
            raise ValueError(f"{cid}: inconsistent history attributes")
        if attrs["card_state"] not in FAMILIES[:3]:
            raise ValueError(f"{cid}: invalid card state")
        family = (
            "out_of_scope"
            if attrs["out_of_scope"]
            else "follow_up"
            if attrs["follow_up"]
            else attrs["card_state"]
        )
        if case["primary_family"] != family:
            raise ValueError(f"{cid}: inconsistent primary family")
        applicability = {
            axis: (
                attrs["history_sensitive"]
                if axis == "history"
                else attrs["out_of_scope"]
                if axis == "scope"
                else True
            )
            for axis in AXES
        }
        if case["applicability"] != applicability or any(
            type(v) is not bool for v in case["applicability"].values()
        ):
            raise ValueError(f"{cid}: inconsistent applicability")
        call, reason = decide(case["card"])
        ref = case["reference"]
        if ref["policy_call"] != call or ref["policy_reason"] != reason:
            raise ValueError(f"{cid}: stale policy reference")
        if card_state(case["card"]) != attrs["card_state"]:
            raise ValueError(
                f"{cid}: card-state annotation disagrees with availability/policy"
            )
        expected = "NO CALL" if attrs["out_of_scope"] else call
        oracle = (
            "message_annotation"
            if attrs["out_of_scope"]
            else "policy_with_follow_up_annotation"
            if attrs["follow_up"]
            else "policy"
        )
        if ref["expected_call"] != expected or ref["oracle"] != oracle:
            raise ValueError(f"{cid}: inconsistent contextual reference")
        if not _id(ref.get("why_reference")):
            raise ValueError(f"{cid}: missing contextual explanation annotation")
        if (
            not _hash(case.get("input_sha256"))
            or sha256(case["input_json"]) != case["input_sha256"]
        ):
            raise ValueError(f"{cid}: input hash mismatch")
        inputs = loads(case["input_json"])
        expected_inputs = {key: case[key] for key in ("card", "history", "message")}
        if dumps(inputs) != dumps(expected_inputs):
            raise ValueError(f"{cid}: input bytes do not describe the ledger inputs")
        if case.get("card_content_sha256", sha256(dumps(case["card"]))) != sha256(
            dumps(case["card"])
        ):
            raise ValueError(f"{cid}: transformed card content hash mismatch")
        by_id[cid] = case
    return by_id


def corpus_case(
    item: dict,
    annotation: dict,
    split: str,
    history_turns: int = 3,
    *,
    source_record: dict | None = None,
) -> dict:
    """Adapt a supplied corpus item; perform no corpus or card-file I/O."""
    messages = item["messages"]
    if (
        not isinstance(messages, list)
        or len(messages) < 2
        or len(messages) % 2
        or any(
            m["role"] != ("user" if i % 2 == 0 else "assistant")
            for i, m in enumerate(messages)
        )
    ):
        raise ValueError("corpus item must end in complete user/assistant exchanges")
    row = deepcopy(annotation)
    if source_record is not None:
        if (
            source_record["card_id"] != item["card_id"]
            or source_record["split"] != split
        ):
            raise ValueError(
                "source record identity/split disagrees with the corpus item"
            )
        row["source_card"] = deepcopy(source_record["card"])
        row["source_card_sha256"] = sha256(dumps(source_record["card"]))
        row["provenance"] = deepcopy(source_record["provenance"])
        row["provenance_sha256"] = sha256(dumps(row["provenance"]))
    turn = len(messages) // 2
    row.update(
        case_id=f"eval:{PROTOCOL_VERSION}:{split}:{item['id']}:turn{turn}",
        card_id=item["card_id"],
        race_id=f"{item['card']['race']['season']}-{item['card']['race']['round']:02d}",
        split=split,
        turn_index=turn,
        history=deepcopy(messages[:-2]),
        full_history=deepcopy(messages[:-2]),
        message=messages[-2]["content"],
        corpus_metadata={
            key: item[key]
            for key in (
                "id",
                "kind",
                "scope",
                "follow_up",
                "removed_field",
                "swap_field",
            )
            if key in item
        },
    )
    return prepare_case(row, item["card"], history_turns)


def pair_outputs(
    cases: list[dict],
    outputs: list[dict],
    versions: list[str],
    cases_sha256: str,
    race_splits: dict | None = None,
) -> dict[str, dict[str, dict]]:
    """Require the full declared matrix, including explicitly logged model failures."""
    if (
        not versions
        or len(set(versions)) != len(versions)
        or not all(map(_id, versions))
    ):
        raise PairingError(["versions must be distinct nonempty identifiers"])
    if not _hash(cases_sha256):
        raise PairingError(["invalid case-ledger hash"])
    try:
        index = validate_cases(cases, race_splits)
    except (ValueError, KeyError, TypeError) as error:
        raise PairingError([str(error)]) from error
    paired = {version: {} for version in versions}
    seen, configs, errors = set(), {}, []
    for row in outputs:
        cid, version, rid = (
            row.get(k) for k in ("case_id", "version_id", "response_id")
        )
        if version not in paired or cid not in index:
            errors.append(f"unknown case/version: {cid}/{version}")
            continue
        if not _id(rid) or rid in seen or cid in paired[version]:
            errors.append(f"duplicate/invalid response identity: {cid}/{version}/{rid}")
            continue
        seen.add(rid)
        if (
            row.get("cases_sha256") != cases_sha256
            or row.get("input_sha256") != index[cid]["input_sha256"]
            or row.get("protocol_id") != PROTOCOL_ID
            or row.get("protocol_version") != PROTOCOL_VERSION
            or not _id(row.get("run_id"))
            or not _hash(row.get("config_sha256"))
        ):
            errors.append(f"inconsistent provenance: {cid}/{version}")
        configuration = (row.get("run_id"), row.get("config_sha256"))
        if configs.setdefault(version, configuration) != configuration:
            errors.append(f"mixed runs/configs within version: {version}")
        status, raw, error = (
            row.get("status"),
            row.get("raw_response"),
            row.get("error"),
        )
        if status == "ok":
            valid = isinstance(raw, str) and error is None
        elif status == "generation_error":
            valid = (raw is None or isinstance(raw, str)) and isinstance(error, dict)
            valid = valid and all(_id(error.get(k)) for k in ("code", "message"))
        else:
            valid = False
        if not valid:
            errors.append(f"invalid generation record: {cid}/{version}")
        paired[version][cid] = {**row, **parse_response(raw, status)}
    for version in versions:
        errors.extend(
            f"missing output: {cid}/{version}"
            for cid in index
            if cid not in paired[version]
        )
    if errors:
        raise PairingError(errors)
    return paired
