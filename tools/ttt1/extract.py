#!/usr/bin/env python3
"""Extract TTT1's archive files and animations straight from tektagt.zip, without MAME.

    python3 tools/ttt1/extract.py --ttt1 tektagt.zip --output workspace/ttt1-rom

The ZIP is verified chip by chip (tools/data/namcos12_model_sources.json) and its
regions rebuilt by tools/arcade_model_probe.py. Written under --output (a fresh
folder, never committed):

- game.bin: the game program, LZ-packed in the program ROM. Header read by the
  boot at ROM+0x2400C: mode (2 = LZ), source 1FC28000, destination, size,
  entry; TTT loads it at 80010000. LZ: a flag byte read bit 0 first, its
  highest set bit a sentinel, flag byte 0 = end; bit 1 = literal, bit 0 = two
  bytes v = b0<<8|b1, distance v & 0x7FF (0 -> 0x800), length v>>11 (0 -> 0x20).
- archive/AA/NNN.bin (.tim for a single TIM): the 37 archives, from the table
  of (header list, count) pairs at 80195E38. Each header is u32 n then
  n x (offset from the header, size); the game numbers the files of an
  archive's headers one after another (8012EC6C). Archive 29 is not one:
  its "header" is a TIM that 80102AF0 reads directly. Archives 2-20 are
  LZ-packed file by file (the same LZ, 80105FF8 right after each load): their
  files are written unpacked.
- anim/ADDRESS.bin: the animations, from the 7,326 (encrypted address, size)
  pairs at banked ROM 03000000. 9xxxxxxx: + 0x2651 (protection answer)
  + 0x700E678B; Axxxxxxx: + 0x63000000 (modulo 2^32).
- characters.csv: per character (index = the body key at 0x29EF12 of the select
  screen) and button variant, its name, model slot, texture and model files,
  moveset, sound profile, number of animations its moveset reaches,
  loading-screen portrait and strong-hit effect sheet.
  Record pointers at 801958C4 (8 per character: name, then byte 7 an
  appearance id, 8 sound, 9 moveset); slots at 8001110C (8 bytes per
  character: Punch, Kick, two older costumes, Start, -, -, extra; 255 = none);
  slot s loads 23/s and 24/s unless the 23 slots at 8019E3B4 hold it at k:
  then 26/k and 27/k (80164ACC, 80164BAC). Moves: 5,515 u16 per moveset at
  80093780 + moveset x 0x2B16, move = 52 bytes at 80036768 whose first word
  indexes the animation table. Portrait: archive 32, file portraits[i] with
  i = the index, or 0x22-0x26 for Tiger, Panda, Angel, Alex, Tetsujin
  (80175428); the table is stored by the code itself, one "addiu v1, n /
  sb v1, i(v0)" pair per index from 80175494. Unknown (0x21): archive 36.
  Effect sheet: record byte 10 = row of 0x18 bytes at 8001AD30 whose first
  word n is the file of archives 3 + 4 read as one (8012EF2C, 80120164).
- stages.csv: stage number (802434E4), name (tools/data/ttt1_stages.json),
  archive (u32 table at 80022D98, 80150D90; file 0 = geometry, the others
  textures) and its file count. Stage 14 (Unknown) loads none.
- index.csv: archive (or "anim"), n° (for an animation, the first table index
  using it), ROM address, size in ROM, format, file, size of the file. Format:
  TIM, TIM*k (k TIMs one after another), 3DMK, MDEC (one video frame), an ASCII
  tag, or else the first 4 bytes in hex; "lz:" before it when LZ-packed.

TIMs here may sit anywhere in System 12's 1024x1024 VRAM (tim_tool keeps to
the PS1's 1024x512), and a file may end with up to 16 bytes of padding (zeros,
"AAAA", "TIMZ").

Game ROM addresses: < 03800000 = banked ROMs, 04000000-043FFFFF = program ROM.
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import arcade_model_probe  # noqa: E402

BASE, ARCHIVES, NARCH = 0x80010000, 0x80195E38, 37
ANIM_TABLE, NANIM = 0x3000000, 7326
ANIM_KEY = {0x9: 0x2651 + 0x700E678B, 0xA: 0x63000000}
DIRECT_TIM, PACKED = 29, range(2, 21)
RECORDS, SLOTS, OVERRIDES, NCHAR = 0x801958C4, 0x8001110C, 0x8019E3B4, 34
MOVESETS, MOVES = 0x80093780, 0x80036768
PORTRAITS, UNKNOWN_PORTRAIT = 0x80175494, 0x21
PORTRAIT_VARIANTS = {(8, 4): 0x22, (11, 1): 0x23, (11, 3): 0x23, (29, 4): 0x24, (17, 1): 0x25,
                     (15, 0): 0x26, (15, 7): 0x26}
STAGES, NSTAGE = 0x80022D98, 15
EFFECTS, EFFECT_SPLIT = 0x8001AD30, 39


def lz(src: bytes, i: int) -> bytes:
    out = bytearray()
    while True:
        flags = src[i]; i += 1
        if flags == 0:
            return bytes(out)
        while flags >= 2:
            if flags & 1:
                out.append(src[i]); i += 1
            else:
                v = src[i] << 8 | src[i + 1]; i += 2
                dist = v & 0x7FF or 0x800
                for _ in range(v >> 11 & 0x1F or 0x20):
                    out.append(out[-dist])
            flags >>= 1


def unpack_game(main: bytes) -> bytes:
    mode, src, dst, size, entry = struct.unpack_from('<5I', main, 0x2400C)
    assert (mode, dst) == (2, BASE), 'unexpected program header'
    return lz(main, src - 0x1FC00000)


class Rom:
    def __init__(self, bank: bytes, main: bytes):
        self.bank, self.main = bank, main

    def __call__(self, a: int, n: int) -> bytes:
        if a + n <= len(self.bank):
            return self.bank[a:a + n]
        assert 0x4000000 <= a and a + n <= 0x4000000 + len(self.main), hex(a)
        return self.main[a - 0x4000000:a - 0x4000000 + n]


def archives(game: bytes, rom: Rom, direct: bool = True):
    """Yield (archive, n°, ROM address, size). direct=False: archive 29 read as
    the game's directory has it (its TIM taken for a header of 16 files)."""
    u32 = lambda a: struct.unpack_from('<I', game, a - BASE)[0]
    for i in range(NARCH):
        lst, count = u32(ARCHIVES + 8 * i), u32(ARCHIVES + 8 * i + 4)
        heads = [u32(lst + 4 * k) for k in range(count)]
        if i == DIRECT_TIM and direct:
            yield i, 0, heads[0], tims(rom(heads[0], 0x40000))[1]
            continue
        n = 0
        for h in heads:
            m = struct.unpack('<I', rom(h, 4))[0]
            for off, size in zip(*[iter(struct.unpack('<%dI' % (2 * m), rom(h + 4, 8 * m)))] * 2):
                yield i, n, h + off, size
                n += 1


