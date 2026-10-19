"""Protocol 1.1.0 structural checks, deliberately independent of WHY semantics."""

from __future__ import annotations

from ._io import LABELS


def parse_response(raw_response: str | None, status: str = "ok") -> dict:
    """Inspect an output without modifying it or treating an error as abstention."""
    result = {"strict_format_valid": False, "extracted_call": None}
    if status != "ok" or not isinstance(raw_response, str):
        return result
    text = raw_response.replace("\r\n", "\n")
    text = text.removesuffix("\n")
    lines = text.split("\n")
    calls = {f"CALL: {label}": label for label in LABELS}
    result["extracted_call"] = calls.get(lines[0])
    if len(lines) != 2 or result["extracted_call"] is None:
        return result
    if not lines[1].startswith("WHY: "):
        return result
    why = lines[1][5:]
    result["strict_format_valid"] = bool(why) and (
        why == why.strip(" \t")
        and not any(char in why for char in "\r\v\f\x85\u2028\u2029")
    )
    return result
