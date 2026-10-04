#!/usr/bin/env python3
"""Test the disc read in place from the APK, without a phone or the real disc.

  1. makes a synthetic 3-track disc shaped like Tekken 3's (synthetic_disc.py:
     Mode 2 Form 1/Form 2 sectors with valid EDC/ECC, XA audio, STR video, CD
     audio, silence), and two texture pack files (.rgba and their PNG, one
     cropped as forest-hd's background);
  2. puts them into an APK with build_apk.py (reusing the libmain.so of an
     Android build: --build-dir, e.g. the one make_apk.py --bios-test makes),
     the tracks packed (disc_pack.py), or plain with --disc-format bin, and the
     textures as PNG; checks that they are stored uncompressed and aligned;
  3. writes the placeholders the app writes (GameData.java): sparse files
     naming the APK, the offset and the length of each track or PNG (a packed
     track's placeholder: psxrecomp-apk-pack, the original track's size);
  4. builds test_disc_in_apk.cpp for arm64 Android with the NDK, linked like
     libmain.so (android_apk_file.c, disc_pack.c, --wrap=fopen, the runtime's
     disc code, hd_png.c), and runs it under qemu-aarch64-static: every track
     must read back byte for byte through fopen, std::ifstream, several
     threads, ISOReader and identify_disc (the launcher's disc check, CRC
     included), and each PNG decode to exactly its .rgba's pixels.

Runs both disc formats unless --disc-format says one.

Usage:
  test_disc_in_apk.py [--build-dir build-android-bios-test] [--keep]
                      [--disc-format packed|bin] [--scale 0.01]
Needs the Android tools in .setup/android (make_apk.py downloads them) and
qemu-aarch64-static (apt install qemu-user-static).
"""
from __future__ import annotations

import argparse
import importlib.util
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_apk  # noqa: E402
import disc_pack  # noqa: E402
import make_apk  # noqa: E402
import synthetic_disc  # noqa: E402

RUNTIME = ROOT / "psxrecomp/runtime"
SLICE_MAGIC = b"psxrecomp-apk-slice\n"
PACK_MAGIC = b"psxrecomp-apk-pack\n"
RAW = 2352
# Real texture files of the repository: one shipped as its own PNG, one made
# from the .rgba (forest-hd's background is a crop of its PNG).
TEXTURES = ("mods/assets/outfit-menu/xiaoyu-blue", "mods/assets/forest-hd/background")


def log(message: str) -> None:
    print(f"[test] {message}", flush=True)


def placeholder(path: Path, apk: str, offset: int, length: int, size: int | None = None) -> None:
    """What GameData.placeholder() writes (size: a packed track's original size)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    magic = SLICE_MAGIC if size is None else PACK_MAGIC
    with path.open("wb") as out:
        out.write(magic + f"{offset} {length}\n{apk}\n".encode())
        out.truncate(length if size is None else size)


def data_offset(apk: Path, info: zipfile.ZipInfo) -> int:
    """Where an entry's bytes start: what AssetFileDescriptor.getStartOffset() says."""
    with apk.open("rb") as f:
        f.seek(info.header_offset)
        header = f.read(30)
    name_length, extra_length = struct.unpack("<HH", header[26:30])
    return info.header_offset + 30 + name_length + extra_length


