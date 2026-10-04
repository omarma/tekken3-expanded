#!/usr/bin/env python3
"""Pack a disc track file (.bin, raw 2352-byte sectors) losslessly for the APK.

The packed file is what the APK carries instead of the track; the runtime
reads it in place with random access (psxrecomp/runtime/src/disc_pack.c,
through android_apk_file.c) and gives the game every byte of the original,
unchanged. Format "PSXPACK1" (all little-endian):

  header (64 bytes)
     0  magic "PSXPACK1"
     8  u64 size of the original file in bytes
    16  u32 sector size (2352)
    20  u32 sectors per block
    24  u32 block count
    28  u32 address of sector 0 (its header's MSF as a frame number), or 0
    32  u64 offset of the block index (64)
    40  24 reserved bytes (0)
  block index: block count + 1 u64 offsets from the start of the file; block
  i is the bytes [index[i], index[i + 1]).
  block: 1 method byte (0 stored, 1 raw deflate), then the payload, deflated
  or not: one type byte per sector of the block, then each sector's body.

Sector types: what is stored, and what the reader computes back.

  RAW        the whole sector (a shorter last sector: what is left of the file)
  ZERO       nothing: 2352 zero bytes (silence, empty pregap)
  FORM1      subheader (4) + user data (2048). Mode 2 Form 1: the sync and the
             header (from the sector's address), the subheader's copy, the EDC
             and the ECC (P and Q) are computed back.
  FORM2      subheader (4) + user data (2324). Mode 2 Form 2: sync, header,
             subheader copy and EDC computed back.
  FORM2_NOEDC as FORM2, the EDC field being 0 (allowed for Form 2).
  XA, XA_NOEDC as FORM2, for XA-ADPCM audio: each of the 18 sound groups
             stores its 16-byte header without its duplicated halves (8 bytes),
             and the 20 padding bytes are zero.
  AUDIO      CD audio (16-bit stereo): each channel's sample differences,
             low bytes then high bytes, which deflate packs better than PCM.

Every sector is checked when packing: a sector is given a computed-back type
only when computing it back gives exactly the original bytes (its EDC and ECC
verify, its header is the expected address...); any other sector is RAW. So
the packed file always unpacks to the original, byte for byte.

Usage:
  disc_pack.py pack <track.bin> <packed>          pack one track
  disc_pack.py unpack <packed> <track.bin>        and back (checks)
  disc_pack.py stats <track.bin>...               what packing would give,
                                                  per sector type (no output)
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
import zlib
from pathlib import Path

MAGIC = b"PSXPACK1"
HEADER = struct.Struct("<8sQIIIIQ24x")
SECTOR = 2352
SECTORS_PER_BLOCK = 16
BATCH = 4096          # sectors checked at once

RAW, ZERO, FORM1, FORM2, FORM2_NOEDC, XA, XA_NOEDC, AUDIO = range(8)
TYPE_NAMES = ("raw", "zero", "form1", "form2", "form2-noedc", "xa", "xa-noedc", "audio")
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"
ZERO_SECTOR = bytes(SECTOR)
XA_GROUPS = 18

# --- EDC and ECC (ECMA-130), on one sector -----------------------------------

EDC_POLY = 0xD8018001     # x^32 + x^31 + x^16 + x^15 + x^4 + x^3 + x + 1, reflected


def _edc_table() -> list[int]:
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (EDC_POLY if c & 1 else 0)
        table.append(c)
    return table


EDC_TABLE = _edc_table()
ECC_F = [((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF for i in range(256)]
ECC_B = [0] * 256
for _i in range(256):
    ECC_B[_i ^ ECC_F[_i]] = _i


def edc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = (crc >> 8) ^ EDC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def _ecc_block(src: bytes, major_count: int, minor_count: int, major_mult: int,
               minor_inc: int) -> bytes:
    size = major_count * minor_count
    out = bytearray(2 * major_count)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        out[major] = a
        out[major + major_count] = a ^ b
    return bytes(out)


def ecc_mode2(sector: bytearray) -> None:
    """Writes the P and Q parity of a Mode 2 Form 1 sector (header taken as 0)."""
    src = bytearray(sector[12:12 + 2064])
    src[0:4] = b"\0\0\0\0"
    sector[2076:2248] = _ecc_block(bytes(src), 86, 24, 2, 86)
    src = bytes(src) + bytes(sector[2076:2248])
    sector[2248:2352] = _ecc_block(src, 52, 43, 86, 88)


def bcd(n: int) -> int:
    return (n // 10) << 4 | n % 10


def address_header(frame: int, mode: int = 2) -> bytes:
    """The 4 header bytes of the sector at this address (MSF as a frame count)."""
    return bytes((bcd(frame // 4500), bcd(frame // 75 % 60), bcd(frame % 75), mode))


def header_frame(header: bytes) -> int | None:
    digits = []
    for b in header[:3]:
        if (b >> 4) > 9 or (b & 15) > 9:
            return None
        digits.append((b >> 4) * 10 + (b & 15))
    m, s, f = digits
    if s >= 60 or f >= 75:
        return None
    return (m * 60 + s) * 75 + f


# --- Sectors back from their bodies (the reader's job; also the tests') ------


def xa_body(data: bytes) -> bytes:
    """The 2324 bytes of an XA sector's data, without what can be computed back."""
    out = bytearray()
    for g in range(XA_GROUPS):
        group = data[g * 128:(g + 1) * 128]
        out += group[0:4] + group[8:12] + group[16:128]
    return bytes(out)


