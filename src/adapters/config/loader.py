import json
from pathlib import Path
from typing import Any

import yaml

from domain.errors import ConfigurationError


def load_structured_file(path: Path) -> dict[str, Any]:
    """Load a `.yaml`/`.yml`/`.json` file into a plain mapping.

    Raises `ConfigurationError` for an unsupported extension, unparseable content, or a
    top-level value that isn't a mapping.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"Could not read configuration file {path}: {exc}") from exc

    if path.suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Malformed YAML in {path}: {exc}") from exc
    elif path.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Malformed JSON in {path}: {exc}") from exc
    else:
        raise ConfigurationError(
            f"Unsupported configuration file extension: {path.suffix} ({path})"
        )

    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Configuration file {path} must contain a mapping at the top level"
        )

    return data
