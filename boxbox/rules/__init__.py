"""Public deterministic race-card decision API."""

from .decision import (
    AHEAD_OPPORTUNITY_SECONDS,
    POLICY_VERSION,
    REJOIN_MARGIN_SECONDS,
    TYRE_LIMITS,
    decide,
    format_answer,
)
from .fields import remove_field

__all__ = [
    "AHEAD_OPPORTUNITY_SECONDS",
    "POLICY_VERSION",
    "REJOIN_MARGIN_SECONDS",
    "TYRE_LIMITS",
    "decide",
    "format_answer",
    "remove_field",
]
