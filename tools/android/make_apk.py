#!/usr/bin/env python3
"""Make the Android APK from a finished Tekken 3 Expanded setup (macOS, Windows, Linux).

Run it after Setup Tekken 3 has built the game on this computer: it reuses what
the setup made (the recompiled game code, the disc copy, the TTT1 import) and
builds the same game for Android phones (arm64):

  1. downloads the Android tools once into .setup/android (pinned versions,
     checked against Google's published SHA-1): the NDK, the SDK build tools,
     the Android 15 platform and platform-tools (adb); and a portable Java
     (Temurin 21, checked against its SHA-256) when no Java 11+ is installed;
  2. compiles the game with the NDK, with the options the setup uses;
  3. packs the game, its mods, the TTT1 characters and the disc into
     Tekken3Expanded.apk, signed with a key kept in .setup/android. The disc
     goes in losslessly packed (tools/android/disc_pack.py; --plain-disc for
     the plain .bin) and the mods' textures as PNG: the game reads the same
     bytes and pixels as on PC.

Keep .setup/android/release.keystore: Android only installs an update signed
with the same key.

Needs: cmake and ninja (the setup's own requirements on macOS and Linux; on
Windows, the tools the setup downloads). Double-click "Build Android APK.command"
on macOS, "Build Android APK.cmd" on Windows, or run the setup with --android.
The setup imports this file: build() is the whole job.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".setup/android"
BASE_URL = "https://dl.google.com/android/repository/"
WINDOWS = os.name == "nt"

# name -> (archive, sha1, folder it unpacks to), per host. The names and SHA-1
# come from Google's repository2-3.xml.
PINS = {
    "darwin": {
        "ndk": ("android-ndk-r28c-darwin.zip", "fc20a6bf15a30fb3428c9b60a7308793a362dc6d", "android-ndk-r28c"),
        "build-tools": ("build-tools_r35_macosx.zip", "93ab8ce91230e067b5add4bfa79919c52b27f072", "android-15"),
        "platform": ("platform-35_r02.zip", "0bb560a90a7a2cbd0dd8348224d518b638fe7949", "android-35"),
        "platform-tools": ("platform-tools_r37.0.1-darwin.zip", "6ae73f4de6452dc57e62ec02b68eed92a4c21661", "platform-tools"),
    },
    "linux": {
        "ndk": ("android-ndk-r28c-linux.zip", "a7b54a5de87fecd125a17d54f73c446199e72a64", "android-ndk-r28c"),
        "build-tools": ("build-tools_r35_linux.zip", "2cfaa0bbb2336e9ec18ed3ecea84fa2e2af607bc", "android-15"),
        "platform": ("platform-35_r02.zip", "0bb560a90a7a2cbd0dd8348224d518b638fe7949", "android-35"),
        "platform-tools": ("platform-tools_r37.0.1-linux.zip", "477254aa5f903c15cf51001717bdf347fb6b53e0", "platform-tools"),
    },
    "windows": {
        "ndk": ("android-ndk-r28c-windows.zip", "086bba43ff2f5eb0e387b15c8278bb4e0d89ba1d", "android-ndk-r28c"),
        "build-tools": ("build-tools_r35_windows.zip", "af059bb67cf7786f45ee0db85e2d24985df1b4b6", "android-15"),
        "platform": ("platform-35_r02.zip", "0bb560a90a7a2cbd0dd8348224d518b638fe7949", "android-35"),
        "platform-tools": ("platform-tools_r37.0.1-win.zip", "e03e78b1d80b396f1c3358e31251cb31740e1110", "platform-tools"),
    },
}

# Google publishes SHA-1 only; each archive is also checked against its
# SHA-256, computed from the same downloads (whose SHA-1 matched the pins).
SHA256 = {
    "android-ndk-r28c-darwin.zip":
        "0d4599e8bbf1a1668a0d51a541729b2246360f350018a2081d0b302dbb594f2a",
    "build-tools_r35_macosx.zip":
        "530cdbd1ec315e1477624d7ed2f0f2962108d69f36eddba5894cef9ea2cedb48",
    "platform-35_r02.zip":
        "0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0",
    "platform-tools_r37.0.1-darwin.zip":
        "ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d",
    "android-ndk-r28c-linux.zip":
        "dfb20d396df28ca02a8c708314b814a4d961dc9074f9a161932746f815aa552f",
    "build-tools_r35_linux.zip":
        "bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88",
    "platform-tools_r37.0.1-linux.zip":
        "d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1",
    "android-ndk-r28c-windows.zip":
        "6bec98ac2354d8a919760889a1a41d020132e5e8cfa1b1fe51610a72c36a466b",
    "build-tools_r35_windows.zip":
        "5753c679a1b90bcf6fbc9945a2ce39dfb9e74f1df0831a1e1866ae5b594326f0",
    "platform-tools_r37.0.1-win.zip":
        "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99",
}

# A portable Java for computers without one (Eclipse Temurin, a JDK: javac
# and keytool). (host, cpu) -> (archive, sha256), from api.adoptium.net.
JDK_RELEASE = "jdk-21.0.12.1+1"
JDK_URL = ("https://github.com/adoptium/temurin21-binaries/releases/download/"
           + urllib.parse.quote(JDK_RELEASE) + "/")
JDKS = {
    ("windows", "x64"): ("OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip",
                         "f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e"),
    ("darwin", "aarch64"): ("OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.12.1_1.tar.gz",
                            "3623232f33a9c3baadf304480b2535f9a3cba8a58d42ecbb438ba267315d9998"),
    ("darwin", "x64"): ("OpenJDK21U-jdk_x64_mac_hotspot_21.0.12.1_1.tar.gz",
                        "44db0f08196daf19a47f90d13388b0c943b67663cb537f998fe29e836fa842ce"),
    ("linux", "x64"): ("OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz",
                       "ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94"),
}

GAME_MARKER = ROOT / "generated/SLUS_004.02_dispatch.c"
DISC = ROOT / "disc"
CUE = DISC / "Tekken 3 (USA).cue"
PC_BUILD = ROOT / "build-release"
DEFAULT_OUT = ROOT / "Tekken3Expanded.apk"
ICON = ROOT / "packaging/icon.png"     # the game's icon (T3E)
ICON_FONT = ROOT / "recomp-ui/assets/common/fonts/LatoLatin-Bold.ttf"
ICON_COLOR = "#6E56CF"


class Stop(Exception):
    """A problem the player can fix; printed without a traceback."""


def report(message: str, detail: str = "") -> None:
    """Progress for a terminal. The setup passes its own (its window's status)."""
    print("  ".join(part for part in (message, detail) if part), flush=True)


def run_command(command: list, env: dict | None = None) -> None:
    """Runs a build step in this terminal. The setup passes its own (its log)."""
    try:
        subprocess.run([str(part) for part in command], check=True, env=env)
    except subprocess.CalledProcessError as error:
        raise Stop(f"The build stopped ({Path(str(command[0])).name} failed). "
                   "The messages above say why.") from error


def host() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    if WINDOWS:
        return "windows"
    raise Stop("Building the Android APK is supported on macOS, Windows and Linux.")


def cpu() -> str:
    machine = platform.machine().lower()
    return "aarch64" if machine in ("arm64", "aarch64") else "x64"


def exe(path: Path) -> Path:
    """A tool of a downloaded folder, with Windows' .exe."""
    return path.with_name(path.name + ".exe") if WINDOWS else path


def file_hash(path: Path, algorithm: str = "sha1") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(name: str, url: str, expected: str, algorithm: str = "sha1", say=report) -> Path:
    downloads = TOOLS / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = urllib.parse.unquote(url.rsplit("/", 1)[1])
    target = downloads / archive
    def good(path: Path) -> bool:
        return (file_hash(path, algorithm) == expected
                and (archive not in SHA256 or file_hash(path, "sha256") == SHA256[archive]))

    if target.is_file() and good(target):
        return target
    partial = target.with_name(archive + ".partial")
    say(f"Downloading the Android tools: {name}", archive)
    request = urllib.request.Request(url, headers={"User-Agent": "Tekken3-Expanded-APK"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done, last = 0, 0.0
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total and time.monotonic() - last > 2:
                    last = time.monotonic()
                    say(f"Downloading the Android tools: {name}",
                        f"{done * 100 // total}% of {total // (1 << 20)} MB")
    except OSError as error:
        raise Stop(f"The download of {archive} was interrupted ({error}). "
                   "Check your connection and run this again.") from error
    if not good(partial):
        partial.unlink()
        raise Stop(f"The download of {archive} is damaged. Run this again.")
    partial.replace(target)
    return target


def long_path(path: Path) -> str:
    """Windows: the NDK's deepest files pass 260 characters under a long folder."""
    text = str(path.resolve())
    if os.name == "nt" and not text.startswith("\\\\"):
        return "\\\\?\\" + text
    return text


def extract_zip(archive: Path, destination: Path) -> None:
    """Unpacks with Python alone (Windows has no unzip and needs no executable
    bits). Refuses entries that would land outside destination."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        for info in members:
            name = info.filename.replace("\\", "/")
            relative = Path(name)
            # ':' would be an NTFS alternate stream on Windows.
            if (PureWindowsPath(name).drive or relative.is_absolute() or ".." in relative.parts
                    or ":" in name or (info.external_attr >> 16) & 0o170000 == 0o120000
                    or destination not in (destination / relative).resolve().parents):
                raise Stop(f"{archive.name} holds an unsafe file ({name}). Delete it and run this again.")
        for info in members:
            target = destination / info.filename.replace("\\", "/")
            if info.is_dir():
                os.makedirs(long_path(target), exist_ok=True)
                continue
            os.makedirs(long_path(target.parent), exist_ok=True)
            with z.open(info) as source, open(long_path(target), "wb") as out:
                shutil.copyfileobj(source, out, 1 << 20)


def extract_tar(archive: Path, destination: Path) -> None:
    """A .tar.gz JDK (macOS, Linux), with its executable bits and links."""
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(destination, filter="data")
            else:   # Python before 3.10.12 / 3.11.4: what filter="data" refuses
                for member in tar.getmembers():
                    link = member.linkname if member.issym() or member.islnk() else ""
                    if (member.name.startswith("/") or ".." in Path(member.name).parts
                            or link.startswith("/") or ".." in Path(link).parts
                            or not (member.isfile() or member.isdir() or member.issym()
                                    or member.islnk())):
                        raise Stop(f"{archive.name} holds an unsafe file ({member.name}).")
                    member.mode &= 0o755   # no setuid, setgid, sticky or group/other write
                tar.extractall(destination)
    except tarfile.TarError as error:
        raise Stop(f"{archive.name} could not be unpacked ({error}). Delete it and run this again.") from error


def unpack(archive: Path, destination: Path) -> None:
    if archive.name.endswith(".tar.gz"):
        extract_tar(archive, destination)
    elif WINDOWS or not shutil.which("unzip"):
        extract_zip(archive, destination)
    else:
        # unzip keeps the executable bits and links the NDK needs (zipfile does not).
        subprocess.run(["unzip", "-q", "-o", str(archive), "-d", str(destination)], check=True)


def tools_ready() -> bool:
    return all((TOOLS / folder / ".sha1").is_file() for _, _, folder in PINS[host()].values())


def tool_folders(say=report) -> dict[str, Path]:
    """Downloads and unpacks the pinned Android tools once."""
    folders = {}
    for name, (archive, expected, folder) in PINS[host()].items():
        path = TOOLS / folder
        marker = path / ".sha1"
        if not (marker.is_file() and marker.read_text().strip() == expected):
            zipped = download(name, BASE_URL + archive, expected, say=say)
            say(f"Unpacking the Android tools: {name}", "This only happens the first time.")
            shutil.rmtree(long_path(path) if path.exists() else path, ignore_errors=True)
            unpack(zipped, TOOLS)
            if not path.is_dir():
                raise Stop(f"{archive} did not unpack to {folder}.")
            marker.write_text(expected)
        folders[name] = path
    return folders


def javac_version(javac: Path) -> int:
    try:
        out = subprocess.run([str(javac), "-version"], capture_output=True, text=True)
    except OSError:
        return 0
    # "javac 21.0.2" (other lines, e.g. "Picked up JAVA_TOOL_OPTIONS", may surround it).
    found = re.search(r"javac (\d+)", out.stdout + out.stderr) if out.returncode == 0 else None
    return int(found.group(1)) if found else 0


def installed_jdk() -> Path | None:
    """The home of an installed JDK 11 or later."""
    homes = []
    if os.environ.get("JAVA_HOME"):
        homes.append(Path(os.environ["JAVA_HOME"]))
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["/usr/libexec/java_home", "-v", "11+"], capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                homes.append(Path(out.stdout.strip()))
        except OSError:
            pass
        for prefix in ("/opt/homebrew/opt", "/usr/local/opt"):
            for jdk in ("openjdk", "openjdk@21", "openjdk@17"):
                homes.append(Path(prefix) / jdk / "libexec/openjdk.jdk/Contents/Home")
    javac = shutil.which("javac")
    # macOS' /usr/bin/javac only offers to install Java.
    if javac and not (sys.platform == "darwin" and javac == "/usr/bin/javac"):
        homes.append(Path(javac).resolve().parent.parent)
    for home in homes:
        if javac_version(exe(home / "bin/javac")) >= 11:
            return home
    return None


def jdk_home(folder: Path) -> Path | None:
    """Where bin/javac is in an unpacked JDK (macOS: Contents/Home)."""
    for home in (folder, folder / "Contents/Home"):
        if exe(home / "bin/javac").is_file():
            return home
    return None


def portable_jdk(say=report) -> Path:
    """Temurin 21, downloaded once into .setup/android."""
    pin = JDKS.get((host(), cpu()))
    if not pin:
        raise Stop("Java 11 or later is needed to build the APK: install a JDK "
                   "(sudo apt install openjdk-21-jdk-headless), then run this again.")
    archive, expected = pin
    folder = TOOLS / JDK_RELEASE
    marker = folder / ".sha256"
    if not (marker.is_file() and marker.read_text().strip() == expected and jdk_home(folder)):
        zipped = download("Java", JDK_URL + archive, expected, "sha256", say=say)
        say("Unpacking the Android tools: Java", "This only happens the first time.")
        shutil.rmtree(long_path(folder) if folder.exists() else folder, ignore_errors=True)
        unpack(zipped, TOOLS)
        if not jdk_home(folder):
            raise Stop(f"{archive} did not unpack to {JDK_RELEASE}.")
        marker.write_text(expected)
    return jdk_home(folder)


def java_home(say=report) -> Path:
    """A JDK 11 or later: the installed one, else a portable one."""
    return installed_jdk() or portable_jdk(say)


def java_env(home: Path, env: dict | None = None) -> dict:
    """The environment of the build: d8 and apksigner start the java of
    JAVA_HOME (Windows) or of the PATH (macOS, Linux)."""
    env = dict(os.environ if env is None else env)
    env["JAVA_HOME"] = str(home)
    env["PATH"] = str(home / "bin") + os.pathsep + env.get("PATH", "")
    return env


def build_tools(toolchain: Path | None) -> tuple[str, str]:
    """cmake and ninja: on Windows, from the tools the setup downloads."""
    if WINDOWS:
        if toolchain is None:
            sys.path.insert(0, str(ROOT / "launcher"))
            import setup_backend
            setup_backend.TEXT = True
            try:
                toolchain = setup_backend.tools()
            except setup_backend.SetupError as error:
                raise Stop(str(error)) from error
        return str(toolchain / "bin/cmake.exe"), str(toolchain / "bin/ninja.exe")
    found = [shutil.which(tool) for tool in ("cmake", "ninja")]
    for tool, path in zip(("cmake", "ninja"), found):
        if not path:
            raise Stop(f"{tool} is missing." + (" brew install cmake ninja" if sys.platform == "darwin" else ""))
    return found[0], found[1]


def make_icon(target: Path) -> Path | None:
    """The default icon: T3 on the launcher's purple. None without Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    size = 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, size - 16, size - 16), radius=96, fill="#17151F")
    draw.rounded_rectangle((40, 40, size - 40, size - 40), radius=76, fill=ICON_COLOR)
    font = ImageFont.truetype(str(ICON_FONT), 250) if ICON_FONT.is_file() else ImageFont.load_default()
    draw.text((size / 2, size / 2), "T3", fill="white", font=font, anchor="mm")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def icon(say=report) -> Path | None:
    if ICON.is_file():
        return ICON
    made = make_icon(TOOLS / "default-icon.png")
    if not made:
        say("No app icon", "Pillow is missing: the APK gets Android's default icon.")
    return made


def adb() -> Path:
    return exe(TOOLS / "platform-tools/adb")


def install_hint(apk: Path) -> str:
    return ("To install it, copy it to your phone and open it there (allow installing "
            "unknown apps when Android asks). Or connect the phone by USB, with USB "
            f"debugging on, and run:\n  \"{adb()}\" install -r \"{apk}\"")


def version_code() -> str:
    # Grows with time, so each APK installs over the previous one.
    return str(int(time.time() // 60) - 29_000_000)


def free_space_needed() -> int:
    # The build and the APK (about 1 GB each for the game), plus the tools once.
    return (3 << 30) + (0 if tools_ready() else 4 << 30)


def build(*, out: Path = DEFAULT_OUT, bios_test: bool = False, defines=(), say=report,
          run=run_command, toolchain: Path | None = None, env: dict | None = None,
          disc_sector_log: bool = False, plain_disc: bool = False) -> Path:
    """Downloads what is missing, builds and signs the APK; returns its path.
    say(message, detail) shows progress, run(command, env) runs a build step
    (and raises when it fails); env: the environment to start from. Raises
    Stop for what the player can fix. disc_sector_log: the game records the
    disc sectors it reads (docs/android-size.md). plain_disc: the disc's
    tracks go in as plain .bin instead of packed."""
    if not bios_test and (not GAME_MARKER.is_file() or not CUE.is_file()):
        raise Stop("Set up the game first: run Setup Tekken 3, then this.")
    TOOLS.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(TOOLS).free < free_space_needed():
        raise Stop(f"Building the APK needs about {free_space_needed() >> 30} GB of free space "
                   "in the tekken3-expanded folder.")
    cmake, ninja = build_tools(toolchain)
    jdk = java_home(say)
    tools = tool_folders(say)

    build_dir = ROOT / ("build-android-bios-test" if bios_test else "build-android")
    # The TTT1 guests: imported (workspace/, staged by the Android build
    # itself), or only in the PC build when the setup freed workspace/.
    ttt1 = ((PC_BUILD / "mods/ttt1").is_dir()
            or (ROOT / "workspace/ttt1-import/roster/guests.txt").is_file())
    command = [
        sys.executable, str(ROOT / "tools/android/build_apk.py"),
        "--ndk", str(tools["ndk"]),
        "--build-tools", str(tools["build-tools"]),
        "--platform", str(tools["platform"]),
        "--build-dir", str(build_dir),
        "--out", str(out),
        "--keystore", str(TOOLS / "release.keystore"),
        "--version-code", version_code(),
        "--javac", str(exe(jdk / "bin/javac")), "--keytool", str(exe(jdk / "bin/keytool")),
        "--cmake", cmake, "--ninja", ninja,
        "-DPython3_EXECUTABLE=" + sys.executable,
        "-DPSX_DEBUG_TOOLS=OFF", "-DPSX_DEBUG_SERVER_LITE=OFF", "-DPSX_NETPLAY=OFF",
        "-DPSXRECOMP_BIOS_STEMS=OpenBIOS", "-DTEKKEN3_BUILD_PC_PORT=OFF",
    ]
    app_icon = icon(say)
    if app_icon:
        command += ["--icon", str(app_icon)]
    if bios_test:
        command += ["-DPSXRECOMP_FORCE_SETUP_HOST=ON", "--no-game-config",
                    "--launch-args", "--no-launcher --bios bios/openbios.bin"]
    else:
        command += ["-DPSXRECOMP_FORCE_SETUP_HOST=OFF", "-DPSXRECOMP_REQUIRE_GAME_C=ON",
                    "-DTEKKEN3_TTT1_CHARACTERS=" + ("ON" if ttt1 else "OFF"),
                    "--data", f"{DISC}=disc"]
        # What the setup staged beside the PC game and CMake does not make
        # (the TTT1 characters, the difficulty levels). Only what the Android
        # build did not stage itself: the rest of the PC build's mods/ dates
        # from its last build, maybe before an update of the sources.
        # TTT Cinematics of an Android game set up alone (the PC game's are in
        # its mods/, below).
        cinematics = ROOT / "workspace/ttt-cinematics"
        if (cinematics / "cinematics.txt").is_file():
            command += ["--data", f"{cinematics}=mods/ttt-cinematics"]
        if (PC_BUILD / "mods").is_dir():
            command += ["--data-missing", f"{PC_BUILD / 'mods'}=mods"]
        # A phone GPU: render at the PS1's own resolution by default (the PC
        # config asks for 3x). The launcher's Display page can raise it.
        build_dir.mkdir(exist_ok=True)
        config = (ROOT / "game.toml").read_text(encoding="utf-8")
        config = re.sub(r"(?m)^supersampling\s*=\s*\d+", "supersampling = 1", config)
        (build_dir / "game.toml").write_text(config, encoding="utf-8")
    if disc_sector_log:
        command.append("--disc-sector-log")
    if plain_disc:
        command += ["--disc-format", "bin"]
    command += [f"-D{option}" for option in defines]
    say("Building the Android game", "The first build takes a while.")
    run(command, java_env(jdk, env))
    if not out.is_file():
        raise Stop(f"The build finished without making {out}.")
    return out


def up_to_date() -> None:
    """Never an APK of an older install (a git pull, a new release, a newer TTT1
    import): the setup's update first, with the files the game was set up with."""
    sys.path.insert(0, str(ROOT / "launcher"))
    import setup_backend
    setup_backend.TEXT = True
    if setup_backend.ready() or setup_backend.android_ready():
        return
    if not (setup_backend.STATE / "ready.json").is_file():
        raise Stop("Choose your game files first: run Build Android APK without options, then this.")
    report("The game is not up to date: updating it first, with the files you set it up with.")
    try:
        setup_backend.update_install()
    except setup_backend.SetupError as error:
        raise Stop(str(error)) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--install", action="store_true",
                        help="install it on the phone connected by USB (adb)")
    parser.add_argument("-D", dest="define", action="append", default=[],
                        help="extra CMake option for the Android build")
    parser.add_argument("--disc-sector-log", action="store_true",
                        help="the game records the disc sectors it reads (docs/android-size.md)")
    parser.add_argument("--plain-disc", action="store_true",
                        help="put the disc's tracks in as plain .bin (a bigger APK) "
                             "instead of losslessly packed")
    parser.add_argument("--bios-test", action="store_true",
                        help="no game needed: an APK that boots OpenBIOS (checks the tools)")
    args = parser.parse_args()

    try:
        if not args.bios_test:
            up_to_date()
        apk = build(out=args.out.resolve(), bios_test=args.bios_test, defines=args.define,
                    disc_sector_log=args.disc_sector_log, plain_disc=args.plain_disc)
        report(f"\nAPK ready: {apk} ({apk.stat().st_size / 1e6:.0f} MB)")
        if args.install:
            report("Installing on the phone (USB debugging must be on)...")
            run_command([adb(), "install", "-r", apk])
            report("Installed. Open Tekken 3 Expanded on the phone.")
        else:
            report(install_hint(apk))
        return 0
    except Stop as stop:
        report(f"\n{stop}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
