"""Configuration management with YAML + environment variable overrides."""

from pathlib import Path
from typing import Any

import yaml

from quantforge.core.errors import ConfigError

_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings:
    """Hierarchical settings: default.yaml <- {env}.yaml <- env vars."""

    def __init__(self, env: str = "development", config_dir: Path | None = None):
        self._config_dir = config_dir or _DEFAULT_CONFIG_DIR
        self._data: dict[str, Any] = {}
        self._load(env)

    def _load(self, env: str) -> None:
        # Load default config
        default_path = self._config_dir / "default.yaml"
        self._data = load_yaml(default_path)

        # Merge environment-specific overrides
        env_path = self._config_dir / f"{env}.yaml"
        if env_path.exists():
            env_data = load_yaml(env_path)
            self._data = deep_merge(self._data, env_data)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting by dot-separated key path. E.g. 'backtest.initial_capital'."""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise ConfigError(f"Setting not found: {key}")
        return value

    @property
    def data(self) -> dict[str, Any]:
        return self._data