def build_test(ndk: Path, build_dir: Path, work: Path) -> Path:
    """test_disc_in_apk.cpp for arm64 Android, linked like libmain.so."""
    bin_dir = ndk / "toolchains/llvm/prebuilt" / build_apk.ndk_host_tag() / "bin"
    target = f"--target=aarch64-linux-android{build_apk.MIN_SDK}"
    chdr = build_apk.cmake_cache(build_dir, "FETCHCONTENT_SOURCE_DIR_PSX_LIBCHDR")
    if not chdr:
        chdr = str(build_dir / "_deps/psx_libchdr-src")
    stb = ROOT / "recomp-ui/src/third_party"
    objects = []
    for source in ("android_apk_file.c", "disc_pack.c", "crc32.c", "psx_sha256.c", "hd_png.c"):
        obj = work / (source + ".o")
        subprocess.run([bin_dir / "clang", target, "-O2", "-Wall", "-Wextra", "-c",
                        "-I", RUNTIME / "include", "-I", stb,
                        RUNTIME / "src" / source, "-o", obj], check=True)
        objects.append(obj)
    test = work / "test_disc_in_apk"
    subprocess.run([bin_dir / "clang++", target, "-static", "-O2", "-std=c++17",
                    "-I", RUNTIME / "include", "-I", RUNTIME / "src", "-I", f"{chdr}/include",
                    ROOT / "tools/android/test_disc_in_apk.cpp",
                    RUNTIME / "src/iso_reader.cpp", RUNTIME / "src/cue_sheet.cpp",
                    RUNTIME / "src/disc_path.cpp", RUNTIME / "src/disc_identity.cpp",
                    *objects, "-lz", "-Wl,--wrap=fopen", "-Wl,--wrap=fopen64", "-o", test],
                   check=True)
    return test


