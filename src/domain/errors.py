"""Domain-level exceptions.

These represent conditions where the router itself cannot proceed (bad configuration,
no resolvable policy) — distinct from a normal "no eligible model for this request"
outcome, which is expressed as a `RoutingDecision` with `NO_ELIGIBLE_MODEL`, not an
exception (see `application.route_evaluation_service`).
"""


class DomainError(Exception):
    """Base class for all domain-level errors."""


class ConfigurationError(DomainError):
    """Raised when routing policy or model catalogue configuration is invalid."""


class RoutingPolicyNotFoundError(DomainError):
    """Raised when no application-specific or default routing policy can be resolved."""
