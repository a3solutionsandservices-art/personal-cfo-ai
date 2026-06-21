"""Application configuration loading (PRD §10, FR-SRC-4, FR-TAX-1).

Loads ``settings.yaml``, ``sources.yaml``, and the taxonomy from a config
directory, plus secrets from the environment (``.env`` is loaded if present).
A malformed config fails fast with a clear error so a scheduled run never
proceeds on half-loaded state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .taxonomy import Taxonomy, load_taxonomy


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class FeedConfig:
    id: str
    type: str
    url: str
    enabled: bool
    show: str
    lookback_days: int


@dataclass(frozen=True)
class AppConfig:
    root: Path
    settings: dict
    feeds: list[FeedConfig]
    taxonomy: Taxonomy
    portfolio_path: Path

    # --- convenience accessors over the settings dict ---
    @property
    def scoring(self) -> dict:
        return self.settings["scoring"]

    @property
    def brief(self) -> dict:
        return self.settings["brief"]

    @property
    def segmenter(self) -> dict:
        return self.settings["segmenter"]

    @property
    def models(self) -> dict:
        return self.settings["models"]

    @property
    def delivery(self) -> dict:
        return self.settings["delivery"]

    @property
    def reliability(self) -> dict:
        return self.settings["reliability"]

    @property
    def transcription(self) -> dict:
        return self.settings["transcription"]

    @property
    def enabled_feeds(self) -> list[FeedConfig]:
        return [f for f in self.feeds if f.enabled]


_REQUIRED_SETTINGS = ["scoring", "brief", "segmenter", "models", "delivery", "reliability"]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name} is malformed: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must be a mapping")
    return data


def load_config(config_dir: str | Path = "config") -> AppConfig:
    """Load the full application config (FR-TAX-1 fail-fast semantics)."""
    _load_dotenv()
    root = Path(config_dir)
    if not root.is_dir():
        raise ConfigError(f"config directory not found: {root}")

    settings = _load_yaml(root / "settings.yaml")
    missing = [k for k in _REQUIRED_SETTINGS if k not in settings]
    if missing:
        raise ConfigError(f"settings.yaml missing required sections: {missing}")

    sources = _load_yaml(root / "sources.yaml")
    default_lookback = int((sources.get("defaults") or {}).get("lookback_days", 14))
    feeds: list[FeedConfig] = []
    for entry in sources.get("feeds", []):
        if "id" not in entry or "type" not in entry or "url" not in entry:
            raise ConfigError(f"feed entry missing id/type/url: {entry}")
        feeds.append(
            FeedConfig(
                id=str(entry["id"]),
                type=str(entry["type"]),
                url=str(entry["url"]),
                enabled=bool(entry.get("enabled", True)),
                show=str(entry.get("show", entry["id"])),
                lookback_days=int(entry.get("lookback_days", default_lookback)),
            )
        )

    taxonomy = load_taxonomy(root / "themes.yaml")

    return AppConfig(
        root=root,
        settings=settings,
        feeds=feeds,
        taxonomy=taxonomy,
        portfolio_path=root / "portfolio.md",
    )


def _load_dotenv() -> None:
    """Minimal ``.env`` loader (KEY=VALUE lines) so secrets stay out of code.

    Avoids a hard dependency on python-dotenv; existing environment variables
    always win over the file.
    """
    path = Path(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
