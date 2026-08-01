from pathlib import Path

import pytest

from adapters.config.local_model_catalogue import LocalFileModelCatalogue
from domain.errors import ConfigurationError

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "config"


def test_loads_valid_catalogue() -> None:
    catalogue = LocalFileModelCatalogue(FIXTURES / "catalogue_valid.yaml")

    assert catalogue.catalogue_version == 2
    assert catalogue.get_by_alias("model-a") is not None
    assert catalogue.get_by_alias("does-not-exist") is None


def test_find_by_capability_returns_only_matching_models() -> None:
    catalogue = LocalFileModelCatalogue(FIXTURES / "catalogue_valid.yaml")

    balanced = catalogue.find_by_capability("balanced-text")
    reasoning = catalogue.find_by_capability("advanced-reasoning")
    none_found = catalogue.find_by_capability("does-not-exist")

    assert [m.model_alias for m in balanced] == ["model-a"]
    assert [m.model_alias for m in reasoning] == ["model-b"]
    assert none_found == ()


def test_all_models_returns_every_catalogued_model() -> None:
    catalogue = LocalFileModelCatalogue(FIXTURES / "catalogue_valid.yaml")

    aliases = {model.model_alias for model in catalogue.all_models()}

    assert aliases == {"model-a", "model-b"}


def test_invalid_schema_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        LocalFileModelCatalogue(FIXTURES / "catalogue_invalid_schema.yaml")


def test_duplicate_alias_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="Duplicate model_alias"):
        LocalFileModelCatalogue(FIXTURES / "catalogue_duplicate_alias.yaml")


def test_malformed_yaml_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        LocalFileModelCatalogue(FIXTURES / "malformed.yaml")


def test_malformed_json_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        LocalFileModelCatalogue(FIXTURES / "malformed.json")


def test_missing_required_top_level_keys_raises_configuration_error(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("models: []\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="catalogue_version"):
        LocalFileModelCatalogue(incomplete)


def test_unsupported_extension_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        LocalFileModelCatalogue(FIXTURES / "unsupported.txt")


def test_non_mapping_top_level_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        LocalFileModelCatalogue(FIXTURES / "not_a_mapping.json")


def test_router_alias_targeting_a_different_provider_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="must target a model from the same provider"):
        LocalFileModelCatalogue(FIXTURES / "catalogue_router_alias_cross_provider.yaml")
