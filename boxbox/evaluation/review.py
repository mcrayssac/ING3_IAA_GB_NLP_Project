"""Metadata-only constrained sampling and reproducible masked review exports."""

from __future__ import annotations

import csv
from collections import Counter
from copy import deepcopy
from pathlib import Path

from ._io import (
    AXES,
    FAMILIES,
    LABELS,
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    dumps,
    loads,
    sha256,
    write_json,
)
from .metrics import validate_rating

PREFIX = f"{PROTOCOL_ID}|{PROTOCOL_VERSION}|2026|"


class SamplingError(ValueError):
    def __init__(self, diagnostics: dict):
        self.diagnostics = diagnostics
        super().__init__(
            "sampling_error: no complete allocation; quotas and caps unchanged"
        )


def _candidate(case: dict) -> dict:
    attrs, ref = case.get("attributes", case), case.get("reference", case)
    row = {
        key: case[key]
        for key in ("case_id", "race_id", "scenario_id", "primary_family")
    }
    row.update(
        card_state=attrs["card_state"],
        history_sensitive=attrs["history_sensitive"],
        expected_call=ref["expected_call"],
        policy_call=ref["policy_call"],
    )
    if (
        any(
            not isinstance(v, str) or not v.strip()
            for k, v in row.items()
            if k != "history_sensitive"
        )
        or type(row["history_sensitive"]) is not bool
        or row["primary_family"] not in FAMILIES
        or row["card_state"] not in FAMILIES[:3]
        or row["expected_call"] not in LABELS
        or row["policy_call"] not in LABELS
    ):
        raise ValueError("invalid sampling metadata")
    if (
        (
            row["primary_family"] in FAMILIES[:3]
            and row["primary_family"] != row["card_state"]
        )
        or (row["policy_call"] == "NO CALL")
        != (row["card_state"] == "blocking_incomplete")
        or row["expected_call"]
        != (
            "NO CALL" if row["primary_family"] == "out_of_scope" else row["policy_call"]
        )
        or (row["primary_family"] in FAMILIES[:3] and row["history_sensitive"])
    ):
        raise ValueError("inconsistent sampling reference/state metadata")
    return row


def _slots() -> list[dict]:
    result = []
    for round_index in range(8):
        for family in FAMILIES:
            slot = {"family": family}
            if family in {"complete", "usable_incomplete"}:
                slot["expected_call"] = "BOX" if round_index < 4 else "STAY OUT"
            elif family in {"blocking_incomplete", "out_of_scope"}:
                slot["expected_call"] = "NO CALL"
            else:
                slot["card_state"] = (
                    "blocking_incomplete"
                    if round_index < 2
                    else "usable_incomplete"
                    if round_index < 4
                    else "complete"
                )
                slot["history_sensitive"] = True
            result.append(slot)
    return result


def _fits(row: dict, slot: dict) -> bool:
    return (
        row["primary_family"] == slot["family"]
        and all(row[key] == value for key, value in slot.items() if key != "family")
        and (slot["family"] != "out_of_scope" or row["policy_call"] in LABELS[:2])
    )


def _allocate(
    candidates: list[dict], slots: list[dict], race_cap: int, scenario_cap: int
) -> list[dict]:
    """Depth-first ranked search; the first solution is the prescribed allocation."""
    pool = sorted(candidates, key=lambda row: row["case_id"])
    if len({r["case_id"] for r in pool}) != len(pool):
        raise ValueError("duplicate sampling case ID")
    scenarios = {}
    for row in pool:
        if scenarios.setdefault(row["scenario_id"], row["race_id"]) != row["race_id"]:
            raise ValueError("sampling scenario crosses races")
    eligible = [[r for r in pool if _fits(r, slot)] for slot in slots]
    ranks = {r["case_id"]: sha256(PREFIX + "sample|" + r["case_id"]) for r in pool}
    used, races, scenes, failed = set(), Counter(), Counter(), set()
    selected, deepest = [], 0

    def available(row: dict) -> bool:
        return (
            row["case_id"] not in used
            and races[row["race_id"]] < race_cap
            and scenes[row["scenario_id"]] < scenario_cap
        )

    def search(index: int) -> bool:
        nonlocal deepest
        deepest = max(deepest, index)
        if index == len(slots):
            return True
        state = (index, frozenset(used))
        if state in failed:
            return False
        capacity: dict[str, tuple[int, list[dict]]] = {}
        union = {}
        for position in range(index, len(slots)):
            key = dumps(slots[position])
            if key not in capacity:
                capacity[key] = (0, [r for r in eligible[position] if available(r)])
            count, choices = capacity[key]
            capacity[key] = count + 1, choices
            union.update((r["case_id"], r) for r in choices)
        if any(len(choices) < count for count, choices in capacity.values()):
            failed.add(state)
            return False
        remaining = len(slots) - index
        race_pool = Counter(r["race_id"] for r in union.values())
        scene_pool = Counter(r["scenario_id"] for r in union.values())
        if (
            len(union) < remaining
            or sum(min(race_cap - races[r], n) for r, n in race_pool.items())
            < remaining
            or sum(min(scenario_cap - scenes[s], n) for s, n in scene_pool.items())
            < remaining
        ):
            failed.add(state)
            return False
        ordered = sorted(
            (r for r in eligible[index] if available(r)),
            key=lambda r: (
                races[r["race_id"]],
                scenes[r["scenario_id"]],
                ranks[r["case_id"]],
                r["case_id"],
            ),
        )
        for row in ordered:
            used.add(row["case_id"])
            races[row["race_id"]] += 1
            scenes[row["scenario_id"]] += 1
            selected.append(row)
            if search(index + 1):
                return True
            selected.pop()
            scenes[row["scenario_id"]] -= 1
            races[row["race_id"]] -= 1
            used.remove(row["case_id"])
        failed.add(state)
        return False

    if not search(0):
        raise SamplingError(
            {
                "candidate_count": len(pool),
                "required_slots": len(slots),
                "deepest_partial_allocation": deepest,
                "slot_capacities": [
                    {"slot": i, **slot, "candidates": len(eligible[i])}
                    for i, slot in enumerate(slots)
                ],
                "race_cap": race_cap,
                "scenario_cap": scenario_cap,
            }
        )
    return selected


