"""CLI dispatch for `python3 -m ra <command> [args...]`.

Used by the autostart shim and by Kodi's `RunScript()` actions. Keeps the
command surface tiny — each subcommand maps to a single function in a sibling
module. Adding a new command means adding one entry to `_COMMANDS`.

Note on logging: we deliberately do NOT call `logging.basicConfig()` here.
`runtime.main` configures the root logger from `AddonSettings` (WARNING by
default, INFO/DEBUG when `ra_log` is enabled), and we don't want this module to
silently force INFO on every invocation. The short-lived commands
(`check_updates`, `check_assets`, `boot_toggle`) inherit whatever default
the host gives them, which is fine because they only emit warnings.
"""

from __future__ import annotations

import sys
from typing import Callable, Sequence


def _cmd_start(argv: Sequence[str]) -> int:
    # Finalize any pending self-update BEFORE the runtime imports the rest
    # of the addon — the marker is also our signal that the new code has
    # actually reached this entry point, so it's safe to drop the rollback
    # backup at `<addon>.old`. See `firstrun.finalize_pending_update`.
    from .firstrun import finalize_pending_update
    finalize_pending_update()
    from .runtime import main
    return main(argv)


def _cmd_check_updates(_argv: Sequence[str]) -> int:
    from .updater import check_for_update
    return 0 if check_for_update() else 1


def _cmd_install_update(argv: Sequence[str]) -> int:
    from .updater import install_update
    restart = bool(argv and argv[0] == "restart")
    return install_update(restart=restart)


def _cmd_check_assets(_argv: Sequence[str]) -> int:
    from .hints import assets_empty
    return 0 if assets_empty() else 1


def _cmd_appimage_ready(_argv: Sequence[str]) -> int:
    # Headless readiness probe for the boot shim: 0 when a compatible RetroArch
    # AppImage is installed, non-zero otherwise. No dialogs, no network. The
    # shim uses this to avoid stopping Kodi when there is nothing to launch.
    from .appimage import is_ready_offline
    return 0 if is_ready_offline() else 1


def _cmd_clear_flags(_argv: Sequence[str]) -> int:
    from .firstrun import clear_flag
    clear_flag()
    return 0


def _cmd_clear_cfg(_argv: Sequence[str]) -> int:
    from .firstrun import backup_user_cfg
    return 0 if backup_user_cfg() else 1


def _cmd_boot_toggle(argv: Sequence[str]) -> int:
    from .boot import boot_toggle
    target = argv[0] if argv else None
    return boot_toggle(target)


_COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "start": _cmd_start,
    "check_updates": _cmd_check_updates,
    "install_update": _cmd_install_update,
    "check_assets": _cmd_check_assets,
    "appimage_ready": _cmd_appimage_ready,
    "clear_flags": _cmd_clear_flags,
    "clear_cfg": _cmd_clear_cfg,
    "boot_toggle": _cmd_boot_toggle,
}


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(f"usage: python3 -m ra <{' | '.join(_COMMANDS)}>", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    handler = _COMMANDS.get(cmd)
    if handler is None:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
