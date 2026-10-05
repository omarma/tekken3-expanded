#!/usr/bin/env python3
"""Build the Android APK of Tekken 3 Expanded, without Gradle.

Compiles the runtime with the Android NDK into libmain.so, then assembles the
APK directly with the SDK build tools:

  1. cmake + ninja, NDK toolchain, arm64-v8a  -> libmain.so + its data folder
  2. javac + d8                                -> classes.dex (SDL's activity
                                                  and GameActivity)
  3. aapt2 compile + link                      -> manifest, icon (--icon) and
                                                  data as assets
  4. zipalign + apksigner                      -> the signed APK

The data folder is the build folder laid out as on PC (assets/, mods/, bios/,
...); PrepareActivity copies it into the app's storage after an install,
except the disc's track files and the mods' PNG textures, which the game
reads from the APK in place (they are stored uncompressed by zip, see
NO_COMPRESS). Two lossless steps make the APK and the install lighter; the
game gets the same bytes and pixels:

  - the disc's tracks are packed (disc_pack.py: the sector headers, EDC/ECC
    and silence left out and computed back, the rest deflated in blocks the
    runtime unpacks as it reads); --disc-format bin keeps the plain .bin;
  - the mods' textures ship as PNG instead of raw .rgba (about a quarter of
    the size, decoded when the texture loads), each checked to decode to
    exactly the .rgba's pixels; --keep-rgba keeps the .rgba.

The APK is signed with a key made on first use and kept beside the build
(--keystore). Keep it: Android only installs an update signed with the same
key, so a new key means uninstalling the game, memory cards included.

Usage:
  build_apk.py --ndk <ndk> --build-tools <sdk>/build-tools/35.0.0
               --platform <sdk>/platforms/android-35 --build-dir <dir>
               --out Tekken3Expanded.apk [--icon icon.png] [-D<cmake option> ...]
"""
from __future__ import annotations

import argparse
import io
import os
import platform
import secrets
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disc_pack  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
MIN_SDK = 28      # posix_spawn and friends are in bionic from API 28
TARGET_SDK = 35
ABI = "arm64-v8a"
# Folders of the build output that belong to the game's data, as on PC.
DATA_DIRS = ("assets", "bios", "mods")
DATA_FILES = ("game.toml",)
# Stored uncompressed so the game can read them without inflating first; the
# disc's tracks (packed or not) and the mods' PNG are read straight from the
# APK (android_apk_file.c). A PNG is compressed already.
NO_COMPRESS = ("bin", "cue", "iso", "chd", "tga", "png", "ttf")
# The disc's track files that are packed (disc_pack.py).
PACKED_TRACKS = (".bin", ".img")
# Files of the mods' texture packs that the game never opens: the runtime
# reads <name>.rgba or <name>.png, mapping.bin and catalog.txt
# (gpu_gl_renderer.c). The authoring atlases and notes stay on PC, and so does
# the PNG each .rgba was made from when the .rgba ships instead (--keep-rgba).
MOD_SOURCES = ("prompts.json", "pack-report.json")


def unread_mod_file(path: Path) -> bool:
    if path.name in MOD_SOURCES:
        return True
    return path.suffix == ".png" and (path.name.startswith("authored-atlas")
                                      or path.with_suffix(".rgba").is_file())


def rgba_pixels(path: Path) -> tuple[int, int, bytes] | None:
    """Width, height and pixels of an HDRGBA01 file (gpu_gl_renderer.c)."""
    data = path.read_bytes()
    if len(data) < 16 or data[:8] != b"HDRGBA01":
        return None
    width, height = int.from_bytes(data[8:12], "little"), int.from_bytes(data[12:16], "little")
    if len(data) != 16 + 4 * width * height:
        return None
    return width, height, data[16:]


