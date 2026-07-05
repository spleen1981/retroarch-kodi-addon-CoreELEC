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

# Single-line progress file consumed by Kodi UI during manual updates.
# Format:
#   10 extracting
#   60 installing
#   100 success
#   error <message>
_PROGRESS_FILE = Path("/tmp/ra_update_progress")
_PROGRESS_ENABLED = False


def _write_progress(head, message: str = "") -> None:
    """Atomically publish installer progress for Kodi UI consumers."""
    if not _PROGRESS_ENABLED:
        return
    line = f"{head} {message}".strip()
    tmp = _PROGRESS_FILE.with_name(_PROGRESS_FILE.name + ".tmp")
    try:
        tmp.write_text(line + "\n", encoding="utf-8")
        os.replace(tmp, _PROGRESS_FILE)
    except OSError as exc:
        log.warning("installer: cannot write progress: %s", exc)


def main(argv: list[str]) -> int:
    global _PROGRESS_ENABLED

    restart = True
    positional: list[str] = []
    for arg in argv:
        if arg == "--no-restart":
            restart = False
        else:
            positional.append(arg)

    # Only manual updates use Kodi-side progress consumption. Auto updates
    # restart Kodi and must not leave a stale /tmp progress file behind.
    _PROGRESS_ENABLED = not restart
    if not _PROGRESS_ENABLED:
        _PROGRESS_FILE.unlink(missing_ok=True)
        _PROGRESS_FILE.with_name(_PROGRESS_FILE.name + ".tmp").unlink(missing_ok=True)
    if len(positional) != 2:
        log.error("usage: %s <update.zip> <addon-dir> [--no-restart]", sys.argv[0])
        return 2

    zip_path = Path(positional[0])
    addon_dir = Path(positional[1])
    if not zip_path.is_file():
        log.error("installer: %s not found", zip_path)
        _write_progress("error", f"{zip_path} not found")
        return 3

    # Use only a temporary .tmp_old during the swap, then remove it.
    backup = addon_dir.with_name(addon_dir.name + ".tmp_old")
    if backup.exists():
        log.info("installer: removing stale temporary backup %s", backup)
        shutil.rmtree(backup, ignore_errors=True)

    _write_progress(1, "preparing")
    time.sleep(_PARENT_WAIT_SECONDS)

    _write_progress(5, "staging")
    staging = Path(tempfile.mkdtemp(prefix="ra_update_", dir=str(addon_dir.parent)))
    try:
        _write_progress(10, "extracting")
        _extract(zip_path, staging)

        _write_progress(35, "validating")
        new_dir = _locate_extracted_root(staging, addon_dir.name)
        if new_dir is None:
            log.error("installer: extracted zip does not contain %s", addon_dir.name)
            _write_progress("error", f"extracted zip does not contain {addon_dir.name}")
            return 4

        _write_progress(60, "installing")
        _swap(new_dir, addon_dir, backup)
    except Exception as exc:  # noqa: BLE001
        log.exception("installer: failed: %s", exc)
        _write_progress("error", str(exc))
        shutil.rmtree(staging, ignore_errors=True)
        return 5
    finally:
        # Clean up the staging area whether or not the swap succeeded.
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        zip_path.unlink(missing_ok=True)

    # Drop the marker AFTER the swap so a SIGTERM mid-extract doesn't leave
    # a marker pointing at a half-installed addon.
    _write_progress(90, "finalizing")
    _write_pending_marker(addon_dir)

    if restart:
        _write_progress(95, "restarting")
        _restart_kodi()

    _write_progress(100, "success")
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
    """Replace addon_dir with new_dir using a temporary rollback directory.

    `backup` is a transient .tmp_old directory used only during the swap window.
    If moving the new tree into place fails after the
    old tree was moved aside, the old tree is restored before re-raising.
    """
    backup_restored = False

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    try:
        if addon_dir.exists():
            os.rename(addon_dir, backup)

        try:
            os.rename(new_dir, addon_dir)
        except OSError:
            if backup.exists() and not addon_dir.exists():
                os.rename(backup, addon_dir)
                backup_restored = True
            raise

    except OSError as exc:
        # Cross-device rename or busy file: fall back to a file-by-file copy.
        log.warning("installer: atomic swap failed (%s); falling back to copy", exc)

        if not addon_dir.exists() and backup.exists() and not backup_restored:
            os.rename(backup, addon_dir)

        _replace_tree_in_place(new_dir, addon_dir)

    finally:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


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
