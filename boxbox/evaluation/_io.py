"""Small, strict JSON helpers; no model or data-loader imports."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

PROTOCOL_ID = "boxbox-eval"
PROTOCOL_VERSION = "1.1.0"
AXES = ("correctness", "role_format", "history", "scope", "factuality")
LABELS = ("BOX", "STAY OUT", "NO CALL")
FAMILIES = (
    "complete",
    "blocking_incomplete",
    "usable_incomplete",
    "follow_up",
    "out_of_scope",
)


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(
        data.encode("utf-8") if isinstance(data, str) else data
    ).hexdigest()


def _constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(text: str) -> Any:
    """Retain decimal precision and refuse duplicate keys and nonfinite numbers."""
    return json.loads(
        text, parse_float=Decimal, parse_constant=_constant, object_pairs_hook=_object
    )


def dumps(value: Any) -> str:
    """Write finite Decimal values as JSON numbers, without passing through float."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return (
            "{"
            + ",".join(dumps(k) + ":" + dumps(value[k]) for k in sorted(value))
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps(item) for item in value) + "]"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite decimal")
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite float")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def read_jsonl(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    data = Path(path).read_bytes()
    rows = []
    for index, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path}:{index}: blank ledger line")
        row = loads(line)
        if not isinstance(row, dict):
            raise TypeError(f"{path}:{index}: expected an object")
        rows.append(row)
    return rows, sha256(data)


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(dumps(value) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    data = "".join(dumps(row) + "\n" for row in rows)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(data)
    return sha256(data)
