#!/usr/bin/env python3
"""Inspect, extract, and locally rebuild Tekken 3 BNS ARC records.

The tool operates on one already-extracted top-level BNS record.  It never
writes to a retail disc image or TEKKEN3.BNS.  Only the compact ARC directory
layout observed in the verified Tekken 3 (USA) records is accepted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Sequence, TextIO


SCHEMA_VERSION = 1
FORMAT_NAME = "tekken3-bns-arc"
ALIGNMENT = 4
MAX_MEMBER_COUNT = 0xFF
UINT32_MAX = 0xFFFFFFFF
CHUNK_SIZE = 64 * 1024


class ArcToolError(RuntimeError):
    """A validation or output error safe to show to a mod author."""


@dataclass(frozen=True)
class ArcMember:
    """One zero-based member span in a validated ARC record."""

    id: int
    offset: int
    size: int

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class ArcArchive:
    """A strict ARC record plus its parsed directory."""

    data: bytes
    members: tuple[ArcMember, ...]
    directory_size: int
    data_offset: int
    header_padding: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class ReplacementSpec:
    """One requested numeric member and author-supplied payload."""

    id: int
    path: Path


def _read_file(path: Path, *, label: str) -> bytes:
    if not path.is_file():
        raise ArcToolError(f"{label} does not exist or is not a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ArcToolError(f"cannot read {label} {path}: {exc}") from exc


def parse_archive(data: bytes) -> ArcArchive:
    """Parse the canonical ARC layout used by top-level Tekken 3 BNS records.

    The verified records use a count followed by ``offset,size`` pairs, up to
    15 optional ``0xFF`` directory-padding bytes, then contiguous
    four-byte-aligned member spans. Zero-size members are valid.
    """

    if len(data) < 12:
        raise ArcToolError("ARC record is too small for a directory and one member")
    if len(data) > UINT32_MAX:
        raise ArcToolError("ARC record exceeds the format's 32-bit size limit")

    member_count = struct.unpack_from("<I", data, 0)[0]
    if not 1 <= member_count <= MAX_MEMBER_COUNT:
        raise ArcToolError(
            f"ARC member count must be 1-{MAX_MEMBER_COUNT}, found {member_count}"
        )

    directory_size = 4 + member_count * 8
    if directory_size > len(data):
        raise ArcToolError("ARC directory extends beyond the record")
    members: list[ArcMember] = []
    for member_id in range(member_count):
        offset, size = struct.unpack_from("<II", data, 4 + member_id * 8)
        members.append(ArcMember(member_id, offset, size))

    data_offset = members[0].offset
    if (
        data_offset < directory_size
        or data_offset - directory_size > 15
        or data_offset % ALIGNMENT
    ):
        raise ArcToolError(
            "ARC first member must begin at a four-byte-aligned offset no more "
            "than 15 padding bytes after the directory"
        )
    if data_offset > len(data):
        raise ArcToolError("ARC record ends before its aligned data area")

    header_padding = data[directory_size:data_offset]
    if header_padding != b"\xFF" * len(header_padding):
        raise ArcToolError("ARC directory alignment padding is not canonical 0xFF")

    expected_offset = data_offset
    for member in members:
        if member.offset != expected_offset:
            raise ArcToolError(
                f"ARC member {member.id:03d} is not contiguous (expected offset "
                f"0x{expected_offset:X}, found 0x{member.offset:X})"
            )
        if member.offset % ALIGNMENT or member.size % ALIGNMENT:
            raise ArcToolError(
                f"ARC member {member.id:03d} offset and size must be four-byte aligned"
            )
        if member.size > len(data) - member.offset:
            raise ArcToolError(f"ARC member {member.id:03d} extends beyond the record")
        expected_offset = member.end_offset

    if expected_offset != len(data):
        raise ArcToolError(
            f"ARC directory covers 0x{expected_offset:X} bytes but record size is "
            f"0x{len(data):X}"
        )

    return ArcArchive(
        data=data,
        members=tuple(members),
        directory_size=directory_size,
        data_offset=data_offset,
        header_padding=header_padding,
    )


def load_archive(path: Path) -> ArcArchive:
    return parse_archive(_read_file(path, label="ARC input"))


def _member_magic(payload: bytes) -> tuple[str, str]:
    """Return only conservative browsing hints, not semantic validation."""

    if payload[:4] == b"\x10\x00\x00\x00":
        return "TIM_MAGIC", ".tim"
    if payload[:4] == b"pBAV":
        return "VAB_MAGIC", ".vab"
    if len(payload) >= 12 and payload[8:12] == b"3DMK":
        return "3DMK_MAGIC", ".3dm"
    if not payload:
        return "EMPTY", ".bin"
    return "UNKNOWN", ".bin"


def build_inventory(archive: ArcArchive) -> dict[str, object]:
    """Build a deterministic, path-independent inventory document."""

    members: list[dict[str, object]] = []
    for member in archive.members:
        payload = archive.data[member.offset : member.end_offset]
        magic_hint, extension = _member_magic(payload)
        members.append(
            {
                "id": member.id,
                "offset": member.offset,
                "size": member.size,
                "end_offset": member.end_offset,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "magic_hint": magic_hint,
                "extension": extension,
                "suggested_filename": f"{member.id:03d}{extension}",
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "format": FORMAT_NAME,
        "archive": {
            "size": len(archive.data),
            "sha256": archive.sha256,
        },
        "layout": {
            "member_count": len(archive.members),
            "directory_size": archive.directory_size,
            "data_offset": archive.data_offset,
            "alignment": ALIGNMENT,
            "header_padding_hex": archive.header_padding.hex(),
        },
        "members": members,
    }


CSV_FIELDS = (
    "id",
    "offset",
    "size",
    "end_offset",
    "sha256",
    "magic_hint",
    "extension",
    "suggested_filename",
)


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


def _atomic_write_text(path: Path, writer: object) -> None:
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
            writer(handle)  # type: ignore[operator]
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_json(path: Path, document: dict[str, object]) -> None:
    def emit(handle: TextIO) -> None:
        json.dump(document, handle, indent=2, sort_keys=False)
        handle.write("\n")

    _atomic_write_text(path, emit)


def write_csv(path: Path, inventory: dict[str, object]) -> None:
    def emit(handle: TextIO) -> None:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(inventory["members"])  # type: ignore[arg-type]

    _atomic_write_text(path, emit)


def _check_outputs(paths: Iterable[Path], *, force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise ArcToolError(
            f"refusing to overwrite existing output(s): {joined}; use --force"
        )


def _require_distinct_paths(named_paths: Sequence[tuple[str, Path]]) -> None:
    """Reject aliases which could turn a requested write into source loss."""

    seen: dict[str, str] = {}
    for label, path in named_paths:
        try:
            identity = os.path.normcase(str(path.resolve()))
        except OSError as exc:
            raise ArcToolError(f"cannot resolve {label} path {path}: {exc}") from exc
        if identity in seen:
            raise ArcToolError(f"{label} path must differ from {seen[identity]} path")
        seen[identity] = label


def parse_member_ids(specification: str | None, member_count: int) -> list[int]:
    if specification is None or specification.strip().casefold() == "all":
        return list(range(member_count))

    selected: set[int] = set()
    for raw_part in specification.split(","):
        part = raw_part.strip()
        if not part:
            raise ArcToolError("empty item in --ids selection")
        if "-" in part:
            pieces = part.split("-")
            if len(pieces) != 2 or not all(piece.strip().isdecimal() for piece in pieces):
                raise ArcToolError(f"invalid member range: {part}")
            first, last = (int(piece.strip(), 10) for piece in pieces)
            if first > last:
                raise ArcToolError(f"descending member range is not allowed: {part}")
            selected.update(range(first, last + 1))
        elif part.isdecimal():
            selected.add(int(part, 10))
        else:
            raise ArcToolError(f"invalid member ID: {part}")

    invalid = sorted(value for value in selected if not 0 <= value < member_count)
    if invalid:
        raise ArcToolError(
            f"member ID(s) outside 0-{member_count - 1}: "
            + ", ".join(map(str, invalid))
        )
    return sorted(selected)


def extract_members(
    archive: ArcArchive,
    output_directory: Path,
    selected_ids: Sequence[int],
    *,
    force: bool,
) -> list[Path]:
    inventory = build_inventory(archive)
    by_id = {item["id"]: item for item in inventory["members"]}  # type: ignore[index]
    payload_paths = [
        output_directory / str(by_id[member_id]["suggested_filename"])
        for member_id in selected_ids
    ]
    manifest_path = output_directory / "arc_manifest.json"
    _check_outputs([*payload_paths, manifest_path], force=force)
    output_directory.mkdir(parents=True, exist_ok=True)

    for member_id, path in zip(selected_ids, payload_paths):
        member = archive.members[member_id]
        _atomic_write_bytes(path, archive.data[member.offset : member.end_offset])

    extraction = dict(inventory)
    extraction["extraction"] = {
        "selected_ids": list(selected_ids),
        "payload_files_written": len(payload_paths),
    }
    write_json(manifest_path, extraction)
    return payload_paths


def parse_replacements(values: Iterable[str]) -> list[ReplacementSpec]:
    replacements: list[ReplacementSpec] = []
    seen: set[int] = set()
    for value in values:
        if "=" not in value:
            raise ArcToolError(f"replacement must use MEMBER=FILE syntax, got {value!r}")
        raw_id, raw_path = value.split("=", 1)
        raw_id = raw_id.strip()
        raw_path = raw_path.strip()
        if not raw_id.isdecimal():
            raise ArcToolError(f"replacement member is not a decimal integer: {raw_id!r}")
        member_id = int(raw_id, 10)
        if member_id in seen:
            raise ArcToolError(f"replacement member {member_id} was supplied more than once")
        if not raw_path:
            raise ArcToolError(f"replacement member {member_id} has an empty file path")
        seen.add(member_id)
        replacements.append(ReplacementSpec(member_id, Path(raw_path)))
    if not replacements:
        raise ArcToolError("at least one --replacement MEMBER=FILE is required")
    return sorted(replacements, key=lambda item: item.id)


def rebuild_archive(
    archive: ArcArchive,
    replacements: Sequence[ReplacementSpec],
    *,
    allow_resize: bool,
) -> tuple[bytes, dict[str, object]]:
    """Return a deterministic rebuilt record and a game-data-free report."""

    replacement_by_id: dict[int, bytes] = {}
    replacement_report: list[dict[str, object]] = []
    for replacement in replacements:
        if replacement.id in replacement_by_id:
            raise ArcToolError(
                f"replacement member {replacement.id} was supplied more than once"
            )
        if not 0 <= replacement.id < len(archive.members):
            raise ArcToolError(
                f"replacement member {replacement.id} is outside 0-{len(archive.members) - 1}"
            )
        payload = _read_file(replacement.path, label=f"replacement {replacement.id:03d}")
        stock_size = archive.members[replacement.id].size
        if not allow_resize and len(payload) != stock_size:
            raise ArcToolError(
                f"replacement member {replacement.id:03d} must have exact stock size "
                f"{stock_size}, got {len(payload)}; use --allow-resize only for an "
                "intentional ARC layout change"
            )
        if len(payload) % ALIGNMENT:
            raise ArcToolError(
                f"replacement member {replacement.id:03d} size {len(payload)} is not "
                "four-byte aligned; pad the authored payload deliberately"
            )
        if len(payload) > UINT32_MAX:
            raise ArcToolError(
                f"replacement member {replacement.id:03d} exceeds the 32-bit size limit"
            )
        replacement_by_id[replacement.id] = payload
        replacement_report.append(
            {
                "id": replacement.id,
                "stock_size": stock_size,
                "replacement_size": len(payload),
                "replacement_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    payloads: list[bytes] = []
    for member in archive.members:
        payloads.append(
            replacement_by_id.get(
                member.id, archive.data[member.offset : member.end_offset]
            )
        )

    rebuilt_size = archive.data_offset + sum(len(payload) for payload in payloads)
    if rebuilt_size > UINT32_MAX:
        raise ArcToolError("rebuilt ARC exceeds the format's 32-bit size limit")

    directory = bytearray(struct.pack("<I", len(payloads)))
    offset = archive.data_offset
    for payload in payloads:
        directory.extend(struct.pack("<II", offset, len(payload)))
        offset += len(payload)
    directory.extend(archive.header_padding)
    rebuilt = bytes(directory) + b"".join(payloads)

    # Validate our own output before it reaches another tool or the runtime.
    parse_archive(rebuilt)
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "format": FORMAT_NAME,
        "mode": "resize" if allow_resize else "exact-size",
        "stock_archive": {
            "size": len(archive.data),
            "sha256": archive.sha256,
        },
        "rebuilt_archive": {
            "size": len(rebuilt),
            "sha256": hashlib.sha256(rebuilt).hexdigest(),
            "size_delta": len(rebuilt) - len(archive.data),
            "exact_top_level_size": len(rebuilt) == len(archive.data),
        },
        "replacements": replacement_report,
    }
    return rebuilt, report


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, extract, and locally rebuild strict Tekken 3 BNS ARC records."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="validate and catalog an ARC record")
    inventory.add_argument("--input", type=Path, required=True, help="extracted ARC record")
    inventory.add_argument("--json", type=Path, help="write deterministic JSON inventory")
    inventory.add_argument("--csv", type=Path, help="write member CSV inventory")
    inventory.add_argument("--force", action="store_true", help="overwrite inventory outputs")

    extract = subparsers.add_parser("extract", help="extract selected numeric ARC members")
    extract.add_argument("--input", type=Path, required=True, help="extracted ARC record")
    extract.add_argument("--output", type=Path, required=True, help="new/existing workspace directory")
    extract.add_argument("--ids", help="members such as 0,2-4 (default: all)")
    extract.add_argument("--force", action="store_true", help="overwrite selected outputs")

    rebuild = subparsers.add_parser("rebuild", help="rebuild an ARC from selected replacements")
    rebuild.add_argument("--input", type=Path, required=True, help="verified stock ARC record")
    rebuild.add_argument(
        "--replacement",
        action="append",
        required=True,
        metavar="MEMBER=FILE",
        help="numeric ARC member and author-owned payload; repeat as needed",
    )
    rebuild.add_argument("--output", type=Path, required=True, help="rebuilt ARC output")
    rebuild.add_argument("--report", type=Path, help="optional deterministic JSON rebuild report")
    rebuild.add_argument(
        "--allow-resize",
        action="store_true",
        help="allow deliberately four-byte-aligned member size changes",
    )
    rebuild.add_argument("--force", action="store_true", help="overwrite output/report")
    return parser


def run(args: argparse.Namespace) -> int:
    archive = load_archive(args.input)

    if args.command == "inventory":
        outputs = [path for path in (args.json, args.csv) if path is not None]
        _require_distinct_paths(
            [("input", args.input)]
            + [
                (label, path)
                for label, path in (("JSON output", args.json), ("CSV output", args.csv))
                if path is not None
            ]
        )
        _check_outputs(outputs, force=args.force)
        inventory = build_inventory(archive)
        if args.json is not None:
            write_json(args.json, inventory)
        if args.csv is not None:
            write_csv(args.csv, inventory)
        hints: dict[str, int] = {}
        for member in inventory["members"]:  # type: ignore[assignment]
            hint = str(member["magic_hint"])
            hints[hint] = hints.get(hint, 0) + 1
        summary = ", ".join(f"{key}={hints[key]}" for key in sorted(hints))
        print(
            f"ARC OK: {len(archive.members)} members, {len(archive.data)} bytes"
            + (f" ({summary})" if summary else "")
        )
        return 0

    if args.command == "extract":
        selected = parse_member_ids(args.ids, len(archive.members))
        written = extract_members(
            archive, args.output, selected, force=args.force
        )
        print(f"Extracted {len(written)} ARC member(s) to {args.output}")
        return 0

    if args.command == "rebuild":
        replacements = parse_replacements(args.replacement)
        outputs = [args.output] + ([args.report] if args.report is not None else [])
        _require_distinct_paths(
            [("input", args.input), ("ARC output", args.output)]
            + ([('report output', args.report)] if args.report is not None else [])
        )
        _check_outputs(outputs, force=args.force)
        rebuilt, report = rebuild_archive(
            archive, replacements, allow_resize=args.allow_resize
        )
        _atomic_write_bytes(args.output, rebuilt)
        if args.report is not None:
            write_json(args.report, report)
        compatibility = report["rebuilt_archive"]["exact_top_level_size"]  # type: ignore[index]
        print(
            f"Rebuilt ARC: {len(rebuilt)} bytes, {len(replacements)} replacement(s); "
            f"bns_mod exact-size compatible={'yes' if compatibility else 'no'}"
        )
        return 0

    raise ArcToolError(f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    try:
        return run(parser.parse_args(argv))
    except (ArcToolError, OSError, struct.error, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
