"""Tests `DynamoDbRoutingDecisionRepository` against a real (moto-simulated) DynamoDB
table.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from adapters.dynamodb.dynamodb_decision_repository import DynamoDbRoutingDecisionRepository
from domain.decision import RoutingDecision
from domain.enums import ProviderName
from domain.invocation import AuditRecord
from domain.reason_codes import RoutingReasonCode
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit


class _MutableClockSeconds:
    def __init__(self, start: float) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now


@pytest.fixture
def table() -> Iterator[object]:
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="decisions-test",
            KeySchema=[{"AttributeName": "decisionId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "decisionId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        yield resource.Table("decisions-test")


def _decision(decision_id: str) -> RoutingDecision:
    return RoutingDecision(
        decision_id=decision_id,
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


def test_save_and_get_round_trip(table: object) -> None:
    repo = DynamoDbRoutingDecisionRepository(
        table=table,  # type: ignore[arg-type]
        clock_seconds=_MutableClockSeconds(1000.0),
    )
    record = AuditRecord(decision=_decision("dec_1"), invocation_attempts=())

    repo.save(record)

    assert repo.get("dec_1") == record


def test_get_returns_none_for_unknown_decision_id(table: object) -> None:
    repo = DynamoDbRoutingDecisionRepository(
        table=table,  # type: ignore[arg-type]
        clock_seconds=_MutableClockSeconds(1000.0),
    )
    assert repo.get("does-not-exist") is None


def test_save_overwrites_existing_record_for_same_decision_id(table: object) -> None:
    repo = DynamoDbRoutingDecisionRepository(
        table=table,  # type: ignore[arg-type]
        clock_seconds=_MutableClockSeconds(1000.0),
    )
    first = AuditRecord(decision=_decision("dec_1"), invocation_attempts=())
    repo.save(first)

    second_decision = _decision("dec_1").model_copy(update={"fallback_used": True})
    second = AuditRecord(decision=second_decision, invocation_attempts=())
    repo.save(second)

    assert repo.get("dec_1") == second