def select_review_cases(cases: list[dict]) -> dict:
    candidates = [_candidate(case) for case in cases]
    selected = _allocate(candidates, _slots(), 8, 2)
    result = {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "seed": 2026,
        "selected_in_slot_order": [r["case_id"] for r in selected],
        "selected_case_ids": sorted(r["case_id"] for r in selected),
        "candidate_metadata_sha256": sha256(
            dumps(sorted(candidates, key=lambda r: r["case_id"]))
        ),
        "slots": _slots(),
        "targets": 40,
        "race_cap": 8,
        "scenario_cap": 2,
        "race_counts": dict(Counter(r["race_id"] for r in selected)),
        "scenario_counts": dict(Counter(r["scenario_id"] for r in selected)),
        "family_counts": dict(Counter(r["primary_family"] for r in selected)),
    }
    result["sampling_manifest_sha256"] = sha256(dumps(result))
    return result


def review_response_count(versions: list[str], drop_b_record: str | None = None) -> int:
    if set(versions) == {"baseline", "A", "B"} and len(versions) == 3:
        return 120
    if set(versions) == {"baseline", "A"} and len(versions) == 2 and drop_b_record:
        return 80
    raise ValueError(
        "review requires baseline/A/B, or baseline/A with an explicit B-drop record"
    )


def version_codes(versions: list[str]) -> dict[str, str]:
    if (
        not versions
        or len(set(versions)) != len(versions)
        or any(not v.strip() for v in versions)
    ):
        raise ValueError("invalid retained versions")
    ordered = sorted(versions, key=lambda v: (sha256(PREFIX + "mask|" + v), v))
    return {version: f"V{index:02d}" for index, version in enumerate(ordered, 1)}


IMMUTABLE_COLUMNS = (
    "review_id",
    "case_id",
    "turn_index",
    "version_code",
    "protocol_version",
    "rating_phase",
    "card_json",
    "history_json",
    "message",
    "reference_json",
    "applicability_json",
    "generation_status",
    "raw_response",
    "error_json",
)


