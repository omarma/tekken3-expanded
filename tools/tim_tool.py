#!/usr/bin/env python3
"""Scan binaries for standard PlayStation TIM images and export PNG previews.

The implementation is original and Python-standard-library-only.  It never
modifies its input.  Strict structural checks intentionally favor rejecting a
custom or malformed image over reporting random binary data as a TIM.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import mmap
import os
import struct
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence


SCHEMA_VERSION = 1
TIM_MAGIC = 0x10
TIM_SIGNATURE = b"\x10\x00\x00\x00"
VRAM_WIDTH_WORDS = 1024
VRAM_HEIGHT = 512
MODE_NAMES = {0: "4bpp", 1: "8bpp", 2: "16bpp", 3: "24bpp"}
BITS_PER_PIXEL = {0: 4, 1: 8, 2: 16, 3: 24}
INDEXED_COLORS = {0: 16, 1: 256}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class TimToolError(RuntimeError):
    """A user-facing input, format, or output error."""


@dataclass(frozen=True)
class TimBlock:
    """One TIM data section, with absolute offsets in the scanned source."""

    offset: int
    size: int
    x: int
    y: int
    width_words: int
    height: int

    @property
    def data_offset(self) -> int:
        return self.offset + 12

    @property
    def data_size(self) -> int:
        return self.size - 12

    @property
    def end_offset(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class TimImage:
    """A validated, uncompressed standard TIM embedded in a source."""

    offset: int
    size: int
    flags: int
    mode: int
    clut: TimBlock | None
    image: TimBlock
    pixel_width: int
    row_padding_bytes: int
    palette_count: int

    @property
    def end_offset(self) -> int:
        return self.offset + self.size

    @property
    def bits_per_pixel(self) -> int:
        return BITS_PER_PIXEL[self.mode]

    @property
    def mode_name(self) -> str:
        return MODE_NAMES[self.mode]


def _parse_block(data: object, offset: int, limit: int, label: str) -> TimBlock:
    if offset < 0 or offset > limit or limit - offset < 12:
        raise TimToolError(f"truncated {label} section header")
    size, x, y, width_words, height = struct.unpack_from("<IHHHH", data, offset)
    if width_words == 0 or height == 0:
        raise TimToolError(f"{label} section has a zero dimension")
    if size != 12 + width_words * height * 2:
        raise TimToolError(f"{label} section size does not match its dimensions")
    if size > limit - offset:
        raise TimToolError(f"truncated {label} section data")
    if x + width_words > VRAM_WIDTH_WORDS or y + height > VRAM_HEIGHT:
        raise TimToolError(f"{label} destination lies outside 1024x512 PS1 VRAM")
    return TimBlock(offset, size, x, y, width_words, height)


def parse_tim(data: object, offset: int = 0) -> TimImage:
    """Parse one standard TIM at ``offset`` in a bytes-like source.

    Accepted flags are the ordinary 4/8bpp indexed modes with a CLUT and the
    ordinary 16/24bpp direct-color modes without one.  Mixed, compressed,
    degenerate, malformed, and game-specific variants are rejected.
    """

    try:
        limit = len(data)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TimToolError("source is not a bytes-like object") from exc
    if offset < 0 or offset > limit or limit - offset < 8:
        raise TimToolError("truncated TIM header")
    magic, flags = struct.unpack_from("<II", data, offset)
    if magic != TIM_MAGIC:
        raise TimToolError("TIM magic/version is not 0x00000010")
    if flags not in (0x08, 0x09, 0x02, 0x03):
        raise TimToolError("unsupported TIM flags or reserved bits")

    mode = flags & 0x7
    position = offset + 8
    clut: TimBlock | None = None
    palette_count = 0
    if flags & 0x8:
        clut = _parse_block(data, position, limit, "CLUT")
        colors_per_palette = INDEXED_COLORS[mode]
        color_count = clut.width_words * clut.height
        if color_count < colors_per_palette or color_count % colors_per_palette:
            raise TimToolError(
                f"{MODE_NAMES[mode]} CLUT does not contain a whole "
                f"{colors_per_palette}-color palette"
            )
        palette_count = color_count // colors_per_palette
        position = clut.end_offset

    image = _parse_block(data, position, limit, "image")
    row_bytes = image.width_words * 2
    if mode == 0:
        pixel_width = image.width_words * 4
        row_padding_bytes = 0
    elif mode == 1:
        pixel_width = image.width_words * 2
        row_padding_bytes = 0
    elif mode == 2:
        pixel_width = image.width_words
        row_padding_bytes = 0
    else:
        # A TIM stores only the row width in 16-bit VRAM words.  Decode every
        # complete RGB triplet and retain the possible 0-2 trailing bytes as
        # row padding in metadata rather than inventing pixels.
        pixel_width, row_padding_bytes = divmod(row_bytes, 3)
        if pixel_width == 0:
            raise TimToolError("24bpp image row is too short for one RGB pixel")

    end_offset = image.end_offset
    return TimImage(
        offset=offset,
        size=end_offset - offset,
        flags=flags,
        mode=mode,
        clut=clut,
        image=image,
        pixel_width=pixel_width,
        row_padding_bytes=row_padding_bytes,
        palette_count=palette_count,
    )


def scan_tims(data: object) -> list[TimImage]:
    """Return non-overlapping standard TIMs in ascending source-offset order."""

    if not hasattr(data, "find"):
        raise TimToolError("source does not support binary scanning")
    results: list[TimImage] = []
    position = 0
    while True:
        candidate = data.find(TIM_SIGNATURE, position)  # type: ignore[attr-defined]
        if candidate < 0:
            break
        try:
            image = parse_tim(data, candidate)
        except (TimToolError, struct.error):
            position = candidate + 1
            continue
        results.append(image)
        position = image.end_offset
    return results


def _psx_color_to_rgba(value: int) -> tuple[int, int, int, int]:
    red = (((value >> 0) & 31) * 255 + 15) // 31
    green = (((value >> 5) & 31) * 255 + 15) // 31
    blue = (((value >> 10) & 31) * 255 + 15) // 31
    if value == 0:
        alpha = 0
    elif value & 0x8000:
        # STP is blend-mode-dependent on hardware.  Alpha 128 is an explicit
        # preview convention; the original bit remains intact in the .tim.
        alpha = 128
    else:
        alpha = 255
    return red, green, blue, alpha


def decode_rgba(data: object, tim: TimImage, palette_index: int = 0) -> bytes:
    """Decode a validated TIM to row-major RGBA8 preview pixels."""

    if tim.mode in (0, 1):
        if tim.clut is None:
            raise TimToolError("indexed TIM has no CLUT")
        if not 0 <= palette_index < tim.palette_count:
            raise TimToolError(
                f"palette {palette_index} is outside 0..{tim.palette_count - 1}"
            )
        colors_per_palette = INDEXED_COLORS[tim.mode]
        palette_start = tim.clut.data_offset + palette_index * colors_per_palette * 2
        palette = [
            _psx_color_to_rgba(struct.unpack_from("<H", data, palette_start + i * 2)[0])
            for i in range(colors_per_palette)
        ]
    elif palette_index != 0:
        raise TimToolError("direct-color TIMs have no selectable palette")

    output = bytearray(tim.pixel_width * tim.image.height * 4)
    destination = 0
    row_bytes = tim.image.width_words * 2
    for row in range(tim.image.height):
        row_start = tim.image.data_offset + row * row_bytes
        if tim.mode == 0:
            for byte_index in range(row_bytes):
                packed = data[row_start + byte_index]  # type: ignore[index]
                for index in (packed & 0x0F, packed >> 4):
                    output[destination : destination + 4] = bytes(palette[index])
                    destination += 4
        elif tim.mode == 1:
            for byte_index in range(row_bytes):
                index = data[row_start + byte_index]  # type: ignore[index]
                output[destination : destination + 4] = bytes(palette[index])
                destination += 4
        elif tim.mode == 2:
            for column in range(tim.pixel_width):
                value = struct.unpack_from("<H", data, row_start + column * 2)[0]
                output[destination : destination + 4] = bytes(_psx_color_to_rgba(value))
                destination += 4
        else:
            # PS1 24-bit VRAM byte order is R, G, B.  Ignore only the trailing
            # bytes that cannot form another complete pixel in this row.
            for column in range(tim.pixel_width):
                source = row_start + column * 3
                output[destination : destination + 4] = bytes(
                    (
                        data[source],  # type: ignore[index]
                        data[source + 1],  # type: ignore[index]
                        data[source + 2],  # type: ignore[index]
                        255,
                    )
                )
                destination += 4
    return bytes(output)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind)
    checksum = binascii.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encode a deterministic, non-interlaced RGBA8 PNG using only stdlib."""

    if width <= 0 or height <= 0:
        raise TimToolError("PNG dimensions must be positive")
    expected = width * height * 4
    if len(rgba) != expected:
        raise TimToolError(f"RGBA payload has {len(rgba)} bytes; expected {expected}")
    stride = width * 4
    scanlines = b"".join(
        b"\x00" + rgba[row * stride : (row + 1) * stride] for row in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(scanlines, 9)),
            _png_chunk(b"IEND", b""),
        )
    )


