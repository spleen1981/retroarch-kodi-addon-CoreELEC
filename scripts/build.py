"""Top-level orchestrator

Flow:
    1. parse CLI args / config
    2. derive per-device variables (PROJECT, DEVICE_LAKKA, ARCH, ADDON_NAME, ...)
    3. resolve the package list (LIBRETRO_CORES with add/remove modifiers)
    4. drive Lakka: checkout pinned commit, apply patches, build packages
    5. assemble the add-on directory: copy built packages, our committed source,
       generated manifests, customized retroarch.cfg
    6. zip the result

Each phase delegates to a helper module:
    `lakka.py`     -- patch apply/revert, package build, file copy from build_pkg
    `package.py`   -- assemble addon dir, substitute placeholders, customize cfg
    `langdata.py`  -- i18n source-of-truth (used by package.po_emit / addon_xml)
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import lakka, package

# Make the addon's Python package importable from the build scripts.
# package.py imports ra.ra_config at runtime (lazy import inside
# customize_retroarch_cfg); that import needs output/modules/ on sys.path.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "output" / "lib"))

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

# v2.0.0: the addon is platform-independent. A single ZIP carries this id; the
# per-platform RetroArch AppImage is a separate release asset (named
# retroarch-<platform>-<version>.AppImage) downloaded at runtime into userdata.
ADDON_ID = "script.retroarch.launcher"

# Pinned Lakka commit. Bumped intentionally — keep in sync with the README.
DEFAULT_LAKKA_VERSION = "c4d3f32b0e3d76889353ea0f6c81f947d6c6f103"

# Package families the build pulls from Lakka, keyed by their subdir under
# `packages/`. The names match the legacy `PKG_SUBDIR_*` variables.
PKG_SUBDIRS: dict[str, str] = {
    "LIBRETRO_CORES":  "lakka/libretro_cores",
    "LIBRETRO_BASE":   "lakka/retroarch_base",
    "LAKKA_TOOLS":     "lakka/lakka_tools",
}

# Static, per-family package lists (excluding LIBRETRO_CORES which is dynamic).
# Library-only packages (flac, curl, ffmpeg, SDL2, zstd, libzip, …) are
# intentionally omitted: Lakka builds them automatically as PKG_DEPENDS_TARGET
# of retroarch or the tool packages, so they appear in install_pkg/ and are
# picked up by collect_deps / collect_pkg_deps without explicit listing here.
STATIC_PACKAGES: dict[str, tuple[str, ...]] = {
    # LIBRETRO_BASE includes the RetroArch frontend, cores info, joypad
    # autoconfig, and the data packages (assets/overlays/shaders/database).
    # The latter were optional (--include-dlc) up to v2.0.0; they are now
    # always bundled so the AppImage is self-sufficient out of the box.
    "LIBRETRO_BASE":  ("retroarch", "core_info", "retroarch_joypad_autoconfig",
                       "retroarch_assets", "retroarch_overlays",
                       "libretro_database", "glsl_shaders"),
    "LAKKA_TOOLS":    ("joyutils", "sixpair", "empty",
                       "xbox360_controllers_shutdown", "cec-mini-kb"),
}

# Per-device customizations of the libretro core list. Cores listed in
# `fallback` are removed from the Lakka build and shipped as pre-compiled .so
# files instead (see `fallback-precompiled-cores/` in the repo root).
@dataclass(frozen=True)
class DeviceProfile:
    source_device: str
    project: str
    device_lakka: str
    arch: str
    cores_add: tuple[str, ...] = ()
    cores_remove: tuple[str, ...] = ()
    cores_fallback: tuple[str, ...] = ()
    fallback_subdir: str = ""
    # AppImage target token. Empty → the family-wide '<family>-any.<arch>'
    # (e.g. 'Amlogic-any.arm'), which any device of that family+arch matches
    # opportunistically at runtime. Set a '<device>.<arch>' value only when a
    # device genuinely needs its own build.
    appimage_target: str = ""


_DEVICES: dict[str, DeviceProfile] = {
    "Amlogic-any.arm": DeviceProfile(
        source_device="Amlogic-ng",
        project="Amlogic",
        device_lakka="AMLGX",
        arch="arm",
        cores_add=("puae2021", "mupen64plus", "same_cdi"),
        cores_remove=("mame", "puae", "mupen64plus_next", "kronos", "lr_moonlight"),
        cores_fallback=("flycast_xtreme",),
        fallback_subdir="arm7hf",
    ),
    "Amlogic-any.aarch64": DeviceProfile(
        source_device="Amlogic-no",
        project="Amlogic",
        device_lakka="AMLGX",
        arch="aarch64",
        cores_add=("puae2021",),
        cores_remove=("mame", "puae", "kronos", "lr_moonlight"),
        cores_fallback=(),
        fallback_subdir="aarch64",
    ),
}


@dataclass
class BuildConfig:
    device: str
    addon_version: str
    lakka_version: str = DEFAULT_LAKKA_VERSION
    lakka_dir: Path = field(default_factory=lambda: REPO_ROOT / "Lakka-LibreELEC")
    build_dir: Path = field(default_factory=lambda: REPO_ROOT / "build")
    work_dir: Path = field(default_factory=lambda: REPO_ROOT / "retroarch_work")
    # Parallel `make` job count for Lakka. None -> let Lakka pick its default.
    jobs: int | None = None
    # AppImage target override (CLI). Empty -> profile.appimage_target -> arch.
    @property
    def profile(self) -> DeviceProfile:
        return _DEVICES[self.device]

    @property
    def addon_name(self) -> str:
        # Platform-independent id (v2). Same for every device.
        return ADDON_ID

    @property
    def appimage_target(self) -> str:
        """Return the AppImage release/manifest target.

        In v2, BuildConfig.device is already the family-wide AppImage target:
            Amlogic-any.arm      -> Lakka Amlogic-ng / arm profile
            Amlogic-any.aarch64  -> Lakka Amlogic-no / aarch64 profile
        """
        return self.device

    @property
    def addon_dir(self) -> Path:
        # The single, universal addon dir assembled once (phase 2). Shared
        # across devices — only written during assembly, never in the
        # per-device AppImage phase (which uses staging_dir).
        return self.work_dir / ADDON_ID

    @property
    def staging_dir(self) -> Path:
        """Per-device scratch dir: Lakka artifacts are extracted here, then
        bin/lib are moved into the AppImage, leaving resources+config that
        feed the universal addon assembly."""
        return self.work_dir / f"staging-{self.device}"

    @property
    def archive_name(self) -> str:
        return f"{ADDON_ID}-{self.addon_version}.zip"

    @property
    def appimage_version(self) -> str:
        """Numeric version for the AppImage filename (no leading 'v'), so it
        matches paths.appimage_filename() used at download time."""
        return self.addon_version.lstrip("vV")

    @property
    def lakka_build_subdir(self) -> str:
        """Name of the per-device Lakka build directory."""
        return f"build.Lakka-{self.profile.device_lakka}.{self.profile.arch}"

    @property
    def lakka_build_dir(self) -> Path:
        """Absolute path to the Lakka per-device build root."""
        return self.lakka_dir / self.lakka_build_subdir

    @property
    def readelf(self) -> str:
        """Full path to the cross readelf from the Lakka toolchain.

        readelf only parses ELF file structure — it does not execute the
        binary — so the cross-readelf runs fine on an x86 host without
        emulation. Falls back to the system readelf when the cross binary
        is absent (e.g. ARM toolchain uses a different triplet name).
        """
        toolchain_bin = self.lakka_build_dir / "toolchain" / "bin"
        # Try the known triplet first; fall back to any *-readelf in the
        # toolchain bin, then to the system readelf (which reads ELF files
        # of any architecture — no emulation needed).
        known_triplet = (
            "aarch64-libreelec-linux-gnu"
            if self.profile.arch == "aarch64"
            else "arm-libreelec-linux-gnueabihf"
        )
        candidate = toolchain_bin / f"{known_triplet}-readelf"
        if candidate.exists():
            return str(candidate)
        # Auto-detect: pick the first *-readelf found in the toolchain.
        for found in sorted(toolchain_bin.glob("*-readelf")):
            return str(found)
        return "readelf"

    @property
    def appimage_staging_dir(self) -> Path:
        """Per-device staging directory for AppImage contents (retroarch + libs)."""
        return self.work_dir / f"appimage-staging-{self.device}"

    @property
    def appimage_name(self) -> str:
        return f"retroarch-{self.appimage_target}-{self.appimage_version}.AppImage"

    @property
    def appimage_out(self) -> Path:
        """Final AppImage path — a release asset, dropped in build/, NOT in the ZIP."""
        return self.build_dir / self.appimage_name

    @property
    def appimage_runtime(self) -> str:
        """AppImage runtime binary installed by the appimage-runtime host package."""
        runtime_arch = "aarch64" if self.profile.arch == "aarch64" else "armhf"
        return str(
            self.lakka_build_dir / "toolchain" / "share" / "appimage"
            / f"runtime-{runtime_arch}"
        )

    # AppImageKit release tag used for the fuse2 runtime. Pinned to a fixed
    # release (not "continuous") for reproducible builds. The type2-runtime
    # from AppImage/type2-runtime uses fuse3/fusermount3 which is absent on
    # CoreELEC; AppImageKit release 13 uses libfuse.so.2 via dlopen() and
    # calls fuse_mount/fuse_unmount in-process — no external fusermount binary
    # required, clean unmount when the AppImage process exits.
    _APPIMAGE_RUNTIME_RELEASE = "13"


# =============================================================== driver ===


@dataclass
class AppImageArtifact:
    """One built per-platform AppImage release asset."""
    platform: str
    version: str       # numeric (no leading 'v')
    path: Path
    sha256: str


def build_retroarch_seed_config(cfg: BuildConfig) -> None:
    """Build only the Lakka `retroarch` package and extract retroarch.cfg.

    This is the --addon-only development path: we need the default
    retroarch.cfg exactly as produced by the Lakka RetroArch package, but we
    do NOT need cores, tools, DLC packages or final AppImage creation.

    Result:
        cfg.staging_dir/config/retroarch.cfg

    Then assemble_addon(cfg) builds the universal thin addon ZIP from that
    staging config plus committed output/ sources.
    """
    log.info("=== addon-only: building retroarch seed cfg for %s ===", cfg.device)
    if not cfg.lakka_dir.is_dir():
        raise FileNotFoundError(f"Lakka source dir not found: {cfg.lakka_dir}")

    package_list = {"LIBRETRO_BASE": ("retroarch",)}

    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    with lakka.patched(cfg.lakka_dir, REPO_ROOT, cfg.profile.source_device, cfg.profile.project,
                       cfg.profile.arch, cfg.lakka_version):
        lakka.build_packages(cfg.lakka_dir, package_list,
                             distro="Lakka",
                             project=cfg.profile.project,
                             device_lakka=cfg.profile.device_lakka,
                             arch=cfg.profile.arch,
                             jobs=cfg.jobs)
        tmp_target = lakka.copy_built_packages(
            cfg.lakka_dir, package_list,
            distro="Lakka", project=cfg.profile.project,
            device_lakka=cfg.profile.device_lakka, arch=cfg.profile.arch,
            subdirs=PKG_SUBDIRS, work_dir=cfg.work_dir,
        )

    if cfg.staging_dir.exists():
        shutil.rmtree(cfg.staging_dir)
    dst_cfg = cfg.staging_dir / "config" / "retroarch.cfg"
    dst_cfg.parent.mkdir(parents=True, exist_ok=True)

    src_cfg = tmp_target / "etc" / "retroarch.cfg"
    if not src_cfg.is_file():
        raise FileNotFoundError(f"retroarch.cfg not found in built package: {src_cfg}")

    shutil.copy2(src_cfg, dst_cfg)
    log.info("addon-only: copied %s -> %s", src_cfg, dst_cfg)


def build_appimage(cfg: BuildConfig) -> AppImageArtifact:
    """Phase 1 (per device): build the per-platform RetroArch AppImage.

    Runs the Lakka build, extracts artifacts into the per-device staging dir,
    moves bin/lib into the AppImage, and writes the AppImage as a release asset
    in build/ (NOT inside the addon ZIP). Leaves cfg.staging_dir holding the
    device-independent resources+config that phase 2 (assemble_addon) uses to
    build the single universal addon ZIP.
    """
    log.info("=== building AppImage %s @ %s ===", cfg.appimage_target, cfg.addon_version)
    if not cfg.lakka_dir.is_dir():
        raise FileNotFoundError(f"Lakka source dir not found: {cfg.lakka_dir}")

    package_list = _resolve_package_list(cfg)

    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    with lakka.patched(cfg.lakka_dir, REPO_ROOT, cfg.profile.source_device, cfg.profile.project,
                       cfg.profile.arch, cfg.lakka_version):
        lakka.build_packages(cfg.lakka_dir, package_list,
                             distro="Lakka",
                             project=cfg.profile.project,
                             device_lakka=cfg.profile.device_lakka,
                             arch=cfg.profile.arch,
                             jobs=cfg.jobs)
        tmp_target = lakka.copy_built_packages(
            cfg.lakka_dir, package_list,
            distro="Lakka", project=cfg.profile.project,
            device_lakka=cfg.profile.device_lakka, arch=cfg.profile.arch,
            subdirs=PKG_SUBDIRS, work_dir=cfg.work_dir,
        )

        # Artifact extraction reads the Lakka source tree (package.mk files
        # created by patches) so it must run while patches are still applied.
        # Everything lands in the per-device STAGING dir, never the universal
        # addon dir.
        _setup_staging_dir(cfg)
        package.move_artifacts(tmp_target, cfg.staging_dir)
        package.clean_lib(cfg.staging_dir)
        package.collect_deps(
            cfg.staging_dir,
            lakka_build_dir=cfg.lakka_build_dir,
            readelf=cfg.readelf,
        )
        package.collect_pkg_deps(
            cfg.staging_dir,
            lakka_dir=cfg.lakka_dir,
            lakka_build_dir=cfg.lakka_build_dir,
            package_list=package_list,
            subdirs=PKG_SUBDIRS,
        )
        package.add_fallback_cores(REPO_ROOT, cfg.staging_dir, cfg.profile)
    # Ensure the AppImage runtime binary is available.
    _ensure_appimage_tools(cfg)

    # Move retroarch + libs out of staging into the AppImage and write it as a
    # standalone release asset in build/. staging_dir keeps resources+config.
    package.stage_appimage(cfg.staging_dir, cfg.appimage_staging_dir,
                           output_dir=OUTPUT_DIR,
                           lakka_build_dir=cfg.lakka_build_dir,
                           appimage_version=cfg.appimage_version)
    package.create_appimage(
        cfg.appimage_staging_dir,
        cfg.appimage_out,
        runtime=cfg.appimage_runtime,
    )
    sha = package.sha256_file(cfg.appimage_out)
    log.info("AppImage -> %s (sha256=%s)", cfg.appimage_out.name, sha)
    return AppImageArtifact(platform=cfg.appimage_target, version=cfg.appimage_version,
                            path=cfg.appimage_out, sha256=sha)


def assemble_addon(cfg: BuildConfig) -> tuple[Path, str]:
    """Phase 2 (once): assemble the single universal addon ZIP.

    `cfg` references a device whose staging_dir already holds the extracted
    resources+config (build_appimage(cfg) ran for it). Resources are
    device-independent, so we take them from this one reference build. The
    addon carries no platform suffix (passed "" to the metadata emitters) and
    no bundled AppImage. Returns (zip_path, sha256).
    """
    src = cfg.staging_dir
    if not src.is_dir():
        raise RuntimeError(f"reference staging dir missing: {src}")

    addon_dir = cfg.addon_dir
    if addon_dir.exists():
        shutil.rmtree(addon_dir)
    addon_dir.mkdir(parents=True, exist_ok=True)
    # Device-independent thin-addon content (resources + seed config).
    for sub in ("resources", "config"):
        s = src / sub
        if s.is_dir():
            shutil.copytree(s, addon_dir / sub, symlinks=True)

    package.install_committed_source(OUTPUT_DIR, addon_dir)
    package.emit_addon_xml(addon_dir, cfg.addon_version,
                           "",  # universal: no platform suffix
                           changelog=REPO_ROOT / "CHANGELOG.md")
    package.emit_language_files(addon_dir, cfg.addon_version, "")
    package.customize_retroarch_cfg(addon_dir)
    package.create_archive(addon_dir, cfg.build_dir, cfg.archive_name)

    zip_path = cfg.build_dir / ADDON_ID / cfg.archive_name
    sha = package.sha256_file(zip_path) if zip_path.is_file() else ""
    log.info("addon ZIP -> %s (sha256=%s)", zip_path.name, sha)
    return zip_path, sha




def _ensure_appimage_tools(cfg: BuildConfig) -> None:
    """Download the AppImage runtime binary if not already present.

    The runtime is a host-independent data file (not executed on the build
    host). appimagetool is no longer needed: create_appimage assembles the
    AppImage directly using the system mksquashfs + cat(runtime, squashfs).
    """
    _HTTP_TIMEOUT = 30.0

    tools = [
        (
            cfg.appimage_runtime,
            "https://github.com/AppImage/AppImageKit/releases/download/"
            f"{BuildConfig._APPIMAGE_RUNTIME_RELEASE}/"
            f"obsolete-runtime-{'aarch64' if cfg.profile.arch == 'aarch64' else 'armhf'}",
            False,
        ),
    ]

    for dst_str, url, executable in tools:
        dst = Path(dst_str)
        if dst.exists():
            log.info("appimage-tools: %s already present", dst.name)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        log.info("appimage-tools: downloading %s", dst.name)
        try:
            urllib.request.urlretrieve(url, dst)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot download {dst.name} from {url}: {exc}"
            ) from exc
        if executable:
            os.chmod(dst, 0o755)
        log.info("appimage-tools: saved %s", dst)


def _setup_staging_dir(cfg: BuildConfig) -> None:
    """Wipe and re-create the per-device staging directories.

    Staging holds the extracted Lakka artifacts. bin/lib are temporary
    (moved into the AppImage by stage_appimage); resources/config remain and
    feed the universal addon assembly.
    """
    for d in (cfg.staging_dir, cfg.appimage_staging_dir):
        if d.exists():
            shutil.rmtree(d)
    for sub in ("", "config", "resources", "bin", "lib"):
        (cfg.staging_dir / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------- libretro core list resolve


def _resolve_package_list(cfg: BuildConfig) -> dict[str, tuple[str, ...]]:
    """Build the {family: (pkg, ...)} dict that drives Lakka invocations."""
    cores = _resolve_libretro_cores(cfg)
    out: dict[str, tuple[str, ...]] = {"LIBRETRO_CORES": cores}
    out.update(STATIC_PACKAGES)
    return out


def _resolve_libretro_cores(cfg: BuildConfig) -> tuple[str, ...]:
    """Replicate the legacy add/remove logic against Lakka's default core list.

    The Lakka package file declares `LIBRETRO_CORES="a b c ..."` at the top.
    We parse it directly rather than sourcing the shell file.
    """
    pkg_mk = cfg.lakka_dir / "packages" / "lakka" / "libretro_cores" / "package.mk"
    base = _parse_make_var(pkg_mk, "LIBRETRO_CORES")
    profile = cfg.profile

    # Remove fallback cores AND the user-configured removals.
    remove = set(profile.cores_remove) | set(profile.cores_fallback)
    result: list[str] = [c for c in base if c not in remove]

    # Append additions (deduped, order preserved).
    for core in profile.cores_add:
        if core not in result:
            result.append(core)
    return tuple(result)


def _parse_make_var(path: Path, name: str) -> tuple[str, ...]:
    """Read a `NAME="a b c"` assignment out of a Lakka package.mk.

    Handles backslash-newline continuations -- Lakka's libretro_cores
    package.mk spans many lines:

        LIBRETRO_CORES="2048 \\
                        4do \\
                        ..."

    A naive line-by-line parser turns the trailing `\\` into a token, which
    then gets passed as a package name. Don't do that.
    """
    text = path.read_text(encoding="utf-8")
    rhs_parts: list[str] = []
    in_assignment = False
    for line in text.splitlines():
        if not in_assignment:
            stripped = line.lstrip()
            if not stripped.startswith(f"{name}="):
                continue
            _, _, rhs = stripped.partition("=")
            in_assignment = True
        else:
            rhs = line
        rstripped = rhs.rstrip()
        if rstripped.endswith("\\"):
            rhs_parts.append(rstripped[:-1])
            continue
        rhs_parts.append(rhs)
        break

    if not in_assignment:
        return ()

    joined = " ".join(rhs_parts).strip()
    # Strip a single pair of outer quotes (or a stray opening/closing one).
    if joined[:1] in ('"', "'"):
        joined = joined[1:]
    if joined[-1:] in ('"', "'"):
        joined = joined[:-1]
    return tuple(token for token in joined.split() if token)


# ================================================================ CLI ===


# ---------------------------------------------------- output mode plumbing

# Two output modes, mirroring the legacy shell build:
#   DEFAULT -- colored progress on screen, full Lakka stdout/stderr to build.log.
#   VERBOSE -- everything streams to the terminal (enabled with `-v/--verbose`).

# ANSI codes; auto-disabled when stderr is not a tty (CI logs, redirected).
_ANSI = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "green":  "\033[32m",
    "cyan":   "\033[36m",
    "yellow": "\033[33m",
    "red":    "\033[31m",
    "dim":    "\033[2m",
}


def _use_color() -> bool:
    return sys.stderr.isatty() and os.environ.get("NO_COLOR") is None


class _ColorFormatter(logging.Formatter):
    """Strip noisy `lakka:` / `package:` prefixes and color by level."""

    _LEVEL_COLOR = {
        "DEBUG":   _ANSI["dim"],
        "INFO":    _ANSI["green"],
        "WARNING": _ANSI["yellow"],
        "ERROR":   _ANSI["red"],
    }

    def __init__(self, *, use_color: bool):
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        # The legacy script printed bare progress; drop the module-prefix noise.
        for prefix in ("lakka: ", "package: "):
            if msg.startswith(prefix):
                msg = msg[len(prefix):]
                break
        if not self.use_color:
            return msg
        color = self._LEVEL_COLOR.get(record.levelname, "")
        # Highlight `[N/M] pkg` progress lines: bold cyan counter.
        if msg.startswith("  [") and "] " in msg:
            counter, _, rest = msg.partition("] ")
            return (f"  {_ANSI['cyan']}{_ANSI['bold']}{counter[2:]}]{_ANSI['reset']} "
                    f"{_ANSI['bold']}{rest}{_ANSI['reset']}")
        # Family header lines start with `== ` -> bold green.
        if msg.startswith("== "):
            return f"{_ANSI['bold']}{_ANSI['green']}{msg}{_ANSI['reset']}"
        return f"{color}{msg}{_ANSI['reset']}"


def _configure_output(verbose: bool):
    """Wire up logging + subprocess redirection.

    Returns the build.log file handle (or None in verbose mode) so the
    caller can close it at the end of the run.
    """
    use_color = _use_color()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_ColorFormatter(use_color=use_color))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    if verbose:
        # Pass-through: subprocess inherits the parent's stdout/stderr.
        lakka.configure_subprocess()
        package.configure_subprocess()
        return None

    # Default: colored progress on screen, everything else into build.log.
    log_path = REPO_ROOT / "build.log"
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    log.info("full output -> %s", log_path)
    lakka.configure_subprocess(stdout=log_file, stderr=subprocess.STDOUT)
    package.configure_subprocess(stdout=log_file, stderr=subprocess.STDOUT)
    return log_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the RetroArch Kodi add-on.",
        epilog="Default: colored progress on screen, full Lakka output "
               "appended to build.log. Use -v/--verbose to stream "
               "everything to the terminal instead.",
    )
    parser.add_argument("--device", choices=sorted(_DEVICES.keys()),
                        action="append", default=None,
                        help="Build only the given device. Repeatable. "
                             "If omitted, builds every supported device.")
    parser.add_argument("--version", dest="addon_version", required=True,
                        help="Add-on version tag (e.g. v1.0.0).")
    parser.add_argument("--lakka-dir", default=str(REPO_ROOT / "Lakka-LibreELEC"),
                        help="Path to a cloned Lakka-LibreELEC tree.")
    parser.add_argument("--lakka-version", default=DEFAULT_LAKKA_VERSION,
                        help="Lakka commit to check out before building.")
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="Parallel `make` jobs for Lakka "
                             "(sets CONCURRENCY_MAKE_LEVEL). "
                             "Defaults to Lakka's own default.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Stream full Lakka output to the terminal.")
    parser.add_argument("--keep-work", action="store_true",
                        help="Keep the retroarch_work/ staging dir after a "
                             "successful build (default: remove it).")
    parser.add_argument("--addon-only", action="store_true",
                        help="Build only the Lakka retroarch package to "
                             "refresh the default retroarch.cfg, then assemble "
                             "the universal add-on ZIP. Skips cores, tools, "
                             "DLC packages and AppImage creation. Intended "
                             "for fast addon ZIP testing when a compatible "
                             "AppImage is already installed on the target box.")
    args = parser.parse_args(argv)

    log_file = _configure_output(verbose=args.verbose)

    last_work_dir: Path | None = None
    try:
        if args.addon_only:
            # Build only the RetroArch package for one reference device so
            # config/retroarch.cfg is generated exactly by Lakka's package
            # build, then assemble the universal thin addon ZIP. No cores,
            # tools, DLC packages and no AppImage asset are built.
            # If multiple --device values are passed, use the first one only:
            # the addon ZIP is universal, and the device is needed only to
            # build the reference RetroArch cfg.
            ref_device = (args.device or sorted(_DEVICES.keys()))[0]
            cfg = BuildConfig(
                device=ref_device,
                addon_version=args.addon_version,
                lakka_dir=Path(args.lakka_dir).resolve(),
                lakka_version=args.lakka_version,
                jobs=args.jobs,
            )
            last_work_dir = cfg.work_dir
            try:
                build_retroarch_seed_config(cfg)
                zip_path, zip_sha = assemble_addon(cfg)

                # addon-only builds produce only the universal addon ZIP.
                # Still emit updates-v2-current.xml with the addon hash and
                # no AppImage artifacts, so maintainers can refresh addon
                # metadata without running a full per-platform AppImage build.
                package.emit_updates_current(
                    REPO_ROOT / "updates-v2-current.xml",
                    addon_id=ADDON_ID,
                    addon_version=args.addon_version,
                    addon_zip=zip_path,
                    addon_sha256=zip_sha,
                    artifacts=[],
                )
            except subprocess.CalledProcessError as exc:
                log.error("addon-only retroarch build failed: %s", exc)
                return 1
            except (FileNotFoundError, RuntimeError) as exc:
                log.error("addon-only build failed: %s", exc)
                return 1

            if not args.keep_work and cfg.work_dir.exists():
                log.info("cleaning up %s", cfg.work_dir)
                shutil.rmtree(cfg.work_dir, ignore_errors=True)
            return 0

        devices = args.device or sorted(_DEVICES.keys())
        artifacts: list[AppImageArtifact] = []
        ref_cfg: BuildConfig | None = None
        # Phase 1: one AppImage per device.
        for device in devices:
            cfg = BuildConfig(
                device=device,
                addon_version=args.addon_version,
                lakka_dir=Path(args.lakka_dir).resolve(),
                lakka_version=args.lakka_version,
                jobs=args.jobs,
            )
            last_work_dir = cfg.work_dir
            try:
                artifacts.append(build_appimage(cfg))
            except subprocess.CalledProcessError as exc:
                log.error("build failed for %s: %s", device, exc)
                return 1
            except (FileNotFoundError, RuntimeError) as exc:
                log.error("%s: %s", device, exc)
                return 1
            if ref_cfg is None:
                ref_cfg = cfg

        # Phase 2: assemble the single universal addon ZIP from the reference
        # device's staging (resources are device-independent).
        if ref_cfg is None:
            log.error("no devices built; nothing to assemble")
            return 1
        zip_path, zip_sha = assemble_addon(ref_cfg)

        # Phase 3: emit updates-v2-current.xml — a build artifact (gitignored)
        # with the real sha256 hashes and EMPTY policy placeholders. The
        # committed updates.xml is hand-curated and never overwritten by the
        # build; the maintainer copies the fresh hashes from here.
        package.emit_updates_current(
            REPO_ROOT / "updates-v2-current.xml",
            addon_id=ADDON_ID,
            addon_version=args.addon_version,
            addon_zip=zip_path,
            addon_sha256=zip_sha,
            artifacts=[(a.platform, a.version, a.path.name, a.sha256)
                       for a in artifacts],
        )

        if not args.keep_work and last_work_dir is not None and last_work_dir.exists():
            log.info("cleaning up %s", last_work_dir)
            shutil.rmtree(last_work_dir, ignore_errors=True)
        return 0
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        return 130
    finally:
        if log_file is not None:
            log_file.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
