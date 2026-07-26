from datetime import datetime

from pydantic import BaseModel, ConfigDict

from domain.candidates import RouteCandidate
from domain.enums import ProviderName
from domain.reason_codes import RoutingReasonCode
from domain.usage import EstimatedCost, Usage


class RoutingDecision(BaseModel):
    """The final, recorded outcome of routing a request.

    This is what `GET /v1/decisions/{decisionId}` returns (sanitized) once the HTTP
    API exists (Phase 5), and what `POST /v1/routes/evaluate` returns today via
    `application.route_evaluation_service.RouteEvaluationService`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    application_id: str
    created_at: datetime
    policy_id: str
    policy_version: int
    capability: str
    selected_model_alias: str | None
    provider: ProviderName | None
    fallback_used: bool = False
    reason_codes: tuple[RoutingReasonCode, ...]
    considered_candidates: tuple[RouteCandidate, ...]
    estimated_usage: Usage | None = None
    estimated_cost: EstimatedCost | None = None
