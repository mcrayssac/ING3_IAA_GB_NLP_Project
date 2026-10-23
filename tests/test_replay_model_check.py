"""The check of OpenJev against policy 2.0: sample, tau and agreement, with no server."""

from __future__ import annotations

import json

import pytest

from boxbox.config import RunConfig
from boxbox.data.splits import FinalSplitClosedError, load_cards
from scripts import replay_model_check as M


def record(card_id: str, call: str, status: str = "GREEN", surface: str = "DRY"):
    card = {"call": call, "track_status": status, "surface": surface, "lap": 5}
    return {"card_id": card_id, "card": card}


def answered(reference, choice, probabilities, cell="BOX|GREEN", split="validation"):
    call = {"choice": choice, "probabilities": probabilities}
    return {
        "case_id": f"{split}-{reference}-{choice}-{cell}",
        "status": "ok",
        "answers": {"call": call},
        "reference": reference,
        "cell": cell,
        "split": split,
    }


def test_the_condition_is_sc_vsc_wet_or_green():
    assert M.condition({"track_status": "SC", "surface": "WET"}) == "SC"
    assert M.condition({"track_status": "VSC", "surface": "DRY"}) == "VSC"
    assert M.condition({"track_status": "GREEN", "surface": "WET"}) == "WET"
    assert M.condition({"track_status": "GREEN", "surface": "DRY"}) == "GREEN"


def test_the_sample_caps_each_cell_in_hash_order_whatever_the_input_order(monkeypatch):
    monkeypatch.setattr(M, "decide", lambda card: (card["call"], "why"))
    records = [record(f"c{i}", "BOX" if i % 2 else "STAY OUT") for i in range(20)]
    records += [record(f"s{i}", "BOX", status="SC") for i in range(4)]
    picked = M.pick(records, 3)
    cells = [(M.decide(r["card"])[0], M.condition(r["card"])) for r in picked]
    assert sorted(set(cells)) == [
        ("BOX", "GREEN"),
        ("BOX", "SC"),
        ("STAY OUT", "GREEN"),
    ]
    assert cells.count(("BOX", "GREEN")) == 3 and cells.count(("BOX", "SC")) == 3
    assert [r["card_id"] for r in M.pick(records[::-1], 3)] == [
        r["card_id"] for r in picked
    ]


def test_a_nan_card_reads_as_null_in_the_sample(monkeypatch):
    monkeypatch.setattr(M, "decide", lambda card: ("NO CALL", "why"))
    bad = record("n1", "NO CALL")
    bad["card"]["compound"] = float("nan")
    assert M.pick([bad], 5)[0]["card"]["compound"] is None


def test_only_open_splits_are_sampled_and_the_closed_ones_refuse(monkeypatch):
    assert set(M.SPLITS) == {"validation", "mini_test"}
    asked = []

    def fake_load(split, config, cards_dir, splits_path):
        asked.append(split)
        return []

    monkeypatch.setattr(M, "load_cards", fake_load)
    assert M.sample() == [] and asked == ["validation", "mini_test"]
    with pytest.raises(FinalSplitClosedError):
        load_cards("test_2026", RunConfig(), M.CARDS_V2, M.SPLITS_V2_FILE)


def test_tau_follows_the_rule_of_35_and_a_failed_request_is_a_miss():
    sure = {"BOX": 0.9, "STAY OUT": 0.05, "NO CALL": 0.05}
    weak = {"BOX": 0.5, "STAY OUT": 0.3, "NO CALL": 0.2}
    rows = [
        answered("BOX", "BOX", sure),
        answered("BOX", "BOX", weak),
        answered("NO CALL", "BOX", weak),  # an unjustified decision unless tau is high
        {"status": "request_error", "answers": None, "reference": "BOX", "cell": "x"},
    ]
    assert M.predicted(rows[0], 0.6) == "BOX" and M.predicted(rows[1], 0.6) == "NO CALL"
    assert M.predicted(rows[3], 0.6) is None
    points = M.curve(rows)
    chosen = M.choose_tau(points)
    # BOX 0.9 and NO CALL: the weak BOX (0.5) turns into NO CALL from tau 0.51 on, which
    # ties with tau 0 on agreement but has no unjustified decision, so 0.51 wins
    assert chosen["call_agreement"] == max(p["call_agreement"] for p in points) == 0.5
    assert (chosen["tau"], chosen["unjustified_decision_rate"]) == (0.51, 0.0)


def test_the_summary_counts_confusion_cells_and_errors():
    probabilities = {"BOX": 0.6, "STAY OUT": 0.3, "NO CALL": 0.1}
    rows = [
        answered("BOX", "BOX", probabilities, "BOX|GREEN"),
        answered("BOX", "STAY OUT", probabilities, "BOX|GREEN"),
        answered("STAY OUT", "STAY OUT", probabilities, "STAY OUT|SC"),
        {
            "status": "request_error",
            "answers": None,
            "reference": "BOX",
            "cell": "BOX|SC",
        },
    ]
    rows[1]["answers"]["call"]["choice"] = "STAY OUT"
    result = M.summary(rows, None)
    assert (result["cards"], result["agreed"], result["request_errors"]) == (4, 2, 1)
    assert result["by_cell"] == {
        "BOX|GREEN": [1, 2],
        "BOX|SC": [0, 1],
        "STAY OUT|SC": [1, 1],
    }
    assert result["confusion"]["BOX"] == {"BOX": 1, "STAY OUT": 1, "ERROR": 1}
    assert result["macro_label_agreement"] == pytest.approx((1 / 3 + 1) / 2)


def test_score_writes_the_run_summary_and_the_committed_agreement(
    tmp_path, monkeypatch
):
    sure = {"BOX": 0.9, "STAY OUT": 0.05, "NO CALL": 0.05}
    rows = [
        answered("BOX", "BOX", sure, "BOX|GREEN", "validation"),
        answered("STAY OUT", "BOX", sure, "STAY OUT|GREEN", "validation"),
        answered("BOX", "BOX", sure, "BOX|GREEN", "mini_test"),
    ]
    run = tmp_path / "run"
    run.mkdir()
    (run / "answers.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    sampled = [{"card_id": r["case_id"], "cell": r["cell"]} for r in rows]
    (run / "sample.jsonl").write_text("\n".join(json.dumps(s) for s in sampled) + "\n")
    (run / "manifest.json").write_text(
        json.dumps({"prompt_sha256": "p", "sample_sha256": "s", "per_cell": 25})
    )
    monkeypatch.setattr(M, "RESULT", tmp_path / "check.json")
    M.score(run, write=True)
    result = json.loads((run / "score.json").read_text())
    assert result["at_tau"]["validation"]["agreed"] == 1
    assert result["at_tau"]["mini_test"]["cards"] == 1
    kept = json.loads((tmp_path / "check.json").read_text())
    assert kept["agreement"] == {"validation": [1, 2], "mini_test": [1, 1]}
    assert kept["tau"] == result["tau"]
