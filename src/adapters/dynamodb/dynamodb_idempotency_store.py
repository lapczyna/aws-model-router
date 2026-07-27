"""`DynamoDbIdempotencyStore`: the multi-instance-safe `IdempotencyStore` implementation.

Atomicity for `reserve()` comes from a DynamoDB conditional `put_item` —
`attribute_not_exists(pk) OR expiresAt < :now` — evaluated server-side, so two Lambda
instances racing on the same key can never both succeed (unlike the in-memory store's
single-process lock, this holds across concurrent Lambda invocations on different
hosts). Table item TTL (the `expiresAt` attribute) provides the safety-net expiry for
abandoned "in progress" reservations, same role as `stale_reservation_seconds` in
`adapters.memory.InMemoryIdempotencyStore`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from botocore.exceptions import ClientError

from domain.idempotency import IdempotencyOutcome, IdempotencyReservation
from domain.invocation import InferenceResult

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_STATUS_IN_PROGRESS = "in_progress"
_STATUS_COMPLETED = "completed"
_MAX_RESERVE_ATTEMPTS = 2  # bounded retry for the rare lost-race-then-deleted edge case


class DynamoDbIdempotencyStore:
    def __init__(
        self,
        table: Table,
        stale_reservation_seconds: int = 300,
        clock_seconds: Callable[[], float] = time.time,
    ) -> None:
        self._table = table
        self._stale_reservation_seconds = stale_reservation_seconds
        self._clock_seconds = clock_seconds

    def reserve(
        self, application_id: str, idempotency_key: str, request_hash: str
    ) -> IdempotencyReservation:
        for _ in range(_MAX_RESERVE_ATTEMPTS):
            reservation = self._try_reserve(application_id, idempotency_key, request_hash)
            if reservation is not None:
                return reservation
        # Both attempts raced against a record that vanished between our conditional
        # put failing and the follow-up get — treat this as a fresh reservation rather
        # than looping forever.
        return IdempotencyReservation(outcome=IdempotencyOutcome.NEW)

    def _try_reserve(
        self, application_id: str, idempotency_key: str, request_hash: str
    ) -> IdempotencyReservation | None:
        now = int(self._clock_seconds())
        try:
            self._table.put_item(
                Item={
                    "pk": application_id,
                    "sk": idempotency_key,
                    "requestHash": request_hash,
                    "status": _STATUS_IN_PROGRESS,
                    "expiresAt": now + self._stale_reservation_seconds,
                },
                ConditionExpression="attribute_not_exists(pk) OR expiresAt < :now",
                ExpressionAttributeValues={":now": now},
            )
            return IdempotencyReservation(outcome=IdempotencyOutcome.NEW)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

        existing = self._table.get_item(Key={"pk": application_id, "sk": idempotency_key}).get(
            "Item"
        )
        if existing is None:
            return None  # ask the caller to retry once

        if existing["requestHash"] != request_hash:
            return IdempotencyReservation(outcome=IdempotencyOutcome.CONFLICT)
        if existing["status"] == _STATUS_IN_PROGRESS:
            return IdempotencyReservation(outcome=IdempotencyOutcome.IN_PROGRESS)

        cached_result = InferenceResult.model_validate_json(cast(str, existing["result"]))
        return IdempotencyReservation(
            outcome=IdempotencyOutcome.COMPLETED, cached_result=cached_result
        )

    def complete(
        self,
        application_id: str,
        idempotency_key: str,
        request_hash: str,
        result: InferenceResult,
        *,
        cache_result: bool,
        retention_seconds: int,
    ) -> None:
        if not cache_result:
            # Nothing to replay — release immediately (mirrors
            # adapters.memory.InMemoryIdempotencyStore's behavior; see ADR-013).
            self.release(application_id, idempotency_key)
            return

        now = int(self._clock_seconds())
        self._table.put_item(
            Item={
                "pk": application_id,
                "sk": idempotency_key,
                "requestHash": request_hash,
                "status": _STATUS_COMPLETED,
                "result": result.model_dump_json(),
                "expiresAt": now + retention_seconds,
            }
        )

    def release(self, application_id: str, idempotency_key: str) -> None:
        self._table.delete_item(Key={"pk": application_id, "sk": idempotency_key})
