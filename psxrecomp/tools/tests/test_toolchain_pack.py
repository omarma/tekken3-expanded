#!/usr/bin/env python3
"""toolchain_pack.py on a macOS-shaped pack and on quarantined packs.

The macOS cmake-clang-v1 pack ships cmake, ninja and ccache only (builds use
the Xcode clang): it must resolve and its ``latest`` pointer must survive the
heal. Dirs named ``<tag>.broken`` (quarantined by the setup host) must never
be picked as the pack.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "toolchain_pack", ROOT / "toolchain_pack.py")
TP = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(TP)


def make_pack(cache: Path, tag: str) -> Path:
    """<cache>/<tag>/bin/{cmake,ninja,ccache}: the macOS pack layout."""
    pack = cache / tag
    bin_dir = pack / "bin"
    bin_dir.mkdir(parents=True)
    for tool in ("cmake", "ninja", "ccache"):
        path = bin_dir / tool
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    (pack / "retcomm-toolchain.json").write_text(
        '{"id": "cmake-clang-v1", "version": "%s"}\n' % tag.split(".broken")[0])
    return pack


@unittest.skipIf(sys.platform == "win32", "fake packs are POSIX shell scripts")
class ToolchainPackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.cache = home / ".local" / "share" / "retcomm" / "toolchains" / TP.PACK_ID
        self.cache.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items()
               if k not in ("XDG_DATA_HOME", "RETCOMM_TOOLCHAIN_CACHE",
                            "RETCOMM_DATA_HOME", "RETCOMM_TOOLCHAIN_DIR",
                            "PSXRECOMP_TOOLCHAIN_DIR", "TOOLCHAIN_DIR",
                            "BPE_TOOLCHAIN_DIR", "RETCOMM_TOOLCHAIN_MIN_VERSION")}
        env["HOME"] = str(home)
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_macos_pack_resolves_and_keeps_latest(self):
        make_pack(self.cache, "1.0.14")
        (self.cache / "latest").symlink_to("1.0.14")
        TP.heal_broken_toolchain_pointers()
        self.assertTrue((self.cache / "latest").is_symlink())
        bin_dir = TP.resolve_toolchain_bin(None)
        self.assertIsNotNone(bin_dir)
        self.assertEqual(bin_dir.resolve(), (self.cache / "1.0.14" / "bin").resolve())
        self.assertTrue(TP.toolchain_bin_runs(bin_dir))

    def test_quarantined_pack_is_never_selected(self):
        make_pack(self.cache, "1.0.14.broken")
        make_pack(self.cache, "1.0.14.broken.broken")
        self.assertIsNone(TP.find_cached_pack())
        make_pack(self.cache, "1.0.12")
        found = TP.find_cached_pack()
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "1.0.12")


if __name__ == "__main__":
    unittest.main()
