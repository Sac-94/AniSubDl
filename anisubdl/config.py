"""Configuration management for AniSubDl (backward-compatible with v1 subdl.cfg)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Optional

CONFIG_FILE = "subdl.cfg"


@dataclass
class AppConfig:
    """Persisted user defaults in subdl.cfg."""

    anime_dir: Optional[str] = None
    provider: str = "auto"
    lang: str = "en"
    format: str = "any"
    resolution: str = "1080p"
    naming_style: str = "exact"
    workers: int = 4
    custom_animetosho_url: Optional[str] = None


def load_config(config_path: str = CONFIG_FILE) -> AppConfig:
    """
    Load configuration from subdl.cfg.
    Supports both v2 JSON format and legacy v1 plain-text directory path format.
    """
    cfg = AppConfig()
    if not os.path.exists(config_path):
        return cfg

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return cfg

        if raw.startswith("{"):
            data = json.loads(raw)
            for key, value in data.items():
                if hasattr(cfg, key) and value is not None:
                    setattr(cfg, key, value)
        else:
            # Legacy v1 format: plain path string
            cfg.anime_dir = raw
    except (OSError, json.JSONDecodeError):
        return cfg

    if cfg.anime_dir and not os.path.isdir(cfg.anime_dir):
        cfg.anime_dir = None

    return cfg


def save_config(cfg: AppConfig, config_path: str = CONFIG_FILE) -> bool:
    """Persist configuration to subdl.cfg as formatted JSON."""
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, indent=2)
        return True
    except OSError:
        return False
