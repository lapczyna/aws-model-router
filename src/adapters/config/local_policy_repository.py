from pathlib import Path

from pydantic import ValidationError

from adapters.config.loader import load_structured_file
from domain.errors import ConfigurationError, RoutingPolicyNotFoundError
from domain.policy import RoutingPolicy


class LocalFileRoutingPolicyRepository:
    """`domain.ports.RoutingPolicyRepository` implementation reading version-controlled files.

    Looks for `<applications_dir>/<application_id>.yaml` (or `.yml`/`.json`) first;
    if it doesn't exist, falls back to the default policy at `default_policy_path`.
    Raises `RoutingPolicyNotFoundError` if neither is available. Resolved policies are
    cached in memory after their first successful load.
    """

    _EXTENSIONS = (".yaml", ".yml", ".json")

    def __init__(self, applications_dir: Path, default_policy_path: Path) -> None:
        self._applications_dir = applications_dir
        self._default_policy_path = default_policy_path
        self._cache: dict[str, RoutingPolicy] = {}
        self._default_policy: RoutingPolicy | None = None
        self._default_policy_loaded = False

    def resolve(self, application_id: str) -> RoutingPolicy:
        if application_id in self._cache:
            return self._cache[application_id]

        app_path = self._find_application_policy_file(application_id)
        if app_path is not None:
            policy = self._load_policy(app_path)
            self._cache[application_id] = policy
            return policy

        default_policy = self._load_default_policy()
        if default_policy is None:
            raise RoutingPolicyNotFoundError(
                f"No routing policy found for application '{application_id}' and no "
                "default policy is configured"
            )
        return default_policy

    def _find_application_policy_file(self, application_id: str) -> Path | None:
        for extension in self._EXTENSIONS:
            candidate = self._applications_dir / f"{application_id}{extension}"
            if candidate.exists():
                return candidate
        return None

    def _load_default_policy(self) -> RoutingPolicy | None:
        if self._default_policy_loaded:
            return self._default_policy
        self._default_policy_loaded = True
        if self._default_policy_path.exists():
            self._default_policy = self._load_policy(self._default_policy_path)
        return self._default_policy

    def _load_policy(self, path: Path) -> RoutingPolicy:
        data = load_structured_file(path)
        try:
            return RoutingPolicy.model_validate(data)
        except ValidationError as exc:
            raise ConfigurationError(f"Invalid routing policy at {path}: {exc}") from exc
