#!/usr/bin/env python3
"""Dr. B's Doctor Breath: the colour of its cloud (B146, GH#196).

    python tools/test_b146_drb_breath.py --build build-rel-lite [--hitspark on|off] [--shots DIR] [--tag NAME]

T3 spits two mists through the first hit limb of a move (fx_special_update,
t3-ps1 decor/8006CC28.c): limb 25 (Nina's Evil Mist, Yoshimitsu's Poison
Breath) makes effect objects of type 10 with link +0x4C = 0, limb 28 (Dr.
B's Doctor Breath, lying face up, 1 or 2) with link 1. fx_type10_init
(decor/800724C4.c) draws the first with fx_cluts[8] = 0x7DCA, CLUT (160,
503), purple; the second with fx_cluts[0] = 0x7DC6, CLUT (96, 503),
yellow-green; T3's smoke, (80, 503), is grey. TTT Hitspark draws both in
64 x 64 with TTT1's smoke images (F22, TIPS 185): the mist in TTT1's mist
palette, the breath in a palette of its own (row 5 of the palette cell,
made from the smoke's: smoke_breath_palette). Before B146, the breath took
the smoke's grey (row 3).

Practice, Dr. B on his T3 moves against Jin (test_hit_effect_64's path). The
record of his alias table whose first hit limb is 28 is launched from a
saved state (actor +0x1A0 / +0x1A4): it must draw a type 10 cloud with link
1 in CLUT (96, 503), yellow-green. With TTT Hitspark on, the palette cell
is found in the upper half by the smoke's palette (row 3); row 4 must be
the mist's, row 5 yellow-green (red = green, blue below). --shots writes
pictures of the move (one launch each, from the saved state).
Needs a build with PSX_DEBUG_SERVER_LITE or PSX_DEBUG_TOOLS, and mods/ttt1.
"""
import argparse, os, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_b67_machine_gun_cannon as B
import test_hit_effect_64 as H

FX_ACTIVE, FX_PRIM, OT_BUFFER = 0x800a0988, 0x28, 0x800adefc
ALIASES = 0x800adc20
DRB = 19
FRAMES = 72
SHOT_FRAMES = range(4, 61, 4)                 # move frames (+0x58) of the pictures
T3_BREATH, T3_SMOKE, T3_MIST = (96, 503), (80, 503), (160, 503)
SMOKE_ROW, MIST_ROW, BREATH_ROW = 3, 4, 5


def word(b, o=0): return struct.unpack_from('<I', b, o)[0]


def five(c): return (c & 31, c >> 5 & 31, c >> 10 & 31)


def peek(g, x, y):
    """The 16 colours of CLUT (x, y), as 15-bit words."""
    h = g.q(cmd='vram_peek', x=x, y=y, w=16, h=1)['hex']
    return [int(h[4 * i:4 * i + 4], 16) for i in range(16)]           # %04x a pixel


def hue(pal):
    """'yellow-green' (red = green, blue below), 'grey', 'purple' (no green) or 'other', on the opaque entries."""
    used = [five(c) for c in pal if c & 0x7fff]
    if not used: return 'empty'
    if all(r == g == b for r, g, b in used): return 'grey'
    bright = [c for c in used if c[0] > 12]
    if bright and all(abs(r - g) <= 1 and b + 3 <= r for r, g, b in bright): return 'yellow-green'
    if all(g <= 2 < r for r, g, b in used): return 'purple'
    return 'other'


def show(pal): return ' '.join('%d.%d.%d' % five(c) for c in pal)


def breath(g):
    """(alias index, record) of each of Dr. B's own records on limb 28."""
    aliases = g.value(g.value(ALIASES) + 12)
    table = g.read(aliases, 4023 * 4)
    found = []
    for i in range(4023):
        r = word(table, 4 * i)
        if not 0x80000000 <= r < 0x80200000: continue
        limbs = word(g.read(r + 40, 4))
        if 0x80000000 <= limbs < 0x80200000 and g.read(limbs, 1)[0] == 28: found.append((i, r))
    assert found, 'no T3 record of Dr. B on limb 28'
    return found


def mists(g):
    """(link, CLUT of the game's own quad) of each type 10 object drawn now."""
    out, e = [], g.value(FX_ACTIVE + 4)
    buf = g.value(OT_BUFFER)
    for _ in range(0x50):
        if not e or e == FX_ACTIVE: break
        head = g.read(e, 0x50 + 2 * FX_PRIM)
        if head[0xc] == 10 and head[0xd] & 0x40:
            out.append((word(head, 0x4c), struct.unpack_from('<H', head, 0x50 + (buf & 1) * FX_PRIM + 14)[0]))
        e = word(head, 4)
    return out


def away(g, distance):
    """Player 2 that far from player 1, on the line between them (the cloud in the clear)."""
    p1, p2 = (struct.unpack('<3i', g.read(B.ACTOR + p * B.STRIDE, 12)) for p in (0, 1))
    dx, dz = p2[0] - p1[0], p2[2] - p1[2]
    n = (dx * dx + dz * dz) ** .5 or 1
    x, z = int(p1[0] + dx / n * distance), int(p1[2] + dz / n * distance)
    for off, v in ((0, x), (8, z), (0xf68, x), (0xf70, z)): g.write(B.ACTOR + B.STRIDE + off, struct.pack('<i', v))
    g.frames(30)


