"""Interaction with systemd: stop/start Kodi, run detached services."""

from __future__ import annotations

import contextlib
import logging
import os
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
    """Check if a systemd unit is currently masked, including runtime masks."""
    result = subprocess.run(
        ["systemctl", "is-enabled", unit],
        capture_output=True,
        text=True,
    )
    out = f"{result.stdout}\n{result.stderr}".strip().lower()
    return "masked" in out


def kodi_active() -> bool:
    """True when the kodi.service systemd unit is currently active."""
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
        if not kodi_active():
            return True
        time.sleep(0.1)
    return False


def _stop_kodi_via_restartapp() -> None:
    """Stop Kodi without triggering a CEC standby broadcast to the TV."""
    log.info("masking kodi.service for this boot to prevent auto-restart")
    rc = systemctl("mask", "--runtime", "kodi")
    if rc != 0:
        log.warning(
            "runtime mask of kodi.service failed; continuing without persistent mask"
        )

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
    if kodi_active():
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


def resolve_fusermount() -> str:
    """Return an absolute path to fusermount3/fusermount, or empty string."""
    candidate = os.environ.get("FUSERMOUNT", "")
    if candidate:
        return candidate
    for path in (
        "/usr/bin/fusermount3", "/usr/bin/fusermount",
        "/bin/fusermount3", "/bin/fusermount",
    ):
        if os.path.isfile(path):
            return path
    return ""


def run_detached(unit_name: str, *args: str) -> int:
    """Run a command as a transient systemd unit and return immediately.

    Used for child processes that must outlive the parent retroarch
    invocation but still be stoppable by name (cec-mini-kb, the updater).
    """
    # --collect: systemd removes the transient unit automatically once it
    # reaches an inactive state (including failed). Without this, a previous
    # failed instance of the same unit name blocks the next systemd-run call.
    #
    # FUSERMOUNT must be forwarded explicitly via --setenv= because systemd-run
    # creates the transient unit with a minimal clean environment — the env
    # passed to subprocess.call() reaches systemd-run itself but is NOT
    # inherited by the spawned unit. Without FUSERMOUNT, the AppImage type-2
    # runtime cannot find fusermount3 in the unit's minimal PATH, so the FUSE
    # squashfs mount hangs and the AppImage never reaches exec.
    fusermount = resolve_fusermount()
    cmd = ["systemd-run", "-q", "--collect", "-u", unit_name]
    if fusermount:
        cmd.append(f"--setenv=FUSERMOUNT={fusermount}")
    cmd.extend(args)
    log.info("systemd-run: %s", " ".join(cmd))
    env = os.environ.copy()
    if fusermount:
        env["FUSERMOUNT"] = fusermount
    return subprocess.call(cmd, env=env)


def stop_unit(unit_name: str) -> int:
    """Stop a transient unit started with `run_detached`."""
    return subprocess.call(
        ["systemctl", "stop", unit_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
