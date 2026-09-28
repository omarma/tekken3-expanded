from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import bns_tool, model_map


def make_3dmk_fixture() -> bytes:
    row_count = 2
    payload_start = model_map.THREEDMK_HEADER_SIZE + row_count * model_map.THREEDMK_ROW_SIZE
    payload_relative = payload_start - model_map.THREEDMK_RELATIVE_BASE
    data = bytearray(
        struct.pack(
            "<II4sIII",
            row_count,
            77,
            b"3DMK",
            0,
            payload_relative,
            0,
        )
    )
    rows = (
        (128, 132, 136, 0, 0, 0, 0xFFFFFFFF, 0, 0, 0, 1, 0, 2, 0),
        (140, 144, 148, 0, 0, 0, 0, 0, 0, 0, 0, 0, 152, 156),
    )
    for row in rows:
        data.extend(struct.pack("<14I", *row))
    data.extend(bytes((index * 17) & 0xFF for index in range(96)))
    return bytes(data)


def make_model_candidate_fixture() -> bytes:
    row_count = model_map.MODEL_CANDIDATE_ROW_COUNT
    table_end = (
        model_map.MODEL_CANDIDATE_HEADER_SIZE
        + row_count * model_map.MODEL_CANDIDATE_ROW_SIZE
    )
    variable_size = row_count * 4
    fixed_start = table_end + variable_size
    fixed_size = row_count * model_map.MODEL_CANDIDATE_FIXED_STRIDE
    file_size = fixed_start + fixed_size
    base = model_map.MODEL_CANDIDATE_RELATIVE_BASE

    data = bytearray(
        struct.pack(
            "<III",
            model_map.MODEL_CANDIDATE_WORD0,
            400,
            row_count,
        )
    )
    for row_id in range(row_count):
        fixed_relative = fixed_start - base + row_id * 8
        variable_relative = table_end - base + row_id * 4
        marker = file_size - base if row_id == 0 else 0
        unknown_count = row_id % 5
        data.extend(
            struct.pack(
                "<7I",
                fixed_relative,
                1,
                marker,
                unknown_count,
                variable_relative,
                unknown_count,
                0,
            )
        )
    data.extend(bytes((0xA0 + index) & 0xFF for index in range(variable_size)))
    data.extend(bytes((index * 9) & 0xFF for index in range(fixed_size)))
    assert len(data) == file_size
    return bytes(data)


class ThreeDmkTests(unittest.TestCase):
    def test_parses_header_rows_offsets_and_major_sections(self) -> None:
        data = make_3dmk_fixture()
        parsed = model_map.parse_3dmk(data)
        self.assertEqual(parsed.profile, model_map.PROFILE_3DMK)
        self.assertEqual(parsed.header["row_count"], 2)
        self.assertEqual(parsed.header["unknown_u32_at_0x04"], 77)
        self.assertEqual(
            [section.name for section in parsed.sections],
            ["header", "row_table", "payload"],
        )
        self.assertEqual(parsed.sections[1].size, 112)
        self.assertEqual(parsed.sections[2].offset, 136)
        self.assertTrue(
            any(
                reference["word_index"] == 12
                and reference["status"] == "conditional_observed_offset"
                for reference in parsed.offset_references
            )
        )
        self.assertTrue(parsed.candidate_regions)

    def test_rejects_header_offset_that_does_not_follow_table(self) -> None:
        data = bytearray(make_3dmk_fixture())
        struct.pack_into("<I", data, 16, 0x40)
        with self.assertRaisesRegex(model_map.ModelMapError, "does not exactly follow"):
            model_map.parse_3dmk(bytes(data))

    def test_rejects_unbounded_observed_offset_column(self) -> None:
        data = bytearray(make_3dmk_fixture())
        struct.pack_into("<I", data, model_map.THREEDMK_HEADER_SIZE, 0xFFFFFFFC)
        with self.assertRaisesRegex(model_map.ModelMapError, "in-file relative offset"):
            model_map.parse_3dmk(bytes(data))


