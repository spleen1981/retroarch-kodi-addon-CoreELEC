"""Central path resolution for the RetroArch Kodi add-on.

Two execution contexts must be supported:

1. Inside Kodi (default.py invoked by the Kodi UI) — xbmcaddon is available
   and exposes the addon installation path via Addon.getAddonInfo('path').

2. Outside Kodi (systemd-run units, boot-time autostart) — xbmcaddon is not
   importable. Paths must be derived from $ADDON_DIR / $ADDON_HOME exported by
   the autostart shim, or from well-known CoreELEC locations as a last resort.

Resolution order, per path:
    1. explicit environment variable (set by shim or systemd)
    2. xbmcaddon lookup (only when Kodi context is available)
    3. derived from $HOME and the compile-time ADDON_NAME

ADDON_NAME is templated by the build script at packaging time. From v2.0.0 the
addon is platform-independent, so the placeholder script.retroarch.launcher is replaced by a
single static id (script.retroarch.launcher) with no device/arch suffix. The
platform is instead detected at runtime (see PLATFORM) and only ever appears in
the name of the per-platform RetroArch AppImage, which lives in userdata so it
survives an addon self-update.
"""

from __future__ import annotations

import os
from pathlib import Path

ADDON_NAME: str = "script.retroarch.launcher"


def _from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _from_kodi_addon() -> Path | None:
    try:
        import xbmcaddon  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return Path(xbmcaddon.Addon(id=ADDON_NAME).getAddonInfo("path"))
    except Exception:
        return None


def _home() -> Path:
    return Path(os.environ.get("HOME", "/storage"))


def _resolve_addon_dir() -> Path:
    return (
        _from_env("ADDON_DIR")
        or _from_kodi_addon()
        or _home() / ".kodi" / "addons" / ADDON_NAME
    )


def _resolve_addon_home() -> Path:
    return (
        _from_env("ADDON_HOME")
        or _home() / ".kodi" / "userdata" / "addon_data" / ADDON_NAME
    )


ADDON_DIR: Path = _resolve_addon_dir()
ADDON_HOME: Path = _resolve_addon_home()

# ----------------------------------------------------------- platform token

def _read_os_release() -> dict[str, str]:
    """Parse /etc/os-release into a dict. Empty on any error."""
    out: dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return out


def platform_token() -> str | None:
    """Return the CoreELEC/LibreELEC platform token (e.g. 'Amlogic-ng.arm').

    Read from /etc/os-release COREELEC_ARCH, falling back to LIBREELEC_ARCH.
    An RA_PLATFORM env override is honored first (desktop test rig / shim).

    Deliberately does NOT use `uname -m`: on Amlogic-ng the kernel is 64-bit
    (aarch64) while the userland is 32-bit (arm), so uname reports the wrong
    architecture. COREELEC_ARCH is the authoritative source.
    """
    override = os.environ.get("RA_PLATFORM")
    if override:
        return override
    osr = _read_os_release()
    return osr.get("COREELEC_ARCH") or osr.get("LIBREELEC_ARCH") or None


PLATFORM: str | None = platform_token()


def arch_token() -> str | None:
    """Architecture part of the platform token (e.g. 'arm', 'aarch64').

    COREELEC_ARCH is '<device>.<arch>' (e.g. 'Amlogic-ng.arm'); the arch is the
    segment after the last dot.
    """
    if PLATFORM is None:
        return None
    return PLATFORM.rsplit(".", 1)[-1]


ARCH: str | None = arch_token()


def generic_target() -> str | None:
    """The family-wide fallback target for this host: '<family>-any.<arch>'.

    Derived from COREELEC_ARCH by replacing the device variant with 'any':
    'Amlogic-ng.arm' / 'Amlogic-ne.arm' -> 'Amlogic-any.arm'. This is the token
    the default (generic) build is published under — scoped to the SoC family
    so it never over-matches a different SoC the way a bare '<arch>' would.
    """
    if PLATFORM is None or ARCH is None:
        return None
    device = PLATFORM.rsplit(".", 1)[0]                       # 'Amlogic-ng'
    family = device.rsplit("-", 1)[0] if "-" in device else device  # 'Amlogic'
    return f"{family}-any.{ARCH}"                             # 'Amlogic-any.arm'


