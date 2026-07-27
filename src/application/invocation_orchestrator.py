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
        monotonic: Callable[[], float] = time.monotonic,
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
        self._monotonic = monotonic

    def invoke(self, request: InferenceRequest) -> InferenceResult:
        """Evaluate, invoke (with fallback), and return the aggregated result.

        Raises `domain.errors.IdempotencyConflictError` if `request.idempotency_key`
        was already used for a request with different content, and
        `domain.errors.IdempotencyInProgressError` if a concurrent request with the
        same key is still in flight. Propagates `domain.errors.RoutingPolicyNotFoundError`
        / `ConfigurationError` from route evaluation unchanged. A request for which no
        model is eligible, or for which every eligible model's invocation fails, is not
        an error — it is returned as an `InferenceResult` with `response=None`.
        """
        if request.idempotency_key is None or self._idempotency_store is None:
            return self._invoke_uncached(request)
        return self._invoke_with_idempotency(
            request, request.idempotency_key, self._idempotency_store
        )

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
        if decision.selected_model_alias is None:
            result = InferenceResult(decision=decision, response=None, invocation_attempts=())
            self._persist(result)
            self._publish_metrics(result)
            return result

        policy = self._policy_repository.resolve(request.application_id)
        effective = resolve_effective_requirements(request.requirements, policy)
        chain = self._build_candidate_chain(decision, policy.fallback_policy)

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
            started_at = self._monotonic()
            try:
                response = self._model_provider.invoke(provider_request)
            except ProviderError as exc:
                latency_ms = int((self._monotonic() - started_at) * 1000)
                status = status_for_provider_error_category(exc.category)
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
        return result

    def _record_health_outcome(self, model_alias: str, status: InvocationAttemptStatus) -> None:
        if self._model_health_repository is not None:
            self._model_health_repository.record_outcome(model_alias, status)

    def _publish_metrics(self, result: InferenceResult) -> None:
        if self._metrics_publisher is not None:
            self._metrics_publisher.publish(result)

    @staticmethod
    def _build_candidate_chain(
        decision: RoutingDecision, fallback_policy: FallbackPolicy
    ) -> list[str]:
        if decision.selected_model_alias is None:  # pragma: no cover - guarded by caller
            raise AssertionError("_build_candidate_chain requires a selected primary model")

        eligible_aliases = {
            candidate.model_alias
            for candidate in decision.considered_candidates
            if candidate.eligible
        }
        chain = [decision.selected_model_alias]
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

        combined_codes = tuple(sort_reason_codes((*original.reason_codes, *extra_reason_codes)))
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
