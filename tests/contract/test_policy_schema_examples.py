"""Validates the real, shipped configuration under `policies/` against the schema.

This is a contract test in the sense that it pins the repository's own sample
configuration to the domain schema it must satisfy — a regression check that doubles as
the "policy-schema validation" step planned for CI (Phase 8). It intentionally reads the
real `policies/` directory, not `tests/fixtures/`.
"""

from pathlib import Path

import pytest

from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from adapters.config.local_policy_repository import LocalFileRoutingPolicyRepository

pytestmark = pytest.mark.contract

POLICIES_DIR = Path(__file__).resolve().parents[2] / "policies"


def test_shipped_model_catalogue_is_valid() -> None:
    catalogue = LocalFileModelCatalogue(POLICIES_DIR / "model_catalogue.yaml")

    assert catalogue.catalogue_version >= 1
    assert catalogue.get_by_alias("economical-text-primary") is not None
    assert catalogue.get_by_alias("balanced-text-primary") is not None
    assert catalogue.get_by_alias("advanced-reasoning-primary") is not None


def test_shipped_default_policy_is_valid() -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=POLICIES_DIR / "applications",
        default_policy_path=POLICIES_DIR / "default_policy.yaml",
    )

    policy = repo.resolve("an-application-with-no-dedicated-policy-file")

    assert policy.is_default is True


def test_shipped_support_assistant_policy_is_valid() -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=POLICIES_DIR / "applications",
        default_policy_path=POLICIES_DIR / "default_policy.yaml",
    )

    policy = repo.resolve("support-assistant")

    assert policy.policy_id == "support-assistant-default"
    assert policy.is_default is False


def test_every_application_policys_allowed_model_aliases_exist_in_the_catalogue() -> None:
    catalogue = LocalFileModelCatalogue(POLICIES_DIR / "model_catalogue.yaml")
    applications_dir = POLICIES_DIR / "applications"
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=applications_dir, default_policy_path=POLICIES_DIR / "default_policy.yaml"
    )

    policy_files = [*applications_dir.glob("*.yaml"), POLICIES_DIR / "default_policy.yaml"]
    for policy_file in policy_files:
        application_id = policy_file.stem
        policy = repo.resolve(application_id)
        for alias in policy.allowed_model_aliases:
            assert catalogue.get_by_alias(alias) is not None, (
                f"{policy_file} allows model alias '{alias}' which is not in the " "model catalogue"
            )
