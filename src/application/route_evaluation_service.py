"""Orchestrates the routing use case, without invoking any model (Phase 3 adds that).

This is the cloud-independent "local routing engine": given an `InferenceRequest`, it
resolves the applicable policy, filters and scores candidate models, and returns a
fully-explained `RoutingDecision` — exactly what `POST /v1/routes/evaluate` will expose
once the HTTP API exists (Phase 5).
"""

from opentelemetry.trace import Tracer

from domain.candidates import RouteCandidate
from domain.decision import RoutingDecision
from domain.filtering import build_route_candidates
from domain.policy import RoutingPolicy
from domain.ports import (
    Clock,
    CostEstimator,
    IdentifierGenerator,
    ModelCatalogue,
    ModelHealthRepository,
    RoutingPolicyRepository,
    TokenEstimator,
)
from domain.reason_codes import RoutingReasonCode, sort_reason_codes
from domain.requests import InferenceRequest
from domain.requirements import resolve_effective_requirements
from domain.strategy import RouteSelection, RoutingContext, get_strategy
from shared.tracing import get_tracer


class RouteEvaluationService:
    def __init__(
        self,
        policy_repository: RoutingPolicyRepository,
        model_catalogue: ModelCatalogue,
        token_estimator: TokenEstimator,
        cost_estimator: CostEstimator,
        clock: Clock,
        identifier_generator: IdentifierGenerator,
        model_health_repository: ModelHealthRepository | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._policy_repository = policy_repository
        self._model_catalogue = model_catalogue
        self._token_estimator = token_estimator
        self._cost_estimator = cost_estimator
        self._clock = clock
        self._identifier_generator = identifier_generator
        self._model_health_repository = model_health_repository
        self._tracer = tracer if tracer is not None else get_tracer()

    def evaluate(self, request: InferenceRequest) -> RoutingDecision:
        """Evaluate the route for `request` (wrapped in a `model_router.evaluate_route`
        span — ADR-031; see `_evaluate` for the actual routing logic).

        Raises `domain.errors.RoutingPolicyNotFoundError` if no policy can be resolved
        for the application, and `domain.errors.ConfigurationError` if the resolved
        policy or catalogue fails validation. A request for which no model is eligible
        is not an error — it is returned as a decision with no selected model and a
        `NO_ELIGIBLE_MODEL` or `REQUIRED_CAPABILITY_UNAVAILABLE` reason code.
        """
        with self._tracer.start_as_current_span("model_router.evaluate_route") as span:
            span.set_attribute("model_router.application_id", request.application_id)
            span.set_attribute("model_router.capability", request.requirements.capability)
            decision = self._evaluate(request)
            span.set_attribute("model_router.decision_id", decision.decision_id)
            span.set_attribute(
                "model_router.selected_model_alias", decision.selected_model_alias or ""
            )
            span.set_attribute(
                "model_router.reason_codes", [code.value for code in decision.reason_codes]
            )
            return decision

    def _evaluate(self, request: InferenceRequest) -> RoutingDecision:
        policy = self._policy_repository.resolve(request.application_id)

        capability = request.requirements.capability
        if capability not in policy.allowed_capabilities:
            return self._build_decision(
                request,
                policy,
                capability,
                selection=RouteSelection(selected=None),
                candidates=(),
                reason_codes=(RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE,),
            )

        effective_requirements = resolve_effective_requirements(request.requirements, policy)
        models = self._model_catalogue.find_by_capability(effective_requirements.capability)
        if not models:
            return self._build_decision(
                request,
                policy,
                capability,
                selection=RouteSelection(selected=None),
                candidates=(),
                reason_codes=(RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE,),
            )

        candidates = build_route_candidates(
            models,
            effective_requirements,
            policy,
            self._token_estimator,
            self._cost_estimator,
            request.messages,
            self._model_health_repository,
        )
        eligible = [candidate for candidate in candidates if candidate.eligible]
        strategy = get_strategy(policy.routing_strategy)
        context = RoutingContext(
            application_id=request.application_id, conversation_id=request.conversation_id
        )
        selection = strategy.select(eligible, policy, effective_requirements, context)

        reason_codes: tuple[RoutingReasonCode, ...]
        if selection.selected is None:
            reason_codes = (RoutingReasonCode.NO_ELIGIBLE_MODEL,)
        else:
            reason_codes = tuple(
                sort_reason_codes(
                    (*selection.selected.reason_codes, *selection.additional_reason_codes)
                )
            )

        return self._build_decision(
            request, policy, capability, selection, tuple(candidates), reason_codes
        )

    def _build_decision(
        self,
        request: InferenceRequest,
        policy: RoutingPolicy,
        capability: str,
        selection: RouteSelection,
        candidates: tuple[RouteCandidate, ...],
        reason_codes: tuple[RoutingReasonCode, ...],
    ) -> RoutingDecision:
        selected = selection.selected
        return RoutingDecision(
            decision_id=self._identifier_generator.new_id("dec"),
            application_id=request.application_id,
            created_at=self._clock.now(),
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            capability=capability,
            selected_model_alias=selected.model_alias if selected else None,
            provider=selected.provider if selected else None,
            reason_codes=reason_codes,
            considered_candidates=candidates,
            estimated_usage=selected.estimated_usage if selected else None,
            estimated_cost=selected.estimated_cost if selected else None,
        )