def _block_manifest(block: TimBlock, tim_offset: int) -> dict[str, object]:
    return {
        "section_offset": block.offset - tim_offset,
        "source_section_offset": block.offset,
        "section_size": block.size,
        "data_offset": block.data_offset - tim_offset,
        "source_data_offset": block.data_offset,
        "data_size": block.data_size,
        "vram_x_words": block.x,
        "vram_y": block.y,
        "width_words": block.width_words,
        "height": block.height,
    }


def texture_manifest(data: object, tim: TimImage, image_id: int) -> dict[str, object]:
    base = f"tim_{image_id:04d}_off_{tim.offset:08X}"
    if tim.palette_count:
        previews = [f"{base}.p{index:03d}.png" for index in range(tim.palette_count)]
    else:
        previews = [f"{base}.png"]
    return {
        "id": image_id,
        "offset": tim.offset,
        "end_offset": tim.end_offset,
        "size": tim.size,
        "sha256": hashlib.sha256(
            data[tim.offset : tim.end_offset]  # type: ignore[index]
        ).hexdigest(),
        "flags": f"0x{tim.flags:08X}",
        "mode": tim.mode_name,
        "bits_per_pixel": tim.bits_per_pixel,
        "has_clut": tim.clut is not None,
        "palette_count": tim.palette_count,
        "pixel_width": tim.pixel_width,
        "height": tim.image.height,
        "row_padding_bytes": tim.row_padding_bytes,
        "image": _block_manifest(tim.image, tim.offset),
        "clut": _block_manifest(tim.clut, tim.offset) if tim.clut else None,
        "suggested_tim_filename": f"{base}.tim",
        "suggested_preview_filenames": previews,
    }


