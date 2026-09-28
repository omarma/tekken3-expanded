#!/usr/bin/env python3
"""Conservative structural maps for Tekken 3 USA model-like BNS records.

The tool is deliberately read-only with respect to the executable, BNS file,
and disc image.  It recognizes the observed 3DMK envelope and a separate,
magic-free structural profile found in exactly fifteen records of the verified
US archive.  It does not assign character, stage, mesh, bone, or animation
names to unknown data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, TextIO

try:  # Support both ``python tools/model_map.py`` and test-package imports.
    from . import bns_tool
except ImportError:  # pragma: no cover - exercised by the CLI entry point
    import bns_tool  # type: ignore[no-redef]


SCHEMA_VERSION = 1
ENTROPY_BLOCK_SIZE = 0x100

PROFILE_3DMK = "3dmk_observed_v1"
PROFILE_STAGE_CANDIDATE = "model_candidate_observed_v1"

THREEDMK_MAGIC = b"3DMK"
THREEDMK_HEADER_SIZE = 24
THREEDMK_ROW_SIZE = 56
THREEDMK_RELATIVE_BASE = 8
THREEDMK_REQUIRED_OFFSET_WORDS = (0, 1, 2, 13)

# These two values are part of the magic-free fingerprint.  Their meanings are
# unknown, so the public schema intentionally keeps the first one opaque.
MODEL_CANDIDATE_WORD0 = 65
MODEL_CANDIDATE_ROW_COUNT = 36
MODEL_CANDIDATE_HEADER_SIZE = 12
MODEL_CANDIDATE_ROW_SIZE = 28
MODEL_CANDIDATE_RELATIVE_BASE = 12
MODEL_CANDIDATE_FIXED_STRIDE = 8


class ModelMapError(RuntimeError):
    """A user-facing validation or output error."""


@dataclass(frozen=True)
class RawSection:
    id: int
    name: str
    offset: int
    size: int
    basis: str

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class ParsedModel:
    profile: str
    data: bytes
    header: dict[str, object]
    rows: tuple[dict[str, object], ...]
    sections: tuple[RawSection, ...]
    offset_references: tuple[dict[str, object], ...]
    candidate_regions: tuple[dict[str, object], ...]
    confidence: str


@dataclass(frozen=True)
class ModelRecord:
    entry: bns_tool.TableEntry
    parsed: ParsedModel


def _u32_words(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    try:
        return struct.unpack_from(f"<{count}I", data, offset)
    except struct.error as exc:
        raise ModelMapError(f"truncated u32 structure at 0x{offset:X}") from exc


def _require_relative_offset(
    value: int,
    *,
    relative_base: int,
    minimum_actual: int,
    file_size: int,
    label: str,
) -> int:
    actual = relative_base + value
    if value % 4 or actual < minimum_actual or actual > file_size:
        raise ModelMapError(
            f"{label} is not a four-byte-aligned in-file relative offset: "
            f"0x{value:X} (base 0x{relative_base:X})"
        )
    return actual


def _byte_metrics(data: bytes) -> dict[str, object]:
    size = len(data)
    if size == 0:
        entropy = 0.0
        zero_fraction = 0.0
        printable_fraction = 0.0
    else:
        counts = [0] * 256
        printable = 0
        for value in data:
            counts[value] += 1
            if 0x20 <= value <= 0x7E:
                printable += 1
        entropy = -sum(
            (count / size) * math.log2(count / size)
            for count in counts
            if count
        )
        zero_fraction = counts[0] / size
        printable_fraction = printable / size
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "entropy": round(entropy, 6),
        "zero_fraction": round(zero_fraction, 6),
        "printable_ascii_fraction": round(printable_fraction, 6),
        "prefix_hex": data[:8].hex().upper(),
    }


def _section_document(data: bytes, section: RawSection) -> dict[str, object]:
    payload = data[section.offset : section.end_offset]
    return {
        "id": section.id,
        "name": section.name,
        "offset": section.offset,
        "end_offset": section.end_offset,
        "size": section.size,
        "basis": section.basis,
        **_byte_metrics(payload),
    }


def _entropy_blocks(data: bytes) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for block_id, offset in enumerate(range(0, len(data), ENTROPY_BLOCK_SIZE)):
        payload = data[offset : offset + ENTROPY_BLOCK_SIZE]
        blocks.append(
            {
                "id": block_id,
                "offset": offset,
                "end_offset": offset + len(payload),
                "size": len(payload),
                **_byte_metrics(payload),
            }
        )
    return blocks


def parse_3dmk(data: bytes) -> ParsedModel:
    """Parse only the proven structural envelope of an observed 3DMK record."""

    if len(data) < THREEDMK_HEADER_SIZE:
        raise ModelMapError("3DMK record is smaller than its 24-byte header")
    if data[8:12] != THREEDMK_MAGIC:
        raise ModelMapError("3DMK marker is not present at byte offset 8")

    row_count, unknown_04, _magic, reserved_0c, payload_rel, reserved_14 = _u32_words(
        data, 0, 6
    )
    if not 1 <= row_count <= 512:
        raise ModelMapError(f"implausible 3DMK row count: {row_count}")
    if reserved_0c != 0 or reserved_14 != 0:
        raise ModelMapError("observed 3DMK reserved header words are not zero")

    table_end = THREEDMK_HEADER_SIZE + row_count * THREEDMK_ROW_SIZE
    payload_start = THREEDMK_RELATIVE_BASE + payload_rel
    if payload_rel % 4 or payload_start != table_end or table_end > len(data):
        raise ModelMapError(
            "3DMK payload-relative offset does not exactly follow the "
            f"{row_count}-row, {THREEDMK_ROW_SIZE}-byte table"
        )

    rows: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    for row_id in range(row_count):
        row_offset = THREEDMK_HEADER_SIZE + row_id * THREEDMK_ROW_SIZE
        words = _u32_words(data, row_offset, THREEDMK_ROW_SIZE // 4)
        if words[10] not in (0, 1):
            raise ModelMapError(
                f"3DMK row {row_id} observed boolean word 10 is {words[10]}"
            )
        if words[11] != 0:
            raise ModelMapError(f"3DMK row {row_id} reserved word 11 is not zero")

        row_references: list[dict[str, object]] = []
        for word_index in THREEDMK_REQUIRED_OFFSET_WORDS:
            value = words[word_index]
            if value == 0:
                continue
            actual = _require_relative_offset(
                value,
                relative_base=THREEDMK_RELATIVE_BASE,
                minimum_actual=payload_start,
                file_size=len(data),
                label=f"3DMK row {row_id} word {word_index}",
            )
            reference = {
                "row_id": row_id,
                "word_index": word_index,
                "relative_offset": value,
                "actual_offset": actual,
                "status": "observed_offset_column",
            }
            row_references.append(reference)
            references.append(reference)

        value_12 = words[12]
        if value_12 not in (0, 2):
            actual = _require_relative_offset(
                value_12,
                relative_base=THREEDMK_RELATIVE_BASE,
                minimum_actual=payload_start,
                file_size=len(data),
                label=f"3DMK row {row_id} conditional word 12",
            )
            reference = {
                "row_id": row_id,
                "word_index": 12,
                "relative_offset": value_12,
                "actual_offset": actual,
                "status": "conditional_observed_offset",
            }
            row_references.append(reference)
            references.append(reference)

        rows.append(
            {
                "id": row_id,
                "offset": row_offset,
                "size": THREEDMK_ROW_SIZE,
                "words_u32": list(words),
                "words_hex": [f"0x{value:08X}" for value in words],
                "offset_references": row_references,
            }
        )

    # These intervals are navigation aids only.  A candidate offset can point
    # into a structure rather than define a semantic section boundary.
    boundaries = sorted(
        {payload_start, len(data)}
        | {int(reference["actual_offset"]) for reference in references}
    )
    regions: list[dict[str, object]] = []
    references_by_offset: dict[int, list[dict[str, int]]] = {}
    for reference in references:
        actual = int(reference["actual_offset"])
        references_by_offset.setdefault(actual, []).append(
            {
                "row_id": int(reference["row_id"]),
                "word_index": int(reference["word_index"]),
            }
        )
    for region_id, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        regions.append(
            {
                "id": region_id,
                "offset": start,
                "end_offset": end,
                "size": end - start,
                "boundary_references": references_by_offset.get(start, []),
                **_byte_metrics(data[start:end]),
            }
        )

    sections = (
        RawSection(0, "header", 0, THREEDMK_HEADER_SIZE, "fixed observed envelope"),
        RawSection(
            1,
            "row_table",
            THREEDMK_HEADER_SIZE,
            table_end - THREEDMK_HEADER_SIZE,
            "header row_count multiplied by the observed 56-byte row size",
        ),
        RawSection(
            2,
            "payload",
            payload_start,
            len(data) - payload_start,
            "header relative offset (base 8) through end of record",
        ),
    )
    header: dict[str, object] = {
        "size": THREEDMK_HEADER_SIZE,
        "row_count": row_count,
        "unknown_u32_at_0x04": unknown_04,
        "magic_offset": 8,
        "magic_ascii": "3DMK",
        "reserved_u32_at_0x0C": reserved_0c,
        "relative_offset_base": THREEDMK_RELATIVE_BASE,
        "payload_relative_offset": payload_rel,
        "payload_actual_offset": payload_start,
        "reserved_u32_at_0x14": reserved_14,
        "row_size": THREEDMK_ROW_SIZE,
    }
    return ParsedModel(
        profile=PROFILE_3DMK,
        data=data,
        header=header,
        rows=tuple(rows),
        sections=sections,
        offset_references=tuple(references),
        candidate_regions=tuple(regions),
        confidence="strict magic plus observed header/table invariants",
    )


def parse_model_candidate(data: bytes) -> ParsedModel:
    """Parse the strictly bounded magic-free profile observed in 15 US records."""

    if len(data) < MODEL_CANDIDATE_HEADER_SIZE + MODEL_CANDIDATE_ROW_SIZE:
        raise ModelMapError("model candidate is too small for its header and row table")
    unknown_00, unknown_04, row_count = _u32_words(data, 0, 3)
    if unknown_00 != MODEL_CANDIDATE_WORD0:
        raise ModelMapError(
            f"model candidate opaque word 0 is {unknown_00}, expected observed value "
            f"{MODEL_CANDIDATE_WORD0}"
        )
    if row_count != MODEL_CANDIDATE_ROW_COUNT:
        raise ModelMapError(
            f"model candidate row count is {row_count}, expected observed value "
            f"{MODEL_CANDIDATE_ROW_COUNT}"
        )

    table_end = MODEL_CANDIDATE_HEADER_SIZE + row_count * MODEL_CANDIDATE_ROW_SIZE
    if table_end > len(data):
        raise ModelMapError("model candidate row table exceeds the record")

    raw_rows = [
        _u32_words(
            data,
            MODEL_CANDIDATE_HEADER_SIZE + row_id * MODEL_CANDIDATE_ROW_SIZE,
            MODEL_CANDIDATE_ROW_SIZE // 4,
        )
        for row_id in range(row_count)
    ]
    if raw_rows[0][2] != len(data) - MODEL_CANDIDATE_RELATIVE_BASE:
        raise ModelMapError("model candidate first-row end marker does not reach EOF")
    if any(row[2] != 0 for row in raw_rows[1:]):
        raise ModelMapError("model candidate later end-marker words are not zero")
    if any(row[3] != row[5] for row in raw_rows):
        raise ModelMapError("model candidate duplicated opaque count words differ")
    if any(row[6] != 0 for row in raw_rows):
        raise ModelMapError("model candidate reserved row word is not zero")

    variable_start = MODEL_CANDIDATE_RELATIVE_BASE + raw_rows[0][4]
    fixed_start = MODEL_CANDIDATE_RELATIVE_BASE + raw_rows[0][0]
    if variable_start != table_end:
        raise ModelMapError("model candidate variable stream does not follow the row table")
    if not table_end <= variable_start <= fixed_start <= len(data):
        raise ModelMapError("model candidate major stream boundaries are out of order")

    variable_offsets = [
        MODEL_CANDIDATE_RELATIVE_BASE + row[4] for row in raw_rows
    ]
    if any(offset % 4 for offset in variable_offsets):
        raise ModelMapError("model candidate variable-stream offset is not aligned")
    if any(
        offset < variable_start or offset > fixed_start for offset in variable_offsets
    ):
        raise ModelMapError("model candidate variable-stream offset is out of bounds")
    if any(first > second for first, second in zip(variable_offsets, variable_offsets[1:])):
        raise ModelMapError("model candidate variable-stream offsets go backwards")

    expected_relative = raw_rows[0][0]
    fixed_ranges: list[dict[str, object]] = []
    for row_id, row in enumerate(raw_rows):
        if row[0] != expected_relative:
            raise ModelMapError(
                f"model candidate fixed-stride row {row_id} is not contiguous"
            )
        actual = MODEL_CANDIDATE_RELATIVE_BASE + row[0]
        size = row[1] * MODEL_CANDIDATE_FIXED_STRIDE
        if actual + size > len(data):
            raise ModelMapError(
                f"model candidate fixed-stride row {row_id} exceeds the record"
            )
        fixed_ranges.append(
            {
                "row_id": row_id,
                "relative_offset": row[0],
                "actual_offset": actual,
                "count": row[1],
                "stride": MODEL_CANDIDATE_FIXED_STRIDE,
                "size": size,
                "end_offset": actual + size,
            }
        )
        expected_relative += size
    if MODEL_CANDIDATE_RELATIVE_BASE + expected_relative != len(data):
        raise ModelMapError("model candidate fixed-stride ranges do not end at EOF")

    next_variable: dict[int, int] = {}
    unique_variable = sorted(set(variable_offsets) | {fixed_start})
    for start, end in zip(unique_variable, unique_variable[1:]):
        next_variable[start] = end

    rows: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    for row_id, (words, fixed_range, variable_offset) in enumerate(
        zip(raw_rows, fixed_ranges, variable_offsets)
    ):
        variable_end = next_variable.get(variable_offset, fixed_start)
        row_offset = MODEL_CANDIDATE_HEADER_SIZE + row_id * MODEL_CANDIDATE_ROW_SIZE
        fixed_reference = {
            "row_id": row_id,
            "word_index": 0,
            "relative_offset": words[0],
            "actual_offset": int(fixed_range["actual_offset"]),
            "status": "proved_fixed_stride8_offset",
        }
        variable_reference = {
            "row_id": row_id,
            "word_index": 4,
            "relative_offset": words[4],
            "actual_offset": variable_offset,
            "status": "bounded_monotonic_offset",
        }
        references.extend((fixed_reference, variable_reference))
        rows.append(
            {
                "id": row_id,
                "offset": row_offset,
                "size": MODEL_CANDIDATE_ROW_SIZE,
                "words_u32": list(words),
                "words_hex": [f"0x{value:08X}" for value in words],
                "fixed_stride8_range": fixed_range,
                "variable_stream_candidate_span": {
                    "offset": variable_offset,
                    "end_offset": variable_end,
                    "size": variable_end - variable_offset,
                    "note": "span is delimited by the next distinct offset; opaque count words are not used as a byte size",
                },
                "offset_references": [fixed_reference, variable_reference],
                "unknown_duplicate_count": words[3],
            }
        )

    sections = (
        RawSection(
            0,
            "header",
            0,
            MODEL_CANDIDATE_HEADER_SIZE,
            "fixed observed envelope; field meanings remain unknown",
        ),
        RawSection(
            1,
            "row_table",
            MODEL_CANDIDATE_HEADER_SIZE,
            table_end - MODEL_CANDIDATE_HEADER_SIZE,
            "header row_count multiplied by the observed 28-byte row size",
        ),
        RawSection(
            2,
            "variable_stream",
            variable_start,
            fixed_start - variable_start,
            "first bounded row offset through the first fixed-stride8 offset",
        ),
        RawSection(
            3,
            "fixed_stride8_stream",
            fixed_start,
            len(data) - fixed_start,
            "row offsets and counts form an exact contiguous 8-byte-stride cover",
        ),
    )
    header: dict[str, object] = {
        "size": MODEL_CANDIDATE_HEADER_SIZE,
        "unknown_u32_at_0x00": unknown_00,
        "unknown_u32_at_0x04": unknown_04,
        "row_count": row_count,
        "row_size": MODEL_CANDIDATE_ROW_SIZE,
        "relative_offset_base": MODEL_CANDIDATE_RELATIVE_BASE,
        "variable_stream_actual_offset": variable_start,
        "fixed_stride8_stream_actual_offset": fixed_start,
    }
    return ParsedModel(
        profile=PROFILE_STAGE_CANDIDATE,
        data=data,
        header=header,
        rows=tuple(rows),
        sections=sections,
        offset_references=tuple(references),
        candidate_regions=tuple(),
        confidence=(
            "strict magic-free observed fingerprint; exact US corpus association is "
            "model-like but semantic stage identity is unproved"
        ),
    )


def detect_model(data: bytes) -> ParsedModel | None:
    if len(data) >= 12 and data[8:12] == THREEDMK_MAGIC:
        return parse_3dmk(data)
    if len(data) >= 12:
        word0, _word1, word2 = _u32_words(data, 0, 3)
        if word0 == MODEL_CANDIDATE_WORD0 and word2 == MODEL_CANDIDATE_ROW_COUNT:
            try:
                return parse_model_candidate(data)
            except ModelMapError:
                return None
    return None


def _record_document(record: ModelRecord) -> dict[str, object]:
    entry = record.entry
    parsed = record.parsed
    document: dict[str, object] = {
        "id": entry.id,
        "sector": entry.sector,
        "bns_offset": entry.offset,
        "bns_end_offset": entry.end_offset,
        "size": entry.size,
        "sha256": hashlib.sha256(parsed.data).hexdigest(),
        "profile": parsed.profile,
        "profile_confidence": parsed.confidence,
        "semantic_name": None,
        "header": parsed.header,
        "sections": [
            _section_document(parsed.data, section) for section in parsed.sections
        ],
        "rows": list(parsed.rows),
        "offset_references": list(parsed.offset_references),
        "entropy_blocks": _entropy_blocks(parsed.data),
    }
    if parsed.candidate_regions:
        document["candidate_regions"] = list(parsed.candidate_regions)
        document["candidate_region_warning"] = (
            "offset-derived navigation intervals are not asserted semantic sections"
        )
    return document


def scan_models(
    source: bns_tool.BnsSource, entries: Sequence[bns_tool.TableEntry]
) -> list[ModelRecord]:
    bns_tool.validate_source_capacity(source, entries)
    records: list[ModelRecord] = []
    for entry in entries:
        if entry.size < 12:
            continue
        prefix = source.read_at(entry.offset, min(entry.size, THREEDMK_HEADER_SIZE))
        is_3dmk = prefix[8:12] == THREEDMK_MAGIC
        is_candidate = False
        if not is_3dmk and len(prefix) >= 12:
            word0, _word1, word2 = _u32_words(prefix, 0, 3)
            is_candidate = (
                word0 == MODEL_CANDIDATE_WORD0
                and word2 == MODEL_CANDIDATE_ROW_COUNT
            )
        if not (is_3dmk or is_candidate):
            continue

        data = source.read_at(entry.offset, entry.size)
        if is_3dmk:
            parsed = parse_3dmk(data)
        else:
            try:
                parsed = parse_model_candidate(data)
            except ModelMapError:
                continue
        records.append(ModelRecord(entry=entry, parsed=parsed))
    return records


def build_inventory(
    records: Sequence[ModelRecord],
    *,
    source: bns_tool.BnsSource,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> dict[str, object]:
    documents = [_record_document(record) for record in records]
    counts: dict[str, int] = {}
    for document in documents:
        profile = str(document["profile"])
        counts[profile] = counts.get(profile, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": bns_tool.GAME_ID,
        "tool_boundary": (
            "read-only structural map; numeric IDs only; no model import, rebuild, "
            "character names, or stage names"
        ),
        "executable": {"path": str(exe_path), "sha256": exe_sha256},
        "table": {
            "file_offset": f"0x{bns_tool.TABLE_FILE_OFFSET:X}",
            "entry_count": bns_tool.TABLE_ENTRY_COUNT,
            "sha256": table_sha256,
        },
        "source": source.metadata(),
        "scan": {
            "bns_records_scanned": bns_tool.TABLE_ENTRY_COUNT,
            "model_records_found": len(documents),
            "profile_counts": {key: counts[key] for key in sorted(counts)},
        },
        "records": documents,
    }


CSV_FIELDS = (
    "bns_id",
    "profile",
    "section_id",
    "section_name",
    "offset",
    "end_offset",
    "size",
    "sha256",
    "entropy",
    "zero_fraction",
    "printable_ascii_fraction",
    "basis",
)


def _atomic_write_text(path: Path, emitter: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            emitter(handle)  # type: ignore[operator]
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_json(path: Path, inventory: dict[str, object]) -> None:
    def emit(handle: TextIO) -> None:
        json.dump(inventory, handle, indent=2, sort_keys=False)
        handle.write("\n")

    _atomic_write_text(path, emit)


def _emit_csv(handle: TextIO, inventory: dict[str, object]) -> None:
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for record in inventory["records"]:  # type: ignore[assignment]
        for section in record["sections"]:
            writer.writerow(
                {
                    "bns_id": record["id"],
                    "profile": record["profile"],
                    "section_id": section["id"],
                    "section_name": section["name"],
                    "offset": section["offset"],
                    "end_offset": section["end_offset"],
                    "size": section["size"],
                    "sha256": section["sha256"],
                    "entropy": section["entropy"],
                    "zero_fraction": section["zero_fraction"],
                    "printable_ascii_fraction": section[
                        "printable_ascii_fraction"
                    ],
                    "basis": section["basis"],
                }
            )


def write_csv(path: Path, inventory: dict[str, object]) -> None:
    _atomic_write_text(path, lambda handle: _emit_csv(handle, inventory))


def _check_outputs(paths: Iterable[Path], *, force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        raise ModelMapError(
            "refusing to overwrite existing output(s): "
            + ", ".join(str(path) for path in existing)
            + "; use --force"
        )


def _path_identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _require_distinct_paths(named_paths: Sequence[tuple[str, Path]]) -> None:
    seen: dict[str, str] = {}
    for label, path in named_paths:
        identity = _path_identity(path)
        if identity in seen:
            raise ModelMapError(f"{label} path must differ from {seen[identity]} path")
        seen[identity] = label


def _select_records(
    records: Sequence[ModelRecord], specification: str | None
) -> list[ModelRecord]:
    by_id = {record.entry.id: record for record in records}
    if specification is None or specification.strip().casefold() == "all":
        return [by_id[entry_id] for entry_id in sorted(by_id)]
    selected_ids = bns_tool.parse_ids(specification)
    unavailable = [entry_id for entry_id in selected_ids if entry_id not in by_id]
    if unavailable:
        raise ModelMapError(
            "selected BNS ID(s) do not match a strict model profile: "
            + ", ".join(f"{entry_id:03d}" for entry_id in unavailable)
        )
    return [by_id[entry_id] for entry_id in selected_ids]


def extract_sections(
    records: Sequence[ModelRecord],
    inventory: dict[str, object],
    output_directory: Path,
    *,
    force: bool,
) -> list[Path]:
    payload_paths: list[Path] = []
    work: list[tuple[Path, bytes]] = []
    for record in records:
        record_directory = output_directory / f"{record.entry.id:03d}"
        for section in record.parsed.sections:
            path = record_directory / f"section_{section.id:03d}_{section.name}.bin"
            payload = record.parsed.data[section.offset : section.end_offset]
            payload_paths.append(path)
            work.append((path, payload))

    manifest_json = output_directory / "model_map.json"
    manifest_csv = output_directory / "sections.csv"
    _check_outputs([*payload_paths, manifest_json, manifest_csv], force=force)
    for path, payload in work:
        _atomic_write_bytes(path, payload)

    selected_ids = [record.entry.id for record in records]
    selected_set = set(selected_ids)
    extraction_inventory = dict(inventory)
    extraction_inventory["records"] = [
        record
        for record in inventory["records"]  # type: ignore[assignment]
        if int(record["id"]) in selected_set
    ]
    extraction_inventory["scan"] = dict(inventory["scan"])  # type: ignore[arg-type]
    extraction_inventory["scan"]["model_records_selected"] = len(selected_ids)  # type: ignore[index]
    extraction_inventory["extraction"] = {
        "selected_ids": selected_ids,
        "section_files_written": len(payload_paths),
        "output_naming": "NNN/section_SSS_name.bin",
    }
    write_json(manifest_json, extraction_inventory)
    write_csv(manifest_csv, extraction_inventory)
    return payload_paths


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--exe",
        type=Path,
        default=Path("disc/SLUS_004.02"),
        help="verified Tekken 3 USA executable (default: disc/SLUS_004.02)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="standalone TEKKEN3.BNS or raw/cooked Track 1 image",
    )
    parser.add_argument(
        "--source-format",
        choices=("auto", "bns", "track"),
        default="auto",
        help="source detection mode (default: auto)",
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build conservative numeric structural maps for Tekken 3 USA "
            "3DMK and model-candidate BNS records."
        )
    )
    parser.add_argument("--version", action="version", version="model_map 1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory", help="scan all BNS records and write structural JSON/CSV"
    )
    _add_source_arguments(inventory)
    inventory.add_argument("--json", type=Path, help="deterministic JSON output")
    inventory.add_argument("--csv", type=Path, help="major-section CSV output")
    inventory.add_argument("--force", action="store_true", help="overwrite outputs")

    extract = subparsers.add_parser(
        "extract", help="extract bounded raw sections for selected numeric IDs"
    )
    _add_source_arguments(extract)
    extract.add_argument(
        "--output",
        type=Path,
        default=Path("workspace/models/sections"),
        help="local output directory (default: workspace/models/sections)",
    )
    extract.add_argument(
        "--ids", help="model BNS IDs such as 56,71,75-79 (default: all detected)"
    )
    extract.add_argument("--force", action="store_true", help="overwrite outputs")
    return parser


def _load(
    args: argparse.Namespace,
) -> tuple[bns_tool.BnsSource, list[ModelRecord], dict[str, object]]:
    entries, exe_sha256, table_sha256 = bns_tool.load_us_table(args.exe)
    source = bns_tool.open_bns_source(args.source, args.source_format)
    source.__enter__()
    try:
        records = scan_models(source, entries)
        inventory = build_inventory(
            records,
            source=source,
            exe_path=args.exe,
            exe_sha256=exe_sha256,
            table_sha256=table_sha256,
        )
    except Exception:
        source.__exit__(None, None, None)
        raise
    return source, records, inventory


def run(args: argparse.Namespace) -> int:
    if args.command == "inventory":
        outputs = [path for path in (args.json, args.csv) if path is not None]
        _require_distinct_paths(
            [("executable", args.exe), ("source", args.source)]
            + [("inventory output", path) for path in outputs]
        )
        _check_outputs(outputs, force=args.force)
        source, records, inventory = _load(args)
        try:
            if args.json is not None:
                write_json(args.json, inventory)
            if args.csv is not None:
                write_csv(args.csv, inventory)
            if args.json is None and args.csv is None:
                json.dump(inventory, sys.stdout, indent=2)
                sys.stdout.write("\n")
        finally:
            source.__exit__(None, None, None)
        counts = inventory["scan"]["profile_counts"]  # type: ignore[index]
        summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        print(f"Mapped {len(records)} model-like record(s) ({summary}).", file=sys.stderr)
        return 0

    if args.command == "extract":
        _require_distinct_paths(
            [
                ("executable", args.exe),
                ("source", args.source),
                ("output directory", args.output),
            ]
        )
        source, records, inventory = _load(args)
        try:
            selected = _select_records(records, args.ids)
            written = extract_sections(
                selected, inventory, args.output, force=args.force
            )
        finally:
            source.__exit__(None, None, None)
        print(
            f"Extracted {len(written)} structural section(s) from "
            f"{len(selected)} numeric BNS record(s) to {args.output}."
        )
        return 0

    raise ModelMapError(f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    try:
        return run(parser.parse_args(argv))
    except (ModelMapError, bns_tool.BnsToolError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
