"""Force display refresh rate to 50 / 60 Hz for the duration of a run.

CoreELEC exposes the active video mode via `/sys/class/display/mode` as a
string of one of these shapes:

    1080p60hz             plain HD-class mode
    2160p60hz             4K UHD, integer Hz
    2160p60hz420          4K UHD with chroma subsampling tag
    4k2k60hz              Amlogic legacy 4K name
    smpte24hz             cinema-standard SMPTE mode

Writing a new value to the same file switches the display. Retroarch's own
`video_refresh_rate` cfg key must match, otherwise input lag and audio drift
are noticeable.

The previous script overwrote both atomically and restored on exit. Here we
do the same as a context manager so the restore runs through `ExitStack`
even if retroarch crashes or is killed.

Edge cases:
    * `/sys/class/display/mode` may not exist on a desktop dev box; in that
      case we no-op so the unit tests still run.
    * The mode string may not parse (custom modes, missing rate); we treat
      that as "do nothing" rather than crashing — refresh rate forcing is
      best-effort.
    * The kernel may temporarily return EBUSY/EAGAIN if a previous mode
      switch is still settling; we retry a couple of times with a short
      backoff before giving up.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import re
import shutil
import subprocess
import time
from typing import Iterator, Optional

from . import paths
from .ra_config import RetroArchConfig

log = logging.getLogger(__name__)

# Mode string regex. Supports:
#   res in {"1080p", "720p", "2160p", "1080i", "4k2k", "smpte"}
#   trailing "<digits>hz"
#   optional trailing tag (e.g. "420" for 4:2:0 chroma) preserved verbatim
_MODE_RE = re.compile(
    r"^(?P<res>\d+[pi]|4k2k|smpte)(?P<rate>\d+)hz(?P<suffix>\w*)$",
    re.IGNORECASE,
)

_RATE_BY_INDEX = {0: 50, 1: 60}

# Retry budget for the sysfs write. EBUSY during a mode switch is normal on
# Amlogic; three attempts at 300 ms is generous without delaying the UI.
_WRITE_RETRIES = 3
_WRITE_BACKOFF_S = 0.3

# DRM modeset via modetest (libdrm) — used as a fallback when the sysfs
# write to /sys/class/display/mode is silently ignored by the driver.
# modetest is set-and-exit on this platform: it applies the mode,
# returns, the modeset persists. The tool is part of libdrm-tests on
# CoreELEC.
_MODETEST_TIMEOUT_S = 5.0
_MODETEST_DRIVER = "meson"
_CONNECTOR_RE = re.compile(
    r"^(\d+)\s+\d+\s+connected\s+HDMI-A-", re.MULTILINE
)


@contextlib.contextmanager
def refresh_rate_override(cfg: RetroArchConfig, target_index: int) -> Iterator[None]:
    """Force the display to 50 or 60 Hz; restore on exit.

    `target_index` follows the `ra_forced_refresh_rate` setting:
        0 -> 50 Hz (PAL), 1 -> 60 Hz (NTSC). Anything else is a no-op.
    """
    target_rate = _RATE_BY_INDEX.get(target_index)
    if target_rate is None:
        log.info("video: target index %s out of range, skipping", target_index)
        yield
        return

    original = _read_mode()
    if original is None:
        log.info("video: cannot read %s, skipping refresh rate override", paths.DISPLAY_MODE)
        yield
        return

    new_mode = _compose_mode(original, target_rate)
    if new_mode is None:
        yield
        return

    # No-op when the display is already at the requested rate. Writing the
    # same value to /sys/class/display/mode still triggers an HDMI
    # renegotiation on Amlogic, which on many TVs presents as a brief
    # power-cycle ("TV goes off and back on") during the Kodi -> RA
    # handover. Skip the write — and the restore — in that case.
    cfg["video_refresh_rate"] = f"{target_rate}.000000"
    if new_mode.lower() == original.strip().lower():
        log.info("video: display already at %s, skipping mode switch", new_mode)
        yield
        return

    log.info("video: switching display mode %s -> %s", original, new_mode)
    _write_mode(new_mode)
    try:
        yield
    finally:
        log.info("video: restoring display mode %s", original)
        _write_mode(original)


# --------------------------------------------------------------- internals


def _compose_mode(current: str, target_rate: int) -> Optional[str]:
    """Build the new mode string by swapping just the Hz component.

    Returns None when the current mode does not match the expected pattern
    (custom modes, missing rate) — caller treats that as "do nothing".
    """
    m = _MODE_RE.match(current.strip().lower())
    if m is None:
        log.info("video: mode %r does not match expected pattern, skipping", current)
        return None
    suffix = m.group("suffix") or ""
    return f"{m.group('res')}{target_rate}hz{suffix}"


def _read_mode() -> Optional[str]:
    try:
        return paths.DISPLAY_MODE.read_text().strip() or None
    except OSError:
        return None


def _modetest_apply(mode_name: str) -> None:
    """Force a DRM modeset commit on HDMI-A-1 via modetest.

    No-op when modetest is absent or no connected HDMI connector is
    found. Failures are logged at INFO level and swallowed: the sysfs
    write that ran first remains the source of truth on platforms
    where this path is irrelevant.
    """
    modetest = shutil.which("modetest")
    if modetest is None:
        return
    connector_id = _find_hdmi_connector(modetest)
    if connector_id is None:
        log.info("video: no connected HDMI connector found via modetest")
        return
    try:
        subprocess.run(
            [modetest, "-M", _MODETEST_DRIVER, "-s",
             f"{connector_id}:{mode_name}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_MODETEST_TIMEOUT_S,
            check=False,
        )
        log.info("video: modetest applied %s on connector %s",
                 mode_name, connector_id)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.info("video: modetest failed: %s", exc)


def _find_hdmi_connector(modetest: str) -> Optional[str]:
    """Parse `modetest -c` to find the connector id of HDMI-A-1 (connected)."""
    try:
        result = subprocess.run(
            [modetest, "-M", _MODETEST_DRIVER, "-c"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_MODETEST_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.info("video: modetest -c failed: %s", exc)
        return None
    m = _CONNECTOR_RE.search(result.stdout)
    if m is None:
        return None
    return m.group(1)


def _write_mode(value: str) -> None:
    """Write the mode, verify it took effect, and fall back to a DRM commit.

    Two driver families to support:

    Legacy Amlogic (kernel 4.9, fbdev/amvideo): the write to
        /sys/class/display/mode is the canonical modeset entry point.
        Readback reflects the new value, the driver propagates to
        HDMI, nothing more to do.

    Modern Amlogic (kernel 5.x+, DRM/KMS): the sysfs write is accepted
        silently but IGNORED — readback stays at the previous value.
        The driver expects a proper DRM commit instead. We fall back
        to modetest, which the driver honors.
    """
    for attempt in range(_WRITE_RETRIES):
        try:
            paths.DISPLAY_MODE.write_text(value)
            readback = _read_mode()
            if readback != value.strip():
                log.info("video: sysfs readback %r != written %r, "
                         "falling back to DRM modeset via modetest",
                         readback, value)
                _modetest_apply(value)
            return
        except OSError as exc:
            transient = exc.errno in (errno.EBUSY, errno.EAGAIN)
            if transient and attempt < _WRITE_RETRIES - 1:
                time.sleep(_WRITE_BACKOFF_S)
                continue
            log.warning("video: cannot write %s: %s", paths.DISPLAY_MODE, exc)
            return