def run_format(disc_format: str, args, tools: dict, qemu: str, test: Path, work: Path,
               tracks: list[Path], textures: Path) -> int:
    """Builds the APK with the disc in this format and runs the test over it."""
    log(f"--- disc format: {disc_format}")
    work.mkdir()
    ndk, build_tools, platform = tools["ndk"], tools["build-tools"], tools["platform"]
    apk = work / "test.apk"
    jdk = make_apk.java_home()
    javac, keytool = make_apk.exe(jdk / "bin/javac"), make_apk.exe(jdk / "bin/keytool")
    disc = tracks[0].parent
    subprocess.run([sys.executable, str(ROOT / "tools/android/build_apk.py"),
                    "--ndk", ndk, "--build-tools", build_tools, "--platform", platform,
                    "--build-dir", args.build_dir, "--skip-native", "--no-game-config",
                    "--keystore", work.parent / "test.keystore", "--javac", javac,
                    "--keytool", keytool, "--data", f"{disc}=disc",
                    "--data", f"{textures}=mods", "--disc-format", disc_format,
                    "--out", apk], check=True, stdout=subprocess.DEVNULL,
                   env=make_apk.java_env(jdk))
    subprocess.run([build_apk.tool(build_tools, "zipalign"), "-c", "-P", "16", "4", apk],
                   check=True)
    log("zipalign -c: the APK is aligned")

    # The placeholders, in a data folder laid out as the app's.
    data = work / "data"
    (data / "disc").mkdir(parents=True)
    shutil.copy2(disc / synthetic_disc.CUE_NAME, data / "disc" / synthetic_disc.CUE_NAME)
    run_args = [f"disc/{synthetic_disc.CUE_NAME}"]
    in_apk = 0
    with zipfile.ZipFile(apk) as z:
        for track in tracks:
            info = z.getinfo(f"assets/data/disc/{track.name}")
            if info.compress_type != zipfile.ZIP_STORED:
                raise SystemExit(f"{info.filename} is compressed in the APK")
            offset = data_offset(apk, info)
            with apk.open("rb") as f:
                f.seek(offset)
                stored = f.read(info.file_size)
            size = disc_pack.disc_pack_size(stored) if disc_format == "packed" else None
            if disc_format == "packed" and size != track.stat().st_size:
                raise SystemExit(f"{info.filename} is not the packed track")
            if disc_format == "bin" and stored != track.read_bytes():
                raise SystemExit(f"{info.filename}: wrong offset {offset}")
            in_apk += info.file_size
            log(f"{info.filename}: stored at offset {offset} ({info.file_size} bytes "
                f"for {track.stat().st_size}, offset % 4 = {offset % 4})")
            placeholder(data / "disc" / track.name, str(apk), offset, info.file_size, size)
            run_args += [f"disc/{track.name}", str(track)]
        for texture in TEXTURES:
            name = f"assets/data/{texture}.png"
            info = z.getinfo(name)
            if info.compress_type != zipfile.ZIP_STORED:
                raise SystemExit(f"{name} is compressed in the APK")
            if f"assets/data/{texture}.rgba" in z.namelist():
                raise SystemExit(f"{texture}.rgba is still in the APK")
            placeholder(data / f"{texture}.png", str(apk), data_offset(apk, info), info.file_size)
            run_args += ["--png", f"{texture}.png", str(textures.parent / f"{texture}.rgba")]
    log(f"the disc takes {in_apk / 1e6:.1f} MB in the APK "
        f"(the tracks: {sum(t.stat().st_size for t in tracks) / 1e6:.1f} MB)")

    # A range past 4 GB (64-bit offsets), in a sparse container.
    rng = random.Random(3)
    big, chunk = work / "big.img", rng.randbytes(1 << 20)
    big_offset = (9 << 29) + 3      # 4.5 GB + 3
    with big.open("wb") as f:
        f.seek(big_offset)
        f.write(chunk)
        f.truncate(big_offset + len(chunk) + 4096)
    (work / "chunk.bin").write_bytes(chunk)
    placeholder(data / "big.bin", str(big), big_offset, len(chunk))
    run_args += ["--big", "big.bin", str(work / "chunk.bin"), str(big_offset)]
    # A placeholder whose APK is gone (the app was updated or moved).
    placeholder(data / "stale.bin", str(work / "gone.apk"), 0, 8192)
    # A packed placeholder whose size is not the packed track's: refused.
    with zipfile.ZipFile(apk) as z:
        info = z.getinfo(f"assets/data/disc/{tracks[0].name}")
    if disc_format == "packed":
        placeholder(data / "wrong-size.bin", str(apk), data_offset(apk, info), info.file_size,
                    tracks[0].stat().st_size + RAW)
    else:
        placeholder(data / "wrong-size.bin", str(work / "gone.apk"), 0, 8192)
    (data / "ordinary.txt").write_text("just a file\n" + "x" * 8000)

    log("running under qemu")
    result = subprocess.run([qemu, test, *run_args], cwd=data)
    sizes = sum(p.stat().st_blocks * 512 for p in (data / "disc").iterdir())
    log(f"the data folder's disc takes {sizes // 1024} KB on disk "
        f"(the tracks: {sum(t.stat().st_size for t in tracks) // 1024} KB)")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-android-bios-test",
                        help="an Android build (its libmain.so goes into the test APK)")
    parser.add_argument("--keep", action="store_true", help="keep the work folder")
    parser.add_argument("--disc-format", choices=("packed", "bin"),
                        help="test only this format of the disc in the APK")
    parser.add_argument("--scale", type=float, default=0.01,
                        help="size of the synthetic disc, as a fraction of Tekken 3's")
    args = parser.parse_args()

    tools = make_apk.tool_folders()
    qemu = shutil.which("qemu-aarch64-static") or shutil.which("qemu-aarch64")
    if not qemu:
        raise SystemExit("qemu-aarch64-static is missing (apt install qemu-user-static)")
    if not (args.build_dir / "libmain.so").is_file():
        raise SystemExit(f"No libmain.so in {args.build_dir}: run make_apk.py --bios-test first")
    if importlib.util.find_spec("PIL") is None:
        raise SystemExit("Pillow is missing (python -m pip install pillow): the APK's "
                         "textures are checked with it")

    work = Path(tempfile.mkdtemp(prefix="disc-in-apk-"))
    try:
        tracks = synthetic_disc.make(work / "disc", args.scale)
        # Texture pack files, as the setup leaves them: .rgba beside its PNG.
        textures = work / "textures/mods"
        for texture in TEXTURES:
            relative = Path(texture).relative_to("mods")
            (textures / relative).parent.mkdir(parents=True, exist_ok=True)
            for suffix in (".rgba", ".png"):
                shutil.copy2(ROOT / (texture + suffix), textures / (str(relative) + suffix))
        test = build_test(tools["ndk"], args.build_dir, work)
        failures = 0
        for disc_format in [args.disc_format] if args.disc_format else ["packed", "bin"]:
            failures += run_format(disc_format, args, tools, qemu, test, work / disc_format,
                                   tracks, textures) != 0
        return 1 if failures else 0
    finally:
        if args.keep:
            log(f"work folder kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
