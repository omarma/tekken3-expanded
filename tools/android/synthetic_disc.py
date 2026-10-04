#!/usr/bin/env python3
"""A synthetic disc shaped like Tekken 3's, to test and measure disc_pack.py.

No real disc is available to the tests: this one has the same three tracks and
the same kinds of sectors, in the real disc's proportions (docs/android-size.md,
section 2.1), scaled down by --scale:

  track 1 (Mode 2/2352): system area (Form 1, an ISO9660 volume descriptor and
    SYSTEM.CNF, then MIPS-like code); TEKKEN3.XAS: STR video sectors (Form 1,
    an STR header then high-entropy MDEC-like data, each frame zero-padded to
    its last sector) interleaved 7 to 1 with their XA audio, then 8-channel XA
    music (Form 2, XA-ADPCM sound groups: duplicated parameter bytes, nibbles
    of a Laplacian residual), with empty sectors; TEKKEN3.BNS-like game data
    (Form 1: 4/8-bit textures with CLUTs, SPU-ADPCM sounds, int16 model and
    animation tables, zero padding); the postgap (Form 2, zeros);
  track 2: CD audio, 16-bit stereo music-like signal (tones, harmonics,
    envelopes, noise), after 2 s of pregap silence;
  track 3: digital silence.

Every Mode 2 sector has a valid EDC (and ECC for Form 1), as on a Redump dump.
The payloads are synthetic, so their deflate ratio is an estimate (the MDEC
and ADPCM data are near-random, like the real ones); the sector-level savings
(headers, EDC/ECC, XA, silence) are those of the real disc.

Usage: synthetic_disc.py <folder> [--scale 0.05] [--seed 1]
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disc_pack  # noqa: E402

SECTOR = disc_pack.SECTOR
# The real disc's sector counts (docs/android-size.md, 2.1).
SYSTEM, VIDEO, XA_AUDIO, EMPTY, BNS, POSTGAP = 604, 111099, 133858, 4595, 18628, 150
TRACK2, TRACK3 = 11778, 11923
CUE_NAME = "Synthetic.cue"


def track_names() -> list[str]:
    return [f"Synthetic (Track {n}).bin" for n in (1, 2, 3)]


class Track1:
    """Mode 2 sectors: user data and subheaders now, sync/header/EDC/ECC at the end."""

    def __init__(self):
        self.sectors = bytearray()
        self.form2: list[bool] = []

    def add(self, submode: int, data: bytes, channel: int = 0, coding: int = 0) -> None:
        form2 = bool(submode & 0x20)
        sector = bytearray(SECTOR)
        sector[0:12] = disc_pack.SYNC
        sector[12:16] = disc_pack.address_header(150 + len(self.form2))
        sector[16:20] = sector[20:24] = bytes((0, channel, submode, coding))
        size = 2324 if form2 else 2048
        sector[24:24 + size] = data[:size].ljust(size, b"\0")
        self.sectors += sector
        self.form2.append(form2)

    def finish(self) -> bytes:
        step = disc_pack.BATCH * SECTOR
        for start in range(0, len(self.sectors), step):
            chunk = self.sectors[start:start + step]
            disc_pack.fill_edc_ecc(chunk, self.form2[start // SECTOR:(start + len(chunk)) // SECTOR])
            self.sectors[start:start + len(chunk)] = chunk
        return bytes(self.sectors)


def laplace_bytes(rng: random.Random, count: int, scale: float) -> bytes:
    """Bytes of two 4-bit signed residuals each, Laplacian around 0."""
    weights = [math.exp(-abs(v) / scale) for v in range(-8, 8)]
    nibbles = rng.choices(range(16), weights=weights, k=2 * count)
    return bytes(nibbles[2 * i] | nibbles[2 * i + 1] << 4 for i in range(count))


def xa_sector_data(rng: random.Random, state: list[int]) -> bytes:
    """18 sound groups of 4-bit XA-ADPCM: 8 units' filter/shift (each twice),
    then 112 bytes of nibbles. state: the slowly moving shift of the stream."""
    out = bytearray()
    for _ in range(18):
        params = bytearray()
        for _unit in range(8):
            state[0] = min(12, max(0, state[0] + rng.choice((-1, 0, 0, 0, 1))))
            params.append(rng.choices((0, 1, 2, 3), (2, 4, 3, 1))[0] << 4 | state[0])
        out += params[0:4] * 2 + params[4:8] * 2 + laplace_bytes(rng, 112, 1.8)
    return bytes(out) + bytes(20)


def str_frames(rng: random.Random, sectors: int):
    """Video sector payloads of STR frames: 32-byte header, then the frame's
    MDEC bitstream (high entropy), zero-padded in its last sector."""
    frame = 0
    produced = 0
    while produced < sectors:
        frame += 1
        size = rng.randint(14000, 19000)
        count = -(-size // 2016)
        bitstream = rng.randbytes(size)
        for k in range(count):
            header = struct.pack("<HHHHIIHH", 0x0160, 0x8001, k, count, frame,
                                 size, 320, 240) + struct.pack("<HH", 0x3800, 2) + bytes(8)
            yield header + bitstream[k * 2016:(k + 1) * 2016]
            produced += 1
            if produced == sectors:
                return


def game_data(rng: random.Random, size: int) -> bytes:
    """BNS-like content: textures, SPU-ADPCM sounds, models, animations."""
    out = bytearray()
    while len(out) < size:
        kind = rng.choices(("tim", "vag", "tmd", "anim"), (35, 30, 20, 15))[0]
        if kind == "tim":
            w, h = rng.choice(((64, 64), (128, 128), (256, 128), (128, 256)))
            bits = rng.choice((4, 8))
            colors = 1 << bits
            clut = struct.pack(f"<{colors}H", *(rng.getrandbits(15) for _ in range(colors)))
            pixels = bytearray()
            level = rng.randrange(colors)
            for _ in range(w * h * bits // 8):
                level = (level + rng.choice((-1, 0, 0, 0, 1))) % colors
                pixels.append(level if bits == 8 else (level & 15) | ((level + 1) & 15) << 4)
            out += struct.pack("<II", 0x10, 8 if bits == 4 else 9) + clut + pixels
        elif kind == "vag":
            for _ in range(rng.randint(200, 1200)):
                out += bytes((rng.randrange(13) | rng.randrange(4) << 4, 0))
                out += laplace_bytes(rng, 14, 2.0)
        elif kind == "tmd":
            vertices = rng.randint(100, 600)
            x = y = z = 0
            for _ in range(vertices):
                x += rng.randint(-40, 40)
                y += rng.randint(-40, 40)
                z += rng.randint(-40, 40)
                out += struct.pack("<hhhh", x, y, z, 0)
            for _ in range(vertices):
                out += struct.pack("<BBBBHHHH", 0x0C, 0x04, 0x34, 0x00, rng.randrange(vertices),
                                   rng.randrange(vertices), rng.randrange(vertices),
                                   rng.randrange(256))
        else:
            channels, frames = rng.randint(20, 60), rng.randint(20, 80)
            values = [rng.randint(-2048, 2047) for _ in range(channels)]
            for _ in range(frames):
                values = [v + rng.randint(-12, 12) for v in values]
                out += struct.pack(f"<{channels}h", *values)
        out += bytes(-len(out) % 2048)
    return bytes(out[:size])


def pcm_music(rng: random.Random, frames: int) -> bytes:
    """16-bit stereo music-like signal at 44.1 kHz."""
    out = bytearray()
    notes: list[list[float]] = []
    for i in range(frames):
        if i % 11025 == 0:
            notes = [[110 * 2 ** (rng.randrange(36) / 12), rng.random() * 3000 + 1000, 0.0]
                     for _ in range(3)]
        left = right = 0.0
        for note in notes:
            freq, amplitude, phase = note
            env = math.exp(-(i % 11025) / 8000)
            sample = amplitude * env * (math.sin(phase) + 0.4 * math.sin(2 * phase)
                                        + 0.2 * math.sin(3 * phase))
            note[2] = phase + 2 * math.pi * freq / 44100
            left += sample
            right += sample * 0.8
        if i % 22050 < 2000:   # a drum hit
            noise = rng.gauss(0, 2500) * math.exp(-(i % 22050) / 400)
            left += noise
            right += noise
        left += rng.gauss(0, 150)
        right += rng.gauss(0, 150)
        out += struct.pack("<hh", max(-32768, min(32767, int(left))),
                           max(-32768, min(32767, int(right))))
    return bytes(out)


def make(folder: Path, scale: float = 0.05, seed: int = 1) -> list[Path]:
    """Writes the cue and the three tracks into folder; returns the tracks."""
    rng = random.Random(seed)

    def n(count: int) -> int:
        return max(1, round(count * scale))

    folder.mkdir(parents=True, exist_ok=True)
    t1 = Track1()
    # System area: 16 license sectors, the volume descriptor, SYSTEM.CNF, code.
    for i in range(16):
        t1.add(0x08, (b"Licensed by Sony Computer Entertainment Amer ica " * 50) if i == 4 else b"")
    pvd = bytearray(2048)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[40:72] = b"TEKKEN3".ljust(32, b" ")
    root = bytearray(34)
    root[0] = 34
    root[2:10] = struct.pack("<I", 22) + struct.pack(">I", 22)
    root[10:18] = struct.pack("<I", 2048) + struct.pack(">I", 2048)
    pvd[156:190] = root
    t1.add(0x09, bytes(pvd))
    for _ in range(17, 24):
        t1.add(0x08, b"")
    t1.add(0x89, b"BOOT = cdrom:\\SLUS_004.02;1\r\nTCB = 4\r\nEVENT = 10\r\n")
    opcodes = [0x27BD, 0x8FBF, 0xAFBF, 0x0C01, 0x3C02, 0x2442, 0x1040, 0x0000, 0x8C42, 0x03E0]
    for _ in range(n(SYSTEM) - 25):
        code = b"".join(struct.pack("<HH", rng.getrandbits(16) & rng.choice((0xFFFF, 0x00FF, 0x0F)),
                                    rng.choice(opcodes)) for _ in range(512))
        t1.add(0x08, code)
    # TEKKEN3.XAS: movies (7 video : 1 audio), then XA music, with empty sectors.
    video = n(VIDEO)
    movie_audio = video // 7
    music = n(XA_AUDIO) - movie_audio
    empty = n(EMPTY)
    frames = str_frames(rng, video)
    xa_state = [[8] for _ in range(8)]
    v = 0
    while v < video:
        for _ in range(7):
            if v < video:
                t1.add(0x48, next(frames))
                v += 1
        t1.add(0x64, xa_sector_data(rng, xa_state[0]), channel=1, coding=0x01)
    empty_every = max(1, (music + empty) // max(empty, 1))
    for i in range(music + empty):
        if i % empty_every == empty_every - 1 and empty > 0:
            t1.add(0x00, b"")
            empty -= 1
        else:
            channel = i % 8
            t1.add(0x64 | (0x80 if i % 400 == 399 else 0), xa_sector_data(rng, xa_state[channel]),
                   channel=channel, coding=0x01)
    # TEKKEN3.BNS-like game data, then the postgap.
    bns = game_data(rng, n(BNS) * 2048)
    for k in range(0, len(bns), 2048):
        t1.add(0x08 | (0x01 if k + 2048 >= len(bns) else 0), bns[k:k + 2048])
    for _ in range(n(POSTGAP)):
        t1.add(0x20, b"")

    tracks = [folder / name for name in track_names()]
    tracks[0].write_bytes(t1.finish())
    pregap = bytes(n(150) * SECTOR)
    music_frames = (n(TRACK2) - n(150)) * SECTOR // 4
    tracks[1].write_bytes(pregap + pcm_music(rng, music_frames))
    tracks[2].write_bytes(bytes(n(TRACK3) * SECTOR))
    (folder / CUE_NAME).write_bytes(
        f'FILE "{tracks[0].name}" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n'
        f'FILE "{tracks[1].name}" BINARY\r\n  TRACK 02 AUDIO\r\n    INDEX 00 00:00:00\r\n'
        f'    INDEX 01 00:02:00\r\n'
        f'FILE "{tracks[2].name}" BINARY\r\n  TRACK 03 AUDIO\r\n    INDEX 00 00:00:00\r\n'
        f'    INDEX 01 00:02:00\r\n'.encode())
    return tracks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--scale", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    for track in make(args.folder, args.scale, args.seed):
        print(f"{track}: {track.stat().st_size // SECTOR} sectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
