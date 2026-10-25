#!/usr/bin/env python3
"""TTT Stages: the music of TTT's arcade stages, made from your tektagt.zip.

    python tools/ttt_stages/music_install.py --ttt1 tektagt.zip [--out DIR]

No MAME, under a second. TTT's sound driver (the H8) played each stage piece
once in MAME (tools/ttt_stages/music.py record, TTT Stages S1); what it wrote
to the C352 sound chip, numbers only, is tools/data/ttt_stage_music.json.gz.
The game replays those writes on its own C352 (src/tekken3_ttt_music.c) over
the chip's samples, which come from the player's tektagt.zip: this tool
copies the 64 KiB banks of the c352 ROM the pieces use next to the writes in
one file, music.ttm (format music_version.FORMAT, zlib), plus version.txt,
into a temporary folder that then replaces DIR (default
workspace/ttt-stages/music-pack). CMakeLists.txt stages that folder beside
the game as mods/ttt-music, on PC and Android. Nothing from the ROM goes into
git.

music.ttm: 'TTTM', u32 format, u32 size of what follows once inflated, then
zlib of: u32 chip_start, u32 out_start (the request in MAME's 88 200 and
44 100 Hz samples: the game's output resampler keeps MAME's phase), u32
pieces, u32 banks, the banks' numbers (u8 each, padded to 4), then for each
piece: u32 number, u32 loop, u32 seam, u32 fade, u32 init count, u32 write
count, init (u16 register, u16 value), writes (u32 samples since the
previous write, the first since the request; u16 register, u16 value, u16
mask); then the banks' bytes.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt_stages')]
import music_version as version  # noqa: E402

TABLE = ROOT / 'tools/data/ttt_stage_music.json.gz'
DEFAULT_OUT = ROOT / 'workspace/ttt-stages/music-pack'


def c352_rom(ttt1: Path) -> bytes:
    import arcade_model_probe as probe
    sets = json.loads(probe.MANIFEST.read_text(encoding='utf-8'))['sets']
    wanted = [r for r in sets[probe.ttt_set(ttt1)]['regions'] if r['name'] == 'c352']
    return probe.reconstruct(ttt1, {'regions': wanted})[0]['c352']


def build(table: dict, rom: bytes) -> bytes:
    banks, pieces = table['banks'], table['pieces']
    body = bytearray(struct.pack('<4I', table['chip_start'], table['out_start'], len(pieces), len(banks)))
    body += bytes(banks) + bytes(-len(banks) % 4)
    for key, p in pieces.items():
        init, writes = p['init'], p['writes']
        body += struct.pack('<6I', int(key, 16), p['loop'], p['seam'], p['fade'], len(init), len(writes))
        for reg, value in init:
            body += struct.pack('<HH', reg, value)
        for w in writes:
            body += struct.pack('<IHHH', w[0], w[1], w[2], w[3] if len(w) > 3 else 0xffff)
    for b in banks:
        body += rom[b << 16:(b + 1) << 16]
    return b'TTTM' + struct.pack('<II', version.FORMAT, len(body)) + zlib.compress(bytes(body), 9)


def install(ttt1: Path, out: Path = DEFAULT_OUT, say=print) -> Path:
    start = time.time()
    with gzip.open(TABLE, 'rt', encoding='utf-8') as f:
        table = json.load(f)
    data = build(table, c352_rom(ttt1))
    temp = out.with_name(out.name + '.new')
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    (temp / version.FILE).write_bytes(data)
    (temp / version.STAMP).write_text(f'{version.MUSIC_VERSION}\n', encoding='utf-8')
    shutil.rmtree(out, ignore_errors=True)
    temp.replace(out)
    say(f'TTT stage music version {version.MUSIC_VERSION}: {len(table["pieces"])} pieces, '
        f'{len(data)} bytes in {out} ({time.time() - start:.1f} s)')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--ttt1', type=Path, required=True, help='tektagt.zip (Tekken Tag Tournament arcade)')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    install(args.ttt1.resolve(), args.out.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
