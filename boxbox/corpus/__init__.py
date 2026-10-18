"""Training and evaluation dialogues built from the race cards (tasks 2.2 and 3.1)."""

from .build import complete, path_of, remove_field
from .load import load_corpus
from .sets import (
    A_KINDS,
    EVAL_KINDS,
    TRACK_ITEMS,
    check_corpus_a,
    check_set,
    check_unseen,
    corpus_a,
    eval_set,
)

__all__ = [
    "A_KINDS",
    "EVAL_KINDS",
    "TRACK_ITEMS",
    "check_corpus_a",
    "check_set",
    "check_unseen",
    "complete",
    "corpus_a",
    "eval_set",
    "load_corpus",
    "path_of",
    "remove_field",
]
