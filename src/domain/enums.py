"""Closed-set vocabularies used across the routing domain.

Logical capabilities (e.g. "balanced-text") are deliberately *not* an enum here — they
are open, configuration-driven strings (ADR-010) so a new capability can be introduced
by editing the model catalogue and a routing policy, without a code change.
"""

from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class QualityTier(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"


class LatencyPreference(StrEnum):
    LOW = "low"
    BALANCED = "balanced"
    HIGH = "high"


class RoutingStrategyType(StrEnum):
    PREFERRED_MODEL = "preferred_model"
    LOWEST_COST = "lowest_cost"
    QUALITY_TIER = "quality_tier"


class ProviderName(StrEnum):
    BEDROCK = "bedrock"


class ModelHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ModelResolutionType(StrEnum):
    DIRECT_MODEL_ID = "direct_model_id"
    CROSS_REGION_INFERENCE_PROFILE = "cross_region_inference_profile"
    APPLICATION_INFERENCE_PROFILE = "application_inference_profile"
    ROUTER_ALIAS = "router_alias"


class StopReason(StrEnum):
    """Normalized across providers (ADR-009). `OTHER` absorbs any value a provider adds
    in the future so response parsing never fails on an unrecognized-but-valid reason.
    """

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    CONTENT_FILTERED = "content_filtered"
    GUARDRAIL_INTERVENED = "guardrail_intervened"
    OTHER = "other"


class ProviderErrorCategory(StrEnum):
    """The provider error taxonomy invocation callers reason about.

    `THROTTLED`, `TRANSIENT`, and `TIMEOUT` are eligible for bounded retry (and, from
    Phase 4, fallback); `PERMANENT` is not — retrying a permanent error (bad alias,
    unsupported capability, malformed response, request validation failure) would just
    reproduce the same failure while adding latency and cost.
    """

    THROTTLED = "throttled"
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    PERMANENT = "permanent"
