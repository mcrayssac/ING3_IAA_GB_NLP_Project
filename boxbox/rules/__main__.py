"""Inspect one JSON race card with the deterministic policy."""

import json
import sys
from decimal import Decimal
from pathlib import Path

from . import format_answer


def _reject_nonfinite_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 -m boxbox.rules CARD.json", file=sys.stderr)
        return 2
    try:
        card = json.loads(
            Path(sys.argv[1]).read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_constant=_reject_nonfinite_constant,
        )
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Cannot read card: {error}", file=sys.stderr)
        return 2
    print(format_answer(card))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
