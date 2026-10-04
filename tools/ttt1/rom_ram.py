#!/usr/bin/env python3
"""TTT1's main RAM at the character select screen, rebuilt from the ROM alone.

What tools/ttt1_import.py reads in a MAME select capture (*-select-ram.bin),
without MAME: the game program at 80010000 (tools/ttt1/extract.py), then what
the game builds at boot and at the select screen:

- the flat file directory at 802FE500 (8012EC6C): each archive's headers one
  after another, 8 bytes per file (ROM address, size); the archive table at
  80195E38 then points at its first file;
- the move table at 80036768 (800FCC8C), 7,326 moves of 52 bytes: word 0 =
  decrypted animation address, byte 0x18 = the animation's first byte (frame
  count), word 3 -> 801B6204 + 14n, word 7 -> 80030D80 + 2n, word 8 ->
  8002AFA8 + 4n (-1 -> 0); then 800FD120: each property 0x18 of the move's
  list (u16 frame, u16 kind << 8 | n) adds n to halfword 1 of its hit rows
  (10 bytes at 800EC8BC + 10 x move halfword 0x14): the first row twice,
  the next ones once, up to the row starting with FFFF;
- the highlighted character's aliases at 802A7350: 5,515 move addresses
  80036768 + 52i, i read at 80093780 + moveset x 0x2B16;
- its keys at 8029EF00 (u16): +0x0E record index (8 x character + variant),
  +0x10 moveset, +0x12 character, +0x14 sound profile, +0x16 model slot.

Everything else the import reads is static in the program: model, motion,
moves and costumes come out byte-identical from these and from the 57 MAME
captures (TIPS.md § 61).

Also from the ROM: the strong-hit effect as player 1's fight VRAM holds it
(effect_vram) and the loading portrait (portrait).
"""
from __future__ import annotations

import functools
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as E  # noqa: E402

SIZE, IMAGE = 0x400000, 0x10000
DIRECTORY, MOVES, NMOVES = 0x2FE500, 0x36768, 7326
HIT_ROWS, BOOSTED = 0xEC8BC, 0x18
ALIASES, MOVESETS, NALIAS = 0x2A7350, 0x93780, 5515
KEYS = 0x29EF00
WITNESS = 7                      # Xiaoyu, under the cursor when the select screen opens
VARIANTS = {'Start': 4, 'Button 4': 1, 'Button 5': 1}   # confirm button -> record variant
UNKNOWN_PORTRAIT = (36, 11)


@functools.lru_cache(maxsize=None)
def load(folder) -> tuple[bytes, bytes, bytes]:
    """(banked ROMs, program ROM, game program) from the regions folder."""
    folder = Path(folder)
    bank, main = (folder / 'bankedroms.bin').read_bytes(), (folder / 'maincpu_rom.bin').read_bytes()
    return bank, main, E.unpack_game(main)


@functools.lru_cache(maxsize=None)
def boot(folder) -> bytes:
    return program(*load(folder))


def character(key: str, entry: dict) -> tuple[int, int]:
    """(character, variant) of a ttt1_characters.json entry, as the selector
    picks it: forced index, else its character and confirm button."""
    if entry.get('force_index') is not None:
        return divmod(entry['force_index'], 8)
    if 'body' not in entry:
        return WITNESS, 0
    return entry['body'], VARIANTS.get(entry.get('confirm'), 0)


def file(folder, archive: int, n: int) -> bytes:
    """One archive file, unpacked when LZ-packed."""
    bank, main, game = load(folder)
    rom = E.Rom(bank, main)
    for i, k, a, size in E.archives(game, rom):
        if (i, k) == (archive, n):
            data = rom(a, size)
            return E.lz(data, 0) if i in E.PACKED and data else data
    raise KeyError((archive, n))


def portrait(folder, c: int, v: int = 0) -> tuple[int, int, bytes, tuple]:
    """Loading portrait: (width in halfwords, height, 8-bit pixels, 256 colours)."""
    game = load(folder)[2]
    p = E.PORTRAIT_VARIANTS.get((c, v), c)
    return tim8(file(folder, *(UNKNOWN_PORTRAIT if p == E.UNKNOWN_PORTRAIT else (32, E.portraits(game)[p]))))


def tim8(data: bytes) -> tuple[int, int, bytes, tuple]:
    pal = struct.unpack_from('<256H', data, 20)
    _, _, _, w, h = struct.unpack_from('<IHHHH', data, 8 + 12 + 512)
    return w, h, data[8 + 12 + 512 + 12:], pal


