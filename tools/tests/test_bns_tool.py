from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import bns_tool


def make_iso_record(name: bytes, extent: int, size: int, *, directory: bool) -> bytes:
    length = 33 + len(name)
    if length % 2:
        length += 1
    record = bytearray(length)
    record[0] = length
    struct.pack_into("<I", record, 2, extent)
    struct.pack_into(">I", record, 6, extent)
    struct.pack_into("<I", record, 10, size)
    struct.pack_into(">I", record, 14, size)
    record[25] = 0x02 if directory else 0x00
    struct.pack_into("<H", record, 28, 1)
    struct.pack_into(">H", record, 30, 1)
    record[32] = len(name)
    record[33 : 33 + len(name)] = name
    return bytes(record)


def make_raw_track(path: Path, payload: bytes, archive_name: bytes = b"TEKKEN3.BNS;1") -> None:
    sector_size = 2352
    user_offset = 24
    payload_sectors = (len(payload) + 2047) // 2048
    image = bytearray(max(32, 30 + payload_sectors) * sector_size)

    def put_user_sector(sector: int, data: bytes) -> None:
        physical = sector * sector_size
        image[physical : physical + 12] = b"\x00" + b"\xFF" * 10 + b"\x00"
        image[physical + 15] = 2
        start = physical + user_offset
        image[start : start + len(data)] = data

    root_record = make_iso_record(b"\x00", 20, 2048, directory=True)
    pvd = bytearray(2048)
    pvd[:7] = b"\x01CD001\x01"
    pvd[156 : 156 + len(root_record)] = root_record
    put_user_sector(16, pvd)

    root = bytearray(2048)
    records = (
        make_iso_record(b"\x00", 20, 2048, directory=True),
        make_iso_record(b"\x01", 20, 2048, directory=True),
        make_iso_record(b"TEKKEN3", 21, 2048, directory=True),
    )
    position = 0
    for record in records:
        root[position : position + len(record)] = record
        position += len(record)
    put_user_sector(20, root)

    subdirectory = bytearray(2048)
    records = (
        make_iso_record(b"\x00", 21, 2048, directory=True),
        make_iso_record(b"\x01", 20, 2048, directory=True),
        make_iso_record(archive_name, 30, len(payload), directory=False),
    )
    position = 0
    for record in records:
        subdirectory[position : position + len(record)] = record
        position += len(record)
    put_user_sector(21, subdirectory)
    for index in range(payload_sectors):
        put_user_sector(30 + index, payload[index * 2048 : (index + 1) * 2048])
    path.write_bytes(image)


class TableTests(unittest.TestCase):
    def test_fixed_table_parsing(self) -> None:
        data = bytearray(
            bns_tool.TABLE_FILE_OFFSET
            + bns_tool.TABLE_ENTRY_COUNT * bns_tool.TABLE_ENTRY_SIZE
        )
        for entry_id in range(bns_tool.TABLE_ENTRY_COUNT):
            struct.pack_into(
                "<II",
                data,
                bns_tool.TABLE_FILE_OFFSET + entry_id * 8,
                entry_id,
                1,
            )
        entries = bns_tool.parse_table_bytes(bytes(data), validate_exe_header=False)
        self.assertEqual(len(entries), 303)
        self.assertEqual(entries[0], bns_tool.TableEntry(0, 0, 1))
        self.assertEqual(entries[-1], bns_tool.TableEntry(302, 302, 1))

    def test_psx_header_uses_load_fields_after_initial_gp(self) -> None:
        data = bytearray(
            bns_tool.TABLE_FILE_OFFSET
            + bns_tool.TABLE_ENTRY_COUNT * bns_tool.TABLE_ENTRY_SIZE
        )
        data[:8] = b"PS-X EXE"
        struct.pack_into("<I", data, 0x10, 0x80079C70)
        struct.pack_into("<I", data, 0x14, 0x12345678)  # Initial GP is unrelated.
        struct.pack_into("<II", data, 0x18, 0x80010000, 0x00121000)
        entries = bns_tool.parse_table_bytes(bytes(data))
        self.assertEqual(len(entries), 303)

    def test_overlapping_table_is_rejected(self) -> None:
        entries = [bns_tool.TableEntry(i, i, 1) for i in range(303)]
        entries[1] = bns_tool.TableEntry(1, 0, 1)
        with self.assertRaisesRegex(bns_tool.BnsToolError, "overlap"):
            bns_tool.validate_table(entries)


