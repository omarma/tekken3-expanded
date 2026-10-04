#!/usr/bin/env python3
"""Builds and runs test_touch_slide.c on the desktop (the on-screen D-pad's
slides and taps reach the game frame by frame).

  test_touch_slide.py --build-dir build-linux   (a desktop build: its SDL3)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    sdl = next(args.build_dir.rglob("libSDL3.a"), None)
    # SDL's headers: in its source folder (the CMake cache names it).
    include = None
    cache = args.build_dir / "CMakeCache.txt"
    if cache.is_file():
        for line in cache.read_text(errors="replace").splitlines():
            if line.startswith("SDL3_SOURCE_DIR:"):
                include = Path(line.split("=", 1)[1]) / "include/SDL3"
    if include is None or not (include / "SDL.h").is_file():
        include = next((p.parent for p in args.build_dir.rglob("SDL3/SDL.h")), None)
    if sdl is None or include is None:
        raise SystemExit(f"No SDL3 (libSDL3.a and its headers) in {args.build_dir}")
    with tempfile.TemporaryDirectory() as work:
        exe = Path(work) / "test_touch_slide"
        subprocess.run([args.cc, "-O1", "-o", str(exe), str(ROOT / "tools/android/test_touch_slide.c"),
                        f"-I{include.parent}", f"-I{ROOT / 'psxrecomp/runtime/include'}",
                        str(sdl), "-lm", "-lpthread", "-ldl"], check=True)
        return subprocess.run([str(exe)], env={**os.environ, "SDL_VIDEO_DRIVER": "dummy"}).returncode


if __name__ == "__main__":
    sys.exit(main())
