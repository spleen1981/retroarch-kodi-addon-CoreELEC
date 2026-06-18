"""Sync retroarch's audio_driver / audio_device with Kodi's settings."""

from __future__ import annotations

import logging
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional

from . import paths
from .ra_config import RetroArchConfig

log = logging.getLogger(__name__)

# Kodi driver token -> retroarch `audio_driver` value.
# PIPEWIRE was added in Kodi 21: CoreELEC builds shipping PipeWire as the
# system audio server expose it here, and retroarch grew matching native
# support in 1.16. Without this entry we'd fall back to "driver not handled"
# and leave audio_driver unchanged, which usually means retroarch tries the
# old ALSA path and gets blocked by PipeWire's exclusive grab.
_DRIVER_MAP = {
    "ALSA": "alsa",
    "PULSE": "pulse",
    "PIPEWIRE": "pipewire",
}


def sync_into(cfg: RetroArchConfig) -> bool:
    """Update `cfg` in place with the audio settings derived from Kodi.

    Returns True if at least one key was set. Returns False on any of the
    "cannot determine a working setting" conditions (no guisettings.xml,
    driver unsupported by this RA build, device missing). The caller is
    expected to leave the existing cfg values alone on False.
    """
    kodi_setting = _read_kodi_audio_setting()
    if kodi_setting is None:
        log.info("audio: no Kodi audiodevice setting found")
        return False

    driver_kodi, device = _split_driver_device(kodi_setting)
    ra_driver = _DRIVER_MAP.get(driver_kodi)
    if ra_driver is None:
        log.info("audio: Kodi driver %r is not handled", driver_kodi)
        return False

    if not _retroarch_supports_driver(ra_driver):
        log.info("audio: retroarch was not built with driver %s", ra_driver)
        return False

    if ra_driver == "alsa":
        if not _alsa_device_exists(device):
            log.info("audio: ALSA device %r not found via aplay -L", device)
            return False
        ra_device = device
    else:
        # Pulse and PipeWire manage devices themselves; let retroarch pick.
        ra_device = ""

    cfg["audio_driver"] = ra_driver
    cfg["audio_device"] = ra_device
    log.info("audio: set audio_driver=%s audio_device=%r", ra_driver, ra_device)
    return True


# --------------------------------------------------------------- internals


def _read_kodi_audio_setting() -> Optional[str]:
    path = paths.KODI_GUI_SETTINGS
    if not path.is_file():
        return None
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        log.warning("audio: cannot parse %s: %s", path, exc)
        return None
    # guisettings is a flat <settings><setting id="..."> tree; iterate to
    # avoid hard-coding the nesting depth which has changed between Kodi
    # major versions.
    for setting in tree.iter("setting"):
        if setting.attrib.get("id") == "audiooutput.audiodevice":
            return (setting.text or "").strip() or None
    return None


def _split_driver_device(raw: str) -> tuple[str, str]:
    """`DRIVER:DEVICE|FORMAT...` -> ('DRIVER', 'DEVICE')."""
    driver, sep, rest = raw.partition(":")
    if not sep:
        return raw, ""
    device = rest.split("|", 1)[0]
    return driver, device


def _retroarch_supports_driver(driver: str) -> bool:
    """Check `retroarch --features` for `<driver>: yes`."""
    try:
        result = subprocess.run(
            [str(paths.RA_BIN), "--features"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("audio: retroarch --features failed: %s", exc)
        return False
    # Output lines look like: "\tDriver name (alsa)            : yes"
    # We match any line that contains the driver name (case-insensitive)
    # followed by ": yes" later on the line.
    needle = driver.lower()
    for line in result.stdout.splitlines():
        lower = line.lower()
        if needle in lower and ": yes" in lower:
            return True
    return False


def _alsa_device_exists(device: str) -> bool:
    if not device:
        return False
    try:
        result = subprocess.run(
            ["aplay", "-L"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("audio: aplay -L failed: %s", exc)
        return False
    return any(line.strip() == device for line in result.stdout.splitlines())
