#!/usr/bin/env python3
"""Round trip of disc_pack.py over every sector, and what it costs to read.

  1. makes a synthetic disc shaped like Tekken 3's (synthetic_disc.py) and
     packs each track (disc_pack.py), printing the sizes per track;
  2. unpacks every track with disc_pack.py's reader: byte for byte the same;
  3. builds test_disc_pack.c with the runtime's reader (disc_pack.c) for this
     computer, with libchdr's ecc_verify when its source is at hand (it checks
     the synthetic disc's ECC with MAME's code), and runs it: every sector,
     random reads, the decode time per sector;
  4. builds it for arm64 Android with the NDK and runs it under qemu (skipped
     without the NDK or qemu-aarch64-static).

The unit tests (format details, damaged input) run without any of that.

Usage:
  test_disc_pack.py [--scale 0.02] [--keep]      (the whole round trip)
  python3 -m unittest tools/android/test_disc_pack.py   (unit tests only)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import disc_pack  # noqa: E402
import synthetic_disc  # noqa: E402

RUNTIME = ROOT / "psxrecomp/runtime"
SECTOR = disc_pack.SECTOR


def log(message: str) -> None:
    print(f"[test] {message}", flush=True)


class DiscPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def round_trip(self, data: bytes, **kwargs) -> tuple[bytes, dict]:
        source, packed = self.dir / "in.bin", self.dir / "in.pack"
        source.write_bytes(data)
        stats: dict = {}
        disc_pack.pack(source, packed, stats=stats, **kwargs)
        reader = disc_pack.Reader(packed)
        try:
            self.assertEqual(reader.size, len(data))
            self.assertEqual(reader.read(0, len(data) + 100), data)
            # Random access, block edges included.
            for at in (0, 1, SECTOR - 1, 16 * SECTOR - 3, len(data) // 2, max(0, len(data) - 5)):
                self.assertEqual(reader.read(at, 7000), data[at:at + 7000])
        finally:
            reader.close()
        return packed.read_bytes(), stats

    def test_every_kind_of_sector(self):
        tracks = synthetic_disc.make(self.dir / "disc", 0.002, seed=7)
        kinds = set()
        for track in tracks:
            _, stats = self.round_trip(track.read_bytes())
            kinds |= set(stats)
        self.assertEqual(kinds, {"form1", "xa", "zero", "raw"})

    def test_sectors_that_do_not_verify_stay_raw(self):
        track = synthetic_disc.make(self.dir / "disc", 0.002, seed=8)[0]
        data = bytearray(track.read_bytes()[:40 * SECTOR])
        data[3 * SECTOR + 2100] ^= 1          # Form 1 ECC wrong
        data[5 * SECTOR + 12] = 0x99          # header not its address
        data[6 * SECTOR + 20] ^= 1            # subheader copies differ
        data[7 * SECTOR + 2349] ^= 0xFF       # Form 2 EDC wrong (and not 0)
        _, stats = self.round_trip(bytes(data))
        self.assertEqual(stats["raw"][0], 4)

    def test_odd_sizes_and_plain_data(self):
        self.round_trip(b"")
        self.round_trip(b"x")
        self.round_trip(bytes(range(256)) * 41 + b"tail")          # not whole sectors
        self.round_trip(bytes(SECTOR * 17 + 5))                      # zeros and a tail
        self.round_trip(bytes(SECTOR * 3), sectors_per_block=1)

    def test_form2_without_edc_and_cd_audio(self):
        t = synthetic_disc.Track1()
        for i in range(20):
            t.add(0x20, bytes([i]) * 2324)
        data = bytearray(t.finish())
        for s in range(0, 20, 2):
            data[s * SECTOR + 2348:s * SECTOR + 2352] = bytes(4)    # EDC left at 0
        audio = synthetic_disc.pcm_music(__import__("random").Random(1), 588 * 40)
        _, stats = self.round_trip(bytes(data) + audio)
        self.assertEqual(stats.get("form2-noedc", [0])[0] + stats.get("xa-noedc", [0])[0], 10)

    def test_damaged_files_are_refused(self):
        packed, _ = self.round_trip(synthetic_disc.make(self.dir / "disc", 0.002, seed=9)[1].read_bytes())
        broken = bytearray(packed)
        broken[0] ^= 1
        (self.dir / "bad").write_bytes(bytes(broken))
        with self.assertRaises(ValueError):
            disc_pack.Reader(self.dir / "bad")


def compile_and_run(compiler: list, out: Path, extra: list, runner: list, pairs: list) -> int:
    subprocess.run([*compiler, "-O2", "-Wall", "-Wextra", "-I", RUNTIME / "src",
                    HERE / "test_disc_pack.c", RUNTIME / "src/disc_pack.c", *extra, "-o", out],
                   check=True)
    return subprocess.run([*runner, out, *pairs]).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", type=float, default=0.02)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    result = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=1).result
    failures = 0 if result.wasSuccessful() else 1

    work = Path(tempfile.mkdtemp(prefix="disc-pack-"))
    try:
        tracks = synthetic_disc.make(work / "disc", args.scale)
        pairs = []
        total_in = total_out = 0
        for track in tracks:
            packed = work / (track.stem + ".pack")
            size = disc_pack.pack(track, packed)
            reader = disc_pack.Reader(packed)
            original = track.read_bytes()
            same = all(reader.block(i) == original[i * 16 * SECTOR:(i + 1) * 16 * SECTOR]
                       for i in range(reader.blocks))
            reader.close()
            if not same:
                log(f"FAIL: {track.name}: disc_pack.py's reader does not give it back")
                failures += 1
            total_in += len(original)
            total_out += size
            log(f"{track.name}: {len(original)} -> {size} bytes "
                f"({100 * size / len(original):.1f}%), Python round trip ok")
            pairs += [str(packed), str(track)]
        log(f"disc: {total_in / 1e6:.1f} MB -> {total_out / 1e6:.1f} MB "
            f"({100 * total_out / total_in:.1f}%)")

        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        chdr = next((p for p in ROOT.glob("build-android*/_deps/psx_libchdr-src")), None)
        if chdr is None:
            import build_apk
            for build in ROOT.glob("build-android*"):
                source = build_apk.cmake_cache(build, "FETCHCONTENT_SOURCE_DIR_PSX_LIBCHDR")
                if source and Path(source).is_dir():
                    chdr = Path(source)
        if cc:
            extra = ["-lz", "-lpthread"]
            runner_args = []
            if chdr and (chdr / "src/libchdr_cdrom.c").is_file():
                extra = ["-DWITH_LIBCHDR", "-I", chdr / "include", chdr / "src/libchdr_cdrom.c"] + extra
                runner_args = ["--ecc-check"]
            log(f"native ({Path(cc).name})")
            failures += compile_and_run([cc], work / "test_native", extra, [],
                                        runner_args + pairs) != 0
        try:
            import make_apk
            import build_apk
            ndk = make_apk.TOOLS / make_apk.PINS[make_apk.host()]["ndk"][2]
            clang = ndk / "toolchains/llvm/prebuilt" / build_apk.ndk_host_tag() / "bin/clang"
        except Exception:
            clang = None
        qemu = shutil.which("qemu-aarch64-static") or shutil.which("qemu-aarch64")
        if clang and clang.is_file() and qemu:
            log("arm64 Android, under qemu")
            failures += compile_and_run(
                [clang, f"--target=aarch64-linux-android{build_apk.MIN_SDK}", "-static"],
                work / "test_arm64", ["-lz"], [qemu], pairs) != 0
        else:
            log("skipped arm64: no NDK in .setup/android or no qemu-aarch64-static")
        log("all ok" if not failures else f"{failures} failed")
        return 1 if failures else 0
    finally:
        if args.keep:
            log(f"work folder kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
