"""Maps domain exceptions and outcomes to the HTTP status/`ErrorResponse` shape
documented in `docs/architecture/api-contracts.md`.

Never includes raw exception text, prompt/response content, or internal configuration
in a response body (ADR-008) — every message here is a fixed, safe string; the original
exception is only ever logged server-side (`logging.exception`, in `api_handler.py`),
never returned to the caller.
"""

from typing import Any

from domain.decision import RoutingDecision
from domain.errors import (
    ConfigurationError,
    DomainError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    ProviderError,
    RoutingPolicyNotFoundError,
)
from domain.reason_codes import RoutingReasonCode


def error_response_body(
    request_id: str,
    error_code: str,
    message: str,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"requestId": request_id, "errorCode": error_code, "message": message}
    if reason_codes is not None:
        body["reasonCodes"] = reason_codes
    return body


def map_exception_to_status_and_body(exc: Exception, request_id: str) -> tuple[int, dict[str, Any]]:
    """Map a caught exception to `(http_status, response_body)`.

    Only exceptions this module knows about get a specific status/code; anything else
    is treated as `INTERNAL_ERROR` — callers should still log the original exception
    themselves for server-side debugging before calling this.
    """
    if isinstance(exc, RoutingPolicyNotFoundError):
        return 403, error_response_body(
            request_id, "POLICY_DENIED", "No routing policy is configured for this application."
        )
    if isinstance(exc, IdempotencyConflictError):
        return 409, error_response_body(
            request_id,
            "IDEMPOTENCY_CONFLICT",
            "This idempotency key was already used for a different request.",
        )
    if isinstance(exc, IdempotencyInProgressError):
        return 409, error_response_body(
            request_id,
            "IDEMPOTENCY_IN_PROGRESS",
            "A request with this idempotency key is already being processed.",
        )
    if isinstance(exc, ConfigurationError):
        return 500, error_response_body(
            request_id, "INTERNAL_ERROR", "The router's configuration could not be loaded."
        )
    if isinstance(exc, ProviderError):
        return 502, error_response_body(
            request_id, "PROVIDER_UNAVAILABLE", "The model provider is currently unavailable."
        )
    if isinstance(exc, DomainError):
        return 500, error_response_body(
            request_id, "INTERNAL_ERROR", "An unexpected error occurred."
        )
    return 500, error_response_body(request_id, "INTERNAL_ERROR", "An unexpected error occurred.")


def map_no_selection_to_status_and_body(
    decision: RoutingDecision, invocation_attempted: bool, request_id: str
) -> tuple[int, dict[str, Any]]:
    """Map a `RoutingDecision`/`InferenceResult` with no selected model to an HTTP
    response for `POST /v1/inference`.

    This is a best-effort heuristic over the existing reason-code vocabulary (ADR-007),
    not an exact 1:1 mapping — the reason codes were designed for route explainability,
    not for HTTP status derivation. Refining this is left to a later security/API review
    (Phase 7) if warranted.
    """
    reason_codes = [code.value for code in decision.reason_codes]

    if invocation_attempted:
        return 502, error_response_body(
            request_id,
            "PROVIDER_UNAVAILABLE",
            "The selected model and all approved fallbacks failed.",
            reason_codes,
        )

    if RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE in decision.reason_codes:
        return 422, error_response_body(
            request_id,
            "REQUIRED_CAPABILITY_UNAVAILABLE",
            "The requested capability is not available to this application.",
            reason_codes,
        )

    cost_rejected_only = bool(decision.considered_candidates) and all(
        not candidate.eligible and RoutingReasonCode.COST_LIMIT_EXCEEDED in candidate.reason_codes
        for candidate in decision.considered_candidates
    )
    if cost_rejected_only:
        return 402, error_response_body(
            request_id,
            "COST_LIMIT_EXCEEDED",
            "No eligible route satisfies the requested cost limit.",
            reason_codes,
        )

    return 404, error_response_body(
        request_id,
        "NO_ELIGIBLE_MODEL",
        "No eligible model is available for this request.",
        reason_codes,
    )
