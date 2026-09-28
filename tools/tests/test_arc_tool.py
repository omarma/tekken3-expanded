from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import arc_tool


def make_arc(payloads: list[bytes], *, header_padding: int = 0) -> bytes:
    directory_size = 4 + len(payloads) * 8
    data_offset = directory_size + header_padding
    if data_offset % 4 or not 0 <= header_padding <= 15:
        raise ValueError("synthetic header padding must retain four-byte alignment")
    directory = bytearray(struct.pack("<I", len(payloads)))
    offset = data_offset
    for payload in payloads:
        if len(payload) % 4:
            raise ValueError("synthetic members must be four-byte aligned")
        directory.extend(struct.pack("<II", offset, len(payload)))
        offset += len(payload)
    directory.extend(b"\xFF" * (data_offset - directory_size))
    return bytes(directory) + b"".join(payloads)


class ArchiveParsingTests(unittest.TestCase):
    def test_parses_canonical_directory_and_zero_member(self) -> None:
        data = make_arc([b"AAAA", b"", b"BBBBBBBB"])
        archive = arc_tool.parse_archive(data)
        self.assertEqual(archive.directory_size, 28)
        self.assertEqual(archive.data_offset, 28)
        self.assertEqual(
            archive.members,
            (
                arc_tool.ArcMember(0, 28, 4),
                arc_tool.ArcMember(1, 32, 0),
                arc_tool.ArcMember(2, 32, 8),
            ),
        )

    def test_requires_alignment_contiguity_and_complete_coverage(self) -> None:
        data = bytearray(make_arc([b"AAAA", b"BBBB"] ))
        struct.pack_into("<I", data, 12, 25)
        with self.assertRaisesRegex(arc_tool.ArcToolError, "contiguous|aligned"):
            arc_tool.parse_archive(bytes(data))

        trailing = make_arc([b"AAAA"]) + b"JUNK"
        with self.assertRaisesRegex(arc_tool.ArcToolError, "covers"):
            arc_tool.parse_archive(trailing)

    def test_requires_canonical_ff_header_padding(self) -> None:
        # Two members make a 20-byte directory; these records may add four bytes.
        data = bytearray(make_arc([b"AAAA", b"BBBB"], header_padding=4))
        data[20:24] = b"\x00" * 4
        with self.assertRaisesRegex(arc_tool.ArcToolError, "0xFF"):
            arc_tool.parse_archive(bytes(data))


