"""CEC integration: run cec-mini-kb alongside retroarch."""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

from . import paths
from .settings import AddonSettings
from .system import run_detached, stop_unit

log = logging.getLogger(__name__)

MINIKB_UNIT = "cec-kb"


@contextlib.contextmanager
def minikb_running(settings: AddonSettings) -> Iterator[None]:
    """Run `cec-mini-kb` as a transient systemd unit while inside the context."""
    bin_path = paths.BIN_DIR / "cec-mini-kb"
    if not bin_path.exists():
        log.info("cec: %s not present, skipping mini-kb", bin_path)
        yield
        return

    args: list[str] = [str(bin_path)]
    if settings.cec_poweroff == 0:
        # The mini-kb supports a `--poweroff <cmd>` flag: when the CEC
        # remote sends a "power" key, it shells out to <cmd>. We compose
        # the chain (xbox360 shutdown then `shutdown -P now`) once and
        # pass it as a single argv element.
        args.append("--poweroff")
        args.append(_compose_poweroff_command(settings))

    rc = run_detached(MINIKB_UNIT, *args)
    if rc != 0:
        log.warning("cec: systemd-run for %s returned %d", MINIKB_UNIT, rc)
    try:
        yield
    finally:
        stop_unit(MINIKB_UNIT)


def _compose_poweroff_command(settings: AddonSettings) -> str:
    parts: list[str] = []
    if settings.xbox360_shutdown:
        xbox_exe = paths.BIN_DIR / "xbox360-controllers-shutdown"
        parts.append(str(xbox_exe))
    parts.append("shutdown -P now")
    return ";".join(parts)
