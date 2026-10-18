"""Boundary and example checks for the task 1.4 reference policy."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from boxbox.rules import decide, format_answer
from boxbox.rules.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
CONVERSATIONS = json.loads(
    (ROOT / "reference/fixtures.json").read_text(encoding="utf-8"), parse_float=Decimal
)["conversations"]
CARDS = {case["id"]: case["card"] for case in CONVERSATIONS}
CLI_CARDS = {
    case["id"]: case["card"]
    for case in json.loads(
        (ROOT / "reference/fixtures.json").read_text(encoding="utf-8")
    )["conversations"]
}


def changed(base: str = "box_old", **fields: object) -> dict[str, object]:
    card = copy.deepcopy(CARDS[base])
    card.update(fields)
    return card


def call(card: object) -> str:
    return decide(card)[0]


def test_five_conversation_fixtures_and_output_shape() -> None:
    assert len(CONVERSATIONS) == 5
    document = (ROOT / "docs/race-card-contract.md").read_text(encoding="utf-8")
    for case in CONVERSATIONS:
        card = case["card"]
        assert all(set(message) == {"role", "content"} for message in case["messages"])
        roles = [message["role"] for message in case["messages"]]
        assert roles == ["user", "assistant"] * (len(roles) // 2)
        answers = case["messages"][1::2]
        for answer, card_policy in zip(answers, case["card_policy"], strict=True):
            expected = answer["content"]
            lines = expected.splitlines()
            assert len(lines) == 2
            assert lines[0] in {"CALL: BOX", "CALL: STAY OUT", "CALL: NO CALL"}
            assert lines[1].startswith("WHY: ")
            assert lines[1].endswith(".")
            assert expected.replace("\n", "\n   ") in document
            if card_policy:
                assert format_answer(card) == expected
            elif case["id"] == "medium_safe":
                assert lines[0] == "CALL: " + call(card)
            else:
                assert lines[0] == "CALL: NO CALL"


@pytest.mark.parametrize(
    ("age", "expected"),
    [(11, "STAY OUT"), (12, "NO CALL"), (17, "NO CALL"), (18, "BOX")],
)
def test_age_boundaries(age: int, expected: str) -> None:
    card = changed(tyre_age_laps=age, gap_ahead={"state": "UNKNOWN", "seconds": None})
    assert call(card) == expected


def test_tyre_age_counts_earlier_sessions() -> None:
    assert call(changed(lap=1, as_of_completed_lap=0, tyre_age_laps=3)) == "STAY OUT"
    assert call(changed(tyre_age_laps=30)) == "BOX"


def test_display_fields_never_change_the_call() -> None:
    for case in CONVERSATIONS:
        bare = copy.deepcopy(case["card"])
        del bare["reference_lap_seconds"]
        for field in ("gap_ahead", "gap_behind"):
            bare[field].pop("driver_number", None)
        assert decide(bare) == decide(case["card"])


def test_irrelevant_missing_fields() -> None:
    assert call(changed("stay_young", gap_ahead=None, gap_behind=None)) == "STAY OUT"
    assert call(changed(gap_ahead=None)) == "BOX"
    assert call(changed("stay_young", gap_ahead={"state": "NONE"})) == "NO CALL"
    assert call(changed(gap_ahead={"state": "NONE"})) == "NO CALL"


@pytest.mark.parametrize(
    ("gap", "expected"),
    [(Decimal("1.99"), "BOX"), (Decimal("2.0"), "BOX"), (Decimal("2.01"), "STAY OUT")],
)
def test_ahead_threshold(gap: Decimal, expected: str) -> None:
    assert (
        call(changed("medium_safe", gap_ahead={"state": "KNOWN", "seconds": gap}))
        == expected
    )


def test_ahead_states() -> None:
    assert (
        call(changed("medium_safe", gap_ahead={"state": "NONE", "seconds": None}))
        == "STAY OUT"
    )
    for invalid in ({"state": "NONE"}, {"state": "NONE", "seconds": 0}):
        assert format_answer(changed("medium_safe", gap_ahead=invalid)).startswith(
            "CALL: NO CALL\n"
        )
    assert (
        call(changed("medium_safe", gap_ahead={"state": "UNKNOWN", "seconds": None}))
        == "NO CALL"
    )
    assert (
        call(changed("medium_safe", gap_ahead={"state": "KNOWN", "seconds": -1}))
        == "NO CALL"
    )


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        (Decimal("22.99"), "STAY OUT"),
        (Decimal("23.0"), "BOX"),
        (Decimal("23.01"), "BOX"),
    ],
)
def test_rejoin_threshold(gap: Decimal, expected: str) -> None:
    assert call(changed(gap_behind={"state": "KNOWN", "seconds": gap})) == expected


def test_behind_states() -> None:
    assert "22.99-second" in format_answer(
        changed(gap_behind={"state": "KNOWN", "seconds": Decimal("22.99")})
    )
    assert (
        call(
            changed(
                gap_behind={"state": "NONE", "seconds": None}, pit_loss_seconds=None
            )
        )
        == "BOX"
    )
    for invalid in ({"state": "NONE"}, {"state": "NONE", "seconds": 0}):
        assert format_answer(
            changed(gap_behind=invalid, pit_loss_seconds=None)
        ).startswith("CALL: NO CALL\n")
    assert call(changed(gap_behind={"state": "UNKNOWN", "seconds": None})) == "NO CALL"
    assert call(changed(gap_behind={"state": "KNOWN", "seconds": None})) == "NO CALL"


@pytest.mark.parametrize(
    ("card", "expected"),
    [
        (
            changed(
                "medium_safe",
                gap_ahead={"state": "KNOWN", "seconds": Decimal("2.0000000000000001")},
            ),
            "STAY OUT",
        ),
        (
            changed(
                gap_behind={"state": "KNOWN", "seconds": Decimal("22.9999999999999999")}
            ),
            "STAY OUT",
        ),
        (
            changed(
                gap_behind={"state": "KNOWN", "seconds": Decimal(23)},
                pit_loss_seconds=Decimal(21),
            ),
            "BOX",
        ),
        (
            changed(
                gap_behind={"state": "KNOWN", "seconds": Decimal(23)},
                pit_loss_seconds=Decimal("21.0000000000000000000000000001"),
            ),
            "STAY OUT",
        ),
    ],
)
def test_direct_decimal_values(card: dict[str, object], expected: str) -> None:
    assert call(card) == expected


@pytest.mark.parametrize(
    ("base", "field", "number", "expected"),
    [
        ("medium_safe", "gap_ahead", "2.0000000000000001", "STAY OUT"),
        ("box_old", "gap_behind", "22.9999999999999999", "STAY OUT"),
    ],
)
def test_cli_preserves_json_decimal_precision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    base: str,
    field: str,
    number: str,
    expected: str,
) -> None:
    card = copy.deepcopy(CLI_CARDS[base])
    card[field] = {"state": "KNOWN", "seconds": "__NUMBER__"}
    source = json.dumps(card).replace('"__NUMBER__"', number)
    path = tmp_path / "card.json"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["boxbox.rules", str(path)])
    assert main() == 0
    assert capsys.readouterr().out.startswith(f"CALL: {expected}\nWHY: ")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_cli_rejects_nonfinite_json_constants(
    tmp_path: Path,
    constant: str,
) -> None:
    card = copy.deepcopy(CLI_CARDS["stay_young"])
    card["pit_loss_seconds"] = "__NUMBER__"
    source = json.dumps(card).replace('"__NUMBER__"', constant)
    path = tmp_path / "card.json"
    path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "boxbox.rules", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"Cannot read card: Invalid JSON constant: {constant}\n"


def test_pit_loss_missing_invalid_and_future_cutoff() -> None:
    assert call(changed(pit_loss_seconds=None)) == "NO CALL"
    assert call(changed(pit_loss_seconds=True)) == "NO CALL"
    assert call(changed(pit_loss_seconds=float("nan"))) == "NO CALL"
    assert call(changed(pit_loss_seconds=Decimal("Infinity"))) == "NO CALL"
    assert call(changed(pit_loss_as_of_completed_lap=None)) == "NO CALL"
    assert call(changed(pit_loss_as_of_completed_lap=30)) == "NO CALL"
    assert call(changed(pit_loss_as_of_completed_lap=28)) == "BOX"


def test_scope_identity_and_malformed_card() -> None:
    assert call(changed(surface="WET")) == "NO CALL"
    assert call(changed(track_status="SC")) == "NO CALL"
    assert call(changed(compound="INTERMEDIATE")) == "NO CALL"
    assert call(changed(compound=[])) == "NO CALL"
    assert call(changed(tyre_age_laps=True)) == "NO CALL"
    assert call(changed(tyre_age_laps=-1)) == "NO CALL"
    assert call(changed(tyre_age_laps=18.0)) == "NO CALL"  # reconstruction must send 18
    assert call(changed(as_of_completed_lap=30)) == "NO CALL"
    assert (
        call(changed(race={**CARDS["box_old"]["race"], "completed": False}))
        == "NO CALL"
    )
    assert call({}) == "NO CALL"
    assert call(None) == "NO CALL"


@pytest.mark.parametrize(
    ("driver_number", "expected"),
    [
        ("1", "BOX"),
        ("99", "BOX"),
        ("01", "NO CALL"),
        ("00", "NO CALL"),
        ("100", "NO CALL"),
    ],
)
def test_driver_number_has_no_leading_zero(driver_number: str, expected: str) -> None:
    assert call(changed(driver_number=driver_number)) == expected
