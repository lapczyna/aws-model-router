from decimal import Decimal

import pytest

from domain.catalogue import ModelPricing
from domain.cost_estimation import DefaultCostEstimator, DefaultTokenEstimator
from domain.enums import Role
from domain.messages import Message
from domain.usage import Usage

pytestmark = pytest.mark.unit


def test_token_estimator_is_deterministic_and_ceils_input_tokens() -> None:
    estimator = DefaultTokenEstimator()
    messages = (Message(role=Role.USER, content="a" * 10),)

    first = estimator.estimate(messages, maximum_output_tokens=100)
    second = estimator.estimate(messages, maximum_output_tokens=100)

    assert first == second
    assert first.input_tokens == 3  # ceil(10 / 4)
    assert first.output_tokens == 100


def test_token_estimator_returns_at_least_one_input_token_for_empty_content() -> None:
    estimator = DefaultTokenEstimator()
    messages = (Message(role=Role.USER, content=""),)

    usage = estimator.estimate(messages, maximum_output_tokens=10)

    assert usage.input_tokens == 1


def test_token_estimator_sums_across_multiple_messages() -> None:
    estimator = DefaultTokenEstimator()
    messages = (
        Message(role=Role.SYSTEM, content="a" * 4),
        Message(role=Role.USER, content="a" * 8),
    )

    usage = estimator.estimate(messages, maximum_output_tokens=10)

    assert usage.input_tokens == 3  # ceil(12 / 4)


def test_cost_estimator_computes_exact_decimal_cost() -> None:
    estimator = DefaultCostEstimator()
    pricing = ModelPricing(
        input_price_per_1k_tokens=Decimal("0.003"),
        output_price_per_1k_tokens=Decimal("0.015"),
        pricing_version=1,
    )
    usage = Usage(input_tokens=1000, output_tokens=1000)

    cost = estimator.estimate(usage, pricing)

    assert cost.amount_usd == Decimal("0.018")
    assert cost.is_estimate is True


def test_cost_estimator_is_deterministic() -> None:
    estimator = DefaultCostEstimator()
    pricing = ModelPricing(
        input_price_per_1k_tokens=Decimal("0.00025"),
        output_price_per_1k_tokens=Decimal("0.00125"),
        pricing_version=1,
    )
    usage = Usage(input_tokens=123, output_tokens=456)

    first = estimator.estimate(usage, pricing)
    second = estimator.estimate(usage, pricing)

    assert first == second