def build_inventory(path: Path, data: object, images: Sequence[TimImage]) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "tim_tool.py",
        "source": {
            "path": str(path),
            "size": len(data),  # type: ignore[arg-type]
            "sha256": hashlib.sha256(data).hexdigest(),  # type: ignore[arg-type]
        },
        "scan": {
            "policy": "strict_standard_uncompressed_non_overlapping",
            "texture_count": len(images),
        },
        "textures": [texture_manifest(data, tim, image_id) for image_id, tim in enumerate(images)],
    }


def parse_ids(expression: str | None, count: int) -> list[int]:
    if expression is None:
        return list(range(count))
    selected: set[int] = set()
    for token in expression.split(","):
        token = token.strip()
        if not token:
            raise TimToolError("empty texture ID in --ids")
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise TimToolError(f"invalid texture ID range: {token}")
            start, end = map(int, parts)
            if start > end:
                raise TimToolError(f"texture ID range goes backwards: {token}")
            selected.update(range(start, end + 1))
        elif token.isdigit():
            selected.add(int(token))
        else:
            raise TimToolError(f"invalid texture ID: {token}")
    if selected and (min(selected) < 0 or max(selected) >= count):
        high = max(count - 1, 0)
        raise TimToolError(f"texture ID is outside 0..{high}")
    return sorted(selected)


