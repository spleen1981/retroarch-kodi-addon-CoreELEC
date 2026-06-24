"""Iterative RetroArch development loop.

Takes the working tree of a local RetroArch checkout, exports it as a
package-level patch into Lakka, builds only the `retroarch` package, and
scp's the resulting binary onto a test device. This is the loop you want
when debugging a one-line RA change without rebuilding the whole addon.

    python -m scripts.test.ra_debug --target Amlogic-any.arm

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
                     BuildConfig, _TARGETS)

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
    parser.add_argument("--target", choices=sorted(_TARGETS.keys()), required=True)
    parser.add_argument("--lakka-dir", default=str(REPO_ROOT / "Lakka-LibreELEC"))
    parser.add_argument("--lakka-version", default=DEFAULT_LAKKA_VERSION)
    parser.add_argument("--ra-src",
                        help="Override RetroArch source dir "
                             "(default: ../RetroArch or local.RETROARCH_SRC_DIR).")
    parser.add_argument("-j", "--jobs", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    local = _load_local()
    sshpass = _check_sshpass()

    cfg = BuildConfig(
        target=args.target,
        addon_version="debug",
        lakka_dir=Path(args.lakka_dir).resolve(),
        lakka_version=args.lakka_version,
        jobs=args.jobs,
    )

    if args.ra_src:
        ra_src = Path(args.ra_src).resolve()
    elif hasattr(local, "RETROARCH_SRC_DIR"):
        ra_src = Path(local.RETROARCH_SRC_DIR).resolve()  # type: ignore[attr-defined]
    else:
        ra_src = (REPO_ROOT.parent / "RetroArch").resolve()

    debug_patch = (cfg.lakka_dir / "packages" / "lakka" / "retroarch_base"
                   / "retroarch" / "patches" / "retroarch_debug.patch")
    debug_patch.unlink(missing_ok=True)

    profile = cfg.profile
    package_list = {"LIBRETRO_BASE": ("retroarch",)}

    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    try:
        with lakka.patched(cfg.lakka_dir, REPO_ROOT, cfg.target, profile.project,
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

        remote_path = (f"/storage/.kodi/addons/{cfg.addon_name}/bin/")
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
            log.warning("scp failed -- copied to %s for manual upload", fallback)
            return 1

        log.info("done")
        return 0
    except KeyboardInterrupt:
        log.warning("interrotto dall'utente")
        return 130
    finally:
        if cfg.work_dir.exists():
            shutil.rmtree(cfg.work_dir, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
