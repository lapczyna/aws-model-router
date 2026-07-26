from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from domain.enums import ProviderName
from domain.reason_codes import RoutingReasonCode
from domain.usage import EstimatedCost, Usage


class RouteCandidate(BaseModel):
    """A `ModelDefinition` under consideration for a specific request.

    Carries every reason code evaluated for this candidate — both why it's eligible
    and why it isn't — so a `RoutingDecision`'s `considered_candidates` can fully
    explain the outcome without exposing internal configuration (ADR-007).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_alias: str
    provider: ProviderName
    eligible: bool
    reason_codes: tuple[RoutingReasonCode, ...]
    estimated_usage: Usage
    estimated_cost: EstimatedCost


@dataclass(frozen=True)
class RouteScore:
    """The score a `RoutingStrategy` assigns a candidate when ranking eligible routes."""

    candidate: RouteCandidate
    score: Decimal
