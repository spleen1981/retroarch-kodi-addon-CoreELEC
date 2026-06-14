"""Test generation of the addon files (manifest, source, PO, settings).

Equivalent of the legacy `scripts/test/new_files_test.sh`. Skips the heavy
Lakka build entirely; produces a `tmp_test_files/<addon_name>/` tree you
can inspect.

    python -m scripts.test.new_files --device Amlogic-ng
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Sequence

from .. import package
from ..build import (BuildConfig, OUTPUT_DIR, REPO_ROOT, _DEVICES,
                     _setup_addon_dir)

log = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the addon's text files into a tmp dir for inspection.",
    )
    parser.add_argument("--device", choices=sorted(_DEVICES.keys()), required=True)
    parser.add_argument("--version", dest="addon_version", default="test")
    parser.add_argument("--provider", default="Giovanni Cascione")
    parser.add_argument("--include-dlc", action="store_true")
    parser.add_argument("--out", default=str(REPO_ROOT / "tmp_test_files"),
                        help="Output directory (wiped on each run).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    out_dir = Path(args.out).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    cfg = BuildConfig(
        device=args.device,
        addon_version=args.addon_version,
        provider=args.provider,
        include_dlc=args.include_dlc,
        work_dir=out_dir,
    )

    _setup_addon_dir(cfg)
    package.install_committed_source(OUTPUT_DIR, cfg.addon_dir, cfg.addon_name)
    package.emit_addon_xml(cfg.addon_dir, cfg.addon_name, cfg.addon_version,
                           cfg.provider, cfg.ra_name_suffix,
                           changelog=REPO_ROOT / "CHANGELOG.md")
    package.emit_language_files(cfg.addon_dir, cfg.addon_version,
                                cfg.ra_name_suffix)

    log.info("generated files under %s", cfg.addon_dir)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
