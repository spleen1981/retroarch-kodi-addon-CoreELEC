"""Optional CIFS mount of a remote ROMs share."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator, Optional

from . import paths
from .settings import AddonSettings

log = logging.getLogger(__name__)


@contextlib.contextmanager
def cifs_remote_roms(settings: AddonSettings) -> Iterator[None]:
    """Mount `settings.roms_remote_path` on `paths.ROMS_FOLDER`; umount on exit."""
    remote = settings.roms_remote_path.strip()
    if not remote:
        log.info("mount: remote roms enabled but no path configured")
        yield
        return

    mounted = _mount(remote, settings)
    try:
        yield
    finally:
        if mounted:
            _umount()


# Scratch mountpoint for the settings-page connectivity test. Never
# /storage/roms: a test must not disturb the folder a launch will use, and
# leaving a half-mounted roms dir behind would be worse than the failure
# being diagnosed.
TEST_MOUNTPOINT = Path("/tmp/ra_mount_test")


def test_remote_mount(settings: AddonSettings) -> dict:
    """Mount the configured share on a scratch dir, read it, unmount.

    Exercises exactly the argv and credentials file a real launch builds, so a
    pass here means the launch path will work too. Returns a result dict:

        ok        bool    mounted AND listable
        rc        int     mount.cifs exit code (0 on success)
        errno     int|None  the N from "mount error(N)", when reported
        output    str     captured mount.cifs stdout+stderr
        entries   int     number of entries found in the mounted root
    """
    result: dict = {"ok": False, "rc": -1, "errno": None, "output": "",
                    "entries": 0}

    remote = settings.roms_remote_path.strip()
    if not remote:
        result["output"] = "no remote path configured"
        return result

    try:
        TEST_MOUNTPOINT.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["output"] = f"cannot create {TEST_MOUNTPOINT}: {exc}"
        return result

    cred_file = _write_credentials_file(settings)
    non_secret_opts = _build_non_secret_options(settings)

    cmd = ["mount.cifs", remote, str(TEST_MOUNTPOINT)]
    opts: list[str] = []
    if cred_file is not None:
        opts.append(f"credentials={cred_file}")
    if non_secret_opts:
        opts.append(non_secret_opts)
    if opts:
        cmd.extend(["-o", ",".join(opts)])

    log.info("mount test: mount.cifs %s %s <options-redacted>",
             remote, TEST_MOUNTPOINT)
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              errors="replace")
        result["rc"] = proc.returncode
        result["output"] = (proc.stdout or "").strip()
    except OSError as exc:
        result["output"] = str(exc)
        return result
    finally:
        if cred_file is not None:
            try:
                os.unlink(cred_file)
            except OSError as exc:
                log.warning("mount test: cannot remove credentials file: %s", exc)

    match = re.search(r"mount error\((\d+)\)", result["output"])
    if match:
        result["errno"] = int(match.group(1))

    if result["rc"] != 0:
        for line in result["output"].splitlines():
            log.warning("mount test: %s", line)
        return result

    # Mounted: confirm it is actually readable. A share can mount and still
    # deny traversal, which would surface as an empty roms folder later.
    try:
        result["entries"] = len(list(TEST_MOUNTPOINT.iterdir()))
        result["ok"] = True
        log.info("mount test: ok, %d entries", result["entries"])
    except OSError as exc:
        result["output"] = f"mounted but not readable: {exc}"
        log.warning("mount test: %s", result["output"])
    finally:
        _umount_path(TEST_MOUNTPOINT)

    return result


# --------------------------------------------------------------- internals


def _mount(remote: str, settings: AddonSettings) -> bool:
    """Run mount.cifs with credentials kept out of argv. Return True on success."""
    cred_file = _write_credentials_file(settings)
    non_secret_opts = _build_non_secret_options(settings)

    cmd = ["mount.cifs", remote, str(paths.ROMS_FOLDER)]
    opts: list[str] = []
    if cred_file is not None:
        opts.append(f"credentials={cred_file}")
    if non_secret_opts:
        opts.append(non_secret_opts)
    if opts:
        cmd.extend(["-o", ",".join(opts)])

    # Mask credentials in logs. With the file-based approach, argv itself
    # only contains the file path — but redact the `-o` value all the same
    # so anyone copy-pasting log lines for support can't accidentally leak
    # the cred file location either.
    log_safe = [shlex.quote(part) for part in cmd]
    for idx, part in enumerate(log_safe):
        if part.startswith("credentials=") or "username=" in part:
            log_safe[idx] = "<options-redacted>"
    log.info("mount: %s", " ".join(log_safe))

    # mount.cifs prints the actual reason ("mount error(13): Permission
    # denied", "Unknown vers=", "Bad UNC", ...) on stderr. subprocess.call
    # inherited the descriptors, so it only ever reached the journal and the
    # addon log showed a bare exit code. Capture it and log it instead.
    captured_output = ""
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              errors="replace")
        rc = proc.returncode
        captured_output = (proc.stdout or "").strip()
    finally:
        if cred_file is not None:
            try:
                os.unlink(cred_file)
            except OSError as exc:
                log.warning("mount: cannot remove credentials file: %s", exc)

    if rc != 0:
        for line in captured_output.splitlines():
            log.warning("mount.cifs: %s", line)
        log.warning("mount: returned %d, continuing with empty roms folder", rc)
        return False
    if captured_output:
        for line in captured_output.splitlines():
            log.info("mount.cifs: %s", line)
    return True


def _write_credentials_file(settings: AddonSettings) -> Optional[str]:
    """Write a 0600 credentials file under /tmp; return its path, or None.

    Returns None when the user did not configure a username — guest mounts
    work without any credentials and don't need a file.
    """
    user = (settings.roms_remote_user or "").strip()
    if not user:
        return None
    password = settings.roms_remote_password or ""
    fd, path = tempfile.mkstemp(prefix="ra_cifs_", dir="/tmp")
    try:
        # fchmod before writing so the password never lands in a
        # world-readable file even briefly.
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"username={user}\n")
            fh.write(f"password={password}\n")
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _build_non_secret_options(settings: AddonSettings) -> str:
    """Compose the non-secret half of `-o` (currently just `vers=`)."""
    parts: list[str] = []
    vers = settings.roms_remote_vers
    if vers and vers != "Default":
        parts.append(f"vers={vers}")
    return ",".join(parts)


def _umount_path(target: Path) -> None:
    """Lazy-umount `target`; log a non-zero return code."""
    rc = subprocess.call(["umount", "-l", str(target)],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    if rc != 0:
        log.warning("umount -l %s returned %d", target, rc)


def _umount() -> None:
    # -l (lazy): detach the mount immediately even if the CIFS connection
    # dropped and there are pending kernel I/O operations. Without this,
    # umount blocks indefinitely on a dead CIFS share, freezing the cleanup.
    rc = subprocess.call(["umount", "-l", str(paths.ROMS_FOLDER)])
    if rc != 0:
        log.warning("umount -l %s returned %d", paths.ROMS_FOLDER, rc)
