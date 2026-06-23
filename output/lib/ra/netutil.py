"""Shared networking / versioning helpers used by updater.py and appimage.py.

Extracted so the two update streams (addon ZIP and the RetroArch AppImage)
reuse one HTTP download, one SHA-256 verifier, one version parser and one
/etc/os-release reader instead of duplicating them.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from . import paths

log = logging.getLogger(__name__)

# The upstream manifest listing the latest addon ZIP and per-platform AppImages.
REPO_INFO_URL = (
    "https://raw.githubusercontent.com/spleen1981/"
    "retroarch-kodi-addon-CoreELEC/master/updates.xml"
)

# How long we wait on HTTP requests. The upstream raw GitHub CDN is fast;
# 15 seconds is plenty and avoids hanging the UI on flaky networks.
HTTP_TIMEOUT = 15.0

# Block size for SHA-256 streaming; 1 MiB keeps memory bounded on the small
# Amlogic boxes while still amortizing syscall overhead.
_HASH_BLOCK = 1 << 20


def parse_version(value: str) -> tuple[int, ...]:
    """Parse `v1.2.3` or `1.2.3` (with optional `-suffix`) into a tuple of ints."""
    if not value:
        return (0,)
    value = value.lstrip("vV")
    chunks: list[str] = []
    for piece in value.split("."):
        chunks.extend(piece.split("-"))
    parts: list[int] = []
    for chunk in chunks:
        try:
            parts.append(int(chunk))
        except ValueError:
            # Non-numeric tail — stop accumulating; the rest is a variant tag.
            break
    return tuple(parts) if parts else (0,)


def host_os_info() -> tuple[str, Optional[tuple[int, ...]]]:
    """Return (ID, VERSION_ID tuple) from /etc/os-release, or ('', None)."""
    osr = paths._read_os_release()
    os_id = osr.get("ID", "")
    ver_str = osr.get("VERSION_ID", "")
    os_ver = parse_version(ver_str) if ver_str else None
    return os_id, os_ver


def installed_addon_version() -> str:
    """Read the addon's currently-installed version from `addon.xml`."""
    addon_xml = paths.ADDON_DIR / "addon.xml"
    if not addon_xml.is_file():
        return "0.0.0"
    try:
        root = ET.parse(addon_xml).getroot()
    except ET.ParseError as exc:
        log.warning("netutil: cannot parse %s: %s", addon_xml, exc)
        return "0.0.0"
    return root.attrib.get("version", "0.0.0")


def download_file(url: str, dst: Path, timeout: float = HTTP_TIMEOUT) -> bool:
    """Stream `url` to `dst`. Returns True on success, False on any OS error."""
    log.info("netutil: downloading %s", url)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, \
                dst.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    except OSError as exc:
        log.warning("netutil: download failed: %s", exc)
        dst.unlink(missing_ok=True)
        return False
    return True


def verify_sha256(path: Path, expected: str) -> bool:
    """Stream the file through SHA-256 and compare to the expected hex digest."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_HASH_BLOCK), b""):
                h.update(chunk)
    except OSError as exc:
        log.warning("netutil: cannot hash %s: %s", path, exc)
        return False
    actual = h.hexdigest()
    if actual.lower() != expected.lower():
        log.warning(
            "netutil: sha256 mismatch (got %s, expected %s)", actual, expected
        )
        return False
    log.info("netutil: sha256 ok for %s", path.name)
    return True
