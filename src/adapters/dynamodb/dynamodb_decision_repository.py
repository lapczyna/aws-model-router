"""`DynamoDbRoutingDecisionRepository`: the multi-instance-safe `RoutingDecisionRepository`
implementation backing `GET /v1/decisions/{decisionId}` (Phase 5).

Records expire via DynamoDB item TTL (`expiresAt`) after `retention_seconds` — audit
retention is a platform-wide operational setting, not a per-application policy choice,
unlike idempotency's `IdempotencyPolicy.retention_seconds`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from domain.invocation import AuditRecord

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60  # 30 days


class DynamoDbRoutingDecisionRepository:
    def __init__(
        self,
        table: Table,
        retention_seconds: int = _DEFAULT_RETENTION_SECONDS,
        clock_seconds: Callable[[], float] = time.time,
    ) -> None:
        self._table = table
        self._retention_seconds = retention_seconds
        self._clock_seconds = clock_seconds

    def save(self, audit_record: AuditRecord) -> None:
        now = int(self._clock_seconds())
        self._table.put_item(
            Item={
                "decisionId": audit_record.decision.decision_id,
                "applicationId": audit_record.decision.application_id,
                "record": audit_record.model_dump_json(),
                "expiresAt": now + self._retention_seconds,
            }
        )

    def get(self, decision_id: str) -> AuditRecord | None:
        item = self._table.get_item(Key={"decisionId": decision_id}).get("Item")
        if item is None:
            return None
        return AuditRecord.model_validate_json(cast(str, item["record"]))
