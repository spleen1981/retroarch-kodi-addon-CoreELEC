"""In-place update of the addon (ZIP stream) from GitHub.

The upstream project publishes a versioned, platform-independent addon ZIP
together with an `updates.xml` manifest. From v2.0.0 the manifest carries a
single `<addon>` element (the addon is no longer per-platform); the RetroArch
AppImage is a separate stream handled by `appimage.py`.

Manifest (schema 2):
    <updates>
        <addon id="script.retroarch.launcher" distro="coreelec">
            <version>v2.0.0</version>
            <download_url>https://…</download_url>
            <sha256>…</sha256>
            <requires_appimage min="2.0.0"/>
        </addon>
        <appimage platform="Amlogic-ng.arm" …>…</appimage>
        …
    </updates>

Legacy v1.x installs read `<latest arch="…">` elements (via root.iter), which
this updater no longer emits matches for — those entries remain in the manifest
purely so old installs can still reach the v1.7.6 end-of-life build.
"""

from __future__ import annotations

import logging
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import netutil, paths
from .system import run_detached

log = logging.getLogger(__name__)

REPO_INFO_URL = netutil.REPO_INFO_URL
_HTTP_TIMEOUT = netutil.HTTP_TIMEOUT

_INSTALLER_UNIT = "ra-update-installer"


@dataclass
class _Release:
    version: str
    url: str
    sha256: Optional[str] = None
    requires_appimage: Optional[str] = None  # min AppImage version this addon needs

    @property
    def version_tuple(self) -> tuple[int, ...]:
        return netutil.parse_version(self.version)


# =================================================================== API ==


def check_for_update() -> bool:
    """Return True if a newer addon release than the installed one is available.

    Logs and returns False on any network or parse failure — auto-update is
    a convenience feature, not a critical path; a failure must never block
    the user from launching retroarch.
    """
    release = _fetch_latest_release()
    if release is None:
        return False
    current = netutil.installed_addon_version()
    log.info("updater: installed=%s latest=%s", current, release.version)
    return netutil.parse_version(current) < release.version_tuple


def install_update(
    restart: bool = True,
    messages: dict[str, str] | None = None,
) -> int:
    """Download the latest release and hand off to the detached installer."""
    notify = _make_notifier(messages)

    release = _fetch_latest_release()
    if release is None:
        log.warning("updater: cannot determine latest release")
        notify("failed")
        return 1

    notify("downloading")
    zip_path = paths.UPDATE_DOWNLOAD_DIR / "ra_update.zip"
    if not netutil.download_file(release.url, zip_path):
        notify("failed")
        return 2

    # Manifest checksums are optional today; once upstream begins emitting
    # them the verification kicks in automatically. A *mismatch* is always
    # a hard failure — never trust a tampered ZIP.
    if release.sha256:
        if not netutil.verify_sha256(zip_path, release.sha256):
            zip_path.unlink(missing_ok=True)
            notify("failed")
            return 2

    installer = _stage_installer()
    if installer is None:
        notify("failed")
        return 3

    notify("installing")
    cmd: list[str] = [
        "/usr/bin/env",
        "python3",
        str(installer),
        str(zip_path),
        str(paths.ADDON_DIR),
    ]
    if not restart:
        cmd.append("--no-restart")
    rc = run_detached(_INSTALLER_UNIT, *cmd)
    if rc != 0:
        log.warning("updater: systemd-run returned %d", rc)
        notify("failed")
        return rc
    notify("succeeded")
    return 0


def _make_notifier(messages: dict[str, str] | None):
    """Return a `notify(stage)` callable that fires a Kodi toast or no-ops."""
    if not messages:
        return lambda _stage: None
    try:
        import xbmcgui  # type: ignore[import-not-found]
    except ImportError:
        return lambda _stage: None
    dialog = xbmcgui.Dialog()

    def notify(stage: str) -> None:
        msg = messages.get(stage)
        if msg:
            dialog.notification("RetroArch", msg, str(paths.ICON), 2000)

    return notify


# ============================================================== internals ==


def _fetch_latest_release() -> Optional[_Release]:
    """Download `updates.xml` and locate the `<addon>` entry for this host.

    The addon is platform-independent in schema 2, so there is no `arch`
    matching: we take the single `<addon>` element, filter by `distro`
    (from /etc/os-release ID) and `min_ver`/`max_ver` against the host OS
    version, and read `version`, `download_url`, optional `sha256`, and the
    optional `<requires_appimage min="…"/>` cross-requirement.
    """
    try:
        with urllib.request.urlopen(REPO_INFO_URL, timeout=_HTTP_TIMEOUT) as resp:
            payload = resp.read()
    except OSError as exc:
        log.warning("updater: cannot fetch %s: %s", REPO_INFO_URL, exc)
        return None

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        log.warning("updater: cannot parse updates.xml: %s", exc)
        return None

    os_id, os_ver = netutil.host_os_info()

    best: Optional[tuple[tuple[int, ...], _Release]] = None
    for entry in root.iter("addon"):
        distro = entry.attrib.get("distro", "")
        if distro and distro.lower() != os_id.lower():
            continue
        min_ver = netutil.parse_version(entry.attrib.get("min_ver", "0"))
        if os_ver and min_ver > os_ver:
            continue  # requires a newer CoreELEC than what we're running
        max_ver_str = entry.attrib.get("max_ver", "")
        if max_ver_str and os_ver and netutil.parse_version(max_ver_str) < os_ver:
            continue  # this entry is too old for the running CoreELEC
        version = (entry.findtext("version") or "").strip()
        url = (entry.findtext("download_url") or "").strip()
        sha256 = (entry.findtext("sha256") or entry.attrib.get("sha256") or "").strip() or None
        requires = _read_requires_min(entry, "requires_appimage")
        if not version or not url:
            continue
        release = _Release(version=version, url=url, sha256=sha256,
                           requires_appimage=requires)
        if best is None or min_ver > best[0]:
            best = (min_ver, release)

    if best is None:
        log.info("updater: no matching <addon> entry for distro=%s in updates.xml",
                 os_id)
        return None
    return best[1]


def _read_requires_min(entry: ET.Element, tag: str) -> Optional[str]:
    """Read `<tag min="…"/>` from an entry; None when absent/empty."""
    node = entry.find(tag)
    if node is None:
        return None
    return (node.attrib.get("min") or "").strip() or None


def _stage_installer() -> Optional[Path]:
    """Copy `_installer.py` to `/tmp` so it survives the addon dir being wiped."""
    source = Path(__file__).with_name("_installer.py")
    if not source.is_file():
        log.warning("updater: missing installer module at %s", source)
        return None
    dst = paths.UPDATE_DOWNLOAD_DIR / "_installer.py"
    try:
        shutil.copy2(source, dst)
    except OSError as exc:
        log.warning("updater: cannot stage installer: %s", exc)
        return None
    return dst
