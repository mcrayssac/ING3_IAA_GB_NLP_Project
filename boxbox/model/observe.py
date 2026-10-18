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


def label_probability(
    model: PreTrainedModel,
    prefix_ids: torch.Tensor,
    tokenizer: PreTrainedTokenizerBase,
    text: str,
) -> float:
    """Probability that the model continues `prefix_ids` with exactly the tokens of `text`."""
    label = tokenizer(text, add_special_tokens=False, return_tensors="pt")["input_ids"]
    label = label.to(prefix_ids.device)
    with torch.no_grad():
        logits = model(torch.cat([prefix_ids, label], dim=1)).logits
    # the logits at position t predict token t + 1, so the label is read one step earlier
    logprobs = torch.log_softmax(logits[0, -label.shape[1] - 1 : -1].float(), dim=-1)
    return logprobs.gather(1, label[0, :, None]).sum().exp().item()


def top_tokens(
    probs: torch.Tensor, tokenizer: PreTrainedTokenizerBase, k: int = 10
) -> list[tuple[str, int, float]]:
    """The k most likely tokens as (text, id, probability)."""
    values, ids = probs.topk(k)
    return [
        (tokenizer.decode([token]), token, round(value, 4))
        for value, token in zip(values.tolist(), ids.tolist())
    ]
