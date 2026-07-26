"""Domain-level exceptions.

These represent conditions where the router itself cannot proceed (bad configuration,
no resolvable policy) — distinct from a normal "no eligible model for this request"
outcome, which is expressed as a `RoutingDecision` with `NO_ELIGIBLE_MODEL`, not an
exception (see `application.route_evaluation_service`).
"""

from domain.enums import ProviderErrorCategory


class DomainError(Exception):
    """Base class for all domain-level errors."""


class ConfigurationError(DomainError):
    """Raised when routing policy or model catalogue configuration is invalid."""


class RoutingPolicyNotFoundError(DomainError):
    """Raised when no application-specific or default routing policy can be resolved."""


class ProviderError(DomainError):
    """Raised by a `ModelProvider` implementation when an invocation cannot succeed.

    `message` is always a fixed, safe, human-readable string — a `ModelProvider` must
    never include prompt/response content, credentials, or raw provider payloads in it
    (see `docs/adr/0008-metadata-only-audit-records-by-default.md`). The original
    provider exception, if any, is available via `__cause__` for local debugging, not
    for display to a caller.
    """

    def __init__(self, message: str, *, category: ProviderErrorCategory) -> None:
        super().__init__(message)
        self.category = category


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key is reused with a different, non-matching request.

    This is deliberately never treated as "fallback eligible" or silently resolved —
    reusing a key for different content is either a client bug or a replay attempt, and
    must surface as a clear error rather than serving a mismatched cached result.
    """


class IdempotencyInProgressError(DomainError):
    """Raised when a concurrent, still-in-flight request holds the same idempotency key.

    Prevents two simultaneous identical requests from both invoking a model (ADR-013).
    """
