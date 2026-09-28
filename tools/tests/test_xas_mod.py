from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import xas_mod  # noqa: E402
import xas_tool  # noqa: E402


def bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def raw_header(index: int) -> bytearray:
    sector = bytearray(xas_tool.RAW_SECTOR_SIZE)
    sector[:12] = xas_tool.SYNC
    minute, remainder = divmod(index + 150, 75 * 60)
    second, frame = divmod(remainder, 75)
    sector[12:16] = bytes((bcd(minute), bcd(second), bcd(frame), 2))
    return sector


def finish_edc(sector: bytearray, form2: bool) -> bytes:
    if form2:
        struct.pack_into("<I", sector, 2348, xas_mod._calculate_edc(sector[16:2348]))
    else:
        struct.pack_into("<I", sector, 2072, xas_mod._calculate_edc(sector[16:2072]))
        prefix = b"\0\0\0\0" + bytes(sector[16:2076])
        p = xas_mod._ecc_block(
            prefix,
            major_count=86,
            minor_count=24,
            major_mult=2,
            minor_inc=86,
        )
        sector[2076:2248] = p
        q = xas_mod._ecc_block(
            prefix + p,
            major_count=52,
            minor_count=43,
            major_mult=86,
            minor_inc=88,
        )
        sector[2248:2352] = q
    return bytes(sector)


def xa_sector(index: int, channel: int, terminal: bool) -> bytes:
    sector = raw_header(index)
    submode = 0xE4 if terminal else 0x64
    sector[16:24] = bytes((1, channel, submode, 1)) * 2
    sector[24:2348] = bytes(((index * 31 + offset) & 0xFF for offset in range(2324)))
    return finish_edc(sector, True)


def form1_sector(index: int, submode: int = 0) -> bytes:
    sector = raw_header(index)
    sector[16:24] = bytes((1, 0, submode, 0)) * 2
    sector[24:2072] = bytes(((index * 17 + offset) & 0xFF for offset in range(2048)))
    return finish_edc(sector, False)


class SectorValidationTests(unittest.TestCase):
    def test_mode2_form1_edc_and_ecc_known_layout(self) -> None:
        sector = form1_sector(123)
        self.assertEqual(
            xas_mod._validate_sector_envelope(
                sector, path=Path("synthetic.raw"), index=0
            ),
            (1, 0, 0, 0),
        )
        bad_p = bytearray(sector)
        bad_p[2076] ^= 1
        with self.assertRaisesRegex(xas_mod.XasModError, "ECC P"):
            xas_mod._validate_sector_envelope(
                bytes(bad_p), path=Path("synthetic.raw"), index=0
            )
        bad_q = bytearray(sector)
        bad_q[2248] ^= 1
        with self.assertRaisesRegex(xas_mod.XasModError, "ECC Q"):
            xas_mod._validate_sector_envelope(
                bytes(bad_q), path=Path("synthetic.raw"), index=0
            )

    def test_exact_xa_layout_and_body_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "authored.raw"
            sectors = [xa_sector(10, 3, False), xa_sector(11, 3, True)]
            path.write_bytes(b"".join(sectors))
            output_path = Path(temporary) / "bodies.bin"
            with output_path.open("wb") as output:
                result = xas_mod.validate_encoded_stream(
                    path,
                    kind="xa",
                    sector_count=2,
                    channel=3,
                    output=output,
                )
            expected = b"".join(sector[16:] for sector in sectors)
            self.assertEqual(output_path.read_bytes(), expected)
            self.assertEqual(result.body_sha256, hashlib.sha256(expected).hexdigest())

    def test_xa_rejects_wrong_channel_terminal_and_edc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.raw"
            path.write_bytes(xa_sector(0, 2, False))
            with self.assertRaisesRegex(xas_mod.XasModError, "expected.*0xE4"):
                xas_mod.validate_encoded_stream(
                    path, kind="xa", sector_count=1, channel=2
                )
            path.write_bytes(xa_sector(0, 1, True))
            with self.assertRaisesRegex(xas_mod.XasModError, "expected 1/2"):
                xas_mod.validate_encoded_stream(
                    path, kind="xa", sector_count=1, channel=2
                )
            corrupted = bytearray(xa_sector(0, 2, True))
            corrupted[100] ^= 1
            path.write_bytes(corrupted)
            with self.assertRaisesRegex(xas_mod.XasModError, "EDC"):
                xas_mod.validate_encoded_stream(
                    path, kind="xa", sector_count=1, channel=2
                )

    def test_movie_rejects_terminal_xa_submode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad-movie.raw"
            path.write_bytes(xa_sector(0, 1, True))
            with self.assertRaisesRegex(xas_mod.XasModError, "shared stream terminator"):
                xas_mod.validate_encoded_stream(path, kind="movie", sector_count=1)


class BuilderUnitTests(unittest.TestCase):
    def test_selector_parser_sorts_and_rejects_duplicates(self) -> None:
        parsed = xas_mod._parse_replacements(
            ["3=three.raw", "1=one.raw"], count=4, label="XA"
        )
        self.assertEqual([item.id for item in parsed], [1, 3])
        with self.assertRaisesRegex(xas_mod.XasModError, "more than once"):
            xas_mod._parse_replacements(
                ["1=a.raw", "1=b.raw"], count=4, label="XA"
            )

    def test_manifest_is_default_off_strided_sector_body_overlay(self) -> None:
        item = xas_mod.PreparedReplacement(
            kind="xa",
            id=7,
            path=Path("authored.raw"),
            raw_sha256="1" * 64,
            payload_sha256="2" * 64,
            expected_sha256="3" * 64,
            first_absolute_lba=100,
            sector_stride=8,
            sector_count=9,
            channel=4,
        )
        manifest = xas_mod._render_manifest(
            package_id="example.xa",
            version="1.0.0",
            name="Example",
            author="Author",
            license_name="CC0-1.0",
            description="Authored media",
            replacements=[item],
        )
        self.assertIn("format_version = 6", manifest)
        self.assertIn("default_enabled = false", manifest)
        self.assertIn('target = "disc_raw"', manifest)
        self.assertIn(f"offset = {100 * 2352 + 16}", manifest)
        self.assertIn("chunk_size = 2336", manifest)
        self.assertIn(f"stride = {8 * 2352}", manifest)
        self.assertIn("chunk_count = 9", manifest)
        self.assertNotIn("authored.raw", manifest)


if __name__ == "__main__":
    unittest.main()
