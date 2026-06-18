"""Map Kodi locale codes to libretro `user_language` enum values."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

from . import paths

log = logging.getLogger(__name__)

# Libretro enum (subset that matches Kodi resource.language.* codes we ship).
RETRO_LANGUAGE_ENGLISH = 0

# Longest matching prefix wins. `pt_br` must precede `pt`, `zh_tw` before `zh`.
_LANGUAGE_MAP: tuple[tuple[str, int], ...] = (
    ("ja", 1),
    ("fr", 2),
    ("es", 3),
    ("de", 4),
    ("it", 5),
    ("pt_br", 7),
    ("pt", 8),
    ("ru", 9),
    ("ko", 10),
    ("zh_tw", 11),
    ("zh", 12),
    ("eo", 13),
    ("pl", 14),
    ("vi", 15),
    ("ar", 16),
    ("el", 17),
    ("tr", 18),
    ("sk", 19),
    ("fa", 20),
    ("he", 21),
    ("ast", 22),
    ("fi", 23),
    ("id", 24),
    ("sv", 25),
    ("uk", 26),
    ("cs", 27),
    ("ca", 28),
)


def retro_language_for(locale: str) -> int:
    """Map a Kodi locale like 'it_it' to a RETRO_LANGUAGE_* value.

    Falls back to ENGLISH for any code we don't know.
    """
    if not locale:
        return RETRO_LANGUAGE_ENGLISH
    needle = locale.lower()
    # Longest-prefix match: try the entries ordered specific→general.
    for prefix, value in sorted(_LANGUAGE_MAP, key=lambda p: -len(p[0])):
        if needle.startswith(prefix):
            return value
    return RETRO_LANGUAGE_ENGLISH


def kodi_current_locale() -> Optional[str]:
    """Extract `locale.language` from Kodi's `guisettings.xml`.

    Returns a value like `it_it`, or None if the file isn't readable.
    """
    path = paths.KODI_GUI_SETTINGS
    if not path.is_file():
        return None
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        log.warning("i18n: cannot parse %s: %s", path, exc)
        return None
    for setting in tree.iter("setting"):
        if setting.attrib.get("id") != "locale.language":
            continue
        raw = (setting.text or "").strip()
        # Format is `resource.language.<code>` (e.g. resource.language.it_it).
        prefix = "resource.language."
        if raw.startswith(prefix):
            return raw[len(prefix):]
        return raw or None
    return None
