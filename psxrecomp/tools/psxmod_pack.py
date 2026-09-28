#!/usr/bin/env python3
"""Create a deterministic .psxmod ZIP from a package source directory."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = args.source / "manifest.toml"
    if not manifest.is_file():
        parser.error("source must contain manifest.toml")
    files = sorted(path for path in args.source.rglob("*") if path.is_file())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(args.source).as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
