"""RetroArch AppImage stream: presence, compatibility, download.

The RetroArch AppImage is a per-platform binary published as a GitHub release
asset, NOT bundled in the addon ZIP. It lives in userdata (paths.APPIMAGE_DIR)
so it survives an addon self-update, and the user can drop it there manually.

This module runs in three contexts:
  - Kodi UI:    dialogs + DialogProgress available (interactive download).
  - Headless:   boot path / `python3 -m ra appimage_ready` — no dialogs, no
                network; only the offline readiness check.
  - Build host: never imports this module.

xbmcgui is imported lazily so headless callers never depend on it.

Compatibility contract (two directions):
  - Offline, addon -> AppImage: REQUIRED_APPIMAGE_MIN (baked in), checked at
    every launch against the installed AppImage version. Guards the boot path.
  - Online, AppImage -> addon: <requires_addon min> per manifest entry, checked
    only when selecting an AppImage to download, against the installed addon
    version. Bump both in lockstep whenever the AppRun<->Python env contract
    (RA_CEC_POWEROFF / RA_SHUTDOWN_FLAG / RA_XBOX360_SHUTDOWN) changes.
"""

from __future__ import annotations

import enum
import logging
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import netutil, paths

log = logging.getLogger(__name__)

# Minimum AppImage version this addon build accepts. Offline-checkable.
REQUIRED_APPIMAGE_MIN = "2.0.0"

# Progress callback: (percent 0-100, message) -> keep_going (False cancels).
ProgressCb = Callable[[int, str], bool]


class State(enum.Enum):
    READY = "ready"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED = "unsupported"   # platform unknown — no package exists for it


@dataclass
class AppImageRelease:
    version: str
    url: str
    target: str = ""                      # matched platform token (device.arch or arch)
    sha256: Optional[str] = None
    requires_addon: Optional[str] = None  # min addon version this AppImage needs

    @property
    def version_tuple(self) -> tuple[int, ...]:
        return netutil.parse_version(self.version)


# ============================================================ offline checks


def evaluate() -> tuple[State, Optional[Path]]:
    """Classify the installed AppImage state. No network, no dialogs.

    Returns (State, path) where path is the resolved installed AppImage when
    one exists (READY or INCOMPATIBLE), else None.
    """
    if not paths.platform_candidates():
        return State.UNSUPPORTED, None
    current = paths.installed_appimage()
    if current is None:
        return State.MISSING, None
    ver = paths.installed_appimage_version() or "0"
    if netutil.parse_version(ver) < netutil.parse_version(REQUIRED_APPIMAGE_MIN):
        return State.INCOMPATIBLE, current
    return State.READY, current


def import_dropped() -> tuple[list[str], int]:
    """Import host-matching AppImages dropped in the well-known import folders.

    Lets a user install/update the RetroArch package by copying it (over Samba)
    into /storage/.update or /storage/downloads instead of the deep userdata
    path. For every `retroarch-*.AppImage` found there:
      - host-matching builds are MOVED into APPIMAGE_DIR (consumed) and made
        executable;
      - incompatible builds (wrong family/arch, or malformed name) are DELETED
        (also consumed) so the import folder doesn't keep useless files.

    After importing, prunes the AppImage dir to the single active build. No
    network, no hash (manual trust, like a direct drop) — the filename target
    must match one of this host's candidates.

    Returns (imported_names, rejected_count).
    """
    if not paths.platform_candidates():
        return [], 0
    imported: list[str] = []
    rejected = 0
    for src_dir in paths.APPIMAGE_IMPORT_DIRS:
        if not src_dir.is_dir():
            continue
        for entry in sorted(src_dir.glob("retroarch-*.AppImage")):
            if not entry.is_file():
                continue
            if paths.is_host_appimage(entry.name):
                paths.APPIMAGE_DIR.mkdir(parents=True, exist_ok=True)
                dst = paths.APPIMAGE_DIR / entry.name
                try:
                    shutil.move(str(entry), str(dst))
                    dst.chmod(0o755)
                    log.info("appimage: imported %s from %s", entry.name, src_dir)
                    imported.append(entry.name)
                except OSError as exc:
                    log.warning("appimage: cannot import %s: %s", entry.name, exc)
            else:
                try:
                    entry.unlink()
                    rejected += 1
                    log.info("appimage: rejected incompatible drop %s", entry.name)
                except OSError as exc:
                    log.warning("appimage: cannot remove %s: %s", entry.name, exc)
    if imported:
        # Keep only the single active build for this host.
        current = paths.installed_appimage()
        if current is not None:
            _cleanup_other_versions(current)
    return imported, rejected


def is_ready_offline() -> bool:
    """True when a compatible AppImage is installed. Logs the reason if not.

    Imports any host-matching AppImage dropped in the import folders first, so
    a boot-to-RA start picks up a manually-placed package.
    """
    import_dropped()
    state, _ = evaluate()
    if state is not State.READY:
        log.warning("appimage: not ready (%s) for platform %s",
                    state.value, paths.PLATFORM)
    return state is State.READY


# ============================================================ manifest fetch


