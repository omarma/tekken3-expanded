from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import xas_tool


def bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def make_sector(
    absolute_lba: int,
    *,
    submode: int = 0x00,
    channel: int = 0,
    coding: int = 0,
    payload: bytes = b"",
) -> bytes:
    raw = bytearray(xas_tool.RAW_SECTOR_SIZE)
    raw[:12] = xas_tool.SYNC
    minute, second, frame = xas_tool._expected_msf(absolute_lba)
    raw[12:15] = bytes((bcd(minute), bcd(second), bcd(frame)))
    raw[15] = 2
    subheader = bytes((1, channel, submode, coding))
    raw[16:20] = subheader
    raw[20:24] = subheader
    raw[24 : 24 + len(payload)] = payload
    return bytes(raw)


def str_payload(
    chunk: int,
    chunks: int,
    frame: int,
    *,
    width: int = 256,
    height: int = 224,
) -> bytes:
    return struct.pack(
        "<HHHHIIHH", 0x0160, 0x8001, chunk, chunks, frame, 100, width, height
    )


def write_source(path: Path, extent_lba: int, sectors: list[bytes]) -> xas_tool.XasSource:
    path.write_bytes(b"\x00" * (extent_lba * xas_tool.RAW_SECTOR_SIZE) + b"".join(sectors))
    return xas_tool.XasSource(path, extent_lba, len(sectors))


class DescriptorTests(unittest.TestCase):
    def test_fixed_executable_table_parsing(self) -> None:
        data = bytearray(
            xas_tool.XAS_TABLE_FILE_OFFSET
            + xas_tool.XAS_TABLE_ENTRY_COUNT * xas_tool.XAS_TABLE_ENTRY_SIZE
        )
        for entry_id in range(xas_tool.XAS_TABLE_ENTRY_COUNT):
            group = entry_id * 16
            struct.pack_into(
                "<III",
                data,
                xas_tool.XAS_TABLE_FILE_OFFSET + entry_id * 12,
                group,
                group,
                entry_id % 8,
            )
        descriptors = xas_tool.parse_descriptor_table_bytes(
            bytes(data), validate_exe_header=False
        )
        self.assertEqual(len(descriptors), 50)
        self.assertEqual(descriptors[3].first_relative_sector, 51)
        self.assertEqual(descriptors[3].sector_count, 1)

    def test_alignment_channel_and_overlap_are_rejected(self) -> None:
        with self.assertRaisesRegex(xas_tool.XasToolError, "aligned"):
            xas_tool.validate_descriptors([xas_tool.XaDescriptor(0, 1, 8, 0)])
        with self.assertRaisesRegex(xas_tool.XasToolError, "channel"):
            xas_tool.validate_descriptors([xas_tool.XaDescriptor(0, 0, 8, 8)])
        with self.assertRaisesRegex(xas_tool.XasToolError, "select sector"):
            xas_tool.validate_descriptors(
                [xas_tool.XaDescriptor(0, 0, 8, 1), xas_tool.XaDescriptor(1, 0, 8, 1)]
            )


class SectorTests(unittest.TestCase):
    def test_mode2_msf_and_duplicate_subheader_validation(self) -> None:
        raw = make_sector(123, submode=0x64, channel=2, coding=1)
        info = xas_tool.parse_raw_sector(raw, absolute_lba=123, relative_sector=4)
        self.assertEqual((info.file_number, info.channel, info.submode, info.coding_info), (1, 2, 0x64, 1))

        malformed = bytearray(raw)
        malformed[20] ^= 1
        with self.assertRaisesRegex(xas_tool.XasToolError, "subheader copies"):
            xas_tool.parse_raw_sector(bytes(malformed), absolute_lba=123, relative_sector=4)
        with self.assertRaisesRegex(xas_tool.XasToolError, "MSF"):
            xas_tool.parse_raw_sector(raw, absolute_lba=124, relative_sector=4)

    def test_xa_descriptor_proves_stride_channel_and_terminal_eof(self) -> None:
        extent = 5
        sectors = [make_sector(extent + index) for index in range(11)]
        sectors[2] = make_sector(extent + 2, submode=0x64, channel=2, coding=1)
        sectors[10] = make_sector(extent + 10, submode=0xE4, channel=2, coding=1)
        descriptor = xas_tool.XaDescriptor(0, 0, 8, 2)
        with tempfile.TemporaryDirectory() as temporary:
            source = write_source(Path(temporary) / "track.bin", extent, sectors)
            with source:
                scan = xas_tool.scan_xas(source, [descriptor])
        expected = hashlib.sha256(sectors[2] + sectors[10]).hexdigest()
        self.assertEqual(scan.xa_stream_sha256, [expected])
        self.assertEqual(descriptor.sector_count, 2)

        sectors[10] = make_sector(extent + 10, submode=0x64, channel=2, coding=1)
        with tempfile.TemporaryDirectory() as temporary:
            source = write_source(Path(temporary) / "track.bin", extent, sectors)
            with source:
                with self.assertRaisesRegex(xas_tool.XasToolError, "descriptor 0"):
                    xas_tool.scan_xas(source, [descriptor])


