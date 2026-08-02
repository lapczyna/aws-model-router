"""Provider-independent interfaces (protocols) the application layer depends on.

Adapters implement these against a concrete backend (local files today; DynamoDB/SSM
from Phase 5 — ADR-010). The domain and application layers only ever depend on the
protocols defined here, never on a concrete adapter (ADR-002).

Only the protocols with a real caller and implementation are defined here.
`ModelHealthRepository` and `MetricsPublisher` were introduced in Phase 6 alongside
their first real implementation and consumer, not speculatively ahead of them
(ADR-020, ADR-019).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from domain.catalogue import ModelDefinition, ModelPricing
from domain.enums import ModelHealthStatus
from domain.idempotency import IdempotencyReservation
from domain.invocation import AuditRecord, InferenceResult, InvocationAttemptStatus
from domain.messages import Message
from domain.policy import RoutingPolicy
from domain.provider import ProviderRequest, ProviderResponse
from domain.usage import EstimatedCost, Usage


class Clock(Protocol):
    """Supplies the current UTC time — injectable so tests are deterministic."""

    def now(self) -> datetime: ...


class IdentifierGenerator(Protocol):
    """Generates unique, prefixed identifiers (e.g. `dec_...`) — injectable for tests."""

    def new_id(self, prefix: str) -> str: ...


class ModelCatalogue(Protocol):
    """Resolves logical capabilities and aliases to `ModelDefinition`s."""

    @property
    def catalogue_version(self) -> int: ...

    def find_by_capability(self, capability: str) -> Sequence[ModelDefinition]: ...

    def get_by_alias(self, model_alias: str) -> ModelDefinition | None: ...

    def all_models(self) -> Sequence[ModelDefinition]: ...


class RoutingPolicyRepository(Protocol):
    """Resolves the effective `RoutingPolicy` for an application.

    Raises `domain.errors.RoutingPolicyNotFoundError` if neither an application-specific
    nor a default policy can be resolved, and `domain.errors.ConfigurationError` if a
    resolved policy fails schema validation.
    """

    def resolve(self, application_id: str) -> RoutingPolicy: ...


class TokenEstimator(Protocol):
    """Estimates input/output token counts for a request."""

    def estimate(self, messages: Sequence[Message], maximum_output_tokens: int) -> Usage: ...


class CostEstimator(Protocol):
    """Computes an `EstimatedCost` from `Usage` and a model's versioned pricing."""

    def estimate(self, usage: Usage, pricing: ModelPricing) -> EstimatedCost: ...


class ModelProvider(Protocol):
    """Invokes a specific model. `BedrockModelProvider` (Phase 3) is the first
    implementation; a second provider is added as a new adapter implementing this same
    protocol, without changing the domain or application layers (ADR-002).

    Raises `domain.errors.ProviderError` for every failure category — callers never
    need to catch provider-specific exception types.
    """

    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...


class IdempotencyStore(Protocol):
    """Deduplicates concurrent invocations and, if policy allows, replays a completed
    result for a repeated idempotency key (ADR-013).
    """

    def reserve(
        self, application_id: str, idempotency_key: str, request_hash: str
    ) -> IdempotencyReservation: ...

    def complete(
        self,
        application_id: str,
        idempotency_key: str,
        request_hash: str,
        result: InferenceResult,
        *,
        cache_result: bool,
        retention_seconds: int,
    ) -> None: ...

    def release(self, application_id: str, idempotency_key: str) -> None: ...


class RoutingDecisionRepository(Protocol):
    """Persists and retrieves sanitized `AuditRecord`s (ADR-008) — what
    `GET /v1/decisions/{decisionId}` will read from once the HTTP API exists (Phase 5).
    """

    def save(self, audit_record: AuditRecord) -> None: ...

    def get(self, decision_id: str) -> AuditRecord | None: ...


class ModelHealthRepository(Protocol):
    """Tracks a model's operational health, sourced from observed invocation outcomes
    (ADR-020) — never predictive modeling. Consulted during candidate filtering
    (`domain.filtering`) and updated by `InvocationOrchestrator` after every invocation
    attempt.
    """

    def get_health(self, model_alias: str) -> ModelHealthStatus: ...

    def record_outcome(self, model_alias: str, status: InvocationAttemptStatus) -> None: ...


class MetricsPublisher(Protocol):
    """Publishes operational metrics for one completed `POST /v1/inference` call
    (ADR-019). Takes the whole `InferenceResult` rather than individual fields so the
    publisher — not every caller — decides which metrics/dimensions to derive from it.

    Implementations must never use `decision_id`, `conversation_id`, `request_id`, or any
    end-user identifier as a metric *dimension* (`docs/requirements.md` NFR-4.2) — only
    bounded, low-cardinality values (capability, model alias, provider, and
    `application_id` — a small, registered set, not a per-request identifier) are safe
    dimensions.
    """

    def publish(self, result: InferenceResult) -> None: ...


class DecisionEventPublisher(Protocol):
    """Publishes a sanitized routing-decision event for one completed request, so an
    external system (analytics, governance, alerting) can subscribe instead of polling
    `GET /v1/decisions/{decisionId}` (ADR-030, Phase 10b). Same shape convention as
    `MetricsPublisher` — takes the whole `InferenceResult`, the publisher decides what
    to include.

    Never includes raw prompt/response content (ADR-008) — the same metadata-only
    discipline as `AuditRecord`/`MetricsPublisher`. A failure to publish an event must
    never fail the underlying request; implementations are responsible for their own
    error containment, the same way `EmfMetricsPublisher` cannot itself fail loudly.
    """

    def publish(self, result: InferenceResult) -> None: ...