def animations(bank: bytes):
    """{ROM address: (first table index, size)}."""
    table = struct.unpack_from('<%dI' % (2 * NANIM), bank, ANIM_TABLE)
    out = {}
    for k, (a, size) in enumerate(zip(table[0::2], table[1::2])):
        out.setdefault((a + ANIM_KEY[a >> 28]) & 0xFFFFFFFF, (k, size))
    return out


def portraits(game: bytes) -> dict:
    """{index: archive-32 file} from the addiu v1 / sb v1 pairs at PORTRAITS."""
    out, a, value = {}, PORTRAITS, None
    while True:
        w = struct.unpack_from('<I', game, a - BASE)[0]
        if w >> 16 == 0x2403:                    # addiu v1, zero, n
            value = w & 0xFFFF
        elif w >> 16 == 0xA043 and value is not None:   # sb v1, i(v0)
            out[0 if w & 0xFFFF == 0x6330 else w & 0xFFFF] = value
        elif w >> 16 != 0x2442:                  # addiu v0, v0, 0x6330
            return out
        a += 4


def characters(game: bytes, anims: dict):
    """Rows of characters.csv."""
    u32 = lambda a: struct.unpack_from('<I', game, a - BASE)[0]
    name = lambda a: game[a - BASE:game.index(b'\0', a - BASE)].decode('latin1')
    table = struct.unpack_from('<%dI' % (2 * NANIM), anims['table'], 0)
    address = lambda k: (table[2 * k] + ANIM_KEY[table[2 * k] >> 28]) & 0xFFFFFFFF
    overrides = struct.unpack_from('<23h', game, OVERRIDES - BASE)
    portrait = portraits(game)
    assert len(portrait) == 0x27 and 109 in overrides, 'unexpected portrait or slot table'
    rows = []
    for c in range(NCHAR):
        for v, slot in enumerate(game[SLOTS - BASE + 8 * c:SLOTS - BASE + 8 * c + 8]):
            if slot == 255:
                continue
            record = u32(RECORDS + 4 * (8 * c + v))
            sound, moveset = game[record - BASE + 8], game[record - BASE + 9]
            moves = struct.unpack_from('<5515H', game, MOVESETS - BASE + moveset * 0x2B16)
            reached = {address(u32(MOVES + 52 * m)) for m in set(moves)}
            k = overrides.index(slot) if slot in overrides else None
            tex, model = ('26/%03d' % k, '27/%03d' % k) if k is not None else ('23/%03d' % slot, '24/%03d' % slot)
            p = PORTRAIT_VARIANTS.get((c, v), c)
            picture = '%02d/%03d' % (36 if p == UNKNOWN_PORTRAIT else 32, portrait[p])
            n = u32(EFFECTS + 0x18 * game[record - BASE + 10])
            effect = '03/%03d' % n if n < EFFECT_SPLIT else '04/%03d' % (n - EFFECT_SPLIT)
            rows.append((c, v, name(u32(record)), slot, tex, model, moveset, sound, len(reached), picture, effect))
    return rows


