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

    manual_update = cmd == "check_updates"
    if manual_update or addon.getSetting("ra_autoupdate") == "true":
        result = _run_updater(addon, dialog, manual_update=manual_update)
        if result is _UPDATE_INSTALLING or manual_update:
            # Updater restarts Kodi when done; do not also launch RA.
            return

    if addon.getSetting("ra_hints") == "true":
        _test_assets(dialog)

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
    # No loose binaries or libs in the thin addon — everything compiled is
    # inside the AppImage. PYTHONPATH points at lib/ (the standard Kodi addon
    # Python modules directory) so `python3 -m ra` finds the ra package.
    lib_dir = paths.ADDON_DIR / "lib"
    shell_cmd = (
        f". /etc/profile && "
        f"oe_setup_addon {paths.ADDON_NAME} && "
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


def _test_assets(dialog) -> None:
    from .hints import assets_empty
    if assets_empty():
        import xbmcaddon  # type: ignore[import-not-found]
        addon = xbmcaddon.Addon(id=paths.ADDON_NAME)
        dialog.ok(NOTIF_TITLE, _localized(addon, 32015))


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

    if addon.getSetting("ra_hints") == "true":
        _test_assets(dialog)

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
