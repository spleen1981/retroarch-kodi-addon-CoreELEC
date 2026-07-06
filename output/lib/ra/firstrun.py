"""First-run setup for retroarch.cfg and the user's RA config tree."""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import time
from pathlib import Path

from . import i18n, paths
from .ra_config import RetroArchConfig

log = logging.getLogger(__name__)

def run() -> None:
    """Execute every first-run step, then drop the first-run flag."""
    log.info("firstrun: starting one-time setup")
    paths.ensure_runtime_dirs()

    cfg_path = paths.RA_CONFIG_FILE
    if not cfg_path.exists() and paths.RA_DEFAULT_CFG.exists():
        cfg_path.write_bytes(paths.RA_DEFAULT_CFG.read_bytes())

    cfg = RetroArchConfig.load(cfg_path)
    _seed_user_language(cfg)
    _override_subdirs(cfg)
    cfg.save()

    paths.FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
    paths.FIRST_RUN_FLAG.touch()
    log.info("firstrun: done")


def clear_flag() -> None:
    """Force the next launch to repeat first-run setup AND the AppImage
    resource sync.

    Clearing the marker `.resources_from_appimage` makes ra_sync redo the
    no-clobber/overwrite merge from the AppImage into the user RA config
    dir on the next launch — useful when the user has manually deleted
    resource subdirs and wants the shipped content re-materialized.
    Hard-coded name (kept in sync with ra_sync._MARKER_NAME; the two
    modules ship in different containers and cannot share constants).
    """
    paths.FIRST_RUN_FLAG.unlink(missing_ok=True)
    (paths.RA_CONFIG_DIR / ".resources_from_appimage").unlink(missing_ok=True)


def migrate_legacy_flag() -> None:
    """Move the pre-patch in-ADDON_DIR flag to ADDON_HOME, if present.

    Idempotent: subsequent calls are no-ops once the legacy file is gone.
    Safe to call before `run()` because we never touch the new flag here
    unless the legacy one was actually found.
    """
    legacy = paths.FIRST_RUN_FLAG_LEGACY
    if not legacy.exists():
        return
    try:
        paths.FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
        if not paths.FIRST_RUN_FLAG.exists():
            paths.FIRST_RUN_FLAG.touch()
        legacy.unlink(missing_ok=True)
        log.info("firstrun: migrated legacy flag to %s", paths.FIRST_RUN_FLAG)
    except OSError as exc:
        log.warning("firstrun: cannot migrate legacy flag: %s", exc)


def finalize_pending_update() -> None:
    """Clear the post-update marker and remove the `<addon>.old` backup.

    Called once at the start of `python3 -m ra start`. The presence of the
    marker is proof that we've actually reached the post-restart entry point
    of the freshly-installed addon — i.e. that the update was successful.
    """
    marker = paths.UPDATE_PENDING_FLAG
    if not marker.exists():
        return
    backup = paths.ADDON_DIR.with_name(paths.ADDON_DIR.name + ".old")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
        log.info("update: removed backup %s", backup)
    marker.unlink(missing_ok=True)


def backup_user_cfg() -> Path | None:
    """Move the user's retroarch.cfg to a dated sibling. Returns new path.

    Called from the "Clear RetroArch config" entry in the addon UI. We keep
    the backup rather than deleting because the user may want to diff or
    cherry-pick their old tweaks back into the regenerated cfg.
    """
    cfg_path = paths.RA_CONFIG_FILE
    if not cfg_path.exists():
        return None
    today = datetime.date.today().strftime("%y_%m_%d")
    backup = cfg_path.with_name(f"{cfg_path.name}_{today}_{int(time.time())}")
    cfg_path.rename(backup)
    log.info("firstrun: backed up cfg to %s", backup)
    return backup


# =============================================================== internals ==


def _seed_user_language(cfg: RetroArchConfig) -> None:
    locale = i18n.kodi_current_locale()
    code = i18n.retro_language_for(locale or "")
    cfg.set("user_language", str(code))
    log.info("firstrun: user_language=%d (locale=%s)", code, locale)


def _override_subdirs(cfg: RetroArchConfig) -> None:
    """Redirect every cfg `<sub>_directory` key to the user-writable RA config dir.

    The subdirs are created empty by paths.ensure_runtime_dirs(); their
    initial content (audio_filters, system, autoconfig, etc.) is materialized
    by the ra_sync module inside the AppImage on each launch — no file
    copy from the addon side here.
    """
    for sub in paths.RA_CONFIG_SUBDIRS:
        target = paths.RA_CONFIG_DIR / sub
        target.mkdir(parents=True, exist_ok=True)
        cfg.set(f"{sub}_directory", str(target))

