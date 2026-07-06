"""Kodi UI dispatch — replaces the legacy `default.py` + `util.py` pair.

Invoked by Kodi's `RunScript(addon_id [, command [, args...]])`:
    (no args)        -> launch retroarch (with optional autoupdate check)
    check_updates    -> manual update check + install dialog
    reset            -> reset retroarch.cfg and re-run first-run setup
    boot_toggle      -> toggle boot-to-retroarch on/off

Or by Kodi via the plugin protocol (Games/Programs window) — see
`plugin_main()`.

We import xbmc/xbmcaddon/xbmcgui lazily inside `main()` so that the module
is importable from a desktop test rig without the Kodi runtime.
"""

from __future__ import annotations

import logging
from typing import Sequence

from pathlib import Path

from . import paths
from .settings import AddonSettings, BOOT_TO_KODI, BOOT_TO_RA

log = logging.getLogger(__name__)

NOTIF_TITLE = "RetroArch"
LONG_NOTIFICATION_MS = 600_000
SHORT_NOTIFICATION_MS = 2_000


def main(argv: Sequence[str]) -> None:
    """Entry point called from default.py."""
    import xbmcaddon  # type: ignore[import-not-found]
    import xbmcgui  # type: ignore[import-not-found]

    addon = xbmcaddon.Addon(id=paths.ADDON_NAME)
    dialog = xbmcgui.Dialog()
    cmd = argv[0] if argv else None

    if cmd == "boot_toggle":
        _boot_toggle(addon, dialog)
        return
    if cmd == "sync_resources":
        _sync_resources_now(addon, dialog)
        return
    if cmd == "reset_config":
        _reset_retroarch_config(addon, dialog)
        return
    if cmd == "factory_reset":
        _factory_reset(addon, dialog)
        return

    # Keep the read-only Info settings fresh on every invocation (and on the
    # explicit Refresh action from that category).
    _update_info_settings(addon)
    if cmd == "refresh_info":
        return

    manual_update = cmd == "check_updates"
    want_update = manual_update or addon.getSetting("ra_autoupdate") == "true"

    # The add-on and the per-platform AppImage ship paired in each release, so a
    # single "auto-update" / "check for updates" covers both streams.
    #
    # The ADD-ON ZIP is checked FIRST.
    if want_update:
        result = _run_updater(addon, dialog, manual_update=manual_update)
        if result is _UPDATE_INSTALLING:
            # Updater restarts Kodi when done; the new add-on resumes the flow.
            return

    # AppImage: mandatory presence/compatibility, plus an optional update when
    # checking. Runs in Kodi UI context so the progress bar works, before we
    # detach to the ra-launcher unit.
    from . import appimage
    ready = appimage.ensure_ready_interactive(addon, dialog, allow_update=want_update)

    # Reflect the post-import/-download package in the Info settings.
    _update_info_settings(addon)

    # A manual "check for updates" stops here — it never launches RetroArch.
    if manual_update:
        return
    if not ready:
        return

    _maybe_presync_resources(addon, dialog)

    _notify_launching_retroarch(addon, dialog)
    _launch_retroarch()


# ---------------------------------------------------------------- helpers


def _notify_launching_retroarch(addon, dialog) -> None:
    """Show the launch notification and give Kodi a short time to render it."""
    dialog.notification(
        NOTIF_TITLE,
        _localized(addon, 20186),
        str(paths.ICON),
        LONG_NOTIFICATION_MS,
    )
    try:
        import xbmc  # type: ignore[import-not-found]
        xbmc.Monitor().waitForAbort(0.35)
    except Exception:  # noqa: BLE001
        pass