def png_texture(rgba: Path):
    """The PNG to ship for an .rgba texture, as (bytes, how): its source PNG
    when that decodes to exactly the same pixels, else a PNG made from the
    .rgba (e.g. a cropped texture). None without Pillow, or for a file that
    is not HDRGBA01. Either way the PNG is decoded again and compared."""
    try:
        from PIL import Image
    except ImportError:
        return None
    texture = rgba_pixels(rgba)
    if texture is None:
        return None
    width, height, pixels = texture

    def same(data: bytes) -> bool:
        with Image.open(io.BytesIO(data)) as image:
            # Only 8-bit PNG: their decoding (Pillow here, stb_image in the
            # game) is exact and the same everywhere.
            if image.format != "PNG" or image.info.get("interlace") or \
                    image.mode not in ("RGBA", "RGB", "L", "LA", "P"):
                return False
            image = image.convert("RGBA")
            return image.size == (width, height) and image.tobytes() == pixels

    source = rgba.with_suffix(".png")
    if source.is_file():
        data = source.read_bytes()
        if same(data):
            return data, "source"
    out = io.BytesIO()
    Image.frombytes("RGBA", (width, height), pixels).save(out, "PNG", optimize=True)
    if not same(out.getvalue()):
        raise SystemExit(f"{rgba}: the PNG made from it does not decode to the same pixels")
    return out.getvalue(), "made"


def ship_png_textures(mods: Path) -> None:
    """Replaces each staged <name>.rgba by <name>.png with the same pixels."""
    textures = sorted(mods.rglob("*.rgba"))
    if not textures:
        return
    before = after = 0
    made = []
    for rgba in textures:
        png = png_texture(rgba)
        if png is None:
            log(f"{rgba.name}: kept as .rgba (needs Pillow to ship it as PNG)")
            continue
        data, how = png
        before += rgba.stat().st_size
        after += len(data)
        rgba.with_suffix(".png").write_bytes(data)
        rgba.unlink()
        if how == "made":
            made.append(rgba.name)
    log(f"Textures as PNG: {before / 1e6:.1f} MB of .rgba -> {after / 1e6:.1f} MB of PNG"
        + (f" (made from the .rgba: {', '.join(made)})" if made else ""))


def stage_track(source: Path, target: Path, packed: bool) -> None:
    """A disc track file into the staged data, packed or as is."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if not packed:
        shutil.copy2(source, target)
        return
    size = disc_pack.pack(source, target)
    log(f"Packed {source.name}: {source.stat().st_size / 1e6:.1f} MB -> {size / 1e6:.1f} MB")


def is_track(relative: Path) -> bool:
    """A file of the staged data that is one of the disc's tracks."""
    return (relative.parts[:1] == ("disc",) and relative.suffix.lower() in PACKED_TRACKS)