def tims(data: bytes) -> tuple[int, int]:
    """(number of TIMs at the start of data, bytes they take)."""
    count = p = 0
    while data[p:p + 4] == b'\x10\0\0\0' and len(data) >= p + 8:
        flags, q = struct.unpack_from('<I', data, p + 4)[0], p + 8
        if flags not in (2, 3, 8, 9):
            break
        for _ in range(2 if flags & 8 else 1):
            size, x, y, w, h = struct.unpack_from('<IHHHH', data, q) if len(data) >= q + 12 else (0,) * 5
            if not w or not h or size != 12 + 2 * w * h or q + size > len(data):
                return count, p
            q += size
        count, p = count + 1, q
    return count, p


def kind(data: bytes) -> str:
    if not data:
        return 'empty'
    count, used = tims(data)
    if count and len(data) - used <= 16:
        return 'TIM' if count == 1 else 'TIM*%d' % count
    if data[2:4] == b'\0\x38':
        return 'MDEC'
    if b'3DMK' in data[:64]:
        return '3DMK'
    if len(data) >= 8 and all(0x20 < c < 0x7F for c in data[:8]):
        return data[:8].decode()
    return data[:4].hex()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ttt1', type=Path, required=True, help='tektagt.zip (MAME, non-merged)')
    ap.add_argument('--output', type=Path, required=True, help='fresh output folder')
    args = ap.parse_args(argv)
    if args.output.exists():
        sys.exit(f'{args.output} already exists; choose a fresh output folder')

    sets = json.loads(arcade_model_probe.MANIFEST.read_text(encoding='utf-8'))['sets']
    wanted = [r for r in sets['tektagt']['regions'] if r['name'] in ('maincpu:rom', 'bankedroms')]
    regions, _ = arcade_model_probe.reconstruct(args.ttt1, {'regions': wanted})
    bank, main_rom = regions['bankedroms'], regions['maincpu:rom']
    rom, game = Rom(bank, main_rom), unpack_game(main_rom)

    args.output.mkdir(parents=True)
    (args.output / 'game.bin').write_bytes(game)
    rows, files = [], []
    for i, n, a, size in archives(game, rom):
        data = rom(a, size)
        if i in PACKED and data:
            data = lz(data, 0)
        fmt = ('lz:' if i in PACKED and data else '') + kind(data)
        name = 'archive/%02d/%03d.%s' % (i, n, 'tim' if fmt == 'TIM' else 'bin')
        rows.append((i, n, '%08X' % a, size, fmt, name, len(data)))
        files.append(data)
    anims = animations(bank)
    assert len(anims) == 4271 and sum(s for _, s in anims.values()) == 14401800, 'unexpected animation table'
    for a, (k, size) in sorted(anims.items()):
        data = rom(a, size)
        rows.append(('anim', k, '%08X' % a, size, kind(data), 'anim/%08X.bin' % a, size))
        files.append(data)

    for row, data in zip(rows, files):
        path = args.output / row[5]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    with open(args.output / 'index.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['archive', 'n', 'rom', 'size', 'format', 'file', 'file_size'])
        w.writerows(rows)
    with open(args.output / 'characters.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['index', 'variant', 'name', 'slot', 'textures', 'model', 'moveset', 'sound', 'animations',
                    'portrait', 'hit_effect'])
        w.writerows(characters(game, {'table': bank[ANIM_TABLE:ANIM_TABLE + 8 * NANIM]}))
    with open(args.output / 'stages.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['stage', 'name', 'archive', 'files'])
        counts = {i: n + 1 for i, n, *_ in rows if isinstance(i, int)}
        names = json.loads((ROOT / 'tools/data/ttt1_stages.json').read_text(encoding='utf-8'))['stages']
        for stage in range(NSTAGE):
            archive = struct.unpack_from('<I', game, STAGES - BASE + 4 * stage)[0] if stage < NSTAGE - 1 else None
            w.writerow((stage, names[stage], archive or '', counts[archive] if archive else 0))
    print(f'{len(rows) - len(anims)} archive files, {len(anims)} animations -> {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
