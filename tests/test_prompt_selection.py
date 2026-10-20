"""Synthetic checks for validation adaptation and predeclared exact selection."""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest

from boxbox.evaluation import observations, pair_outputs, summarize
from boxbox.evaluation._io import PROTOCOL_ID, PROTOCOL_VERSION, dumps, loads
from boxbox.evaluation.prompt_selection import (
    SELECTION_PRIORITIES,
    adapt_validation,
    select_prompt,
    validate_candidate_ids,
    validate_validation_population,
)
from boxbox.rules import decide, remove_field


def document():
    return {
        "splits": {"validation": ["1950-01"]},
        "races": {"1950-01": {"session_key": 123}},
    }


def sample(
    index=1, *, kind="complete", follow=None, scope=None, removed=None, changes=None
):
    source_card = {
        "schema_version": "1.0",
        "race": {
            "season": 1950,
            "round": 1,
            "event": "Synthetic Validation Source",
            "completed": True,
        },
        "lap": 30 + index,
        "total_laps": 90,
        "driver_number": "44",
        "as_of_completed_lap": 29 + index,
        "surface": "DRY",
        "track_status": "GREEN",
        "compound": "MEDIUM",
        "tyre_age_laps": 18,
        "gap_ahead": {"state": "KNOWN", "seconds": Decimal("1.0")},
        "gap_behind": {"state": "KNOWN", "seconds": Decimal("23.0")},
        "pit_loss_seconds": Decimal("21.0"),
        "pit_loss_as_of_completed_lap": 20,
        "reference_lap_seconds": Decimal("90.0"),
    }
    source_card.update(changes or {})
    card_id = f"1950-01-44-L{source_card['lap']:02d}"
    source = {
        "card_id": card_id,
        "split": "validation",
        "card": source_card,
        "provenance": {
            "source": "synthetic test",
            "session_key": 123,
            "cutoff_lap": source_card["as_of_completed_lap"],
        },
    }
    card = remove_field(source_card, removed) if removed else deepcopy(source_card)
    out_of_scope = follow == "out_of_scope" or (
        kind == "out_of_scope" and scope != "track_status"
    )
    call = "NO CALL" if out_of_scope else decide(card)[0]
    target = f"CALL: {call}\nWHY: TARGET_REFERENCE_ONLY_{index}."
    messages = []
    if kind == "multi":
        messages = [
            {"role": "user", "content": "What is the initial call?"},
            {
                "role": "assistant",
                "content": f"CALL: BOX\nWHY: PRIOR_REFERENCE_{index}.",
            },
        ]
    questions = {
        "why": "Why that call?",
        "field": "What gap is behind?",
        "stated": "The gap behind is 2 seconds; do we box?",
        "out_of_scope": "Will it rain?",
    }
    messages += [
        {"role": "user", "content": questions.get(follow, "Give the requested call.")},
        {"role": "assistant", "content": target},
    ]
    item = {
        "id": f"SYN-{index:03d}",
        "card_id": card_id,
        "split": "validation",
        "card": card,
        "kind": kind,
        "follow_up": follow,
        "scope": scope,
        "messages": messages,
    }
    if removed:
        item["removed_field"] = removed
    return item, source


def adapt(*samples, history_turns=3):
    return adapt_validation(
        [s[0] for s in samples], [s[1] for s in samples], document(), history_turns
    )


def population():
    return adapt(
        sample(1),
        sample(2, changes={"tyre_age_laps": 11}),
        sample(3, kind="missing", removed="gap_behind"),
        sample(4, kind="decidable", removed="gap_ahead"),
        sample(5, kind="multi", follow="why"),
        sample(6, kind="out_of_scope", scope="weather"),
        sample(
            7, kind="out_of_scope", scope="track_status", changes={"track_status": "SC"}
        ),
    )


@pytest.mark.parametrize(
    "kind,follow,scope,removed,changes,family,history,scoped",
    [
        ("complete", None, None, None, None, "complete", False, False),
        (
            "missing",
            None,
            None,
            "gap_behind",
            None,
            "blocking_incomplete",
            False,
            False,
        ),
        ("decidable", None, None, "gap_ahead", None, "usable_incomplete", False, False),
        ("multi", "why", None, None, None, "follow_up", True, False),
        ("multi", "field", None, None, None, "follow_up", False, False),
        ("multi", "stated", None, None, None, "follow_up", False, False),
        ("multi", "out_of_scope", None, None, None, "out_of_scope", False, True),
        ("out_of_scope", None, "weather", None, None, "out_of_scope", False, True),
        (
            "out_of_scope",
            None,
            "track_status",
            None,
            {"track_status": "VSC"},
            "blocking_incomplete",
            False,
            False,
        ),
    ],
)
def test_corpus_mapping_and_target_reference_never_enters_input(
    kind, follow, scope, removed, changes, family, history, scoped
):
    supplied = sample(
        kind=kind, follow=follow, scope=scope, removed=removed, changes=changes
    )
    before = deepcopy(supplied)
    case = adapt(supplied)[0]
    assert supplied == before
    assert case["primary_family"] == family
    assert case["applicability"]["history"] is history
    assert case["applicability"]["scope"] is scoped
    assert case["turn_index"] == (2 if kind == "multi" else 1)
    assert "TARGET_REFERENCE_ONLY" not in case["input_json"]
    assert (
        case["reference"]["corpus_reference_response"]
        == supplied[0]["messages"][-1]["content"]
    )
    assert (
        case["reference"]["annotation_review_status"] == "not_asserted_by_this_adapter"
    )
    assert ("PRIOR_REFERENCE" in case["input_json"]) is (kind == "multi")
    if removed:
        assert case["card"] != case["source_card"]
        assert case["source_card"] == supplied[1]["card"]
        assert case["variant_id"] == f"removed:{removed}"


