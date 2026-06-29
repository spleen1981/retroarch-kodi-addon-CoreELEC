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

    if cmd == "reset":
        _reset_to_defaults(addon, dialog)
        return
    if cmd == "boot_toggle":
        _boot_toggle(addon, dialog)
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

    dialog.notification(
        NOTIF_TITLE, _localized(addon, 20186), str(paths.ICON), LONG_NOTIFICATION_MS
    )
    _launch_retroarch()


# ---------------------------------------------------------------- helpers


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

def _reset_to_defaults(addon, dialog) -> None:
    if not dialog.yesno(
        f"{_localized(addon, 13007)} (retroarch.cfg / setup)",
        _localized(addon, 750),
    ):
        return
    from .firstrun import backup_user_cfg, clear_flag
    backup_user_cfg()
    clear_flag()
    dialog.notification(
        NOTIF_TITLE,
        f"{_localized(addon, 13007)} (retroarch.cfg / setup)",
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

    rc = install_update(
        restart=not manual_update,
        messages={
            "downloading": _localized(addon, 24078),
            "installing": _localized(addon, 24086),
            "failed": _localized(addon, 113),
            "succeeded": _localized(addon, 24065),
        },
    )
    if rc != 0:
        dialog.notification(
            NOTIF_TITLE,
            f"{_localized(addon, 113)} ({rc})",
            str(paths.ICON),
            SHORT_NOTIFICATION_MS,
        )
        return _UPDATE_NONE
    return _UPDATE_INSTALLING



def _update_info_settings(addon) -> None:
    """Populate the read-only Info settings (shown inline in that category).

    Written whenever the add-on runs, so opening Settings shows the state as of
    the last invocation; the Refresh action repopulates them on demand.
    """
    from . import appimage
    addon.setSetting("ra_info_version", addon.getAddonInfo("version"))
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


def _maybe_presync_resources(addon, dialog) -> None:
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
    if marker_val == installed_ver:
        return

    appimage = paths.installed_appimage()
    if appimage is None:
        return

    log.info("kodi_entry: pre-sync needed (marker=%r, installed=%r)",
             marker_val, installed_ver)

    progress_file = Path("/tmp/ra_sync_progress")
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
    Skip the autoupdate flow entirely in plugin mode: it can block on
    a `yesno` dialog which would freeze the Games window. Manual update
    checks remain available via RunScript(..., check_updates).
    """
    import xbmcaddon   # type: ignore[import-not-found]
    import xbmcgui     # type: ignore[import-not-found]
    import xbmcplugin  # type: ignore[import-not-found]

    addon = xbmcaddon.Addon(id=paths.ADDON_NAME)
    dialog = xbmcgui.Dialog()

    # A missing/incompatible RetroArch AppImage is a hard stop, so the yesno +
    # progress dialog is justified here even though the *autoupdate* flow is
    # deliberately skipped in plugin mode. If not ready, close the directory so
    # the Games window doesn't hang, then return without launching.
    from . import appimage
    if not appimage.ensure_ready_interactive(addon, dialog, allow_update=False):
        try:
            handle = int(argv[1])
        except (IndexError, ValueError):
            handle = -1
        if handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
        return

    _maybe_presync_resources(addon, dialog)

    dialog.notification(
        NOTIF_TITLE, _localized(addon, 20186), str(paths.ICON), LONG_NOTIFICATION_MS
    )
    _launch_retroarch()

    try:
        handle = int(argv[1])
    except (IndexError, ValueError):
        handle = -1
    if handle >= 0:
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


# Re-export so default.py can still import it if a caller prefers AddonSettings.
__all__ = ["main", "plugin_main", "AddonSettings"]
