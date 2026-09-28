#!/usr/bin/env python3
"""Strict RGBA PNG to exact-size standard PlayStation TIM re-encoder.

The original TIM supplies the complete layout contract.  This tool changes
only its pixel payload, preserves all headers/VRAM coordinates/row padding and
preserves indexed CLUT bytes.  It never edits the input files or builds a mod
package.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

try:  # Support both direct CLI execution and package imports in tests.
    from . import tim_tool
except ImportError:  # pragma: no cover - direct CLI path
    import tim_tool  # type: ignore[no-redef]


SCHEMA_VERSION = 1
MAX_PNG_DECODE_BYTES = 256 * 1024 * 1024
VALID_ALPHA_CLASSES = (0, 128, 255)


class TimImportError(RuntimeError):
    """A user-facing PNG, policy, or re-encoding error."""


@dataclass(frozen=True)
class RgbaPng:
    width: int
    height: int
    rgba: bytes


@dataclass(frozen=True)
class ReencodeResult:
    data: bytes
    report: dict[str, object]


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distance_left = abs(estimate - left)
    distance_above = abs(estimate - above)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def _unfilter_scanline(
    filtered: bytes, previous: bytes, filter_type: int, bytes_per_pixel: int
) -> bytes:
    if filter_type not in range(5):
        raise TimImportError(f"unsupported PNG row filter {filter_type}")
    output = bytearray(len(filtered))
    for index, value in enumerate(filtered):
        left = output[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        above = previous[index] if previous else 0
        upper_left = (
            previous[index - bytes_per_pixel]
            if previous and index >= bytes_per_pixel
            else 0
        )
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        else:
            predictor = _paeth(left, above, upper_left)
        output[index] = (value + predictor) & 0xFF
    return bytes(output)


def decode_png_rgba(
    payload: bytes,
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> RgbaPng:
    """Decode a strict non-interlaced RGBA8 PNG with verified CRCs."""

    if not payload.startswith(tim_tool.PNG_SIGNATURE):
        raise TimImportError("input is not a PNG file")
    position = len(tim_tool.PNG_SIGNATURE)
    width = height = 0
    seen_ihdr = False
    seen_idat = False
    ended_idat = False
    seen_iend = False
    compressed = bytearray()

    while position < len(payload):
        if len(payload) - position < 12:
            raise TimImportError("truncated PNG chunk")
        length = struct.unpack_from(">I", payload, position)[0]
        if length > len(payload) - position - 12:
            raise TimImportError("PNG chunk length exceeds the file")
        kind = payload[position + 4 : position + 8]
        if (
            len(kind) != 4
            or any(not (65 <= value <= 90 or 97 <= value <= 122) for value in kind)
            or kind[2] & 0x20
        ):
            raise TimImportError("PNG contains an invalid chunk type")
        data_start = position + 8
        data_end = data_start + length
        chunk_data = payload[data_start:data_end]
        stored_crc = struct.unpack_from(">I", payload, data_end)[0]
        calculated_crc = binascii.crc32(kind)
        calculated_crc = binascii.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            label = kind.decode("ascii", errors="replace")
            raise TimImportError(f"PNG {label} chunk has a bad CRC")
        position = data_end + 4

        if not seen_ihdr and kind != b"IHDR":
            raise TimImportError("PNG IHDR must be the first chunk")
        if kind == b"IHDR":
            if seen_ihdr or length != 13:
                raise TimImportError("PNG must contain one 13-byte IHDR")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression_method,
                filter_method,
                interlace_method,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if width == 0 or height == 0:
                raise TimImportError("PNG dimensions must be positive")
            if (bit_depth, color_type) != (8, 6):
                raise TimImportError("PNG must be 8-bit RGBA (color type 6)")
            if (compression_method, filter_method, interlace_method) != (0, 0, 0):
                raise TimImportError(
                    "PNG must use standard compression/filtering and no interlace"
                )
            if expected_width is not None and width != expected_width:
                raise TimImportError(
                    f"PNG width {width} does not match TIM width {expected_width}"
                )
            if expected_height is not None and height != expected_height:
                raise TimImportError(
                    f"PNG height {height} does not match TIM height {expected_height}"
                )
            decoded_size = width * height * 4
            filtered_size = height * (width * 4 + 1)
            if max(decoded_size, filtered_size) > MAX_PNG_DECODE_BYTES:
                raise TimImportError("decoded PNG exceeds the safety size limit")
            seen_ihdr = True
        elif kind == b"IDAT":
            if ended_idat:
                raise TimImportError("PNG IDAT chunks must be consecutive")
            seen_idat = True
            compressed.extend(chunk_data)
        elif kind == b"IEND":
            if length != 0 or not seen_idat:
                raise TimImportError("PNG has an invalid IEND or no IDAT data")
            if position != len(payload):
                raise TimImportError("PNG has bytes after IEND")
            seen_iend = True
            break
        else:
            if seen_idat:
                ended_idat = True
            if kind in (b"acTL", b"fcTL", b"fdAT"):
                raise TimImportError("animated PNG is not supported")
            # An uppercase first type byte marks a critical chunk.  Unknown
            # critical chunks change decoding and therefore cannot be ignored.
            if kind and not (kind[0] & 0x20):
                label = kind.decode("ascii", errors="replace")
                raise TimImportError(f"unsupported critical PNG chunk {label}")

    if not seen_ihdr or not seen_idat or not seen_iend:
        raise TimImportError("PNG is missing IHDR, IDAT, or IEND")

    stride = width * 4
    expected_raw_size = height * (stride + 1)
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(bytes(compressed), expected_raw_size + 1)
        # A max_length hit leaves compressed input unconsumed.  Reject before
        # flush so a malformed/zlib-bomb stream cannot expand without a cap.
        if inflater.unconsumed_tail or len(raw) > expected_raw_size:
            raise TimImportError(
                "PNG decompressed data exceeds the declared dimensions"
            )
        raw += inflater.flush(expected_raw_size + 1 - len(raw))
    except zlib.error as exc:
        raise TimImportError(f"invalid PNG zlib stream: {exc}") from exc
    if (
        not inflater.eof
        or inflater.unused_data
        or inflater.unconsumed_tail
        or len(raw) != expected_raw_size
    ):
        raise TimImportError(
            f"PNG decompressed data size is {len(raw)}; expected {expected_raw_size}"
        )

    rgba = bytearray(width * height * 4)
    previous = b""
    source = 0
    destination = 0
    for _row in range(height):
        filter_type = raw[source]
        source += 1
        filtered = raw[source : source + stride]
        source += stride
        scanline = _unfilter_scanline(filtered, previous, filter_type, 4)
        rgba[destination : destination + stride] = scanline
        destination += stride
        previous = scanline
    return RgbaPng(width, height, bytes(rgba))


def _pixels(rgba: bytes) -> list[tuple[int, int, int, int]]:
    if len(rgba) % 4:
        raise TimImportError("internal RGBA payload is not pixel-aligned")
    return [tuple(rgba[index : index + 4]) for index in range(0, len(rgba), 4)]  # type: ignore[list-item]


def _validate_alpha(pixel: tuple[int, int, int, int], pixel_index: int) -> None:
    red, green, blue, alpha = pixel
    if alpha not in VALID_ALPHA_CLASSES:
        raise TimImportError(
            f"pixel {pixel_index} alpha {alpha} is ambiguous; use only 0, 128, or 255"
        )
    if alpha == 0 and (red, green, blue) != (0, 0, 0):
        raise TimImportError(
            f"pixel {pixel_index} is transparent but retains nonzero RGB; "
            "transparent PS1 color must be RGBA 0,0,0,0"
        )


def _read_indexed_pixels(original: bytes, tim: tim_tool.TimImage) -> list[int]:
    indices: list[int] = []
    row_bytes = tim.image.width_words * 2
    for row in range(tim.image.height):
        row_start = tim.image.data_offset + row * row_bytes
        if tim.mode == 0:
            for packed in original[row_start : row_start + row_bytes]:
                indices.extend((packed & 0x0F, packed >> 4))
        else:
            indices.extend(original[row_start : row_start + row_bytes])
    return indices


def _indexed_palette(
    original: bytes, tim: tim_tool.TimImage
) -> tuple[list[int], list[tuple[int, int, int, int]]]:
    if tim.clut is None:
        raise TimImportError("indexed TIM has no CLUT")
    if tim.palette_count != 1:
        raise TimImportError(
            f"indexed import requires exactly one palette; TIM contains {tim.palette_count}"
        )
    count = tim_tool.INDEXED_COLORS[tim.mode]
    values = list(struct.unpack_from(f"<{count}H", original, tim.clut.data_offset))
    colors = [tim_tool._psx_color_to_rgba(value) for value in values]
    return values, colors


def _map_indexed_pixels(
    desired: Sequence[tuple[int, int, int, int]],
    original_indices: Sequence[int],
    palette: Sequence[tuple[int, int, int, int]],
    *,
    nearest_palette: bool,
) -> tuple[list[int], int]:
    mapped: list[int] = []
    changed = 0
    exact_by_color: dict[tuple[int, int, int, int], list[int]] = {}
    by_alpha: dict[int, list[int]] = {alpha: [] for alpha in VALID_ALPHA_CLASSES}
    for palette_index, color in enumerate(palette):
        exact_by_color.setdefault(color, []).append(palette_index)
        by_alpha.setdefault(color[3], []).append(palette_index)

    for pixel_index, (pixel, original_index) in enumerate(
        zip(desired, original_indices)
    ):
        _validate_alpha(pixel, pixel_index)
        if palette[original_index] == pixel:
            selected = original_index
        else:
            exact = exact_by_color.get(pixel)
            if exact:
                selected = exact[0]
            elif nearest_palette:
                candidates = by_alpha.get(pixel[3], [])
                if not candidates:
                    raise TimImportError(
                        f"pixel {pixel_index} has alpha class {pixel[3]} but the "
                        "existing palette has no matching transparency/STP class"
                    )
                selected = min(
                    candidates,
                    key=lambda index: (
                        sum(
                            (pixel[channel] - palette[index][channel]) ** 2
                            for channel in range(3)
                        ),
                        index,
                    ),
                )
            else:
                raise TimImportError(
                    f"pixel {pixel_index} RGBA {pixel} is not present in the existing "
                    "palette; use --nearest-palette explicitly to quantize RGB"
                )
        mapped.append(selected)
        if selected != original_index:
            changed += 1
    return mapped, changed


def _write_indexed_pixels(
    output: bytearray, tim: tim_tool.TimImage, indices: Sequence[int]
) -> None:
    expected = tim.pixel_width * tim.image.height
    if len(indices) != expected:
        raise TimImportError("internal indexed pixel count mismatch")
    source = 0
    row_bytes = tim.image.width_words * 2
    for row in range(tim.image.height):
        row_start = tim.image.data_offset + row * row_bytes
        if tim.mode == 0:
            for byte_index in range(row_bytes):
                low = indices[source]
                high = indices[source + 1]
                source += 2
                output[row_start + byte_index] = low | (high << 4)
        else:
            output[row_start : row_start + row_bytes] = bytes(
                indices[source : source + row_bytes]
            )
            source += row_bytes


_PSX_CHANNEL_LEVELS = tuple(
    ((value * 255 + 15) // 31) for value in range(32)
)
_EXACT_PSX_CHANNEL = {expanded: value for value, expanded in enumerate(_PSX_CHANNEL_LEVELS)}


def _encode_channel(value: int, *, quantize: bool, pixel_index: int) -> int:
    exact = _EXACT_PSX_CHANNEL.get(value)
    if exact is not None:
        return exact
    if not quantize:
        raise TimImportError(
            f"pixel {pixel_index} RGB channel {value} is not an exact PS1 5-bit "
            "round-trip value; use --quantize-16bpp explicitly"
        )
    return (value * 31 + 127) // 255


def _rgba_to_psx_word(
    pixel: tuple[int, int, int, int], *, quantize: bool, pixel_index: int
) -> int:
    _validate_alpha(pixel, pixel_index)
    red, green, blue, alpha = pixel
    if alpha == 0:
        return 0
    word = (
        _encode_channel(red, quantize=quantize, pixel_index=pixel_index)
        | (_encode_channel(green, quantize=quantize, pixel_index=pixel_index) << 5)
        | (_encode_channel(blue, quantize=quantize, pixel_index=pixel_index) << 10)
    )
    if alpha == 128:
        word |= 0x8000
    elif word == 0:
        raise TimImportError(
            f"pixel {pixel_index} requests opaque black, which PS1 word 0 treats as "
            "transparent; choose a nonzero quantized color or explicit STP alpha 128"
        )
    return word


def reencode_tim(
    original: bytes,
    png: RgbaPng,
    *,
    nearest_palette: bool = False,
    quantize_16bpp: bool = False,
) -> ReencodeResult:
    """Return an exact-size TIM with pixels encoded under explicit policies."""

    try:
        tim = tim_tool.parse_tim(original)
    except tim_tool.TimToolError as exc:
        raise TimImportError(str(exc)) from exc
    if tim.offset != 0 or tim.size != len(original):
        raise TimImportError("original must be one standalone TIM with no trailing bytes")
    if (png.width, png.height) != (tim.pixel_width, tim.image.height):
        raise TimImportError(
            f"PNG dimensions {png.width}x{png.height} do not match TIM "
            f"{tim.pixel_width}x{tim.image.height}"
        )
    if len(png.rgba) != png.width * png.height * 4:
        raise TimImportError("PNG RGBA payload size does not match its dimensions")
    if nearest_palette and tim.mode not in (0, 1):
        raise TimImportError("--nearest-palette applies only to 4/8bpp indexed TIMs")
    if quantize_16bpp and tim.mode != 2:
        raise TimImportError("--quantize-16bpp applies only to 16bpp TIMs")

    output = bytearray(original)
    desired = _pixels(png.rgba)
    changed_pixels = 0
    policy: str

    if tim.mode in (0, 1):
        _values, palette = _indexed_palette(original, tim)
        original_indices = _read_indexed_pixels(original, tim)
        mapped, changed_pixels = _map_indexed_pixels(
            desired,
            original_indices,
            palette,
            nearest_palette=nearest_palette,
        )
        _write_indexed_pixels(output, tim, mapped)
        policy = "nearest_existing_palette_same_alpha" if nearest_palette else "exact_existing_palette"
        clut_preserved = True
    elif tim.mode == 2:
        for pixel_index, pixel in enumerate(desired):
            offset = tim.image.data_offset + pixel_index * 2
            original_word = struct.unpack_from("<H", original, offset)[0]
            if tim_tool._psx_color_to_rgba(original_word) == pixel:
                word = original_word
            else:
                word = _rgba_to_psx_word(
                    pixel, quantize=quantize_16bpp, pixel_index=pixel_index
                )
            if word != original_word:
                changed_pixels += 1
                struct.pack_into("<H", output, offset, word)
        policy = "nearest_rgb555_explicit" if quantize_16bpp else "exact_rgb555_roundtrip"
        clut_preserved = None
    else:
        row_bytes = tim.image.width_words * 2
        pixel_index = 0
        for row in range(tim.image.height):
            row_start = tim.image.data_offset + row * row_bytes
            for column in range(tim.pixel_width):
                pixel = desired[pixel_index]
                if pixel[3] != 255:
                    raise TimImportError(
                        f"pixel {pixel_index} alpha {pixel[3]} is invalid for 24bpp; "
                        "direct RGB TIMs require alpha 255"
                    )
                source = row_start + column * 3
                rgb = bytes(pixel[:3])
                if output[source : source + 3] != rgb:
                    changed_pixels += 1
                    output[source : source + 3] = rgb
                pixel_index += 1
        policy = "exact_rgb888"
        clut_preserved = None

    encoded = bytes(output)
    try:
        check = tim_tool.parse_tim(encoded)
    except tim_tool.TimToolError as exc:  # pragma: no cover - defensive invariant
        raise TimImportError(f"internal output TIM validation failed: {exc}") from exc
    if check.size != len(original) or len(encoded) != len(original):
        raise TimImportError("internal output TIM size changed")
    if (
        check.flags != tim.flags
        or check.pixel_width != tim.pixel_width
        or check.image != tim.image
        or check.clut != tim.clut
    ):
        raise TimImportError("internal output TIM layout changed")

    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "operation": "exact-size TIM pixel re-encode",
        "mode": tim.mode_name,
        "bits_per_pixel": tim.bits_per_pixel,
        "width": tim.pixel_width,
        "height": tim.image.height,
        "palette_count": tim.palette_count,
        "policy": policy,
        "changed_pixels": changed_pixels,
        "pixel_count": tim.pixel_width * tim.image.height,
        "exact_size": len(encoded) == len(original),
        "clut_preserved": clut_preserved,
        "layout_preserved": True,
        "row_padding_preserved": True,
        "row_padding_bytes_per_row": tim.row_padding_bytes,
        "artifact_status": "private_local_derived_staging_artifact",
        "redistribution": (
            "not_independently_authored; do not redistribute without permission "
            "or proof that every redistributed byte is independently authored"
        ),
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    return ReencodeResult(encoded, report)


def _read(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TimImportError(f"cannot read {label} {path}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Re-encode an identical-dimension RGBA PNG into one strict standard "
            "PS1 TIM while preserving its exact layout and size."
        ),
        epilog=(
            "The output retains bytes from the original and is a private local "
            "derived staging artifact, not an independently authored release file."
        ),
    )
    parser.add_argument("--original", required=True, type=Path, help="standalone stock-layout TIM")
    parser.add_argument("--png", required=True, type=Path, help="8-bit non-interlaced RGBA PNG")
    parser.add_argument("--output", required=True, type=Path, help="exact-size TIM output")
    parser.add_argument("--report", type=Path, help="optional deterministic JSON report")
    parser.add_argument(
        "--nearest-palette",
        action="store_true",
        help="for indexed TIMs, quantize RGB to the nearest existing entry within the same alpha/STP class",
    )
    parser.add_argument(
        "--quantize-16bpp",
        action="store_true",
        help="for 16bpp TIMs, round RGB to nearest 5-bit channels; alpha must still be 0/128/255",
    )
    parser.add_argument("--force", action="store_true", help="replace output/report")
    return parser


def run(args: argparse.Namespace) -> int:
    outputs = [args.output] + ([args.report] if args.report is not None else [])
    tim_tool._preflight(
        outputs,
        force=args.force,
        protected_paths=[args.original, args.png],
    )
    original = _read(args.original, "original TIM")
    png_payload = _read(args.png, "PNG")
    try:
        tim = tim_tool.parse_tim(original)
    except tim_tool.TimToolError as exc:
        raise TimImportError(str(exc)) from exc
    if tim.size != len(original):
        raise TimImportError("original must be one standalone TIM with no trailing bytes")
    png = decode_png_rgba(
        png_payload,
        expected_width=tim.pixel_width,
        expected_height=tim.image.height,
    )
    result = reencode_tim(
        original,
        png,
        nearest_palette=args.nearest_palette,
        quantize_16bpp=args.quantize_16bpp,
    )
    report = dict(result.report)
    report["inputs"] = {
        "original": {
            "path": str(args.original),
            "size": len(original),
            "sha256": hashlib.sha256(original).hexdigest(),
        },
        "png": {
            "path": str(args.png),
            "size": len(png_payload),
            "sha256": hashlib.sha256(png_payload).hexdigest(),
        },
    }
    report["output"] = {
        "path": str(args.output),
        "size": len(result.data),
        "sha256": hashlib.sha256(result.data).hexdigest(),
    }
    tim_tool._atomic_write(args.output, result.data, force=args.force)
    if args.report is not None:
        tim_tool._atomic_write(
            args.report,
            (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            force=args.force,
        )
    print(
        f"TIM re-encode: {tim.mode_name} {tim.pixel_width}x{tim.image.height}, "
        f"{result.report['changed_pixels']} changed pixel(s), exact-size private "
        f"derived staging artifact -> {args.output}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except (
        TimImportError,
        tim_tool.TimToolError,
        OSError,
        struct.error,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