def fetch_appimage_release() -> Optional[AppImageRelease]:
    """Fetch updates.xml and return the best `<appimage>` entry for this host.

    An entry matches when its `platform` is one of this host's candidate targets
    (`paths.platform_candidates()` — the exact '<device>.<arch>' or the family-wide
    '<family>-any.<arch>'), its `distro` matches, and its `min_ver`/`max_ver`
    bracket the host OS. Entries whose `<requires_addon min>` exceeds the installed
    add-on version are rejected ("update the add-on first").

    Among the survivors the selection mirrors installed_appimage(): device-
    specific beats family-wide (target specificity is primary), highest version is
    the tiebreaker.
    """
    cands = paths.platform_candidates()
    if not cands:
        return None
    try:
        with urllib.request.urlopen(netutil.REPO_INFO_URL,
                                    timeout=netutil.HTTP_TIMEOUT) as resp:
            payload = resp.read()
    except OSError as exc:
        log.warning("appimage: cannot fetch %s: %s", netutil.REPO_INFO_URL, exc)
        return None
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        log.warning("appimage: cannot parse updates.xml: %s", exc)
        return None

    os_id, os_ver = netutil.host_os_info()
    addon_ver = netutil.parse_version(netutil.installed_addon_version())

    best: Optional[tuple[tuple[int, tuple[int, ...]], AppImageRelease]] = None
    for entry in root.iter("appimage"):
        target = entry.attrib.get("platform", "")
        if target not in cands:
            continue
        distro = entry.attrib.get("distro", "")
        if distro and distro.lower() != os_id.lower():
            continue
        min_ver = netutil.parse_version(entry.attrib.get("min_ver", "0"))
        if os_ver and min_ver > os_ver:
            continue
        max_ver_str = entry.attrib.get("max_ver", "")
        if max_ver_str and os_ver and netutil.parse_version(max_ver_str) < os_ver:
            continue
        version = (entry.findtext("version") or "").strip()
        url = (entry.findtext("download_url") or "").strip()
        if not version or not url:
            continue
        sha256 = (entry.findtext("sha256") or entry.attrib.get("sha256") or "").strip() or None
        requires_addon = _read_requires_min(entry, "requires_addon")
        if requires_addon and netutil.parse_version(requires_addon) > addon_ver:
            log.info("appimage: skipping %s — needs addon >= %s",
                     version, requires_addon)
            continue
        rel = AppImageRelease(version=version, url=url, target=target,
                              sha256=sha256, requires_addon=requires_addon)
        # More specific target == lower candidate index == higher priority;
        # version is the tiebreaker within the same target.
        key = (-cands.index(target), netutil.parse_version(version))
        if best is None or key > best[0]:
            best = (key, rel)

    if best is None:
        log.info("appimage: no compatible <appimage> for targets=%s distro=%s",
                 cands, os_id)
        return None
    return best[1]


def _read_requires_min(entry: ET.Element, tag: str) -> Optional[str]:
    node = entry.find(tag)
    if node is None:
        return None
    return (node.attrib.get("min") or "").strip() or None


# ============================================================ download + hash


