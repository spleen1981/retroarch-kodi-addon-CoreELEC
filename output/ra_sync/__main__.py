"""Sync RetroArch resources from the AppImage to the user RA config dir.

Invoked by AppRun on each launch:
    python3 "$APPDIR/lib/ra_sync" <APPDIR> <APPIMAGE_VERSION>

Per-subdir policy (mirrors the legacy script behavior):
    system/   no-clobber merge   (preserves user BIOSes / savegames)
    others    overwrite          (shipped data refreshed with each AppImage)

Blacklist: files NEVER copied at any depth in any subdir.
    NAMES     exact basename     (e.g. "scummvm.ini")
    PATTERNS  fnmatch globs      (e.g. "*.cfg", "*.opt")

Marker file at <HOME>/.config/retroarch/.resources_from_appimage records
the last-synced AppImage version. Identical version -> short-circuit
(zero I/O). Mismatched/missing -> full sync, marker rewritten on success.

Logging policy mirrors `ra.runtime`: reads the `ra_log` setting from
addon_data/<addon>/settings.xml and writes to the unified
retroarch.log only when level is ERROR (1) or VERBOSE (2). Logging
failures are swallowed silently — diagnostics must never crash the sync.

Exit codes:
    0  success or short-circuit
    1  recoverable failure (AppRun continues to launch retroarch)
    2  argv error
"""

from __future__ import annotations

import datetime
import fnmatch
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Hard-coded; must match ra.paths.ADDON_NAME (different package, can't import).
_ADDON_NAME = "script.retroarch.launcher"

# Hard-coded; must match ra.settings.LOG_OFF / LOG_ERROR / LOG_VERBOSE.
_LOG_OFF = 0
_LOG_ERROR = 1
_LOG_VERBOSE = 2

_NO_CLOBBER_SUBDIRS = ("system",)
_OVERWRITE_SUBDIRS = (
    "audio_filters", "video_filters", "joypads",
    "shaders", "database", "overlays", "assets",
)

# Files cores write at runtime — never overlay shipped content on top.
_BLACKLIST_NAMES = frozenset({"scummvm.ini"})

# fnmatch globs against basename at any depth.
_BLACKLIST_PATTERNS = ("*.cfg", "*.opt")

_MARKER_NAME = ".resources_from_appimage"

# Atomic single-line state file read by the Kodi pre-sync hook
# (kodi_entry._maybe_presync_resources). Tmpfs on CoreELEC.
_PROGRESS_FILE = Path("/tmp/ra_sync_progress")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python3 $APPDIR/lib/ra_sync <APPDIR> <APPIMAGE_VERSION>",
            file=sys.stderr,
        )
        return 2

    appdir = Path(argv[0])
    version = argv[1].strip()
    home = Path(os.environ.get("HOME", "/storage"))

    log_level = _read_log_level(home)
    logger = _Logger(home, log_level)

    if not version:
        logger.error("appimage_version not provided (build placeholder leak?)")
        return 1

    if not appdir.is_dir():
        logger.error(f"appdir {appdir} is not a directory")
        return 1

    ra_cfg = home / ".config" / "retroarch"
    marker = ra_cfg / _MARKER_NAME
    if _marker_matches(marker, version):
        return 0  # short-circuit, zero I/O

    src_root = appdir / "resources"
    if not src_root.is_dir():
        logger.info("no resources/ in AppImage, nothing to sync")
        return 0

    progress = _Progress()
    try:
        all_subs = _NO_CLOBBER_SUBDIRS + _OVERWRITE_SUBDIRS
        progress.set_total(_count_files(src_root, all_subs))
        ra_cfg.mkdir(parents=True, exist_ok=True)
        for sub in _NO_CLOBBER_SUBDIRS:
            _merge(src_root / sub, ra_cfg / sub, overwrite=False,
                   progress=progress)
        for sub in _OVERWRITE_SUBDIRS:
            _merge(src_root / sub, ra_cfg / sub, overwrite=True,
                   progress=progress)
        marker.write_text(version, encoding="utf-8")
        progress.done()
        logger.info(f"synced resources from AppImage v{version}")
    except OSError as exc:
        progress.error(str(exc))
        logger.error(f"sync failed: {exc}")
        return 1
    return 0


# ----------------------------------------------------- logging policy


