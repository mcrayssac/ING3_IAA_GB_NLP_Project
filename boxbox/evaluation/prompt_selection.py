"""Validation-only corpus adaptation and exact prospective prompt selection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from copy import deepcopy
from fractions import Fraction

from boxbox.rules import decide, remove_field

from ._io import AXES, FAMILIES, LABELS, PROTOCOL_ID, PROTOCOL_VERSION, dumps
from .parsing import parse_response
from .records import card_state, corpus_case, validate_cases

SELECTION_PRIORITIES = (
    ("overall/strict_format_rate", 1),
    ("overall/unjustified_decision_rate", -1),
    ("overall/excessive_refusal_rate", -1),
    ("overall/macro_label_agreement", 1),
    ("overall/macro_family_agreement", 1),
    ("overall/call_agreement", 1),
)
_KINDS = {"complete", "missing", "decidable", "multi", "out_of_scope"}
_REMOVABLE = {"gap_ahead", "gap_behind", "pit_loss_seconds", "tyre_age_laps"}
_SCOPE = {
    "weather",
    "live_race",
    "betting",
    "championship",
    "radio",
    "other_car",
    "multi_stop",
    "unrelated",
    "track_status",
}


def validate_candidate_ids(candidate_ids: Sequence[str]) -> tuple[str, ...]:
    """Return the fixed lexical order; the caller must save it before generation."""
    if isinstance(candidate_ids, (str, bytes)) or not isinstance(
        candidate_ids, Sequence
    ):
        raise TypeError("candidate IDs must be a sequence of identifiers")
    if len(candidate_ids) < 2 or any(
        not isinstance(value, str) or not value or any(c.isspace() for c in value)
        for value in candidate_ids
    ):
        raise ValueError("declare at least two nonempty, whitespace-free candidate IDs")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate IDs must be distinct")
    return tuple(sorted(candidate_ids))


def adapt_validation(
    items: list[dict],
    source_records: list[dict],
    split_document: dict,
    history_turns: int = 3,
) -> list[dict]:
    """Adapt supplied validation data without reading files or asserting human review.

    The caller verifies the corpus manifest and loads exact JSON decimals. Source
    records and the full checked split document are mandatory. The stored target
    answer supplies contextual reference material, never model input. The adapter
    validates structure/policy consistency; it does not judge English or certify
    that a human reviewed these derived annotations.
    """
    if not isinstance(split_document.get("races"), dict) or not isinstance(
        split_document.get("splits", {}).get("validation"), list
    ):
        raise TypeError("the full checked split document is required")
    sources = {}
    for source in source_records:
        identifier = source.get("card_id")
        if not isinstance(identifier, str) or not identifier or identifier in sources:
            raise ValueError("missing or duplicate source card ID")
        if source.get("split") != "validation":
            raise ValueError("source records must belong to validation only")
        sources[identifier] = source
    seen, cases = set(), []
    for item in items:
        if item.get("split") != "validation":
            raise ValueError("prompt comparison accepts validation items only")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("missing or duplicate corpus item ID")
        seen.add(identifier)
        if item.get("card_id") not in sources:
            raise ValueError(f"{identifier}: missing source card/provenance")
        source = sources[item["card_id"]]
        source_card, card = source["card"], item["card"]
        provenance = source.get("provenance")
        race = f"{source_card['race']['season']}-{source_card['race']['round']:02d}"
        metadata = split_document["races"].get(race)
        if (
            race not in split_document["splits"]["validation"]
            or not isinstance(metadata, dict)
            or not isinstance(provenance, dict)
            or not isinstance(provenance.get("source"), str)
            or not provenance["source"]
            or provenance.get("session_key") is None
            or provenance.get("session_key") != metadata.get("session_key")
            or provenance.get("cutoff_lap") != source_card["as_of_completed_lap"]
        ):
            raise ValueError(f"{identifier}: missing or inconsistent source provenance")
        kind, follow, scope = item.get("kind"), item.get("follow_up"), item.get("scope")
        if kind not in _KINDS:
            raise ValueError(f"{identifier}: unsupported corpus kind")
        removed = item.get("removed_field")
        if removed is not None and (
            kind not in {"missing", "decidable"} or removed not in _REMOVABLE
        ):
            raise ValueError(f"{identifier}: unsupported recorded card transformation")
        expected_card = remove_field(source_card, removed) if removed else source_card
        if dumps(card) != dumps(expected_card):
            raise ValueError(
                f"{identifier}: card differs from its recorded source/transformation"
            )
        messages = item.get("messages")
        turns = 2 if kind == "multi" else 1
        if not isinstance(messages, list) or len(messages) != 2 * turns:
            raise ValueError(f"{identifier}: unexpected corpus conversation length")
        if kind == "multi":
            if (
                follow not in {"why", "field", "stated", "out_of_scope"}
                or scope is not None
            ):
                raise ValueError(f"{identifier}: unsupported follow-up metadata")
        elif (
            follow is not None
            or (kind == "out_of_scope" and scope not in _SCOPE)
            or (kind != "out_of_scope" and scope is not None)
        ):
            raise ValueError(f"{identifier}: inconsistent scope/follow-up metadata")
        state = card_state(card)
        expected_state = {
            "complete": "complete",
            "missing": "blocking_incomplete",
            "decidable": "usable_incomplete",
        }.get(kind)
        if expected_state and state != expected_state:
            raise ValueError(
                f"{identifier}: corpus kind disagrees with card availability"
            )
        if scope == "track_status" and (
            card.get("track_status") not in {"SC", "VSC"}
            or state != "blocking_incomplete"
        ):
            raise ValueError(
                f"{identifier}: track-status probe is not a blocking SC/VSC card"
            )
        out_of_scope = follow == "out_of_scope" or (
            kind == "out_of_scope" and scope != "track_status"
        )
        history_sensitive = follow == "why"
        policy_call, policy_reason = decide(card)
        expected_call = "NO CALL" if out_of_scope else policy_call
        target = messages[-1].get("content")
        parsed = parse_response(target)
        if (
            not parsed["strict_format_valid"]
            or parsed["extracted_call"] != expected_call
        ):
            raise ValueError(
                f"{identifier}: stored target reference conflicts with policy/context"
            )
        why = target.replace("\r\n", "\n").removesuffix("\n").split("\n")[1][5:]
        requirement = (
            "Refuse the capability requested by the target message and explain the boundary stated in the corpus reference."
            if out_of_scope
            else "Explain the prior call using the current card and the supplied prior exchange."
            if history_sensitive
            else "Identify the contradictory gap assertion explicitly and use the current card for the call."
            if follow == "stated"
            else "Answer the field question from the current card while retaining its policy call."
            if follow == "field"
            else "Explain the policy call using the current card or its declared limits."
        )
        annotation = {
            "scenario_id": f"source:{item['card_id']}",
            "variant_id": f"removed:{removed}" if removed else "original",
            "attributes": {
                "card_state": state,
                "follow_up": kind == "multi",
                "history_sensitive": history_sensitive,
                "out_of_scope": out_of_scope,
            },
            "primary_family": "out_of_scope"
            if out_of_scope
            else "follow_up"
            if kind == "multi"
            else state,
            "required_history_turns": int(history_sensitive),
            "applicability": {
                axis: history_sensitive
                if axis == "history"
                else out_of_scope
                if axis == "scope"
                else True
                for axis in AXES
            },
            "reference": {
                "policy_call": policy_call,
                "policy_reason": policy_reason,
                "expected_call": expected_call,
                "oracle": "message_annotation"
                if out_of_scope
                else "policy_with_follow_up_annotation"
                if kind == "multi"
                else "policy",
                "why_reference": why,
                "required_evidence": [
                    "Current race card and policy version, not user assertions.",
                    requirement,
                ],
                "history_requirement": requirement if history_sensitive else None,
                "scope_requirement": requirement if out_of_scope else None,
                "corpus_reference_response": target,
                "annotation_origin": "integrated_corpus_reference_and_documented_mapping",
                "annotation_review_status": "not_asserted_by_this_adapter",
            },
            "input_issue": "unsupported_context"
            if scope == "track_status"
            else "missing_required_field"
            if state == "blocking_incomplete"
            else None,
        }
        cases.append(
            corpus_case(
                item, annotation, "validation", history_turns, source_record=source
            )
        )
    validate_cases(cases, split_document)
    return cases


def validate_validation_population(cases: list[dict], split_document: dict) -> dict:
    """Check the full common population before any prompt outputs are observed."""
    if any(case.get("split") != "validation" for case in cases):
        raise ValueError("prompt selection accepts validation cases only")
    validate_cases(cases, split_document)
    labels = Counter(case["reference"]["expected_call"] for case in cases)
    families = Counter(case["primary_family"] for case in cases)
    missing_labels = sorted(set(LABELS) - labels.keys())
    missing_families = sorted(set(FAMILIES) - families.keys())
    if missing_labels or missing_families:
        raise ValueError(
            f"validation population is incomplete: labels={missing_labels}, families={missing_families}"
        )
    return {
        "targets": len(cases),
        "labels": dict(labels),
        "families": dict(families),
        "Z": labels["NO CALL"],
        "D": labels["BOX"] + labels["STAY OUT"],
        "race_ids": sorted({case["race_id"] for case in cases}),
    }


def _ratio(value: dict) -> Fraction:
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        raise ValueError("a selection metric needs an exact fraction")
    n, d = value["numerator"], value["denominator"]
    if type(n) is not int or type(d) is not int or d <= 0:
        raise ValueError("invalid exact fraction in selection metric")
    return Fraction(n, d)


def _selection_fraction(metric: dict) -> Fraction:
    if not isinstance(metric, dict) or metric.get("status") != "defined":
        raise ValueError("undefined or incomplete metric cannot select a prompt")
    exact = _ratio(metric.get("exact"))
    numerator, denominator = metric.get("numerator"), metric.get("denominator")
    if type(numerator) is int:
        numerator = Fraction(numerator)
    else:
        numerator = _ratio(numerator)
    if (
        type(denominator) is not int
        or denominator <= 0
        or numerator / denominator != exact
        or not 0 <= exact <= 1
    ):
        raise ValueError("selection metric counts disagree with its exact fraction")
    return exact


def select_prompt(summaries: dict[str, dict], candidate_ids: Sequence[str]) -> dict:
    """Rank already paired validation summaries; no rounded values or human tiebreak."""
    candidates = validate_candidate_ids(candidate_ids)
    if set(summaries) != set(candidates):
        raise ValueError("summaries must cover exactly the predeclared candidate IDs")
    values, coordinates = {}, {}
    for candidate in candidates:
        metrics = summaries[candidate].get("metrics", {})
        if any(name not in metrics for name, _ in SELECTION_PRIORITIES):
            raise ValueError(f"{candidate}: missing selection metric")
        fractions = [
            _selection_fraction(metrics[name]) for name, _ in SELECTION_PRIORITIES
        ]
        coordinates[candidate] = tuple(
            value * sign for value, (_, sign) in zip(fractions, SELECTION_PRIORITIES)
        )
        values[candidate] = {
            name: {"numerator": value.numerator, "denominator": value.denominator}
            for value, (name, _) in zip(fractions, SELECTION_PRIORITIES)
        }
    ranked = sorted(candidates, key=coordinates.__getitem__, reverse=True)
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "candidate_ids": list(candidates),
        "selected_candidate": ranked[0],
        "ranked_candidate_ids": ranked,
        "priorities": [
            {"metric": name, "direction": "higher" if sign > 0 else "lower"}
            for name, sign in SELECTION_PRIORITIES
        ],
        "exact_values": deepcopy(values),
        "tie_break": "smallest_predeclared_lexicographic_candidate_id",
        "interpretation": "Conservative validation-only selection; not an overall quality claim or final-study freeze.",
    }