def _atomic_write(path: Path, payload: bytes, *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise TimToolError(f"refusing to overwrite existing output: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _json_bytes(document: dict[str, object]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _path_key(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def _preflight(
    paths: Sequence[Path],
    *,
    force: bool,
    protected_paths: Sequence[Path] = (),
) -> None:
    keys = [_path_key(path) for path in paths]
    if len(keys) != len(set(keys)):
        raise TimToolError("two requested outputs resolve to the same path")
    protected = {_path_key(path) for path in protected_paths}
    collision = next((path for path, key in zip(paths, keys) if key in protected), None)
    if collision is not None:
        raise TimToolError(f"output would overwrite the input source: {collision}")
    if force:
        return
    existing = next((path for path in paths if path.exists()), None)
    if existing is not None:
        raise TimToolError(f"refusing to overwrite existing output: {existing}")


def extract_images(
    data: object,
    images: Sequence[TimImage],
    inventory: dict[str, object],
    selected_ids: Sequence[int],
    output: Path,
    *,
    all_palettes: bool,
    force: bool,
    protected_paths: Sequence[Path] = (),
) -> list[Path]:
    """Extract exact TIM blobs, previews, and an inventory atomically per file."""

    rows = inventory["textures"]
    if not isinstance(rows, list):
        raise TimToolError("internal inventory texture list is invalid")
    plans: list[tuple[Path, bytes]] = []
    for image_id in selected_ids:
        tim = images[image_id]
        row = rows[image_id]
        if not isinstance(row, dict):
            raise TimToolError("internal inventory texture row is invalid")
        tim_path = output / str(row["suggested_tim_filename"])
        plans.append((tim_path, bytes(data[tim.offset : tim.end_offset])))  # type: ignore[index]
        preview_names = row["suggested_preview_filenames"]
        if not isinstance(preview_names, list):
            raise TimToolError("internal preview filename list is invalid")
        palette_ids = range(tim.palette_count) if all_palettes else range(min(1, tim.palette_count))
        if not tim.palette_count:
            palette_ids = range(1)
        extracted_previews: list[str] = []
        for palette_id in palette_ids:
            preview_path = output / str(preview_names[palette_id])
            rgba = decode_rgba(data, tim, palette_id)
            plans.append(
                (
                    preview_path,
                    encode_png_rgba(tim.pixel_width, tim.image.height, rgba),
                )
            )
            extracted_previews.append(preview_path.name)
        row["extracted"] = {
            "tim": tim_path.name,
            "previews": extracted_previews,
        }

    inventory_path = output / "inventory.json"
    plans.append((inventory_path, _json_bytes(inventory)))
    _preflight(
        [path for path, _payload in plans],
        force=force,
        protected_paths=protected_paths,
    )
    for path, payload in plans:
        _atomic_write(path, payload, force=force)
    return [path for path, _payload in plans]


class _MappedSource:
    def __init__(self, path: Path):
        self.path = path
        self.handle: BinaryIO | None = None
        self.data: bytes | mmap.mmap = b""

    def __enter__(self) -> bytes | mmap.mmap:
        try:
            self.handle = self.path.open("rb")
            size = self.path.stat().st_size
            self.data = (
                mmap.mmap(self.handle.fileno(), 0, access=mmap.ACCESS_READ) if size else b""
            )
            return self.data
        except OSError as exc:
            if self.handle is not None:
                self.handle.close()
            raise TimToolError(f"cannot read source {self.path}: {exc}") from exc

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if isinstance(self.data, mmap.mmap):
            self.data.close()
        if self.handle is not None:
            self.handle.close()


def _add_common_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, type=Path, help="TIM or binary to scan")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan binary files for standard PS1 TIM images and export PNG previews."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser("inventory", help="write a TIM inventory")
    _add_common_source(inventory_parser)
    inventory_parser.add_argument("--json", type=Path, help="JSON output (stdout if omitted)")
    inventory_parser.add_argument("--force", action="store_true", help="replace existing output")

    extract_parser = subparsers.add_parser("extract", help="extract TIMs and PNG previews")
    _add_common_source(extract_parser)
    extract_parser.add_argument("--output", required=True, type=Path, help="output directory")
    extract_parser.add_argument("--ids", help="texture IDs/ranges, for example 0,2-4")
    extract_parser.add_argument(
        "--all-palettes",
        action="store_true",
        help="export every indexed palette (the first palette is the default)",
    )
    extract_parser.add_argument("--force", action="store_true", help="replace existing outputs")
    return parser


def run(args: argparse.Namespace) -> int:
    with _MappedSource(args.source) as data:
        images = scan_tims(data)
        inventory = build_inventory(args.source, data, images)
        if args.command == "inventory":
            payload = _json_bytes(inventory)
            if args.json:
                _preflight(
                    [args.json],
                    force=args.force,
                    protected_paths=[args.source],
                )
                _atomic_write(args.json, payload, force=args.force)
                print(f"TIM inventory: {len(images)} texture(s) -> {args.json}")
            else:
                sys.stdout.buffer.write(payload)
            return 0

        selected = parse_ids(args.ids, len(images))
        written = extract_images(
            data,
            images,
            inventory,
            selected,
            args.output,
            all_palettes=args.all_palettes,
            force=args.force,
            protected_paths=[args.source],
        )
        print(
            f"TIM extraction: {len(selected)} texture(s), {len(written)} file(s) "
            f"-> {args.output}"
        )
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except (TimToolError, OSError, struct.error, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
