"""Default, dependency-free implementations of `TokenEstimator` and `CostEstimator`.

These are pure, deterministic heuristics — not a real tokenizer and not a substitute
for AWS billing. Every value they produce is surfaced as an explicit estimate
(`domain.usage.EstimatedCost.is_estimate`), never equated with billed cost.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from domain.catalogue import ModelPricing
from domain.messages import Message
from domain.usage import EstimatedCost, Usage

_CENTS_PER_1K = Decimal(1000)


@dataclass(frozen=True)
class DefaultTokenEstimator:
    """Estimates input tokens from message character length; output is capped at the
    request's requested maximum. A deliberately simple, deterministic heuristic
    (~`chars_per_token` characters per token) rather than a real tokenizer.
    """

    chars_per_token: int = 4

    def estimate(self, messages: Sequence[Message], maximum_output_tokens: int) -> Usage:
        total_chars = sum(len(message.content) for message in messages)
        input_tokens = max(1, -(-total_chars // self.chars_per_token))  # ceiling division
        return Usage(input_tokens=input_tokens, output_tokens=maximum_output_tokens)


class DefaultCostEstimator:
    """Computes estimated cost as a pure function of `Usage` and versioned pricing."""

    def estimate(self, usage: Usage, pricing: ModelPricing) -> EstimatedCost:
        input_cost = (
            Decimal(usage.input_tokens) / _CENTS_PER_1K
        ) * pricing.input_price_per_1k_tokens
        output_cost = (
            Decimal(usage.output_tokens) / _CENTS_PER_1K
        ) * pricing.output_price_per_1k_tokens
        total = (input_cost + output_cost).quantize(Decimal("0.000001"))
        return EstimatedCost(amount_usd=total)
