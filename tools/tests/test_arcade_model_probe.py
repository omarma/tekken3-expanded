from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from tools import arcade_model_probe as probe
from tools.tests.test_model_map import make_3dmk_fixture


class RomLayoutTests(unittest.TestCase):
    def assemble(self, size, loads):
        target, used = bytearray(size), bytearray(size)
        for operation, offset, payload in loads:
            probe.place_rom(target, used, payload, {"operation": operation, "offset": offset})
        return bytes(target)

    def test_system12_byte_and_word_lane_wiring(self):
        self.assertEqual(self.assemble(8, [("ROM_LOAD16_BYTE", 0, b"ACEG"),
                                          ("ROM_LOAD16_BYTE", 1, b"BDFH")]), b"ABCDEFGH")
        self.assertEqual(self.assemble(8, [("ROM_LOAD32_WORD", 0, b"ABEF"),
                                          ("ROM_LOAD32_WORD", 2, b"CDGH")]), b"ABCDEFGH")
        self.assertEqual(self.assemble(8, [("ROM_LOAD32_BYTE", 0, b"AE"),
                                          ("ROM_LOAD32_BYTE", 1, b"BF"),
                                          ("ROM_LOAD32_BYTE", 2, b"CG"),
                                          ("ROM_LOAD32_BYTE", 3, b"DH")]), b"ABCDEFGH")
        self.assertEqual(self.assemble(4, [("ROM_LOAD16_WORD_SWAP", 0, b"BADC")]), b"ABCD")

    def test_overlap_bounds_and_partial_word_are_rejected(self):
        for size, loads in [(2, [("ROM_LOAD16_BYTE", 1, b"ab")]),
                            (8, [("ROM_LOAD32_WORD", 0, b"abc")]),
                            (4, [("ROM_LOAD", 0, b"abc"), ("ROM_LOAD", 2, b"z")])]:
            with self.subTest(loads=loads), self.assertRaises(probe.ProbeError):
                self.assemble(size, loads)

    def test_zip_verification_precedes_reconstruction(self):
        data = b"ABCD"
        spec = {"name": "chip.ic1", "size": 4, "offset": 0, "operation": "ROM_LOAD",
                "sha1": hashlib.sha1(data).hexdigest(), "crc32": f"{zlib.crc32(data):08x}"}
        definition = {"regions": [{"name": "test", "size": 4, "loads": [spec]}]}
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "rom.zip"
            with zipfile.ZipFile(archive, "w") as source:
                source.writestr("set/chip.ic1", data)
            regions, files = probe.reconstruct(archive, definition)
            self.assertEqual(regions["test"], data)
            self.assertEqual(len(files), 1)
            spec["sha1"] = "0" * 40
            with self.assertRaisesRegex(probe.ProbeError, "checksum"):
                probe.reconstruct(archive, definition)


class ModelProbeTests(unittest.TestCase):
    def test_live_identity_accepts_relocation_but_rejects_changed_geometry(self):
        raw = make_3dmk_fixture()
        ram = bytearray(64 + len(raw))
        ram[64:] = raw
        pointer_offsets = [16, 24, 28]
        for offset in pointer_offsets:
            value = struct.unpack_from("<I", raw, offset)[0]
            struct.pack_into("<I", ram, 64 + offset, value + 0x80000040)
        self.assertEqual(probe.identify_live_model(raw, bytes(ram), 64), pointer_offsets)
        ram[-1] ^= 1
        self.assertIsNone(probe.identify_live_model(raw, bytes(ram), 64))
        self.assertIsNone(probe.identify_live_model(raw, bytes(ram), -4))

    def test_embedded_model_uses_region_relative_bounds_without_inventing_eof(self):
        fixture = make_3dmk_fixture()
        report = probe.scan_3dmk(b"\0" * 32 + fixture + b"other data")
        self.assertEqual(report["magic_hits"], 1)
        self.assertEqual(report["candidates"][0]["region_offset"], 32)
        self.assertIsNone(report["candidates"][0]["record_size"])
        self.assertIsNone(report["candidates"][0]["semantic_name"])

    def test_truncated_and_out_of_bounds_signatures_are_not_models(self):
        malformed = bytearray(make_3dmk_fixture())
        struct.pack_into("<I", malformed, 24, 0xfffffff0)
        for data in (b"3DMK", make_3dmk_fixture()[:40], bytes(malformed)):
            with self.subTest(size=len(data)):
                self.assertEqual(probe.scan_3dmk(data)["candidates"], [])

    def test_directory_proves_model_size_and_rejects_fake_member_extent(self):
        model = make_3dmk_fixture()
        arc = struct.pack("<III", 1, 12, len(model)) + model
        region = b"\0" * 32 + arc + b"\0" * 32
        matches = probe.find_model_archives(region)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], 32)
        self.assertEqual(matches[0][1].members[0].size, len(model))
        malformed = bytearray(region)
        struct.pack_into("<I", malformed, 40, len(region) + 4)
        self.assertEqual(probe.find_model_archives(bytes(malformed)), [])


if __name__ == "__main__":
    unittest.main()
