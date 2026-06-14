"""Hints shown to the user via Kodi notifications."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import paths
from .ra_config import RetroArchConfig

log = logging.getLogger(__name__)


def assets_empty() -> bool:
    """Return True if the configured `assets_directory` is missing or empty."""
    cfg_path = paths.RA_CONFIG_FILE if paths.RA_CONFIG_FILE.exists() else paths.RA_DEFAULT_CFG
    if not cfg_path.exists():
        return False
    cfg = RetroArchConfig.load(cfg_path)
    raw = cfg.get("assets_directory")
    if not raw:
        return False
    assets_dir = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not assets_dir.is_dir():
        return True
    try:
        return not any(assets_dir.iterdir())
    except OSError:
        return False
