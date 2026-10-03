"""Iterative RetroArch development loop.

Takes the working tree of a local RetroArch checkout, exports it as a
package-level patch into Lakka, builds only the `retroarch` package, and
scp's the resulting binary onto a test device. This is the loop you want
when debugging a one-line RA change without rebuilding the whole addon.

    python -m scripts.test.ra_debug --device Amlogic-any.arm

Credentials and the RetroArch source path come from `scripts/test/local.py`
(see `local.py.example`).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .. import lakka
from ..build import (DEFAULT_LAKKA_VERSION, PKG_SUBDIRS, REPO_ROOT,
                     BuildConfig, _DEVICES)

log = logging.getLogger(__name__)


def _load_local() -> object:
    try:
        from . import local  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "scripts/test/local.py not found. Copy local.py.example to "
            "local.py and fill in REMOTE_IP / REMOTE_USER / REMOTE_PASSWORD."
        ) from exc
    for attr in ("REMOTE_IP", "REMOTE_USER", "REMOTE_PASSWORD"):
        if not getattr(local, attr, None):
            raise SystemExit(f"scripts/test/local.py: {attr} is empty")
    return local


def _try_load_local() -> object | None:
    """Best-effort import of local.py: None if absent, no REMOTE_* validation.

    Used to resolve RETROARCH_SRC_DIR for modes (--promote-patch) that need
    neither sshpass nor remote credentials.
    """
    try:
        from . import local  # type: ignore[import-not-found]
        return local
    except ImportError:
        return None


def _check_sshpass() -> str:
    path = shutil.which("sshpass")
    if path is None:
        raise SystemExit(
            "sshpass not found in PATH. Install it (e.g. `apt install sshpass`) "
            "or use SSH keys and edit this script."
        )
    return path


def _export_debug_patch(ra_src: Path, dest: Path) -> bool:
    """Write `git diff` from the RetroArch checkout into `dest`.

    Returns False (and skips writing) when the working tree is clean.
    """
    if not ra_src.is_dir():
        raise SystemExit(f"RetroArch source dir not found: {ra_src}")
    result = subprocess.run(
        ["git", "diff"], cwd=str(ra_src),
        capture_output=True, text=True, check=True,
    )
    if not result.stdout.strip():
        log.info("RetroArch working tree clean -- no debug patch")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout, encoding="utf-8")
    log.info("wrote debug patch -> %s", dest)
    return True


def promote_debug_patch(cfg: BuildConfig, ra_src: Path,
                        external_patch: Path, internal_name: str) -> bool:
    """Promote the current RetroArch working-tree diff into a committable patch.

    Pipeline:
        1. `git diff` in `ra_src` (the RetroArch checkout) -- the fix itself.
        2. Written as `<internal_name>` under Lakka's
           packages/lakka/retroarch_base/retroarch/patches/ -- the internal
           patch LibreELEC's own package build auto-applies while compiling
           `retroarch` (the same mechanism `retroarch_debug.patch` abuses for
           throwaway test builds).
        3. Captured as a single-file `git diff` of that new file against the
           pinned Lakka commit, written to `external_patch` -- the patch this
           addon commits under `patches/<scope>/`, where `lakka.patched()`
           applies it on every future build like any other project patch.

    Lakka is reset to `cfg.lakka_version` first so the capture is always
    relative to the same pinned baseline every other patch in `patches/` is
    written against; the tree must already be clean (no leftover debug state).
    The internal patch file and the `git add` staging are both undone before
    returning, so the Lakka checkout is left exactly as it was found -- Lakka
    itself is scratch here, nothing is meant to persist in it.

    Returns False (nothing written) when the RetroArch working tree has no
    pending changes to promote.
    """
    if not internal_name.endswith(".patch"):
        raise ValueError(
            f"internal_name must end in .patch for LibreELEC's package build "
            f"to auto-apply it: {internal_name!r}"
        )

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(cfg.lakka_dir),
        capture_output=True, text=True, check=True,
    )
    if status.stdout.strip():
        raise RuntimeError(
            f"Lakka tree at {cfg.lakka_dir} is dirty -- commit or stash before "
            f"promoting a patch so the capture is relative to a known "
            f"baseline:\n{status.stdout}"
        )
    lakka._git_checkout(cfg.lakka_dir, cfg.lakka_version)

    internal_patch = (
        cfg.lakka_dir / "packages" / "lakka" / "retroarch_base"
        / "retroarch" / "patches" / internal_name
    )
    if not _export_debug_patch(ra_src, internal_patch):
        return False

    rel = internal_patch.relative_to(cfg.lakka_dir).as_posix()
    try:
        subprocess.run(["git", "add", "--", rel], cwd=str(cfg.lakka_dir), check=True)
        result = subprocess.run(
            ["git", "diff", "--staged", "--", rel], cwd=str(cfg.lakka_dir),
            capture_output=True, text=True, check=True,
        )
    finally:
        subprocess.run(["git", "reset", "--", rel], cwd=str(cfg.lakka_dir), check=False)
        internal_patch.unlink(missing_ok=True)

    if not result.stdout.strip():
        raise RuntimeError(f"git diff produced no output for {rel}")

    external_patch.parent.mkdir(parents=True, exist_ok=True)
    external_patch.write_text(result.stdout, encoding="utf-8")
    log.info("promote: internal patches/%s -> external %s", internal_name, external_patch)
    return True


def list_applied_patches(cfg: BuildConfig) -> list[str]:
    """Return every *.patch file present in the RetroArch package's own
    patches/ dir once this project's patches (patches/<scope>/*.patch, as
    collected by lakka._collect_patches) are checked out and applied.

    Scoped to packages/lakka/retroarch_base/retroarch/patches/ only -- this
    is a RetroArch debugging helper, not a general Lakka patch browser, so
    every other package's patches (there can be hundreds across the tree)
    are deliberately excluded.

    This includes patches promoted via promote_debug_patch(): once one lands
    under that same directory as <name>.patch via the external patch
    committed to patches/<scope>/, applying the latter recreates the former,
    so it shows up here exactly like any upstream Lakka RetroArch patch would.

    Lakka is left exactly as found: checked out fresh to cfg.lakka_version,
    patched, listed, reverted -- same lifecycle as lakka.patched(), just
    without running a build in between. Subprocess stdout/stderr from the
    checkout/apply/revert steps is discarded by the caller; only the
    resulting patch list is meant to reach the user.
    """
    retroarch_patches_dir = (
        cfg.lakka_dir / "packages" / "lakka" / "retroarch_base"
        / "retroarch" / "patches"
    )
    with lakka.patched(cfg.lakka_dir, REPO_ROOT, cfg.profile.source_device,
                       cfg.profile.project, cfg.profile.arch, cfg.lakka_version):
        found = sorted(
            str(p.relative_to(cfg.lakka_dir))
            for p in retroarch_patches_dir.glob("*.patch")
        ) if retroarch_patches_dir.is_dir() else []
    return found


def _scp_binary(local_bin: Path, remote_host: str, remote_user: str,
                remote_password: str, remote_path: str,
                sshpass: str) -> None:
    cmd = [
        sshpass, "-p", remote_password,
        "scp",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-q",
        str(local_bin),
        f"{remote_user}@{remote_host}:{remote_path}",
    ]
    subprocess.run(cmd, check=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Iterative RetroArch build+deploy loop.",
    )
    parser.add_argument("--device", choices=sorted(_DEVICES.keys()), required=True)
    parser.add_argument("--lakka-dir", default=str(REPO_ROOT / "Lakka-LibreELEC"))
    parser.add_argument("--lakka-version", default=DEFAULT_LAKKA_VERSION)
    parser.add_argument("--ra-src",
                        help="Override RetroArch source dir "
                             "(default: ../RetroArch or local.RETROARCH_SRC_DIR).")
    parser.add_argument("-j", "--jobs", type=int, default=None)
    parser.add_argument("--promote-patch", metavar="EXTERNAL_PATH", default=None,
                        help="Instead of building+deploying, promote the "
                             "current RetroArch working-tree diff to a "
                             "committable addon patch at EXTERNAL_PATH (e.g. "
                             "patches/common/06-fix.patch, so lakka.patched() "
                             "picks it up on future builds). Requires "
                             "--internal-name. Needs neither sshpass nor "
                             "scripts/test/local.py.")
    parser.add_argument("--internal-name", metavar="NAME", default=None,
                        help="Filename for the internal Lakka-side RetroArch "
                             "patch (placed under packages/lakka/"
                             "retroarch_base/retroarch/patches/NAME). Must "
                             "end in .patch. Required with --promote-patch.")
    parser.add_argument("--list-patches", action="store_true",
                        help="List every *.patch file present under Lakka's "
                             "packages/ tree once this project's own patches "
                             "(patches/<scope>/*.patch) are applied, then "
                             "revert and exit. Includes anything landed via "
                             "--promote-patch. Needs neither sshpass nor "
                             "scripts/test/local.py.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    local = _try_load_local()

    cfg = BuildConfig(
        device=args.device,
        addon_version="debug",
        lakka_dir=Path(args.lakka_dir).resolve(),
        lakka_version=args.lakka_version,
        jobs=args.jobs,
    )

    if args.list_patches:
        lakka.configure_subprocess(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            patches = list_applied_patches(cfg)
        except subprocess.CalledProcessError as exc:
            log.error("list-patches failed: %s", exc)
            return 1
        if not patches:
            log.info("no retroarch patches found")
        else:
            log.info("%d retroarch patch(es):", len(patches))
            for rel in patches:
                log.info("  %s", rel)
        return 0

    if args.ra_src:
        ra_src = Path(args.ra_src).resolve()
    elif local is not None and hasattr(local, "RETROARCH_SRC_DIR"):
        ra_src = Path(local.RETROARCH_SRC_DIR).resolve()  # type: ignore[attr-defined]
    else:
        ra_src = (REPO_ROOT.parent / "RetroArch").resolve()

    if args.promote_patch:
        if not args.internal_name:
            parser.error("--promote-patch requires --internal-name")
        external_patch = Path(args.promote_patch)
        if not external_patch.is_absolute():
            external_patch = (REPO_ROOT / external_patch).resolve()
        try:
            promoted = promote_debug_patch(cfg, ra_src, external_patch,
                                           args.internal_name)
        except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
            log.error("promote failed: %s", exc)
            return 1
        if not promoted:
            log.info("RetroArch working tree clean -- nothing to promote")
            return 0
        log.info("promoted patch -> %s", external_patch)
        return 0

    local = _load_local()
    sshpass = _check_sshpass()

    debug_patch = (cfg.lakka_dir / "packages" / "lakka" / "retroarch_base"
                   / "retroarch" / "patches" / "retroarch_debug.patch")
    debug_patch.unlink(missing_ok=True)

    profile = cfg.profile
    package_list = {"LIBRETRO_BASE": ("retroarch",)}

    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    try:
        with lakka.patched(cfg.lakka_dir, REPO_ROOT, profile.source_device, profile.project,
                           profile.arch, cfg.lakka_version):
            _export_debug_patch(ra_src, debug_patch)
            try:
                lakka.build_packages(cfg.lakka_dir, package_list,
                                     distro="Lakka",
                                     project=profile.project,
                                     device_lakka=profile.device_lakka,
                                     arch=profile.arch,
                                     jobs=cfg.jobs)
                staging = lakka.copy_built_packages(
                    cfg.lakka_dir, package_list,
                    distro="Lakka", project=profile.project,
                    device_lakka=profile.device_lakka, arch=profile.arch,
                    subdirs=PKG_SUBDIRS, work_dir=cfg.work_dir,
                )
            finally:
                debug_patch.unlink(missing_ok=True)

        retroarch_bin = staging / "usr" / "bin" / "retroarch"
        if not retroarch_bin.is_file():
            log.error("built retroarch binary not found at %s", retroarch_bin)
            return 1

        remote_dir = (
            "/storage/.kodi/userdata/"
            "addon_data/script.retroarch.launcher/"
            "test"
        )
        remote_path = f"{remote_dir}/retroarch"

        mkdir_cmd = [
            sshpass, "-p", local.REMOTE_PASSWORD,  # type: ignore[attr-defined]
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-q",
            f"{local.REMOTE_USER}@{local.REMOTE_IP}",  # type: ignore[attr-defined]
            f"mkdir -p {remote_dir}",
        ]
        subprocess.run(mkdir_cmd, check=True)

        log.info("scp %s -> %s@%s:%s", retroarch_bin.name,
                 local.REMOTE_USER, local.REMOTE_IP, remote_path)  # type: ignore[attr-defined]
        try:
            _scp_binary(retroarch_bin,
                        local.REMOTE_IP, local.REMOTE_USER,  # type: ignore[attr-defined]
                        local.REMOTE_PASSWORD, remote_path,  # type: ignore[attr-defined]
                        sshpass)
        except subprocess.CalledProcessError:
            fallback = Path.cwd() / "retroarch"
            shutil.copy2(retroarch_bin, fallback)
            log.warning("scp failed -- copied to %s for manual upload to addon_data/test/retroarch", fallback)
            return 1

        log.info("done")
        return 0
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        return 130
    finally:
        if cfg.work_dir.exists():
            shutil.rmtree(cfg.work_dir, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
