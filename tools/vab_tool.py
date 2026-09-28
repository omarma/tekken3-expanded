#!/usr/bin/env python3
"""Audit and reconstruct Tekken 3 USA split PlayStation VAB sound banks.

Tekken 3 stores each Sony VH record separately from its raw VB bytes.  The VB
is member 2 of the immediately following top-level BNS ARC record for every
verified bank in SLUS-00402.  This tool validates both containers and the SPU
ADPCM framing before concatenating ``VH + VB`` into a conventional .vab file.

Sources are always opened read-only.  The Python standard library is the only
runtime dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence, TextIO

try:
    from tools import bns_tool
except ModuleNotFoundError:  # Direct execution: ``python tools/vab_tool.py``.
    import bns_tool  # type: ignore[no-redef]


SCHEMA_VERSION = 1
SUPPORTED_VAB_VERSION = 7
VERIFIED_VB_MEMBER_INDEX = 2

# These pairs were verified against Tekken 3 USA (SLUS-00402).  Each VH record
# is immediately followed by an ARC whose member 2 is the matching raw VB.
VERIFIED_VH_IDS = (
    72,
    76,
    80,
    84,
    88,
    92,
    96,
    100,
    104,
    108,
    112,
    116,
    120,
    124,
    128,
    132,
    136,
    140,
    144,
    148,
    152,
    156,
    160,
    164,
    168,
    172,
    176,
    180,
    184,
    188,
    192,
    196,
    200,
    204,
    208,
    212,
    216,
    220,
    224,
    228,
    232,
    236,
    240,
    244,
    248,
    252,
    256,
    276,
)
VERIFIED_PAIRS = tuple((vh_id, vh_id + 1) for vh_id in VERIFIED_VH_IDS)


class VabToolError(RuntimeError):
    """A user-facing validation or reconstruction error."""


@dataclass(frozen=True)
class VhHeader:
    version: int
    vab_id: int
    declared_total_size: int
    program_count: int
    tone_count: int
    vag_count: int
    master_volume: int
    master_pan: int
    sample_size_units: tuple[int, ...]
    header_size: int

    @property
    def sample_sizes(self) -> tuple[int, ...]:
        """Raw byte lengths for VAG numbers 1 through ``vag_count``."""

        return tuple(units * 8 for units in self.sample_size_units[1 : self.vag_count + 1])

    @property
    def vb_size(self) -> int:
        return sum(self.sample_size_units) * 8


@dataclass(frozen=True)
class ArcMember:
    index: int
    offset: int
    size: int


@dataclass(frozen=True)
class ArcDirectory:
    members: tuple[ArcMember, ...]
    directory_size: int
    data_offset: int


@dataclass(frozen=True)
class PreparedPair:
    vh_entry: bns_tool.TableEntry
    arc_entry: bns_tool.TableEntry
    header: VhHeader
    arc: ArcDirectory
    vb_member: ArcMember
    vh_data: bytes
    arc_data: bytes
    vb_data: bytes

    @property
    def reconstructed(self) -> bytes:
        return self.vh_data + self.vb_data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_vh(data: bytes) -> VhHeader:
    """Strictly parse the split VH representation used by the US game."""

    if len(data) < 0xA20:
        raise VabToolError(f"VH is too small: 0x{len(data):X} bytes")
    if data[:4] != b"pBAV":
        raise VabToolError("VH magic is not pBAV")

    version, vab_id, declared_total_size = struct.unpack_from("<III", data, 4)
    reserved0, program_count, tone_count, vag_count = struct.unpack_from(
        "<HHHH", data, 0x10
    )
    master_volume, master_pan, _attribute1, _attribute2 = struct.unpack_from(
        "<BBBB", data, 0x18
    )
    reserved1 = struct.unpack_from("<I", data, 0x1C)[0]

    if version != SUPPORTED_VAB_VERSION:
        raise VabToolError(
            f"VH version is {version}; verified Tekken 3 banks use version "
            f"{SUPPORTED_VAB_VERSION}"
        )
    if vab_id != 0:
        raise VabToolError(f"VH bank ID is {vab_id}; verified banks use ID 0")
    if reserved0 != 0xEEEE or reserved1 != 0xFFFFFFFF:
        raise VabToolError("VH reserved markers do not match the verified format")
    if not 1 <= program_count <= 128:
        raise VabToolError(f"VH program count is outside 1-128: {program_count}")
    if not 1 <= tone_count <= program_count * 16:
        raise VabToolError(
            f"VH tone count {tone_count} is invalid for {program_count} program(s)"
        )
    if not 1 <= vag_count <= 254:
        raise VabToolError(f"VH VAG count is outside 1-254: {vag_count}")
    if master_volume > 0x7F or master_pan > 0x7F:
        raise VabToolError("VH master volume or pan is outside the 7-bit range")

    expected_header_size = 0xA20 + program_count * 0x200
    if len(data) != expected_header_size:
        raise VabToolError(
            f"VH size is 0x{len(data):X}; {program_count} program(s) require "
            f"exactly 0x{expected_header_size:X} bytes"
        )
    if declared_total_size <= len(data):
        raise VabToolError(
            f"VH declares total VAB size 0x{declared_total_size:X}, which leaves no VB"
        )

    program_tones = tuple(data[0x20 + index * 0x10] for index in range(program_count))
    if any(count > 16 for count in program_tones):
        raise VabToolError("VH program attribute table contains more than 16 tones")
    if sum(program_tones) != tone_count:
        raise VabToolError(
            "VH program tone counts do not add up to the header tone count"
        )

    size_table_offset = 0x820 + program_count * 0x200
    sample_size_units = struct.unpack_from("<256H", data, size_table_offset)
    if sample_size_units[0] != 0:
        raise VabToolError("VH VAG size-table sentinel at index 0 is not zero")

    active_units = sample_size_units[1 : vag_count + 1]
    if any(units == 0 for units in active_units):
        raise VabToolError("VH has a zero-sized active VAG")
    if any(units & 1 for units in active_units):
        raise VabToolError("VH VAG size is not aligned to a 16-byte SPU ADPCM block")
    if any(sample_size_units[vag_count + 1 :]):
        raise VabToolError("VH has nonzero VAG sizes beyond its declared VAG count")

    vb_size = sum(sample_size_units) * 8
    if declared_total_size != len(data) + vb_size:
        raise VabToolError(
            f"VH declares 0x{declared_total_size:X} total bytes, but its header and "
            f"VAG size table account for 0x{len(data) + vb_size:X}"
        )

    return VhHeader(
        version=version,
        vab_id=vab_id,
        declared_total_size=declared_total_size,
        program_count=program_count,
        tone_count=tone_count,
        vag_count=vag_count,
        master_volume=master_volume,
        master_pan=master_pan,
        sample_size_units=tuple(sample_size_units),
        header_size=len(data),
    )


def parse_arc(data: bytes) -> ArcDirectory:
    """Parse the small contiguous offset/size ARC directory used by BNS records."""

    if len(data) < 12:
        raise VabToolError("ARC is too small for a member directory")
    member_count = struct.unpack_from("<I", data, 0)[0]
    if not 1 <= member_count <= 0xFF:
        raise VabToolError(f"ARC member count is outside 1-255: {member_count}")

    directory_size = 4 + member_count * 8
    if directory_size > len(data):
        raise VabToolError("ARC member directory exceeds the record")

    members = tuple(
        ArcMember(index, *struct.unpack_from("<II", data, 4 + index * 8))
        for index in range(member_count)
    )
    first_offset = members[0].offset
    aligned_directory_size = (directory_size + 0xF) & ~0xF
    if first_offset != aligned_directory_size:
        raise VabToolError(
            f"ARC first member starts at 0x{first_offset:X}; expected the aligned "
            f"directory end 0x{aligned_directory_size:X}"
        )
    padding = data[directory_size:first_offset]
    if padding and padding != bytes((0xFF,)) * len(padding):
        raise VabToolError("ARC directory alignment padding is not the verified 0xFF marker")

    expected_offset = first_offset
    for member in members:
        if member.offset != expected_offset:
            raise VabToolError(
                f"ARC member {member.index} is not contiguous with the previous member"
            )
        if member.offset & 3 or member.size & 3:
            raise VabToolError(
                f"ARC member {member.index} offset or size is not 4-byte aligned"
            )
        if member.offset > len(data) or member.size > len(data) - member.offset:
            raise VabToolError(f"ARC member {member.index} exceeds the record")
        expected_offset = member.offset + member.size
    if expected_offset != len(data):
        raise VabToolError("ARC member directory does not consume the record exactly")

    return ArcDirectory(
        members=members,
        directory_size=directory_size,
        data_offset=first_offset,
    )


def validate_vb(data: bytes, header: VhHeader) -> None:
    """Validate raw VB length, sample boundaries, and SPU ADPCM block headers."""

    if len(data) != header.vb_size:
        raise VabToolError(
            f"VB has 0x{len(data):X} bytes; VH requires exactly 0x{header.vb_size:X}"
        )

    position = 0
    for sample_number, sample_size in enumerate(header.sample_sizes, start=1):
        sample = data[position : position + sample_size]
        if len(sample) != sample_size:
            raise VabToolError(f"VB ends inside VAG {sample_number}")
        if sample[:16] != bytes(16):
            raise VabToolError(
                f"VB VAG {sample_number} does not start with a zero SPU ADPCM block"
            )

        for block_offset in range(0, sample_size, 16):
            predictor_shift = sample[block_offset]
            flags = sample[block_offset + 1]
            predictor = predictor_shift >> 4
            shift = predictor_shift & 0x0F
            if predictor > 4 or shift > 12:
                raise VabToolError(
                    f"VB VAG {sample_number} has an invalid SPU ADPCM block header"
                )
            if flags & ~0x07:
                raise VabToolError(
                    f"VB VAG {sample_number} has unsupported SPU ADPCM flags "
                    f"0x{flags:02X}"
                )
        if not (sample[-15] & 0x01):
            raise VabToolError(f"VB VAG {sample_number} has no end flag on its last block")
        position += sample_size

    if position != len(data):
        raise VabToolError("VH VAG sizes do not consume the VB exactly")


def _validate_pair_ids(vh_id: int, arc_id: int) -> None:
    if (vh_id, arc_id) not in VERIFIED_PAIRS:
        raise VabToolError(
            f"BNS IDs {vh_id}/{arc_id} are not a verified Tekken 3 USA VH/ARC pair; "
            "run the audit command to list the 48 supported pairs"
        )


def prepare_pair(
    source: bns_tool.BnsSource,
    entries: Sequence[bns_tool.TableEntry],
    vh_id: int,
    arc_id: int,
) -> PreparedPair:
    """Read and strictly prove one known VH/ARC relationship."""

    _validate_pair_ids(vh_id, arc_id)
    if len(entries) != bns_tool.TABLE_ENTRY_COUNT:
        raise VabToolError(
            f"expected {bns_tool.TABLE_ENTRY_COUNT} BNS table entries, found {len(entries)}"
        )
    if entries[vh_id].id != vh_id or entries[arc_id].id != arc_id:
        raise VabToolError("BNS table entries are not indexed by their numeric IDs")
    if arc_id != vh_id + 1:
        raise VabToolError("verified VH and ARC records must be adjacent")

    vh_entry = entries[vh_id]
    arc_entry = entries[arc_id]
    vh_data = source.read_at(vh_entry.offset, vh_entry.size)
    header = parse_vh(vh_data)
    arc_data = source.read_at(arc_entry.offset, arc_entry.size)
    arc = parse_arc(arc_data)

    matching_members = tuple(
        member for member in arc.members if member.size == header.vb_size
    )
    if len(matching_members) != 1:
        raise VabToolError(
            f"ARC {arc_id:03d} has {len(matching_members)} members matching the "
            f"VH-required VB size 0x{header.vb_size:X}; expected exactly one"
        )
    vb_member = matching_members[0]
    if vb_member.index != VERIFIED_VB_MEMBER_INDEX:
        raise VabToolError(
            f"matching VB is ARC member {vb_member.index}; verified Tekken 3 banks "
            f"use member {VERIFIED_VB_MEMBER_INDEX}"
        )

    vb_data = arc_data[vb_member.offset : vb_member.offset + vb_member.size]
    validate_vb(vb_data, header)
    if len(vh_data) + len(vb_data) != header.declared_total_size:
        raise VabToolError("reconstructed VAB size does not match the VH declaration")

    return PreparedPair(
        vh_entry=vh_entry,
        arc_entry=arc_entry,
        header=header,
        arc=arc,
        vb_member=vb_member,
        vh_data=vh_data,
        arc_data=arc_data,
        vb_data=vb_data,
    )


def pair_manifest(pair: PreparedPair) -> dict[str, object]:
    reconstructed = pair.reconstructed
    return {
        "vh_id": pair.vh_entry.id,
        "arc_id": pair.arc_entry.id,
        "vb_member_index": pair.vb_member.index,
        "proof": {
            "known_us_pair": True,
            "adjacent_bns_records": pair.arc_entry.id == pair.vh_entry.id + 1,
            "unique_arc_member_size_match": True,
            "verified_member_index": pair.vb_member.index == VERIFIED_VB_MEMBER_INDEX,
            "declared_total_size_match": len(reconstructed)
            == pair.header.declared_total_size,
            "vag_size_table_match": len(pair.vb_data) == pair.header.vb_size,
            "spu_adpcm_blocks_validated": True,
        },
        "vh": {
            "sector": pair.vh_entry.sector,
            "offset": pair.vh_entry.offset,
            "size": pair.vh_entry.size,
            "sha256": _sha256(pair.vh_data),
        },
        "arc": {
            "sector": pair.arc_entry.sector,
            "offset": pair.arc_entry.offset,
            "size": pair.arc_entry.size,
            "sha256": _sha256(pair.arc_data),
            "member_count": len(pair.arc.members),
        },
        "vb": {
            "member_offset": pair.vb_member.offset,
            "size": len(pair.vb_data),
            "sha256": _sha256(pair.vb_data),
        },
        "vab_header": {
            "version": pair.header.version,
            "bank_id": pair.header.vab_id,
            "header_size": pair.header.header_size,
            "declared_total_size": pair.header.declared_total_size,
            "program_count": pair.header.program_count,
            "tone_count": pair.header.tone_count,
            "vag_count": pair.header.vag_count,
            "master_volume": pair.header.master_volume,
            "master_pan": pair.header.master_pan,
            "sample_sizes": list(pair.header.sample_sizes),
        },
        "reconstructed_vab": {
            "size": len(reconstructed),
            "sha256": _sha256(reconstructed),
        },
    }


def _base_manifest(
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
    source: bns_tool.BnsSource,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": bns_tool.GAME_ID,
        "executable": {"path": str(exe_path), "sha256": exe_sha256},
        "table": {
            "virtual_address": f"0x{bns_tool.TABLE_VIRTUAL_ADDRESS:08X}",
            "file_offset": f"0x{bns_tool.TABLE_FILE_OFFSET:X}",
            "entry_count": bns_tool.TABLE_ENTRY_COUNT,
            "sha256": table_sha256,
        },
        "source": source.metadata(),
    }


def build_audit_manifest(
    source: bns_tool.BnsSource,
    entries: Sequence[bns_tool.TableEntry],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> dict[str, object]:
    bns_tool.validate_source_capacity(source, entries)
    pairs = [pair_manifest(prepare_pair(source, entries, *ids)) for ids in VERIFIED_PAIRS]
    manifest = _base_manifest(
        exe_path=exe_path,
        exe_sha256=exe_sha256,
        table_sha256=table_sha256,
        source=source,
    )
    manifest.update(
        {
            "operation": "audit_vab_pairs",
            "verified_pair_count": len(pairs),
            "pairs": pairs,
        }
    )
    return manifest


def build_extraction_manifest(
    pair: PreparedPair,
    output_path: Path,
    source: bns_tool.BnsSource,
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> dict[str, object]:
    manifest = _base_manifest(
        exe_path=exe_path,
        exe_sha256=exe_sha256,
        table_sha256=table_sha256,
        source=source,
    )
    manifest.update(
        {
            "operation": "reconstruct_vab",
            "pair": pair_manifest(pair),
            "output": {
                "path": str(output_path),
                "size": len(pair.reconstructed),
                "sha256": _sha256(pair.reconstructed),
            },
        }
    )
    return manifest


def _write_json(handle: TextIO, value: dict[str, object]) -> None:
    json.dump(value, handle, indent=2, sort_keys=False)
    handle.write("\n")


def _path_key(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def _preflight_outputs(
    paths: Sequence[Path],
    *,
    force: bool,
    protected_paths: Sequence[Path] = (),
) -> None:
    keys = [_path_key(path) for path in paths]
    if len(keys) != len(set(keys)):
        raise VabToolError("two requested outputs resolve to the same path")
    protected_keys = {_path_key(path) for path in protected_paths}
    collision = next((path for path, key in zip(paths, keys) if key in protected_keys), None)
    if collision is not None:
        raise VabToolError(f"output would overwrite a protected input: {collision}")
    if not force:
        existing = [path for path in paths if path.exists()]
        if existing:
            raise VabToolError(
                "refusing to overwrite existing output(s): "
                + ", ".join(str(path) for path in existing)
                + "; use --force"
            )


def _atomic_temp(path: Path, mode: str) -> tuple[BinaryIO | TextIO, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {
        "mode": mode,
        "prefix": f".{path.name}.",
        "suffix": ".tmp",
        "dir": path.parent,
        "delete": False,
    }
    if "b" not in mode:
        kwargs.update({"encoding": "utf-8", "newline": ""})
    handle = tempfile.NamedTemporaryFile(**kwargs)
    return handle, Path(handle.name)


def write_json(
    path: Path,
    value: dict[str, object],
    *,
    force: bool = False,
    protected_paths: Sequence[Path] = (),
) -> None:
    _preflight_outputs([path], force=force, protected_paths=protected_paths)
    handle: TextIO | None = None
    temporary: Path | None = None
    try:
        raw_handle, temporary = _atomic_temp(path, "w")
        handle = raw_handle  # type: ignore[assignment]
        with handle:
            _write_json(handle, value)
        os.replace(temporary, path)
    except Exception:
        if handle is not None and not handle.closed:
            handle.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_reconstruction(
    output_path: Path,
    manifest_path: Path,
    pair: PreparedPair,
    manifest: dict[str, object],
    *,
    force: bool = False,
    protected_paths: Sequence[Path] = (),
) -> None:
    if output_path.suffix.casefold() != ".vab":
        raise VabToolError("reconstructed output must use the .vab extension")
    _preflight_outputs(
        [output_path, manifest_path],
        force=force,
        protected_paths=protected_paths,
    )

    binary_handle: BinaryIO | None = None
    json_handle: TextIO | None = None
    binary_temp: Path | None = None
    json_temp: Path | None = None
    try:
        raw_binary, binary_temp = _atomic_temp(output_path, "w+b")
        binary_handle = raw_binary  # type: ignore[assignment]
        with binary_handle:
            binary_handle.write(pair.reconstructed)

        raw_json, json_temp = _atomic_temp(manifest_path, "w")
        json_handle = raw_json  # type: ignore[assignment]
        with json_handle:
            _write_json(json_handle, manifest)

        os.replace(binary_temp, output_path)
        os.replace(json_temp, manifest_path)
    except Exception:
        if binary_handle is not None and not binary_handle.closed:
            binary_handle.close()
        if json_handle is not None and not json_handle.closed:
            json_handle.close()
        if binary_temp is not None:
            binary_temp.unlink(missing_ok=True)
        if json_temp is not None:
            json_temp.unlink(missing_ok=True)
        raise


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
        description="Audit or reconstruct Tekken 3 USA split VH/VB sound banks"
    )
    parser.add_argument("--version", action="version", version="vab_tool 1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser(
        "audit", help="strictly validate all 48 known VH/ARC pairs"
    )
    _add_source_arguments(audit_parser)
    audit_parser.add_argument("--json", type=Path, help="write the audit manifest here")
    audit_parser.add_argument(
        "--force", action="store_true", help="replace an existing audit manifest"
    )

    extract_parser = subparsers.add_parser(
        "extract", help="reconstruct one explicitly selected verified pair"
    )
    _add_source_arguments(extract_parser)
    extract_parser.add_argument("--vh-id", type=int, required=True, help="numeric VH BNS ID")
    extract_parser.add_argument(
        "--arc-id", type=int, required=True, help="numeric associated ARC BNS ID"
    )
    extract_parser.add_argument(
        "--output", type=Path, required=True, help="local reconstructed .vab path"
    )
    extract_parser.add_argument(
        "--manifest",
        type=Path,
        help="JSON manifest path (default: <output>.json)",
    )
    extract_parser.add_argument(
        "--force", action="store_true", help="replace matching existing outputs"
    )
    return parser


def run(args: argparse.Namespace) -> int:
    entries, exe_sha256, table_sha256 = bns_tool.load_us_table(args.exe)
    source = bns_tool.open_bns_source(args.source, args.source_format)
    with source:
        bns_tool.validate_source_capacity(source, entries)
        if args.command == "audit":
            manifest = build_audit_manifest(
                source,
                entries,
                exe_path=args.exe,
                exe_sha256=exe_sha256,
                table_sha256=table_sha256,
            )
            if args.json is None:
                _write_json(sys.stdout, manifest)
            else:
                write_json(
                    args.json,
                    manifest,
                    force=args.force,
                    protected_paths=[args.source, args.exe],
                )
            print(
                f"Validated {manifest['verified_pair_count']} VH/ARC/VB pairs.",
                file=sys.stderr,
            )
            return 0

        if args.command == "extract":
            pair = prepare_pair(source, entries, args.vh_id, args.arc_id)
            manifest_path = args.manifest or Path(f"{args.output}.json")
            manifest = build_extraction_manifest(
                pair,
                args.output,
                source,
                exe_path=args.exe,
                exe_sha256=exe_sha256,
                table_sha256=table_sha256,
            )
            write_reconstruction(
                args.output,
                manifest_path,
                pair,
                manifest,
                force=args.force,
                protected_paths=[args.source, args.exe],
            )
            print(
                f"Reconstructed VAB from VH {args.vh_id:03d} and ARC "
                f"{args.arc_id:03d} member {pair.vb_member.index}: {args.output}"
            )
            return 0

    raise VabToolError(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (VabToolError, bns_tool.BnsToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
