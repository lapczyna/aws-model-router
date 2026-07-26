from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domain.money import Money


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class EstimatedCost(BaseModel):
    """A cost estimate derived from `Usage` and versioned `ModelPricing`.

    `is_estimate` is fixed to `True` so this type can never be mistaken, in code or in
    a serialized payload, for actual AWS billed cost (ADR-005, `docs/requirements.md`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_usd: Money
    is_estimate: Literal[True] = True
