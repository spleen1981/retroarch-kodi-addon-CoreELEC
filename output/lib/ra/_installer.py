"""Standalone installer staged to `/tmp` by `updater.install_update`.

Invocation:
    python3 /tmp/_installer.py /tmp/ra_update.zip /storage/.kodi/addons/<addon> [--no-restart]

"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

log = logging.getLogger("ra._installer")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# How long we wait for the parent to exit before starting. The parent is
# Kodi (or the addon's UI process); we don't want to be writing into the
# addon dir while Python over there still has files open.
_PARENT_WAIT_SECONDS = 3.0

# Relative path of the marker file within Kodi's userdata addon_data dir.
# We avoid importing ra.paths so this stays standalone — the path is built
# from $HOME (or /storage as a fallback) and the addon dir basename.
_MARKER_BASENAME = "update_pending"


def main(argv: list[str]) -> int:
    restart = True
    positional: list[str] = []
    for arg in argv:
        if arg == "--no-restart":
            restart = False
        else:
            positional.append(arg)
    if len(positional) != 2:
        log.error("usage: %s <update.zip> <addon-dir> [--no-restart]", sys.argv[0])
        return 2

    zip_path = Path(positional[0])
    addon_dir = Path(positional[1])
    if not zip_path.is_file():
        log.error("installer: %s not found", zip_path)
        return 3

    backup = addon_dir.with_name(addon_dir.name + ".old")
    if backup.exists():
        # A previous update left a backup behind. Refuse to start: we don't
        # know if it's a successful rollback the user wants to keep, or a
        # failed install we'd be papering over.
        log.error(
            "installer: stale backup at %s; clean it up before re-running",
            backup,
        )
        return 6

    time.sleep(_PARENT_WAIT_SECONDS)

    staging = Path(tempfile.mkdtemp(prefix="ra_update_", dir=str(addon_dir.parent)))
    try:
        _extract(zip_path, staging)
        new_dir = _locate_extracted_root(staging, addon_dir.name)
        if new_dir is None:
            log.error("installer: extracted zip does not contain %s", addon_dir.name)
            return 4
        _swap(new_dir, addon_dir, backup)
    except Exception as exc:  # noqa: BLE001
        log.exception("installer: failed: %s", exc)
        shutil.rmtree(staging, ignore_errors=True)
        return 5
    finally:
        # Clean up the staging area whether or not the swap succeeded.
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        zip_path.unlink(missing_ok=True)

    # Drop the marker AFTER the swap so a SIGTERM mid-extract doesn't leave
    # a marker pointing at a half-installed addon.
    _write_pending_marker(addon_dir)

    if restart:
        _restart_kodi()
    return 0


def _extract(zip_path: Path, dst: Path) -> None:
    log.info("installer: extracting %s -> %s", zip_path, dst)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dst)


def _locate_extracted_root(staging: Path, addon_name: str) -> Path | None:
    """Find the addon dir inside the extracted zip.

    Upstream zips put the addon under `<addon_name>/...`. Some manual zips
    extract flat; in that case `staging` itself is the addon dir.
    """
    nested = staging / addon_name
    if nested.is_dir():
        return nested
    # Flat zip: treat the staging dir as the addon dir, but only if it has
    # an addon.xml at the top.
    if (staging / "addon.xml").is_file():
        return staging
    return None


def _swap(new_dir: Path, addon_dir: Path, backup: Path) -> None:
    """Replace addon_dir with new_dir, leaving the old version at `backup`.

    The backup is NOT removed here — it survives until the new addon
    confirms a successful start.
    """
    try:
        if addon_dir.exists():
            os.rename(addon_dir, backup)
        os.rename(new_dir, addon_dir)
    except OSError as exc:
        # Cross-device rename or busy file: fall back to a file-by-file copy.
        log.warning("installer: rename failed (%s); falling back to copy", exc)
        if addon_dir.exists() and not backup.exists():
            shutil.copytree(addon_dir, backup, symlinks=True)
        _replace_tree_in_place(new_dir, addon_dir)


def _replace_tree_in_place(src: Path, dst: Path) -> None:
    """Overwrite dst's contents with src, preserving dst's identity (inode)."""
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
    # Delete everything currently inside dst.
    for entry in dst.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
    # Copy in the new contents.
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target, follow_symlinks=False)


def _write_pending_marker(addon_dir: Path) -> None:
    """Drop the update_pending marker in the addon's userdata dir.

    Standalone helper (no ra imports): derive the marker location from
    $HOME and the addon's dir basename. Failure is logged but not fatal.
    """
    addon_home = _resolve_addon_home(addon_dir.name)
    try:
        addon_home.mkdir(parents=True, exist_ok=True)
        (addon_home / _MARKER_BASENAME).touch()
        log.info("installer: marker written at %s/%s", addon_home, _MARKER_BASENAME)
    except OSError as exc:
        log.warning("installer: cannot write update marker: %s", exc)


def _resolve_addon_home(addon_name: str) -> Path:
    """Mirror ra.paths._resolve_addon_home using only stdlib + env."""
    explicit = os.environ.get("ADDON_HOME")
    if explicit:
        return Path(explicit)
    home = Path(os.environ.get("HOME", "/storage"))
    return home / ".kodi" / "userdata" / "addon_data" / addon_name


def _restart_kodi() -> None:
    log.info("installer: restarting kodi")
    subprocess.call(["systemctl", "restart", "kodi"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
