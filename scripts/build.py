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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import lakka, package

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

# Pinned Lakka commit. Bumped intentionally — keep in sync with the README.
DEFAULT_LAKKA_VERSION = "c4d3f32b0e3d76889353ea0f6c81f947d6c6f103"

# Package families the build pulls from Lakka, keyed by their subdir under
# `packages/`. The names match the legacy `PKG_SUBDIR_*` variables.
PKG_SUBDIRS: dict[str, str] = {
    "LIBRETRO_CORES":  "lakka/libretro_cores",
    "LIBRETRO_BASE":   "lakka/retroarch_base",
    "LAKKA_TOOLS":     "lakka/lakka_tools",
    "LAKKA_DEPENDS":   "lakka/lakka_depends",
    "AUDIO":           "audio",
    "COMPRESS":        "compress",
    "SYSTEM_TOOLS":    "addons/addon-depends/system-tools-depends",
    "ADDON_DEPENDS":   "addons/addon-depends",
    "MULTIMEDIA":      "multimedia",
    "WEB":             "web",
    "DEVEL":           "devel",
    "VIRTUAL":         "virtual",
}

# Static, per-family package lists (excluding LIBRETRO_CORES which is dynamic).
STATIC_PACKAGES: dict[str, tuple[str, ...]] = {
    "LIBRETRO_BASE":  ("retroarch", "core_info", "retroarch_joypad_autoconfig"),
    "LAKKA_TOOLS":    ("joyutils", "sixpair", "empty",
                       "xbox360_controllers_shutdown", "cec-mini-kb"),
    "LAKKA_DEPENDS":  ("SDL2_input",),
    "AUDIO":          ("flac", "libogg", "openal-soft"),
    "COMPRESS":       ("zstd",),
    "SYSTEM_TOOLS":   ("diffutils",),
    "ADDON_DEPENDS":  ("libzip",),
    "MULTIMEDIA":     ("ffmpeg", "dav1d"),
    "WEB":            ("curl",),
    "DEVEL":          ("libfmt",),
    "VIRTUAL":        ("gbm",)
}

# Additional packages when DLC (assets / overlays / shaders / database) is on.
DLC_PACKAGES: tuple[str, ...] = (
    "retroarch_assets",
    "retroarch_overlays",
    "libretro_database",
    "glsl_shaders",
    "slang_shaders",
)

# Per-device customizations of the libretro core list. Cores listed in
# `fallback` are removed from the Lakka build and shipped as pre-compiled .so
# files instead (see `fallback-precompiled-cores/` in the repo root).
@dataclass(frozen=True)
class DeviceProfile:
    project: str
    device_lakka: str
    arch: str
    cores_add: tuple[str, ...] = ()
    cores_remove: tuple[str, ...] = ()
    cores_fallback: tuple[str, ...] = ()
    fallback_subdir: str = ""


