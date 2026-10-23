"""The policy 2.0 prompt of the Replay: its numbers are the rule's constants."""

from __future__ import annotations

import re

from boxbox.model.policy2_prompt import policy2_instructions
from boxbox.rules.decision import REJOIN_MARGIN_SECONDS, TYRE_LIMITS
from boxbox.rules.policy2 import TYRE_LOSS_LIMITS


def test_every_constant_of_the_rule_is_in_the_text():
    text = policy2_instructions()
    for name, (low, high) in TYRE_LOSS_LIMITS.items():
        assert f"{name} {low} and {high}" in text
    for name, (young, old) in TYRE_LIMITS.items():
        assert f"{name} {young} and {old}" in text
    assert f"plus {REJOIN_MARGIN_SECONDS} seconds" in text
    assert not re.search(r"[{}]", text)  # nothing left to format


def test_every_branch_of_policy_2_0_is_described():
    text = policy2_instructions()
    for part in (
        "safety car (SC)",
        "virtual safety car (VSC)",
        "mandatory_stop_pending",
        "undercut reach",
        "cars_in_pit_window",
        "penalty_pending_seconds",
        "malformed NONE",
        "display only",
    ):
        assert part in text


def test_the_text_asks_for_a_choice_and_not_for_an_answer_format():
    text = policy2_instructions()
    assert "Return exactly two lines" not in text
    assert "dry track" not in text and "neutralised-race" not in text  # not policy 1.1