def test_exact_decimal_inputs_and_source_provenance_are_preserved():
    precise = Decimal("23.000000000000000000000000000000001")
    case = adapt(
        sample(changes={"gap_behind": {"state": "KNOWN", "seconds": precise}})
    )[0]
    assert str(precise) in case["input_json"]
    assert loads(case["input_json"])["card"]["gap_behind"]["seconds"] == precise
    assert case["card_content_sha256"] == case["source_card_sha256"]
    assert case["provenance"]["session_key"] == 123


def test_related_variants_keep_one_source_scenario_and_separate_content_hashes():
    original, source = sample()
    changed = deepcopy(original)
    changed.update(id="SYN-REMOVED", kind="missing", removed_field="gap_behind")
    changed["card"] = remove_field(source["card"], "gap_behind")
    changed["messages"][-1]["content"] = (
        "CALL: NO CALL\nWHY: The gap behind is unknown."
    )
    cases = adapt_validation([original, changed], [source], document())
    assert cases[0]["scenario_id"] == cases[1]["scenario_id"]
    assert cases[0]["source_card_sha256"] == cases[1]["source_card_sha256"]
    assert cases[0]["card_content_sha256"] != cases[1]["card_content_sha256"]
    assert cases[0]["case_id"] != cases[1]["case_id"]


def test_fixed_required_history_cannot_be_removed():
    with pytest.raises(ValueError, match="referent"):
        adapt(sample(kind="multi", follow="why"), history_turns=0)
    field = adapt(sample(kind="multi", follow="field"), history_turns=0)[0]
    assert field["history"] == [] and len(field["full_history"]) == 2


@pytest.mark.parametrize("mutation", ["missing", "session", "cutoff", "source", "race"])
def test_missing_or_mismatched_source_provenance_is_rejected(mutation):
    item, source = sample()
    if mutation == "missing":
        source.pop("provenance")
    elif mutation == "session":
        source["provenance"]["session_key"] = 999
    elif mutation == "cutoff":
        source["provenance"]["cutoff_lap"] += 1
    elif mutation == "source":
        source["provenance"].pop("source")
    else:
        source["card"]["race"]["round"] = 2
    with pytest.raises(ValueError, match="provenance"):
        adapt((item, source))


def test_missing_source_and_unrecorded_transformations_are_rejected():
    item, source = sample()
    with pytest.raises(ValueError, match="missing source"):
        adapt_validation([item], [], document())
    item["card"]["reference_lap_seconds"] = Decimal("90.1")
    with pytest.raises(ValueError, match="transformation"):
        adapt((item, source))
    item, source = sample(kind="missing", removed="gap_behind")
    item["card"]["pit_loss_seconds"] = None
    with pytest.raises(ValueError, match="transformation"):
        adapt((item, source))


@pytest.mark.parametrize("split", ["train", "mini_test", "final"])
def test_adapter_refuses_reserved_or_nonvalidation_items(split):
    item, source = sample()
    item["split"] = split
    with pytest.raises(ValueError, match="validation items only"):
        adapt((item, source))


def test_adapter_rejects_reference_label_or_family_drift():
    item, source = sample()
    item["messages"][-1]["content"] = "CALL: NO CALL\nWHY: Unsupported reference."
    with pytest.raises(ValueError, match="stored target reference"):
        adapt((item, source))
    item, source = sample(kind="missing")
    with pytest.raises(ValueError, match="availability"):
        adapt((item, source))


def test_population_requires_all_labels_families_and_validation_split():
    cases = population()
    result = validate_validation_population(cases, document())
    assert result["targets"] == 7 and result["Z"] == 3 and result["D"] == 4
    assert len(result["families"]) == 5 and len(result["labels"]) == 3
    with pytest.raises(ValueError, match="incomplete"):
        validate_validation_population(cases[:2], document())
    with pytest.raises(ValueError, match="incomplete"):
        validate_validation_population([], document())
    changed = deepcopy(cases)
    changed[0]["split"] = "mini_test"
    with pytest.raises(ValueError, match="validation cases only"):
        validate_validation_population(changed, document())