class ClassificationTests(unittest.TestCase):
    def test_3dmk(self) -> None:
        self.assertEqual(
            bns_tool.classify_entry(b"\x00" * 8 + b"3DMK", 12),
            ("3DMK", ".3dm"),
        )

    def test_vh_and_complete_vab(self) -> None:
        header = bytearray(32)
        header[:4] = b"pBAV"
        struct.pack_into("<I", header, 4, 7)
        struct.pack_into("<I", header, 0x0C, 0x100)
        self.assertEqual(bns_tool.classify_entry(bytes(header), 32), ("VH", ".vh"))
        struct.pack_into("<I", header, 0x0C, 32)
        self.assertEqual(bns_tool.classify_entry(bytes(header), 32), ("VAB", ".vab"))

    def test_arc_requires_a_consistent_directory(self) -> None:
        archive = bytearray(32)
        struct.pack_into("<IIIII", archive, 0, 2, 24, 4, 28, 4)
        archive[24:] = b"AAAABBBB"
        self.assertEqual(bns_tool.classify_entry(bytes(archive), 32), ("ARC", ".arc"))

        struct.pack_into("<I", archive, 12, 29)
        self.assertEqual(bns_tool.classify_entry(bytes(archive), 32), ("BIN", ".bin"))

    def test_tim_structure_is_validated(self) -> None:
        tim = struct.pack("<IIIHHHHH", 0x10, 0x02, 14, 0, 0, 1, 1, 0x1234)
        self.assertEqual(len(tim), 22)
        self.assertEqual(bns_tool.classify_entry(tim, len(tim)), ("TIM", ".tim"))

        malformed = bytearray(tim)
        struct.pack_into("<I", malformed, 8, 100)
        self.assertEqual(
            bns_tool.classify_entry(bytes(malformed), len(malformed)), ("BIN", ".bin")
        )


class SourceTests(unittest.TestCase):
    def test_raw_track_iso_discovery_and_logical_read(self) -> None:
        payload = b"A" * 2040 + b"raw-track-boundary-payload"
        with tempfile.TemporaryDirectory() as temporary_directory:
            track_path = Path(temporary_directory) / "Track 1.bin"
            make_raw_track(track_path, payload)
            source = bns_tool.open_bns_source(track_path)
            self.assertEqual(source.kind, "raw_track_2352_mode2")
            self.assertEqual(source.extent_sector, 30)
            self.assertEqual(source.logical_size, len(payload))
            with source:
                self.assertEqual(source.read_at(0, len(payload)), payload)
                self.assertEqual(source.read_at(2038, 16), payload[2038:2054])

    def test_raw_track_accepts_short_bns_iso_name(self) -> None:
        payload = b"short-name-payload"
        with tempfile.TemporaryDirectory() as temporary_directory:
            track_path = Path(temporary_directory) / "Track 1.bin"
            make_raw_track(track_path, payload, b"BNS;1")
            source = bns_tool.open_bns_source(track_path)
            self.assertEqual(source.iso_path, "/TEKKEN3/BNS;1")
            with source:
                self.assertEqual(source.read_at(0, len(payload)), payload)

    def test_flat_source_hash_and_prefix(self) -> None:
        payload = b"some standalone archive payload"
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "TEKKEN3.BNS"
            source_path.write_bytes(payload)
            source = bns_tool.open_bns_source(source_path)
            entry = bns_tool.TableEntry(0, 0, len(payload))
            with source:
                item = bns_tool._inventory_entry(source, entry)
            self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(item["kind"], "BIN")


class SelectionAndExtractionTests(unittest.TestCase):
    def test_id_ranges_are_sorted_and_deduplicated(self) -> None:
        self.assertEqual(bns_tool.parse_ids("4,2-4,0"), [0, 2, 3, 4])
        self.assertEqual(len(bns_tool.parse_ids(None)), 303)
        with self.assertRaises(bns_tool.BnsToolError):
            bns_tool.parse_ids("303")
        with self.assertRaises(bns_tool.BnsToolError):
            bns_tool.parse_ids("8-2")

    def test_extract_writes_numeric_payload_and_manifests(self) -> None:
        payload = b"payload"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "TEKKEN3.BNS"
            source_path.write_bytes(payload)
            output = root / "workspace" / "bns"
            source = bns_tool.open_bns_source(source_path)
            entries = [
                bns_tool.TableEntry(0, 0, len(payload)),
                bns_tool.TableEntry(1, 1, 0),
            ]
            with source:
                items = [bns_tool._inventory_entry(source, entry) for entry in entries]
                inventory = {"entries": items}
                written = bns_tool.extract_entries(
                    source, entries, inventory, [0, 1], output, force=False
                )

            self.assertEqual(written, [output / "000.bin"])
            self.assertEqual((output / "000.bin").read_bytes(), payload)
            self.assertFalse((output / "001.bin").exists())
            manifest = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["extraction"]["selected_ids"], [0, 1])
            self.assertEqual(manifest["extraction"]["zero_size_entries_skipped"], [1])
            self.assertTrue((output / "inventory.csv").is_file())

            with source:
                with self.assertRaisesRegex(bns_tool.BnsToolError, "overwrite"):
                    bns_tool.extract_entries(
                        source, entries, inventory, [0], output, force=False
                    )


if __name__ == "__main__":
    unittest.main()
