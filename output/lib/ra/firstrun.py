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

# Subdirs whose cfg `<sub>_directory` we redirect to the user-writable cfg dir
# and whose shipped content we copy. `system` is special: we never overwrite
# files already in the user's system dir (those are typically copyrighted
# BIOSes the user supplied themselves).
_NO_CLOBBER_SUBDIRS = frozenset({"system"})

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

    _restore_flattened_symlinks(paths.LIB_DIR)

    paths.FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
    paths.FIRST_RUN_FLAG.touch()
    log.info("firstrun: done")


def clear_flag() -> None:
    """Force the next launch to repeat first-run setup."""
    paths.FIRST_RUN_FLAG.unlink(missing_ok=True)


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
    """For each shipped subdir, redirect the cfg key and copy content.

    The cfg key naming convention is `<sub>_directory` for every entry in
    RA_CONFIG_SUBDIRS that the addon overrides (a few — `savestates`,
    `savefiles`, `playlists`, `thumbnails`, `remappings` — are also in
    RA_CONFIG_SUBDIRS but have no shipped content; we still create the dir).
    """
    for sub in paths.RA_CONFIG_SUBDIRS:
        target = paths.RA_CONFIG_DIR / sub
        target.mkdir(parents=True, exist_ok=True)
        cfg.set(f"{sub}_directory", str(target))

        source = paths.CONFIG_DIR / sub
        if not source.is_dir():
            continue
        no_clobber = sub in _NO_CLOBBER_SUBDIRS
        _merge_tree(source, target, no_clobber=no_clobber)


def _merge_tree(src: Path, dst: Path, *, no_clobber: bool) -> None:
    """Copy src into dst, optionally preserving any existing files in dst.

    Replaces the legacy `cp -r` / `cp -rn` pair. We walk in Python so we
    can keep behavior identical across the no-clobber and overwrite cases.
    """
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dst_root = dst / rel
        dst_root.mkdir(parents=True, exist_ok=True)
        for name in files:
            src_file = Path(root) / name
            dst_file = dst_root / name
            if no_clobber and dst_file.exists():
                continue
            shutil.copy2(src_file, dst_file)


def _restore_flattened_symlinks(root: Path) -> None:
    """Find `*.symlink` placeholder files and replace them with real symlinks.

    The packaging script flattens dangling symlinks into a placeholder file
    named `<original>.symlink` whose contents are the link target. This is
    how we ship symlinks inside a zip archive without losing them; here we
    restore them on disk.
    """
    if not root.is_dir():
        return
    for placeholder in root.rglob("*.symlink"):
        try:
            target = placeholder.read_text(encoding="utf-8").strip()
        except OSError as exc:
            log.warning("firstrun: cannot read %s: %s", placeholder, exc)
            continue
        if not target:
            continue
        link_path = placeholder.with_suffix("")  # drop `.symlink`
        try:
            link_path.unlink(missing_ok=True)
            link_path.symlink_to(target)
            placeholder.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("firstrun: cannot create symlink %s -> %s: %s",
                        link_path, target, exc)