def xa_data(body: bytes) -> bytes:
    out = bytearray()
    for g in range(XA_GROUPS):
        part = body[g * 120:(g + 1) * 120]
        out += part[0:4] * 2 + part[4:8] * 2 + part[8:120]
    return bytes(out) + bytes(20)


def audio_body(sector: bytes) -> bytes:
    """Each channel's sample differences (mod 2^16), low bytes then high bytes."""
    x = int.from_bytes(sector, "little")
    previous = (x << 32) & _MASK_SECTOR
    d = _sub16(x, previous).to_bytes(SECTOR, "little")
    return d[0::2] + d[1::2]


def audio_sector(body: bytes) -> bytes:
    d = bytearray(SECTOR)
    d[0::2] = body[:SECTOR // 2]
    d[1::2] = body[SECTOR // 2:]
    samples = struct.unpack(f"<{SECTOR // 2}H", d)
    out = [0] * len(samples)
    left = right = 0
    for i in range(0, len(samples), 2):
        left = (left + samples[i]) & 0xFFFF
        right = (right + samples[i + 1]) & 0xFFFF
        out[i], out[i + 1] = left, right
    return struct.pack(f"<{SECTOR // 2}H", *out)


def body_size(kind: int, raw_length: int = SECTOR) -> int:
    return {RAW: raw_length, ZERO: 0, FORM1: 4 + 2048, FORM2: 4 + 2324,
            FORM2_NOEDC: 4 + 2324, XA: 4 + XA_GROUPS * 120, XA_NOEDC: 4 + XA_GROUPS * 120,
            AUDIO: SECTOR}[kind]


def rebuild(kind: int, body: bytes, frame: int) -> bytes:
    """A sector from its type and body (frame: its address)."""
    if kind == RAW:
        return body
    if kind == ZERO:
        return ZERO_SECTOR
    if kind == AUDIO:
        return audio_sector(body)
    sector = bytearray(SECTOR)
    sector[0:12] = SYNC
    sector[12:16] = address_header(frame)
    sub = body[0:4]
    sector[16:20] = sector[20:24] = sub
    if kind == FORM1:
        sector[24:2072] = body[4:2052]
        sector[2072:2076] = struct.pack("<I", edc(sector[16:2072]))
        ecc_mode2(sector)
        return bytes(sector)
    sector[24:2348] = body[4:] if kind in (FORM2, FORM2_NOEDC) else xa_data(body[4:])
    if kind in (FORM2, XA):
        sector[2348:2352] = struct.pack("<I", edc(sector[16:2348]))
    return bytes(sector)


# --- Many sectors at once (packing) ------------------------------------------
# Python is slow byte by byte, so the EDC and the ECC of a batch of sectors are
# computed on big integers that hold one lane per sector (SWAR): the same few
# operations then run over every sector of the batch at once.

_MASK_SECTOR = (1 << (8 * SECTOR)) - 1


def _repeat(byte_pattern: bytes, count: int) -> int:
    return int.from_bytes(byte_pattern * count, "little")


def _sub16(x: int, y: int) -> int:
    """Lane-wise x - y mod 2^16 on 16-bit lanes of a sector."""
    h = _H16
    return ((x | h) - (y & ~h & _MASK_SECTOR)) ^ ((x ^ ~y) & h)


_H16 = _repeat(b"\x00\x80", SECTOR // 2)


def _gf_inverse(value: int) -> int:
    for candidate in range(1, 256):
        product, a, b = 0, value, candidate
        while b:
            if b & 1:
                product ^= a
            a = ECC_F[a]
            b >>= 1
        if product == 1:
            return candidate
    raise ValueError(value)


_INV3 = _gf_inverse(3)


class _Lanes:
    """Masks for n lanes of `width` bytes."""

    def __init__(self, n: int, width: int):
        self.n, self.width = n, width
        if width == 1:
            self.m7f = _repeat(b"\x7f", n)
            self.m01 = _repeat(b"\x01", n)
        else:
            self.low24 = _repeat(b"\xff\xff\xff\x00", n)
            self.bit0 = _repeat(b"\x01\x00\x00\x00", n)

    def mul2(self, x: int) -> int:
        return ((x & self.m7f) << 1) ^ (((x >> 7) & self.m01) * 0x1D)

    def mul(self, x: int, constant: int) -> int:
        out = 0
        while constant:
            if constant & 1:
                out ^= x
            x = self.mul2(x)
            constant >>= 1
        return out


def _column_matrix(chunk: bytes, n: int, offsets: list[int]) -> bytes:
    """Bytes at `offsets` of each of the n sectors, sector after sector."""
    width = len(offsets)
    out = bytearray(n * width)
    for j, offset in enumerate(offsets):
        out[j::width] = chunk[offset::SECTOR][:n]
    return bytes(out)


_P_ROWS = [[12 + 86 * m + j for j in range(86)] for m in range(24)]
_Q_ROWS = [[12 + ((j >> 1) * 86 + (j & 1) + 88 * m) % 2236 for j in range(52)] for m in range(43)]
_P_OUT = [2076 + j for j in range(172)]
_Q_OUT = [2248 + j for j in range(104)]


def _header_zeroed(chunk: bytes) -> bytes:
    """Mode 2's ECC is computed with the 4 header bytes taken as zero."""
    zeroed = bytearray(chunk)
    for k in range(12, 16):
        zeroed[k::SECTOR] = bytes(len(range(k, len(chunk), SECTOR)))
    return bytes(zeroed)


def _parity(zeroed: bytes, n: int, rows: list[list[int]], count: int) -> list[bytes]:
    """P (rows=_P_ROWS, count=86) or Q (_Q_ROWS, 52) parity of each sector."""
    lanes = _Lanes(n * count, 1)
    a = b = 0
    for offsets in rows:
        t = int.from_bytes(_column_matrix(zeroed, n, offsets), "little")
        a = lanes.mul2(a ^ t)
        b ^= t
    a = lanes.mul(lanes.mul2(a) ^ b, _INV3)
    first = a.to_bytes(n * count, "little")
    second = (a ^ b).to_bytes(n * count, "little")
    return [first[s * count:(s + 1) * count] + second[s * count:(s + 1) * count]
            for s in range(n)]


def _ecc_ok(chunk: bytes, n: int) -> list[bool]:
    """Whether the P and Q parity of each Mode 2 Form 1 sector is right."""
    zeroed = _header_zeroed(chunk)
    p = _parity(zeroed, n, _P_ROWS, 86)
    q = _parity(zeroed, n, _Q_ROWS, 52)
    return [chunk[s * SECTOR + 2076:s * SECTOR + 2248] == p[s]
            and chunk[s * SECTOR + 2248:(s + 1) * SECTOR] == q[s] for s in range(n)]


def fill_edc_ecc(sectors: bytearray, form2: list[bool]) -> None:
    """Writes the EDC, and the ECC of Form 1 sectors, of whole Mode 2 sectors
    whose sync, header and subheaders are set (makes test discs)."""
    n = len(sectors) // SECTOR
    edc1, edc2 = _edc_values(bytes(sectors), n)
    for s in range(n):
        at = s * SECTOR + (2348 if form2[s] else 2072)
        sectors[at:at + 4] = struct.pack("<I", edc2[s] if form2[s] else edc1[s])
    p = _parity(_header_zeroed(bytes(sectors)), n, _P_ROWS, 86)
    for s in range(n):
        if not form2[s]:
            sectors[s * SECTOR + 2076:s * SECTOR + 2248] = p[s]
    q = _parity(_header_zeroed(bytes(sectors)), n, _Q_ROWS, 52)
    for s in range(n):
        if not form2[s]:
            sectors[s * SECTOR + 2248:(s + 1) * SECTOR] = q[s]


_EDC_BITS = [EDC_TABLE[1 << k] for k in range(8)]


def _edc_values(chunk: bytes, n: int) -> tuple[list[int], list[int]]:
    """The EDC of each sector over Form 1's range (16..2072) and Form 2's
    (16..2348): one pass, Form 1's being where Form 2's passes byte 2072."""
    lanes = _Lanes(n, 4)
    crc = 0
    form1 = None
    lane_bytes = bytearray(4 * n)
    for position in range(16, 2348):
        if position == 2072:
            form1 = crc
        lane_bytes[0::4] = chunk[position::SECTOR][:n]
        v = crc ^ int.from_bytes(lane_bytes, "little")
        crc = (v >> 8) & lanes.low24
        for k in range(8):
            crc ^= ((v >> k) & lanes.bit0) * _EDC_BITS[k]

    def values(x: int) -> list[int]:
        raw = x.to_bytes(4 * n, "little")
        return [int.from_bytes(raw[4 * s:4 * s + 4], "little") for s in range(n)]

    return values(form1), values(crc)


def _xa_layout(data: bytes) -> bool:
    """XA-ADPCM sound groups: each header's halves duplicated, zero padding."""
    if data[2304:2324] != bytes(20):
        return False
    for g in range(XA_GROUPS):
        base = g * 128
        if (data[base:base + 4] != data[base + 4:base + 8]
                or data[base + 8:base + 12] != data[base + 12:base + 16]):
            return False
    return True


def classify(chunk: bytes, first_sector: int, base: int | None) -> list[tuple[int, bytes]]:
    """(type, body) of each sector of a chunk of whole sectors."""
    n = len(chunk) // SECTOR
    candidates = []
    any_data = False
    for s in range(n):
        sector = chunk[s * SECTOR:(s + 1) * SECTOR]
        data_like = (base is not None and sector[0:12] == SYNC
                     and sector[12:16] == address_header(base + first_sector + s)
                     and sector[16:20] == sector[20:24])
        candidates.append(data_like)
        any_data |= data_like
    form1_edc = form2_edc = ecc_ok = []
    if any_data:
        form1_edc, form2_edc = _edc_values(chunk, n)
        ecc_ok = _ecc_ok(chunk, n)
    out = []
    for s in range(n):
        sector = chunk[s * SECTOR:(s + 1) * SECTOR]
        if sector == ZERO_SECTOR:
            out.append((ZERO, b""))
            continue
        if candidates[s]:
            sub = sector[16:20]
            stored_edc = int.from_bytes(sector[2348:2352], "little")
            if not sub[2] & 0x20:
                if (form1_edc[s] == int.from_bytes(sector[2072:2076], "little")
                        and ecc_ok[s]):
                    out.append((FORM1, sub + sector[24:2072]))
                    continue
            elif stored_edc in (form2_edc[s], 0):
                with_edc = stored_edc == form2_edc[s]
                data = sector[24:2348]
                if _xa_layout(data):
                    out.append((XA if with_edc else XA_NOEDC, sub + xa_body(data)))
                else:
                    out.append((FORM2 if with_edc else FORM2_NOEDC, sub + data))
                continue
        out.append((RAW, sector))
    return out


def find_base(path: Path, sectors: int) -> int | None:
    """The address of sector 0, from the first sectors with a data header."""
    with path.open("rb") as f:
        for s in range(min(sectors, 64)):
            sector = f.read(SECTOR)
            if sector[0:12] == SYNC and sector[15] == 2:
                frame = header_frame(sector[12:15])
                if frame is not None and frame >= s:
                    return frame - s
    return None


def _payload(kinds: list[tuple[int, bytes]]) -> bytes:
    return bytes(k for k, _ in kinds) + b"".join(body for _, body in kinds)


def _deflate(payload: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
    packed = c.compress(payload) + c.flush()
    return b"\x01" + packed if len(packed) < len(payload) else b"\x00" + payload


def pack_block(kinds: list[tuple[int, bytes]]) -> bytes:
    best = _deflate(_payload(kinds))
    if any(k == RAW and len(body) == SECTOR for k, body in kinds):
        # CD audio packs better as sample differences: keep whichever is smaller.
        audio = [(AUDIO, audio_body(body)) if k == RAW and len(body) == SECTOR else (k, body)
                 for k, body in kinds]
        other = _deflate(_payload(audio))
        if len(other) < len(best):
            best = other
    return best


def pack(source: Path, target: Path, sectors_per_block: int = SECTORS_PER_BLOCK,
         stats: dict | None = None) -> int:
    """Packs a track file; returns the packed size. stats (optional) gets the
    number of sectors and bytes per type."""
    size = source.stat().st_size
    sectors = -(-size // SECTOR)
    blocks = -(-sectors // sectors_per_block)
    base = find_base(source, sectors)
    partial = target.with_name(target.name + ".partial")
    index = []
    with source.open("rb") as src, partial.open("wb") as out:
        out.write(bytes(HEADER.size + 8 * (blocks + 1)))
        position = HEADER.size + 8 * (blocks + 1)
        pending: list[tuple[int, bytes]] = []
        done = 0
        while done < sectors:
            count = min(BATCH, sectors - done)
            chunk = src.read(count * SECTOR)
            whole = len(chunk) // SECTOR
            kinds = classify(chunk[:whole * SECTOR], done, base) if whole else []
            if len(chunk) % SECTOR:
                kinds.append((RAW, chunk[whole * SECTOR:]))
            if stats is not None:
                for kind, body in kinds:
                    entry = stats.setdefault(TYPE_NAMES[kind], [0, 0])
                    entry[0] += 1
                    entry[1] += len(body)
            pending += kinds
            done += count
            while len(pending) >= sectors_per_block or (done >= sectors and pending):
                block, pending = pending[:sectors_per_block], pending[sectors_per_block:]
                data = pack_block(block)
                index.append(position)
                out.write(data)
                position += len(data)
        index.append(position)
        out.seek(0)
        out.write(HEADER.pack(MAGIC, size, SECTOR, sectors_per_block, blocks, base or 0,
                              HEADER.size))
        out.write(struct.pack(f"<{blocks + 1}Q", *index))
    partial.replace(target)
    return position


class Reader:
    """Random access to a packed file (as the runtime's disc_pack.c)."""

    def __init__(self, path: Path):
        self.file = path.open("rb")
        header = self.file.read(HEADER.size)
        (magic, self.size, sector, self.per_block, self.blocks, self.base,
         index_offset) = HEADER.unpack(header.ljust(HEADER.size, b"\0"))
        if magic != MAGIC or sector != SECTOR:
            self.file.close()
            raise ValueError(f"{path} is not a packed track")
        self.file.seek(index_offset)
        self.index = struct.unpack(f"<{self.blocks + 1}Q", self.file.read(8 * (self.blocks + 1)))
        self.cached = (-1, b"")

    def close(self) -> None:
        self.file.close()

    def block(self, i: int) -> bytes:
        if self.cached[0] == i:
            return self.cached[1]
        self.file.seek(self.index[i])
        data = self.file.read(self.index[i + 1] - self.index[i])
        payload = zlib.decompress(data[1:], -15) if data[0] == 1 else data[1:]
        first = i * self.per_block
        count = min(self.per_block, -(-self.size // SECTOR) - first)
        kinds, offset, out = payload[:count], count, bytearray()
        for s in range(count):
            raw_length = min(SECTOR, self.size - (first + s) * SECTOR)
            length = body_size(kinds[s], raw_length)
            out += rebuild(kinds[s], payload[offset:offset + length], self.base + first + s)
            offset += length
        if offset != len(payload):
            raise ValueError(f"block {i}: {len(payload) - offset} bytes left over")
        self.cached = (i, bytes(out))
        return self.cached[1]

    def read(self, position: int, length: int) -> bytes:
        out = bytearray()
        span = self.per_block * SECTOR
        while length > 0 and position < self.size:
            i = position // span
            data = self.block(i)
            start = position - i * span
            part = data[start:start + length]
            out += part
            position += len(part)
            length -= len(part)
        return bytes(out)


def disc_pack_size(header: bytes) -> int | None:
    """The original size when `header` starts a packed track, else None."""
    if len(header) < 16 or header[:len(MAGIC)] != MAGIC:
        return None
    return int.from_bytes(header[8:16], "little")


def unpack(source: Path, target: Path) -> None:
    reader = Reader(source)
    try:
        with target.open("wb") as out:
            for i in range(reader.blocks):
                out.write(reader.block(i))
    finally:
        reader.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pack")
    p.add_argument("source", type=Path)
    p.add_argument("target", type=Path)
    p.add_argument("--sectors-per-block", type=int, default=SECTORS_PER_BLOCK)
    u = sub.add_parser("unpack")
    u.add_argument("source", type=Path)
    u.add_argument("target", type=Path)
    s = sub.add_parser("stats")
    s.add_argument("tracks", type=Path, nargs="+")
    s.add_argument("--sectors-per-block", type=int, default=SECTORS_PER_BLOCK)
    args = parser.parse_args()

    if args.command == "pack":
        start = time.monotonic()
        stats: dict = {}
        packed = pack(args.source, args.target, args.sectors_per_block, stats)
        size = args.source.stat().st_size
        print(f"{args.source.name}: {size} -> {packed} bytes ({100 * packed / size:.1f}%) "
              f"in {time.monotonic() - start:.1f} s")
        for name, (count, body) in sorted(stats.items()):
            print(f"  {name:12} {count:8} sectors  {body / 1e6:9.1f} MB before deflate")
    elif args.command == "unpack":
        unpack(args.source, args.target)
    else:
        import tempfile
        total_in = total_out = 0
        for track in args.tracks:
            with tempfile.TemporaryDirectory() as work:
                stats = {}
                start = time.monotonic()
                packed = pack(track, Path(work) / "packed", args.sectors_per_block, stats)
            size = track.stat().st_size
            total_in, total_out = total_in + size, total_out + packed
            print(f"{track.name}: {size / 1e6:.1f} MB -> {packed / 1e6:.1f} MB "
                  f"({100 * packed / size:.1f}%), {time.monotonic() - start:.0f} s")
            for name, (count, body) in sorted(stats.items()):
                print(f"  {name:12} {count:8} sectors  {body / 1e6:9.1f} MB before deflate")
        print(f"total: {total_in / 1e6:.1f} MB -> {total_out / 1e6:.1f} MB "
              f"({100 * total_out / max(total_in, 1):.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
