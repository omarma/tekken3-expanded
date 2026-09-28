from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import bns_tool, vab_tool


def make_vb(*, end_flag: bool = True) -> bytes:
    first_block = bytes(16)
    final_block = bytearray(16)
    final_block[1] = 1 if end_flag else 0
    return first_block + bytes(final_block)


def make_vh(vb: bytes) -> bytes:
    program_count = 1
    tone_count = 1
    vag_count = 1
    header_size = 0xA20 + program_count * 0x200
    data = bytearray(header_size)
    data[:4] = b"pBAV"
    struct.pack_into("<III", data, 4, 7, 0, header_size + len(vb))
    struct.pack_into(
        "<HHHH", data, 0x10, 0xEEEE, program_count, tone_count, vag_count
    )
    struct.pack_into("<BBBB", data, 0x18, 100, 64, 0, 0)
    struct.pack_into("<I", data, 0x1C, 0xFFFFFFFF)
    data[0x20] = 1
    size_table_offset = 0x820 + program_count * 0x200
    struct.pack_into("<H", data, size_table_offset + 2, len(vb) // 8)
    return bytes(data)


def make_arc(vb: bytes, *, ambiguous: bool = False, padding: bytes = b"\xFF" * 4) -> bytes:
    members = [
        b"A" * (len(vb) if ambiguous else 16),
        b"B" * 24,
        vb,
        b"C" * 8,
        b"D" * 4,
    ]
    count = len(members)
    directory_size = 4 + count * 8
    first_offset = 0x30
    if len(padding) != first_offset - directory_size:
        raise AssertionError("test ARC padding has the wrong size")
    data = bytearray(first_offset + sum(map(len, members)))
    struct.pack_into("<I", data, 0, count)
    position = first_offset
    for index, member in enumerate(members):
        struct.pack_into("<II", data, 4 + index * 8, position, len(member))
        data[position : position + len(member)] = member
        position += len(member)
    data[directory_size:first_offset] = padding
    return bytes(data)


def make_source(root: Path, vh: bytes, arc: bytes) -> tuple[bns_tool.BnsSource, list[bns_tool.TableEntry]]:
    arc_sector = (len(vh) + 2047) // 2048
    arc_offset = arc_sector * 2048
    payload = vh + bytes(arc_offset - len(vh)) + arc
    path = root / "TEKKEN3.BNS"
    path.write_bytes(payload)
    entries = [bns_tool.TableEntry(index, 0, 0) for index in range(303)]
    entries[72] = bns_tool.TableEntry(72, 0, len(vh))
    entries[73] = bns_tool.TableEntry(73, arc_sector, len(arc))
    return bns_tool.open_bns_source(path, "bns"), entries


class VhTests(unittest.TestCase):
    def test_parse_verified_split_header(self) -> None:
        vb = make_vb()
        header = vab_tool.parse_vh(make_vh(vb))
        self.assertEqual(header.version, 7)
        self.assertEqual(header.header_size, 0xC20)
        self.assertEqual(header.program_count, 1)
        self.assertEqual(header.tone_count, 1)
        self.assertEqual(header.vag_count, 1)
        self.assertEqual(header.sample_sizes, (len(vb),))
        self.assertEqual(header.vb_size, len(vb))

    def test_declared_total_must_match_size_table(self) -> None:
        vh = bytearray(make_vh(make_vb()))
        struct.pack_into("<I", vh, 0x0C, len(vh) + 16)
        with self.assertRaisesRegex(vab_tool.VabToolError, "size table"):
            vab_tool.parse_vh(bytes(vh))

    def test_unused_vag_sizes_must_be_zero(self) -> None:
        vh = bytearray(make_vh(make_vb()))
        size_table_offset = 0x820 + 0x200
        struct.pack_into("<H", vh, size_table_offset + 4, 2)
        struct.pack_into("<I", vh, 0x0C, len(vh) + 48)
        with self.assertRaisesRegex(vab_tool.VabToolError, "beyond"):
            vab_tool.parse_vh(bytes(vh))

    def test_header_markers_and_exact_length_are_required(self) -> None:
        vh = bytearray(make_vh(make_vb()))
        vh[:4] = b"nope"
        with self.assertRaisesRegex(vab_tool.VabToolError, "magic"):
            vab_tool.parse_vh(bytes(vh))
        with self.assertRaisesRegex(vab_tool.VabToolError, "require exactly"):
            vab_tool.parse_vh(make_vh(make_vb()) + bytes(16))


class ArcTests(unittest.TestCase):
    def test_parse_contiguous_arc(self) -> None:
        arc = vab_tool.parse_arc(make_arc(make_vb()))
        self.assertEqual(len(arc.members), 5)
        self.assertEqual(arc.members[2].index, 2)
        self.assertEqual(arc.members[2].size, len(make_vb()))

    def test_reject_non_verified_padding(self) -> None:
        with self.assertRaisesRegex(vab_tool.VabToolError, "padding"):
            vab_tool.parse_arc(make_arc(make_vb(), padding=bytes(4)))

    def test_reject_non_contiguous_member(self) -> None:
        data = bytearray(make_arc(make_vb()))
        member_one_offset = struct.unpack_from("<I", data, 12)[0]
        struct.pack_into("<I", data, 12, member_one_offset + 1)
        with self.assertRaisesRegex(vab_tool.VabToolError, "not contiguous"):
            vab_tool.parse_arc(bytes(data))

    def test_reject_unaligned_member_size(self) -> None:
        data = bytearray(make_arc(make_vb()))
        struct.pack_into("<I", data, 8, 15)
        with self.assertRaisesRegex(vab_tool.VabToolError, "not 4-byte aligned"):
            vab_tool.parse_arc(bytes(data))


class VbTests(unittest.TestCase):
    def test_validate_spu_adpcm_framing(self) -> None:
        vb = make_vb()
        vab_tool.validate_vb(vb, vab_tool.parse_vh(make_vh(vb)))

    def test_reject_missing_sample_end_flag(self) -> None:
        vb = make_vb(end_flag=False)
        with self.assertRaisesRegex(vab_tool.VabToolError, "no end flag"):
            vab_tool.validate_vb(vb, vab_tool.parse_vh(make_vh(vb)))

    def test_reject_invalid_predictor(self) -> None:
        vb = bytearray(make_vb())
        vb[16] = 0x50
        with self.assertRaisesRegex(vab_tool.VabToolError, "block header"):
            vab_tool.validate_vb(bytes(vb), vab_tool.parse_vh(make_vh(bytes(vb))))


class PairAndOutputTests(unittest.TestCase):
    def test_verified_pair_reconstructs_vh_plus_arc_member_two(self) -> None:
        vb = make_vb()
        vh = make_vh(vb)
        arc = make_arc(vb)
        with tempfile.TemporaryDirectory() as temporary_directory:
            source, entries = make_source(Path(temporary_directory), vh, arc)
            with source:
                pair = vab_tool.prepare_pair(source, entries, 72, 73)
            self.assertEqual(pair.vb_member.index, 2)
            self.assertEqual(pair.vb_data, vb)
            self.assertEqual(pair.reconstructed, vh + vb)
            manifest = vab_tool.pair_manifest(pair)
            self.assertTrue(all(manifest["proof"].values()))
            self.assertEqual(
                manifest["reconstructed_vab"]["sha256"],
                hashlib.sha256(vh + vb).hexdigest(),
            )

    def test_explicit_ids_must_be_a_known_pair(self) -> None:
        with self.assertRaisesRegex(vab_tool.VabToolError, "not a verified"):
            vab_tool._validate_pair_ids(72, 77)
        self.assertEqual(len(vab_tool.VERIFIED_PAIRS), 48)

    def test_matching_arc_member_must_be_unique(self) -> None:
        vb = make_vb()
        vh = make_vh(vb)
        with tempfile.TemporaryDirectory() as temporary_directory:
            source, entries = make_source(
                Path(temporary_directory), vh, make_arc(vb, ambiguous=True)
            )
            with source:
                with self.assertRaisesRegex(vab_tool.VabToolError, "2 members"):
                    vab_tool.prepare_pair(source, entries, 72, 73)

    def test_atomic_output_and_overwrite_guard(self) -> None:
        vb = make_vb()
        vh = make_vh(vb)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source, entries = make_source(root, vh, make_arc(vb))
            output = root / "workspace" / "072.vab"
            manifest_path = root / "workspace" / "072.vab.json"
            with source:
                pair = vab_tool.prepare_pair(source, entries, 72, 73)
                manifest = vab_tool.build_extraction_manifest(
                    pair,
                    output,
                    source,
                    exe_path=Path("SLUS_004.02"),
                    exe_sha256="a" * 64,
                    table_sha256="b" * 64,
                )
                vab_tool.write_reconstruction(
                    output, manifest_path, pair, manifest, force=False
                )

            self.assertEqual(output.read_bytes(), vh + vb)
            written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(written_manifest["pair"]["vh_id"], 72)
            self.assertEqual(
                written_manifest["output"]["sha256"],
                hashlib.sha256(vh + vb).hexdigest(),
            )
            with self.assertRaisesRegex(vab_tool.VabToolError, "overwrite"):
                vab_tool.write_reconstruction(
                    output, manifest_path, pair, manifest, force=False
                )

    def test_force_cannot_replace_a_protected_input(self) -> None:
        vb = make_vb()
        vh = make_vh(vb)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source, entries = make_source(root, vh, make_arc(vb))
            output = root / "safe.vab"
            with source:
                pair = vab_tool.prepare_pair(source, entries, 72, 73)
                manifest = {"pair": {"vh_id": 72}}
                with self.assertRaisesRegex(vab_tool.VabToolError, "protected input"):
                    vab_tool.write_reconstruction(
                        output,
                        source.path,
                        pair,
                        manifest,
                        force=True,
                        protected_paths=[source.path],
                    )


if __name__ == "__main__":
    unittest.main()