def _launch_retroarch() -> None:
    """Detach retroarch.start via systemd-run so Kodi can be stopped.

    `systemd-run` spawns the unit in a clean environment — no PYTHONPATH,
    no ADDON_DIR/ADDON_HOME from Kodi's own process. We rebuild what
    `ra_autostart.sh` sets up on boot, with one important twist:

        1. `. /etc/profile` to make `oe_setup_addon` visible (it's a
           shell function defined in the CoreELEC profile).
        2. `oe_setup_addon <name>` to export `$ADDON_DIR` / `$ADDON_HOME`.
        3. Prepend `ADDON_DIR` to `PYTHONPATH` so Python finds the `modules`
           package. Recent CoreELEC builds of `oe_setup_addon` do NOT extend
           PYTHONPATH, so `python3 -m modules` would fail with "No module
           named modules". We use the Python-resolved `paths.ADDON_DIR` here
           instead of the shell `$ADDON_DIR` — inside Kodi `paths.ADDON_DIR`
           comes from `xbmcaddon.Addon().getAddonInfo("path")` and is
           guaranteed to point at the right place even when the shell variable
           isn't populated by this CoreELEC version.
        4. Exec the Python entry point.
    """
    from .system import run_detached
    lib_dir = paths.ADDON_DIR / "lib"
    boot_log = paths.BOOT_LOG_FILE
    # Clear any leftover boot-log from a previous failed session so the
    # runtime starts with a clean signal about THIS launch.
    # FATAL messages here are appended to retroarch_boot.log only on error;
    # runtime adopts it as retroarch.log when log_level is not OFF.
    shell_cmd = (
        f"mkdir -p {boot_log.parent} 2>/dev/null; "
        f"rm -f {boot_log} 2>/dev/null; "
        f". /etc/profile || "
        f"{{ echo \"$(date '+%F %T') FATAL: /etc/profile failed\" >> {boot_log}; exit 1; }}; "
        f"oe_setup_addon {paths.ADDON_NAME} || "
        f"{{ echo \"$(date '+%F %T') FATAL: oe_setup_addon failed\" >> {boot_log}; exit 1; }}; "
        f'PYTHONPATH="{lib_dir}${{PYTHONPATH:+:$PYTHONPATH}}" '
        f"exec python3 -m ra start"
    )
    run_detached("ra-launcher", "/bin/sh", "-c", shell_cmd)

def _sync_resources_now(addon, dialog) -> None:
    """Force a no-clobber RetroArch resource synchronization now."""
    _maybe_presync_resources(addon, dialog, force=True)


