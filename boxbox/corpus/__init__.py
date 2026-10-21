"""Training and evaluation dialogues built from the race cards (tasks 2.2 and 3.1)."""

from .build import complete, path_of, remove_field
from .load import load_corpus
from .sets import (
    A_KINDS,
    EVAL_KINDS,
    INCOMPLETE_WHY,
    TRACK_ITEMS,
    check_corpus_a,
    check_incomplete_whys,
    check_set,
    check_unseen,
    corpus_a,
    eval_set,
)
from .variants import B_SHARED, check_corpus_b, corpus_b, exposure, pairs

__all__ = [
    "A_KINDS",
    "B_SHARED",
    "EVAL_KINDS",
    "INCOMPLETE_WHY",
    "TRACK_ITEMS",
    "check_corpus_a",
    "check_corpus_b",
    "check_incomplete_whys",
    "check_set",
    "check_unseen",
    "complete",
    "corpus_a",
    "corpus_b",
    "eval_set",
    "exposure",
    "load_corpus",
    "pairs",
    "path_of",
    "remove_field",
]
