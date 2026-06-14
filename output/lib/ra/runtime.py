"""Orchestrator to handle the RetroArch runtime."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys
from typing import Sequence

from . import paths
from .ra_config import RetroArchConfig
from .settings import AddonSettings

log = logging.getLogger(__name__)


class RetroArchRuntime:
    """Owns the lifecycle of a single retroarch process invocation."""

    def __init__(self, settings: AddonSettings, extra_args: Sequence[str] = ()) -> None:
        self.settings = settings
        self.extra_args = list(extra_args)
        self._stack = contextlib.ExitStack()

    # ------------------------------------------------------------------ run

    def run(self) -> int:
        """Set up subsystems, exec retroarch, tear down, return its exit code."""
        self._install_signal_handlers()
        try:
            with self._stack:
                self._prepare_filesystem()
                self._maybe_first_run()
                cfg = RetroArchConfig.load(paths.RA_CONFIG_FILE)
                self._enter_subsystems(cfg)
                cfg.save()
                rc = self._exec_retroarch()
        finally:
            self._handle_power_action()
        return rc

    # -------------------------------------------------------- subsystems --

    def _enter_subsystems(self, cfg: RetroArchConfig) -> None:
        """Enter every subsystem context manager into the ExitStack."""
        from . import audio, cec, mount, system, video

        # Stop Kodi; everything below assumes Kodi is not running.
        # Skip the restart on the way out when a power action is pending —
        # otherwise the user sees a brief Kodi splash right before shutdown.
        self._stack.enter_context(
            system.kodi_stopped(restart_on_exit=self._should_restart_kodi)
        )

        # Optional remote ROMs over CIFS.
        if self.settings.roms_remote:
            self._stack.enter_context(mount.cifs_remote_roms(self.settings))

        # Force refresh rate; restore the original on cleanup.
        if self.settings.force_refresh_rate:
            self._stack.enter_context(
                video.refresh_rate_override(cfg, self.settings.forced_refresh_rate)
            )

        # Sync audio settings is one-shot: the user explicitly asked for
        # retroarch to match Kodi's audio device. No restore.
        if self.settings.sync_audio_settings:
            audio.sync_into(cfg)

        # cec-mini-kb runs alongside retroarch and is stopped on cleanup.
        if self.settings.cec_remote:
            self._stack.enter_context(cec.minikb_running(self.settings))

        # On exit (after the stack unwinds), optionally power off xbox360
        # controllers and cycle bluetooth. Registered as callbacks so they
        # run regardless of how the stack unwinds.
        if self.settings.xbox360_shutdown:
            self._stack.callback(self._xbox360_shutdown)
        if self.settings.bt_shutdown:
            self._stack.callback(self._cycle_bluetooth)

    # ----------------------------------------------------------- retroarch

    def _exec_retroarch(self) -> int:
        args = [str(paths.RA_BIN), f"--config={paths.RA_CONFIG_FILE}"]
        if self.settings.log_to_file:
            args.insert(1, "--verbose")
        args.extend(self.extra_args)
        log.info("exec: %s", " ".join(args))
        if not self.settings.log_to_file:
            return subprocess.call(args)
        # Combine RA's stdout/stderr into the same file the Python logger is
        # writing to. Both writers use append mode so individual writes are
        # atomic on POSIX and interleave correctly. Flush Python handlers
        # first so our "exec:" line lands before RA's startup banner.
        for h in logging.getLogger().handlers:
            h.flush()
        with open(paths.LOG_FILE, "a", encoding="utf-8") as fp:
            return subprocess.call(args, stdout=fp, stderr=subprocess.STDOUT)

    # ----------------------------------------------------- filesystem prep

    def _prepare_filesystem(self) -> None:
        """Create runtime dirs and seed retroarch.cfg if missing."""
        paths.ensure_runtime_dirs()
        if not paths.RA_CONFIG_FILE.exists() and paths.RA_DEFAULT_CFG.exists():
            paths.RA_CONFIG_FILE.write_bytes(paths.RA_DEFAULT_CFG.read_bytes())

    def _maybe_first_run(self) -> None:
        """Run one-time post-install fixups (path redirects, symlinks, ...)."""
        from . import firstrun
        # Migrate any legacy first-run flag stored inside ADDON_DIR (which is
        # wiped on every self-update) to the new location in ADDON_HOME.
        firstrun.migrate_legacy_flag()
        if paths.FIRST_RUN_FLAG.exists():
            return
        firstrun.run()

    # -------------------------------------------------------- power action

    def _power_pending(self) -> bool:
        """True when the user requested shutdown/reboot from inside retroarch."""
        return paths.SHUTDOWN_FLAG.exists() or paths.REBOOT_FLAG.exists()

    def _should_restart_kodi(self) -> bool:
        """Restart Kodi on unwind unless a power action is pending."""
        return not self._power_pending()

    def _handle_power_action(self) -> None:
        if paths.SHUTDOWN_FLAG.exists():
            paths.SHUTDOWN_FLAG.unlink(missing_ok=True)
            subprocess.call(["shutdown", "-P", "now"])
        elif paths.REBOOT_FLAG.exists():
            paths.REBOOT_FLAG.unlink(missing_ok=True)
            subprocess.call(["shutdown", "-r", "now"])
        else:
            # Hand control back to Kodi. `system.kodi_stopped`'s __exit__
            # already restarted it (with the DRM-teardown settle delay);
            # this branch is a no-op safety net.
            pass

    # ---------------------------------------------------- signal handling

    def _install_signal_handlers(self) -> None:
        def _raise_exit(signum: int, _frame) -> None:
            log.info("received signal %d, unwinding", signum)
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, _raise_exit)
        signal.signal(signal.SIGINT, _raise_exit)

    # ----------------------------------------------------------- helpers

    def _xbox360_shutdown(self) -> None:
        exe = paths.BIN_DIR / "xbox360-controllers-shutdown"
        if exe.exists():
            subprocess.call([str(exe)])

    def _cycle_bluetooth(self) -> None:
        # bluetoothctl power off / on. Ignore errors — if bluetoothctl
        # isn't installed or the controller is absent, there's nothing to
        # do and we shouldn't poison the unwind.
        for action in ("off", "on"):
            subprocess.call(
                ["bluetoothctl", "power", action],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = AddonSettings.load()
    _configure_root_logging(settings)
    if settings.log_to_file:
        _enable_file_logging()
    rc = RetroArchRuntime(settings, extra_args=argv).run()
    return rc


def _configure_root_logging(settings: AddonSettings) -> None:
    """Set root logger level from the addon setting.

    When `ra_log` is off, default to WARNING so we don't spam the systemd
    journal with INFO traces for every quiet launch. When on, INFO at the
    console and DEBUG via the file handler set up by `_enable_file_logging`.
    """
    level = logging.INFO if settings.log_to_file else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _enable_file_logging() -> None:
    """Attach a DEBUG FileHandler so Python and RetroArch share one log file.

    Rotates the previous session's log to `retroarch.log.old` so each run
    starts from an empty file. Only one generation is kept.
    """
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    if paths.LOG_FILE.exists():
        paths.LOG_FILE.replace(paths.LOG_FILE_OLD)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    handler = logging.FileHandler(paths.LOG_FILE, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    ))
    root.addHandler(handler)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
