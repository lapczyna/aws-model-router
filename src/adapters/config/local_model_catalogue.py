from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from adapters.config.loader import load_structured_file
from domain.catalogue import ModelDefinition
from domain.enums import ModelResolutionType
from domain.errors import ConfigurationError


class LocalFileModelCatalogue:
    """`domain.ports.ModelCatalogue` implementation reading a version-controlled file.

    Loads and validates the entire catalogue once, at construction time — a malformed
    or internally inconsistent catalogue fails fast rather than surfacing errors
    lazily on the first lookup.
    """

    def __init__(self, catalogue_path: Path) -> None:
        data = load_structured_file(catalogue_path)

        if "catalogue_version" not in data or "models" not in data:
            raise ConfigurationError(
                f"Model catalogue at {catalogue_path} must define "
                "'catalogue_version' and 'models'"
            )

        try:
            self._catalogue_version = int(data["catalogue_version"])
            models = [ModelDefinition.model_validate(item) for item in data["models"]]
        except (TypeError, ValueError, ValidationError) as exc:
            raise ConfigurationError(f"Invalid model catalogue at {catalogue_path}: {exc}") from exc

        aliases = [model.model_alias for model in models]
        if len(aliases) != len(set(aliases)):
            duplicates = {alias for alias in aliases if aliases.count(alias) > 1}
            raise ConfigurationError(
                f"Duplicate model_alias values in catalogue at {catalogue_path}: {sorted(duplicates)}"
            )

        models_by_alias = {model.model_alias: model for model in models}
        for model in models:
            if model.resolution.type is not ModelResolutionType.ROUTER_ALIAS:
                continue
            target = models_by_alias.get(model.resolution.value)
            if target is not None and target.provider != model.provider:
                raise ConfigurationError(
                    f"router_alias {model.model_alias!r} (provider {model.provider.value!r}) "
                    f"targets {model.resolution.value!r} (provider {target.provider.value!r}) "
                    f"in catalogue at {catalogue_path} — a router_alias must target a model "
                    "from the same provider, since the alias's own provider determines which "
                    "adapter actually handles the invocation."
                )

        self._models = tuple(models)
        self._models_by_alias = {model.model_alias: model for model in models}
        self._models_by_capability: dict[str, list[ModelDefinition]] = defaultdict(list)
        for model in models:
            for tag in model.capabilities.capability_tags:
                self._models_by_capability[tag].append(model)

    @property
    def catalogue_version(self) -> int:
        return self._catalogue_version

    def find_by_capability(self, capability: str) -> Sequence[ModelDefinition]:
        return tuple(self._models_by_capability.get(capability, ()))

    def get_by_alias(self, model_alias: str) -> ModelDefinition | None:
        return self._models_by_alias.get(model_alias)

    def all_models(self) -> Sequence[ModelDefinition]:
        return self._models