def effect_vram(folder, c: int, v: int = 0) -> bytes:
    """Player 1's fight VRAM (1024 x 1024 halfwords) holding only the strong-hit
    effect, as 80122FB4 uploads it: record byte 10 -> row of 0x18 bytes at
    8001AD30 (word 0 = file of archives 3 + 4, halfwords 0x0C, 0x0E, 0x10 = red,
    green, blue scale / 128 of the palette); palette at (512, 64), image k at
    (512 + 64 (k / 16) + 16 (k % 4), 256 + 64 (k % 16 / 4))."""
    game = load(folder)[2]
    u32 = lambda a: struct.unpack_from('<I', game, a - E.BASE)[0]
    record = u32(E.RECORDS + 4 * (8 * c + v))
    row = E.EFFECTS + 0x18 * game[record - E.BASE + 10]
    n = u32(row)
    red, green, blue = struct.unpack_from('<3h', game, row + 0x0C - E.BASE)
    sheet = file(folder, 3, n) if n < E.EFFECT_SPLIT else file(folder, 4, n - E.EFFECT_SPLIT)
    vram = bytearray(0x200000)
    put = lambda x, y, w, h, data: [vram.__setitem__(slice(2 * (1024 * (y + r) + x), 2 * (1024 * (y + r) + x + w)),
                                                    data[2 * w * r:2 * w * (r + 1)]) for r in range(h)]
    tint = lambda c: (c & 0x8000 | min(31, (c >> 10 & 31) * blue >> 7) << 10
                      | min(31, (c >> 5 & 31) * green >> 7) << 5 | min(31, (c & 31) * red >> 7))
    p = k = 0
    while sheet[p:p + 4] == b'\x10\0\0\0':
        flags, q = struct.unpack_from('<I', sheet, p + 4)[0], p + 8
        for block in range(2 if flags & 8 else 1):
            size, _, _, w, h = struct.unpack_from('<IHHHH', sheet, q)
            data = sheet[q + 12:q + size]
            if block == 0 and flags & 8:
                if k == 0:
                    put(512, 64, w, h, struct.pack('<%dH' % (len(data) // 2), *map(tint, struct.unpack('<%dH' % (len(data) // 2), data))))
            else:
                put(512 + 64 * (k // 16) + 16 * (k % 4), 256 + 64 * (k % 16 // 4), w, h, data)
            q += size
        p, k = q, k + 1
    return bytes(vram)


def program(bank: bytes, main: bytes, game: bytes | None = None) -> bytes:
    """RAM after boot: the program, its file directory and its move table."""
    game = game or E.unpack_game(main)
    rom = E.Rom(bank, main)
    ram = bytearray(SIZE)
    ram[IMAGE:IMAGE + len(game)] = game
    p, first = DIRECTORY, {}
    for i, n, a, size in E.archives(game, rom, direct=False):
        first.setdefault(i, (p, 0))
        first[i] = (first[i][0], n + 1)
        struct.pack_into('<II', ram, p, a & 0xFFFFFFFF, size)     # archive 29 wraps, as in the game
        p += 8
    for i, (start, count) in first.items():
        struct.pack_into('<II', ram, (E.ARCHIVES & 0x3FFFFF) + 8 * i, 0x80000000 | start, count)
    table = struct.unpack_from('<%dI' % (2 * E.NANIM), bank, E.ANIM_TABLE)
    for k in range(NMOVES):
        a = MOVES + 52 * k
        w = list(struct.unpack_from('<13I', ram, a))
        anim = (table[2 * w[0]] + E.ANIM_KEY[table[2 * w[0]] >> 28]) & 0xFFFFFFFF
        w[0], w[6] = anim, (w[6] & ~0xFF) | bank[anim]
        w[3] = 0x801B6204 + 14 * w[3]
        w[7] = 0 if w[7] == 0xFFFFFFFF else 0x80030D80 + 2 * w[7]
        w[8] = 0 if w[8] == 0xFFFFFFFF else 0x8002AFA8 + 4 * w[8]
        struct.pack_into('<13I', ram, a, *w)
        p = w[8] & 0x3FFFFF
        while w[8] and struct.unpack_from('<H', ram, p)[0]:
            kind, n = ram[p + 3], ram[p + 2]
            if kind == BOOSTED:
                row = HIT_ROWS + 10 * (w[5] & 0xFFFF)
                add = lambda r: struct.pack_into('<H', ram, r + 2, (struct.unpack_from('<H', ram, r + 2)[0] + n) & 0xFFFF)
                add(row)
                if struct.unpack_from('<H', ram, row)[0] != 0xFFFF:
                    while True:
                        add(row)
                        row += 10
                        if struct.unpack_from('<H', ram, row)[0] == 0xFFFF:
                            break
            p += 4
    return bytes(ram)


def select(boot: bytes, character: int, variant: int = 0, moveset: int | None = None) -> bytes:
    """RAM with this character (record 8 x character + variant) highlighted;
    moveset overrides its own (Tetsujin's and Unknown's draws)."""
    ram = bytearray(boot)
    u32 = lambda a: struct.unpack_from('<I', ram, a & 0x3FFFFF)[0]
    record = u32(E.RECORDS + 4 * (8 * character + variant)) & 0x3FFFFF
    sound, own = ram[record + 8], ram[record + 9]
    moveset = own if moveset is None else moveset
    slot = ram[(E.SLOTS & 0x3FFFFF) + 8 * character + variant]
    struct.pack_into('<5H', ram, KEYS + 0x0E, 8 * character + variant, moveset, character, sound, slot)
    moves = struct.unpack_from('<%dH' % NALIAS, ram, MOVESETS + moveset * 0x2B16)
    struct.pack_into('<%dI' % NALIAS, ram, ALIASES, *(0x80000000 | MOVES + 52 * m for m in moves))
    return bytes(ram)
