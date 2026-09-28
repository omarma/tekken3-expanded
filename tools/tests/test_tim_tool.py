from __future__ import annotations

import hashlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr
from pathlib import Path

from tools import tim_tool


def make_block(
    payload: bytes,
    width_words: int,
    height: int,
    *,
    x: int = 0,
    y: int = 0,
) -> bytes:
    assert len(payload) == width_words * height * 2
    return struct.pack("<IHHHH", 12 + len(payload), x, y, width_words, height) + payload


def colors(count: int, overrides: dict[int, int] | None = None) -> bytes:
    values = [0] * count
    for index, value in (overrides or {}).items():
        values[index] = value
    return struct.pack(f"<{count}H", *values)


def make_4bpp(*, palettes: int = 1) -> bytes:
    palette = colors(
        16 * palettes,
        {
            1: 0x001F,
            2: 0x03E0,
            3: 0x7C00,
            **({17: 0x7C00} if palettes > 1 else {}),
        },
    )
    return (
        struct.pack("<II", 0x10, 0x08)
        + make_block(palette, 16 * palettes, 1, x=32, y=480)
        + make_block(b"\x10\x32", 1, 1, x=128, y=64)
    )


def make_8bpp() -> bytes:
    palette = colors(256, {1: 0x001F, 2: 0x83E0})
    return (
        struct.pack("<II", 0x10, 0x09)
        + make_block(palette, 256, 1, x=0, y=511)
        + make_block(b"\x01\x02", 1, 1)
    )


def make_16bpp() -> bytes:
    return struct.pack("<II", 0x10, 0x02) + make_block(
        struct.pack("<HH", 0x001F, 0xFC00), 2, 1
    )


def make_24bpp(*, padded: bool = False) -> bytes:
    if padded:
        return struct.pack("<II", 0x10, 0x03) + make_block(
            b"\x01\x02\x03\xEE", 2, 1
        )
    return struct.pack("<II", 0x10, 0x03) + make_block(
        b"\x01\x02\x03\xF0\xE0\xD0", 3, 1
    )


