"""Public deterministic race-card decision API."""

from .decision import (
    AHEAD_OPPORTUNITY_SECONDS,
    POLICY_VERSION,
    REJOIN_MARGIN_SECONDS,
    TYRE_LIMITS,
)
from .fields import remove_field
from .policy2 import decide, format_answer  # 2.0 cards get policy 2.0

__all__ = [
    "AHEAD_OPPORTUNITY_SECONDS",
    "POLICY_VERSION",
    "REJOIN_MARGIN_SECONDS",
    "TYRE_LIMITS",
    "decide",
    "format_answer",
    "remove_field",
]
