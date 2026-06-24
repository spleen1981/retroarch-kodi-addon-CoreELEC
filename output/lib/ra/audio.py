"""Sync retroarch's audio_driver / audio_device with Kodi's settings."""

from __future__ import annotations

import json
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
    """True if RetroArch was built with `driver` (per `retroarch --features`).

    Backed by a cache so the (FUSE-mounting) `--features` probe runs at most
    once per AppImage build, not every launch — see `_supported_drivers`.
    """
    return driver.lower() in _supported_drivers()


def _supported_drivers() -> set[str]:
    """Return the set of audio-driver tokens RetroArch supports.

    Cached in userdata (paths.AUDIO_FEATURES_CACHE). The cache key is the
    AppImage's (filename, size, mtime) — cheap to compute (one os.stat, no
    hashing) and it changes whenever the AppImage is replaced, whether by a
    download (atomic rename → new mtime) or a manual copy (cp/mv → new mtime).
    On a key match we skip the probe entirely; otherwise we run `--features`
    once and rewrite the cache.
    """
    appimage = paths.installed_appimage()
    if appimage is None:
        log.warning("audio: no RetroArch AppImage installed; skipping driver check")
        return set()
    try:
        st = appimage.stat()
        sig = f"{appimage.name}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        sig = ""

    if sig:
        try:
            data = json.loads(paths.AUDIO_FEATURES_CACHE.read_text(encoding="utf-8"))
            if data.get("sig") == sig:
                return set(data.get("drivers", []))
        except (OSError, ValueError):
            pass

    drivers = _probe_features(appimage)
    if sig:
        try:
            paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            paths.AUDIO_FEATURES_CACHE.write_text(
                json.dumps({"sig": sig, "drivers": sorted(drivers)}),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("audio: cannot write features cache: %s", exc)
    return drivers


def _probe_features(appimage) -> set[str]:
    """Run `retroarch --features` via the AppImage; return the supported subset
    of the drivers we care about (the `_DRIVER_MAP` values).

    Uses the same loose match as before — a line containing the driver token
    and ": yes" — but only for alsa/pulse/pipewire, so we never depend on the
    exact column layout of `--features`.
    """
    try:
        result = subprocess.run(
            [str(appimage), "--features"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("audio: retroarch --features failed: %s", exc)
        return set()
    lines = [ln.lower() for ln in result.stdout.splitlines()]
    supported: set[str] = set()
    for driver in set(_DRIVER_MAP.values()):
        if any(driver in ln and ": yes" in ln for ln in lines):
            supported.add(driver)
    return supported


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
