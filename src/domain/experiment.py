"""Deterministic, weighted experiment routing (ADR-012).

Cohort assignment is a pure hash of a stable subject key — no randomness, no external
state. The same subject always lands in the same arm for a given experiment, and
different experiments never correlate (the experiment ID is part of the hash input), so
running two experiments concurrently for the same application/conversation doesn't bias
one against the other.
"""

import hashlib
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_HASH_SPACE = 0xFFFFFFFF  # first 8 hex digits of a sha256 digest


class ExperimentSubjectKeySource(StrEnum):
    APPLICATION_ID = "application_id"
    CONVERSATION_ID = "conversation_id"
    APPLICATION_AND_CONVERSATION = "application_and_conversation"


class ExperimentArm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    model_alias: str
    weight: int = Field(gt=0)


class ExperimentPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    arms: tuple[ExperimentArm, ...] = Field(min_length=2)
    subject_key_source: ExperimentSubjectKeySource = (
        ExperimentSubjectKeySource.APPLICATION_AND_CONVERSATION
    )

    @model_validator(mode="after")
    def _validate_unique_arms(self) -> "ExperimentPolicy":
        aliases = [arm.model_alias for arm in self.arms]
        if len(aliases) != len(set(aliases)):
            raise ValueError("experiment arms must not repeat the same model_alias")
        return self


def build_experiment_subject_key(
    experiment: ExperimentPolicy, application_id: str, conversation_id: str | None
) -> str:
    """Build the stable string hashed to assign a cohort.

    The experiment ID is always the first component, so the same application/
    conversation is assigned independently across different experiments.
    """
    parts = [experiment.experiment_id]
    source = experiment.subject_key_source
    if source in (
        ExperimentSubjectKeySource.APPLICATION_ID,
        ExperimentSubjectKeySource.APPLICATION_AND_CONVERSATION,
    ):
        parts.append(application_id)
    if (
        source
        in (
            ExperimentSubjectKeySource.CONVERSATION_ID,
            ExperimentSubjectKeySource.APPLICATION_AND_CONVERSATION,
        )
        and conversation_id is not None
    ):
        parts.append(conversation_id)
    return "|".join(parts)


def assign_experiment_cohort(subject_key: str, experiment: ExperimentPolicy) -> str:
    """Deterministically assign `subject_key` to one of `experiment.arms`, proportional
    to each arm's weight. Returns the selected arm's `model_alias`."""
    digest = hashlib.sha256(subject_key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / _HASH_SPACE  # in [0, 1]

    total_weight = sum(arm.weight for arm in experiment.arms)
    threshold = bucket * total_weight
    cumulative = 0
    for arm in experiment.arms:
        cumulative += arm.weight
        if threshold < cumulative:
            return arm.model_alias
    return experiment.arms[-1].model_alias  # pragma: no cover - only if bucket == 1.0 exactly
