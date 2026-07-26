"""Fallback configuration (ADR-011).

Fallback is policy-controlled, not automatic: an application's `RoutingPolicy` must
explicitly configure `fallback_model_aliases` for any fallback to be attempted at all.
`maximum_attempts` bounds the *entire* fallback chain (primary plus fallbacks) — this is
both the "maximum invocation attempts" and the "retry budget" control (ADR-014):
bounding the number of *distinct models* tried per logical request, independent of
`adapters.bedrock.retry.RetryPolicy`, which separately bounds retries *within* a single
model's invocation.
"""

from pydantic import BaseModel, ConfigDict, Field


class FallbackPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fallback_model_aliases: tuple[str, ...] = ()
    maximum_attempts: int = Field(default=1, ge=1)
