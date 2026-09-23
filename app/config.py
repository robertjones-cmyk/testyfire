"""Configuration loading.

``config.yaml`` holds everything non-secret. Secrets are named by environment
variable (``*_env`` keys) and resolved at use time by :func:`env_secret`, so a
secret is never stored in the config, the database, or a log line.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("TORCH_CONFIG", "config.yaml"))


class Config:
    """Thin wrapper over the parsed YAML with dotted lookups."""

    def __init__(self, data: dict[str, Any], path: Path | None = None):
        self._data = data
        self.path = path

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        target = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(target, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return cls(data, target)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    # -- convenience paths ---------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return Path(self.get("app.data_dir", "./data"))

    @property
    def frames_dir(self) -> Path:
        return Path(self.get("app.frames_dir", "./data/frames"))

    @property
    def db_path(self) -> Path:
        return Path(self.get("app.db_path", "./data/torch.db"))

    def feeds(self) -> list[dict[str, Any]]:
        return list(self.get("feeds", []) or [])

    def feed(self, feed_id: str) -> dict[str, Any] | None:
        for entry in self.feeds():
            if entry.get("id") == feed_id:
                return entry
        return None

    def enabled_feeds(self) -> list[dict[str, Any]]:
        return [f for f in self.feeds() if f.get("enabled", True)]


class MissingSecret(Exception):
    """Raised when a configured ``*_env`` variable is not set."""


def env_secret(var_name: str | None, *, required: bool = False) -> str | None:
    """Read a secret from the environment. Never logs the value."""
    if not var_name:
        if required:
            raise MissingSecret("no environment variable name configured")
        return None
    value = os.environ.get(var_name)
    if not value and required:
        raise MissingSecret(f"environment variable {var_name} is not set")
    return value or None


_CONFIG: Config | None = None


def get_config(path: str | Path | None = None, *, reload: bool = False) -> Config:
    global _CONFIG
    if _CONFIG is None or reload or path is not None:
        _CONFIG = Config.load(path)
    return _CONFIG