def _reset_retroarch_config(addon, dialog) -> None:
    """Backup and remove the user retroarch.cfg, then force first-run setup."""
    import time
    from .firstrun import clear_flag

    cfg = paths.RA_CONFIG_FILE
    if cfg.exists():
        backup = cfg.with_name(
            f"{cfg.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        )
        try:
            backup.write_bytes(cfg.read_bytes())
            cfg.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("reset config: cannot backup/remove %s: %s", cfg, exc)
            dialog.notification(
                NOTIF_TITLE,
                f"{_localized(addon, 113)}: {exc}",
                str(paths.ICON),
                SHORT_NOTIFICATION_MS,
            )
            return

    clear_flag()

    dialog.notification(
        NOTIF_TITLE,
        _localized(addon, 32038),
        str(paths.ICON),
        SHORT_NOTIFICATION_MS,
    )


def _factory_reset(addon, dialog) -> None:
    """Remove all add-on userdata and the RetroArch user configuration tree."""
    if not dialog.yesno(
        _localized(addon, 32034),
        _localized(addon, 32037),
    ):
        return

    import shutil

    for path in (paths.ADDON_HOME, paths.RA_CONFIG_DIR):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except OSError as exc:
            log.warning("factory reset: cannot remove %s: %s", path, exc)

    for path in (
        paths.UPDATE_PROGRESS_FILE,
        paths.UPDATE_PROGRESS_FILE.with_name(paths.UPDATE_PROGRESS_FILE.name + ".tmp"),
        paths.SYNC_PROGRESS_FILE,
        paths.SYNC_PROGRESS_FILE.with_name(paths.SYNC_PROGRESS_FILE.name + ".tmp"),
    ):
        path.unlink(missing_ok=True)

    dialog.notification(
        NOTIF_TITLE,
        _localized(addon, 32042),
        str(paths.ICON),
        SHORT_NOTIFICATION_MS,
    )

def _boot_toggle(addon, dialog) -> None:
    current = addon.getSetting("ra_boot_toggle")
    if current == BOOT_TO_RA:
        question = f"{BOOT_TO_RA}. {_localized(addon, 32012)} {BOOT_TO_KODI}?"
        new_value = BOOT_TO_KODI
    else:
        question = f"{BOOT_TO_KODI}. {_localized(addon, 32012)} {BOOT_TO_RA}?"
        new_value = BOOT_TO_RA
    if not dialog.yesno(_localized(addon, 32010), f"{_localized(addon, 32011)} {question}"):
        return
    from .boot import boot_toggle
    boot_toggle(target="on" if new_value == BOOT_TO_RA else "off")
    addon.setSetting("ra_boot_toggle", new_value)


# Sentinels for _run_updater return value.
_UPDATE_NONE = object()
_UPDATE_INSTALLING = object()


def _run_updater(addon, dialog, manual_update: bool):
    from .updater import check_for_update, install_update

    dialog.notification(
        NOTIF_TITLE, _localized(addon, 24092), str(paths.ICON), LONG_NOTIFICATION_MS
    )
    has_update = check_for_update()
    if not has_update:
        dialog.notification(
            NOTIF_TITLE, _localized(addon, 21341), str(paths.ICON), SHORT_NOTIFICATION_MS
        )
        return _UPDATE_NONE

    if not dialog.yesno(_localized(addon, 24061), _localized(addon, 24101)):
        dialog.notification(
            NOTIF_TITLE, _localized(addon, 16024), str(paths.ICON), SHORT_NOTIFICATION_MS
        )
        return _UPDATE_NONE

    previous_version = None
    if manual_update:
        from . import netutil
        previous_version = netutil.installed_addon_version()
        paths.UPDATE_PROGRESS_FILE.unlink(missing_ok=True)
        paths.UPDATE_PROGRESS_FILE.with_name(
            paths.UPDATE_PROGRESS_FILE.name + ".tmp"
        ).unlink(missing_ok=True)

    messages = {
        "downloading": _localized(addon, 24078),
        "installing": _localized(addon, 24086),
        "failed": _localized(addon, 113),
        "succeeded": _localized(addon, 24065),
    }

    progress_bar = None
    progress_cb = None

    if manual_update:
        # The background progress is the UI for manual updates. Suppress all
        # stage toasts here; _run_updater() already reports the final failure
        # with the return code when install_update() fails.
        messages = {}

        import xbmcgui  # type: ignore[import-not-found]
        progress_bar = xbmcgui.DialogProgressBG()
        progress_bar.create(NOTIF_TITLE, _localized(addon, 24078))

        def progress_cb(pct: int, msg: str) -> bool:
            # Download occupies the first half of the unified progress. The
            # installer progress is mapped by _refresh_kodi_addon_metadata().
            mapped = max(0, min(45, int(pct * 0.45)))
            progress_bar.update(mapped, NOTIF_TITLE, msg)
            return True

    rc = install_update(
        restart=not manual_update,
        messages=messages,
        progress=progress_cb,
    )
    if rc != 0:
        if progress_bar is not None:
            progress_bar.close()
        dialog.notification(
            NOTIF_TITLE,
            f"{_localized(addon, 113)} ({rc})",
            str(paths.ICON),
            SHORT_NOTIFICATION_MS,
        )
        return _UPDATE_NONE

    if manual_update:
        if not _refresh_kodi_addon_metadata(addon, dialog, previous_version, progress_bar):
            return _UPDATE_NONE

    return _UPDATE_INSTALLING



def _refresh_kodi_addon_metadata(
    addon,
    dialog,
    previous_version: str | None = None,
    pbar=None,
) -> bool:
    """Wait for manual self-update completion and refresh Kodi metadata.

    The installer is detached via systemd-run and publishes a single-line state
    file at /tmp/ra_update_progress. We follow that state with a background
    progress dialog and conclude only on a final success/error state.
    """
    import time
    import xbmc  # type: ignore[import-not-found]
    import xbmcaddon  # type: ignore[import-not-found]
    import xbmcgui  # type: ignore[import-not-found]
    from . import netutil

    progress_file = paths.UPDATE_PROGRESS_FILE
    monitor = xbmc.Monitor()
    own_pbar = pbar is None
    if pbar is None:
        pbar = xbmcgui.DialogProgressBG()
        pbar.create(NOTIF_TITLE, _localized(addon, 24086))
    else:
        pbar.update(45, NOTIF_TITLE, _localized(addon, 24086))

    final_state = ""
    final_message = ""

    try:
        deadline = time.monotonic() + 120.0
        last_line = ""

        while time.monotonic() < deadline and not monitor.abortRequested():
            try:
                line = progress_file.read_text(encoding="utf-8").strip()
            except OSError:
                line = ""

            if line and line != last_line:
                last_line = line
                parts = line.split(maxsplit=1)
                head = parts[0]
                msg = parts[1] if len(parts) > 1 else ""

                if head == "error":
                    final_state = "error"
                    final_message = msg or _localized(addon, 113)
                    pbar.update(100, NOTIF_TITLE, final_message)
                    break

                try:
                    pct = int(head)
                except ValueError:
                    pct = 0

                pct = max(0, min(100, pct))
                mapped_pct = 45 + int(pct * 0.55)
                mapped_pct = max(45, min(100, mapped_pct))
                pbar.update(mapped_pct, NOTIF_TITLE, msg)

                if pct >= 100:
                    final_state = "success"
                    final_message = msg
                    break

            monitor.waitForAbort(0.25)

        if not final_state:
            final_state = "error"
            final_message = "Timed out waiting for installer"
            pbar.update(100, NOTIF_TITLE, final_message)
    finally:
        if own_pbar:
            pbar.close()
        progress_file.unlink(missing_ok=True)
        progress_file.with_name(progress_file.name + ".tmp").unlink(missing_ok=True)

    if final_state != "success":
        if not own_pbar:
            pbar.close()
        log.warning("manual update failed or timed out: %s", final_message)
        dialog.notification(
            NOTIF_TITLE,
            f"{_localized(addon, 113)}: {final_message}",
            str(paths.ICON),
            SHORT_NOTIFICATION_MS,
        )
        return False

    # Optional sanity check: addon.xml should now differ from the old version.
    if previous_version:
        current = netutil.installed_addon_version()
        if current == previous_version:
            log.warning(
                "manual update reported success but addon.xml version is still %s",
                previous_version,
            )

    if not own_pbar:
        pbar.close()

    # Update our own Info settings from filesystem state.
    fresh_addon = xbmcaddon.Addon(id=paths.ADDON_NAME)
    _update_info_settings(fresh_addon)

    # Ask Kodi to rescan installed addon.xml metadata and refresh visible UI.
    xbmc.executebuiltin("UpdateLocalAddons")
    xbmc.executebuiltin("Container.Refresh")

    # Give Kodi's addon manager a short chance to process the async refresh.
    monitor.waitForAbort(1.0)
    return True

def _update_info_settings(addon) -> None:
    """Populate the read-only Info settings (shown inline in that category).

    Written whenever the add-on runs, so opening Settings shows the state as of
    the last invocation; the Refresh action repopulates them on demand.
    """
    from . import appimage, netutil
    addon.setSetting("ra_info_version", netutil.installed_addon_version())
    addon.setSetting("ra_info_platform", paths.PLATFORM or "unknown")
    rows = appimage.installed_summary()
    if not rows:
        addon.setSetting("ra_info_package", "(none installed)")
        return
    r = next((x for x in rows if x["active"]), rows[0])
    extra = f"  +{len(rows) - 1} more" if len(rows) > 1 else ""
    addon.setSetting(
        "ra_info_package",
        f"v{r['version']} — {r['target']} — {r['size_mb']:.0f} MB{extra}",
    )


def _maybe_presync_resources(addon, dialog, *, force: bool = False) -> None:
    """Run ra_sync via the installed AppImage while Kodi UI is still up.

    Detects a stale or missing `.resources_from_appimage` marker against the
    installed AppImage version; if mismatch, invokes the AppImage in
    `--sync-only` mode and shows a background progress dialog driven by
    `/tmp/ra_sync_progress` (single atomic line rewritten by ra_sync).

    Skipped silently in steady state (marker matches → no toast, no I/O).
    The boot path (ra_autostart.sh) cannot use this hook: no Kodi UI exists
    yet. ra_sync still runs as a backstop in AppRun on every launch.
    """
    import subprocess
    import time
    import xbmcgui  # type: ignore[import-not-found]

    marker = paths.RA_CONFIG_DIR / ".resources_from_appimage"
    installed_ver = paths.installed_appimage_version()
    if installed_ver is None:
        return
    try:
        marker_val = marker.read_text(encoding="utf-8").strip()
    except OSError:
        marker_val = ""
    if marker_val == installed_ver and not force:
        return

    appimage = paths.installed_appimage()
    if appimage is None:
        return

    log.info("kodi_entry: pre-sync needed (marker=%r, installed=%r)",
             marker_val, installed_ver)

    progress_file = paths.SYNC_PROGRESS_FILE
    pbar = xbmcgui.DialogProgressBG()
    pbar.create(NOTIF_TITLE, _localized(addon, 32023))

    proc = None
    try:
        proc = subprocess.Popen(
            [str(appimage), "--sync-only"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 180.0
        while True:
            _read_progress_and_update(progress_file, pbar)
            rc = proc.poll()
            if rc is not None:
                # One last read to capture final state.
                _read_progress_and_update(progress_file, pbar)
                break
            if time.monotonic() > deadline:
                log.warning("kodi_entry: pre-sync timeout, killing")
                proc.kill()
                proc.wait()
                break
            time.sleep(0.25)
    except OSError as exc:
        log.warning("kodi_entry: pre-sync failed (%s); AppRun will retry", exc)
    finally:
        pbar.close()
        progress_file.unlink(missing_ok=True)
        progress_file.with_name(progress_file.name + ".tmp").unlink(missing_ok=True)


def _read_progress_and_update(progress_file, pbar) -> None:
    """Read the atomic single-line progress file and forward to DialogProgressBG.

    Lines: "<N> <relpath>" (0-99), "100 done" (success), "error <msg>" (failure).
    The `error` and `done` lines naturally close the loop because the caller
    breaks on proc.poll() != None; no extra signaling needed.
    """
    try:
        line = progress_file.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not line:
        return
    parts = line.split(maxsplit=1)
    head = parts[0]
    msg = parts[1] if len(parts) > 1 else ""
    if head == "error":
        log.warning("kodi_entry: pre-sync reported error: %s", msg)
        return
    try:
        pct = int(head)
    except ValueError:
        return
    pbar.update(pct, NOTIF_TITLE, msg)


def _localized(addon, msg_id: int) -> str:
    """Look up a localized string. <32000 is Kodi-builtin; >=32000 is addon."""
    if msg_id < 32000:
        import xbmc  # type: ignore[import-not-found]
        return xbmc.getLocalizedString(msg_id)
    return addon.getLocalizedString(msg_id)


def plugin_main(argv: Sequence[str]) -> None:
    """Entry point when Kodi invokes us via plugin:// (Games/Programs window).

    The addon advertises `provides="executable game"`, so Kodi opens a
    directory request against us when the user navigates to those windows.
    We have no library to enumerate — we just notify + launch RetroArch
    detached, then close the directory.

    Order matters: do the work *before* endOfDirectory, because Kodi 22
    can reap the plugin invoker shortly after the directory is closed.
    Plugin mode is also the normal launch path from Kodi's Games/Programs UI,
    so it honors the same auto-update setting as script mode.
    """
    import xbmcaddon   # type: ignore[import-not-found]
    import xbmcgui     # type: ignore[import-not-found]
    import xbmcplugin  # type: ignore[import-not-found]

    addon = xbmcaddon.Addon(id=paths.ADDON_NAME)
    dialog = xbmcgui.Dialog()

    try:
        handle = int(argv[1])
    except (IndexError, ValueError):
        handle = -1

    def close_directory() -> None:
        if handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)

    # Keep Info settings fresh also when launched from Games/Programs.
    _update_info_settings(addon)

    # Plugin mode is the normal launch path from Kodi's Games/Programs UI, so it
    # must honor the same auto-update setting as script mode. If an add-on ZIP
    # update is installed, the installer restarts Kodi and this invocation stops.
    want_update = addon.getSetting("ra_autoupdate") == "true"
    if want_update:
        result = _run_updater(addon, dialog, manual_update=False)
        if result is _UPDATE_INSTALLING:
            close_directory()
            return

    # A missing/incompatible RetroArch AppImage is a hard stop, so the yesno +
    # progress dialog is justified here. If not ready, close the directory so
    # the Games window doesn't hang, then return without launching.
    from . import appimage
    if not appimage.ensure_ready_interactive(addon, dialog, allow_update=want_update):
        close_directory()
        return

    # Reflect post-import/-download AppImage state in Info settings.
    _update_info_settings(addon)

    _maybe_presync_resources(addon, dialog)

    _notify_launching_retroarch(addon, dialog)
    _launch_retroarch()

    close_directory()


# Re-export so default.py can still import it if a caller prefers AddonSettings.
__all__ = ["main", "plugin_main", "AddonSettings"]