class InventoryAndExtractionTests(unittest.TestCase):
    def test_inventory_is_path_independent_and_only_hints_magic(self) -> None:
        tim_magic = b"\x10\x00\x00\x00" + b"not-validated"
        tim_magic += b"\x00" * (-len(tim_magic) % 4)
        data = make_arc([tim_magic, b"plain-data!!"])
        archive = arc_tool.parse_archive(data)
        first = arc_tool.build_inventory(archive)
        second = arc_tool.build_inventory(arc_tool.parse_archive(bytes(data)))
        self.assertEqual(first, second)
        self.assertEqual(first["format"], "tekken3-bns-arc")
        self.assertEqual(first["archive"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(first["members"][0]["magic_hint"], "TIM_MAGIC")
        self.assertEqual(first["members"][0]["suggested_filename"], "000.tim")

    def test_extracts_numeric_members_and_deterministic_manifest(self) -> None:
        data = make_arc([b"AAAA", b"BBBBBBBB"])
        archive = arc_tool.parse_archive(data)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "members"
            written = arc_tool.extract_members(
                archive, output, [1], force=False
            )
            self.assertEqual(written, [output / "001.bin"])
            self.assertEqual((output / "001.bin").read_bytes(), b"BBBBBBBB")
            manifest_text = (output / "arc_manifest.json").read_text(encoding="utf-8")
            manifest = json.loads(manifest_text)
            self.assertEqual(manifest["extraction"]["selected_ids"], [1])
            self.assertNotIn(str(output), manifest_text)

            with self.assertRaisesRegex(arc_tool.ArcToolError, "overwrite"):
                arc_tool.extract_members(archive, output, [1], force=False)

    def test_member_selection_is_sorted_and_bounded(self) -> None:
        self.assertEqual(arc_tool.parse_member_ids("3,1-2,2", 4), [1, 2, 3])
        self.assertEqual(arc_tool.parse_member_ids(None, 2), [0, 1])
        with self.assertRaises(arc_tool.ArcToolError):
            arc_tool.parse_member_ids("4", 4)
        with self.assertRaises(arc_tool.ArcToolError):
            arc_tool.parse_member_ids("3-1", 4)


class RebuildTests(unittest.TestCase):
    def test_exact_replacement_preserves_layout_and_unmodified_members(self) -> None:
        stock = make_arc([b"AAAA", b"BBBBBBBB", b"CCCC"])
        archive = arc_tool.parse_archive(stock)
        with tempfile.TemporaryDirectory() as temporary_directory:
            replacement = Path(temporary_directory) / "authored.bin"
            replacement.write_bytes(b"XXXXXXXX")
            rebuilt, report = arc_tool.rebuild_archive(
                archive,
                [arc_tool.ReplacementSpec(1, replacement)],
                allow_resize=False,
            )
            parsed = arc_tool.parse_archive(rebuilt)
            self.assertEqual(len(rebuilt), len(stock))
            self.assertEqual(
                rebuilt[parsed.members[0].offset : parsed.members[0].end_offset],
                b"AAAA",
            )
            self.assertEqual(
                rebuilt[parsed.members[1].offset : parsed.members[1].end_offset],
                b"XXXXXXXX",
            )
            self.assertEqual(
                rebuilt[parsed.members[2].offset : parsed.members[2].end_offset],
                b"CCCC",
            )
            self.assertTrue(report["rebuilt_archive"]["exact_top_level_size"])

    def test_resize_rewrites_offsets_and_reports_outer_size_change(self) -> None:
        stock = make_arc([b"AAAA", b"BBBB", b"CCCC"])
        archive = arc_tool.parse_archive(stock)
        with tempfile.TemporaryDirectory() as temporary_directory:
            replacement = Path(temporary_directory) / "larger.bin"
            replacement.write_bytes(b"X" * 12)
            rebuilt, report = arc_tool.rebuild_archive(
                archive,
                [arc_tool.ReplacementSpec(1, replacement)],
                allow_resize=True,
            )
            parsed = arc_tool.parse_archive(rebuilt)
            self.assertEqual(parsed.members[1].size, 12)
            self.assertEqual(parsed.members[2].offset, archive.members[2].offset + 8)
            self.assertEqual(report["rebuilt_archive"]["size_delta"], 8)
            self.assertFalse(report["rebuilt_archive"]["exact_top_level_size"])

    def test_resize_requires_explicit_mode_and_authored_alignment(self) -> None:
        archive = arc_tool.parse_archive(make_arc([b"AAAA"]))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            resized = root / "resized.bin"
            resized.write_bytes(b"B" * 8)
            with self.assertRaisesRegex(arc_tool.ArcToolError, "exact stock size"):
                arc_tool.rebuild_archive(
                    archive,
                    [arc_tool.ReplacementSpec(0, resized)],
                    allow_resize=False,
                )

            unaligned = root / "unaligned.bin"
            unaligned.write_bytes(b"odd")
            with self.assertRaisesRegex(arc_tool.ArcToolError, "four-byte aligned"):
                arc_tool.rebuild_archive(
                    archive,
                    [arc_tool.ReplacementSpec(0, unaligned)],
                    allow_resize=True,
                )

    def test_replacement_parser_rejects_duplicates_and_bad_syntax(self) -> None:
        parsed = arc_tool.parse_replacements(["2=b.bin", "0=a.bin"])
        self.assertEqual([item.id for item in parsed], [0, 2])
        with self.assertRaisesRegex(arc_tool.ArcToolError, "more than once"):
            arc_tool.parse_replacements(["1=a.bin", "01=b.bin"])
        with self.assertRaisesRegex(arc_tool.ArcToolError, "MEMBER=FILE"):
            arc_tool.parse_replacements(["1:a.bin"])

    def test_rebuild_api_rejects_duplicate_members(self) -> None:
        archive = arc_tool.parse_archive(make_arc([b"AAAA"]))
        with tempfile.TemporaryDirectory() as temporary_directory:
            replacement = Path(temporary_directory) / "replacement.bin"
            replacement.write_bytes(b"BBBB")
            spec = arc_tool.ReplacementSpec(0, replacement)
            with self.assertRaisesRegex(arc_tool.ArcToolError, "more than once"):
                arc_tool.rebuild_archive(archive, [spec, spec], allow_resize=False)


class OutputSafetyTests(unittest.TestCase):
    def test_output_paths_must_be_distinct_even_before_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.arc"
            output = root / "output.arc"
            source.write_bytes(make_arc([b"AAAA"]))
            with self.assertRaisesRegex(arc_tool.ArcToolError, "must differ"):
                arc_tool._require_distinct_paths(
                    [("input", source), ("ARC output", output), ("report output", output)]
                )


if __name__ == "__main__":
    unittest.main()