def launch(g, number, record):
    keep = g.read(B.ACTOR + 0x1a2, 2)
    g.q(cmd='write_ram', addr=f'{B.ACTOR + 0x1a0:08x}', bytes=(struct.pack('<H', number) + keep + struct.pack('<I', record)).hex())


def palette_cell(g, smoke_pal):
    """(x, y) of the upper half's palette cell: the row holding the smoke pack's palette, minus 3."""
    dump = H.WORK / f'high-vram-{os.getpid()}.bin'
    g.q(cmd='high_vram', path=str(dump))
    hi = dump.read_bytes(); dump.unlink()
    want = struct.pack('<16H', *smoke_pal)
    at = [o for o in range(0, len(hi), 32) if hi[o:o + 32] == want]
    assert at, "the smoke's palette is not in the upper half"
    o = at[0] // 2
    rows = lambda r: list(struct.unpack_from('<16H', hi, at[0] + 2048 * (r - SMOKE_ROW)))
    return (o % 1024, 512 + o // 1024 - SMOKE_ROW), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--hitspark', choices=('on', 'off'), default='on')
    ap.add_argument('--shots', type=Path)
    ap.add_argument('--tag')
    a = ap.parse_args()
    build = (ROOT / a.build).resolve()
    tag = a.tag or f'b146-drb-{a.hitspark}'
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    smoke_pal = list(struct.unpack_from('<16H', (build / 'mods/ttt1/Smoke-TTT1-hiteffect64.hfx').read_bytes(), 16))
    mist_pal = list(struct.unpack_from('<16H', (build / 'mods/ttt1/Mist-TTT1-hiteffect64.hfx').read_bytes(), 16))
    H.WORK.mkdir(parents=True, exist_ok=True)
    g = H.Game(build, tag, (), 'off', (), a.hitspark == 'on')
    if a.shots: a.shots.mkdir(parents=True, exist_ok=True)
    failures = []
    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what, flush=True)
        if not ok: failures.append(what)
    try:
        H.to_practice(g, 'drb', catalogue)
        assert struct.unpack('<5H', g.read(0x800a923c, 10))[2] == DRB, 'P1 is not Dr. B'
        g.write(B.DUMMY, bytes([0]))
        g.frames(60)                                # his stance is not move 3: B.place would wait for it
        records = breath(g)
        print('Dr. B on limb 28: ' + ', '.join(f'alias {i:#x} record {r:08X} active {g.read(r + 45, 1)[0]}..{g.read(r + 46, 1)[0]}'
                                               for i, r in records))
        away(g, 1400)
        g.q(cmd='savestate', op='save', slot=1); time.sleep(1)
        t3 = {xy: peek(g, *xy) for xy in (T3_BREATH, T3_SMOKE, T3_MIST)}
        for xy, p in t3.items(): print(f'T3 CLUT {xy}: {hue(p)}: {show(p)}')
        check(hue(t3[T3_BREATH]) == 'yellow-green', f'T3 breath CLUT {T3_BREATH} yellow-green')
        seen = set()
        g.q(cmd='savestate', op='load', slot=1); time.sleep(1)
        launch(g, *records[0])
        f0 = g.frame()
        while g.frame() < f0 + FRAMES: seen.update(mists(g))
        clut = 0x7dc6
        check((1, clut) in seen, f'the breath drew a type 10 cloud, link 1, CLUT {clut:04X} (seen {sorted(seen)})')
        if a.hitspark == 'on':
            cell, rows = palette_cell(g, smoke_pal)
            print(f'palette cell {cell}:')
            for r, name in ((SMOKE_ROW, 'smoke'), (MIST_ROW, 'mist'), (BREATH_ROW, 'breath')):
                print(f'  row {r} ({name}): {hue(rows(r))}: {show(rows(r))}')
            check(rows(MIST_ROW) == mist_pal, "row 4 is TTT1's mist palette")
            check(hue(rows(BREATH_ROW)) == 'yellow-green', 'row 5, the breath, is yellow-green')
        if a.shots:                                 # one launch a picture, at move frame k
            for k in SHOT_FRAMES:
                g.q(cmd='savestate', op='load', slot=1); time.sleep(1)
                launch(g, *records[0])
                end = time.monotonic() + 10
                while time.monotonic() < end:           # player 1's record (+0x54) and its frame (+0x58)
                    now = g.read(B.ACTOR + 0x54, 6)
                    if word(now) == records[0][1] and struct.unpack_from('<h', now, 4)[0] >= k: break
                g.q(cmd='screenshot', path=str(a.shots / f'{tag}-{k:03d}.png'))
            print(f'pictures: {a.shots}')
    finally:
        g.stop()
    if failures: raise SystemExit('FAIL: ' + '; '.join(failures))
    print('PASS')


if __name__ == '__main__':
    main()
