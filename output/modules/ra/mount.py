"""Optional CIFS mount of a remote ROMs share."""

from __future__ import annotations

import contextlib
import logging
import os
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

    try:
        rc = subprocess.call(cmd)
    finally:
        if cred_file is not None:
            try:
                os.unlink(cred_file)
            except OSError as exc:
                log.warning("mount: cannot remove credentials file: %s", exc)

    if rc != 0:
        log.warning("mount: returned %d, continuing with empty roms folder", rc)
        return False
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


def _umount() -> None:
    rc = subprocess.call(["umount", str(paths.ROMS_FOLDER)])
    if rc != 0:
        log.warning("umount %s returned %d", paths.ROMS_FOLDER, rc)
