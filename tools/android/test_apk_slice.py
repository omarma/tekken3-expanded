#!/usr/bin/env python3
"""Builds and runs test_apk_slice.c on the desktop: the placeholder header
parser of the runtime's android_apk_file.c, with AddressSanitizer when the
compiler has it.

  test_apk_slice.py [--cc cc]
  python3 -m unittest tools/android/test_apk_slice.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "psxrecomp/runtime/src"


def build_and_run(cc: str = "cc") -> int:
    with tempfile.TemporaryDirectory() as work:
        exe = Path(work) / "test_apk_slice"
        sources = [str(ROOT / "tools/android/test_apk_slice.c"), str(SRC / "android_apk_file.c")]
        common = ["-O1", "-g", "-Wall", "-Wextra", "-DPSX_APK_SLICE_PARSE_ONLY", f"-I{SRC}",
                  "-o", str(exe), *sources]
        sanitized = subprocess.run([cc, "-fsanitize=address,undefined", *common],
                                   capture_output=True)
        if sanitized.returncode != 0:
            subprocess.run([cc, *common], check=True)
        return subprocess.run([str(exe)]).returncode


class ApkSliceTests(unittest.TestCase):
    def test_parser(self):
        self.assertEqual(build_and_run(), 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cc", default="cc")
    return build_and_run(parser.parse_args().cc)


if __name__ == "__main__":
    sys.exit(main())
