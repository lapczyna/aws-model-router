"""Stable, machine-readable routing reason codes.

This is a versioned, semi-public contract (ADR-007): codes are never renamed or
repurposed once introduced, only added to. The declaration order below is the
canonical order used to sort any reason-code list before it is exposed on a
`RouteCandidate` or `RoutingDecision`, so identical routing outcomes always produce
byte-identical, ordered reason-code lists.
"""

from collections.abc import Iterable
from enum import StrEnum


class RoutingReasonCode(StrEnum):
    CAPABILITY_MATCH = "CAPABILITY_MATCH"
    MODEL_ALLOWED = "MODEL_ALLOWED"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    WITHIN_COST_LIMIT = "WITHIN_COST_LIMIT"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    LOWEST_ESTIMATED_COST = "LOWEST_ESTIMATED_COST"
    LATENCY_PREFERENCE_MATCH = "LATENCY_PREFERENCE_MATCH"
    QUALITY_TIER_MATCH = "QUALITY_TIER_MATCH"
    REGION_POLICY_MATCH = "REGION_POLICY_MATCH"
    MODEL_UNHEALTHY = "MODEL_UNHEALTHY"
    MODEL_THROTTLED = "MODEL_THROTTLED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    FALLBACK_SELECTED = "FALLBACK_SELECTED"
    EXPERIMENT_ROUTE_SELECTED = "EXPERIMENT_ROUTE_SELECTED"
    NO_ELIGIBLE_MODEL = "NO_ELIGIBLE_MODEL"
    INVALID_ROUTING_POLICY = "INVALID_ROUTING_POLICY"
    REQUIRED_CAPABILITY_UNAVAILABLE = "REQUIRED_CAPABILITY_UNAVAILABLE"


_CANONICAL_ORDER = {code: index for index, code in enumerate(RoutingReasonCode)}


def sort_reason_codes(codes: Iterable[RoutingReasonCode]) -> list[RoutingReasonCode]:
    """Return `codes` deduplicated and sorted into canonical, deterministic order."""
    unique = dict.fromkeys(codes)
    return sorted(unique, key=lambda code: _CANONICAL_ORDER[code])