class MovieTests(unittest.TestCase):
    def test_str_frame_resets_form_numeric_movie_regions(self) -> None:
        extent = 20
        sectors = [
            make_sector(extent + 0, submode=0x48, channel=1, payload=str_payload(0, 2, 1)),
            make_sector(extent + 1, submode=0x64, channel=1, coding=1),
            make_sector(extent + 2, submode=0x48, channel=1, payload=str_payload(1, 2, 1)),
            make_sector(extent + 3),
            make_sector(extent + 4, submode=0x48, channel=1, payload=str_payload(0, 1, 2)),
            make_sector(extent + 5, submode=0x48, channel=1, payload=str_payload(0, 1, 1, width=320, height=240)),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            source = write_source(Path(temporary) / "track.bin", extent, sectors)
            with source:
                scan = xas_tool.scan_xas(source, [])
        movies = xas_tool.discover_movie_regions(scan.str_sectors, expected_count=2)
        self.assertEqual((movies[0].start_relative_sector, movies[0].end_relative_sector), (0, 4))
        self.assertEqual((movies[0].frame_count, movies[0].str_sector_count), (2, 3))
        self.assertEqual((movies[1].width, movies[1].height), (320, 240))

    def test_incomplete_str_frame_is_rejected(self) -> None:
        sectors = [
            xas_tool.StrSector(0, xas_tool.StrChunkHeader(0, 2, 1, 100, 256, 224))
        ]
        with self.assertRaisesRegex(xas_tool.XasToolError, "mid-frame"):
            xas_tool.discover_movie_regions(sectors)


class SelectionAndExtractionTests(unittest.TestCase):
    def test_id_ranges_and_exact_raw_sector_output(self) -> None:
        self.assertEqual(xas_tool.parse_ids("3,1-3", 5, "XA ID"), [1, 2, 3])
        self.assertEqual(xas_tool.parse_ids(None, 5, "XA ID"), [])
        with self.assertRaises(xas_tool.XasToolError):
            xas_tool.parse_ids("5", 5, "XA ID")

        extent = 7
        sectors = [make_sector(extent + index) for index in range(11)]
        sectors[2] = make_sector(extent + 2, submode=0x64, channel=2, coding=1)
        sectors[10] = make_sector(extent + 10, submode=0xE4, channel=2, coding=1)
        descriptor = xas_tool.XaDescriptor(0, 0, 8, 2)
        movie = xas_tool.MovieRegion(0, 3, 4, 1, 256, 224, (1,), 1)
        inventory = {"xa_streams": [], "movie_regions": []}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_source(root / "track.bin", extent, sectors)
            with source:
                written = xas_tool.extract_selected(
                    source,
                    [descriptor],
                    [movie],
                    inventory,
                    root / "out",
                    xa_ids=[0],
                    movie_ids=[0],
                    force=False,
                )
            self.assertEqual(len(written), 2)
            self.assertEqual((root / "out" / "xa-000.raw").read_bytes(), sectors[2] + sectors[10])
            self.assertEqual((root / "out" / "movie-000.str.raw").read_bytes(), sectors[3] + sectors[4])
            manifest = json.loads((root / "out" / "inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["extraction"]["xa_ids"], [0])
            self.assertTrue((root / "out" / "inventory.csv").is_file())


if __name__ == "__main__":
    unittest.main()
