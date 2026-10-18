"""Training and evaluation dialogues built from the race cards (tasks 2.2 and 3.1)."""

from .build import complete, path_of, remove_field
from .sets import A_KINDS, EVAL_KINDS, check_corpus_a, check_set, corpus_a, eval_set

__all__ = [
    "A_KINDS",
    "EVAL_KINDS",
    "check_corpus_a",
    "check_set",
    "complete",
    "corpus_a",
    "eval_set",
    "path_of",
    "remove_field",
]
