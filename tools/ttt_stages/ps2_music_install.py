#!/usr/bin/env python3
"""TTT Stages: the PS2 music of TTT's stages, copied from your Tekken Tag
Tournament (USA) PS2 disc (SLUS-20001).

    python tools/ttt_stages/ps2_music_install.py --ttt-disc DISC [--out DIR]
    python tools/ttt_stages/ps2_music_install.py --ttt-disc DISC --check

About a second. The PS2 game streams each stage piece from TEKKEN.BIN as
headerless PS-ADPCM, stereo interleaved by 1 024-byte blocks (left, right)
in each 2 048-byte sector, 44 100 Hz; its sound driver (RSPU2DRV.IRX) loops a
piece by reading the disc again from the piece's loop sector (TIPS). The 14
stage pieces lie in one run of sectors (LBA 112 875..142 915), checked here by
sha256: this tool copies their sectors as they are, nothing decoded, into
ps2-music.ttp (format music_version.PS2_FORMAT) with version.txt, in a
temporary folder that then replaces DIR (default
workspace/ttt-stages/ps2-music-pack). CMakeLists.txt stages that folder beside
the game as mods/ttt-ps2-music (PC and Android); src/tekken3_ttt_music.c plays
it when GAME OPTION's BGM SELECT is REMIXED. --check only says whether DISC is
the right disc. Nothing from the disc goes into git.

ps2-music.ttp: 'TTP2', u32 format, u32 pieces, then for each piece: u32 PS2
BGM number, u32 offset of its first sector in the file, u32 sectors, u32 loop
sector (from the piece's first, the driver's max(point, 0)), u32 volume (the
driver's, 0x3FFF = full); then the sectors' 2 048 bytes each.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt_stages')]
import music_version as version  # noqa: E402

DEFAULT_OUT = ROOT / 'workspace/ttt-stages/ps2-music-pack'

# The stage pieces' run of sectors and its sha256 (the 2 048 data bytes of each).
FIRST, LAST = 112875, 142915
SHA256 = '0955079110096122e92e6c1448a1fe037e8c8c43c55104245f174f932fcaf317'

# SLUS_200.01's BGM table (0x50CC00, files 0x509D40): number, first LBA,
# sectors, loop point (sectors, < 0: the start), volume. Stage -> number is
# 0x4FB8C0, kept in src/tekken3_ttt_music.c.
PIECES = [
    (0x09, 112875, 1569, 93, 9830),       # PAUL
    (0x0A, 116665, 1412, 21, 9011),       # LAW
    (0x0B, 118077, 2365, 184, 10649),     # YOSHIMITSU
    (0x0C, 120442, 2078, -129, 9830),     # XIAOYU
    (0x0D, 122520, 2368, 7, 10649),       # HWOARANG
    (0x0E, 114444, 2221, -1930, 11468),   # LEI
    (0x0F, 124888, 2428, 226, 12288),     # OGRE
    (0x10, 127316, 2193, -3924, 10649),   # SCHOOL
    (0x11, 129509, 2180, -281, 10649),    # JIN
    (0x12, 131689, 2054, -9809, 10649),   # NINA
    (0x13, 133743, 2701, -92, 10649),     # EDDY
    (0x14, 136444, 2126, 237, 9011),      # KING
    (0x15, 138570, 2365, 3, 10649),       # HEIHACHI
    (0x16, 140935, 1980, 72, 11468),      # UNKNOWN
]


def disc_sectors(disc: Path):
    """(bin file, sector size, data offset) of a .cue, .bin (2 352-byte
    sectors) or .iso (2 048)."""
    disc = Path(disc)
    if disc.suffix.lower() == '.cue':
        line = next(l for l in disc.read_text(errors='replace').splitlines() if l.strip().upper().startswith('FILE'))
        disc = disc.parent / line.split('"')[1]
    with disc.open('rb') as f:
        sync = f.read(12)
    raw = sync == b'\0' + b'\xff' * 10 + b'\0'
    return disc, (2352 if raw else 2048), (24 if raw else 0)


def stage_sectors(disc: Path) -> bytes | None:
    """The stage pieces' sectors on DISC, None on another disc."""
    try:
        path, size, offset = disc_sectors(disc)
        data = bytearray()
        with path.open('rb') as f:
            for n in range(FIRST, LAST):
                f.seek(n * size + offset)
                data += f.read(2048)
    except (OSError, ValueError, StopIteration, IndexError):
        return None
    return bytes(data) if hashlib.sha256(data).hexdigest() == SHA256 else None


def found(disc: Path) -> bool:
    return stage_sectors(disc) is not None


def build(data: bytes) -> bytes:
    head = bytearray(b'TTP2' + struct.pack('<II', version.PS2_FORMAT, len(PIECES)))
    offset = len(head) + 20 * len(PIECES)
    body = bytearray()
    for number, lba, sectors, loop, volume in PIECES:
        head += struct.pack('<5I', number, offset + len(body), sectors, max(loop, 0), volume)
        body += data[(lba - FIRST) * 2048:(lba - FIRST + sectors) * 2048]
    return bytes(head + body)


def install(disc: Path, out: Path = DEFAULT_OUT, say=print) -> Path:
    start = time.time()
    data = stage_sectors(disc)
    if data is None:
        raise ValueError(f'{disc}: not Tekken Tag Tournament USA (SLUS-20001) for PS2, the stage music was not found')
    pack = build(data)
    temp = out.with_name(out.name + '.new')
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    (temp / version.PS2_FILE).write_bytes(pack)
    (temp / version.STAMP).write_text(f'{version.PS2_VERSION}\n', encoding='utf-8')
    shutil.rmtree(out, ignore_errors=True)
    temp.replace(out)
    say(f'TTT stage PS2 music version {version.PS2_VERSION}: {len(PIECES)} pieces, '
        f'{len(pack)} bytes in {out} ({time.time() - start:.1f} s)')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--ttt-disc', type=Path, required=True, help='Tekken Tag Tournament USA PS2 disc (.cue, .bin or .iso)')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--check', action='store_true', help='only say whether the disc holds the stage music')
    args = ap.parse_args(argv)
    if args.check:
        ok = found(args.ttt_disc)
        print(f'{args.ttt_disc}: ' + ('the stage music is there' if ok else 'not the stage music of SLUS-20001'))
        return 0 if ok else 1
    try:
        install(args.ttt_disc.resolve(), args.out.resolve())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
