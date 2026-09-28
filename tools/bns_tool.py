#!/usr/bin/env python3
"""Inventory and locally extract Tekken 3 (USA) TEKKEN3.BNS entries.

This tool is deliberately read-only with respect to the executable, archive, and
disc image.  It uses only the Python standard library and supports either a
standalone TEKKEN3.BNS file or a raw/cooked Track 1 image containing the file.
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
from typing import BinaryIO, Iterable, Iterator, Sequence, TextIO


GAME_ID = "SLUS-00402"
US_EXE_SHA256 = "fbda8b68e5799dbef4af39a161783bc670c15b0aa0e87dce65e210717da19b8c"
TABLE_VIRTUAL_ADDRESS = 0x80024400
TABLE_FILE_OFFSET = 0x14C00
TABLE_ENTRY_COUNT = 303
TABLE_ENTRY_SIZE = 8
LOGICAL_SECTOR_SIZE = 0x800
CLASSIFY_PREFIX_SIZE = 0x1000
SCHEMA_VERSION = 1


class BnsToolError(RuntimeError):
    """A user-facing validation or archive error."""


@dataclass(frozen=True)
class TableEntry:
    """One zero-based entry in the executable's BNS table."""

    id: int
    sector: int
    size: int

    @property
    def offset(self) -> int:
        return self.sector * LOGICAL_SECTOR_SIZE

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class IsoLayout:
    sector_size: int
    user_offset: int
    kind: str


@dataclass(frozen=True)
class IsoRecord:
    name: str
    extent: int
    size: int
    is_directory: bool


def parse_table_bytes(data: bytes, *, validate_exe_header: bool = True) -> list[TableEntry]:
    """Parse the fixed US table from a complete PS-X EXE byte string.

    ``validate_exe_header=False`` exists for small synthetic fixtures in tests;
    normal CLI use additionally requires the known US executable SHA-256.
    """

    table_end = TABLE_FILE_OFFSET + TABLE_ENTRY_COUNT * TABLE_ENTRY_SIZE
    if len(data) < table_end:
        raise BnsToolError(
            f"executable is too small for the {TABLE_ENTRY_COUNT}-entry table "
            f"at 0x{TABLE_FILE_OFFSET:X}"
        )

    if validate_exe_header:
        if data[:8] != b"PS-X EXE":
            raise BnsToolError("input is not a PS-X EXE")
        # PS-X EXE fields are not three adjacent values: 0x14 is the initial
        # GP, followed by the text load address and size at 0x18/0x1C.
        entry_pc = struct.unpack_from("<I", data, 0x10)[0]
        load_address, text_size = struct.unpack_from("<II", data, 0x18)
        expected = (0x80079C70, 0x80010000, 0x00121000)
        if (entry_pc, load_address, text_size) != expected:
            raise BnsToolError(
                "PS-X EXE header does not match Tekken 3 USA (SLUS-00402)"
            )

    entries = [
        TableEntry(i, *struct.unpack_from("<II", data, TABLE_FILE_OFFSET + i * 8))
        for i in range(TABLE_ENTRY_COUNT)
    ]
    validate_table(entries)
    return entries


def validate_table(entries: Sequence[TableEntry]) -> None:
    if len(entries) != TABLE_ENTRY_COUNT:
        raise BnsToolError(
            f"expected {TABLE_ENTRY_COUNT} BNS entries, found {len(entries)}"
        )

    for expected_id, entry in enumerate(entries):
        if entry.id != expected_id:
            raise BnsToolError("BNS table IDs are not contiguous and zero-based")

    for current, following in zip(entries, entries[1:]):
        occupied_sectors = (current.size + LOGICAL_SECTOR_SIZE - 1) // LOGICAL_SECTOR_SIZE
        first_free_sector = current.sector + occupied_sectors
        if following.sector < first_free_sector:
            raise BnsToolError(
                f"BNS table entries {current.id} and {following.id} overlap or go backwards"
            )