def platform_candidates() -> list[str]:
    """Acceptable AppImage target tokens for this host, most specific first.

    The device is OPPORTUNISTIC: a build tagged with the exact '<device>.<arch>'
    (== COREELEC_ARCH) is preferred, but the family-wide '<family>-any.<arch>'
    build is accepted as a fallback. So an Amlogic-ne box (CE20+) runs the
    'Amlogic-any.arm' build when no 'Amlogic-ne.arm'-specific build exists.

    Future: a board-specific token can be prepended here (e.g.
    '<board>.<device>.<arch>') for finer matching — this list is the single
    extension point; nothing else in the resolution logic needs to change.
    """
    if PLATFORM is None:
        return []
    cands = [PLATFORM]
    gen = generic_target()
    if gen and gen != PLATFORM:
        cands.append(gen)
    return cands


# BIN_DIR and LIB_DIR are kept for compatibility but no longer exist in the
# thin addon — all compiled binaries and shared libs live inside the AppImage.
# Use APPIMAGE with --run <binary> to invoke bundled tools at runtime.
BIN_DIR: Path = ADDON_DIR / "bin"
LIB_DIR: Path = ADDON_DIR / "lib"
CONFIG_DIR: Path = ADDON_DIR / "config"
RESOURCES_DIR: Path = ADDON_DIR / "resources"

ICON: Path = RESOURCES_DIR / "icon.png"
FANART: Path = RESOURCES_DIR / "fanart.jpg"

SETTINGS_FILE: Path = ADDON_HOME / "settings.xml"
SETTINGS_DEFAULTS_FILE: Path = ADDON_DIR / "settings-default.xml"

# ------------------------------------------------------------- AppImage path
#
# The per-platform RetroArch AppImage is no longer bundled in the addon ZIP.
# It lives in userdata (ADDON_HOME/appimage/) so it survives an addon
# self-update (which wipes ADDON_DIR), and the user can drop it there manually.
# Its filename carries a TARGET token and the version:
#     retroarch-<target>-<version>.AppImage
# where <target> is one of this host's platform_candidates() — either the exact
# '<device>.<arch>' (device-specific build) or the family-wide '<family>-any.<arch>'
# (generic build). The active AppImage depends on filesystem state; resolve it
# via installed_appimage().
APPIMAGE_DIR: Path = ADDON_HOME / "appimage"
_APPIMAGE_PREFIX: str = "retroarch-"
_APPIMAGE_SUFFIX: str = ".AppImage"

# Well-known, user-reachable folders (exposed over Samba on CoreELEC) where a
# user can drop a downloaded AppImage instead of digging into the deep userdata
# path. The add-on imports any host-matching AppImage from here at launch.
APPIMAGE_IMPORT_DIRS: tuple[Path, ...] = (
    _home() / ".update",
    _home() / "downloads",
)


def appimage_filename(version: str, target: str) -> str:
    """Filename for the AppImage of `version` built for `target`.

    `target` is the token the matching manifest entry used (a device-specific
    '<device>.<arch>' or the family-wide '<family>-any.<arch>'), so a downloaded
    file keeps the specificity it was published with.
    """
    ver = version.lstrip("vV")
    return f"{_APPIMAGE_PREFIX}{target}-{ver}{_APPIMAGE_SUFFIX}"


def _target_and_version(name: str) -> tuple[str, str] | None:
    """If `name` is an AppImage for one of this host's candidate targets,
    return (target, version); else None.

    The target itself contains '-' and '.', so we parse relative to the known
    candidate set (most specific first) rather than naively splitting. Trying
    '<device>.<arch>' before '<family>-any.<arch>' means a device-specific name
    is never mis-read as the family-wide target.
    """
    if not name.startswith(_APPIMAGE_PREFIX) or not name.endswith(_APPIMAGE_SUFFIX):
        return None
    for target in platform_candidates():
        prefix = f"{_APPIMAGE_PREFIX}{target}-"
        if name.startswith(prefix):
            version = name[len(prefix):-len(_APPIMAGE_SUFFIX)]
            if version:
                return target, version
    return None


def is_host_appimage(name: str) -> bool:
    """True if `name` is a RetroArch AppImage built for one of this host's
    candidate targets (correct family/arch)."""
    return _target_and_version(name) is not None


def appimage_meta(name: str) -> tuple[str, str] | None:
    """(target, version) parsed from a host AppImage filename, or None."""
    return _target_and_version(name)


