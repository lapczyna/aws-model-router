"""Orchestrates fallback, idempotency, and final decision aggregation on top of Phase 2
route evaluation and Phase 3 Bedrock invocation (ADR-011, ADR-013, ADR-014).

This is what will back `POST /v1/inference` once the HTTP API exists (Phase 5):
evaluate a route, invoke the selected model, fall back to an approved alternate on an
eligible failure (bounded by the policy's fallback chain), and return a fully-aggregated
`InferenceResult` -- the final decision, the ordered invocation-attempt history, and the
normalized response, if any model succeeded.
"""

import time
from collections.abc import Callable

from opentelemetry.trace import Tracer

from application.route_evaluation_service import RouteEvaluationService
from domain.decision import RoutingDecision
from domain.enums import ProviderErrorCategory
from domain.errors import IdempotencyConflictError, IdempotencyInProgressError, ProviderError
from domain.fallback import FallbackPolicy
from domain.idempotency import IdempotencyOutcome, compute_request_hash
from domain.invocation import (
    AuditRecord,
    InferenceResult,
    InvocationAttempt,
    InvocationAttemptStatus,
    reason_code_for_provider_error_category,
    status_for_provider_error_category,
)
from domain.ports import (
    Clock,
    DecisionEventPublisher,
    IdempotencyStore,
    IdentifierGenerator,
    MetricsPublisher,
    ModelHealthRepository,
    ModelProvider,
    RoutingDecisionRepository,
    RoutingPolicyRepository,
)
from domain.provider import ProviderRequest
from domain.reason_codes import RoutingReasonCode, sort_reason_codes
from domain.requests import InferenceRequest
from domain.requirements import resolve_effective_requirements
from shared.tracing import get_tracer


