"""Invocation-attempt records and final decision aggregation (ADR-011, ADR-014).

`InvocationAttempt` records what happened for one model in a fallback chain;
`InferenceResult` is what `application.invocation_orchestrator.InvocationOrchestrator`
returns — the fully-aggregated `RoutingDecision` (reflecting whatever actually happened
during invocation, not just the pre-invocation route selection) plus the ordered
attempt history and the normalized response, if any model succeeded.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from domain.decision import RoutingDecision
from domain.enums import ProviderErrorCategory
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode


class InvocationAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    THROTTLED = "throttled"
    TRANSIENT_ERROR = "transient_error"
    NON_RETRYABLE_ERROR = "non_retryable_error"
    TIMEOUT = "timeout"


_STATUS_BY_CATEGORY: dict[ProviderErrorCategory, InvocationAttemptStatus] = {
    ProviderErrorCategory.THROTTLED: InvocationAttemptStatus.THROTTLED,
    ProviderErrorCategory.TRANSIENT: InvocationAttemptStatus.TRANSIENT_ERROR,
    ProviderErrorCategory.TIMEOUT: InvocationAttemptStatus.TIMEOUT,
    ProviderErrorCategory.PERMANENT: InvocationAttemptStatus.NON_RETRYABLE_ERROR,
}

_REASON_CODE_BY_CATEGORY: dict[ProviderErrorCategory, RoutingReasonCode] = {
    ProviderErrorCategory.THROTTLED: RoutingReasonCode.MODEL_THROTTLED,
    ProviderErrorCategory.TRANSIENT: RoutingReasonCode.MODEL_UNAVAILABLE,
    ProviderErrorCategory.TIMEOUT: RoutingReasonCode.MODEL_UNAVAILABLE,
}


def status_for_provider_error_category(category: ProviderErrorCategory) -> InvocationAttemptStatus:
    return _STATUS_BY_CATEGORY[category]


def reason_code_for_provider_error_category(
    category: ProviderErrorCategory,
) -> RoutingReasonCode | None:
    """The decision-level reason code an invocation failure contributes, if any.

    `PERMANENT` contributes none — `InvocationAttempt.status` already records it, and
    there is no dedicated "permanent invocation failure" reason code in the fixed
    vocabulary (ADR-007) distinct from the pre-invocation eligibility codes.
    """
    return _REASON_CODE_BY_CATEGORY.get(category)


class InvocationAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_alias: str
    status: InvocationAttemptStatus
    latency_ms: int = Field(ge=0)


class InferenceResult(BaseModel):
    """What `InvocationOrchestrator.invoke()` returns: the final, aggregated decision,
    the ordered invocation-attempt history, and the response from whichever model
    ultimately succeeded (`None` if every attempt failed or no model was eligible)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: RoutingDecision
    response: ProviderResponse | None
    invocation_attempts: tuple[InvocationAttempt, ...] = ()


class AuditRecord(BaseModel):
    """The sanitized, persisted record combining a decision and its invocation
    attempts (ADR-008) — metadata only, never raw prompt/response content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: RoutingDecision
    invocation_attempts: tuple[InvocationAttempt, ...] = ()