def _version_key(version: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' / '1.2.3' into a comparable tuple of ints."""
    parts: list[int] = []
    for chunk in version.lstrip("vV").replace("-", ".").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def installed_appimages() -> list[Path]:
    """Every installed AppImage usable on this host (any candidate target)."""
    if not platform_candidates() or not APPIMAGE_DIR.is_dir():
        return []
    out: list[Path] = []
    for entry in APPIMAGE_DIR.glob(f"{_APPIMAGE_PREFIX}*{_APPIMAGE_SUFFIX}"):
        if entry.is_file() and _target_and_version(entry.name) is not None:
            out.append(entry)
    return out


def installed_appimage() -> Path | None:
    """Return the best installed AppImage for this host, or None.

    Selection: device-specific beats family-wide (target specificity is the
    primary key), then highest version within the same specificity. Returns
    None when the platform/arch is unknown, the dir is absent, or nothing
    matches a candidate target.
    """
    cands = platform_candidates()
    if not cands or not APPIMAGE_DIR.is_dir():
        return None
    best: tuple[tuple[int, tuple[int, ...]], Path] | None = None
    for entry in installed_appimages():
        target, version = _target_and_version(entry.name)  # type: ignore[misc]
        # More specific target == lower index == higher priority. Negate so
        # max() prefers it; version is the tiebreaker within the same target.
        key = (-cands.index(target), _version_key(version))
        if best is None or key > best[0]:
            best = (key, entry)
    return best[1] if best else None


def installed_appimage_version() -> str | None:
    """Version string of the active installed AppImage, or None."""
    current = installed_appimage()
    if current is None:
        return None
    tv = _target_and_version(current.name)
    return tv[1] if tv else None


# RA_DEFAULT_CFG is the seed retroarch.cfg shipped in the (platform-independent)
# addon resources/config dir.
RA_DEFAULT_CFG: Path = CONFIG_DIR / "retroarch.cfg"

# Shell script installed in the addon root; written to ~/.config/autostart.sh
# by boot.py when the boot-to-RA toggle is enabled.
RA_AUTOSTART_SH: Path = ADDON_DIR / "ra_autostart.sh"

# First-run flag lives in ADDON_HOME (userdata) so it survives a self-update,
# which wipes ADDON_DIR. The legacy location is migrated by `firstrun`.
FIRST_RUN_FLAG: Path = ADDON_HOME / "first_run_done"
FIRST_RUN_FLAG_LEGACY: Path = CONFIG_DIR / "first_run_done"

# Marker dropped by the installer right before it asks systemd to restart
# Kodi. The next successful start of the addon clears it (and removes the
# `<addon>.old` backup directory). Missing marker after a restart = the
# update failed and the backup should be left in place for manual rollback.
UPDATE_PENDING_FLAG: Path = ADDON_HOME / "update_pending"

RA_CONFIG_DIR: Path = _home() / ".config" / "retroarch"
RA_CONFIG_FILE: Path = RA_CONFIG_DIR / "retroarch.cfg"
RA_CONFIG_SUBDIRS: tuple[str, ...] = (
    "savestates", "savefiles", "remappings", "playlists", "thumbnails",
    "system", "assets", "joypads", "shaders", "database", "overlays",
)

ROMS_FOLDER: Path = _home() / "roms"
ROMS_DOWNLOADS: Path = ROMS_FOLDER / "downloads"

KODI_GUI_SETTINGS: Path = _home() / ".kodi" / "userdata" / "guisettings.xml"

# CoreELEC's user-level autostart hook. The system unit
# `/usr/lib/systemd/system/kodi-autostart.service` invokes this file via a
# `sh -c` wrapper at boot if it exists and is executable.
KODI_AUTOSTART_SH: Path = _home() / ".config" / "autostart.sh"

DISPLAY_MODE: Path = Path("/sys/class/display/mode")

LOG_DIR: Path = ADDON_HOME / "logs"
LOG_FILE: Path = LOG_DIR / "retroarch.log"
LOG_FILE_OLD: Path = LOG_DIR / "retroarch.log.old"

# Derived, regenerable data (e.g. the `retroarch --features` driver cache).
# Safe to delete: it is rebuilt on demand. Kept separate from settings/logs.
CACHE_DIR: Path = ADDON_HOME / "cache"
AUDIO_FEATURES_CACHE: Path = CACHE_DIR / "audio_features.json"
SHUTDOWN_FLAG: Path = Path("/tmp/ra_exit_shutdown")
REBOOT_FLAG: Path = Path("/tmp/ra_exit_reboot")
UPDATER_TMP: Path = Path("/tmp/ra_updater.start")
UPDATE_DOWNLOAD_DIR: Path = Path("/tmp")


def ensure_runtime_dirs() -> None:
    """Create the runtime directories owned by the user. Idempotent."""
    ADDON_HOME.mkdir(parents=True, exist_ok=True)
    APPIMAGE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ROMS_FOLDER.mkdir(parents=True, exist_ok=True)
    ROMS_DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for sub in RA_CONFIG_SUBDIRS:
        (RA_CONFIG_DIR / sub).mkdir(parents=True, exist_ok=True)
