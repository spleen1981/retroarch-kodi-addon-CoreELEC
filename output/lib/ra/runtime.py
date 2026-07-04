"""Orchestrator to handle the RetroArch runtime."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import paths, system
from .ra_config import RetroArchConfig
from .settings import AddonSettings, LOG_ERROR, LOG_OFF, LOG_VERBOSE

log = logging.getLogger(__name__)


REQUIRED_VALUES: dict[str, str] = {
    # CoreELEC/KMS refresh switching can trigger a second audio initialization
    # on content load and leave ALSA busy. Keep disabled unless the RA-side
    # reinit path is fixed.
    "video_autoswitch_refresh_rate": "3",

    # CoreELEC CE22 does not provide connmanctl; RetroArch falls back to nmcli,
    # which may also be absent. Avoid noisy startup errors.
    "wifi_driver": "null",
}


class RetroArchRuntime:
    """Owns the lifecycle of a single retroarch process invocation."""

    def __init__(self, settings: AddonSettings, extra_args: Sequence[str] = ()) -> None:
        self.settings = settings
        self.extra_args = list(extra_args)
        self._stack = contextlib.ExitStack()
        self._appimage: Optional[Path] = None  # resolved in run()
        self._boot_path = False

    # ------------------------------------------------------------------ run

    def run(self) -> int:
        """Set up subsystems, exec retroarch, tear down, return its exit code."""
        self._install_signal_handlers()
        # Offline AppImage readiness guard. MUST run before _enter_subsystems
        # stops Kodi — on the boot path Kodi was already stopped by the shim,
        # so aborting here would leave a black screen unless we restart it.
        # The UI launch path (kodi_entry) has already offered the download
        # dialog; this is the backstop for the boot path and direct invocations.
        if not self._appimage_ready():
            return 1
        self._ensure_appimage_executable()
        try:
            with self._stack:
                self._prepare_filesystem()
                self._maybe_first_run()
                cfg = RetroArchConfig.load(paths.RA_CONFIG_FILE)
                self._boot_path = not system.kodi_active()
                self._enter_subsystems(cfg)
                self._enforce_runtime_config(cfg)
                cfg.save()
                self._prepare_display_for_retroarch()
                rc = self._exec_retroarch()
        finally:
            self._handle_power_action()
        return rc

    def _appimage_ready(self) -> bool:
        """Resolve the installed AppImage; abort cleanly if not usable.

        No dialogs here (we may be headless). On abort, restart Kodi if it is
        not running (boot path) so the user is not stranded at a black screen.
        """
        from . import appimage
        state, current = appimage.evaluate()
        if state is not appimage.State.READY:
            log.error("runtime: AppImage not ready (%s) for platform %s; aborting",
                      state.value, paths.PLATFORM)
            if not system.kodi_active():
                log.info("runtime: restarting kodi after aborted launch")
                system.systemctl("start", "kodi")
            return False
        self._appimage = current
        return True

    # -------------------------------------------------------- subsystems --

    def _enter_subsystems(self, cfg: RetroArchConfig) -> None:
        """Enter every subsystem context manager into the ExitStack."""
        from . import audio, mount, video

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

        # cec-mini-kb and xbox360-controllers-shutdown are started and stopped
        # by AppRun within the single FUSE mount shared with retroarch.
        # RA_CEC* and RA_XBOX360_SHUTDOWN env vars are passed to the AppImage
        # in _exec_retroarch; no separate processes or systemd units needed.

        if self.settings.bt_shutdown:
            self._stack.callback(self._cycle_bluetooth)

    # ---------------------------------------------------- runtime policy

    def _enforce_runtime_config(self, cfg: RetroArchConfig) -> None:
        """Enforce runtime-critical RetroArch options before every launch.

        These values are not just defaults. They protect the CoreELEC runtime
        environment from known-bad settings, so they are restored on each
        launch even if changed from RetroArch UI.
        """
        for key, value in REQUIRED_VALUES.items():
            current = cfg.get(key)
            if current != value:
                log.info(
                    "runtime config: enforcing %s=%s (was %s)",
                    key,
                    value,
                    current,
                )
                cfg.set(key, value)

    # ----------------------------------------------------------- display prep

    def _display_prep_cmd(self, label: str, cmd: str) -> int:
        """Run a small display-prep shell command and log compact output."""
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        out = (result.stdout or "").strip()
        if out:
            for line in out.splitlines():
                log.info("display prep %s: %s", label, line)
        else:
            log.debug("display prep %s: rc=%s", label, result.returncode)
        return result.returncode

    def _force_premodeset_enabled(self) -> bool:
        """Return true when the target-side premodeset fallback is enabled.

        This is intentionally a runtime flag so the workaround can be enabled
        on affected targets without rebuilding the add-on.
        """
        flag = getattr(paths, "ADDON_HOME", None)
        if flag is None:
            flag = Path("/storage/.kodi/userdata/addon_data/script.retroarch.launcher")
        return (flag / "force_premodeset").exists()

    def _prepare_display_for_retroarch(self) -> None:
        """Release boot display state before launching RetroArch.

        Older CoreELEC/LibreELEC variants may have used a userspace
        splash-image helper. CE22 does not ship it, so these commands are
        normally no-ops there, but keeping them preserves compatibility.

        The former CE22 boot workaround, a modetest premodeset, is now only a
        fallback. RetroArch handles connectors with encoder_id == 0 directly
        through the DRM possible-encoder fallback patch.
        """
        if not self._boot_path:
            log.debug("display prep: regular Kodi launch path, skipping")
            return

        log.info("preparing display for RetroArch")

        # Compatibility with older CoreELEC/LibreELEC variants that may have
        # used a userspace splash-image helper. CE22 has no such binary/service.
        self._display_prep_cmd(
            "splash-stop",
            "systemctl stop splash-image 2>/dev/null || true; "
            "pgrep splash-image | xargs -r kill -TERM 2>/dev/null || true; "
            "pgrep splash-image | xargs -r kill -KILL 2>/dev/null || true"
        )

        if not self._force_premodeset_enabled():
            log.debug("display prep: premodeset fallback disabled")
            return

        # Fallback only:
        # If a target still fails to bind a DRM encoder before RetroArch starts,
        # create addon_data/script.retroarch.launcher/force_premodeset.
        #
        # No hardcoded connector id: current mode comes from CoreELEC sysfs,
        # connected connector id comes from compact modetest parsing.
        self._display_prep_cmd(
            "premodeset-fallback",
            "if command -v modetest >/dev/null 2>&1 && [ -e /dev/dri/card0 ]; then "
            "mode=$(cat /sys/class/display/mode 2>/dev/null); "
            "conn=$(modetest -M meson -c 2>/dev/null | "
            "awk '$3 == \"connected\" {print $1; exit}'); "
            "if [ -n \"$mode\" ] && [ -n \"$conn\" ]; then "
            "echo \"connector=$conn mode=$mode\"; "
            "modetest -M meson -s \"$conn:$mode\" < /dev/null >/dev/null 2>&1; "
            "echo rc=$?; "
            "else "
            "echo \"skip: connector=$conn mode=$mode\"; "
            "fi; "
            "else "
            "echo \"skip: modetest or /dev/dri/card0 unavailable\"; "
            "fi"
        )

        import time
        time.sleep(0.1)


    # ----------------------------------------------------------- retroarch

    def _ensure_appimage_executable(self) -> None:
        """Ensure the AppImage has execute permission.

        A manually-dropped AppImage (or one extracted from a ZIP) may lack the
        execute bit. Called after _appimage_ready() has resolved self._appimage.
        """
        appimage = self._appimage
        if appimage is None:
            return
        if appimage.exists() and not os.access(appimage, os.X_OK):
            import stat as _stat
            appimage.chmod(
                appimage.stat().st_mode
                | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH
            )
            log.info("runtime: made %s executable", appimage.name)

    def _exec_retroarch(self) -> int:
        # Launch the AppImage. AppRun sets up LD_LIBRARY_PATH, starts
        # cec-mini-kb and xbox360-controllers-shutdown within the same
        # squashfs mount (no additional FUSE mounts), runs retroarch, then
        # cleans up the tools on exit. We communicate settings via RA_*
        # env vars so AppRun can configure the tools at launch time.
        args = [str(self._appimage), f"--config={paths.RA_CONFIG_FILE}"]
        if self.settings.log_level == LOG_VERBOSE:
            args.insert(1, "--verbose")
        args.extend(self.extra_args)

        log.info("exec: %s", " ".join(args))

        env = os.environ.copy()

        # FUSERMOUNT: needed for mount AND unmount of the AppImage squashfs.
        # Without it, the runtime can't find fusermount on exit → FUSE cleanup
        # hangs → system freezes after retroarch exits.
        if "FUSERMOUNT" not in env:
            fm = system.resolve_fusermount()
            if fm:
                env["FUSERMOUNT"] = fm

        # CEC and xbox360 settings: read by AppRun to start/stop tools.
        from . import cec
        env.update(cec.appimage_env(self.settings))
        if self.settings.xbox360_shutdown:
            env["RA_XBOX360_SHUTDOWN"] = "1"

        # Single source of truth for the shutdown-flag path: AppRun checks it
        # to switch the TV off (SIGUSR1 to cec-mini-kb) when the user picks
        # "shutdown" inside RetroArch.
        env["RA_SHUTDOWN_FLAG"] = str(paths.SHUTDOWN_FLAG)

        return self._run_appimage_process(args, env)

    def _run_appimage_process(self, args: Sequence[str], env: dict[str, str]) -> int:
        """Run AppImage/RetroArch while applying the addon log policy.

        stdout/stderr are always forwarded to this process stdout so systemd's
        journal keeps the full live trace.

        The persistent retroarch.log follows the addon setting:
          OFF     -> do not write RetroArch process output to file
          ERROR   -> write warning/error/fatal/traceback lines only
          VERBOSE -> write the full RetroArch process output
        """
        for handler in logging.getLogger().handlers:
            handler.flush()

        log_fp = None
        if self.settings.log_level != LOG_OFF:
            paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_fp = paths.LOG_FILE.open("a", encoding="utf-8")

        try:
            proc = subprocess.Popen(
                args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                errors="replace",
            )

            assert proc.stdout is not None
            for line in proc.stdout:
                # Keep journalctl complete.
                sys.stdout.write(line)
                sys.stdout.flush()

                if log_fp is not None and self._should_log_process_line(line):
                    log_fp.write(line)
                    log_fp.flush()

            return proc.wait()
        finally:
            if log_fp is not None:
                log_fp.close()

    def _should_log_process_line(self, line: str) -> bool:
        """Return whether an AppImage/RetroArch output line goes to file."""
        if self.settings.log_level == LOG_VERBOSE:
            return True
        if self.settings.log_level != LOG_ERROR:
            return False

        text = line.lower()
        return (
            "[error]" in text
            or "[fatal]" in text
            or "[warn]" in text
            or "error:" in text
            or "warning" in text
            or "traceback" in text
            or "exception" in text
        )

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
    _adopt_boot_log_or_clear(settings.log_level)
    if settings.log_level != _LOG_OFF_LOCAL():
        _enable_file_logging(settings.log_level)
    rc = RetroArchRuntime(settings, extra_args=argv).run()
    return rc


def _LOG_OFF_LOCAL() -> int:
    # Lazy import to keep this module light at import time.
    from .settings import LOG_OFF
    return LOG_OFF


def _adopt_boot_log_or_clear(log_level: int) -> None:
    """Reconcile the shim's retroarch_boot.log with the unified log file.

    OFF     -> delete everything in logs/ (true off, no disk footprint).
    ERROR / VERBOSE:
        - if retroarch_boot.log exists (shim recorded an error this boot),
          rotate retroarch.log -> .old and adopt boot log as retroarch.log
          so the unified file leads with the shim's trace;
        - otherwise standard rotation of retroarch.log -> .old.
    """
    from .settings import LOG_OFF
    if log_level == LOG_OFF:
        for f in (paths.BOOT_LOG_FILE, paths.LOG_FILE, paths.LOG_FILE_OLD):
            f.unlink(missing_ok=True)
        return
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    if paths.BOOT_LOG_FILE.exists():
        paths.LOG_FILE_OLD.unlink(missing_ok=True)
        if paths.LOG_FILE.exists():
            paths.LOG_FILE.replace(paths.LOG_FILE_OLD)
        paths.BOOT_LOG_FILE.replace(paths.LOG_FILE)
    elif paths.LOG_FILE.exists():
        paths.LOG_FILE.replace(paths.LOG_FILE_OLD)


def _configure_root_logging(settings: AddonSettings) -> None:
    """Set root logger level from the addon setting.

    OFF/ERROR -> WARNING root (default Python verbosity for journal).
    VERBOSE   -> INFO root (full pipeline trace).
    The FileHandler attached by _enable_file_logging filters per its own level.
    """
    from .settings import LOG_VERBOSE
    level = logging.INFO if settings.log_level == LOG_VERBOSE else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _enable_file_logging(log_level: int) -> None:
    """Attach a FileHandler for Python-side runtime logs.

    The retroarch.log file has been prepared by _adopt_boot_log_or_clear
    (either freshly empty after rotation, or seeded with the shim's trace
    from retroarch_boot.log). RetroArch/AppImage stdout/stderr is appended
    separately by _run_appimage_process() according to the same log policy.
    """
    from .settings import LOG_VERBOSE
    handler_level = logging.DEBUG if log_level == LOG_VERBOSE else logging.WARNING
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > handler_level:
        root.setLevel(handler_level)
    handler = logging.FileHandler(paths.LOG_FILE, mode="a", encoding="utf-8")
    handler.setLevel(handler_level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    ))
    root.addHandler(handler)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
