"""Standalone patch apply/revert against the Lakka source tree.

Equivalent of the legacy `scripts/test/apply_patches.sh`. Useful when
iterating on patches without paying the cost of a full build.

    python -m scripts.test.apply_patches --target Amlogic-any.arm
    python -m scripts.test.apply_patches --target Amlogic-any.arm --revert
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from .. import lakka
from ..build import DEFAULT_LAKKA_VERSION, REPO_ROOT, _TARGETS

log = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply or revert all patches against the Lakka source tree.",
    )
    parser.add_argument("--target", choices=sorted(_TARGETS.keys()), required=True)
    parser.add_argument("--lakka-dir", default=str(REPO_ROOT / "Lakka-LibreELEC"))
    parser.add_argument("--lakka-version", default=DEFAULT_LAKKA_VERSION,
                        help="Lakka commit to check out before applying. "
                             "Skipped if --no-checkout is set.")
    parser.add_argument("--no-checkout", action="store_true",
                        help="Don't run `git checkout` first; operate on the "
                             "tree as it currently is.")
    parser.add_argument("--revert", action="store_true",
                        help="Revert patches instead of applying them.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    profile = _TARGETS[args.target]
    lakka_dir = Path(args.lakka_dir).resolve()
    if not lakka_dir.is_dir():
        log.error("Lakka source dir not found: %s", lakka_dir)
        return 1

    if not args.no_checkout:
        lakka._git_checkout(lakka_dir, args.lakka_version)

    patches = lakka._collect_patches(REPO_ROOT, args.target, profile.project,
                                     profile.arch)
    if not patches:
        log.info("no patches found for %s", args.target)
        return 0

    order = list(reversed(patches)) if args.revert else patches
    action = "reverting" if args.revert else "applying"
    log.info("%s %d patches", action, len(order))
    failed: list[Path] = []
    for patch in order:
        try:
            lakka._git_apply(lakka_dir, patch, reverse=args.revert)
            log.info("  ok    %s", patch.name)
        except Exception as exc:  # noqa: BLE001
            failed.append(patch)
            log.warning("  fail  %s: %s", patch.name, exc)

    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
