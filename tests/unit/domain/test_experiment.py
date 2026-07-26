from collections import Counter

import pytest
from pydantic import ValidationError

from domain.experiment import (
    ExperimentArm,
    ExperimentPolicy,
    ExperimentSubjectKeySource,
    assign_experiment_cohort,
    build_experiment_subject_key,
)

pytestmark = pytest.mark.unit


def _policy(**overrides: object) -> ExperimentPolicy:
    defaults: dict[str, object] = {
        "experiment_id": "exp-1",
        "arms": (
            ExperimentArm(model_alias="arm-a", weight=70),
            ExperimentArm(model_alias="arm-b", weight=30),
        ),
    }
    defaults.update(overrides)
    return ExperimentPolicy.model_validate(defaults)


def test_rejects_duplicate_arm_aliases() -> None:
    with pytest.raises(ValidationError, match="must not repeat"):
        ExperimentPolicy(
            experiment_id="exp-1",
            arms=(
                ExperimentArm(model_alias="arm-a", weight=50),
                ExperimentArm(model_alias="arm-a", weight=50),
            ),
        )


def test_requires_at_least_two_arms() -> None:
    with pytest.raises(ValidationError):
        ExperimentPolicy(
            experiment_id="exp-1", arms=(ExperimentArm(model_alias="arm-a", weight=100),)
        )


def test_subject_key_includes_experiment_id_and_application_id() -> None:
    policy = _policy(subject_key_source=ExperimentSubjectKeySource.APPLICATION_ID)
    key = build_experiment_subject_key(policy, "app-1", conversation_id="conv-1")
    assert key == "exp-1|app-1"  # conversation_id excluded by subject_key_source


def test_subject_key_includes_conversation_id_when_configured() -> None:
    policy = _policy(subject_key_source=ExperimentSubjectKeySource.APPLICATION_AND_CONVERSATION)
    key = build_experiment_subject_key(policy, "app-1", conversation_id="conv-1")
    assert key == "exp-1|app-1|conv-1"


def test_subject_key_with_conversation_id_only_source_excludes_application_id() -> None:
    policy = _policy(subject_key_source=ExperimentSubjectKeySource.CONVERSATION_ID)
    key = build_experiment_subject_key(policy, "app-1", conversation_id="conv-1")
    assert key == "exp-1|conv-1"


def test_subject_key_omits_conversation_id_when_none() -> None:
    policy = _policy(subject_key_source=ExperimentSubjectKeySource.APPLICATION_AND_CONVERSATION)
    key = build_experiment_subject_key(policy, "app-1", conversation_id=None)
    assert key == "exp-1|app-1"


def test_different_experiment_ids_produce_independent_assignment() -> None:
    policy_a = _policy(experiment_id="exp-a")
    policy_b = _policy(experiment_id="exp-b")
    key_a = build_experiment_subject_key(policy_a, "app-1", conversation_id="conv-1")
    key_b = build_experiment_subject_key(policy_b, "app-1", conversation_id="conv-1")
    assert key_a != key_b


def test_cohort_assignment_is_deterministic() -> None:
    policy = _policy()
    key = "exp-1|app-1|conv-1"
    first = assign_experiment_cohort(key, policy)
    for _ in range(10):
        assert assign_experiment_cohort(key, policy) == first


def test_cohort_assignment_only_returns_configured_arms() -> None:
    policy = _policy()
    valid_aliases = {arm.model_alias for arm in policy.arms}
    for i in range(200):
        result = assign_experiment_cohort(f"subject-{i}", policy)
        assert result in valid_aliases


def test_cohort_allocation_respects_weight_proportions_within_tolerance() -> None:
    policy = _policy()  # 70/30 split
    counts: Counter[str] = Counter()
    sample_size = 5000
    for i in range(sample_size):
        counts[assign_experiment_cohort(f"app-{i}", policy)] += 1

    arm_a_fraction = counts["arm-a"] / sample_size
    arm_b_fraction = counts["arm-b"] / sample_size

    assert 0.65 <= arm_a_fraction <= 0.75
    assert 0.25 <= arm_b_fraction <= 0.35


def test_even_split_allocation_boundary() -> None:
    policy = _policy(
        arms=(
            ExperimentArm(model_alias="arm-a", weight=1),
            ExperimentArm(model_alias="arm-b", weight=1),
        )
    )
    counts: Counter[str] = Counter()
    sample_size = 4000
    for i in range(sample_size):
        counts[assign_experiment_cohort(f"subject-{i}", policy)] += 1

    assert 0.45 <= counts["arm-a"] / sample_size <= 0.55
    assert 0.45 <= counts["arm-b"] / sample_size <= 0.55
