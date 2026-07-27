"""`EmfMetricsPublisher` — the real `domain.ports.MetricsPublisher` implementation
(ADR-019). Every metric point is written as its own CloudWatch Embedded Metric Format
(EMF) JSON line via `print()`; the Lambda's log group already accepts these (no new IAM
permission), and CloudWatch auto-extracts them into real, queryable/alarmable metrics.

Every metric declares exactly one CloudWatch dimension — `Environment` — regardless of
how many *extra*, non-dimension properties (capability, model alias, status,
application ID) ride along in the same JSON line. This is deliberate (ADR-019): a
CloudWatch metric's identity is its namespace + metric name + *exact* dimension set, so
dimensioning by e.g. `ModelAlias` would fragment `ProviderFailureCount` into one
untraceable time series per model, which a CDK-defined alarm (fixed at synth time) could
never reliably reference without also hardcoding every model alias from the catalogue.
One stable `{Environment}`-dimensioned series per metric name is what the CDK alarms in
`cdk_constructs/observability_construct.py` are built against; the extra properties are
still fully queryable per-model/per-capability via CloudWatch Logs Insights over these
same structured log lines (see `docs/operations/observability.md`).
"""

import json
import time
from typing import Any, Final

from domain.invocation import InferenceResult
from domain.reason_codes import RoutingReasonCode

_NAMESPACE: Final = "ModelRouter"

# The fixed, enforced whitelist (`docs/requirements.md` NFR-4.2) for the *extra*,
# non-dimension properties every metric line may also carry: never a
# requestId/decisionId/conversationId/end-user identifier. `_put_metric` raises
# `ValueError` on anything else, so a future call site accidentally introducing a
# high-cardinality or sensitive property fails loudly (caught by
# `test_emf_metrics_publisher.py`), not silently in production.
_ALLOWED_EXTRA_KEYS: Final = frozenset({"Capability", "ModelAlias", "Status", "ApplicationId"})

_NO_ELIGIBLE_REASON_CODES: Final = frozenset(
    {RoutingReasonCode.NO_ELIGIBLE_MODEL, RoutingReasonCode.REQUIRED_CAPABILITY_UNAVAILABLE}
)


class EmfMetricsPublisher:
    def __init__(self, environment: str) -> None:
        self._environment = environment

    def publish(self, result: InferenceResult) -> None:
        decision = result.decision
        common = {"Capability": decision.capability}

        self._put_metric("RequestCount", 1, "Count", common)
        self._put_metric("FallbackUsedCount", 1 if decision.fallback_used else 0, "Count", common)
        no_eligible_model = any(code in _NO_ELIGIBLE_REASON_CODES for code in decision.reason_codes)
        self._put_metric("NoEligibleModelCount", 1 if no_eligible_model else 0, "Count", common)
        if decision.estimated_cost is not None:
            self._put_metric(
                "EstimatedCostUsd",
                float(decision.estimated_cost.amount_usd),
                "None",
                {**common, "ApplicationId": decision.application_id},
            )

        for attempt in result.invocation_attempts:
            extra_attempt = {"ModelAlias": attempt.model_alias, "Status": attempt.status.value}
            self._put_metric("InvocationAttemptCount", 1, "Count", extra_attempt)
            self._put_metric(
                "InvocationLatencyMs", attempt.latency_ms, "Milliseconds", extra_attempt
            )
            if attempt.status is not attempt.status.SUCCEEDED:
                self._put_metric("ProviderFailureCount", 1, "Count", extra_attempt)

    def _put_metric(
        self, name: str, value: float, unit: str, extra: dict[str, str] | None = None
    ) -> None:
        extra = extra or {}
        invalid = set(extra) - _ALLOWED_EXTRA_KEYS
        if invalid:
            raise ValueError(
                f"Refusing to publish metric {name!r} with disallowed propert{'y' if len(invalid) == 1 else 'ies'} "
                f"{sorted(invalid)} — only {sorted(_ALLOWED_EXTRA_KEYS)} are approved (NFR-4.2)."
            )
        payload: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": _NAMESPACE,
                        "Dimensions": [["Environment"]],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            "Environment": self._environment,
            **extra,
            name: value,
        }
        print(json.dumps(payload))
