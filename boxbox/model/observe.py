"""Next-token observations used in step 2 of the notebook."""

from __future__ import annotations

import torch
from transformers import PreTrainedModel, PreTrainedTokenizerBase


def next_token_probs(
    model: PreTrainedModel, input_ids: torch.Tensor, temperature: float = 1.0
) -> torch.Tensor:
    """Softmax over the vocabulary for the token after `input_ids`."""
    with torch.no_grad():
        logits = model(input_ids).logits[0, -1].float()
    return torch.softmax(logits / temperature, dim=-1)


def top_tokens(
    probs: torch.Tensor, tokenizer: PreTrainedTokenizerBase, k: int = 10
) -> list[tuple[str, int, float]]:
    """The k most likely tokens as (text, id, probability)."""
    values, ids = probs.topk(k)
    return [
        (tokenizer.decode([token]), token, round(value, 4))
        for value, token in zip(values.tolist(), ids.tolist())
    ]
