"""Interaction with systemd: stop/start Kodi, run detached services."""

from __future__ import annotations

import contextlib
import logging
import subprocess
import time
from typing import Callable, Iterator, Optional

log = logging.getLogger(__name__)

# Upper bound for how long we wait for Kodi to actually exit after asking it
# to RestartApp. Kodi's own teardown (settings flush, DB checkpoint, libcec
# deinit) takes ~2-5s in practice; 15s leaves slack for slow SD cards.
_KODI_EXIT_TIMEOUT_S = 15.0

# After SIGKILL, systemd reaps the process almost immediately. A short
# bounded wait is still cheaper than racing the next `systemctl start kodi`.
_KODI_KILL_TIMEOUT_S = 5.0

# DRM teardown settle delay before restarting kodi after retroarch exits.
# retroarch holds /dev/dri/card0 with an active EGL/GBM context and modeset
# until its subprocess returns; the kernel needs a beat to tear that state
# down before kodi.bin can create its own surface. Without this delay kodi
# races the cleanup and aborts with `std::logic_error: Creating a surface
# requires a display` (kodi.service exits 134). 2s is the lower bound that
# worked reliably in testing; bump if a slower SoC needs more.
_KODI_DRM_SETTLE_S = 2.0


def systemctl(*args: str, check: bool = False) -> int:
    """Thin wrapper around `systemctl`. Returns its exit code."""
    cmd = ["systemctl", *args]
    log.debug("systemctl: %s", " ".join(cmd))
    return subprocess.call(cmd) if not check else subprocess.check_call(cmd)


def is_masked(unit: str) -> bool:
    """Check if a systemd unit is currently masked."""
    rc = subprocess.call(
        ["systemctl", "is-enabled", "--quiet", unit],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # is-enabled returns 1 for masked; verify by parsing the human output.
    if rc == 0:
        return False
    result = subprocess.run(
        ["systemctl", "is-enabled", unit],
        capture_output=True,
        text=True,
    )
    return "masked" in result.stdout.strip().lower()


def _kodi_active() -> bool:
    rc = subprocess.call(
        ["systemctl", "is-active", "--quiet", "kodi"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return rc == 0


def _wait_for_kodi_exit(timeout_s: float) -> bool:
    """Poll `systemctl is-active kodi` until inactive or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _kodi_active():
            return True
        time.sleep(0.1)
    return False


def _stop_kodi_via_restartapp() -> None:
    """Stop Kodi without triggering a CEC standby broadcast to the TV."""
    log.info("masking kodi.service to prevent auto-restart")
    systemctl("mask", "kodi")

    log.info("asking kodi to exit via RestartApp (suppresses CEC standby)")
    rc = subprocess.call(["kodi-send", "--action=RestartApp"])
    if rc != 0:
        log.warning("kodi-send RestartApp returned %d", rc)

    if _wait_for_kodi_exit(_KODI_EXIT_TIMEOUT_S):
        log.info("kodi exited cleanly")
        return

    log.warning(
        "kodi did not exit within %.1fs; sending SIGKILL", _KODI_EXIT_TIMEOUT_S
    )
    systemctl("kill", "-s", "SIGKILL", "kodi")
    if not _wait_for_kodi_exit(_KODI_KILL_TIMEOUT_S):
        log.error("kodi still active after SIGKILL; proceeding anyway")


@contextlib.contextmanager
def kodi_stopped(
    restart_on_exit: Optional[Callable[[], bool]] = None,
) -> Iterator[None]:
    """Stop Kodi for the duration of the context, restart it on exit."""
    if _kodi_active():
        _stop_kodi_via_restartapp()
    else:
        log.info("kodi already stopped (boot path); skipping graceful stop")
    try:
        yield
    finally:
        _restart_kodi_if_wanted(restart_on_exit)


def _restart_kodi_if_wanted(
    restart_on_exit: Optional[Callable[[], bool]],
) -> None:
    if is_masked("kodi"):
        log.info("unmasking kodi")
        systemctl("unmask", "kodi")
    if restart_on_exit is not None and not restart_on_exit():
        log.info("not restarting kodi (caller requested skip)")
    else:
        log.info("waiting %.1fs for DRM teardown", _KODI_DRM_SETTLE_S)
        time.sleep(_KODI_DRM_SETTLE_S)
        log.info("starting kodi")
        systemctl("start", "kodi")


def run_detached(unit_name: str, *args: str) -> int:
    """Run a command as a transient systemd unit and return immediately.

    Used for child processes that must outlive the parent retroarch
    invocation but still be stoppable by name (cec-mini-kb, the updater).
    """
    cmd = ["systemd-run", "-q", "-u", unit_name, *args]
    log.info("systemd-run: %s", " ".join(cmd))
    return subprocess.call(cmd)


def stop_unit(unit_name: str) -> int:
    """Stop a transient unit started with `run_detached`."""
    return subprocess.call(
        ["systemctl", "stop", unit_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