class ModelCandidateTests(unittest.TestCase):
    def test_parses_exact_structural_cover_without_semantic_names(self) -> None:
        data = make_model_candidate_fixture()
        parsed = model_map.parse_model_candidate(data)
        self.assertEqual(parsed.profile, model_map.PROFILE_STAGE_CANDIDATE)
        self.assertEqual(len(parsed.rows), 36)
        self.assertEqual(
            [section.name for section in parsed.sections],
            ["header", "row_table", "variable_stream", "fixed_stride8_stream"],
        )
        self.assertEqual(parsed.sections[1].end_offset, 1020)
        self.assertEqual(parsed.sections[-1].end_offset, len(data))
        self.assertEqual(parsed.rows[0]["fixed_stride8_range"]["stride"], 8)
        self.assertIn("opaque", parsed.rows[0]["variable_stream_candidate_span"]["note"])

    def test_rejects_noncontiguous_fixed_stride_offsets(self) -> None:
        data = bytearray(make_model_candidate_fixture())
        row_10_word_0 = (
            model_map.MODEL_CANDIDATE_HEADER_SIZE
            + 10 * model_map.MODEL_CANDIDATE_ROW_SIZE
        )
        original = struct.unpack_from("<I", data, row_10_word_0)[0]
        struct.pack_into("<I", data, row_10_word_0, original + 4)
        with self.assertRaisesRegex(model_map.ModelMapError, "not contiguous"):
            model_map.parse_model_candidate(bytes(data))

    def test_rejects_changed_opaque_fingerprint_constant(self) -> None:
        data = bytearray(make_model_candidate_fixture())
        struct.pack_into("<I", data, 0, 64)
        with self.assertRaisesRegex(model_map.ModelMapError, "opaque word 0"):
            model_map.parse_model_candidate(bytes(data))


class DetectionAndOutputTests(unittest.TestCase):
    def test_detection_is_conservative(self) -> None:
        self.assertEqual(
            model_map.detect_model(make_3dmk_fixture()).profile,
            model_map.PROFILE_3DMK,
        )
        self.assertEqual(
            model_map.detect_model(make_model_candidate_fixture()).profile,
            model_map.PROFILE_STAGE_CANDIDATE,
        )
        self.assertIsNone(model_map.detect_model(bytes(range(64))))

    def test_section_extraction_uses_numeric_directories_and_no_overwrite(self) -> None:
        data = make_3dmk_fixture()
        parsed = model_map.parse_3dmk(data)
        record = model_map.ModelRecord(
            bns_tool.TableEntry(71, 100, len(data)), parsed
        )
        document = model_map._record_document(record)
        inventory = {
            "schema_version": 1,
            "scan": {"model_records_found": 1},
            "records": [document],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "models"
            written = model_map.extract_sections(
                [record], inventory, output, force=False
            )
            self.assertEqual(len(written), 3)
            self.assertEqual(
                (output / "071" / "section_000_header.bin").read_bytes(),
                data[: model_map.THREEDMK_HEADER_SIZE],
            )
            manifest = json.loads(
                (output / "model_map.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["extraction"]["selected_ids"], [71])
            self.assertIsNone(manifest["records"][0]["semantic_name"])
            with self.assertRaisesRegex(model_map.ModelMapError, "overwrite"):
                model_map.extract_sections([record], inventory, output, force=False)

    def test_csv_is_deterministic_and_section_only(self) -> None:
        parsed = model_map.parse_model_candidate(make_model_candidate_fixture())
        record = model_map.ModelRecord(
            bns_tool.TableEntry(56, 10, len(parsed.data)), parsed
        )
        inventory = {"records": [model_map._record_document(record)]}
        first = io.StringIO()
        second = io.StringIO()
        model_map._emit_csv(first, inventory)
        model_map._emit_csv(second, inventory)
        self.assertEqual(first.getvalue(), second.getvalue())
        self.assertEqual(len(first.getvalue().splitlines()), 5)
        self.assertNotIn("stage_name", first.getvalue())

    def test_selection_rejects_non_model_bns_ids(self) -> None:
        parsed = model_map.parse_3dmk(make_3dmk_fixture())
        records = [
            model_map.ModelRecord(bns_tool.TableEntry(71, 1, len(parsed.data)), parsed)
        ]
        with self.assertRaisesRegex(model_map.ModelMapError, "do not match"):
            model_map._select_records(records, "72")


if __name__ == "__main__":
    unittest.main()