# The launcher icon's sizes (--icon), per screen density.
MIPMAPS = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
# Android 8+ draws an adaptive icon: a 108 dp foreground over a background,
# cut to the launcher's shape (circle, squircle...). Only the middle 66 dp
# circle is sure to show, so the picture takes ICON_ART of the foreground.
ICON_ART = 0.72
ICON_BACKGROUND = "#000000"
ADAPTIVE_ICON = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
</adaptive-icon>
"""
ICON_ATTRIBUTE = 'android:icon="@mipmap/ic_launcher"'


def log(message: str) -> None:
    print(f"[apk] {message}", flush=True)


def run(command: list, **kwargs) -> None:
    shown = ["pass:***" if str(part).startswith("pass:") else str(part) for part in command]
    if "-storepass" in shown:
        shown[shown.index("-storepass") + 1] = "***"
    log(" ".join(shown))
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def tool(folder: Path, name: str) -> Path:
    for suffix in ("", ".exe", ".bat"):
        candidate = folder / (name + suffix)
        if candidate.is_file():
            return candidate
    raise SystemExit(f"{name} not found in {folder}")


def ndk_host_tag() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows-x86_64"
    if system == "Darwin":
        return "darwin-x86_64"   # the NDK ships universal binaries here
    return "linux-x86_64"


def cmake_cache(build_dir: Path, key: str) -> str | None:
    cache = build_dir / "CMakeCache.txt"
    if not cache.is_file():
        return None
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + ":"):
            return line.split("=", 1)[1]
    return None


def runs(command: list) -> bool:
    try:
        return subprocess.run([str(c) for c in command], capture_output=True).returncode == 0
    except OSError:
        return False


def find_glslc(ndk: Path) -> Path:
    """The Vulkan shader compiler. Android draws with Vulkan only, so without
    it the game would have no renderer: stop rather than build a stub."""
    bundled = ndk / "shader-tools" / ndk_host_tag() / ("glslc.exe" if os.name == "nt" else "glslc")
    for candidate in (bundled, shutil.which("glslc")):
        if candidate and runs([candidate, "--version"]):
            return Path(candidate)
    hint = (" On a Mac with Apple silicon: softwareupdate --install-rosetta, or brew install shaderc."
            if sys.platform == "darwin" else "")
    raise SystemExit(f"glslc (the NDK's Vulkan shader compiler) cannot run.{hint}")


# Netplay and the debug tools (a server on a local port that reads and writes
# the game's memory) stay out of the APK. They are set on every configure, as
# CMake would otherwise keep an ON from an earlier build in its cache; a -D
# turning them on needs --allow-debug-features.
RELEASE_DEFINES = ("PSX_DEBUG_TOOLS=OFF", "PSX_DEBUG_SERVER_LITE=OFF", "PSX_NETPLAY=OFF")


def native_defines(defines: list[str], allow_debug: bool) -> list[str]:
    released = {d.split("=", 1)[0] for d in RELEASE_DEFINES}
    for define in defines:
        name, _, value = define.partition("=")
        name = name.split(":", 1)[0]
        turns_on = name in released and value.strip().upper() not in ("OFF", "0", "FALSE", "NO")
        if not allow_debug and (turns_on or name == "CMAKE_BUILD_TYPE"):
            raise SystemExit(f"-D{define}: the APK is built without netplay and the debug "
                             "tools, in Release (--allow-debug-features for a test APK)")
    return ([] if allow_debug else list(RELEASE_DEFINES)) + list(defines)


# Windows runs d8 and apksigner, .bat files, through cmd.exe, which reads these
# in their arguments even quoted (Python only quotes arguments with spaces).
CMD_SPECIAL = set('&|<>^%!"')


def check_paths_for_cmd(*paths, windows: bool = os.name == "nt") -> None:
    if not windows:
        return
    for path in paths:
        bad = sorted(CMD_SPECIAL & set(str(path)))
        if bad:
            raise SystemExit(f"{path}: Windows cannot run the Android tools on a path with "
                             f"{' '.join(bad)} in it; move the folder or rename it")


# The PC setup's toolchain pack, which runtime.cmake searches for SDL3 and zlib:
# they are Windows or macOS builds, so the Android build must not see them.
PC_TOOLCHAIN_VARS = ("RETCOMM_TOOLCHAIN_DIR", "PSXRECOMP_TOOLCHAIN_DIR", "BPE_TOOLCHAIN_DIR", "TOOLCHAIN_DIR")


def android_env(build_dir: Path) -> dict:
    """The environment without the PC toolchain pack, and a CMake cache that
    found its SDL3 or zlib (Build Android APK 1.2.0 on Windows) dropped."""
    packs = [Path(os.environ[k]).as_posix() for k in PC_TOOLCHAIN_VARS if os.environ.get(k)]
    cache = build_dir / "CMakeCache.txt"
    if packs and cache.is_file() and any(p in cache.read_text(errors="replace") for p in packs):
        cache.unlink()
    return {k: v for k, v in os.environ.items() if k not in PC_TOOLCHAIN_VARS}


def build_native(args, build_dir: Path) -> Path:
    env = android_env(build_dir)
    toolchain = args.ndk / "build/cmake/android.toolchain.cmake"
    glslc = find_glslc(args.ndk)
    configure = [
        args.cmake, "-S", ROOT, "-B", build_dir, "-G", "Ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain}",
        f"-DANDROID_ABI={ABI}",
        f"-DANDROID_PLATFORM=android-{MIN_SDK}",
        "-DANDROID_STL=c++_static",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DGLSLC_EXE={glslc}",
    ]
    if args.ninja:
        configure.append(f"-DCMAKE_MAKE_PROGRAM={args.ninja}")
    configure += [f"-D{option}" for option in native_defines(args.define, args.allow_debug_features)]
    run(configure, env=env)
    run([args.cmake, "--build", build_dir, "--target", "psx-runtime"], env=env)
    library = build_dir / "libmain.so"
    if not library.is_file():
        raise SystemExit(f"The build did not produce {library}")
    return library


def compile_java(args, build_dir: Path, work: Path) -> Path:
    sdl_source = cmake_cache(build_dir, "SDL3_SOURCE_DIR")
    if not sdl_source:
        raise SystemExit("SDL3's source folder is not in the CMake cache")
    # SDL's Java half must come from the same SDL as libmain.so.
    sdl_java = Path(sdl_source) / "android-project/app/src/main/java"
    # recomp-ui's native launcher screens, then the app's own classes.
    sources = (sorted(sdl_java.rglob("*.java"))
               + sorted((ROOT / "recomp-ui/android/java").rglob("*.java"))
               + sorted((ROOT / "psxrecomp/runtime/android/java").rglob("*.java"))
               + sorted((ANDROID / "java").rglob("*.java")))
    classes = work / "classes"
    shutil.rmtree(classes, ignore_errors=True)
    classes.mkdir(parents=True)
    android_jar = args.platform / "android.jar"
    run([args.javac, "-encoding", "UTF-8", "-source", "11", "-target", "11",
         "-nowarn", "-Xlint:-options", "-classpath", android_jar, "-d", classes, *sources])
    dex = work / "dex"
    shutil.rmtree(dex, ignore_errors=True)
    dex.mkdir()
    run([tool(args.build_tools, "d8"), "--release", "--min-api", MIN_SDK,
         "--lib", android_jar, "--output", dex, *sorted(classes.rglob("*.class"))])
    return dex / "classes.dex"


def stage_data(args, build_dir: Path, work: Path) -> Path:
    assets = work / "assets"
    shutil.rmtree(assets, ignore_errors=True)
    data = assets / "data"
    data.mkdir(parents=True)
    for name in DATA_DIRS:
        if (build_dir / name).is_dir():
            shutil.copytree(build_dir / name, data / name)
    for name in DATA_FILES:
        if name == "game.toml" and args.no_game_config:
            continue
        for source in (build_dir / name, ROOT / name):
            if source.is_file():
                shutil.copy2(source, data / name)
                break
    # Data from outside the build (the disc, the TTT1 import), as SOURCE=DEST.
    packed = args.disc_format == "packed"
    for spec in args.data:
        source, _, dest = spec.partition("=")
        source = Path(source).expanduser()
        target = data / (dest or source.name)
        relative = target.relative_to(data)
        if source.is_dir():
            def tracks(folder, names, base=source, under=relative):
                where = under / Path(folder).relative_to(base)
                return [n for n in names if is_track(where / n) and (Path(folder) / n).is_file()]
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=tracks)
            for track in sorted(source.rglob("*")):
                if track.is_file() and is_track(relative / track.relative_to(source)):
                    stage_track(track, target / track.relative_to(source), packed)
        elif source.is_file():
            if is_track(relative):
                stage_track(source, target, packed)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        else:
            raise SystemExit(f"--data: {source} not found")
    # Data that only fills in what the build did not stage (--data-missing):
    # the PC build's mods/ holds what the setup made beside CMake (the TTT1
    # guests, the difficulty levels), and also older copies of what this
    # build just staged from the current sources, which must win.
    for spec in args.data_missing:
        source, _, dest = spec.partition("=")
        source = Path(source).expanduser()
        target = data / (dest or source.name)
        if not source.is_dir():
            raise SystemExit(f"--data-missing: {source} is not a folder")
        added = 0
        for path in sorted(source.rglob("*")):
            out = target / path.relative_to(source)
            if path.is_file() and not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, out)
                added += 1
        log(f"--data-missing {source.name}: {added} file(s) the build did not stage")
    if not args.keep_rgba and (data / "mods").is_dir():
        ship_png_textures(data / "mods")
    if not args.keep_mod_sources and (data / "mods").is_dir():
        unread = [p for p in (data / "mods").rglob("*") if p.is_file() and unread_mod_file(p)]
        size = sum(p.stat().st_size for p in unread)
        for path in unread:
            path.unlink()
        if unread:
            log(f"Left out {len(unread)} mod files the game does not read ({size / 1e6:.1f} MB)")
    if args.disc_sector_log:
        # android_main.c: the game then maps the disc sectors it reads.
        (data / "disc-sector-log.on").write_text("1\n", encoding="utf-8")
    if args.launch_args:
        # GameActivity passes these to the runtime, one per line.
        (data / "launch-args.txt").write_text(
            "\n".join(shlex.split(args.launch_args)) + "\n", encoding="utf-8")
    return assets


def compile_icon(args, work: Path) -> Path:
    """The icon PNG, scaled to each density's mipmap and compiled by aapt2."""
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("--icon needs Pillow (python -m pip install pillow)")
    res = work / "res"
    shutil.rmtree(res, ignore_errors=True)
    with Image.open(args.icon) as source:
        source = source.convert("RGBA")
        for density, size in MIPMAPS.items():
            folder = res / f"mipmap-{density}"
            folder.mkdir(parents=True)
            source.resize((size, size), Image.LANCZOS).save(folder / "ic_launcher.png")
            # The adaptive icon's foreground: 108/48 of the legacy size.
            full = size * 108 // 48
            art = round(full * ICON_ART)
            foreground = Image.new("RGBA", (full, full), (0, 0, 0, 0))
            foreground.paste(source.resize((art, art), Image.LANCZOS),
                             ((full - art) // 2, (full - art) // 2))
            foreground.save(folder / "ic_launcher_foreground.png")
    (res / "mipmap-anydpi-v26").mkdir()
    (res / "mipmap-anydpi-v26/ic_launcher.xml").write_text(ADAPTIVE_ICON, encoding="utf-8")
    (res / "values").mkdir()
    (res / "values/ic_launcher_colors.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">{ICON_BACKGROUND}</color>\n</resources>\n',
        encoding="utf-8")
    compiled = work / "res.zip"
    compiled.unlink(missing_ok=True)
    run([tool(args.build_tools, "aapt2"), "compile", "--dir", res, "-o", compiled])
    return compiled


def manifest(args, work: Path) -> Path:
    """The manifest; without --icon, without its icon (no resource to point to)."""
    source = ANDROID / "AndroidManifest.xml"
    if args.icon:
        return source
    text = source.read_text(encoding="utf-8")
    if ICON_ATTRIBUTE not in text:
        return source
    stripped = work / "AndroidManifest.xml"
    stripped.write_text(text.replace(ICON_ATTRIBUTE, ""), encoding="utf-8")
    return stripped


def link_apk(args, assets: Path, work: Path) -> Path:
    unsigned = work / "unsigned.apk"
    command = [tool(args.build_tools, "aapt2"), "link", "-o", unsigned,
               "--manifest", manifest(args, work),
               "-I", args.platform / "android.jar",
               "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
               "--version-code", args.version_code, "--version-name", args.version_name,
               "-A", assets]
    if args.icon:
        # -R is an overlay: --auto-add-overlay lets it add the icon's new resources.
        command += ["-R", compile_icon(args, work), "--auto-add-overlay"]
    for extension in NO_COMPRESS:
        command += ["-0", extension]
    run(command)
    return unsigned


def add_code(unsigned: Path, dex: Path, library: Path, strip: Path, work: Path) -> None:
    stripped = work / "libmain.so"
    run([strip, "--strip-unneeded", "-o", stripped, library])
    with zipfile.ZipFile(unsigned, "a") as apk:
        apk.write(dex, "classes.dex", compress_type=zipfile.ZIP_DEFLATED)
        # Stored, so Android maps it straight from the APK
        # (extractNativeLibs=false); zipalign -P 16 aligns it to 16 KB pages.
        apk.write(stripped, f"lib/{ABI}/libmain.so", compress_type=zipfile.ZIP_STORED)


# The signing password reaches keytool and apksigner through this variable,
# not their command lines, which other users of the computer can see (ps).
PASSWORD_VARIABLE = "T3E_KEYSTORE_PASSWORD"


def private(path: Path) -> None:
    """Only the player can read the key and its password (no effect on Windows)."""
    if os.name != "nt":
        os.chmod(path, 0o600)


def signing_key(args) -> tuple[Path, str]:
    keystore = args.keystore
    password_file = keystore.with_suffix(".password")
    if keystore.is_file() and password_file.is_file():
        private(keystore)
        private(password_file)
        return keystore, password_file.read_text(encoding="utf-8").strip()
    keystore.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    run([args.keytool, "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12",
         "-storepass:env", PASSWORD_VARIABLE, "-alias", "tekken3expanded", "-keyalg", "RSA",
         "-keysize", "4096", "-validity", "36500", "-dname", "CN=Tekken 3 Expanded"],
        stdout=subprocess.DEVNULL, env={**os.environ, PASSWORD_VARIABLE: password})
    private(keystore)
    with os.fdopen(os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
                   "w", encoding="utf-8") as out:
        out.write(password)
    private(password_file)
    log(f"New signing key: {keystore} (keep it for updates)")
    return keystore, password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--platform", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build-android")
    parser.add_argument("--out", type=Path, default=ROOT / "Tekken3Expanded.apk")
    parser.add_argument("--keystore", type=Path, default=ROOT / ".setup/android/release.keystore")
    parser.add_argument("--version-code", default="1")
    parser.add_argument("--version-name", default=(ROOT / "VERSION").read_text().strip()
                        if (ROOT / "VERSION").is_file() else "dev")
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--ninja", default=None)
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--keytool", default="keytool")
    parser.add_argument("-D", dest="define", action="append", default=[],
                        help="extra CMake option for the native build")
    parser.add_argument("--allow-debug-features", action="store_true",
                        help="let -D turn on netplay or the debug tools (a test APK only)")
    parser.add_argument("--skip-native", action="store_true",
                        help="reuse libmain.so already in --build-dir")
    parser.add_argument("--launch-args", default="",
                        help="arguments the app passes to the runtime (tests), "
                             "e.g. \"--no-launcher --bios bios/openbios.bin\"")
    parser.add_argument("--data", action="append", default=[], metavar="SOURCE=DEST",
                        help="add a file or folder to the game data (DEST is relative "
                             "to the data folder), e.g. disc=disc")
    parser.add_argument("--data-missing", action="append", default=[], metavar="SOURCE=DEST",
                        help="like --data for a folder, but only the files the build did "
                             "not stage itself (the PC build's mods: what the setup made)")
    parser.add_argument("--icon", type=Path,
                        help="the app's icon: a square PNG (512 px or more), "
                             "scaled to Android's mipmap sizes")
    parser.add_argument("--disc-format", choices=("packed", "bin"), default="packed",
                        help="the disc's tracks in the APK: packed losslessly (disc_pack.py, "
                             "the default) or plain .bin as on PC")
    parser.add_argument("--keep-rgba", action="store_true",
                        help="ship the mods' textures as raw .rgba instead of PNG")
    parser.add_argument("--keep-mod-sources", action="store_true",
                        help="keep the texture packs' PNG sources and notes, which the game "
                             "does not read (see unread_mod_file)")
    parser.add_argument("--disc-sector-log", action="store_true",
                        help="the game records the disc sectors it reads in its external "
                             "files folder (disc-sectors.bin, see tools/disc_usage.py)")
    parser.add_argument("--keep-work", action="store_true",
                        help="keep the staged data and the unsigned and aligned APKs "
                             "in <build-dir>/apk (deleted by default)")
    parser.add_argument("--no-game-config", action="store_true",
                        help="leave game.toml out (a BIOS-only test needs no disc)")
    args = parser.parse_args()

    build_dir = args.build_dir.resolve()
    check_paths_for_cmd(ROOT, build_dir, args.build_tools, args.out.resolve(),
                        args.keystore.resolve())
    work = build_dir / "apk"
    work.mkdir(parents=True, exist_ok=True)

    library = build_dir / "libmain.so" if args.skip_native else build_native(args, build_dir)
    dex = compile_java(args, build_dir, work)
    assets = stage_data(args, build_dir, work)
    unsigned = link_apk(args, assets, work)
    strip = tool(args.ndk / "toolchains/llvm/prebuilt" / ndk_host_tag() / "bin", "llvm-strip")
    add_code(unsigned, dex, library, strip, work)

    aligned = work / "aligned.apk"
    run([tool(args.build_tools, "zipalign"), "-P", "16", "-f", "4", unsigned, aligned])
    # Each of these is about as big as the APK (the disc included): about
    # 3 GB in all, not needed once the APK is made.
    if not args.keep_work:
        unsigned.unlink()
        shutil.rmtree(assets, ignore_errors=True)
    keystore, password = signing_key(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run([tool(args.build_tools, "apksigner"), "sign", "--ks", keystore,
         "--ks-pass", f"env:{PASSWORD_VARIABLE}", "--min-sdk-version", MIN_SDK,
         "--out", args.out, aligned], env={**os.environ, PASSWORD_VARIABLE: password})
    run([tool(args.build_tools, "apksigner"), "verify", args.out])
    if not args.keep_work:
        aligned.unlink()
    log(f"APK ready: {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
