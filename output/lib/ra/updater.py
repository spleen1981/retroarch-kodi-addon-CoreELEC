"""In-place update of the addon from GitHub.

The upstream project publishes versioned ZIP releases together with an
`updates.xml` manifest at:

    https://raw.githubusercontent.com/spleen1981/retroarch-kodi-addon-CoreELEC/master/updates.xml
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths
from .system import run_detached

log = logging.getLogger(__name__)

REPO_INFO_URL = (
    "https://raw.githubusercontent.com/spleen1981/"
    "retroarch-kodi-addon-CoreELEC/master/updates.xml"
)

# How long we wait on HTTP requests. The upstream raw GitHub CDN is fast;
# 15 seconds is plenty and avoids hanging the UI on flaky networks.
_HTTP_TIMEOUT = 15.0

_INSTALLER_UNIT = "ra-update-installer"

# Block size for SHA-256 streaming; 1 MiB keeps memory bounded on the small
# Amlogic boxes while still amortizing syscall overhead.
_HASH_BLOCK = 1 << 20


@dataclass
class _Release:
    version: str
    url: str
    sha256: Optional[str] = None

    @property
    def version_tuple(self) -> tuple[int, ...]:
        return _parse_version(self.version)


# =================================================================== API ==


def check_for_update() -> bool:
    """Return True if a newer release than the installed one is available.

    Logs and returns False on any network or parse failure — auto-update is
    a convenience feature, not a critical path; a failure must never block
    the user from launching retroarch.
    """
    release = _fetch_latest_release()
    if release is None:
        return False
    current = _installed_version()
    log.info("updater: installed=%s latest=%s", current, release.version)
    return _parse_version(current) < release.version_tuple


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
    if not _download(release.url, zip_path):
        notify("failed")
        return 2

    # Manifest checksums are optional today; once upstream begins emitting
    # them the verification kicks in automatically. A *mismatch* is always
    # a hard failure — never trust a tampered ZIP.
    if release.sha256:
        if not _verify_sha256(zip_path, release.sha256):
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


def _installed_version() -> str:
    """Read the addon's currently-installed version from `addon.xml`."""
    addon_xml = paths.ADDON_DIR / "addon.xml"
    if not addon_xml.is_file():
        return "0.0.0"
    try:
        root = ET.parse(addon_xml).getroot()
    except ET.ParseError as exc:
        log.warning("updater: cannot parse %s: %s", addon_xml, exc)
        return "0.0.0"
    return root.attrib.get("version", "0.0.0")


def _fetch_latest_release() -> Optional[_Release]:
    """Download `updates.xml` and locate the entry for this addon variant.

    The manifest format is:
        <updates>
            <latest arch="Amlogic-no.aarch64" distro="coreelec" min_ver="21">
                <version>v1.7.5</version>
                <download_url>https://…</download_url>
            </latest>
            …
        </updates>

    We match on `arch` (== ADDON_NAME suffix after the last dot-separated
    addon-id prefix, i.e. the platform token) and `distro` (from
    /etc/os-release ID), then filter by `min_ver` <= host VERSION_ID.
    When multiple entries match (unlikely but allowed), the one with the
    highest `min_ver` is preferred — it is the most specific build.
    `sha256` is accepted as an optional attribute for forward compatibility.
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

    os_id, os_ver = _host_os_info()
    # ADDON_NAME is e.g. "script.retroarch.launcher.Amlogic-no.aarch64";
    # the arch token in the manifest is "Amlogic-no.aarch64" — everything
    # after the last occurrence of the distro-independent prefix.  We derive
    # it as the last two dot-separated components of the addon id so this
    # works for all variants without hard-coding the prefix length.
    parts = paths.ADDON_NAME.rsplit(".", 2)
    arch_token = ".".join(parts[-2:]) if len(parts) >= 2 else paths.ADDON_NAME

    best: Optional[tuple[tuple[int, ...], _Release]] = None
    for entry in root.iter("latest"):
        if entry.attrib.get("arch") != arch_token:
            continue
        if entry.attrib.get("distro", "").lower() != os_id.lower():
            continue
        min_ver_str = entry.attrib.get("min_ver", "0")
        min_ver = _parse_version(min_ver_str)
        if os_ver and min_ver > os_ver:
            continue  # requires a newer CoreELEC than what we're running
        max_ver_str = entry.attrib.get("max_ver", "")
        if max_ver_str and os_ver and _parse_version(max_ver_str) < os_ver:
            continue  # this entry is too old for the running CoreELEC
        version = (entry.findtext("version") or "").strip()
        url = (entry.findtext("download_url") or "").strip()
        sha256 = (entry.findtext("sha256") or entry.attrib.get("sha256") or "").strip() or None
        if not version or not url:
            continue
        release = _Release(version=version, url=url, sha256=sha256)
        if best is None or min_ver > best[0]:
            best = (min_ver, release)

    if best is None:
        log.info("updater: no matching entry for arch=%s distro=%s in updates.xml",
                 arch_token, os_id)
        return None
    return best[1]


def _host_os_info() -> tuple[str, Optional[tuple[int, ...]]]:
    """Return (ID, VERSION_ID tuple) from /etc/os-release, or ('', None) on error."""
    os_id = ""
    os_ver: Optional[tuple[int, ...]] = None
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("ID="):
                    os_id = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("VERSION_ID="):
                    ver_str = line.split("=", 1)[1].strip().strip('"')
                    os_ver = _parse_version(ver_str)
    except OSError as exc:
        log.warning("updater: cannot read /etc/os-release: %s", exc)
    return os_id, os_ver


def _download(url: str, dst: Path) -> bool:
    log.info("updater: downloading %s", url)
    try:
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT) as resp, \
                dst.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    except OSError as exc:
        log.warning("updater: download failed: %s", exc)
        dst.unlink(missing_ok=True)
        return False
    return True


def _verify_sha256(path: Path, expected: str) -> bool:
    """Stream the file through SHA-256 and compare to the expected hex digest."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_HASH_BLOCK), b""):
                h.update(chunk)
    except OSError as exc:
        log.warning("updater: cannot hash %s: %s", path, exc)
        return False
    actual = h.hexdigest()
    if actual.lower() != expected.lower():
        log.warning(
            "updater: sha256 mismatch (got %s, expected %s)", actual, expected
        )
        return False
    log.info("updater: sha256 ok")
    return True


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


def _parse_version(value: str) -> tuple[int, ...]:
    """Parse `v1.2.3` or `1.2.3` (with optional `-suffix`) into a tuple of ints."""
    if not value:
        return (0,)
    value = value.lstrip("vV")
    parts: list[int] = []
    # Split first on `.`, then handle any `-` separators in each chunk so a
    # rebuild marker like `3-2` contributes both 3 and 2 to the tuple.
    chunks: list[str] = []
    for piece in value.split("."):
        chunks.extend(piece.split("-"))
    for chunk in chunks:
        try:
            parts.append(int(chunk))
        except ValueError:
            # Non-numeric tail — stop accumulating; the rest is a variant tag.
            break
    return tuple(parts) if parts else (0,)