def load_us_table(exe_path: Path) -> tuple[list[TableEntry], str, str]:
    """Load the table, requiring the verified SLUS-00402 executable."""

    try:
        data = exe_path.read_bytes()
    except OSError as exc:
        raise BnsToolError(f"cannot read executable {exe_path}: {exc}") from exc

    exe_sha256 = hashlib.sha256(data).hexdigest()
    if exe_sha256 != US_EXE_SHA256:
        raise BnsToolError(
            "executable SHA-256 does not match the supported Tekken 3 USA "
            f"SLUS-00402 file (expected {US_EXE_SHA256}, got {exe_sha256})"
        )

    entries = parse_table_bytes(data)
    table_data = data[
        TABLE_FILE_OFFSET : TABLE_FILE_OFFSET + TABLE_ENTRY_COUNT * TABLE_ENTRY_SIZE
    ]
    return entries, exe_sha256, hashlib.sha256(table_data).hexdigest()


def _read_iso_sector(handle: BinaryIO, layout: IsoLayout, sector: int) -> bytes:
    physical_offset = sector * layout.sector_size + layout.user_offset
    handle.seek(physical_offset)
    data = handle.read(LOGICAL_SECTOR_SIZE)
    if len(data) != LOGICAL_SECTOR_SIZE:
        raise BnsToolError(f"disc image ends while reading ISO sector {sector}")
    return data


def _detect_iso_layout(handle: BinaryIO, image_size: int) -> IsoLayout | None:
    candidates = (
        IsoLayout(2352, 24, "raw_track_2352_mode2"),
        IsoLayout(2352, 16, "raw_track_2352_mode1"),
        IsoLayout(2048, 0, "cooked_iso_2048"),
    )
    for layout in candidates:
        pvd_offset = 16 * layout.sector_size + layout.user_offset
        if pvd_offset + LOGICAL_SECTOR_SIZE > image_size:
            continue
        handle.seek(pvd_offset)
        pvd = handle.read(LOGICAL_SECTOR_SIZE)
        if pvd[:7] == b"\x01CD001\x01":
            return layout
    return None


def _normalize_iso_name(raw_name: bytes) -> str:
    if raw_name in (b"\x00", b"\x01"):
        return "." if raw_name == b"\x00" else ".."
    return raw_name.decode("ascii", errors="replace").split(";", 1)[0].rstrip(".")


