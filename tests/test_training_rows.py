"""Training rows of task 2.6 render the exact inference prompt of the engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from boxbox.config import load_config
from boxbox.corpus import load_corpus
from boxbox.training import assistant_turns, build_rows

CONFIG = load_config(Path("configs/adapter-a.toml"))


def test_one_turn_per_assistant_message() -> None:
    items = {i["kind"]: i for i in load_corpus("A_train")}
    single, multi = assistant_turns(items["complete"]), assistant_turns(items["multi"])
    assert [len(history) for history, _, _ in single] == [0]
    assert [len(history) for history, _, _ in multi] == [0, 2]
    assert multi[1][0] == items["multi"]["messages"][:2]


@pytest.fixture(scope="module")
def engine():
    transformers = pytest.importorskip("transformers")
    from boxbox.model import ConversationEngine

    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            CONFIG.model_id, revision=CONFIG.model_revision, local_files_only=True
        )
    except OSError:
        pytest.skip("the pinned tokenizer is not cached")

    class NoWeights:  # rows need the tokenizer only; the engine asks for parameters
        config = None

        def parameters(self):
            return iter(())

    prompt = Path("configs/prompts/p01-policy-first.txt").read_text(encoding="utf-8")
    return ConversationEngine(
        NoWeights(), tokenizer, CONFIG, instructions=prompt, device="cpu"
    )


def test_rows_match_inference_and_train_on_answers_only(engine) -> None:
    rows = build_rows(engine, load_corpus("A_train"), CONFIG.lora.max_length)
    assert len(rows) == 480  # 320 single-turn items and 80 two-turn items
    end = engine.tokenizer.eos_token_id
    for row in rows:
        start = row["completion_mask"].index(1)
        assert row["completion_mask"] == [0] * start + [1] * (
            len(row["input_ids"]) - start
        )
        assert row["input_ids"][-1] == end  # the answer stops where generation stops
    item = load_corpus("A_train")[0]
    prompt = engine.prepare(
        item["card"], [], item["messages"][0]["content"], fixed_history=True
    )
    assert (
        rows[0]["input_ids"][: rows[0]["completion_mask"].index(1)]
        == prompt.input_ids[0].tolist()
    )
    assert (
        len(build_rows(engine, load_corpus("validation"), CONFIG.lora.max_length))
        == 120
    )


def test_rows_refuse_what_does_not_fit(engine) -> None:
    with pytest.raises(ValueError, match="over max_length"):
        build_rows(engine, load_corpus("A_train")[:1], 100)
