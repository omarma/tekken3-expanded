from __future__ import annotations

import binascii
import io
import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools import tim_import, tim_tool


def make_block(payload: bytes, width_words: int, height: int) -> bytes:
    assert len(payload) == width_words * height * 2
    return struct.pack("<IHHHH", 12 + len(payload), 0, 0, width_words, height) + payload


def palette_words(count: int, overrides: dict[int, int]) -> bytes:
    values = [0] * count
    for index, value in overrides.items():
        values[index] = value
    return struct.pack(f"<{count}H", *values)


def make_4bpp(*, palettes: int = 1, duplicate_red: bool = False) -> bytes:
    overrides = {
        1: 0x001F,  # opaque red
        2: 0x03E0,  # opaque green
        3: 0x7C00,  # opaque blue
        4: 0x801F,  # STP red (preview alpha 128)
    }
    if duplicate_red:
        overrides[5] = 0x001F
    if palettes == 2:
        overrides[17] = 0x001F
    return (
        struct.pack("<II", 0x10, 0x08)
        + make_block(palette_words(16 * palettes, overrides), 16 * palettes, 1)
        + make_block(b"\x10\x32", 1, 1)
    )


def make_8bpp() -> bytes:
    return (
        struct.pack("<II", 0x10, 0x09)
        + make_block(
            palette_words(256, {1: 0x001F, 2: 0x03E0, 3: 0xFC00}),
            256,
            1,
        )
        + make_block(b"\x01\x02", 1, 1)
    )


def make_16bpp() -> bytes:
    return struct.pack("<II", 0x10, 0x02) + make_block(
        struct.pack("<HH", 0x001F, 0xFC00), 2, 1
    )


def make_24bpp_padded() -> bytes:
    return struct.pack("<II", 0x10, 0x03) + make_block(
        b"\x01\x02\x03\xEE", 2, 1
    )


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind)
    checksum = binascii.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    candidates = (
        (abs(estimate - left), left),
        (abs(estimate - above), above),
        (abs(estimate - upper_left), upper_left),
    )
    return min(enumerate(candidates), key=lambda pair: (pair[1][0], pair[0]))[1][1]


def filtered_png(width: int, height: int, rgba: bytes, filter_type: int) -> bytes:
    stride = width * 4
    raw = bytearray()
    previous = bytes(stride)
    for row in range(height):
        scanline = rgba[row * stride : (row + 1) * stride]
        filtered = bytearray(stride)
        for index, value in enumerate(scanline):
            left = scanline[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            else:
                predictor = paeth(left, above, upper_left)
            filtered[index] = (value - predictor) & 0xFF
        raw.append(filter_type)
        raw.extend(filtered)
        previous = scanline
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        tim_tool.PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )


class StrictPngTests(unittest.TestCase):
    def test_decodes_every_standard_filter(self) -> None:
        rgba = bytes(
            (
                1, 2, 3, 255, 20, 30, 40, 128,
                5, 6, 7, 255, 90, 100, 110, 0,
            )
        )
        for filter_type in range(5):
            with self.subTest(filter_type=filter_type):
                decoded = tim_import.decode_png_rgba(
                    filtered_png(2, 2, rgba, filter_type),
                    expected_width=2,
                    expected_height=2,
                )
                self.assertEqual(decoded, tim_import.RgbaPng(2, 2, rgba))

    def test_rejects_bad_crc_resizing_and_non_rgba(self) -> None:
        png = bytearray(tim_tool.encode_png_rgba(1, 1, bytes((1, 2, 3, 255))))
        png[29] ^= 1  # IHDR CRC byte.
        with self.assertRaisesRegex(tim_import.TimImportError, "bad CRC"):
            tim_import.decode_png_rgba(bytes(png))

        valid = tim_tool.encode_png_rgba(1, 1, bytes((1, 2, 3, 255)))
        with self.assertRaisesRegex(tim_import.TimImportError, "does not match"):
            tim_import.decode_png_rgba(valid, expected_width=2)

        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        rgb_png = (
            tim_tool.PNG_SIGNATURE
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
            + png_chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "8-bit RGBA"):
            tim_import.decode_png_rgba(rgb_png)

    def test_rejects_unknown_critical_and_trailing_data(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        critical = (
            tim_tool.PNG_SIGNATURE
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"ABCD", b"")
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
            + png_chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "critical"):
            tim_import.decode_png_rgba(critical)

        valid = tim_tool.encode_png_rgba(1, 1, bytes((0, 0, 0, 0)))
        with self.assertRaisesRegex(tim_import.TimImportError, "after IEND"):
            tim_import.decode_png_rgba(valid + b"x")

    def test_rejects_decompressed_data_beyond_declared_dimensions(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        oversized = (
            tim_tool.PNG_SIGNATURE
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00extra"))
            + png_chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "exceeds"):
            tim_import.decode_png_rgba(oversized)


class IndexedImportTests(unittest.TestCase):
    def test_preview_round_trip_preserves_duplicate_index_bytes(self) -> None:
        original = bytearray(make_4bpp(duplicate_red=True))
        tim = tim_tool.parse_tim(original)
        original[tim.image.data_offset] = 0x50  # Transparent, duplicate red index 5.
        original = bytes(original)
        preview = tim_import.RgbaPng(
            tim.pixel_width,
            tim.image.height,
            tim_tool.decode_rgba(original, tim),
        )
        result = tim_import.reencode_tim(original, preview)
        self.assertEqual(result.data, original)
        self.assertEqual(result.report["changed_pixels"], 0)

    def test_exact_4bpp_mapping_preserves_clut_and_layout(self) -> None:
        original = make_4bpp()
        tim = tim_tool.parse_tim(original)
        rgba = bytes(
            (
                0, 0, 255, 255,
                0, 255, 0, 255,
                255, 0, 0, 255,
                0, 0, 0, 0,
            )
        )
        result = tim_import.reencode_tim(original, tim_import.RgbaPng(4, 1, rgba))
        self.assertEqual(len(result.data), len(original))
        self.assertEqual(
            result.data[tim.clut.offset : tim.clut.end_offset],  # type: ignore[union-attr]
            original[tim.clut.offset : tim.clut.end_offset],  # type: ignore[union-attr]
        )
        self.assertEqual(result.data[tim.image.data_offset :], b"\x23\x01")
        self.assertEqual(tim_tool.decode_rgba(result.data, tim_tool.parse_tim(result.data)), rgba)

    def test_exact_8bpp_mapping(self) -> None:
        original = make_8bpp()
        rgba = bytes((0, 0, 255, 128, 255, 0, 0, 255))
        result = tim_import.reencode_tim(original, tim_import.RgbaPng(2, 1, rgba))
        tim = tim_tool.parse_tim(result.data)
        self.assertEqual(result.data[tim.image.data_offset :], b"\x03\x01")
        self.assertEqual(result.report["policy"], "exact_existing_palette")

    def test_exact_default_rejects_missing_color(self) -> None:
        original = make_4bpp()
        rgba = bytes((250, 3, 2, 255)) * 4
        with self.assertRaisesRegex(tim_import.TimImportError, "not present"):
            tim_import.reencode_tim(original, tim_import.RgbaPng(4, 1, rgba))

    def test_nearest_is_explicit_deterministic_and_stp_class_safe(self) -> None:
        original = make_4bpp()
        rgba = bytes(
            (
                250, 4, 3, 255,
                249, 1, 2, 128,
                2, 251, 4, 255,
                1, 2, 248, 255,
            )
        )
        result = tim_import.reencode_tim(
            original,
            tim_import.RgbaPng(4, 1, rgba),
            nearest_palette=True,
        )
        tim = tim_tool.parse_tim(result.data)
        self.assertEqual(result.data[tim.image.data_offset :], b"\x41\x32")
        self.assertEqual(
            result.report["policy"], "nearest_existing_palette_same_alpha"
        )

        no_stp = bytearray(original)
        parsed = tim_tool.parse_tim(no_stp)
        struct.pack_into("<H", no_stp, parsed.clut.data_offset + 4 * 2, 0)  # type: ignore[union-attr]
        with self.assertRaisesRegex(tim_import.TimImportError, "no matching"):
            tim_import.reencode_tim(
                bytes(no_stp),
                tim_import.RgbaPng(4, 1, bytes((1, 2, 3, 128)) * 4),
                nearest_palette=True,
            )

    def test_rejects_multiple_palettes_and_ambiguous_alpha(self) -> None:
        multi = make_4bpp(palettes=2)
        rgba = tim_import.RgbaPng(4, 1, bytes((0, 0, 0, 0)) * 4)
        with self.assertRaisesRegex(tim_import.TimImportError, "exactly one palette"):
            tim_import.reencode_tim(multi, rgba)

        ambiguous = tim_import.RgbaPng(4, 1, bytes((0, 0, 0, 64)) * 4)
        with self.assertRaisesRegex(tim_import.TimImportError, "ambiguous"):
            tim_import.reencode_tim(make_4bpp(), ambiguous, nearest_palette=True)

        hidden_rgb = tim_import.RgbaPng(4, 1, bytes((1, 0, 0, 0)) * 4)
        with self.assertRaisesRegex(tim_import.TimImportError, "retains nonzero RGB"):
            tim_import.reencode_tim(make_4bpp(), hidden_rgb, nearest_palette=True)


class DirectColorImportTests(unittest.TestCase):
    def test_16bpp_exact_and_explicit_quantization(self) -> None:
        original = make_16bpp()
        exact = tim_import.RgbaPng(
            2,
            1,
            bytes((0, 255, 0, 255, 0, 0, 255, 128)),
        )
        result = tim_import.reencode_tim(original, exact)
        tim = tim_tool.parse_tim(result.data)
        self.assertEqual(
            struct.unpack_from("<HH", result.data, tim.image.data_offset),
            (0x03E0, 0xFC00),
        )

        arbitrary = tim_import.RgbaPng(
            2,
            1,
            bytes((123, 77, 201, 255, 0, 0, 255, 128)),
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "5-bit"):
            tim_import.reencode_tim(original, arbitrary)
        quantized = tim_import.reencode_tim(
            original, arbitrary, quantize_16bpp=True
        )
        first_word = struct.unpack_from(
            "<H", quantized.data, tim_tool.parse_tim(quantized.data).image.data_offset
        )[0]
        expected = (
            (123 * 31 + 127) // 255
            | ((77 * 31 + 127) // 255) << 5
            | ((201 * 31 + 127) // 255) << 10
        )
        self.assertEqual(first_word, expected)

    def test_16bpp_rejects_opaque_black_and_ambiguous_alpha(self) -> None:
        original = make_16bpp()
        opaque_black = tim_import.RgbaPng(
            2, 1, bytes((0, 0, 0, 255, 0, 0, 255, 128))
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "opaque black"):
            tim_import.reencode_tim(original, opaque_black)

        ambiguous = tim_import.RgbaPng(
            2, 1, bytes((255, 0, 0, 64, 0, 0, 255, 128))
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "ambiguous"):
            tim_import.reencode_tim(original, ambiguous)

    def test_24bpp_preserves_row_padding_and_requires_opaque(self) -> None:
        original = make_24bpp_padded()
        result = tim_import.reencode_tim(
            original, tim_import.RgbaPng(1, 1, bytes((9, 8, 7, 255)))
        )
        tim = tim_tool.parse_tim(result.data)
        self.assertEqual(result.data[tim.image.data_offset :], b"\x09\x08\x07\xEE")
        self.assertEqual(len(result.data), len(original))
        with self.assertRaisesRegex(tim_import.TimImportError, "invalid for 24bpp"):
            tim_import.reencode_tim(
                original, tim_import.RgbaPng(1, 1, bytes((9, 8, 7, 128)))
            )

    def test_dimension_and_irrelevant_policy_flags_are_rejected(self) -> None:
        with self.assertRaisesRegex(tim_import.TimImportError, "dimensions"):
            tim_import.reencode_tim(
                make_16bpp(), tim_import.RgbaPng(1, 1, bytes((0, 0, 0, 0)))
            )
        preview = tim_import.RgbaPng(
            2, 1, tim_tool.decode_rgba(make_16bpp(), tim_tool.parse_tim(make_16bpp()))
        )
        with self.assertRaisesRegex(tim_import.TimImportError, "indexed"):
            tim_import.reencode_tim(make_16bpp(), preview, nearest_palette=True)

        with self.assertRaisesRegex(tim_import.TimImportError, "no trailing bytes"):
            tim_import.reencode_tim(make_16bpp() + b"x", preview)


class CliSafetyTests(unittest.TestCase):
    def test_cli_writes_exact_size_report_and_protects_both_inputs(self) -> None:
        original = make_4bpp()
        tim = tim_tool.parse_tim(original)
        png = tim_tool.encode_png_rgba(
            tim.pixel_width, tim.image.height, tim_tool.decode_rgba(original, tim)
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original_path = root / "original.tim"
            png_path = root / "edit.png"
            output_path = root / "replacement.tim"
            report_path = root / "report.json"
            original_path.write_bytes(original)
            png_path.write_bytes(png)
            with redirect_stdout(io.StringIO()):
                status = tim_import.main(
                    [
                        "--original", str(original_path),
                        "--png", str(png_path),
                        "--output", str(output_path),
                        "--report", str(report_path),
                    ]
                )
            self.assertEqual(status, 0)
            self.assertEqual(output_path.read_bytes(), original)
            report = json.loads(report_path.read_text("utf-8"))
            self.assertTrue(report["exact_size"])
            self.assertEqual(report["changed_pixels"], 0)
            self.assertEqual(
                report["artifact_status"],
                "private_local_derived_staging_artifact",
            )
            first_report = report_path.read_bytes()

            with redirect_stdout(io.StringIO()):
                status = tim_import.main(
                    [
                        "--original", str(original_path),
                        "--png", str(png_path),
                        "--output", str(output_path),
                        "--report", str(report_path),
                        "--force",
                    ]
                )
            self.assertEqual(status, 0)
            self.assertEqual(report_path.read_bytes(), first_report)

            with redirect_stderr(io.StringIO()):
                status = tim_import.main(
                    [
                        "--original", str(original_path),
                        "--png", str(png_path),
                        "--output", str(original_path),
                        "--force",
                    ]
                )
            self.assertEqual(status, 2)
            self.assertEqual(original_path.read_bytes(), original)

            with redirect_stderr(io.StringIO()):
                status = tim_import.main(
                    [
                        "--original", str(original_path),
                        "--png", str(png_path),
                        "--output", str(png_path),
                        "--force",
                    ]
                )
            self.assertEqual(status, 2)
            self.assertEqual(png_path.read_bytes(), png)


if __name__ == "__main__":
    unittest.main()