def download_with_progress(
    rel: AppImageRelease,
    progress: ProgressCb,
) -> bool:
    """Download `rel` into APPIMAGE_DIR with progress + sha256 verification.

    Downloads to a `*.part` sidecar and only atomically renames to the final
    versioned name after the hash passes — so a partial / corrupt download is
    never globbed as an installed AppImage. `progress(pct, msg)` returns False
    to cancel. Returns True on success.
    """
    paths.APPIMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = rel.target or (paths.generic_target() or "")
    final = paths.APPIMAGE_DIR / paths.appimage_filename(rel.version, target)
    part = final.with_name(final.name + ".part")
    part.unlink(missing_ok=True)

    try:
        with urllib.request.urlopen(rel.url, timeout=netutil.HTTP_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            block = 1 << 16
            with part.open("wb") as fh:
                while True:
                    if not progress(_pct(done, total), _human(done, total)):
                        log.info("appimage: download cancelled by user")
                        part.unlink(missing_ok=True)
                        return False
                    chunk = resp.read(block)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
            progress(100, "Verifying…")
    except OSError as exc:
        log.warning("appimage: download failed: %s", exc)
        part.unlink(missing_ok=True)
        return False

    if rel.sha256 and not netutil.verify_sha256(part, rel.sha256):
        part.unlink(missing_ok=True)
        return False

    try:
        part.chmod(0o755)
        part.replace(final)   # atomic within the same filesystem
    except OSError as exc:
        log.warning("appimage: cannot finalize %s: %s", final, exc)
        part.unlink(missing_ok=True)
        return False
    log.info("appimage: installed %s", final.name)
    _cleanup_other_versions(keep=final)
    return True


def _pct(done: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(100, int(done * 100 / total))


def _human(done: int, total: int) -> str:
    mb = 1 << 20
    if total > 0:
        return f"{done / mb:.0f} / {total / mb:.0f} MB"
    return f"{done / mb:.0f} MB"


def _cleanup_other_versions(keep: Path) -> None:
    """Remove other installed AppImages usable on this host, keeping `keep`.

    Covers every candidate target (device-specific and family-wide), so a fresh
    download supersedes both an older device-specific build and a stale
    family-wide one.
    """
    for p in paths.installed_appimages():
        if p != keep:
            p.unlink(missing_ok=True)
            log.info("appimage: removed stale %s", p.name)


def delete_platform_appimages() -> None:
    """Remove every installed AppImage usable on this host (any candidate target)."""
    for p in paths.installed_appimages():
        p.unlink(missing_ok=True)
        log.info("appimage: deleted %s", p.name)
    # Also drop any leftover partial downloads.
    if paths.APPIMAGE_DIR.is_dir():
        for p in paths.APPIMAGE_DIR.glob("retroarch-*.AppImage.part"):
            p.unlink(missing_ok=True)


# ============================================================ interactive (UI)


def ensure_ready_interactive(addon, dialog, *, allow_update: bool = False) -> bool:
    """Make sure a compatible AppImage is present, prompting via Kodi dialogs.

    Returns True when RetroArch can be launched (AppImage present & compatible),
    False when the caller should abort (user declined, no package, etc.).

    Missing / incompatible / unsupported are always handled (mandatory — the
    add-on cannot launch otherwise). When `allow_update` is True (the unified
    "auto-update" setting is on, or the user invoked a manual update check) and
    the AppImage is already usable, a newer compatible release is offered too —
    the add-on and the AppImage ship paired in each release, so one check covers
    both streams.

    `addon` is an xbmcaddon.Addon (for notifications), `dialog` an xbmcgui.Dialog.
    """
    # First, pick up any AppImage the user dropped into the import folders
    # (/storage/.update, /storage/downloads) — a simpler manual-install path.
    # Two sequential toasts: how many imported, then how many rejected.
    imported, rejected = import_dropped()
    if imported:
        n = len(imported)
        _notify(dialog, f"Imported {n} RetroArch package{'s' if n != 1 else ''}")
    if rejected:
        _notify(dialog,
                f"Removed {rejected} incompatible RetroArch "
                f"package{'s' if rejected != 1 else ''}")

    state, current = evaluate()

    if state is State.UNSUPPORTED:
        _notify(dialog, "No RetroArch package is available for this device.")
        return False

    if state is State.READY:
        # Optional update: only when checking, and only if a newer one exists.
        if allow_update:
            rel = fetch_appimage_release()
            if rel and rel.version_tuple > netutil.parse_version(
                    paths.installed_appimage_version() or "0"):
                if dialog.yesno(
                    "RetroArch update available",
                    f"A newer RetroArch package (v{rel.version}) is available. "
                    f"Download it now?",
                ):
                    return _download_flow(addon, dialog, rel, delete_first=False)
        return True

    # MISSING or INCOMPATIBLE → we need a download; fetch the manifest first.
    rel = fetch_appimage_release()
    if rel is None:
        _notify(dialog,
                "No compatible RetroArch package found. Check your connection "
                "or update the add-on first.")
        return False

    if state is State.MISSING:
        if not dialog.yesno(
            "RetroArch package not installed",
            f"The RetroArch package for {paths.PLATFORM} (v{rel.version}) is "
            f"not installed.\nDownload it now?",
        ):
            _notify(dialog, "RetroArch package missing — not launched.")
            return False
        return _download_flow(addon, dialog, rel, delete_first=False)

    # INCOMPATIBLE
    cur_ver = paths.installed_appimage_version() or "?"
    if not dialog.yesno(
        "RetroArch package too old",
        f"The installed package (v{cur_ver}) is too old for this add-on.\n"
        f"Delete it and download v{rel.version}?",
    ):
        _notify(dialog, "RetroArch package incompatible — not launched.")
        return False
    return _download_flow(addon, dialog, rel, delete_first=True)


def _download_flow(addon, dialog, rel: AppImageRelease, *, delete_first: bool) -> bool:
    if delete_first:
        delete_platform_appimages()
    progress = _kodi_progress(addon)
    try:
        ok = download_with_progress(rel, progress.update_cb)
    finally:
        progress.close()
    if ok:
        _notify(dialog, f"RetroArch package updated to v{rel.version}.")
    else:
        _notify(dialog, "RetroArch package download failed.")
    return ok


def _notify(dialog, message: str) -> None:
    try:
        dialog.notification("RetroArch", message, str(paths.ICON), 4000)
    except Exception:  # noqa: BLE001
        log.info("appimage: %s", message)


class _kodi_progress:
    """Thin wrapper over xbmcgui.DialogProgress exposing an update_cb."""

    def __init__(self, addon) -> None:
        import xbmcgui  # type: ignore[import-not-found]
        self._dlg = xbmcgui.DialogProgress()
        self._dlg.create("RetroArch", "Downloading RetroArch package…")

    def update_cb(self, pct: int, msg: str) -> bool:
        # DialogProgress.iscanceled() returns True once the user cancels.
        if self._dlg.iscanceled():
            return False
        self._dlg.update(pct, msg)
        return True

    def close(self) -> None:
        try:
            self._dlg.close()
        except Exception:  # noqa: BLE001
            pass
