"""Kodi entry point.

Kodi requires `default.py` at the addon root. We keep it minimal: extend
`sys.path` so the bundled `lib/` is importable, then dispatch to the real
implementation in `ra.kodi_entry`.

Kodi invokes us in two distinct modes (addon.xml declares
`xbmc.python.pluginsource` with `provides="executable game"`):

  Script mode (RunScript):
      sys.argv = ["<addon_path>/default.py", *args]
      args = () | ("check_updates",) | ("reset",) | ("boot_toggle",)

  Plugin mode (Kodi opening the Games/Programs window):
      sys.argv = ["plugin://<addon_id>/<path>", "<handle>", "<query>"]
      Kodi expects xbmcplugin.endOfDirectory(handle) before timing out.
"""

from __future__ import annotations

import os
import sys

_ADDON_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ADDON_ROOT, "lib"))

if __name__ == "__main__":
    if sys.argv and sys.argv[0].startswith("plugin://"):
        from ra.kodi_entry import plugin_main  # noqa: E402
        plugin_main(sys.argv)
    else:
        from ra.kodi_entry import main  # noqa: E402
        main(sys.argv[1:])
