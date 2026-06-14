"""Typed access to the addon's user settings.

Settings live in `addon_data/<addon>/settings.xml` and are edited through
Kodi's UI (see `resources/settings.xml` for the schema). Two access paths
must be supported:

1. From Kodi (default.py / kodi_entry.py): xbmcaddon.Addon().getSetting().
2. From systemd context (autostart): xbmcaddon isn't importable. Parse the
   XML directly with stdlib xml.etree.

Both paths return values typed by the dataclass fields. Unknown / missing
settings fall back to the defaults declared in `settings-default.xml`
(replicated here so a brand-new install works even before Kodi seeds the
user copy).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, fields
from typing import Any

from . import paths

log = logging.getLogger(__name__)

BOOT_TO_RA = "RETROARCH"
BOOT_TO_KODI = "KODI"


@dataclass
class AddonSettings:
    """User settings as a typed bag. Mirrors `resources/settings.xml` ids."""

    boot_toggle: str = BOOT_TO_KODI
    hints: bool = True
    sigkill_kodi: bool = False
    autoupdate: bool = True
    xbox360_shutdown: bool = True
    bt_shutdown: bool = False
    cec_remote: bool = True
    cec_poweroff: int = 0
    force_refresh_rate: bool = True
    forced_refresh_rate: int = 1  # 0 = 50Hz, 1 = 60Hz
    sync_audio_settings: bool = True
    roms_remote: bool = False
    roms_remote_path: str = ""
    roms_remote_user: str = ""
    roms_remote_password: str = ""
    roms_remote_vers: str = "Default"
    log_to_file: bool = False

    # Mapping: dataclass field name -> settings.xml id.
    _XML_IDS = {
        "boot_toggle": "ra_boot_toggle",
        "hints": "ra_hints",
        "sigkill_kodi": "ra_sigkill_kodi",
        "autoupdate": "ra_autoupdate",
        "xbox360_shutdown": "ra_xbox360_shutdown",
        "bt_shutdown": "ra_bt_shutdown",
        "cec_remote": "ra_cec_remote",
        "cec_poweroff": "ra_cec_poweroff",
        "force_refresh_rate": "ra_force_refresh_rate",
        "forced_refresh_rate": "ra_forced_refresh_rate",
        "sync_audio_settings": "ra_sync_audio_settings",
        "roms_remote": "ra_roms_remote",
        "roms_remote_path": "ra_roms_remote_path",
        "roms_remote_user": "ra_roms_remote_user",
        "roms_remote_password": "ra_roms_remote_password",
        "roms_remote_vers": "ra_roms_remote_vers",
        "log_to_file": "ra_log",
    }

    # ----------------------------------------------------------- factories

    @classmethod
    def load(cls) -> "AddonSettings":
        """Read user settings. Try xbmcaddon first, fall back to XML parse."""
        values = cls._read_via_xbmc() or cls._read_via_xml() or {}
        return cls._from_raw(values)

    @classmethod
    def _read_via_xbmc(cls) -> dict[str, str] | None:
        try:
            import xbmcaddon  # type: ignore[import-not-found]
        except ImportError:
            return None
        try:
            addon = xbmcaddon.Addon(id=paths.ADDON_NAME)
        except Exception:  # noqa: BLE001
            return None
        return {
            field: addon.getSetting(xml_id)
            for field, xml_id in cls._XML_IDS.items()
        }

    @classmethod
    def _read_via_xml(cls) -> dict[str, str] | None:
        """Parse `addon_data/<addon>/settings.xml` directly.

        Supports both v1 (`<setting id="..." value="..."/>`) and v2
        (`<setting id="...">value</setting>`) formats that CoreELEC has
        shipped over time.
        """
        path = paths.SETTINGS_FILE
        if not path.exists():
            path = paths.SETTINGS_DEFAULTS_FILE
        if not path.exists():
            return None
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            log.warning("malformed settings.xml at %s: %s", path, exc)
            return None
        version = root.attrib.get("version", "1")
        out: dict[str, str] = {}
        for setting in root.iter("setting"):
            sid = setting.attrib.get("id")
            if sid is None:
                continue
            if version == "2":
                value = (setting.text or "").strip()
            else:
                value = setting.attrib.get("value", "")
            for field_name, xml_id in cls._XML_IDS.items():
                if xml_id == sid:
                    out[field_name] = value
                    break
        return out

    @classmethod
    def _from_raw(cls, raw: dict[str, Any]) -> "AddonSettings":
        kwargs: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in raw:
                continue
            value = raw[field.name]
            if field.type is bool or field.type == "bool":
                kwargs[field.name] = _coerce_bool(value)
            elif field.type is int or field.type == "int":
                kwargs[field.name] = _coerce_int(value, field.default)  # type: ignore[arg-type]
            else:
                kwargs[field.name] = "" if value is None else str(value)
        return cls(**kwargs)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
