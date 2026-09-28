#!/usr/bin/env python3
"""Verify that CPS game output carries both MSVC and GCC/Clang startup hooks.

Usage: python test_msvc_cps_codegen.py [--recompiler <psxrecomp-game.exe>]
"""

import argparse
import os
import struct
import subprocess
import sys
import tempfile


LOAD = 0x80010000


def make_exe():
    header = bytearray(2048)
    header[0:8] = b"PS-X EXE"
    struct.pack_into("<I", header, 0x10, LOAD)
    struct.pack_into("<I", header, 0x18, LOAD)
    body = struct.pack("<II", 0x03E00008, 0x00000000)  # jr ra; nop
    struct.pack_into("<I", header, 0x1C, len(body))
    return bytes(header) + body


def generate_dispatch(recompiler):
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "tiny.psx")
        seeds = os.path.join(tmp, "seeds.txt")
        out = os.path.join(tmp, "out")
        with open(exe, "wb") as stream:
            stream.write(make_exe())
        with open(seeds, "w", encoding="utf-8") as stream:
            stream.write(f"0x{LOAD:08X}\n")
        result = subprocess.run(
            [recompiler, exe, "--seeds", seeds, "--out-dir", out],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        dispatches = [
            os.path.join(out, name)
            for name in os.listdir(out)
            if name.endswith("_dispatch.c")
        ]
        if len(dispatches) != 1:
            raise RuntimeError(
                "expected one generated dispatch, found "
                f"{[os.path.basename(path) for path in dispatches]}; "
                f"generator output:\n{result.stdout}"
            )
        with open(dispatches[0], encoding="utf-8") as stream:
            return stream.read()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default = os.path.normpath(
        os.path.join(here, "..", "build", "psxrecomp-game.exe")
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--recompiler", default=default)
    args = parser.parse_args()

    if not os.path.isfile(args.recompiler):
        print(f"FAIL: recompiler not found: {args.recompiler}", file=sys.stderr)
        return 2

    try:
        generated = generate_dispatch(args.recompiler)
    except (OSError, RuntimeError) as exc:
        print(f"FAIL: generation failed: {exc}", file=sys.stderr)
        return 1

    required = (
        "static void psx_cps_mark_game(void)",
        "#if defined(_MSC_VER)",
        '#pragma section(".CRT$XCU", read)',
        '__declspec(allocate(".CRT$XCU")) static void '
        "(*psx_cps_mark_game_ctor)(void) = psx_cps_mark_game;",
        "__attribute__((constructor)) static void psx_cps_mark_game_ctor(void) "
        "{ psx_cps_mark_game(); }",
    )
    missing = [text for text in required if text not in generated]
    if missing:
        for text in missing:
            print(f"FAIL: generated dispatch is missing: {text}", file=sys.stderr)
        return 1

    print("PASS: generated CPS startup hooks cover MSVC and GCC/Clang.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
