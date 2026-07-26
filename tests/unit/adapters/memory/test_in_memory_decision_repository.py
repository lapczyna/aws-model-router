from datetime import UTC, datetime

import pytest

from adapters.memory.in_memory_decision_repository import InMemoryRoutingDecisionRepository
from domain.decision import RoutingDecision
from domain.enums import ProviderName
from domain.invocation import AuditRecord
from domain.reason_codes import RoutingReasonCode
from tests.support.fakes import make_policy

pytestmark = pytest.mark.unit

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _decision(decision_id: str) -> RoutingDecision:
    return RoutingDecision(
        decision_id=decision_id,
        application_id="app-1",
        created_at=FIXED_NOW,
        policy_id=make_policy().policy_id,
        policy_version=1,
        capability="balanced-text",
        selected_model_alias="model-a",
        provider=ProviderName.BEDROCK,
        reason_codes=(RoutingReasonCode.CAPABILITY_MATCH,),
        considered_candidates=(),
    )


def test_save_and_get_round_trip() -> None:
    repo = InMemoryRoutingDecisionRepository()
    record = AuditRecord(decision=_decision("dec_1"), invocation_attempts=())

    repo.save(record)

    assert repo.get("dec_1") == record


def test_get_returns_none_for_unknown_decision_id() -> None:
    repo = InMemoryRoutingDecisionRepository()
    assert repo.get("does-not-exist") is None


def test_save_overwrites_existing_record_for_same_decision_id() -> None:
    repo = InMemoryRoutingDecisionRepository()
    first = AuditRecord(decision=_decision("dec_1"), invocation_attempts=())
    repo.save(first)

    second_decision = _decision("dec_1").model_copy(update={"fallback_used": True})
    second = AuditRecord(decision=second_decision, invocation_attempts=())
    repo.save(second)

    assert repo.get("dec_1") == second