class _Logger:
    """Append to the unified retroarch.log respecting ra_log level.

    OFF     -> no writes (true off).
    ERROR   -> error() only.
    VERBOSE -> error() + info().
    """
    def __init__(self, home: Path, log_level: int) -> None:
        self._level = log_level
        self._path = (
            home / ".kodi" / "userdata" / "addon_data" / _ADDON_NAME
            / "logs" / "retroarch.log"
        )

    def info(self, msg: str) -> None:
        if self._level >= _LOG_VERBOSE:
            self._write("INFO", msg)

    def error(self, msg: str) -> None:
        if self._level >= _LOG_ERROR:
            self._write("ERROR", msg)

    def _write(self, level: str, msg: str) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(f"{ts} ra_sync {level} {msg}\n")
        except OSError:
            pass  # logging must never crash the sync


def _read_log_level(home: Path) -> int:
    """Read ra_log from addon_data settings.xml; default OFF on any error."""
    settings = (
        home / ".kodi" / "userdata" / "addon_data" / _ADDON_NAME / "settings.xml"
    )
    if not settings.is_file():
        return _LOG_OFF
    try:
        root = ET.parse(settings).getroot()
    except ET.ParseError:
        return _LOG_OFF
    version = root.attrib.get("version", "1")
    for setting in root.iter("setting"):
        if setting.attrib.get("id") != "ra_log":
            continue
        if version == "2":
            raw = (setting.text or "").strip()
        else:
            raw = setting.attrib.get("value", "")
        try:
            return int(raw)
        except ValueError:
            return _LOG_OFF
    return _LOG_OFF


# --------------------------------------------------------- sync core


def _merge(src: Path, dst: Path, *, overwrite: bool,
           progress: "_Progress", rel_prefix: str = "") -> None:
    """Recursive merge with blacklist filtering.

    overwrite=True   shipped wins on existing files.
    overwrite=False  user wins on existing files (no-clobber).
    Blacklisted files are skipped in BOTH modes — never created, never replaced.
    `progress.tick()` is called for every iterated file (copied OR skipped) so
    the counter advances linearly to 100% regardless of overwrite policy.
    """
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if _blacklisted(entry.name):
            continue
        target = dst / entry.name
        rel = f"{rel_prefix}{entry.name}"
        if entry.is_dir():
            _merge(entry, target, overwrite=overwrite, progress=progress,
                   rel_prefix=f"{rel}/")
            continue
        if overwrite or not target.exists():
            shutil.copy2(entry, target)
        progress.tick(rel)


def _blacklisted(name: str) -> bool:
    if name in _BLACKLIST_NAMES:
        return True
    return any(fnmatch.fnmatchcase(name, pat) for pat in _BLACKLIST_PATTERNS)


def _count_files(src_root: Path, subdirs: tuple) -> int:
    """Walk all sync sources counting non-blacklisted files for progress total."""
    n = 0
    for sub in subdirs:
        d = src_root / sub
        if not d.is_dir():
            continue
        for entry in d.rglob("*"):
            if entry.is_file() and not _blacklisted(entry.name):
                n += 1
    return n


class _Progress:
    """Atomic single-line state file consumed by the Kodi pre-sync hook.

    Protocol (one line, rewritten atomically via rename):
        "<pct> <relpath>"   progress 0-99 with current file
        "100 done"          successful completion
        "error <message>"   fatal failure (Kodi logs and closes the toast)

    Writes are best-effort: any OSError is swallowed so progress reporting
    never breaks the sync itself. Residue from a previous run is removed
    on construction.
    """
    def __init__(self) -> None:
        self._total = 0
        self._done = 0
        _PROGRESS_FILE.unlink(missing_ok=True)

    def set_total(self, n: int) -> None:
        self._total = n

    def tick(self, relpath: str) -> None:
        self._done += 1
        pct = int(self._done * 100 / self._total) if self._total else 0
        # Cap at 99 during progress; 100 reserved for done().
        if pct >= 100:
            pct = 99
        self._write(f"{pct} {relpath}")

    def done(self) -> None:
        self._write("100 done")

    def error(self, message: str) -> None:
        self._write(f"error {message}")

    def _write(self, line: str) -> None:
        try:
            tmp = _PROGRESS_FILE.with_suffix(".tmp")
            tmp.write_text(line, encoding="utf-8")
            tmp.replace(_PROGRESS_FILE)
        except OSError:
            pass


def _marker_matches(marker: Path, expected: str) -> bool:
    try:
        return marker.read_text(encoding="utf-8").strip() == expected
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