_DEVICES: dict[str, DeviceProfile] = {
    "Amlogic-ng": DeviceProfile(
        project="Amlogic",
        device_lakka="AMLGX",
        arch="arm",
        cores_add=("puae2021", "mupen64plus", "same_cdi"),
        cores_remove=("mame", "puae", "mupen64plus_next", "kronos", "lr_moonlight"),
        cores_fallback=("flycast_xtreme",),
        fallback_subdir="arm7hf",
    ),
    "Amlogic-no": DeviceProfile(
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
    provider: str = "Giovanni Cascione"
    include_dlc: bool = False
    lakka_version: str = DEFAULT_LAKKA_VERSION
    lakka_dir: Path = field(default_factory=lambda: REPO_ROOT / "Lakka-LibreELEC")
    build_dir: Path = field(default_factory=lambda: REPO_ROOT / "build")
    work_dir: Path = field(default_factory=lambda: REPO_ROOT / "retroarch_work")
    # Parallel `make` job count for Lakka. None -> let Lakka pick its default.
    jobs: int | None = None

    @property
    def profile(self) -> DeviceProfile:
        return _DEVICES[self.device]

    @property
    def addon_name(self) -> str:
        return f"script.retroarch.launcher.{self.device}.{self.profile.arch}"

    @property
    def ra_name_suffix(self) -> str:
        return f"{self.device}.{self.profile.arch}"

    @property
    def addon_dir(self) -> Path:
        return self.work_dir / self.addon_name

    @property
    def archive_name(self) -> str:
        return f"{self.addon_name}-{self.addon_version}.zip"


# =============================================================== driver ===


def build(cfg: BuildConfig) -> None:
    """Run every phase of the build for a single device profile."""
    log.info("=== building %s @ %s ===", cfg.addon_name, cfg.addon_version)
    if not cfg.lakka_dir.is_dir():
        raise FileNotFoundError(f"Lakka source dir not found: {cfg.lakka_dir}")

    package_list = _resolve_package_list(cfg)

    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    with lakka.patched(cfg.lakka_dir, REPO_ROOT, cfg.device, cfg.profile.project,
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

    _setup_addon_dir(cfg)
    package.move_artifacts(tmp_target, cfg.addon_dir, with_dlc=cfg.include_dlc)
    package.add_fallback_cores(REPO_ROOT, cfg.addon_dir, cfg.profile)
    package.install_committed_source(OUTPUT_DIR, cfg.addon_dir, cfg.addon_name)
    package.emit_addon_xml(cfg.addon_dir, cfg.addon_name, cfg.addon_version,
                           cfg.provider, cfg.ra_name_suffix,
                           changelog=REPO_ROOT / "CHANGELOG.md")
    package.emit_language_files(cfg.addon_dir, cfg.addon_version,
                                cfg.ra_name_suffix)
    package.customize_retroarch_cfg(cfg.addon_dir, cfg.addon_name,
                                    with_dlc=cfg.include_dlc)
    package.create_archive(cfg.addon_dir, cfg.build_dir, cfg.archive_name)


def _setup_addon_dir(cfg: BuildConfig) -> None:
    """Wipe and re-create the per-device staging directory."""
    if cfg.addon_dir.exists():
        shutil.rmtree(cfg.addon_dir)
    for sub in ("", "config", "resources", "bin", "lib"):
        (cfg.addon_dir / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------- libretro core list resolve


def _resolve_package_list(cfg: BuildConfig) -> dict[str, tuple[str, ...]]:
    """Build the {family: (pkg, ...)} dict that drives Lakka invocations."""
    cores = _resolve_libretro_cores(cfg)
    out: dict[str, tuple[str, ...]] = {"LIBRETRO_CORES": cores}
    for family, pkgs in STATIC_PACKAGES.items():
        if family == "LIBRETRO_BASE" and cfg.include_dlc:
            out[family] = pkgs + DLC_PACKAGES
        else:
            out[family] = pkgs
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
    parser.add_argument("--provider", default="Giovanni Cascione")
    parser.add_argument("--include-dlc", action="store_true",
                        help="Bundle assets / overlays / shaders / database "
                             "into the addon (much larger zip).")
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
    args = parser.parse_args(argv)

    log_file = _configure_output(verbose=args.verbose)

    last_work_dir: Path | None = None
    try:
        devices = args.device or sorted(_DEVICES.keys())
        for device in devices:
            cfg = BuildConfig(
                device=device,
                addon_version=args.addon_version,
                provider=args.provider,
                include_dlc=args.include_dlc,
                lakka_dir=Path(args.lakka_dir).resolve(),
                lakka_version=args.lakka_version,
                jobs=args.jobs,
            )
            last_work_dir = cfg.work_dir
            try:
                build(cfg)
            except subprocess.CalledProcessError as exc:
                log.error("build failed for %s: %s", device, exc)
                return 1
            except (FileNotFoundError, RuntimeError) as exc:
                log.error("%s: %s", device, exc)
                return 1
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