def export_review(
    folder: Path,
    cases: list[dict],
    paired: dict,
    selected_ids: list[str],
    ratings: list[dict] | None = None,
    *,
    illustrative: bool = False,
    drop_b_record: str | None = None,
    rating_phase: str = "initial",
) -> dict:
    """Export raw text, pending score fields, and identity keys in separate files."""
    index = {c["case_id"]: c for c in cases}
    if (
        len(set(selected_ids)) != len(selected_ids)
        or not set(selected_ids) <= index.keys()
    ):
        raise ValueError("invalid review target selection")
    if len(selected_ids) == 40 and not illustrative:
        review_response_count(list(paired), drop_b_record)
    codes = version_codes(list(paired))
    if rating_phase not in {"initial", "adjudicated"}:
        raise ValueError("invalid rating phase")
    phase_notes = [
        r for r in ratings or [] if r.get("rating_phase", "initial") == rating_phase
    ]
    notes = {r["response_id"]: r for r in phase_notes}
    if len(notes) != len(phase_notes):
        raise ValueError("duplicate review annotations")
    known = {r["response_id"] for outputs in paired.values() for r in outputs.values()}
    if not notes.keys() <= known:
        raise ValueError("unknown annotation response")
    rows, lookup = [], {}
    presentation = sorted(
        ((cid, version) for cid in selected_ids for version in paired),
        key=lambda pair: (
            sha256(PREFIX + "present|" + pair[0] + "|" + codes[pair[1]]),
            pair[0],
            codes[pair[1]],
        ),
    )
    for ordinal, (cid, version) in enumerate(presentation, 1):
        case, response = index[cid], paired[version][cid]
        rid = f"R{ordinal:05d}"
        row = {
            "review_id": rid,
            "case_id": cid,
            "turn_index": str(case["turn_index"]),
            "version_code": codes[version],
            "protocol_version": PROTOCOL_VERSION,
            "rating_phase": rating_phase,
            "card_json": dumps(case["card"]),
            "history_json": dumps(case["history"]),
            "message": case["message"],
            "reference_json": dumps(case["reference"]),
            "applicability_json": dumps(case["applicability"]),
            "generation_status": response["status"],
            "raw_response": response["raw_response"]
            if response["raw_response"] is not None
            else "",
            "error_json": dumps(response["error"]),
            "rating_status": "pending",
            "rater_id": "",
            "rated_at": "",
            "sensitivity_flags": "",
            "second_review_json": "null",
            "adjudication_json": "null",
        }
        note = notes.get(response["response_id"])
        if note:
            if note["case_id"] != cid:
                raise ValueError("review annotation case mismatch")
            validate_rating(note, case, allow_synthetic=illustrative, response=response)
            for field in ("rating_status", "rater_id", "rated_at"):
                row[field] = note.get(field) or ""
            row["sensitivity_flags"] = dumps(note.get("sensitivity_flags", []))
            row["second_review_json"] = dumps(note.get("second_review"))
            row["adjudication_json"] = dumps(note.get("adjudication"))
        for axis in AXES:
            row[axis] = (
                note["scores"][axis]
                if note
                else None
                if case["applicability"][axis]
                else "N/A"
            )
            row[axis + "_reason"] = (
                note["reasons"][axis]
                if note
                else ""
                if case["applicability"][axis]
                else "This axis is not applicable to the target inputs."
            )
        lookup[rid] = {
            "response_id": response["response_id"],
            "run_id": response["run_id"],
            "version_id": version,
            "case_id": cid,
            "version_code": codes[version],
            "visible_input_sha256": sha256(
                dumps({k: row[k] for k in IMMUTABLE_COLUMNS})
            ),
        }
        rows.append(row)
    folder.mkdir(parents=True, exist_ok=False)
    columns = [
        *IMMUTABLE_COLUMNS,
        "rating_status",
        "rater_id",
        "rated_at",
        *[v for axis in AXES for v in (axis, axis + "_reason")],
        "sensitivity_flags",
        "second_review_json",
        "adjudication_json",
    ]
    with (folder / "review.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    write_json(folder / "version-key.json", codes)
    write_json(folder / "response-lookup.json", lookup)
    manifest = {
        "annotation_status": "illustrative_export"
        if illustrative
        else "pending_human_review",
        "targets": len(selected_ids),
        "responses": len(rows),
        "drop_b_record": drop_b_record,
        "selected_case_ids": sorted(selected_ids),
        "presentation_review_ids": [r["review_id"] for r in rows],
        "review_sheet_sha256": sha256((folder / "review.csv").read_bytes()),
        "limits": [
            "Seeded hashes are reproducible, not cryptographic blinding.",
            "Restrict key/config access during rating; style, context and errors may reveal identity.",
            "Raw text is never edited to hide identity.",
            "Synthetic expectations and blank sheets are not actual human ratings.",
        ],
    }
    write_json(folder / "manifest.json", manifest)
    return manifest


def import_review(
    sheet: Path, lookup: dict, cases: list[dict], *, illustrative: bool = False
) -> list[dict]:
    """Validate supplied notes while preserving raw inputs and separate adjudication."""
    index = {c["case_id"]: c for c in cases}
    result, seen = [], set()
    with sheet.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            rid = row["review_id"]
            if rid in seen or rid not in lookup:
                raise ValueError("unknown/duplicate review ID")
            seen.add(rid)
            link = lookup[rid]
            if (
                sha256(dumps({k: row[k] for k in IMMUTABLE_COLUMNS}))
                != link["visible_input_sha256"]
            ):
                raise ValueError("review inputs/raw output were altered")
            scores = {
                axis: None
                if row[axis] == ""
                else "N/A"
                if row[axis] == "N/A"
                else int(row[axis])
                for axis in AXES
            }
            note = {
                "review_id": rid,
                "case_id": row["case_id"],
                "response_id": link["response_id"],
                "version_id": link["version_id"],
                "protocol_version": row["protocol_version"],
                "rating_phase": row["rating_phase"],
                "rating_status": row["rating_status"],
                "rater_id": row["rater_id"] or None,
                "rated_at": row["rated_at"] or None,
                "applicability": deepcopy(index[row["case_id"]]["applicability"]),
                "scores": scores,
                "reasons": {axis: row[axis + "_reason"] for axis in AXES},
                "sensitivity_flags": loads(row["sensitivity_flags"] or "[]"),
                "second_review": loads(row["second_review_json"]),
                "adjudication": loads(row["adjudication_json"]),
            }
            if note["rating_status"] == "synthetic_expected":
                note["annotation_kind"] = "synthetic_expected"
            validate_rating(note, index[row["case_id"]], illustrative)
            result.append(note)
    if seen != lookup.keys():
        raise ValueError("missing review rows")
    return result
