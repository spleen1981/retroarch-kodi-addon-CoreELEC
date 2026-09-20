"""File logging for the Kodi-UI side of the add-on.

Kodi-hosted entry points (kodi_entry, appimage, updater, boot, firstrun) never
go through `runtime.main`, so nothing ever attached a FileHandler for them and
their `log.*` calls only reached kodi.log — the unified retroarch.log stayed
empty whenever the interesting work happened before RetroArch was launched.

The handler targets BOOT_LOG_FILE, not LOG_FILE, on purpose:
`runtime._adopt_boot_log_or_clear()` rotates retroarch.log -> .old and adopts
retroarch_boot.log as the new head on the next `python3 -m ra start`, so the UI
trace is preserved in front of the runtime trace instead of being wiped by that
rotation.
"""

from __future__ import annotations

import logging

from . import paths
from .settings import AddonSettings, LOG_OFF, LOG_VERBOSE

_MARK = "_ra_ui_log"
_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"


def setup_ui_logging() -> None:
    """Attach (or refresh) the UI-side FileHandler. Never raises.

    Idempotent: `reuselanguageinvoker=true` keeps the interpreter alive across
    invocations, so the handler is tagged and reused instead of stacking up.
    """
    try:
        level = AddonSettings.load().log_level
    except Exception:  # noqa: BLE001
        return

    root = logging.getLogger()
    existing = [h for h in root.handlers if getattr(h, _MARK, False)]

    if level == LOG_OFF:
        for handler in existing:
            root.removeHandler(handler)
            handler.close()
        return

    handler_level = logging.DEBUG if level == LOG_VERBOSE else logging.WARNING

    if existing:
        for handler in existing:
            handler.setLevel(handler_level)
    else:
        try:
            paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(
                paths.BOOT_LOG_FILE, mode="a", encoding="utf-8"
            )
        except OSError:
            return
        handler.setLevel(handler_level)
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, _MARK, True)
        root.addHandler(handler)

    if root.level == logging.NOTSET or root.level > handler_level:
        root.setLevel(handler_level)