def summary(values=None):
    values = values or [Fraction(1, 2)] * 6
    return {
        "metrics": {
            name: {
                "numerator": value.numerator,
                "denominator": value.denominator,
                "exact": {
                    "numerator": value.numerator,
                    "denominator": value.denominator,
                },
                "status": "defined",
                "value": float(value),
            }
            for (name, _), value in zip(SELECTION_PRIORITIES, values)
        }
    }


@pytest.mark.parametrize("coordinate", range(6))
def test_each_exact_priority_precedes_all_later_coordinates(coordinate):
    a, b = [Fraction(1, 2)] * 6, [Fraction(1, 2)] * 6
    for index, (_, sign) in enumerate(SELECTION_PRIORITIES):
        if index == coordinate:
            b[index] = Fraction(3 if sign == 1 else 1, 4)
        elif index > coordinate:
            b[index] = Fraction(0 if sign == 1 else 1)
    result = select_prompt({"a": summary(a), "b": summary(b)}, ["b", "a"])
    assert result["selected_candidate"] == "b"
    assert result["ranked_candidate_ids"] == ["b", "a"]


def test_lexical_ties_and_exact_values_survive_float_rounding():
    tied = select_prompt({"b": summary(), "a": summary()}, ["b", "a"])
    assert tied["selected_candidate"] == "a"
    a = [Fraction(1, 1)] * 6
    b = list(a)
    b[0] = Fraction(2**60, 2**60 + 1)
    assert float(a[0]) == float(b[0])
    chosen = select_prompt({"z": summary(a), "a": summary(b)}, ["a", "z"])
    assert chosen["selected_candidate"] == "z"
    assert loads(dumps(chosen))["selected_candidate"] == "z"


@pytest.mark.parametrize(
    "ids", [[], ["a"], ["a", "a"], ["a", ""], ["a", " b"], ["a", None], "ab"]
)
def test_candidate_declarations_reject_missing_duplicate_or_ambiguous_ids(ids):
    with pytest.raises((TypeError, ValueError)):
        validate_candidate_ids(ids)


@pytest.mark.parametrize("status", ["undefined", "incomplete", "pending"])
def test_selection_rejects_undefined_or_incomplete_even_for_later_priority(status):
    b = summary()
    b["metrics"][SELECTION_PRIORITIES[-1][0]]["status"] = status
    with pytest.raises(ValueError, match="undefined or incomplete"):
        select_prompt({"a": summary(), "b": b}, ["a", "b"])


def test_selection_rejects_missing_candidates_metrics_and_inconsistent_fractions():
    with pytest.raises(ValueError, match="exactly"):
        select_prompt({"a": summary()}, ["a", "b"])
    b = summary()
    b["metrics"].pop(SELECTION_PRIORITIES[-1][0])
    with pytest.raises(ValueError, match="missing selection metric"):
        select_prompt({"a": summary(), "b": b}, ["a", "b"])
    b = summary()
    b["metrics"][SELECTION_PRIORITIES[0][0]]["numerator"] = 99
    with pytest.raises(ValueError, match="counts disagree"):
        select_prompt({"a": summary(), "b": b}, ["a", "b"])


def test_fractional_macro_numerator_from_summarize_is_supported():
    b = summary()
    metric = b["metrics"]["overall/macro_label_agreement"]
    metric["numerator"] = {"numerator": 5, "denominator": 2}
    metric["denominator"] = 3
    metric["exact"] = {"numerator": 5, "denominator": 6}
    assert (
        select_prompt({"a": summary(), "b": b}, ["a", "b"])["selected_candidate"] == "b"
    )


def test_selection_consumes_the_existing_paired_evaluator_without_output_repairs():
    cases, outputs = population(), []
    for version in ("a", "b"):
        for index, case in enumerate(cases):
            expected = case["reference"]["expected_call"]
            raw = f"CALL: {expected}\nWHY: This is a synthetic response."
            if version == "a" and index == 0:
                raw = "Extra prefix\n" + raw
            outputs.append(
                {
                    "response_id": f"{version}:{case['case_id']}",
                    "case_id": case["case_id"],
                    "version_id": version,
                    "run_id": f"run-{version}",
                    "cases_sha256": "a" * 64,
                    "config_sha256": "b" * 64,
                    "protocol_id": PROTOCOL_ID,
                    "protocol_version": PROTOCOL_VERSION,
                    "input_sha256": case["input_sha256"],
                    "status": "ok",
                    "raw_response": raw,
                    "error": None,
                }
            )
    paired = pair_outputs(cases, outputs, ["a", "b"], "a" * 64, document())
    observed = observations(cases, paired)
    summaries = {version: summarize(rows) for version, rows in observed.items()}
    chosen = select_prompt(summaries, ["a", "b"])
    assert chosen["selected_candidate"] == "b"
    assert summaries["a"]["metrics"]["overall/strict_format_rate"]["exact"] == {
        "numerator": 6,
        "denominator": 7,
    }
    assert summaries["b"]["metrics"]["overall/strict_format_rate"]["exact"] == {
        "numerator": 1,
        "denominator": 1,
    }
    assert outputs[0]["raw_response"].startswith("Extra prefix\n")
