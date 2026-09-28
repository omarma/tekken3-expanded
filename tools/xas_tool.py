#!/usr/bin/env python3
"""Inventory and locally extract Tekken 3 USA XA/STR sector streams.

The retail Track 1 image remains read-only.  This tool accepts only the exact
Redump-compatible SLUS-00402 data track, discovers TEKKEN3.XAS through ISO 9660,
and validates raw 2352-byte Mode 2 sectors before producing any output.
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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, Sequence, TextIO


GAME_ID = "SLUS-00402"
US_EXE_SHA256 = "fbda8b68e5799dbef4af39a161783bc670c15b0aa0e87dce65e210717da19b8c"
TRACK_SIZE = 632_532_768
TRACK_SHA256 = "6b660e62748d02779e9e08362a5ed202540af7fad134de2ec0a2184ad78bb496"
XAS_TABLE_FILE_OFFSET = 0x15578
XAS_TABLE_ENTRY_COUNT = 50
XAS_TABLE_ENTRY_SIZE = 12
XAS_TABLE_SHA256 = "aef0b4eabb5246347837b9158327aa2d428ad460ada751172bd33ffdd7595a71"
XAS_EXTENT_LBA = 604
XAS_LOGICAL_SIZE = 511_082_496
XAS_SECTOR_COUNT = XAS_LOGICAL_SIZE // 2048
XAS_RAW_SHA256 = "78cbc376c9031a47285362b3d3ee38207c6af21066ecde699e9958a01ecb09a5"
RAW_SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
ISO_SECTOR_SIZE = 2048
XA_STRIDE = 8
EXPECTED_MOVIE_COUNT = 22
EXPECTED_SUBMODE_COUNTS = {0x00: 4_595, 0x48: 111_099, 0x64: 133_807, 0xE4: 51}
SCHEMA_VERSION = 1
SYNC = b"\x00" + b"\xFF" * 10 + b"\x00"


class XasToolError(RuntimeError):
    """A user-facing revision, sector, or output validation error."""


@dataclass(frozen=True)
class XaDescriptor:
    """One executable table row; start/end are eight-sector group bases."""

    id: int
    start_group_sector: int
    end_group_sector: int
    channel: int

    @property
    def first_relative_sector(self) -> int:
        return self.start_group_sector + self.channel

    @property
    def last_relative_sector(self) -> int:
        return self.end_group_sector + self.channel

    @property
    def sector_count(self) -> int:
        return (self.end_group_sector - self.start_group_sector) // XA_STRIDE + 1


@dataclass(frozen=True)
class SectorInfo:
    relative_sector: int
    file_number: int
    channel: int
    submode: int
    coding_info: int


@dataclass(frozen=True)
class StrChunkHeader:
    chunk_index: int
    chunks_in_frame: int
    frame_number: int
    demuxed_size: int
    width: int
    height: int


@dataclass(frozen=True)
class StrSector:
    relative_sector: int
    header: StrChunkHeader


@dataclass(frozen=True)
class MovieRegion:
    id: int
    start_relative_sector: int
    end_relative_sector: int
    frame_count: int
    width: int
    height: int
    chunks_per_frame: tuple[int, ...]
    str_sector_count: int

    @property
    def span_sector_count(self) -> int:
        return self.end_relative_sector - self.start_relative_sector + 1


@dataclass(frozen=True)
class IsoRecord:
    name: str
    extent: int
    size: int
    is_directory: bool


@dataclass
class ScanResult:
    sector_infos: list[SectorInfo]
    str_sectors: list[StrSector]
    xa_stream_sha256: list[str]
    xas_raw_sha256: str
    submode_counts: Counter[int]


class XasSource:
    """Raw-sector access to the discovered XAS extent in a Track 1 image."""

    def __init__(self, path: Path, extent_lba: int, sector_count: int) -> None:
        self.path = path
        self.extent_lba = extent_lba
        self.sector_count = sector_count
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "XasSource":
        try:
            self._handle = self.path.open("rb")
        except OSError as exc:
            raise XasToolError(f"cannot open Track 1 image {self.path}: {exc}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _require_handle(self) -> BinaryIO:
        if self._handle is None:
            raise XasToolError("XAS source is not open")
        return self._handle

    def read_raw_sector(self, relative_sector: int) -> bytes:
        if not 0 <= relative_sector < self.sector_count:
            raise XasToolError(
                f"XAS relative sector {relative_sector} is outside 0-{self.sector_count - 1}"
            )
        handle = self._require_handle()
        absolute_lba = self.extent_lba + relative_sector
        handle.seek(absolute_lba * RAW_SECTOR_SIZE)
        raw = handle.read(RAW_SECTOR_SIZE)
        if len(raw) != RAW_SECTOR_SIZE:
            raise XasToolError(f"Track 1 ends while reading absolute LBA {absolute_lba}")
        return raw


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise XasToolError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def parse_descriptor_table_bytes(
    data: bytes, *, validate_exe_header: bool = True
) -> list[XaDescriptor]:
    table_end = XAS_TABLE_FILE_OFFSET + XAS_TABLE_ENTRY_COUNT * XAS_TABLE_ENTRY_SIZE
    if len(data) < table_end:
        raise XasToolError(
            f"executable is too small for the {XAS_TABLE_ENTRY_COUNT}-entry XAS table "
            f"at 0x{XAS_TABLE_FILE_OFFSET:X}"
        )
    if validate_exe_header:
        if data[:8] != b"PS-X EXE":
            raise XasToolError("input is not a PS-X EXE")
        entry_pc = struct.unpack_from("<I", data, 0x10)[0]
        load_address, text_size = struct.unpack_from("<II", data, 0x18)
        if (entry_pc, load_address, text_size) != (
            0x80079C70,
            0x80010000,
            0x00121000,
        ):
            raise XasToolError("PS-X EXE header does not match Tekken 3 USA (SLUS-00402)")

    descriptors = [
        XaDescriptor(
            entry_id,
            *struct.unpack_from(
                "<III", data, XAS_TABLE_FILE_OFFSET + entry_id * XAS_TABLE_ENTRY_SIZE
            ),
        )
        for entry_id in range(XAS_TABLE_ENTRY_COUNT)
    ]
    validate_descriptors(descriptors, required_count=XAS_TABLE_ENTRY_COUNT)
    return descriptors


def validate_descriptors(
    descriptors: Sequence[XaDescriptor], *, required_count: int | None = None
) -> None:
    if required_count is not None and len(descriptors) != required_count:
        raise XasToolError(f"expected {required_count} XA descriptors, found {len(descriptors)}")

    occupied: dict[int, int] = {}
    for expected_id, descriptor in enumerate(descriptors):
        if descriptor.id != expected_id:
            raise XasToolError("XA descriptor IDs are not contiguous and zero-based")
        if not 0 <= descriptor.channel < XA_STRIDE:
            raise XasToolError(f"XA descriptor {descriptor.id} has invalid channel {descriptor.channel}")
        if descriptor.start_group_sector % XA_STRIDE or descriptor.end_group_sector % XA_STRIDE:
            raise XasToolError(
                f"XA descriptor {descriptor.id} start/end are not {XA_STRIDE}-sector aligned"
            )
        if descriptor.end_group_sector < descriptor.start_group_sector:
            raise XasToolError(f"XA descriptor {descriptor.id} has a descending sector range")
        if descriptor.last_relative_sector >= XAS_SECTOR_COUNT:
            raise XasToolError(f"XA descriptor {descriptor.id} exceeds TEKKEN3.XAS")
        for relative_sector in range(
            descriptor.first_relative_sector,
            descriptor.last_relative_sector + 1,
            XA_STRIDE,
        ):
            previous = occupied.setdefault(relative_sector, descriptor.id)
            if previous != descriptor.id:
                raise XasToolError(
                    f"XA descriptors {previous} and {descriptor.id} select sector {relative_sector}"
                )


def load_us_descriptors(exe_path: Path) -> tuple[list[XaDescriptor], str, str]:
    try:
        data = exe_path.read_bytes()
    except OSError as exc:
        raise XasToolError(f"cannot read executable {exe_path}: {exc}") from exc
    exe_sha256 = hashlib.sha256(data).hexdigest()
    if exe_sha256 != US_EXE_SHA256:
        raise XasToolError(
            "executable SHA-256 does not match Tekken 3 USA SLUS-00402 "
            f"(expected {US_EXE_SHA256}, got {exe_sha256})"
        )
    descriptors = parse_descriptor_table_bytes(data)
    table = data[
        XAS_TABLE_FILE_OFFSET : XAS_TABLE_FILE_OFFSET
        + XAS_TABLE_ENTRY_COUNT * XAS_TABLE_ENTRY_SIZE
    ]
    table_sha256 = hashlib.sha256(table).hexdigest()
    if table_sha256 != XAS_TABLE_SHA256:
        raise XasToolError("XAS descriptor table hash does not match the supported revision")
    return descriptors, exe_sha256, table_sha256


def _decode_bcd(value: int) -> int:
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        raise XasToolError(f"invalid BCD sector address byte 0x{value:02X}")
    return high * 10 + low


def _expected_msf(absolute_lba: int) -> tuple[int, int, int]:
    absolute_frame = absolute_lba + 150
    minute, remainder = divmod(absolute_frame, 75 * 60)
    second, frame = divmod(remainder, 75)
    return minute, second, frame


def parse_raw_sector(raw: bytes, *, absolute_lba: int, relative_sector: int) -> SectorInfo:
    if len(raw) != RAW_SECTOR_SIZE:
        raise XasToolError(
            f"absolute LBA {absolute_lba} has {len(raw)} bytes, expected {RAW_SECTOR_SIZE}"
        )
    if raw[:12] != SYNC:
        raise XasToolError(f"absolute LBA {absolute_lba} has an invalid CD sync header")
    actual_msf = tuple(_decode_bcd(value) for value in raw[12:15])
    if actual_msf != _expected_msf(absolute_lba):
        raise XasToolError(
            f"absolute LBA {absolute_lba} has MSF {actual_msf}, "
            f"expected {_expected_msf(absolute_lba)}"
        )
    if raw[15] != 2:
        raise XasToolError(f"absolute LBA {absolute_lba} is CD mode {raw[15]}, expected Mode 2")
    if raw[16:20] != raw[20:24]:
        raise XasToolError(f"absolute LBA {absolute_lba} has mismatched XA subheader copies")
    file_number, channel, submode, coding_info = raw[16:20]
    return SectorInfo(relative_sector, file_number, channel, submode, coding_info)


def parse_str_chunk(raw: bytes, *, relative_sector: int) -> StrChunkHeader:
    magic, kind, chunk, chunks, frame, demuxed_size, width, height = struct.unpack_from(
        "<HHHHIIHH", raw, USER_DATA_OFFSET
    )
    if (magic, kind) != (0x0160, 0x8001):
        raise XasToolError(
            f"XAS sector {relative_sector} has invalid STR magic/type "
            f"0x{magic:04X}/0x{kind:04X}"
        )
    if chunks == 0 or chunk >= chunks:
        raise XasToolError(f"XAS sector {relative_sector} has an invalid STR chunk index/count")
    if frame == 0:
        raise XasToolError(f"XAS sector {relative_sector} has STR frame number zero")
    if not 0 < demuxed_size <= chunks * 2016:
        raise XasToolError(f"XAS sector {relative_sector} has an invalid STR demuxed size")
    if width == 0 or height == 0 or width % 2 or height % 2:
        raise XasToolError(f"XAS sector {relative_sector} has invalid STR dimensions")
    return StrChunkHeader(chunk, chunks, frame, demuxed_size, width, height)


def _iso_name(raw_name: bytes) -> str:
    if raw_name in (b"\x00", b"\x01"):
        return "." if raw_name == b"\x00" else ".."
    return raw_name.decode("ascii", errors="replace").split(";", 1)[0].rstrip(".")


def _iter_iso_directory(data: bytes) -> Iterator[IsoRecord]:
    position = 0
    while position < len(data):
        length = data[position]
        if length == 0:
            position = ((position // ISO_SECTOR_SIZE) + 1) * ISO_SECTOR_SIZE
            continue
        if length < 34 or position + length > len(data):
            raise XasToolError("malformed ISO 9660 directory record")
        name_length = data[position + 32]
        name_start = position + 33
        if name_start + name_length > position + length:
            raise XasToolError("malformed ISO 9660 file identifier")
        yield IsoRecord(
            _iso_name(data[name_start : name_start + name_length]),
            struct.unpack_from("<I", data, position + 2)[0],
            struct.unpack_from("<I", data, position + 10)[0],
            bool(data[position + 25] & 0x02),
        )
        position += length


def _read_user_sector(handle: BinaryIO, lba: int) -> bytes:
    handle.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
    data = handle.read(ISO_SECTOR_SIZE)
    if len(data) != ISO_SECTOR_SIZE:
        raise XasToolError(f"Track 1 ends while reading ISO user sector {lba}")
    return data


def _read_iso_extent(handle: BinaryIO, extent: int, size: int) -> bytes:
    output = bytearray()
    for index in range((size + ISO_SECTOR_SIZE - 1) // ISO_SECTOR_SIZE):
        output.extend(_read_user_sector(handle, extent + index))
    return bytes(output[:size])


def _find_xas_iso_record(handle: BinaryIO) -> IsoRecord:
    pvd = _read_user_sector(handle, 16)
    if pvd[:7] != b"\x01CD001\x01":
        raise XasToolError("Track 1 has no Mode 2 ISO 9660 primary volume descriptor")
    root_length = pvd[156]
    if root_length < 34 or 156 + root_length > len(pvd):
        raise XasToolError("ISO primary volume descriptor has no valid root directory")
    current = next(_iter_iso_directory(pvd[156 : 156 + root_length]))
    for index, wanted in enumerate(("TEKKEN3", "TEKKEN3.XAS")):
        directory = _read_iso_extent(handle, current.extent, current.size)
        match = next(
            (record for record in _iter_iso_directory(directory) if record.name.casefold() == wanted.casefold()),
            None,
        )
        if match is None:
            raise XasToolError(f"Track 1 does not contain /TEKKEN3/TEKKEN3.XAS;1")
        if index == 0 and not match.is_directory:
            raise XasToolError("ISO path /TEKKEN3 is not a directory")
        current = match
    if current.is_directory:
        raise XasToolError("ISO path /TEKKEN3/TEKKEN3.XAS unexpectedly identifies a directory")
    return current


def open_verified_track(path: Path) -> tuple[XasSource, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise XasToolError(f"cannot inspect Track 1 image {path}: {exc}") from exc
    if size != TRACK_SIZE:
        raise XasToolError(f"Track 1 size must be {TRACK_SIZE} bytes, got {size}")
    track_sha256 = _hash_file(path)
    if track_sha256 != TRACK_SHA256:
        raise XasToolError(
            "Track 1 SHA-256 does not match the supported Tekken 3 USA image "
            f"(expected {TRACK_SHA256}, got {track_sha256})"
        )
    try:
        with path.open("rb") as handle:
            record = _find_xas_iso_record(handle)
    except OSError as exc:
        raise XasToolError(f"cannot inspect ISO filesystem in {path}: {exc}") from exc
    if (record.extent, record.size) != (XAS_EXTENT_LBA, XAS_LOGICAL_SIZE):
        raise XasToolError(
            "TEKKEN3.XAS ISO extent does not match the supported revision: "
            f"LBA {record.extent}, size {record.size}"
        )
    return XasSource(path, record.extent, record.size // ISO_SECTOR_SIZE), track_sha256


def _sector_selection(descriptors: Sequence[XaDescriptor]) -> dict[int, int]:
    selected: dict[int, int] = {}
    for descriptor in descriptors:
        for relative_sector in range(
            descriptor.first_relative_sector,
            descriptor.last_relative_sector + 1,
            XA_STRIDE,
        ):
            if relative_sector in selected:
                raise XasToolError("XA descriptor sector selections overlap")
            selected[relative_sector] = descriptor.id
    return selected


def scan_xas(
    source: XasSource,
    descriptors: Sequence[XaDescriptor],
    *,
    expected_submode_counts: dict[int, int] | None = None,
) -> ScanResult:
    validate_descriptors(descriptors)
    selection = _sector_selection(descriptors)
    stream_digests = [hashlib.sha256() for _ in descriptors]
    selected_counts = [0] * len(descriptors)
    sector_infos: list[SectorInfo] = []
    str_sectors: list[StrSector] = []
    xas_digest = hashlib.sha256()
    submode_counts: Counter[int] = Counter()

    for relative_sector in range(source.sector_count):
        raw = source.read_raw_sector(relative_sector)
        absolute_lba = source.extent_lba + relative_sector
        info = parse_raw_sector(raw, absolute_lba=absolute_lba, relative_sector=relative_sector)
        sector_infos.append(info)
        xas_digest.update(raw)
        submode_counts[info.submode] += 1

        if info.submode == 0x00:
            if (info.file_number, info.channel, info.coding_info) != (1, 0, 0):
                raise XasToolError(f"XAS padding sector {relative_sector} has unexpected subheader fields")
        elif info.submode in (0x64, 0xE4):
            if info.file_number != 1 or not 0 <= info.channel < XA_STRIDE or info.coding_info != 1:
                raise XasToolError(f"XAS audio sector {relative_sector} has unexpected subheader fields")
        elif info.submode == 0x48:
            if (info.file_number, info.channel, info.coding_info) != (1, 1, 0):
                raise XasToolError(f"XAS STR sector {relative_sector} has unexpected subheader fields")
            str_sectors.append(StrSector(relative_sector, parse_str_chunk(raw, relative_sector=relative_sector)))
        else:
            raise XasToolError(
                f"XAS sector {relative_sector} has unsupported submode 0x{info.submode:02X}"
            )

        descriptor_id = selection.get(relative_sector)
        if descriptor_id is not None:
            descriptor = descriptors[descriptor_id]
            expected_submode = 0xE4 if relative_sector == descriptor.last_relative_sector else 0x64
            if (
                info.file_number,
                info.channel,
                info.submode,
                info.coding_info,
            ) != (1, descriptor.channel, expected_submode, 1):
                raise XasToolError(
                    f"XA descriptor {descriptor.id} selects invalid sector {relative_sector}: "
                    f"subheader={info.file_number}/{info.channel}/0x{info.submode:02X}/0x{info.coding_info:02X}"
                )
            stream_digests[descriptor_id].update(raw)
            selected_counts[descriptor_id] += 1

    for descriptor, selected_count in zip(descriptors, selected_counts):
        if selected_count != descriptor.sector_count:
            raise XasToolError(
                f"XA descriptor {descriptor.id} selected {selected_count} sectors, "
                f"expected {descriptor.sector_count}"
            )
    if expected_submode_counts is not None and dict(submode_counts) != expected_submode_counts:
        pretty = {f"0x{key:02X}": value for key, value in sorted(submode_counts.items())}
        raise XasToolError(f"XAS sector-type counts do not match the supported revision: {pretty}")
    raw_sha256 = xas_digest.hexdigest()
    if source.sector_count == XAS_SECTOR_COUNT and raw_sha256 != XAS_RAW_SHA256:
        raise XasToolError("raw TEKKEN3.XAS sector span hash does not match the supported revision")
    return ScanResult(
        sector_infos,
        str_sectors,
        [digest.hexdigest() for digest in stream_digests],
        raw_sha256,
        submode_counts,
    )


def discover_movie_regions(
    str_sectors: Sequence[StrSector], *, expected_count: int | None = None
) -> list[MovieRegion]:
    if not str_sectors:
        raise XasToolError("TEKKEN3.XAS contains no validated STR sectors")
    movies: list[MovieRegion] = []
    movie_start = 0
    previous_header: StrChunkHeader | None = None
    frame_header: StrChunkHeader | None = None
    expected_chunk = 0

    def finish(end_index: int) -> None:
        segment = str_sectors[movie_start:end_index]
        if not segment:
            raise XasToolError("empty STR movie region")
        if expected_chunk != 0:
            raise XasToolError(
                f"STR movie beginning at sector {segment[0].relative_sector} ends mid-frame"
            )
        dimensions = {(item.header.width, item.header.height) for item in segment}
        if len(dimensions) != 1:
            raise XasToolError("STR dimensions change inside one movie region")
        width, height = next(iter(dimensions))
        frame_numbers = [item.header.frame_number for item in segment if item.header.chunk_index == 0]
        if frame_numbers != list(range(1, len(frame_numbers) + 1)):
            raise XasToolError("STR frame numbers are not contiguous from one")
        movies.append(
            MovieRegion(
                len(movies),
                segment[0].relative_sector,
                segment[-1].relative_sector,
                len(frame_numbers),
                width,
                height,
                tuple(sorted({item.header.chunks_in_frame for item in segment})),
                len(segment),
            )
        )

    for index, item in enumerate(str_sectors):
        header = item.header
        is_new_movie = header.chunk_index == 0 and header.frame_number == 1
        if index == 0:
            if not is_new_movie:
                raise XasToolError("first STR sector is not chunk 0 of frame 1")
        elif is_new_movie:
            finish(index)
            movie_start = index
            previous_header = None
            frame_header = None
            expected_chunk = 0

        if header.chunk_index != expected_chunk:
            raise XasToolError(
                f"STR sector {item.relative_sector} has chunk {header.chunk_index}, "
                f"expected {expected_chunk}"
            )
        if header.chunk_index == 0:
            expected_frame = 1 if previous_header is None else previous_header.frame_number + 1
            if header.frame_number != expected_frame:
                raise XasToolError(
                    f"STR sector {item.relative_sector} has frame {header.frame_number}, "
                    f"expected {expected_frame}"
                )
            frame_header = header
        elif frame_header is None or (
            header.frame_number,
            header.chunks_in_frame,
            header.demuxed_size,
            header.width,
            header.height,
        ) != (
            frame_header.frame_number,
            frame_header.chunks_in_frame,
            frame_header.demuxed_size,
            frame_header.width,
            frame_header.height,
        ):
            raise XasToolError(f"STR sector {item.relative_sector} disagrees with its frame header")

        expected_chunk += 1
        if expected_chunk == header.chunks_in_frame:
            expected_chunk = 0
            previous_header = header

    finish(len(str_sectors))
    if expected_count is not None and len(movies) != expected_count:
        raise XasToolError(f"expected {expected_count} STR movie regions, found {len(movies)}")
    return movies


def _hash_sector_span(source: XasSource, first: int, last: int, stride: int = 1) -> str:
    digest = hashlib.sha256()
    for relative_sector in range(first, last + 1, stride):
        digest.update(source.read_raw_sector(relative_sector))
    return digest.hexdigest()


def build_inventory(
    source: XasSource,
    descriptors: Sequence[XaDescriptor],
    scan: ScanResult,
    movies: Sequence[MovieRegion],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
    track_sha256: str,
) -> dict[str, object]:
    xa_streams: list[dict[str, object]] = []
    for descriptor, digest in zip(descriptors, scan.xa_stream_sha256):
        xa_streams.append(
            {
                "id": descriptor.id,
                "descriptor_file_offset": f"0x{XAS_TABLE_FILE_OFFSET + descriptor.id * XAS_TABLE_ENTRY_SIZE:X}",
                "start_group_sector": descriptor.start_group_sector,
                "end_group_sector": descriptor.end_group_sector,
                "first_relative_sector": descriptor.first_relative_sector,
                "last_relative_sector": descriptor.last_relative_sector,
                "first_absolute_lba": source.extent_lba + descriptor.first_relative_sector,
                "last_absolute_lba": source.extent_lba + descriptor.last_relative_sector,
                "sector_stride": XA_STRIDE,
                "sector_count": descriptor.sector_count,
                "file_number": 1,
                "channel": descriptor.channel,
                "coding_info": "0x01",
                "terminal_submode": "0xE4",
                "raw_sector_stream_size": descriptor.sector_count * RAW_SECTOR_SIZE,
                "raw_sector_stream_sha256": digest,
                "suggested_filename": f"xa-{descriptor.id:03d}.raw",
            }
        )

    movie_items: list[dict[str, object]] = []
    for movie in movies:
        infos = scan.sector_infos[
            movie.start_relative_sector : movie.end_relative_sector + 1
        ]
        counts = Counter(info.submode for info in infos)
        movie_items.append(
            {
                "id": movie.id,
                "boundary_rule": "validated STR chunk 0 frame 1 reset",
                "start_relative_sector": movie.start_relative_sector,
                "end_relative_sector": movie.end_relative_sector,
                "first_absolute_lba": source.extent_lba + movie.start_relative_sector,
                "last_absolute_lba": source.extent_lba + movie.end_relative_sector,
                "span_sector_count": movie.span_sector_count,
                "frame_count": movie.frame_count,
                "width": movie.width,
                "height": movie.height,
                "chunks_per_frame": list(movie.chunks_per_frame),
                "str_sector_count": movie.str_sector_count,
                "xa_sector_count": counts[0x64] + counts[0xE4],
                "padding_sector_count": counts[0x00],
                "str_file_number": 1,
                "str_channel": 1,
                "str_submode": "0x48",
                "str_coding_info": "0x00",
                "xa_file_number": 1,
                "xa_channel": 1,
                "xa_submode": "0x64",
                "xa_coding_info": "0x01",
                "raw_sector_span_size": movie.span_sector_count * RAW_SECTOR_SIZE,
                "raw_sector_span_sha256": _hash_sector_span(
                    source, movie.start_relative_sector, movie.end_relative_sector
                ),
                "suggested_filename": f"movie-{movie.id:03d}.str.raw",
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": GAME_ID,
        "executable": {"path": str(exe_path), "sha256": exe_sha256},
        "descriptor_table": {
            "file_offset": f"0x{XAS_TABLE_FILE_OFFSET:X}",
            "entry_count": XAS_TABLE_ENTRY_COUNT,
            "entry_size": XAS_TABLE_ENTRY_SIZE,
            "sha256": table_sha256,
        },
        "source": {
            "path": str(source.path),
            "container_kind": "raw_track_2352_mode2",
            "container_size": source.path.stat().st_size,
            "track_sha256": track_sha256,
            "iso_path": "/TEKKEN3/TEKKEN3.XAS;1",
            "iso_extent_lba": source.extent_lba,
            "iso_logical_size": source.sector_count * ISO_SECTOR_SIZE,
            "raw_sector_count": source.sector_count,
            "raw_sector_span_sha256": scan.xas_raw_sha256,
            "submode_counts": {
                f"0x{key:02X}": value for key, value in sorted(scan.submode_counts.items())
            },
        },
        "xa_streams": xa_streams,
        "movie_regions": movie_items,
    }


CSV_FIELDS = (
    "kind",
    "id",
    "start_group_sector",
    "end_group_sector",
    "start_relative_sector",
    "end_relative_sector",
    "first_absolute_lba",
    "last_absolute_lba",
    "sector_stride",
    "sector_count",
    "frame_count",
    "width",
    "height",
    "chunks_per_frame",
    "str_sector_count",
    "xa_sector_count",
    "padding_sector_count",
    "file_number",
    "channel",
    "coding_info",
    "sha256",
    "suggested_filename",
)


def _inventory_csv_rows(inventory: dict[str, object]) -> Iterator[dict[str, object]]:
    for item in inventory["xa_streams"]:  # type: ignore[assignment]
        yield {
            "kind": "xa_stream",
            "id": item["id"],
            "start_group_sector": item["start_group_sector"],
            "end_group_sector": item["end_group_sector"],
            "start_relative_sector": item["first_relative_sector"],
            "end_relative_sector": item["last_relative_sector"],
            "first_absolute_lba": item["first_absolute_lba"],
            "last_absolute_lba": item["last_absolute_lba"],
            "sector_stride": item["sector_stride"],
            "sector_count": item["sector_count"],
            "file_number": item["file_number"],
            "channel": item["channel"],
            "coding_info": item["coding_info"],
            "sha256": item["raw_sector_stream_sha256"],
            "suggested_filename": item["suggested_filename"],
        }
    for item in inventory["movie_regions"]:  # type: ignore[assignment]
        yield {
            "kind": "movie_region",
            "id": item["id"],
            "start_relative_sector": item["start_relative_sector"],
            "end_relative_sector": item["end_relative_sector"],
            "first_absolute_lba": item["first_absolute_lba"],
            "last_absolute_lba": item["last_absolute_lba"],
            "sector_stride": 1,
            "sector_count": item["span_sector_count"],
            "frame_count": item["frame_count"],
            "width": item["width"],
            "height": item["height"],
            "chunks_per_frame": ",".join(map(str, item["chunks_per_frame"])),
            "str_sector_count": item["str_sector_count"],
            "xa_sector_count": item["xa_sector_count"],
            "padding_sector_count": item["padding_sector_count"],
            "file_number": item["str_file_number"],
            "channel": item["str_channel"],
            "coding_info": item["str_coding_info"],
            "sha256": item["raw_sector_span_sha256"],
            "suggested_filename": item["suggested_filename"],
        }


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


def write_json(path: Path, inventory: dict[str, object]) -> None:
    def emit(handle: TextIO) -> None:
        json.dump(inventory, handle, indent=2, sort_keys=False)
        handle.write("\n")

    _atomic_write_text(path, emit)


def write_csv(path: Path, inventory: dict[str, object]) -> None:
    def emit(handle: TextIO) -> None:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_inventory_csv_rows(inventory))

    _atomic_write_text(path, emit)


def _check_outputs(paths: Iterable[Path], force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        raise XasToolError(
            "refusing to overwrite existing output(s): "
            + ", ".join(map(str, existing))
            + "; use --force"
        )


def parse_ids(specification: str | None, count: int, label: str) -> list[int]:
    if specification is None:
        return []
    if specification.strip().casefold() == "all":
        return list(range(count))
    selected: set[int] = set()
    for part in specification.split(","):
        part = part.strip()
        if not part:
            raise XasToolError(f"empty item in {label} selection")
        if "-" in part:
            pieces = part.split("-")
            if len(pieces) != 2 or not all(piece.strip().isdigit() for piece in pieces):
                raise XasToolError(f"invalid {label} range: {part}")
            first, last = (int(piece.strip()) for piece in pieces)
            if first > last:
                raise XasToolError(f"descending {label} range is not allowed: {part}")
            selected.update(range(first, last + 1))
        elif part.isdigit():
            selected.add(int(part))
        else:
            raise XasToolError(f"invalid {label}: {part}")
    invalid = sorted(item for item in selected if not 0 <= item < count)
    if invalid:
        raise XasToolError(
            f"{label}(s) outside supported range 0-{count - 1}: " + ", ".join(map(str, invalid))
        )
    return sorted(selected)


def _write_sector_file(source: XasSource, path: Path, sectors: Iterable[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            for relative_sector in sectors:
                handle.write(source.read_raw_sector(relative_sector))
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def extract_selected(
    source: XasSource,
    descriptors: Sequence[XaDescriptor],
    movies: Sequence[MovieRegion],
    inventory: dict[str, object],
    output: Path,
    *,
    xa_ids: Sequence[int],
    movie_ids: Sequence[int],
    force: bool,
) -> list[Path]:
    paths = [output / f"xa-{item:03d}.raw" for item in xa_ids]
    paths.extend(output / f"movie-{item:03d}.str.raw" for item in movie_ids)
    json_path, csv_path = output / "inventory.json", output / "inventory.csv"
    _check_outputs([*paths, json_path, csv_path], force)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for descriptor_id in xa_ids:
        descriptor = descriptors[descriptor_id]
        path = output / f"xa-{descriptor_id:03d}.raw"
        _write_sector_file(
            source,
            path,
            range(
                descriptor.first_relative_sector,
                descriptor.last_relative_sector + 1,
                XA_STRIDE,
            ),
        )
        written.append(path)
    for movie_id in movie_ids:
        movie = movies[movie_id]
        path = output / f"movie-{movie_id:03d}.str.raw"
        _write_sector_file(
            source,
            path,
            range(movie.start_relative_sector, movie.end_relative_sector + 1),
        )
        written.append(path)
    extraction_inventory = dict(inventory)
    extraction_inventory["extraction"] = {
        "xa_ids": list(xa_ids),
        "movie_ids": list(movie_ids),
        "payload_files_written": len(written),
        "format": "unaltered 2352-byte raw sectors",
    }
    write_json(json_path, extraction_inventory)
    write_csv(csv_path, extraction_inventory)
    return written


def _add_common(parser: argparse.ArgumentParser) -> None:
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
        help="exact raw 2352-byte Mode 2 Track 1 image",
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory or locally extract Tekken 3 USA TEKKEN3.XAS streams"
    )
    parser.add_argument("--version", action="version", version="xas_tool 1")
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="validate and catalog XA/STR sectors")
    _add_common(inventory)
    inventory.add_argument("--json", type=Path, help="write JSON inventory here")
    inventory.add_argument("--csv", type=Path, help="write CSV inventory here")
    inventory.add_argument("--force", action="store_true", help="replace requested inventory files")
    extract = commands.add_parser("extract", help="extract selected raw-sector streams")
    _add_common(extract)
    extract.add_argument(
        "--output",
        type=Path,
        default=Path("workspace/xas/streams"),
        help="local output directory (default: workspace/xas/streams)",
    )
    extract.add_argument("--xa-ids", help="XA numeric IDs/ranges, for example 0,4-7")
    extract.add_argument("--movie-ids", help="movie numeric IDs/ranges, for example 0,2-3")
    extract.add_argument("--force", action="store_true", help="replace matching outputs")
    return parser


def _load(args: argparse.Namespace) -> tuple[
    list[XaDescriptor], XasSource, ScanResult, list[MovieRegion], dict[str, object]
]:
    descriptors, exe_sha256, table_sha256 = load_us_descriptors(args.exe)
    source, track_sha256 = open_verified_track(args.source)
    source.__enter__()
    try:
        scan = scan_xas(source, descriptors, expected_submode_counts=EXPECTED_SUBMODE_COUNTS)
        movies = discover_movie_regions(scan.str_sectors, expected_count=EXPECTED_MOVIE_COUNT)
        inventory = build_inventory(
            source,
            descriptors,
            scan,
            movies,
            exe_path=args.exe,
            exe_sha256=exe_sha256,
            table_sha256=table_sha256,
            track_sha256=track_sha256,
        )
    except Exception:
        source.__exit__(None, None, None)
        raise
    return descriptors, source, scan, movies, inventory


def run(args: argparse.Namespace) -> int:
    if args.command == "inventory":
        output_paths = [path for path in (args.json, args.csv) if path is not None]
        _check_outputs(output_paths, args.force)
        _descriptors, source, _scan, _movies, inventory = _load(args)
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
        print("Inventoried 50 XA streams and 22 STR movie regions.", file=sys.stderr)
        return 0

    if args.command == "extract":
        xa_ids = parse_ids(args.xa_ids, XAS_TABLE_ENTRY_COUNT, "XA ID")
        movie_ids = parse_ids(args.movie_ids, EXPECTED_MOVIE_COUNT, "movie ID")
        if not xa_ids and not movie_ids:
            raise XasToolError("extract requires --xa-ids and/or --movie-ids")
        descriptors, source, _scan, movies, inventory = _load(args)
        try:
            written = extract_selected(
                source,
                descriptors,
                movies,
                inventory,
                args.output,
                xa_ids=xa_ids,
                movie_ids=movie_ids,
                force=args.force,
            )
        finally:
            source.__exit__(None, None, None)
        print(f"Extracted {len(written)} raw-sector stream(s) to {args.output}.")
        return 0

    raise XasToolError(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (XasToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
