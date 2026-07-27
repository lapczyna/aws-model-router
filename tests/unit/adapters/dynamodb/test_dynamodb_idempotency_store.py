"""Tests `DynamoDbIdempotencyStore` against a real (moto-simulated) DynamoDB table —
exercising the actual conditional-write semantics (`ConditionExpression`), not a fake,
since that atomicity guarantee is exactly what ADR-018 depends on.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from adapters.dynamodb.dynamodb_idempotency_store import DynamoDbIdempotencyStore
from domain.decision import RoutingDecision
from domain.enums import ProviderName, Role, StopReason
from domain.idempotency import IdempotencyOutcome
from domain.invocation import InferenceResult
from domain.messages import Message
from domain.provider import ProviderResponse
from domain.reason_codes import RoutingReasonCode
from domain.usage import Usage
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit


class _MutableClockSeconds:
    def __init__(self, start: float) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def table() -> Iterator[object]:
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="idempotency-test",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        yield resource.Table("idempotency-test")


def _result() -> InferenceResult:
    decision = RoutingDecision(
        decision_id="dec_1",
        application_id="app-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        policy_id=make_policy().policy_id,
        policy_version=1,
        capability="balanced-text",
        selected_model_alias="model-a",
        provider=ProviderName.BEDROCK,
        reason_codes=(RoutingReasonCode.CAPABILITY_MATCH,),
        considered_candidates=(),
    )
    response = ProviderResponse(
        model_alias="model-a",
        provider=ProviderName.BEDROCK,
        message=Message(role=Role.ASSISTANT, content="hi"),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    return InferenceResult(decision=decision, response=response, invocation_attempts=())


def test_reserve_on_fresh_key_returns_new(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    reservation = store.reserve("app-1", "key-1", "hash-1")
    assert reservation.outcome is IdempotencyOutcome.NEW


def test_reserve_while_in_progress_returns_in_progress(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    reservation = store.reserve("app-1", "key-1", "hash-1")
    assert reservation.outcome is IdempotencyOutcome.IN_PROGRESS


def test_reserve_with_different_hash_returns_conflict(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    reservation = store.reserve("app-1", "key-1", "hash-2")
    assert reservation.outcome is IdempotencyOutcome.CONFLICT


def test_complete_with_caching_makes_result_replayable(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    result = _result()
    store.complete("app-1", "key-1", "hash-1", result, cache_result=True, retention_seconds=300)

    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.COMPLETED
    assert reservation.cached_result == result


def test_complete_without_caching_releases_the_key(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    store.complete("app-1", "key-1", "hash-1", _result(), cache_result=False, retention_seconds=300)

    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_release_frees_the_key(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    store.release("app-1", "key-1")

    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_cached_result_expires_after_retention_seconds(table: object) -> None:
    clock = _MutableClockSeconds(1000.0)
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=clock)  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    store.complete("app-1", "key-1", "hash-1", _result(), cache_result=True, retention_seconds=10)

    clock.advance(11)
    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_stale_in_progress_reservation_expires(table: object) -> None:
    clock = _MutableClockSeconds(1000.0)
    store = DynamoDbIdempotencyStore(table=table, stale_reservation_seconds=5, clock_seconds=clock)  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")

    clock.advance(6)
    reservation = store.reserve("app-1", "key-1", "hash-1")

    assert reservation.outcome is IdempotencyOutcome.NEW


def test_different_applications_do_not_share_keys(table: object) -> None:
    store = DynamoDbIdempotencyStore(table=table, clock_seconds=_MutableClockSeconds(1000.0))  # type: ignore[arg-type]
    store.reserve("app-1", "key-1", "hash-1")
    reservation = store.reserve("app-2", "key-1", "hash-1")
    assert reservation.outcome is IdempotencyOutcome.NEW
