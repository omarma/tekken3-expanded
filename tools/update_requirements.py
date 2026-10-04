#!/usr/bin/env python3
"""Writes tools/requirements-import.txt and tools/requirements-pip.txt: the
importers' Python packages (Pillow, numpy) and pip itself, each an exact
version with the SHA-256 of every wheel PyPI has for it, so that pip installs
nothing else (the build scripts use --require-hashes --only-binary=:all:).

Run it again after changing a version below. numpy has no version for every
Python the build scripts accept (3.10 to 3.14): 2.2 for 3.10, 2.3 from 3.11.

Usage: update_requirements.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPORT = (("pillow", "12.0.0", ""),
          ("numpy", "2.2.6", 'python_version < "3.11"'),
          ("numpy", "2.3.5", 'python_version >= "3.11"'))
PIP = (("pip", "26.2.1", ""),)
HEADER = ("# Written by tools/update_requirements.py (exact versions, every wheel's\n"
          "# SHA-256 from PyPI): install with --require-hashes --only-binary=:all:\n")


def wheels(package: str, version: str) -> list[str]:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        release = json.load(response)
    return sorted(f["digests"]["sha256"] for f in release["urls"]
                  if f["packagetype"] == "bdist_wheel" and not f["yanked"])


def write(path: Path, pins) -> None:
    lines = [HEADER]
    for package, version, marker in pins:
        lines.append(f"{package}=={version}" + (f" ; {marker}" if marker else "") + " \\\n")
        hashes = wheels(package, version)
        lines += [f"    --hash=sha256:{h}" + (" \\\n" if i < len(hashes) - 1 else "\n")
                  for i, h in enumerate(hashes)]
    path.write_text("".join(lines), encoding="utf-8")
    print(f"{path}: {sum(len(wheels(p, v)) for p, v, _ in pins)} wheels")


if __name__ == "__main__":
    write(HERE / "requirements-import.txt", IMPORT)
    write(HERE / "requirements-pip.txt", PIP)
