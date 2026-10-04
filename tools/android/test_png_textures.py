#!/usr/bin/env python3
"""The mods' textures as the APK ships them: PNG with exactly the .rgba's pixels.

Stages every texture pack of mods/ (and of --mods, e.g. build-release/mods
with the TTT1 import) the way build_apk.py does (ship_png_textures), then
decodes each PNG with the runtime's own decoder (hd_png.c, stb_image) and
compares it with its .rgba, byte for byte: on this computer, and for arm64
Android under qemu when the NDK and qemu-aarch64-static are there. Prints the
sizes and the decode times. Needs Pillow (as build_apk.py does).

Usage: test_png_textures.py [--mods build-release/mods]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import struct
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_apk  # noqa: E402

RUNTIME = ROOT / "psxrecomp/runtime"
STB = ROOT / "recomp-ui/src/third_party"


def log(message: str) -> None:
    print(f"[test] {message}", flush=True)


def build_and_run(compiler: list, runner: list, out: Path, pairs: list) -> int:
    subprocess.run([*compiler, "-O2", "-Wall", "-Wextra", "-I", RUNTIME / "src", "-I", STB,
                    HERE / "test_png_textures.c", RUNTIME / "src/hd_png.c", "-o", out, "-lm"],
                   check=True)
    return subprocess.run([*runner, out, *pairs]).returncode


def blank_png(width: int, height: int) -> bytes:
    """A black 1-bit grayscale PNG: tiny, whatever its size."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    row = bytes(1 + (width + 7) // 8)
    rows = zlib.compressobj(9)
    data = b"".join(rows.compress(row) for _ in range(height)) + rows.flush()
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", data) + chunk(b"IEND", b""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mods", type=Path, action="append", default=[ROOT / "mods"])
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="png-textures-"))
    try:
        pairs = []
        for n, mods in enumerate(args.mods):
            staged = work / f"staged{n}"
            shutil.copytree(mods, staged, ignore=shutil.ignore_patterns("*.tim", "*.bin"))
            originals = {p.relative_to(staged): mods / p.relative_to(staged)
                         for p in staged.rglob("*.rgba")}
            build_apk.ship_png_textures(staged)
            for relative, original in sorted(originals.items()):
                png = staged / relative.with_suffix(".png")
                if (staged / relative).exists() or not png.is_file():
                    log(f"FAIL: {relative} was not replaced by a PNG")
                    return 1
                pairs += [str(png), str(original)]
        # PNG bigger than any texture (a few KB each, gigabytes once decoded
        # unchecked): refused before decoding.
        for name, (width, height) in {"too-wide": (8193, 1), "too-many-pixels": (4097, 4097)}.items():
            big = work / f"{name}.png"
            big.write_bytes(blank_png(width, height))
            pairs[:0] = ["--refuse", str(big)]
        failures = build_and_run([shutil.which("cc") or "cc"], [], work / "native", pairs) != 0
        qemu = shutil.which("qemu-aarch64-static") or shutil.which("qemu-aarch64")
        try:
            import make_apk
            ndk = make_apk.TOOLS / make_apk.PINS[make_apk.host()]["ndk"][2]
            clang = ndk / "toolchains/llvm/prebuilt" / build_apk.ndk_host_tag() / "bin/clang"
        except Exception:
            clang = None
        if qemu and clang and clang.is_file():
            log("arm64 Android, under qemu")
            failures += build_and_run([clang, f"--target=aarch64-linux-android{build_apk.MIN_SDK}",
                                       "-static"], [qemu], work / "arm64", pairs) != 0
        else:
            log("skipped arm64: no NDK in .setup/android or no qemu-aarch64-static")
        return 1 if failures else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