def parse_png(payload: bytes) -> tuple[int, int, bytes]:
    if not payload.startswith(tim_tool.PNG_SIGNATURE):
        raise AssertionError("missing PNG signature")
    position = len(tim_tool.PNG_SIGNATURE)
    width = height = 0
    compressed = bytearray()
    while position < len(payload):
        size = struct.unpack_from(">I", payload, position)[0]
        kind = payload[position + 4 : position + 8]
        data = payload[position + 8 : position + 8 + size]
        checksum = struct.unpack_from(">I", payload, position + 8 + size)[0]
        self_checksum = zlib.crc32(kind)
        self_checksum = zlib.crc32(data, self_checksum) & 0xFFFFFFFF
        if checksum != self_checksum:
            raise AssertionError("bad PNG CRC")
        if kind == b"IHDR":
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if (depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                raise AssertionError("unexpected PNG format")
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            break
        position += 12 + size
    return width, height, zlib.decompress(bytes(compressed))


class TimParsingTests(unittest.TestCase):
    def test_parse_and_decode_4bpp(self) -> None:
        data = make_4bpp()
        tim = tim_tool.parse_tim(data)
        self.assertEqual((tim.mode_name, tim.pixel_width, tim.image.height), ("4bpp", 4, 1))
        self.assertEqual(tim.palette_count, 1)
        self.assertEqual((tim.clut.x, tim.clut.y), (32, 480))  # type: ignore[union-attr]
        self.assertEqual(
            tim_tool.decode_rgba(data, tim),
            bytes(
                (
                    0,
                    0,
                    0,
                    0,
                    255,
                    0,
                    0,
                    255,
                    0,
                    255,
                    0,
                    255,
                    0,
                    0,
                    255,
                    255,
                )
            ),
        )

    def test_parse_and_decode_8bpp_with_stp_preview(self) -> None:
        data = make_8bpp()
        tim = tim_tool.parse_tim(data)
        self.assertEqual((tim.mode_name, tim.pixel_width, tim.palette_count), ("8bpp", 2, 1))
        self.assertEqual(
            tim_tool.decode_rgba(data, tim),
            bytes((255, 0, 0, 255, 0, 255, 0, 128)),
        )

    def test_parse_and_decode_16bpp(self) -> None:
        data = make_16bpp()
        tim = tim_tool.parse_tim(data)
        self.assertEqual((tim.mode_name, tim.pixel_width, tim.palette_count), ("16bpp", 2, 0))
        self.assertEqual(
            tim_tool.decode_rgba(data, tim),
            bytes((255, 0, 0, 255, 0, 0, 255, 128)),
        )

    def test_parse_and_decode_24bpp_rgb_order(self) -> None:
        data = make_24bpp()
        tim = tim_tool.parse_tim(data)
        self.assertEqual((tim.pixel_width, tim.row_padding_bytes), (2, 0))
        self.assertEqual(
            tim_tool.decode_rgba(data, tim),
            bytes((1, 2, 3, 255, 240, 224, 208, 255)),
        )

    def test_24bpp_reports_and_ignores_incomplete_trailing_pixel(self) -> None:
        data = make_24bpp(padded=True)
        tim = tim_tool.parse_tim(data)
        self.assertEqual((tim.pixel_width, tim.row_padding_bytes), (1, 1))
        self.assertEqual(tim_tool.decode_rgba(data, tim), bytes((1, 2, 3, 255)))

    def test_multiple_palettes_are_linear_and_selectable(self) -> None:
        data = make_4bpp(palettes=2)
        tim = tim_tool.parse_tim(data)
        self.assertEqual(tim.palette_count, 2)
        first_pixel = tim_tool.decode_rgba(data, tim, 1)[4:8]
        self.assertEqual(first_pixel, bytes((0, 0, 255, 255)))
        with self.assertRaisesRegex(tim_tool.TimToolError, "outside"):
            tim_tool.decode_rgba(data, tim, 2)

    def test_rejects_bad_flags_lengths_clut_and_vram_bounds(self) -> None:
        bad_flags = bytearray(make_16bpp())
        struct.pack_into("<I", bad_flags, 4, 0x12)
        with self.assertRaisesRegex(tim_tool.TimToolError, "flags"):
            tim_tool.parse_tim(bad_flags)

        bad_length = bytearray(make_16bpp())
        struct.pack_into("<I", bad_length, 8, 13)
        with self.assertRaisesRegex(tim_tool.TimToolError, "size"):
            tim_tool.parse_tim(bad_length)

        partial_clut = (
            struct.pack("<II", 0x10, 0x08)
            + make_block(colors(8), 8, 1)
            + make_block(b"\x00\x00", 1, 1)
        )
        with self.assertRaisesRegex(tim_tool.TimToolError, "whole"):
            tim_tool.parse_tim(partial_clut)

        outside = bytearray(make_16bpp())
        struct.pack_into("<H", outside, 12, 1023)
        with self.assertRaisesRegex(tim_tool.TimToolError, "outside"):
            tim_tool.parse_tim(outside)


class ScanningAndManifestTests(unittest.TestCase):
    def test_scans_unaligned_non_overlapping_images_and_skips_false_magic(self) -> None:
        first = make_4bpp()
        second = make_16bpp()
        data = b"abc" + first + b"\x10\x00\x00\x00invalid" + b"Z" + second
        images = tim_tool.scan_tims(data)
        self.assertEqual([image.offset for image in images], [3, 3 + len(first) + 12])
        self.assertEqual([image.mode_name for image in images], ["4bpp", "16bpp"])

    def test_inventory_has_stable_offsets_hashes_and_names(self) -> None:
        payload = b"prefix" + make_24bpp()
        images = tim_tool.scan_tims(payload)
        inventory = tim_tool.build_inventory(Path("record.bin"), payload, images)
        row = inventory["textures"][0]  # type: ignore[index]
        self.assertEqual(
            inventory["source"]["sha256"],  # type: ignore[index]
            hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(row["offset"], 6)
        self.assertEqual(row["suggested_tim_filename"], "tim_0000_off_00000006.tim")
        self.assertEqual(row["suggested_preview_filenames"], ["tim_0000_off_00000006.png"])
        self.assertEqual(row["image"]["section_offset"], 8)

    def test_id_parser_sorts_deduplicates_and_checks_bounds(self) -> None:
        self.assertEqual(tim_tool.parse_ids("3,1-3,0", 4), [0, 1, 2, 3])
        self.assertEqual(tim_tool.parse_ids(None, 2), [0, 1])
        with self.assertRaises(tim_tool.TimToolError):
            tim_tool.parse_ids("2", 2)
        with self.assertRaises(tim_tool.TimToolError):
            tim_tool.parse_ids("3-1", 4)


class PngAndExtractionTests(unittest.TestCase):
    def test_stdlib_png_is_deterministic_and_decodes(self) -> None:
        rgba = bytes((255, 0, 0, 255, 0, 255, 0, 128))
        first = tim_tool.encode_png_rgba(2, 1, rgba)
        second = tim_tool.encode_png_rgba(2, 1, rgba)
        self.assertEqual(first, second)
        width, height, scanlines = parse_png(first)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(scanlines, b"\x00" + rgba)

    def test_extract_preserves_raw_tim_and_defaults_to_first_palette(self) -> None:
        payload = b"P" + make_4bpp(palettes=2)
        images = tim_tool.scan_tims(payload)
        inventory = tim_tool.build_inventory(Path("record.bin"), payload, images)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "textures"
            written = tim_tool.extract_images(
                payload,
                images,
                inventory,
                [0],
                output,
                all_palettes=False,
                force=False,
            )
            self.assertEqual(len(written), 3)
            self.assertEqual(
                (output / "tim_0000_off_00000001.tim").read_bytes(),
                make_4bpp(palettes=2),
            )
            self.assertTrue((output / "tim_0000_off_00000001.p000.png").is_file())
            self.assertFalse((output / "tim_0000_off_00000001.p001.png").exists())
            manifest = json.loads((output / "inventory.json").read_text("utf-8"))
            self.assertEqual(
                manifest["textures"][0]["extracted"]["previews"],
                ["tim_0000_off_00000001.p000.png"],
            )
            with self.assertRaisesRegex(tim_tool.TimToolError, "overwrite"):
                tim_tool.extract_images(
                    payload,
                    images,
                    tim_tool.build_inventory(Path("record.bin"), payload, images),
                    [0],
                    output,
                    all_palettes=True,
                    force=False,
                )

    def test_extract_all_palettes(self) -> None:
        payload = make_4bpp(palettes=2)
        images = tim_tool.scan_tims(payload)
        inventory = tim_tool.build_inventory(Path("record.bin"), payload, images)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            tim_tool.extract_images(
                payload,
                images,
                inventory,
                [0],
                output,
                all_palettes=True,
                force=False,
            )
            self.assertTrue((output / "tim_0000_off_00000000.p000.png").is_file())
            self.assertTrue((output / "tim_0000_off_00000000.p001.png").is_file())

    def test_force_cannot_replace_the_input_source(self) -> None:
        payload = make_16bpp()
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "record.bin"
            source.write_bytes(payload)
            with redirect_stderr(io.StringIO()):
                result = tim_tool.main(
                    [
                        "inventory",
                        "--source",
                        str(source),
                        "--json",
                        str(source),
                        "--force",
                    ]
                )
            self.assertEqual(result, 2)
            self.assertEqual(source.read_bytes(), payload)

    def test_extract_protects_source_and_rejects_duplicate_outputs(self) -> None:
        payload = make_16bpp()
        images = tim_tool.scan_tims(payload)
        inventory = tim_tool.build_inventory(Path("inventory.json"), payload, images)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            source = output / "inventory.json"
            source.write_bytes(payload)
            with self.assertRaisesRegex(tim_tool.TimToolError, "input source"):
                tim_tool.extract_images(
                    payload,
                    images,
                    inventory,
                    [0],
                    output,
                    all_palettes=False,
                    force=True,
                    protected_paths=[source],
                )
            self.assertEqual(source.read_bytes(), payload)
            with self.assertRaisesRegex(tim_tool.TimToolError, "same path"):
                tim_tool._preflight([source, source], force=True)


if __name__ == "__main__":
    unittest.main()