class InvocationOrchestrator:
    def __init__(
        self,
        route_evaluation_service: RouteEvaluationService,
        policy_repository: RoutingPolicyRepository,
        model_provider: ModelProvider,
        clock: Clock,
        identifier_generator: IdentifierGenerator,
        idempotency_store: IdempotencyStore | None = None,
        decision_repository: RoutingDecisionRepository | None = None,
        model_health_repository: ModelHealthRepository | None = None,
        metrics_publisher: MetricsPublisher | None = None,
        decision_event_publisher: DecisionEventPublisher | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        tracer: Tracer | None = None,
    ) -> None:
        self._route_evaluation_service = route_evaluation_service
        self._policy_repository = policy_repository
        self._model_provider = model_provider
        self._clock = clock
        self._identifier_generator = identifier_generator
        self._idempotency_store = idempotency_store
        self._decision_repository = decision_repository
        self._model_health_repository = model_health_repository
        self._metrics_publisher = metrics_publisher
        self._decision_event_publisher = decision_event_publisher
        self._monotonic = monotonic
        self._tracer = tracer if tracer is not None else get_tracer()

    def invoke(self, request: InferenceRequest) -> InferenceResult:
        """Evaluate, invoke (with fallback), and return the aggregated result (wrapped
        in a `model_router.invoke` span — ADR-031).

        Raises `domain.errors.IdempotencyConflictError` if `request.idempotency_key`
        was already used for a request with different content, and
        `domain.errors.IdempotencyInProgressError` if a concurrent request with the
        same key is still in flight. Propagates `domain.errors.RoutingPolicyNotFoundError`
        / `ConfigurationError` from route evaluation unchanged. A request for which no
        model is eligible, or for which every eligible model's invocation fails, is not
        an error — it is returned as an `InferenceResult` with `response=None`.
        """
        with self._tracer.start_as_current_span("model_router.invoke") as span:
            span.set_attribute("model_router.application_id", request.application_id)
            span.set_attribute(
                "model_router.has_idempotency_key", request.idempotency_key is not None
            )
            if request.idempotency_key is None or self._idempotency_store is None:
                result = self._invoke_uncached(request)
            else:
                result = self._invoke_with_idempotency(
                    request, request.idempotency_key, self._idempotency_store
                )
            span.set_attribute("model_router.decision_id", result.decision.decision_id)
            span.set_attribute(
                "model_router.selected_model_alias", result.decision.selected_model_alias or ""
            )
            span.set_attribute("model_router.fallback_used", result.decision.fallback_used)
            span.set_attribute("model_router.response_succeeded", result.response is not None)
            return result

    def _invoke_with_idempotency(
        self, request: InferenceRequest, idempotency_key: str, store: IdempotencyStore
    ) -> InferenceResult:
        request_hash = compute_request_hash(request)
        reservation = store.reserve(request.application_id, idempotency_key, request_hash)

        if reservation.outcome is IdempotencyOutcome.CONFLICT:
            raise IdempotencyConflictError(
                f"idempotency_key {idempotency_key!r} was already used for a different request"
            )
        if reservation.outcome is IdempotencyOutcome.IN_PROGRESS:
            raise IdempotencyInProgressError(
                f"a request with idempotency_key {idempotency_key!r} is already in progress"
            )
        if reservation.outcome is IdempotencyOutcome.COMPLETED:
            if reservation.cached_result is None:  # pragma: no cover - defensive
                raise AssertionError("COMPLETED reservation must carry a cached_result")
            return reservation.cached_result

        try:
            result = self._invoke_uncached(request)
        except Exception:
            store.release(request.application_id, idempotency_key)
            raise

        policy = self._policy_repository.resolve(request.application_id)
        store.complete(
            request.application_id,
            idempotency_key,
            request_hash,
            result,
            cache_result=policy.idempotency_policy.allow_response_caching,
            retention_seconds=policy.idempotency_policy.retention_seconds,
        )
        return result

    def _invoke_uncached(self, request: InferenceRequest) -> InferenceResult:
        decision = self._route_evaluation_service.evaluate(request)
        policy = self._policy_repository.resolve(request.application_id)
        chain = self._build_candidate_chain(decision, policy.fallback_policy)
        if not chain:
            result = InferenceResult(decision=decision, response=None, invocation_attempts=())
            self._persist(result)
            self._publish_metrics(result)
            self._publish_decision_event(result)
            return result

        effective = resolve_effective_requirements(request.requirements, policy)

        attempts: list[InvocationAttempt] = []
        extra_reason_codes: list[RoutingReasonCode] = []
        response = None
        succeeded_alias: str | None = None

        for candidate_alias in chain:
            provider_request = ProviderRequest(
                model_alias=candidate_alias,
                messages=request.messages,
                max_output_tokens=effective.maximum_output_tokens,
                requires_tool_use=effective.requires_tool_use,
                requires_structured_output=effective.requires_structured_output,
            )
            with self._tracer.start_as_current_span("model_router.invoke_attempt") as attempt_span:
                attempt_span.set_attribute("model_router.model_alias", candidate_alias)
                started_at = self._monotonic()
                try:
                    response = self._model_provider.invoke(provider_request)
                except ProviderError as exc:
                    latency_ms = int((self._monotonic() - started_at) * 1000)
                    status = status_for_provider_error_category(exc.category)
                    attempt_span.set_attribute("model_router.attempt_status", status.value)
                    attempt_span.set_attribute("model_router.latency_ms", latency_ms)
                    attempts.append(
                        InvocationAttempt(
                            model_alias=candidate_alias, status=status, latency_ms=latency_ms
                        )
                    )
                    self._record_health_outcome(candidate_alias, status)
                    extra_code = reason_code_for_provider_error_category(exc.category)
                    if extra_code is not None:
                        extra_reason_codes.append(extra_code)
                    if exc.category is ProviderErrorCategory.PERMANENT:
                        break
                    continue
                else:
                    latency_ms = int((self._monotonic() - started_at) * 1000)
                    attempt_span.set_attribute(
                        "model_router.attempt_status", InvocationAttemptStatus.SUCCEEDED.value
                    )
                    attempt_span.set_attribute("model_router.latency_ms", latency_ms)
                    attempts.append(
                        InvocationAttempt(
                            model_alias=candidate_alias,
                            status=InvocationAttemptStatus.SUCCEEDED,
                            latency_ms=latency_ms,
                        )
                    )
                    self._record_health_outcome(candidate_alias, InvocationAttemptStatus.SUCCEEDED)
                    succeeded_alias = candidate_alias
                    if candidate_alias != decision.selected_model_alias:
                        extra_reason_codes.append(RoutingReasonCode.FALLBACK_SELECTED)
                    break

        final_decision = self._aggregate_decision(decision, succeeded_alias, extra_reason_codes)
        result = InferenceResult(
            decision=final_decision,
            response=response if succeeded_alias is not None else None,
            invocation_attempts=tuple(attempts),
        )
        self._persist(result)
        self._publish_metrics(result)
        self._publish_decision_event(result)
        return result

    def _record_health_outcome(self, model_alias: str, status: InvocationAttemptStatus) -> None:
        if self._model_health_repository is not None:
            self._model_health_repository.record_outcome(model_alias, status)

    def _publish_decision_event(self, result: InferenceResult) -> None:
        if self._decision_event_publisher is not None:
            self._decision_event_publisher.publish(result)

    def _publish_metrics(self, result: InferenceResult) -> None:
        if self._metrics_publisher is not None:
            self._metrics_publisher.publish(result)

    @staticmethod
    def _build_candidate_chain(
        decision: RoutingDecision, fallback_policy: FallbackPolicy
    ) -> list[str]:
        """Build the ordered chain of model aliases to attempt.

        Usually starts with the strategy's selected model. But a strategy (e.g.
        `PreferredModelStrategy`) may deliberately leave `selected_model_alias` unset
        when its preferred model is ineligible (e.g. excluded by model-health
        filtering) rather than implicitly choosing a substitute -- that substitution is
        this method's job. In that case the chain still considers the policy's
        configured fallback aliases, so a healthy fallback model isn't left unused
        just because it wasn't anyone's first choice.
        """
        eligible_aliases = {
            candidate.model_alias
            for candidate in decision.considered_candidates
            if candidate.eligible
        }
        chain: list[str] = []
        if decision.selected_model_alias is not None:
            chain.append(decision.selected_model_alias)
        for alias in fallback_policy.fallback_model_aliases:
            if len(chain) >= fallback_policy.maximum_attempts:
                break
            if alias in eligible_aliases and alias not in chain:
                chain.append(alias)
        return chain

    @staticmethod
    def _aggregate_decision(
        original: RoutingDecision,
        succeeded_alias: str | None,
        extra_reason_codes: list[RoutingReasonCode],
    ) -> RoutingDecision:
        fallback_used = (
            succeeded_alias is not None and succeeded_alias != original.selected_model_alias
        )
        selected_candidate = None
        if succeeded_alias is not None:
            selected_candidate = next(
                candidate
                for candidate in original.considered_candidates
                if candidate.model_alias == succeeded_alias
            )

        # `_aggregate_decision` is only ever called once `_build_candidate_chain` has
        # produced a non-empty chain, i.e. at least one eligible candidate was found
        # and attempted -- so `NO_ELIGIBLE_MODEL` (set when the strategy itself
        # selected nothing) is stale here even if every attempt in the chain failed.
        original_codes = tuple(
            code
            for code in original.reason_codes
            if code is not RoutingReasonCode.NO_ELIGIBLE_MODEL
        )
        combined_codes = tuple(sort_reason_codes((*original_codes, *extra_reason_codes)))
        return original.model_copy(
            update={
                "selected_model_alias": succeeded_alias,
                "provider": selected_candidate.provider if selected_candidate else None,
                "fallback_used": fallback_used,
                "reason_codes": combined_codes,
                "estimated_usage": (
                    selected_candidate.estimated_usage if selected_candidate else None
                ),
                "estimated_cost": selected_candidate.estimated_cost if selected_candidate else None,
            }
        )

    def _persist(self, result: InferenceResult) -> None:
        if self._decision_repository is not None:
            self._decision_repository.save(
                AuditRecord(
                    decision=result.decision, invocation_attempts=result.invocation_attempts
                )
            )
