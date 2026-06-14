"""Driver for the Lakka-LibreELEC build system.

Drives Lakka to:

    1. Apply patches from `patches/<scope>/*.patch` and revert them on exit
       (context-manager so a crash mid-build still cleans up the source tree).
    2. Run `./scripts/build <package>` for each package in the family list,
       with the right DISTRO / PROJECT / DEVICE / ARCH environment.
    3. Locate the resulting `build.<distro>-<device>.<arch>/install_pkg/<pkg>-<ver>`
       directories and copy their contents into a single staging tree.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Iterator

log = logging.getLogger(__name__)

_PKG_VERSION_RE = re.compile(
    r'^\s*PKG_VERSION\s*=\s*"(?P<value>[^"]+)"', re.MULTILINE
)


# Subprocess output target -- configured once from build.py's main().
# `None` (default) = pass-through to terminal (verbose mode).
# `DEVNULL`        = discard (quiet mode, the default).
# Open file handle = tee into log file (DEBUG=1 mode).
_SUBPROC_KW: dict = {}


def configure_subprocess(*, stdout=None, stderr=None) -> None:
    """Set default stdout/stderr for every subprocess.run in this module."""
    global _SUBPROC_KW
    _SUBPROC_KW = {}
    if stdout is not None:
        _SUBPROC_KW["stdout"] = stdout
    if stderr is not None:
        _SUBPROC_KW["stderr"] = stderr


def _run(args, **kw):
    """subprocess.run wrapper honoring `configure_subprocess` defaults."""
    merged = {**_SUBPROC_KW, **kw}
    return subprocess.run(args, **merged)


@contextlib.contextmanager
def patched(lakka_dir: Path, repo_root: Path, device: str, project: str,
            arch: str, lakka_version: str) -> Iterator[None]:
    """Check out `lakka_version`, apply all patches; revert on exit."""
    _git_checkout(lakka_dir, lakka_version)
    patches = _collect_patches(repo_root, device, project, arch)
    log.info("lakka: applying %d patches", len(patches))
    applied: list[Path] = []
    try:
        for patch in patches:
            _git_apply(lakka_dir, patch, reverse=False)
            applied.append(patch)
        yield
    finally:
        log.info("lakka: reverting %d patches", len(applied))
        for patch in reversed(applied):
            try:
                _git_apply(lakka_dir, patch, reverse=True)
            except subprocess.CalledProcessError as exc:
                log.warning("lakka: revert of %s failed: %s", patch, exc)


def build_packages(lakka_dir: Path, package_list: dict[str, tuple[str, ...]],
                   *, distro: str, project: str, device_lakka: str,
                   arch: str, jobs: int | None = None) -> None:
    """Call Lakka's `./scripts/build <pkg>` for every package."""
    env = _build_env(distro=distro, project=project,
                     device=device_lakka, arch=arch)
    if jobs is not None:
        env["CONCURRENCY_MAKE_LEVEL"] = str(jobs)
    script = lakka_dir / "scripts" / "build"
    total = sum(len(p) for p in package_list.values())
    counter = 0
    for family, pkgs in package_list.items():
        log.info("== %s (%d packages)", family, len(pkgs))
        for pkg in pkgs:
            counter += 1
            log.info("  [%d/%d] %s", counter, total, pkg)
            _run([str(script), pkg], cwd=str(lakka_dir),
                 env=env, check=True)


def copy_built_packages(lakka_dir: Path,
                        package_list: dict[str, tuple[str, ...]],
                        *, distro: str, project: str, device_lakka: str,
                        arch: str, subdirs: dict[str, str],
                        work_dir: Path) -> Path:
    """Copy every built package's `install_pkg/` content into a single tree.

    Returns the path of the merged staging directory.
    """
    build_sub = f"build.{distro}-{device_lakka or project}.{arch}"
    build_root = lakka_dir / build_sub / "install_pkg"
    if not build_root.is_dir():
        raise FileNotFoundError(f"Lakka build output missing: {build_root}")

    target = work_dir / "staging"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for family, pkgs in package_list.items():
        subdir = subdirs.get(family)
        if subdir is None:
            log.warning("lakka: no subdir mapping for family %s", family)
            continue
        for pkg in pkgs:
            pkg_mk = lakka_dir / "packages" / subdir / pkg / "package.mk"
            if not pkg_mk.is_file():
                log.info("lakka: skipping %s (no package.mk)", pkg)
                continue
            versions = _pkg_versions(pkg_mk)
            src = _locate_install_pkg(build_root, pkg, versions)
            if src is None:
                log.info("lakka: skipping %s (no install_pkg dir)", pkg)
                continue
            _merge_tree(src, target)
    return target


# ============================================================== internals ==


def _build_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_SSL_NO_VERIFY", "1")
    env["BUILD_NO_VERSION"] = "yes"
    for key, value in overrides.items():
        env[key.upper()] = value
    return env


def _collect_patches(repo_root: Path, device: str, project: str,
                     arch: str) -> list[Path]:
    """Return all .patch files from the standard patches search path, in order."""
    scopes = ["common", device, project, arch]
    out: list[Path] = []
    for scope in scopes:
        scope_dir = repo_root / "patches" / scope
        if not scope_dir.is_dir():
            continue
        out.extend(sorted(scope_dir.glob("*.patch")))
    return out


def _git_checkout(lakka_dir: Path, ref: str) -> None:
    _run(["git", "checkout", ref], cwd=str(lakka_dir), check=True)


def _git_apply(lakka_dir: Path, patch: Path, *, reverse: bool) -> None:
    args = ["git", "apply"]
    if reverse:
        args.append("--reverse")
    args.append(str(patch))
    _run(args, cwd=str(lakka_dir), check=True)


def _pkg_versions(pkg_mk: Path) -> list[str]:
    """Return every value Lakka assigns to PKG_VERSION in this file.

    Most packages have a single line; some pin via a fallback assignment
    (e.g. `PKG_VERSION="x.y.z"` then later `PKG_VERSION="$(rev-parse HEAD)"`)
    so we record every match and let the caller pick whichever directory
    exists.
    """
    text = pkg_mk.read_text(encoding="utf-8", errors="replace")
    return [m.group("value") for m in _PKG_VERSION_RE.finditer(text)]


def _locate_install_pkg(build_root: Path, pkg: str,
                        versions: Iterable[str]) -> Path | None:
    for version in versions:
        candidate = build_root / f"{pkg}-{version}"
        if candidate.is_dir():
            return candidate
    return None


def _merge_tree(src: Path, dst: Path) -> None:
    """Recursive copy with overwrite. Equivalent to `cp -Rf src/* dst/`."""
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dst_root = dst / rel
        dst_root.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(Path(root) / name, dst_root / name)
