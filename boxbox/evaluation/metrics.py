"""Exact point estimates and validation of supplied, never generated, ratings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from ._io import AXES, FAMILIES, LABELS

DIRECTIONS = {
    "unjustified_decision_rate": "lower",
    "excessive_refusal_rate": "lower",
    "unusable_label_rate": "lower",
    "response_failure_rate": "lower",
    "decision_coverage": "descriptive",
}
MACROS = {
    "overall/macro_label_agreement": tuple(f"label/{v}/call_agreement" for v in LABELS),
    "overall/macro_family_agreement": tuple(
        f"family/{v}/call_agreement" for v in FAMILIES
    ),
}


@dataclass(frozen=True)
class Measure:
    numerator: int | Fraction
    denominator: int
    reason: str | None = None

    @property
    def exact(self) -> Fraction | None:
        return Fraction(self.numerator, self.denominator) if self.denominator else None

    def as_dict(self) -> dict:
        n = Fraction(self.numerator)
        value = self.exact
        return {
            "numerator": n.numerator
            if n.denominator == 1
            else {"numerator": n.numerator, "denominator": n.denominator},
            "denominator": self.denominator,
            "value": float(value) if value is not None else None,
            "exact": {"numerator": value.numerator, "denominator": value.denominator}
            if value is not None
            else None,
            "status": "incomplete"
            if self.reason == "incomplete_ratings"
            else "undefined"
            if value is None
            else "defined",
            "reason": "no_rated_scores"
            if not self.denominator and self.reason == "incomplete_ratings"
            else self.reason
            if self.reason
            else ("empty_population" if value is None else None),
        }


def validate_rating(
    rating: dict,
    case: dict,
    allow_synthetic: bool = False,
    *,
    response: dict | None = None,
) -> None:
    """Accept explicit human annotations, or clearly separated calibration expectations."""
    status = rating["rating_status"]
    if status not in {"pending", "completed", "synthetic_expected"}:
        raise ValueError("unknown rating_status")
    if rating.get("applicability") != case["applicability"]:
        raise ValueError("rating applicability disagrees with case")
    if set(rating["scores"]) != set(AXES) or set(rating["reasons"]) != set(AXES):
        raise ValueError("rating must contain all five axes and reasons")
    if status == "synthetic_expected":
        if (
            not allow_synthetic
            or rating.get("annotation_kind") != "synthetic_expected"
            or rating.get("rater_id") is not None
            or rating.get("rated_at") is not None
        ):
            raise ValueError("synthetic scores cannot stand for actual human ratings")
    elif status == "completed":
        if (
            not isinstance(rating.get("rater_id"), str)
            or not rating["rater_id"].strip()
        ):
            raise ValueError("completed rating requires an actual rater")
        stamp = datetime.fromisoformat(rating["rated_at"])
        if stamp.tzinfo is None:
            raise ValueError("rating timestamp requires a timezone")
    for axis in AXES:
        score, reason = rating["scores"][axis], rating["reasons"][axis]
        if not isinstance(reason, str):
            raise TypeError("rating reason must be text")
        if not case["applicability"][axis]:
            if score != "N/A" or not reason.strip():
                raise ValueError("non-applicable axes require N/A and a reason")
        elif score is None:
            if status != "pending":
                raise ValueError("completed applicable rating is missing")
        elif type(score) is not int or score not in (0, 1, 2) or not reason.strip():
            raise ValueError("applicable rating requires integer 0/1/2 and a reason")
    failed_response = response is not None and (
        response["status"] != "ok" or not (response["raw_response"] or "").strip()
    )
    if failed_response and any(
        rating["scores"][axis] not in (None, 0)
        for axis in AXES
        if case["applicability"][axis]
    ):
        raise ValueError(
            "empty/error outputs require applicable zeros or pending ratings"
        )


def observations(
    cases: list[dict],
    paired: dict,
    ratings: list[dict] | None = None,
    review_case_ids: list[str] | None = None,
    allow_synthetic: bool = False,
    rating_phase: str = "initial",
) -> dict[str, list[dict]]:
    index = {case["case_id"]: case for case in cases}
    selected = set(review_case_ids or [])
    if ratings is not None and review_case_ids is None:
        raise ValueError("ratings require the preselected review case IDs")
    if len(selected) != len(review_case_ids or []) or not selected <= index.keys():
        raise ValueError("invalid/duplicate selected review IDs")
    if rating_phase not in {"initial", "adjudicated"}:
        raise ValueError("rating phase must be initial or adjudicated")
    known_responses = {
        row["response_id"]: (version, cid)
        for version, outputs in paired.items()
        for cid, row in outputs.items()
    }
    notes = {}
    for rating in ratings or []:
        if rating.get("rating_phase", "initial") != rating_phase:
            continue
        rid = rating["response_id"]
        if rid not in known_responses or rid in notes:
            raise ValueError("unknown/duplicate rating response")
        version, cid = known_responses[rid]
        if rating["case_id"] != cid or cid not in selected:
            raise ValueError("rating does not match selected target")
        if rating.get("version_id", version) != version:
            raise ValueError("rating version mismatch")
        validate_rating(
            rating, index[cid], allow_synthetic, response=paired[version][cid]
        )
        notes[rid] = rating
    return {
        version: [
            {
                **case,
                **outputs[case["case_id"]],
                "review_selected": case["case_id"] in selected,
                "review": notes.get(outputs[case["case_id"]]["response_id"]),
            }
            for case in cases
        ]
        for version, outputs in paired.items()
    }


def _completed(row: dict) -> bool:
    return bool(row.get("review")) and row["review"]["rating_status"] in {
        "completed",
        "synthetic_expected",
    }


def measures(rows: list[dict], human: bool = False) -> dict[str, Measure]:
    n = len(rows)
    z = [row for row in rows if row["reference"]["expected_call"] == "NO CALL"]
    d = [row for row in rows if row["reference"]["expected_call"] != "NO CALL"]

    def pred(row: dict) -> str | None:
        return row["extracted_call"]

    def decisions(pool: list[dict]) -> int:
        return sum(pred(row) in LABELS[:2] for row in pool)

    result = {
        "strict_format_rate": Measure(
            sum(row["strict_format_valid"] for row in rows), n
        ),
        "call_label_validity": Measure(sum(pred(row) in LABELS for row in rows), n),
        "call_agreement": Measure(
            sum(pred(row) == row["reference"]["expected_call"] for row in rows), n
        ),
        "justified_abstention_call_rate": Measure(
            sum(pred(r) == "NO CALL" for r in z), len(z)
        ),
        "unjustified_decision_rate": Measure(decisions(z), len(z)),
        "excessive_refusal_rate": Measure(sum(pred(r) == "NO CALL" for r in d), len(d)),
        "decision_coverage": Measure(decisions(rows), n),
        "eligible_decision_coverage": Measure(decisions(d), len(d)),
        "unusable_label_rate": Measure(sum(pred(r) is None for r in rows), n),
        "response_failure_rate": Measure(
            sum(
                r["status"] != "ok" or not (r["raw_response"] or "").strip()
                for r in rows
            ),
            n,
        ),
    }
    if human:
        selected = [r for r in rows if r.get("review_selected")]
        completed = [r for r in selected if _completed(r)]
        incomplete = any(not _completed(r) for r in selected)
        reason = "incomplete_ratings" if incomplete else None
        result["why_supported_rate"] = Measure(
            sum(r["review"]["scores"]["factuality"] == 2 for r in completed),
            len(completed),
            reason,
        )
        abstentions = [
            r for r in completed if r["reference"]["expected_call"] == "NO CALL"
        ]
        result["justified_abstention_review_rate"] = Measure(
            sum(
                r["strict_format_valid"]
                and pred(r) == "NO CALL"
                and all(
                    r["review"]["scores"][axis] == 2
                    for axis in ("correctness", "factuality", "history", "scope")
                    if r["applicability"][axis]
                )
                for r in abstentions
            ),
            len(abstentions),
            reason,
        )
        for axis in AXES:
            applicable = [r for r in selected if r["applicability"][axis]]
            scores = [
                r["review"]["scores"][axis]
                for r in applicable
                if r.get("review") and type(r["review"]["scores"][axis]) is int
            ]
            pending = len(scores) != len(applicable) or any(
                not _completed(r) for r in applicable
            )
            axis_reason = (
                "no_applicable_scores"
                if not applicable
                else "incomplete_ratings"
                if pending
                else None
            )
            result[f"human_{axis}_mean"] = Measure(
                sum(scores), len(scores), axis_reason
            )
    return result


def all_measures(rows: list[dict], human: bool = False) -> dict[str, Measure]:
    groups = {"overall": rows}
    groups.update(
        {f"family/{f}": [r for r in rows if r["primary_family"] == f] for f in FAMILIES}
    )
    groups.update(
        {
            f"label/{v}": [r for r in rows if r["reference"]["expected_call"] == v]
            for v in LABELS
        }
    )
    groups["eligibility/Z"] = [
        r for r in rows if r["reference"]["expected_call"] == "NO CALL"
    ]
    groups["eligibility/D"] = [
        r for r in rows if r["reference"]["expected_call"] != "NO CALL"
    ]
    result = {
        f"{group}/{name}": metric
        for group, subset in groups.items()
        for name, metric in measures(subset, human).items()
    }
    for name, components in MACROS.items():
        values = [result[key].exact for key in components]
        result[name] = (
            Measure(sum(values, Fraction()), len(values))
            if all(value is not None for value in values)
            else Measure(0, 0)
        )
    return result


def summarize(rows: list[dict], human: bool = False) -> dict:
    metrics = all_measures(rows, human)
    result = {
        "metrics": {
            name: {
                **metric.as_dict(),
                "direction": DIRECTIONS.get(name.rsplit("/", 1)[-1], "higher"),
            }
            for name, metric in metrics.items()
        },
        "confusion": {
            expected: {
                predicted: sum(
                    r["reference"]["expected_call"] == expected
                    and (r["extracted_call"] or "INVALID") == predicted
                    for r in rows
                )
                for predicted in (*LABELS, "INVALID")
            }
            for expected in LABELS
        },
        "attribute_counts": {
            "follow_up_by_card_state": {
                state: sum(
                    r["attributes"]["follow_up"]
                    and r["attributes"]["card_state"] == state
                    for r in rows
                )
                for state in FAMILIES[:3]
            },
            "out_of_scope_follow_up": sum(
                r["attributes"]["out_of_scope"] and r["attributes"]["follow_up"]
                for r in rows
            ),
        },
    }
    for name, components in MACROS.items():
        result["metrics"][name]["missing_components"] = [
            component for component in components if metrics[component].exact is None
        ]
    if human:
        selected = [r for r in rows if r.get("review_selected")]
        result["rating_population"] = (
            "synthetic_expected"
            if any(
                r.get("review") and r["review"]["rating_status"] == "synthetic_expected"
                for r in selected
            )
            else "supplied_human_ratings"
        )
        result["axes"] = {}
        for axis in AXES:
            applicable = [r for r in selected if r["applicability"][axis]]
            scores = [
                r["review"]["scores"][axis] for r in applicable if r.get("review")
            ]
            rated = [score for score in scores if type(score) is int]
            result["axes"][axis] = {
                "selected": len(selected),
                "applicable": len(applicable),
                "rated": len(rated),
                "missing": len(applicable) - len(rated),
                "not_applicable": len(selected) - len(applicable),
                "counts": {str(v): rated.count(v) for v in range(3)},
                "mean": metrics[f"overall/human_{axis}_mean"].as_dict(),
            }
    return result
