import random

import pytest

from domain.reason_codes import RoutingReasonCode, sort_reason_codes

pytestmark = pytest.mark.unit


def test_sort_reason_codes_matches_canonical_declaration_order() -> None:
    shuffled = [
        RoutingReasonCode.QUALITY_TIER_MATCH,
        RoutingReasonCode.CAPABILITY_MATCH,
        RoutingReasonCode.LOWEST_ESTIMATED_COST,
        RoutingReasonCode.MODEL_ALLOWED,
        RoutingReasonCode.WITHIN_COST_LIMIT,
    ]
    assert sort_reason_codes(shuffled) == [
        RoutingReasonCode.CAPABILITY_MATCH,
        RoutingReasonCode.MODEL_ALLOWED,
        RoutingReasonCode.WITHIN_COST_LIMIT,
        RoutingReasonCode.LOWEST_ESTIMATED_COST,
        RoutingReasonCode.QUALITY_TIER_MATCH,
    ]


def test_sort_reason_codes_is_stable_across_random_input_orders() -> None:
    codes = list(RoutingReasonCode)
    expected = sort_reason_codes(codes)
    rng = random.Random(1234)
    for _ in range(20):
        shuffled = codes.copy()
        rng.shuffle(shuffled)
        assert sort_reason_codes(shuffled) == expected


def test_sort_reason_codes_deduplicates() -> None:
    codes = [
        RoutingReasonCode.CAPABILITY_MATCH,
        RoutingReasonCode.CAPABILITY_MATCH,
        RoutingReasonCode.MODEL_ALLOWED,
    ]
    assert sort_reason_codes(codes) == [
        RoutingReasonCode.CAPABILITY_MATCH,
        RoutingReasonCode.MODEL_ALLOWED,
    ]
