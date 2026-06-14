"""Boot-to-RetroArch toggle.

CoreELEC runs `$HOME/.config/autostart.sh` once at boot if it exists and is
executable (the hook is wired in `/usr/lib/systemd/system/kodi-autostart.service`,
which sources that file via a `sh -c` wrapper). When boot-to-RetroArch is
enabled we append a line that invokes the addon's `ra_autostart.sh` shim,
and when it is disabled we remove that line. Toggling also flips the
`ra_boot_toggle` setting in `settings.xml` and unmasks Kodi if it was
masked by a previous RA-on-boot run that crashed.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from . import paths
from .settings import BOOT_TO_KODI, BOOT_TO_RA
from .system import is_masked, systemctl

log = logging.getLogger(__name__)

# Invariant token used to find our line in autostart.sh on disable. Matching
# the full command would miss the line if the addon dir changed between
# enable and disable (e.g. after a reinstall under a slightly different id).
_BOOT_MARKER = "ra_autostart.sh"


def boot_toggle(target: Optional[str] = None) -> int:
    """Toggle / set boot-to-RetroArch.

    `target`:
        None       -> flip the current state
        'on'       -> ensure RA-on-boot is enabled
        'off'      -> ensure it is disabled
        'check'    -> reconcile filesystem state with `ra_boot_toggle` setting

    Returns 0 on success, 1 when the reconciled state ended up as
    BOOT_TO_KODI (only meaningful when target == 'check' — `ra_autostart.sh`
    treats this as "settings were reset externally, do not launch RA"),
    or 2 on parameter error.
    """
    autostart_sh = paths.KODI_AUTOSTART_SH
    autostart_sh.parent.mkdir(parents=True, exist_ok=True)

    # Absolute path. `$ADDON_DIR` is NOT exported when CoreELEC's
    # kodi-autostart.service runs this file — `oe_setup_addon` is called
    # *inside* ra_autostart.sh, not before it. boot_toggle runs from the
    # addon UI, so paths.ADDON_DIR is correctly resolved here.
    boot_cmd = f'{paths.BIN_DIR / "ra_autostart.sh"} 2>/dev/null'

    is_check = target == "check"

    if is_check:
        # Force a re-apply of whichever side is currently selected.
        current = _read_setting()
        target = "on" if current == BOOT_TO_RA else "off"
    elif target is None:
        current = _read_setting()
        target = "off" if current == BOOT_TO_RA else "on"

    if target == "on":
        _enable(autostart_sh, boot_cmd)
        _write_setting(BOOT_TO_RA)
        return 0
    if target == "off":
        _disable(autostart_sh)
        if _kodi_is_masked():
            systemctl("unmask", "kodi")
        _write_setting(BOOT_TO_KODI)
        # `check` callers (the autostart shim) need to distinguish "RA is
        # still the desired boot target" from "settings were reset and we
        # just disabled the boot line" — so they can fall back to a plain
        # Kodi boot instead of launching RA.
        return 1 if is_check else 0

    log.error("boot: unknown target %r", target)
    return 2


# --------------------------------------------------------------- internals


def _enable(autostart_sh: Path, boot_cmd: str) -> None:
    """Ensure our boot line is present in `autostart_sh`; create file if needed.

    If a line containing the marker already exists, replace it — the addon
    path may have changed since the previous enable, and a stale absolute
    path would silently fail at boot.
    """
    lines = _read_lines(autostart_sh)
    has_marker = any(_BOOT_MARKER in line for line in lines)

    if has_marker:
        lines = [boot_cmd if _BOOT_MARKER in line else line for line in lines]
        _write_lines(autostart_sh, lines)
        return

    if not lines:
        # Fresh file: needs a shebang plus the command, plus the +x bit.
        lines = ["#!/bin/sh", boot_cmd]
        _write_lines(autostart_sh, lines)
        autostart_sh.chmod(0o755)
        return

    lines.append(boot_cmd)
    _write_lines(autostart_sh, lines)


def _disable(autostart_sh: Path) -> None:
    """Remove our boot line from `autostart_sh`; delete file if empty of content."""
    if not autostart_sh.exists():
        return
    lines = _read_lines(autostart_sh)
    filtered = [line for line in lines if _BOOT_MARKER not in line]
    if filtered == lines:
        return  # nothing to do

    # Drop blank lines and the lone shebang — those alone are not content.
    meaningful = [line for line in filtered if line.strip() and not line.startswith("#!")]
    if not meaningful:
        autostart_sh.unlink(missing_ok=True)
        return

    _write_lines(autostart_sh, filtered)


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _kodi_is_masked() -> bool:
    return is_masked("kodi")


# ----------------------------------------------------- settings.xml r/w --


def _read_setting() -> str:
    """Read `ra_boot_toggle` directly from settings.xml without xbmcaddon.

    This is invoked from `ra_autostart.sh` which runs outside Kodi.
    """
    path = paths.SETTINGS_FILE
    if not path.is_file():
        return BOOT_TO_KODI
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return BOOT_TO_KODI
    for setting in root.iter("setting"):
        if setting.attrib.get("id") != "ra_boot_toggle":
            continue
        return (setting.attrib.get("value") or (setting.text or "").strip() or BOOT_TO_KODI)
    return BOOT_TO_KODI


def _write_setting(value: str) -> None:
    """Update `ra_boot_toggle` in settings.xml in place.

    We rewrite via ET so the result is well-formed even if the file used
    inconsistent quoting. If Kodi is running it won't see the change until
    it reloads, but `boot_toggle` is invoked from the addon UI which then
    calls `addon.setSetting()` itself — this is a fallback for the case
    where the toggle is invoked from outside Kodi.
    """
    path = paths.SETTINGS_FILE
    if not path.is_file():
        return
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        log.warning("boot: cannot parse %s: %s", path, exc)
        return
    root = tree.getroot()
    found = False
    version = root.attrib.get("version", "1")
    for setting in root.iter("setting"):
        if setting.attrib.get("id") != "ra_boot_toggle":
            continue
        found = True
        if version == "2":
            setting.text = value
        else:
            setting.set("value", value)
        break
    if not found:
        elem = ET.SubElement(root, "setting", {"id": "ra_boot_toggle"})
        if version == "2":
            elem.text = value
        else:
            elem.set("value", value)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)
