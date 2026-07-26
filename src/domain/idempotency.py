"""Idempotency primitives (ADR-013).

`IdempotencyPolicy` (the per-application config) lives in `domain.policy` alongside the
other policy sub-models — it has no dependency on `InferenceRequest`/`InferenceResult`,
unlike everything else here, which does, and `domain.policy` must stay import-safe for
`domain.requirements` (which depends on `RoutingPolicy`) without a cycle back through
`domain.requests` → `domain.requirements` → `domain.policy`.

Idempotency dedup for *concurrent* in-flight duplicates always applies once a client
supplies an idempotency key — this is a cost/correctness control, not a policy option
(two simultaneous identical requests must never both invoke a model). Whether a
*completed* result may be replayed to a later, non-overlapping duplicate request is the
separate, explicit `IdempotencyPolicy.allow_response_caching` decision, off by default
(ADR-008) — persisting an actual model response is exactly the raw-content retention
ADR-008 requires to be opt-in.
"""

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from domain.invocation import InferenceResult
from domain.requests import InferenceRequest


class IdempotencyOutcome(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CONFLICT = "conflict"


class IdempotencyReservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: IdempotencyOutcome
    cached_result: InferenceResult | None = None


def compute_request_hash(request: InferenceRequest) -> str:
    """A stable hash of the semantically meaningful part of a request.

    Used to detect idempotency-key reuse across genuinely *different* requests (a
    client bug or replay-with-different-content), which must be rejected rather than
    silently served a mismatched cached result.
    """
    payload = {
        "application_id": request.application_id,
        "messages": [
            {"role": message.role.value, "content": message.content} for message in request.messages
        ],
        "requirements": request.requirements.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