def _iter_iso_directory(data: bytes) -> Iterator[IsoRecord]:
    position = 0
    while position < len(data):
        record_length = data[position]
        if record_length == 0:
            position = ((position // LOGICAL_SECTOR_SIZE) + 1) * LOGICAL_SECTOR_SIZE
            continue
        if record_length < 34 or position + record_length > len(data):
            raise BnsToolError("malformed ISO 9660 directory record")
        name_length = data[position + 32]
        name_start = position + 33
        if name_start + name_length > position + record_length:
            raise BnsToolError("malformed ISO 9660 file identifier")
        yield IsoRecord(
            name=_normalize_iso_name(data[name_start : name_start + name_length]),
            extent=struct.unpack_from("<I", data, position + 2)[0],
            size=struct.unpack_from("<I", data, position + 10)[0],
            is_directory=bool(data[position + 25] & 0x02),
        )
        position += record_length


def _read_iso_extent(
    handle: BinaryIO, layout: IsoLayout, extent: int, size: int
) -> bytes:
    output = bytearray()
    sectors = (size + LOGICAL_SECTOR_SIZE - 1) // LOGICAL_SECTOR_SIZE
    for index in range(sectors):
        output.extend(_read_iso_sector(handle, layout, extent + index))
    return bytes(output[:size])


def _find_iso_record(
    handle: BinaryIO, layout: IsoLayout, components: Sequence[str]
) -> IsoRecord:
    pvd = _read_iso_sector(handle, layout, 16)
    root_length = pvd[156]
    if root_length < 34 or 156 + root_length > len(pvd):
        raise BnsToolError("ISO primary volume descriptor has no valid root directory")
    root = next(_iter_iso_directory(pvd[156 : 156 + root_length]))
    current = root

    for component_index, component in enumerate(components):
        directory_data = _read_iso_extent(handle, layout, current.extent, current.size)
        wanted = component.casefold()
        match = next(
            (record for record in _iter_iso_directory(directory_data) if record.name.casefold() == wanted),
            None,
        )
        if match is None:
            joined = "/".join(components[: component_index + 1])
            raise BnsToolError(f"disc image does not contain {joined}")
        if component_index + 1 < len(components) and not match.is_directory:
            raise BnsToolError(f"ISO path component {component} is not a directory")
        current = match
    return current


class BnsSource:
    """Logical byte access to the BNS file inside either supported container."""

    def __init__(
        self,
        path: Path,
        *,
        kind: str,
        logical_size: int,
        sector_size: int = LOGICAL_SECTOR_SIZE,
        user_offset: int = 0,
        extent_sector: int = 0,
        iso_path: str | None = None,
    ) -> None:
        self.path = path
        self.kind = kind
        self.logical_size = logical_size
        self.sector_size = sector_size
        self.user_offset = user_offset
        self.extent_sector = extent_sector
        self.iso_path = iso_path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "BnsSource":
        try:
            self._handle = self.path.open("rb")
        except OSError as exc:
            raise BnsToolError(f"cannot open BNS source {self.path}: {exc}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @property
    def is_flat(self) -> bool:
        return self.sector_size == LOGICAL_SECTOR_SIZE and self.user_offset == 0

    def _require_handle(self) -> BinaryIO:
        if self._handle is None:
            raise BnsToolError("BNS source is not open")
        return self._handle

    def read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.logical_size:
            raise BnsToolError(
                f"BNS read 0x{offset:X}+0x{size:X} exceeds logical archive size "
                f"0x{self.logical_size:X}"
            )
        if size == 0:
            return b""

        handle = self._require_handle()
        if self.is_flat:
            handle.seek(self.extent_sector * LOGICAL_SECTOR_SIZE + offset)
            data = handle.read(size)
            if len(data) != size:
                raise BnsToolError("BNS source ends unexpectedly")
            return data

        remaining = size
        logical_position = offset
        output = bytearray()
        while remaining:
            archive_sector, within_sector = divmod(logical_position, LOGICAL_SECTOR_SIZE)
            take = min(remaining, LOGICAL_SECTOR_SIZE - within_sector)
            physical_sector = self.extent_sector + archive_sector
            physical_offset = (
                physical_sector * self.sector_size + self.user_offset + within_sector
            )
            handle.seek(physical_offset)
            chunk = handle.read(take)
            if len(chunk) != take:
                raise BnsToolError(
                    f"raw disc image ends while reading BNS sector {archive_sector}"
                )
            output.extend(chunk)
            logical_position += take
            remaining -= take
        return bytes(output)

    def iter_range(self, offset: int, size: int, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        position = offset
        remaining = size
        while remaining:
            take = min(remaining, chunk_size)
            yield self.read_at(position, take)
            position += take
            remaining -= take

    def metadata(self) -> dict[str, object]:
        result: dict[str, object] = {
            "path": str(self.path),
            "container_kind": self.kind,
            "container_size": self.path.stat().st_size,
            "bns_size": self.logical_size,
        }
        if self.iso_path is not None:
            result.update(
                {
                    "iso_path": self.iso_path,
                    "iso_extent_lba": self.extent_sector,
                    "physical_sector_size": self.sector_size,
                    "user_data_offset": self.user_offset,
                }
            )
        return result


def open_bns_source(path: Path, source_format: str = "auto") -> BnsSource:
    """Describe a standalone BNS or locate it inside a Track 1 image."""

    try:
        image_size = path.stat().st_size
        with path.open("rb") as handle:
            layout = _detect_iso_layout(handle, image_size) if source_format != "bns" else None
            if source_format == "track" and layout is None:
                raise BnsToolError("source is not a recognized raw Track 1 or cooked ISO image")
            if layout is not None:
                directory = _find_iso_record(handle, layout, ("TEKKEN3",))
                directory_data = _read_iso_extent(
                    handle, layout, directory.extent, directory.size
                )
                records = list(_iter_iso_directory(directory_data))
                # The verified US image uses TEKKEN3.BNS;1. Accept BNS;1 as a
                # conservative compatibility alias for dumps/tools which expose
                # that short name, without relying on a physical LBA.
                record = next(
                    (
                        item
                        for wanted in ("tekken3.bns", "bns")
                        for item in records
                        if item.name.casefold() == wanted
                    ),
                    None,
                )
                if record is None:
                    raise BnsToolError(
                        "disc image does not contain TEKKEN3/TEKKEN3.BNS;1 or "
                        "TEKKEN3/BNS;1"
                    )
                if record.is_directory:
                    raise BnsToolError(f"TEKKEN3/{record.name} unexpectedly identifies a directory")
                return BnsSource(
                    path,
                    kind=layout.kind,
                    logical_size=record.size,
                    sector_size=layout.sector_size,
                    user_offset=layout.user_offset,
                    extent_sector=record.extent,
                    iso_path=f"/TEKKEN3/{record.name};1",
                )
    except OSError as exc:
        raise BnsToolError(f"cannot inspect BNS source {path}: {exc}") from exc

    return BnsSource(path, kind="standalone_bns", logical_size=image_size)


def validate_source_capacity(source: BnsSource, entries: Sequence[TableEntry]) -> None:
    required_size = max((entry.end_offset for entry in entries), default=0)
    if source.logical_size < required_size:
        raise BnsToolError(
            f"BNS source is too small: table needs 0x{required_size:X} bytes, "
            f"source exposes 0x{source.logical_size:X}"
        )


def _valid_vab_header(prefix: bytes) -> bool:
    if len(prefix) < 32 or prefix[:4] != b"pBAV":
        return False
    version = struct.unpack_from("<I", prefix, 4)[0]
    return 1 <= version <= 7


def _valid_arc(prefix: bytes, total_size: int) -> bool:
    if len(prefix) < 12:
        return False
    file_count = struct.unpack_from("<I", prefix, 0)[0]
    if not 1 <= file_count <= 0xFF:
        return False
    directory_end = 4 + file_count * 8
    if directory_end > len(prefix) or directory_end > total_size:
        return False

    previous_end: int | None = None
    first_offset = 0
    for index in range(file_count):
        offset, size = struct.unpack_from("<II", prefix, 4 + index * 8)
        if index == 0:
            first_offset = offset
        if offset < directory_end or offset > total_size or size > total_size - offset:
            return False
        if previous_end is not None and offset != previous_end:
            return False
        previous_end = offset + size

    # Observed ARC directories are followed only by ordinary alignment padding.
    if first_offset - directory_end > 15:
        return False
    return previous_end == total_size


def _tim_block(prefix: bytes, position: int, total_size: int) -> tuple[int, bool]:
    if position + 12 > len(prefix):
        return position, False
    block_size, _x, _y, width, height = struct.unpack_from("<IHHHH", prefix, position)
    expected_size = 12 + width * height * 2
    if width == 0 or height == 0 or block_size != expected_size:
        return position, False
    if block_size > total_size - position:
        return position, False
    return position + block_size, True


def _valid_tim(prefix: bytes, total_size: int) -> bool:
    if len(prefix) < 20 or total_size < 20:
        return False
    magic, flags = struct.unpack_from("<II", prefix, 0)
    if magic != 0x10 or flags not in (0x08, 0x09, 0x02, 0x03):
        return False
    position = 8
    if flags & 0x08:
        position, valid = _tim_block(prefix, position, total_size)
        if not valid:
            return False
    position, valid = _tim_block(prefix, position, total_size)
    return valid and position == total_size


def classify_entry(prefix: bytes, total_size: int) -> tuple[str, str]:
    """Return a conservative signature hint and suggested file extension."""

    if total_size == 0:
        return "EMPTY", ".bin"
    if total_size >= 12 and len(prefix) >= 12 and prefix[8:12] == b"3DMK":
        return "3DMK", ".3dm"
    if _valid_vab_header(prefix):
        declared_size = struct.unpack_from("<I", prefix, 0x0C)[0]
        return ("VAB", ".vab") if 0 < declared_size <= total_size else ("VH", ".vh")
    if _valid_tim(prefix, total_size):
        return "TIM", ".tim"
    if _valid_arc(prefix, total_size):
        return "ARC", ".arc"
    return "BIN", ".bin"


def _inventory_entry(source: BnsSource, entry: TableEntry) -> dict[str, object]:
    digest = hashlib.sha256()
    prefix = bytearray()
    for chunk in source.iter_range(entry.offset, entry.size):
        digest.update(chunk)
        if len(prefix) < CLASSIFY_PREFIX_SIZE:
            prefix.extend(chunk[: CLASSIFY_PREFIX_SIZE - len(prefix)])
    kind, extension = classify_entry(bytes(prefix), entry.size)
    return {
        "id": entry.id,
        "sector": entry.sector,
        "offset": entry.offset,
        "size": entry.size,
        "end_offset": entry.end_offset,
        "sha256": digest.hexdigest(),
        "kind": kind,
        "extension": extension,
        "suggested_filename": f"{entry.id:03d}{extension}",
    }


def build_inventory(
    source: BnsSource,
    entries: Sequence[TableEntry],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> dict[str, object]:
    validate_source_capacity(source, entries)
    inventory_entries = [_inventory_entry(source, entry) for entry in entries]
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": GAME_ID,
        "executable": {
            "path": str(exe_path),
            "sha256": exe_sha256,
        },
        "table": {
            "virtual_address": f"0x{TABLE_VIRTUAL_ADDRESS:08X}",
            "file_offset": f"0x{TABLE_FILE_OFFSET:X}",
            "entry_count": TABLE_ENTRY_COUNT,
            "entry_size": TABLE_ENTRY_SIZE,
            "sha256": table_sha256,
        },
        "source": source.metadata(),
        "entries": inventory_entries,
    }


CSV_FIELDS = (
    "id",
    "sector",
    "offset",
    "size",
    "end_offset",
    "sha256",
    "kind",
    "extension",
    "suggested_filename",
)


def _check_output_paths(paths: Iterable[Path], force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise BnsToolError(f"refusing to overwrite existing output(s): {joined}; use --force")


def _atomic_binary_writer(path: Path) -> tuple[BinaryIO, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w+b", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    )
    return handle, Path(handle.name)


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


def write_json(path: Path, inventory: dict[str, object]) -> None:
    def emit(handle: TextIO) -> None:
        json.dump(inventory, handle, indent=2, sort_keys=False)
        handle.write("\n")

    _atomic_write_text(path, emit)


def _emit_csv(handle: TextIO, inventory: dict[str, object]) -> None:
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(inventory["entries"])  # type: ignore[arg-type]


def write_csv(path: Path, inventory: dict[str, object]) -> None:
    _atomic_write_text(path, lambda handle: _emit_csv(handle, inventory))


def parse_ids(specification: str | None) -> list[int]:
    if specification is None or specification.strip().casefold() == "all":
        return list(range(TABLE_ENTRY_COUNT))
    selected: set[int] = set()
    for part in specification.split(","):
        part = part.strip()
        if not part:
            raise BnsToolError("empty item in --ids selection")
        if "-" in part:
            pieces = part.split("-")
            if len(pieces) != 2 or not all(piece.strip().isdigit() for piece in pieces):
                raise BnsToolError(f"invalid ID range: {part}")
            first, last = (int(piece.strip()) for piece in pieces)
            if first > last:
                raise BnsToolError(f"descending ID range is not allowed: {part}")
            selected.update(range(first, last + 1))
        elif part.isdigit():
            selected.add(int(part))
        else:
            raise BnsToolError(f"invalid entry ID: {part}")
    invalid = sorted(value for value in selected if not 0 <= value < TABLE_ENTRY_COUNT)
    if invalid:
        raise BnsToolError(
            f"entry ID(s) outside supported range 0-{TABLE_ENTRY_COUNT - 1}: "
            + ", ".join(map(str, invalid))
        )
    return sorted(selected)


def extract_entries(
    source: BnsSource,
    entries: Sequence[TableEntry],
    inventory: dict[str, object],
    selected_ids: Sequence[int],
    output_directory: Path,
    *,
    force: bool,
) -> list[Path]:
    inventory_by_id = {item["id"]: item for item in inventory["entries"]}  # type: ignore[index]
    selected_entries = [entries[entry_id] for entry_id in selected_ids]
    payload_paths = [
        output_directory / str(inventory_by_id[entry.id]["suggested_filename"])
        for entry in selected_entries
        if entry.size
    ]
    manifest_json = output_directory / "inventory.json"
    manifest_csv = output_directory / "inventory.csv"
    _check_output_paths([*payload_paths, manifest_json, manifest_csv], force)
    output_directory.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for entry, output_path in zip(
        (entry for entry in selected_entries if entry.size), payload_paths
    ):
        handle: BinaryIO | None = None
        temporary: Path | None = None
        try:
            handle, temporary = _atomic_binary_writer(output_path)
            with handle:
                for chunk in source.iter_range(entry.offset, entry.size):
                    handle.write(chunk)
            os.replace(temporary, output_path)
            written.append(output_path)
        except Exception:
            if handle is not None and not handle.closed:
                handle.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    extraction_inventory = dict(inventory)
    extraction_inventory["extraction"] = {
        "selected_ids": list(selected_ids),
        "payload_files_written": len(written),
        "zero_size_entries_skipped": [entry.id for entry in selected_entries if not entry.size],
    }
    write_json(manifest_json, extraction_inventory)
    write_csv(manifest_csv, extraction_inventory)
    return written


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
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
        description="Inventory or locally extract Tekken 3 USA TEKKEN3.BNS"
    )
    parser.add_argument("--version", action="version", version="bns_tool 1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser(
        "inventory", help="hash, classify, and list all 303 entries"
    )
    _add_common_arguments(inventory_parser)
    inventory_parser.add_argument("--json", type=Path, help="write the JSON inventory here")
    inventory_parser.add_argument("--csv", type=Path, help="write the CSV inventory here")
    inventory_parser.add_argument(
        "--force", action="store_true", help="replace existing requested inventory files"
    )

    extract_parser = subparsers.add_parser(
        "extract", help="extract selected numeric entries and write inventories"
    )
    _add_common_arguments(extract_parser)
    extract_parser.add_argument(
        "--output",
        type=Path,
        default=Path("workspace/bns/entries"),
        help="local output directory (default: workspace/bns/entries)",
    )
    extract_parser.add_argument(
        "--ids",
        help=f"comma/range selection such as 71,72-74 (default: all 0-{TABLE_ENTRY_COUNT - 1})",
    )
    extract_parser.add_argument(
        "--force", action="store_true", help="replace matching existing payload/manifests"
    )
    return parser


def _load_inventory(args: argparse.Namespace) -> tuple[
    list[TableEntry], BnsSource, dict[str, object]
]:
    entries, exe_sha256, table_sha256 = load_us_table(args.exe)
    source = open_bns_source(args.source, args.source_format)
    source.__enter__()
    try:
        inventory = build_inventory(
            source,
            entries,
            exe_path=args.exe,
            exe_sha256=exe_sha256,
            table_sha256=table_sha256,
        )
    except Exception:
        source.__exit__(None, None, None)
        raise
    return entries, source, inventory


def run(args: argparse.Namespace) -> int:
    if args.command == "inventory":
        paths = [path for path in (args.json, args.csv) if path is not None]
        _check_output_paths(paths, args.force)
        _entries, source, inventory = _load_inventory(args)
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
        kinds: dict[str, int] = {}
        for entry in inventory["entries"]:  # type: ignore[assignment]
            kind = entry["kind"]
            kinds[kind] = kinds.get(kind, 0) + 1
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(kinds.items()))
        print(f"Inventoried {TABLE_ENTRY_COUNT} entries ({summary}).", file=sys.stderr)
        return 0

    if args.command == "extract":
        selected_ids = parse_ids(args.ids)
        entries, source, inventory = _load_inventory(args)
        try:
            written = extract_entries(
                source,
                entries,
                inventory,
                selected_ids,
                args.output,
                force=args.force,
            )
        finally:
            source.__exit__(None, None, None)
        print(
            f"Extracted {len(written)} payload(s) for {len(selected_ids)} selected ID(s) "
            f"to {args.output}."
        )
        return 0


    raise BnsToolError(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (BnsToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
