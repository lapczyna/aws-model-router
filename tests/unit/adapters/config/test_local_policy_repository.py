from pathlib import Path

import pytest

from adapters.config.local_policy_repository import LocalFileRoutingPolicyRepository
from domain.errors import ConfigurationError, RoutingPolicyNotFoundError

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "config"


def test_application_specific_policy_is_used_when_present() -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=FIXTURES / "policies_with_default" / "applications",
        default_policy_path=FIXTURES / "policies_with_default" / "default_policy.yaml",
    )

    policy = repo.resolve("app-a")

    assert policy.policy_id == "app-a-specific"
    assert policy.policy_version == 5
    assert policy.is_default is False


def test_falls_back_to_default_policy_when_application_specific_is_absent() -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=FIXTURES / "policies_with_default" / "applications",
        default_policy_path=FIXTURES / "policies_with_default" / "default_policy.yaml",
    )

    policy = repo.resolve("some-unregistered-app")

    assert policy.policy_id == "default"
    assert policy.is_default is True


def test_raises_when_neither_application_specific_nor_default_policy_exists(
    tmp_path: Path,
) -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=FIXTURES / "policies_without_default" / "applications",
        default_policy_path=tmp_path / "does_not_exist.yaml",
    )

    with pytest.raises(RoutingPolicyNotFoundError):
        repo.resolve("some-unregistered-app")


def test_application_specific_policy_still_resolves_without_a_default_configured() -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=FIXTURES / "policies_without_default" / "applications",
        default_policy_path=Path("does/not/exist.yaml"),
    )

    policy = repo.resolve("app-a")

    assert policy.policy_id == "app-a-specific"


def test_invalid_policy_file_raises_configuration_error(tmp_path: Path) -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=tmp_path / "applications",
        default_policy_path=FIXTURES / "invalid_standalone_policy.yaml",
    )

    with pytest.raises(ConfigurationError):
        repo.resolve("anything")


def test_resolved_policies_are_cached() -> None:
    repo = LocalFileRoutingPolicyRepository(
        applications_dir=FIXTURES / "policies_with_default" / "applications",
        default_policy_path=FIXTURES / "policies_with_default" / "default_policy.yaml",
    )

    first = repo.resolve("app-a")
    # If resolve() re-read the file, mutating it here would change the second result.
    second = repo.resolve("app-a")

    assert first is second
