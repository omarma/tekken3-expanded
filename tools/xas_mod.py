#!/usr/bin/env python3
"""Build guarded Tekken 3 XA/STR mod packages from authored raw sectors.

The verified retail BIN/CUE remains read-only.  Input files must already be
encoded as complete 2352-byte Mode 2 sectors.  The package stores only bytes
16..2351 of each authored sector, preserving the stock sync/MSF/mode header at
runtime and, for XA streams, leaving all seven sibling interleave sectors
untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Sequence

try:
    from tools import xas_tool
except ModuleNotFoundError:  # Direct execution: ``python tools/xas_mod.py``.
    import xas_tool  # type: ignore[no-redef]


PACKAGE_FORMAT_VERSION = 6
RAW_HEADER_SIZE = 16
SECTOR_BODY_SIZE = xas_tool.RAW_SECTOR_SIZE - RAW_HEADER_SIZE
MAX_PACKAGE_PAYLOAD = 256 * 1024 * 1024
ID_PATTERN = re.compile(r"^[a-z0-9._-]{1,96}$")
VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)


class XasModError(RuntimeError):
    """A validation or publication error safe to show to a mod author."""


@dataclass(frozen=True)
class ReplacementSpec:
    id: int
    path: Path


@dataclass(frozen=True)
class EncodedValidation:
    raw_sha256: str
    body_sha256: str
    sector_count: int
    width: int | None = None
    height: int | None = None
    frame_count: int | None = None


@dataclass(frozen=True)
class PreparedReplacement:
    kind: str
    id: int
    path: Path
    raw_sha256: str
    payload_sha256: str
    expected_sha256: str
    first_absolute_lba: int
    sector_stride: int
    sector_count: int
    channel: int | None = None
    width: int | None = None
    height: int | None = None
    frame_count: int | None = None

    @property
    def feature_id(self) -> str:
        return f"xas-{self.kind}-{self.id:03d}"

    @property
    def feature_name(self) -> str:
        label = "XA stream" if self.kind == "xa" else "STR movie"
        return f"{label} {self.id:03d}"

    @property
    def relative_asset_path(self) -> str:
        return f"assets/xas/{self.kind}-{self.id:03d}.sector-bodies"

    @property
    def disc_raw_offset(self) -> int:
        return self.first_absolute_lba * xas_tool.RAW_SECTOR_SIZE + RAW_HEADER_SIZE

    @property
    def stride_bytes(self) -> int:
        return self.sector_stride * xas_tool.RAW_SECTOR_SIZE


@dataclass(frozen=True)
class BuildResult:
    output_directory: Path
    archive: Path | None
    replacements: tuple[PreparedReplacement, ...]
    track_sha256: str


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise XasModError(f"file does not exist or is not a regular file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise XasModError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def _parse_replacements(
    values: Iterable[str], *, count: int, label: str
) -> list[ReplacementSpec]:
    parsed: list[ReplacementSpec] = []
    seen: set[int] = set()
    for value in values:
        if "=" not in value:
            raise XasModError(f"{label} replacement must use ID=FILE syntax: {value!r}")
        raw_id, raw_path = (part.strip() for part in value.split("=", 1))
        if not raw_id.isascii() or not raw_id.isdecimal():
            raise XasModError(f"{label} ID is not a decimal integer: {raw_id!r}")
        item_id = int(raw_id, 10)
        if not 0 <= item_id < count:
            raise XasModError(f"{label} ID {item_id} is outside 0-{count - 1}")
        if item_id in seen:
            raise XasModError(f"{label} ID {item_id} was supplied more than once")
        if not raw_path:
            raise XasModError(f"{label} ID {item_id} has an empty file path")
        seen.add(item_id)
        parsed.append(ReplacementSpec(item_id, Path(raw_path)))
    return sorted(parsed, key=lambda item: item.id)


def _edc_table() -> tuple[int, ...]:
    table: list[int] = []
    for value in range(256):
        entry = value
        for _ in range(8):
            entry = (entry >> 1) ^ (0xD8018001 if entry & 1 else 0)
        table.append(entry)
    return tuple(table)


EDC_TABLE = _edc_table()


def _ecc_tables() -> tuple[tuple[int, ...], tuple[int, ...]]:
    forward: list[int] = []
    backward = [0] * 256
    for value in range(256):
        shifted = value << 1
        if shifted & 0x100:
            shifted ^= 0x11D
        forward.append(shifted)
        backward[value ^ shifted] = value
    return tuple(forward), tuple(backward)


ECC_FORWARD, ECC_BACKWARD = _ecc_tables()


def _calculate_edc(data: bytes) -> int:
    result = 0
    for value in data:
        result = (result >> 8) ^ EDC_TABLE[(result ^ value) & 0xFF]
    return result


def _ecc_block(
    source: bytes,
    *,
    major_count: int,
    minor_count: int,
    major_mult: int,
    minor_inc: int,
) -> bytes:
    size = major_count * minor_count
    output = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = ecc_b = 0
        for _ in range(minor_count):
            value = source[index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a ^= value
            ecc_b ^= value
            ecc_a = ECC_FORWARD[ecc_a]
        ecc_a = ECC_BACKWARD[ECC_FORWARD[ecc_a] ^ ecc_b]
        output[major] = ecc_a
        output[major + major_count] = ecc_a ^ ecc_b
    return bytes(output)


def _validate_mode2_form1_ecc(raw: bytes, *, context: str) -> None:
    # Mode 2 Form 1 ECC treats the four address bytes as zero and covers the
    # subheader, user data, and EDC. Q also covers freshly calculated P parity.
    prefix = b"\x00\x00\x00\x00" + raw[16:2076]
    expected_p = _ecc_block(
        prefix,
        major_count=86,
        minor_count=24,
        major_mult=2,
        minor_inc=86,
    )
    if raw[2076:2248] != expected_p:
        raise XasModError(f"{context} has invalid Mode 2 Form 1 ECC P parity")
    expected_q = _ecc_block(
        prefix + expected_p,
        major_count=52,
        minor_count=43,
        major_mult=86,
        minor_inc=88,
    )
    if raw[2248:2352] != expected_q:
        raise XasModError(f"{context} has invalid Mode 2 Form 1 ECC Q parity")


def _validate_sector_envelope(raw: bytes, *, path: Path, index: int) -> tuple[int, int, int, int]:
    context = f"{path} sector {index}"
    if len(raw) != xas_tool.RAW_SECTOR_SIZE:
        raise XasModError(f"{context} is truncated")
    if raw[:12] != xas_tool.SYNC:
        raise XasModError(f"{context} has an invalid CD sync header")
    minute, second, frame = raw[12:15]
    for label, value, maximum in (
        ("minute", minute, 99),
        ("second", second, 59),
        ("frame", frame, 74),
    ):
        high, low = value >> 4, value & 0x0F
        if high > 9 or low > 9 or high * 10 + low > maximum:
            raise XasModError(f"{context} has an invalid BCD {label} byte")
    if raw[15] != 2:
        raise XasModError(f"{context} is CD mode {raw[15]}, expected Mode 2")
    if raw[16:20] != raw[20:24]:
        raise XasModError(f"{context} has mismatched XA subheader copies")
    file_number, channel, submode, coding_info = raw[16:20]
    if submode & 0x20:
        calculated = _calculate_edc(raw[16:2348])
        stored = struct.unpack_from("<I", raw, 2348)[0]
    else:
        calculated = _calculate_edc(raw[16:2072])
        stored = struct.unpack_from("<I", raw, 2072)[0]
    if calculated != stored:
        raise XasModError(
            f"{context} has invalid Mode 2 EDC "
            f"(expected 0x{calculated:08X}, got 0x{stored:08X})"
        )
    if not (submode & 0x20):
        _validate_mode2_form1_ecc(raw, context=context)
    return file_number, channel, submode, coding_info


def validate_encoded_stream(
    path: Path,
    *,
    kind: str,
    sector_count: int,
    channel: int | None = None,
    expected_dimensions: tuple[int, int] | None = None,
    output: BinaryIO | None = None,
) -> EncodedValidation:
    """Validate authored raw sectors and optionally emit their 2336-byte bodies."""

    if kind not in {"xa", "movie"}:
        raise XasModError(f"unsupported encoded stream kind: {kind}")
    if sector_count <= 0:
        raise XasModError("encoded stream sector count must be positive")
    if kind == "xa" and channel is None:
        raise XasModError("XA stream validation requires a channel")
    if not path.is_file():
        raise XasModError(f"encoded {kind} replacement is not a regular file: {path}")
    expected_size = sector_count * xas_tool.RAW_SECTOR_SIZE
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise XasModError(f"cannot inspect encoded replacement {path}: {exc}") from exc
    if actual_size != expected_size:
        raise XasModError(
            f"encoded {kind} replacement has {actual_size} bytes; exact "
            f"{sector_count}-sector size {expected_size} is required"
        )

    raw_digest = hashlib.sha256()
    body_digest = hashlib.sha256()
    str_sectors: list[xas_tool.StrSector] = []
    try:
        with path.open("rb") as handle:
            for index in range(sector_count):
                raw = handle.read(xas_tool.RAW_SECTOR_SIZE)
                fields = _validate_sector_envelope(raw, path=path, index=index)
                file_number, actual_channel, submode, coding_info = fields
                if kind == "xa":
                    expected_submode = 0xE4 if index == sector_count - 1 else 0x64
                    expected = (1, channel, expected_submode, 1)
                    if fields != expected:
                        raise XasModError(
                            f"{path} sector {index} subheader is "
                            f"{file_number}/{actual_channel}/0x{submode:02X}/"
                            f"0x{coding_info:02X}; expected "
                            f"1/{channel}/0x{expected_submode:02X}/0x01"
                        )
                elif submode == 0x48:
                    if fields != (1, 1, 0x48, 0):
                        raise XasModError(f"{path} sector {index} has invalid STR subheader")
                    try:
                        header = xas_tool.parse_str_chunk(raw, relative_sector=index)
                    except xas_tool.XasToolError as exc:
                        raise XasModError(f"{path} sector {index}: {exc}") from exc
                    str_sectors.append(xas_tool.StrSector(index, header))
                elif submode == 0x64:
                    if fields != (1, 1, 0x64, 1):
                        raise XasModError(f"{path} sector {index} has invalid movie XA subheader")
                elif submode == 0xE4:
                    raise XasModError(
                        f"{path} sector {index} has terminal XA submode 0xE4; "
                        "stock movie regions do not own the shared stream terminator"
                    )
                elif submode == 0x00:
                    if fields != (1, 0, 0x00, 0):
                        raise XasModError(f"{path} sector {index} has invalid movie padding subheader")
                else:
                    raise XasModError(
                        f"{path} sector {index} has unsupported movie submode 0x{submode:02X}"
                    )

                raw_digest.update(raw)
                body = raw[RAW_HEADER_SIZE:]
                body_digest.update(body)
                if output is not None:
                    output.write(body)
    except OSError as exc:
        raise XasModError(f"cannot read encoded replacement {path}: {exc}") from exc

    width = height = frame_count = None
    if kind == "movie":
        if not str_sectors:
            raise XasModError(f"encoded movie replacement contains no STR video sectors: {path}")
        try:
            movie = xas_tool.discover_movie_regions(str_sectors, expected_count=1)[0]
        except xas_tool.XasToolError as exc:
            raise XasModError(f"encoded movie replacement is not one valid STR sequence: {exc}") from exc
        width, height, frame_count = movie.width, movie.height, movie.frame_count
        if expected_dimensions is not None and (width, height) != expected_dimensions:
            raise XasModError(
                f"encoded movie dimensions {width}x{height} do not match the "
                f"stock decoder contract {expected_dimensions[0]}x{expected_dimensions[1]}"
            )

    return EncodedValidation(
        raw_sha256=raw_digest.hexdigest(),
        body_sha256=body_digest.hexdigest(),
        sector_count=sector_count,
        width=width,
        height=height,
        frame_count=frame_count,
    )


def _stock_body_sha256(
    source: xas_tool.XasSource,
    sectors: Iterable[int],
    *,
    xa_channel: int | None = None,
) -> str:
    digest = hashlib.sha256()
    sequence = list(sectors)
    for index, relative_sector in enumerate(sequence):
        absolute_lba = source.extent_lba + relative_sector
        raw = source.read_raw_sector(relative_sector)
        try:
            info = xas_tool.parse_raw_sector(
                raw, absolute_lba=absolute_lba, relative_sector=relative_sector
            )
        except xas_tool.XasToolError as exc:
            raise XasModError(f"stock XAS sector validation failed: {exc}") from exc
        if xa_channel is not None:
            expected_submode = 0xE4 if index == len(sequence) - 1 else 0x64
            if (info.file_number, info.channel, info.submode, info.coding_info) != (
                1,
                xa_channel,
                expected_submode,
                1,
            ):
                raise XasModError(
                    f"stock XA sector {relative_sector} does not match descriptor channel/layout"
                )
        digest.update(raw[RAW_HEADER_SIZE:])
    return digest.hexdigest()


def _load_catalog(
    exe_path: Path, track_path: Path, *, need_movies: bool
) -> tuple[
    list[xas_tool.XaDescriptor],
    list[xas_tool.MovieRegion],
    xas_tool.XasSource,
    str,
]:
    try:
        descriptors, _exe_sha256, _table_sha256 = xas_tool.load_us_descriptors(exe_path)
        source, track_sha256 = xas_tool.open_verified_track(track_path)
    except xas_tool.XasToolError as exc:
        raise XasModError(str(exc)) from exc
    movies: list[xas_tool.MovieRegion] = []
    if need_movies:
        with source:
            try:
                scan = xas_tool.scan_xas(
                    source,
                    descriptors,
                    expected_submode_counts=xas_tool.EXPECTED_SUBMODE_COUNTS,
                )
                movies = xas_tool.discover_movie_regions(
                    scan.str_sectors, expected_count=xas_tool.EXPECTED_MOVIE_COUNT
                )
            except xas_tool.XasToolError as exc:
                raise XasModError(str(exc)) from exc
    return descriptors, movies, source, track_sha256


def _prepare_replacements(
    *,
    exe_path: Path,
    track_path: Path,
    xa_specs: Sequence[ReplacementSpec],
    movie_specs: Sequence[ReplacementSpec],
) -> tuple[list[PreparedReplacement], str]:
    descriptors, movies, source, track_sha256 = _load_catalog(
        exe_path, track_path, need_movies=bool(movie_specs)
    )
    prepared: list[PreparedReplacement] = []
    selected_xa_sectors: dict[int, int] = {}
    for specification in xa_specs:
        descriptor = descriptors[specification.id]
        validation = validate_encoded_stream(
            specification.path,
            kind="xa",
            sector_count=descriptor.sector_count,
            channel=descriptor.channel,
        )
        sectors = list(
            range(
                descriptor.first_relative_sector,
                descriptor.last_relative_sector + 1,
                xas_tool.XA_STRIDE,
            )
        )
        for sector in sectors:
            selected_xa_sectors[sector] = descriptor.id
        with source:
            expected_sha256 = _stock_body_sha256(
                source, sectors, xa_channel=descriptor.channel
            )
        prepared.append(
            PreparedReplacement(
                kind="xa",
                id=descriptor.id,
                path=specification.path,
                raw_sha256=validation.raw_sha256,
                payload_sha256=validation.body_sha256,
                expected_sha256=expected_sha256,
                first_absolute_lba=source.extent_lba + descriptor.first_relative_sector,
                sector_stride=xas_tool.XA_STRIDE,
                sector_count=descriptor.sector_count,
                channel=descriptor.channel,
            )
        )

    for specification in movie_specs:
        movie = movies[specification.id]
        overlap = next(
            (
                (sector, selected_xa_sectors[sector])
                for sector in range(
                    movie.start_relative_sector, movie.end_relative_sector + 1
                )
                if sector in selected_xa_sectors
            ),
            None,
        )
        if overlap is not None:
            sector, xa_id = overlap
            raise XasModError(
                f"movie {movie.id:03d} owns XAS sector {sector}, also selected by "
                f"XA stream {xa_id:03d}; place overlapping alternatives in separate packages"
            )
        validation = validate_encoded_stream(
            specification.path,
            kind="movie",
            sector_count=movie.span_sector_count,
            expected_dimensions=(movie.width, movie.height),
        )
        sectors = range(movie.start_relative_sector, movie.end_relative_sector + 1)
        with source:
            expected_sha256 = _stock_body_sha256(source, sectors)
        prepared.append(
            PreparedReplacement(
                kind="movie",
                id=movie.id,
                path=specification.path,
                raw_sha256=validation.raw_sha256,
                payload_sha256=validation.body_sha256,
                expected_sha256=expected_sha256,
                first_absolute_lba=source.extent_lba + movie.start_relative_sector,
                sector_stride=1,
                sector_count=movie.span_sector_count,
                width=validation.width,
                height=validation.height,
                frame_count=validation.frame_count,
            )
        )
    prepared.sort(key=lambda item: (item.kind, item.id))
    total_payload = sum(item.sector_count * SECTOR_BODY_SIZE for item in prepared)
    if total_payload > MAX_PACKAGE_PAYLOAD:
        raise XasModError(
            f"authored sector-body payload is {total_payload} bytes; package safety "
            f"limit is {MAX_PACKAGE_PAYLOAD} bytes"
        )
    return prepared, track_sha256


def _validate_metadata(
    package_id: str, version: str, name: str, author: str, license_name: str
) -> None:
    if (
        not ID_PATTERN.fullmatch(package_id)
        or package_id.startswith(".")
        or package_id.endswith(".")
    ):
        raise XasModError(
            "package ID must be 1-96 lowercase letters, digits, dots, dashes, "
            "or underscores, and may not start or end with a dot"
        )
    if not VERSION_PATTERN.fullmatch(version):
        raise XasModError("version must be a semantic version such as 1.0.0")
    for label, value in (
        ("package name", name),
        ("author", author),
        ("license", license_name),
    ):
        if not value.strip():
            raise XasModError(f"{label} must not be empty")
        if "\x00" in value:
            raise XasModError(f"{label} must not contain a NUL character")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_manifest(
    *,
    package_id: str,
    version: str,
    name: str,
    author: str,
    license_name: str,
    description: str,
    replacements: Sequence[PreparedReplacement],
) -> str:
    lines = [
        f"format_version = {PACKAGE_FORMAT_VERSION}",
        f"id = {_toml_string(package_id)}",
        f"version = {_toml_string(version)}",
        f"name = {_toml_string(name)}",
        f"author = {_toml_string(author)}",
        f"description = {_toml_string(description)}",
        f"license = {_toml_string(license_name)}",
        'resolver = "declarative"',
        'save_compatibility = "shared"',
        "",
        "[[target]]",
        f"game_id = {_toml_string(xas_tool.GAME_ID)}",
        f"exe_sha256 = {_toml_string(xas_tool.US_EXE_SHA256)}",
        f"disc_sha256 = {_toml_string(xas_tool.TRACK_SHA256)}",
    ]
    for item in replacements:
        if item.kind == "xa":
            detail = (
                f"Encoded XA stream on channel {item.channel}, "
                f"{item.sector_count} sectors."
            )
        else:
            detail = (
                f"Encoded STR movie {item.width}x{item.height}, "
                f"{item.frame_count} frames in {item.sector_count} sectors."
            )
        lines.extend(
            [
                "",
                "[[feature]]",
                f"id = {_toml_string(item.feature_id)}",
                f"name = {_toml_string(item.feature_name)}",
                f"description = {_toml_string(detail)}",
                'group = "XAS media replacements"',
                "default_enabled = false",
                "",
                "[[overlay]]",
                f"feature = {_toml_string(item.feature_id)}",
                'target = "disc_raw"',
                f"offset = {item.disc_raw_offset}",
                f"file = {_toml_string(item.relative_asset_path)}",
                f"sha256 = {_toml_string(item.payload_sha256)}",
                f"expected_sha256 = {_toml_string(item.expected_sha256)}",
                f"chunk_size = {SECTOR_BODY_SIZE}",
                f"stride = {item.stride_bytes}",
                f"chunk_count = {item.sector_count}",
            ]
        )
    return "\n".join(lines) + "\n"


def _validate_outputs(
    output_directory: Path,
    archive: Path | None,
    inputs: Sequence[Path],
    exe_path: Path,
    track_path: Path,
) -> None:
    if output_directory.exists():
        raise XasModError(f"refusing to overwrite package source: {output_directory}")
    if archive is not None and archive.exists():
        raise XasModError(f"refusing to overwrite archive: {archive}")
    if archive is not None and archive.suffix.casefold() != ".psxmod":
        raise XasModError("archive output must use the .psxmod extension")
    output_resolved = output_directory.resolve(strict=False)
    protected = [exe_path, track_path, *inputs]
    for path in protected:
        resolved = path.resolve(strict=False)
        if output_resolved == resolved or output_resolved.is_relative_to(resolved):
            raise XasModError(f"package output must not replace or be inside input: {path}")
    if archive is not None:
        archive_resolved = archive.resolve(strict=False)
        if archive_resolved.is_relative_to(output_resolved):
            raise XasModError("archive output must not be inside package source directory")
        if any(archive_resolved == path.resolve(strict=False) for path in protected):
            raise XasModError("archive output must not replace an input file")


def _write_deterministic_archive(source: Path, output: Path) -> None:
    files = sorted(path for path in source.rglob("*") if path.is_file())
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise XasModError(f"unsafe generated archive path: {relative}")
            info = zipfile.ZipInfo(relative)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def build_package(
    *,
    exe_path: Path,
    track_path: Path,
    xa_specs: Sequence[ReplacementSpec],
    movie_specs: Sequence[ReplacementSpec],
    package_id: str,
    version: str,
    name: str,
    author: str,
    license_name: str,
    description: str | None,
    output_directory: Path,
    archive: Path | None = None,
) -> BuildResult:
    _validate_metadata(package_id, version, name, author, license_name)
    if not xa_specs and not movie_specs:
        raise XasModError("at least one --xa-replacement or --movie-replacement is required")
    xa_ids = [item.id for item in xa_specs]
    movie_ids = [item.id for item in movie_specs]
    if len(xa_ids) != len(set(xa_ids)) or len(movie_ids) != len(set(movie_ids)):
        raise XasModError("replacement IDs must be unique within their media kind")
    _validate_outputs(
        output_directory,
        archive,
        [item.path for item in (*xa_specs, *movie_specs)],
        exe_path,
        track_path,
    )
    prepared, track_sha256 = _prepare_replacements(
        exe_path=exe_path,
        track_path=track_path,
        xa_specs=sorted(xa_specs, key=lambda item: item.id),
        movie_specs=sorted(movie_specs, key=lambda item: item.id),
    )
    actual_description = description or (
        f"Tekken 3 XAS media pack with {len(prepared)} independently selectable "
        f"encoded replacement{'s' if len(prepared) != 1 else ''}."
    )
    if "\x00" in actual_description:
        raise XasModError("description must not contain a NUL character")
    manifest = _render_manifest(
        package_id=package_id,
        version=version,
        name=name,
        author=author,
        license_name=license_name,
        description=actual_description,
        replacements=prepared,
    )

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.",
            suffix=".tmp",
            dir=output_directory.parent,
        )
    )
    temporary_archive: Path | None = None
    try:
        (staging / "manifest.toml").write_text(manifest, encoding="utf-8", newline="\n")
        for item in prepared:
            destination = staging / item.relative_asset_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as output:
                validation = validate_encoded_stream(
                    item.path,
                    kind=item.kind,
                    sector_count=item.sector_count,
                    channel=item.channel,
                    expected_dimensions=(item.width, item.height)
                    if item.kind == "movie"
                    else None,
                    output=output,
                )
            if (
                validation.raw_sha256 != item.raw_sha256
                or validation.body_sha256 != item.payload_sha256
                or _sha256_file(destination) != item.payload_sha256
            ):
                raise XasModError(f"replacement {item.feature_name} changed during build")

        if archive is not None:
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f".{archive.name}.",
                suffix=".tmp",
                dir=archive.parent,
                delete=False,
            ) as handle:
                temporary_archive = Path(handle.name)
            _write_deterministic_archive(staging, temporary_archive)
        os.replace(staging, output_directory)
        if archive is not None and temporary_archive is not None:
            os.replace(temporary_archive, archive)
            temporary_archive = None
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if temporary_archive is not None:
            temporary_archive.unlink(missing_ok=True)
        raise
    return BuildResult(output_directory, archive, tuple(prepared), track_sha256)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build guarded .psxmod packages from already encoded, author-owned "
            "Tekken 3 USA XA/STR raw sectors without modifying the disc"
        )
    )
    parser.add_argument("--exe", type=Path, default=Path("disc/SLUS_004.02"))
    parser.add_argument(
        "--track",
        type=Path,
        default=Path("disc/Tekken 3 (USA) (Track 1).bin"),
    )
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--license", dest="license_name", default="LicenseRef-Proprietary")
    parser.add_argument("--description")
    parser.add_argument(
        "--xa-replacement",
        action="append",
        default=[],
        metavar="ID=FILE",
        help="already encoded raw-sector XA stream; repeat for multiple IDs",
    )
    parser.add_argument(
        "--movie-replacement",
        action="append",
        default=[],
        metavar="ID=FILE",
        help="already encoded exact-budget raw-sector STR movie; repeat for multiple IDs",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        xa_specs = _parse_replacements(
            args.xa_replacement,
            count=xas_tool.XAS_TABLE_ENTRY_COUNT,
            label="XA",
        )
        movie_specs = _parse_replacements(
            args.movie_replacement,
            count=xas_tool.EXPECTED_MOVIE_COUNT,
            label="movie",
        )
        result = build_package(
            exe_path=args.exe,
            track_path=args.track,
            xa_specs=xa_specs,
            movie_specs=movie_specs,
            package_id=args.package_id,
            version=args.version,
            name=args.name,
            author=args.author,
            license_name=args.license_name,
            description=args.description,
            output_directory=args.output,
            archive=args.archive,
        )
    except (XasModError, xas_tool.XasToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Built package source: {result.output_directory}")
    if result.archive is not None:
        print(f"Built deterministic archive: {result.archive}")
    print(f"Prepared {len(result.replacements)} default-off XAS replacement feature(s).")
    print("Only distribute the package if you own redistribution rights to every input sector.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
