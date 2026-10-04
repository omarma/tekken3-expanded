"""Checks of make_apk.py without the network or the game: the pinned
archives per host, their checks, unpacking (Windows' zipfile path, the JDK's
tar.gz), the Java fallback and the icon.

  python3 tools/android/test_make_apk.py

With ANDROID_WINDOWS_ZIPS=<folder holding Google's -windows archives>, also
unpacks the real ones as Windows would."""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import struct
import re
import sys
import tarfile
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_apk  # noqa: E402
import make_apk  # noqa: E402


def zip_bytes(files: dict[str, bytes]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return data.getvalue()


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def as_windows():
    """Patches make_apk to take this computer for Windows."""
    return (patch.object(make_apk, "WINDOWS", True), patch.object(make_apk.sys, "platform", "win32"))


class MakeApkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tools = Path(self.temp.name) / "android"
        patcher = patch.object(make_apk, "TOOLS", self.tools)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_every_host_pins_the_same_tools(self):
        folders = {name: folder for name, (_, _, folder) in make_apk.PINS["linux"].items()}
        for host, pins in make_apk.PINS.items():
            self.assertEqual({n: f for n, (_, _, f) in pins.items()}, folders, host)
            for archive, sha1, _ in pins.values():
                self.assertRegex(sha1, r"^[0-9a-f]{40}$")
                if archive.startswith("platform-35"):
                    continue    # the same for every host
                suffix = {"darwin": ("darwin", "macosx"), "linux": ("linux",), "windows": ("windows", "win")}[host]
                self.assertRegex(archive, r"[-_](%s)\.zip$" % "|".join(suffix), archive)

    def test_host_and_jdk_selection(self):
        with as_windows()[0], as_windows()[1]:
            self.assertEqual(make_apk.host(), "windows")
            self.assertEqual(make_apk.exe(Path("x/bin/javac")), Path("x/bin/javac.exe"))
        for machine, expected in (("AMD64", "x64"), ("x86_64", "x64"), ("arm64", "aarch64")):
            with patch.object(make_apk.platform, "machine", return_value=machine):
                self.assertEqual(make_apk.cpu(), expected)
        for (host, cpu), (archive, sha256) in make_apk.JDKS.items():
            self.assertRegex(sha256, r"^[0-9a-f]{64}$")
            self.assertIn({"windows": "windows", "darwin": "mac", "linux": "linux"}[host], archive)
            self.assertIn(cpu, archive)
            self.assertTrue(archive.endswith(".zip" if host == "windows" else ".tar.gz"))
            self.assertIn(make_apk.JDK_RELEASE.split("+")[0].removeprefix("jdk-"), archive)
        self.assertIn("%2B", make_apk.JDK_URL)

    def test_download_checks_the_digest_and_reuses_a_good_file(self):
        data = b"android tool"
        good = hashlib.sha1(data).hexdigest()
        url = make_apk.BASE_URL + "tool.zip"
        with patch.object(make_apk.urllib.request, "urlopen", return_value=Response(data)) as network:
            path = make_apk.download("tool", url, good, say=lambda *a: None)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(make_apk.download("tool", url, good, say=lambda *a: None), path)
            network.assert_called_once()
        with patch.object(make_apk.urllib.request, "urlopen", return_value=Response(b"damaged")):
            with self.assertRaises(make_apk.Stop):
                make_apk.download("other", make_apk.BASE_URL + "other.zip", good, say=lambda *a: None)
        self.assertEqual(list((self.tools / "downloads").glob("*.partial")), [])
        with patch.object(make_apk.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(make_apk.Stop):
                make_apk.download("other", make_apk.BASE_URL + "other.zip", good, say=lambda *a: None)

    def test_download_checks_the_sha256_too(self):
        data = b"android tool"
        sha1 = hashlib.sha1(data).hexdigest()
        url = make_apk.BASE_URL + "pinned.zip"
        with patch.dict(make_apk.SHA256, {"pinned.zip": hashlib.sha256(b"other").hexdigest()}), \
                patch.object(make_apk.urllib.request, "urlopen", return_value=Response(data)):
            with self.assertRaises(make_apk.Stop):   # the SHA-1 matches, the SHA-256 does not
                make_apk.download("tool", url, sha1, say=lambda *a: None)
        with patch.dict(make_apk.SHA256, {"pinned.zip": hashlib.sha256(data).hexdigest()}), \
                patch.object(make_apk.urllib.request, "urlopen", return_value=Response(data)):
            self.assertEqual(make_apk.download("tool", url, sha1, say=lambda *a: None).read_bytes(), data)

    def test_every_pinned_archive_has_a_sha256(self):
        for host, pins in make_apk.PINS.items():
            for name, (archive, _, _) in pins.items():
                with self.subTest(host=host, name=name):
                    self.assertRegex(make_apk.SHA256.get(archive, ""), "^[0-9a-f]{64}$")

    def test_native_build_keeps_netplay_and_debug_tools_out(self):
        defines = build_apk.native_defines(["PSX_DEBUG_TOOLS=OFF", "FOO=1"], False)
        for released in build_apk.RELEASE_DEFINES:   # every configure, over the CMake cache
            self.assertIn(released, defines)
        self.assertEqual(defines[-2:], ["PSX_DEBUG_TOOLS=OFF", "FOO=1"])
        for bad in ("PSX_DEBUG_TOOLS=ON", "PSX_NETPLAY:BOOL=1", "PSX_DEBUG_SERVER_LITE=yes",
                    "CMAKE_BUILD_TYPE=Debug"):
            with self.subTest(define=bad), self.assertRaises(SystemExit):
                build_apk.native_defines([bad], False)
        self.assertEqual(build_apk.native_defines(["PSX_DEBUG_TOOLS=ON"], True), ["PSX_DEBUG_TOOLS=ON"])

    def test_windows_refuses_paths_cmd_would_misread(self):
        for path in (r"C:\Jeux\Tom&Jerry", r"C:\100%\t3", "C:\\a^b", 'C:\\a"b'):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                build_apk.check_paths_for_cmd("C:\\ok", path, windows=True)
        build_apk.check_paths_for_cmd(r"C:\Users\Omar Amer\Tekken 3 (USA)", windows=True)
        build_apk.check_paths_for_cmd("/home/a&b", windows=False)

    def test_download_names_the_file_without_url_quoting(self):
        data = b"jdk"
        with patch.object(make_apk.urllib.request, "urlopen", return_value=Response(data)):
            path = make_apk.download("Java", "https://example.invalid/jdk-21%2B1/a%2Bb.zip",
                                     hashlib.sha256(data).hexdigest(), "sha256", say=lambda *a: None)
        self.assertEqual(path.name, "a+b.zip")

    def test_windows_tools_unpack_with_zipfile(self):
        archives = {}
        for name, (archive, _, folder) in make_apk.PINS["windows"].items():
            data = zip_bytes({f"{folder}/": b"", f"{folder}/bin/{name}.exe": name.encode()})
            archives[archive] = data
        pins = {"windows": {name: (archive, hashlib.sha1(archives[archive]).hexdigest(), folder)
                            for name, (archive, _, folder) in make_apk.PINS["windows"].items()}}
        fetched = []

        def fake_download(name, url, expected, algorithm="sha1", say=None):
            archive = url.rsplit("/", 1)[1]
            fetched.append(archive)
            path = self.tools / "downloads" / archive
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archives[archive])
            return path

        windows, platform_ = as_windows()
        with windows, platform_, patch.dict(make_apk.PINS, pins), \
                patch.object(make_apk, "download", side_effect=fake_download), \
                patch.object(make_apk.subprocess, "run", side_effect=AssertionError("no unzip on Windows")):
            folders = make_apk.tool_folders(say=lambda *a: None)
            self.assertEqual(sorted(fetched), sorted(archives))
            for name, path in folders.items():
                self.assertEqual((path / "bin" / f"{name}.exe").read_bytes(), name.encode())
            self.assertTrue(make_apk.tools_ready())
            fetched.clear()
            make_apk.tool_folders(say=lambda *a: None)   # unpacked: nothing to do
            self.assertEqual(fetched, [])

    def test_unsafe_zip_is_refused_before_writing(self):
        for name in ("../escape", "/abs", "C:/escape", "a/../../escape", "file.txt:stream"):
            with self.subTest(name=name):
                archive = Path(self.temp.name) / "bad.zip"
                archive.write_bytes(zip_bytes({"good": b"1", name: b"2"}))
                with self.assertRaises(make_apk.Stop):
                    make_apk.extract_zip(archive, Path(self.temp.name) / "out")
                self.assertFalse((Path(self.temp.name) / "out/good").exists())

    def test_tar_without_data_filter_refuses_links_out_and_setuid(self):
        # Python before 3.10.12 / 3.11.4 has no filter="data": the fallback checks.
        old_python = types.SimpleNamespace(open=tarfile.open, TarError=tarfile.TarError)

        def tar_of(*members) -> Path:
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w:gz") as tar:
                for info, content in members:
                    tar.addfile(info, io.BytesIO(content) if content else None)
            path = Path(self.temp.name) / "t.tar.gz"
            path.write_bytes(data.getvalue())
            return path

        def entry(name, kind=tarfile.REGTYPE, link="", mode=0o644, content=b""):
            info = tarfile.TarInfo(name)
            info.type, info.linkname, info.mode, info.size = kind, link, mode, len(content)
            return info, content

        out = Path(self.temp.name) / "jdk"
        with patch.object(make_apk, "tarfile", old_python):
            for bad in (entry("a/link", tarfile.SYMTYPE, "../../outside"),
                        entry("a/abs", tarfile.SYMTYPE, "/etc/passwd"),
                        entry("a/hard", tarfile.LNKTYPE, "../x"),
                        entry("a/dev", tarfile.CHRTYPE)):
                with self.subTest(name=bad[0].name), self.assertRaises(make_apk.Stop):
                    make_apk.extract_tar(tar_of(bad), out)
            make_apk.extract_tar(tar_of(entry("bin/java", mode=0o6777, content=b"x"),
                                        entry("bin/javac", tarfile.SYMTYPE, "java")), out)
        if os.name != "nt":
            self.assertEqual((out / "bin/java").stat().st_mode & 0o7777, 0o755)
            self.assertEqual((out / "bin/javac").read_bytes(), b"x")

    def fake_jdk(self, host: str) -> bytes:
        home = f"{make_apk.JDK_RELEASE}/Contents/Home" if host == "darwin" else make_apk.JDK_RELEASE
        suffix = ".exe" if host == "windows" else ""
        files = {f"{home}/bin/javac{suffix}": b"javac", f"{home}/bin/keytool{suffix}": b"keytool"}
        if host == "windows":
            return zip_bytes(files)
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as tar:
            for name, content in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o755
                tar.addfile(info, io.BytesIO(content))
        return data.getvalue()

    def test_portable_jdk_per_host(self):
        for host, cpu in (("windows", "x64"), ("darwin", "aarch64"), ("darwin", "x64"), ("linux", "x64")):
            with self.subTest(host=host, cpu=cpu):
                data = self.fake_jdk(host)
                archive = make_apk.JDKS[(host, cpu)][0]
                jdks = {(host, cpu): (archive, hashlib.sha256(data).hexdigest())}
                calls = []

                def fake_download(name, url, expected, algorithm="sha1", say=None):
                    self.assertEqual(url, make_apk.JDK_URL + archive)
                    self.assertEqual(algorithm, "sha256")
                    calls.append(url)
                    path = self.tools / "downloads" / archive
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    return path

                with patch.object(make_apk, "WINDOWS", host == "windows"), \
                        patch.object(make_apk, "host", return_value=host), \
                        patch.object(make_apk, "cpu", return_value=cpu), \
                        patch.dict(make_apk.JDKS, jdks, clear=True), \
                        patch.object(make_apk, "download", side_effect=fake_download), \
                        patch.object(make_apk, "installed_jdk", return_value=None):
                    home = make_apk.java_home(say=lambda *a: None)
                    javac, keytool = make_apk.exe(home / "bin/javac"), make_apk.exe(home / "bin/keytool")
                    self.assertTrue(Path(javac).is_file(), javac)
                    self.assertTrue(Path(keytool).is_file(), keytool)
                    self.assertEqual(Path(javac).name, "javac.exe" if host == "windows" else "javac")
                    if host != "windows":
                        self.assertTrue(os.access(javac, os.X_OK))
                    make_apk.java_home(say=lambda *a: None)   # unpacked: no second download
                    self.assertEqual(len(calls), 1)
                import shutil
                shutil.rmtree(self.tools, ignore_errors=True)

    def test_installed_java_is_preferred(self):
        with patch.object(make_apk, "installed_jdk", return_value=Path("/opt/jdk")), \
                patch.object(make_apk, "portable_jdk", side_effect=AssertionError("no download")):
            self.assertEqual(make_apk.java_home(), Path("/opt/jdk"))
        env = make_apk.java_env(Path("/opt/jdk"), {"PATH": "/usr/bin"})
        self.assertEqual(env["JAVA_HOME"], str(Path("/opt/jdk")))
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(Path("/opt/jdk/bin")))

    def test_no_portable_java_for_unknown_hosts(self):
        with patch.object(make_apk, "host", return_value="linux"), patch.object(make_apk, "cpu", return_value="aarch64"):
            with self.assertRaises(make_apk.Stop):
                make_apk.portable_jdk(say=lambda *a: None)

    def test_windows_cmake_and_ninja_come_from_the_setup_tools(self):
        toolchain = Path("C:/Games/tekken3-expanded/.setup/tools/toolchain-1.0.10")
        with patch.object(make_apk, "WINDOWS", True):
            cmake, ninja = make_apk.build_tools(toolchain)
        self.assertEqual(Path(cmake), toolchain / "bin/cmake.exe")
        self.assertEqual(Path(ninja), toolchain / "bin/ninja.exe")

    def test_default_icon(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow")
        with patch.object(make_apk, "ICON", Path(self.temp.name) / "none.png"):
            path = make_apk.icon(say=lambda *a: None)
        with Image.open(path) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.getpixel((256, 60))[:3], (0x6E, 0x56, 0xCF))

    def test_install_hint_names_adb_and_the_apk(self):
        hint = make_apk.install_hint(Path("/x/Tekken3Expanded.apk"))
        self.assertIn("install -r", hint)
        self.assertIn("Tekken3Expanded.apk", hint)
        self.assertIn(str(make_apk.adb()), hint)

    def test_manifest_exposes_only_the_launcher_activity(self):
        import xml.dom.minidom
        manifest = xml.dom.minidom.parse(str(make_apk.ROOT / "android/AndroidManifest.xml"))
        exported = {a.getAttribute("android:name").rsplit(".", 1)[1]
                    for a in manifest.getElementsByTagName("activity")
                    if a.getAttribute("android:exported") != "false"}
        self.assertEqual(exported, {"PrepareActivity"})
        for tag in ("service", "receiver", "provider"):
            self.assertEqual(manifest.getElementsByTagName(tag), [], tag)
        permissions = {p.getAttribute("android:name")
                       for p in manifest.getElementsByTagName("uses-permission")}
        self.assertEqual(permissions, {"android.permission.VIBRATE"})   # no INTERNET
        application = manifest.getElementsByTagName("application")[0]
        self.assertEqual(application.getAttribute("android:allowBackup"), "false")
        self.assertEqual(application.getAttribute("android:debuggable"), "")

    def test_manifest_asks_for_the_icon(self):
        import xml.dom.minidom
        manifest = make_apk.ROOT / "android/AndroidManifest.xml"
        application = xml.dom.minidom.parse(str(manifest)).getElementsByTagName("application")[0]
        self.assertEqual(application.getAttribute("android:icon"), "@mipmap/ic_launcher")
        sys.path.insert(0, str(make_apk.ROOT / "tools/android"))
        import build_apk
        self.assertIn(build_apk.ICON_ATTRIBUTE, manifest.read_text(encoding="utf-8"))

    def test_apk_leaves_out_the_mod_files_the_game_does_not_read(self):
        skin = Path(self.temp.name) / "mods/nina-white-satin"
        skin.mkdir(parents=True)
        names = ("nina.rgba", "nina.png", "authored-atlas.png", "mapping.bin", "prompts.json",
                 "pack-report.json", "catalog.txt", "Jun-TTT1-arcade-P1.tim", "portrait.png")
        for name in names:
            (skin / name).write_bytes(b"x")
        left_out = {name for name in names if build_apk.unread_mod_file(skin / name)}
        self.assertEqual(left_out, {"nina.png", "authored-atlas.png", "prompts.json", "pack-report.json"})

    def stage(self, data: list[str], **options) -> Path:
        build = Path(self.temp.name) / "build"
        work = Path(self.temp.name) / "work"
        build.mkdir(exist_ok=True)
        args = argparse.Namespace(data=data, no_game_config=True, disc_sector_log=False,
                                  launch_args="", keep_mod_sources=False, keep_rgba=False,
                                  disc_format="packed", data_missing=[])
        for key, value in options.items():
            setattr(args, key, value)
        return build_apk.stage_data(args, build, work) / "data"

    def test_pc_mods_only_fill_in_what_the_build_did_not_stage(self):
        # After an update, the Android build stages the current mods; the PC
        # build's older copies must not replace them, only add what the setup
        # made beside CMake (the TTT1 guests).
        build = Path(self.temp.name) / "build"
        (build / "mods/catalog").mkdir(parents=True)
        (build / "mods/catalog/mod.toml").write_text("new\n")
        pc = Path(self.temp.name) / "pc-mods"
        (pc / "catalog").mkdir(parents=True)
        (pc / "catalog/mod.toml").write_text("old\n")
        (pc / "ttt1").mkdir()
        (pc / "ttt1/guests.txt").write_text("kuma\n")
        data = self.stage([], data_missing=[f"{pc}=mods"])
        self.assertEqual((data / "mods/catalog/mod.toml").read_text(), "new\n")
        self.assertEqual((data / "mods/ttt1/guests.txt").read_text(), "kuma\n")

    def test_apk_packs_the_disc_tracks_and_nothing_else(self):
        import disc_pack
        import synthetic_disc
        disc = Path(self.temp.name) / "disc"
        tracks = synthetic_disc.make(disc, 0.001)
        (disc / "SLUS_004.02").write_bytes(b"exe" * 5000)
        for disc_format in ("packed", "bin"):
            with self.subTest(disc_format=disc_format):
                data = self.stage([f"{disc}=disc"], disc_format=disc_format)
                for track in tracks:
                    staged = data / "disc" / track.name
                    if disc_format == "bin":
                        self.assertEqual(staged.read_bytes(), track.read_bytes())
                        continue
                    self.assertEqual(disc_pack.disc_pack_size(staged.read_bytes()[:16]),
                                     track.stat().st_size)
                    self.assertLess(staged.stat().st_size, track.stat().st_size)
                    reader = disc_pack.Reader(staged)
                    self.assertEqual(reader.read(0, reader.size), track.read_bytes())
                    reader.close()
                for name in ("SLUS_004.02", synthetic_disc.CUE_NAME):
                    self.assertEqual((data / "disc" / name).read_bytes(), (disc / name).read_bytes())
                shutil.rmtree(Path(self.temp.name) / "work")

    def test_apk_ships_textures_as_png_with_the_same_pixels(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is missing")
        mods = Path(self.temp.name) / "mods/skin"
        mods.mkdir(parents=True)
        image = Image.new("RGBA", (40, 30))
        image.putdata([(x * 6, y * 8, (x * y) % 256, 255 - x) for y in range(30) for x in range(40)])

        def rgba(img):
            return b"HDRGBA01" + struct.pack("<II", *img.size) + img.tobytes()

        image.save(mods / "same.png")
        (mods / "same.rgba").write_bytes(rgba(image))
        # A crop (as forest-hd's background): its PNG is the bigger source image.
        (mods / "cropped.rgba").write_bytes(rgba(image.crop((0, 5, 40, 25))))
        image.save(mods / "cropped.png")
        # Without a PNG at all.
        (mods / "alone.rgba").write_bytes(rgba(image.crop((3, 3, 13, 13))))
        data = self.stage([f"{mods.parent}=mods"])
        shipped = data / "mods/skin"
        self.assertEqual(sorted(p.name for p in shipped.iterdir()),
                         ["alone.png", "cropped.png", "same.png"])
        self.assertEqual((shipped / "same.png").read_bytes(), (mods / "same.png").read_bytes())
        for name in ("same", "cropped", "alone"):
            with Image.open(shipped / f"{name}.png") as png:
                self.assertEqual(rgba(png.convert("RGBA")), (mods / f"{name}.rgba").read_bytes())
        shutil.rmtree(Path(self.temp.name) / "work")
        kept = self.stage([f"{mods.parent}=mods"], keep_rgba=True) / "mods/skin"
        self.assertEqual(sorted(p.name for p in kept.iterdir()),
                         ["alone.rgba", "cropped.rgba", "same.rgba"])

    @unittest.skipUnless(shutil.which("keytool"), "no keytool on PATH")
    def test_signing_password_stays_off_command_lines_and_files_are_private(self):
        args = argparse.Namespace(keystore=Path(self.temp.name) / "keys/release.keystore",
                                  keytool=shutil.which("keytool"))
        commands = []
        real_run = build_apk.subprocess.run

        def spy(command, **kwargs):
            commands.append([str(part) for part in command])
            return real_run(command, **kwargs)

        with patch.object(build_apk.subprocess, "run", spy), patch.object(build_apk, "log"):
            keystore, password = build_apk.signing_key(args)
            self.assertEqual(build_apk.signing_key(args), (keystore, password))   # reused
        self.assertTrue(keystore.is_file())
        self.assertEqual(len(commands), 1)
        self.assertFalse(any(password in part for part in commands[0]), commands[0])
        if os.name != "nt":
            for path in (keystore, keystore.with_suffix(".password")):
                self.assertEqual(path.stat().st_mode & 0o077, 0, path)
        # The key opens with the password that was kept.
        real_run([args.keytool, "-list", "-keystore", str(keystore), "-storepass", password],
                 check=True, capture_output=True)

    @unittest.skipUnless(os.environ.get("ANDROID_WINDOWS_ZIPS"), "set ANDROID_WINDOWS_ZIPS to unpack Google's real archives")
    def test_real_windows_archives(self):
        folder = Path(os.environ["ANDROID_WINDOWS_ZIPS"])
        expected = {"ndk": ("build/cmake/android.toolchain.cmake", "shader-tools/windows-x86_64/glslc.exe",
                            "toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe"),
                    "build-tools": ("aapt2.exe", "d8.bat", "zipalign.exe", "apksigner.bat", "lib/d8.jar"),
                    "platform": ("android.jar",),
                    "platform-tools": ("adb.exe",)}
        for name, (archive, sha1, unpacked) in make_apk.PINS["windows"].items():
            with self.subTest(name=name):
                path = folder / archive
                self.assertEqual(make_apk.file_hash(path), sha1)
                make_apk.extract_zip(path, self.tools)
                for relative in expected[name]:
                    self.assertTrue((self.tools / unpacked / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
