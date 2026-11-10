#!/usr/bin/env python3
"""F28: the guests' HD grid tiles and portraits in the running game, and the
stage they must not spoil (TIPS § 225).

    python tools/test_f28_hd_tiles.py OUT [--exe build-rel-lite/Tekken_3_Expanded.exe] [--data DIR]

The reference bench's game (tools/perf/ref_bench.py: a lite build, windowed,
game.toml's OpenGL x3, blank cards), with a catalogue holding the HD tiles
(--data: bios and mods; mods/ttt1 with <Name>-T3-tile-hd.bin and
-portrait-hd.bin; mods/arcade-stages). Through slot.py.

1. Arcade selector, Tag page: guest cells drawn from the upper VRAM half
   (debug command high_vram: its primitive count grows); Kazuya under the
   cursor, more than the 18 cells a frame (his portrait's strips); the
   loading screen's portrait of a guest too.
2. The arena-0 stage pack stays loaded after the fight (arena 0 also shows
   behind CONTINUE: the same pack, not loaded again); player 1 loses, CONTINUE,
   back to the selector, whose HD tiles are written over the stage's
   rectangles; the same fight again (the pack is not loaded again): every
   pixel of the upper half the tiles changed is the stage's again, as in
   the first fight (pixels that change between two dumps of the first fight,
   animated textures, left out). Fails if no tile covered the stage or if
   the pack was loaded again (the check would see nothing).
3. Team Battle grid, Tag page: guest cells from the upper half too.
(The Arcade loading screen shows the two portraits, not the cards that
hd_card_put also covers.)
Exit status 1 if a check fails. Dumps and screenshots in OUT.
"""
import argparse, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/perf'), str(ROOT / 'tools')]
import ref_bench as B
import ref_scenes as S

R2 = 0xfdff
ARENA = 0             # the arena CONTINUE shows too: its pack stays loaded from one fight to the next


def high(g, path):
    g.q(cmd='high_vram', path=str(path))
    return np.fromfile(path, '<u2').reshape(512, 1024)


def prims(g): return g.q(cmd='high_vram')['primitives']


def stage_pixels(path):
    """The upper half as an arcade stage pack (format 3) poses it: its VRAM
    section's rectangles (src/tekken3_arcade_stages.c, pack_load_from), NaN
    outside them."""
    import struct
    b = path.read_bytes()
    n = struct.unpack_from('<I', b, 8)[0]
    o = next(struct.unpack_from('<I', b, 16 + 12 * i + 4)[0] for i in range(n) if b[16 + 12 * i:20 + 12 * i] == b'VRAM')
    out = np.full((512, 1024), np.nan)
    count = struct.unpack_from('<I', b, o)[0]; o += 4
    for _ in range(count):
        x, y, w, h = struct.unpack_from('<4H', b, o); o += 8
        if y >= 512: out[y - 512:y - 512 + h, x:x + w] = np.frombuffer(b, '<u2', w * h, o).reshape(h, w)
        o += 2 * w * h
    return out


def hd_slots():
    """What the HD tiles and portraits take in the upper half (src/tekken3_ttt1_roster.c,
    hd_slot_place: 20 tiles of 64 x 116, 16 a row; hd_portrait_put: 168 x 252 at (192 p, 768))."""
    m = np.zeros((512, 1024), bool)
    for s in range(20): m[116 * (s // 16):116 * (s // 16) + 116, 64 * (s % 16):64 * (s % 16) + 64] = True
    for p in range(2): m[256:508, 192 * p:192 * p + 168] = True
    return m


def grows(g, seconds, step=None):
    a = prims(g)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if step: step()
        time.sleep(.5)
    return prims(g) - a


def pick(g, what):
    """Square on the cell under player 1's cursor until the loading screen
    (state 11); once Square opened the MOVESET card (a native), Cross until
    it confirms, as ref_scenes.to_fight does."""
    cards = g.log().count('P1 opens the MOVESET card')
    end, last = time.monotonic() + 60, 0.0
    while g.value(B.STATE) in (9, 8) and not (g.value(B.STATE) == 8 and g.value(B.PHASE, 2) >= 6):
        if time.monotonic() > end: raise AssertionError(what)
        opened = g.log().count('P1 opens the MOVESET card') > cards
        if g.value(B.STATE) == 9 and time.monotonic() - last > (.5 if opened else 1.5):
            g.q(cmd='press', buttons=B.CROSS if opened else B.SQUARE, frames=4)
            last = time.monotonic()
        time.sleep(.1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out', type=Path)
    ap.add_argument('--exe', type=Path, default=ROOT / 'build-rel-lite/Tekken_3_Expanded.exe')
    ap.add_argument('--data', type=Path, default=Path(r'C:\TekkenProject\f28-hd\data-hd'))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    S.DATA = a.data                                   # ref_scenes.guest() reads its catalogue
    failed = []

    def check(ok, what):
        print(('ok    ' if ok else 'FAILED ') + what, flush=True)
        if not ok: failed.append(what)

    g = B.Game('f28', a.exe, a.data, env={'TEKKEN3_STAGES': 't3'})
    try:
        kazuya = S.guest('kazuya')
        # 1. the selector's Tag page
        S.to_selector(g)
        g.press(R2); time.sleep(2)
        # the cursor on the page's first cell, Kazuya: his 18 tiles' cells and his portrait's strips
        f0, n0 = g.frame(), prims(g); time.sleep(2); f1, n1 = g.frame(), prims(g)
        per = (n1 - n0) / max(1, f1 - f0)
        g.shot(a.out / 'selector-portrait.png')
        check(per > 18.5, f'selector, Kazuya under the cursor: {per:.1f} primitives from the upper half a frame '
                          '(18 tiles, more with his HD portrait)')
        n = grows(g, 3, lambda: g.press(S.RIGHT))
        g.shot(a.out / 'selector-tag.png')
        check(n > 0, f'selector Tag page: {n} primitives from the upper half in 3 s')
        # 2. a fight on arena 0 (its stage in the upper half); lose, CONTINUE, selector, the same fight
        S.force_arena(g, ARENA)
        pick(g, 'the loading screen never came')
        for side, fighter in ((0, kazuya), (1, S.JIN)):
            g.write(0x800add5c + 2 * side, fighter.to_bytes(2, 'little'))
            g.write(0x800add98 + 2 * side, b'\0\0')
        n0 = prims(g); time.sleep(1); g.shot(a.out / 'loading.png')
        g.wait(lambda: g.value(B.STATE) != 11, 'the loading screen never ended', 120)
        check(prims(g) > n0, f'loading screen: {prims(g) - n0} primitives from the upper half (the guest\'s HD portrait)')
        g.wait(lambda: g.value(B.STATE) == 8 and g.value(B.PHASE, 2) >= 8, 'the round never started', 120)
        time.sleep(2)
        f1a = high(g, a.out / 'fight1-a.bin'); time.sleep(1.5); f1b = high(g, a.out / 'fight1-b.bin')
        g.shot(a.out / 'fight1.png')

        def lose():
            if g.value(B.STATE) == 8 and g.value(B.PHASE, 2) == 8: g.write(S.LIFE1, b'\0\0')
            if g.value(B.STATE) != 8: g.press(B.START)
        g.wait(lambda: g.value(B.STATE) == 9, 'CONTINUE never led back to the selector', 180, lambda: (lose(), time.sleep(.5)))
        time.sleep(3)
        sel = high(g, a.out / 'selector-after.bin')
        g.shot(a.out / 'selector-after.png')
        pick(g, 'the second loading screen never came')
        for side, fighter in ((0, kazuya), (1, S.JIN)):
            g.write(0x800add5c + 2 * side, fighter.to_bytes(2, 'little'))
            g.write(0x800add98 + 2 * side, b'\0\0')
        g.wait(lambda: g.value(B.STATE) == 8 and g.value(B.PHASE, 2) >= 8, 'the second round never started', 120)
        time.sleep(2)
        f2 = high(g, a.out / 'fight2.bin')
        g.shot(a.out / 'fight2.png')
        # The stage's own pixels, from its pack; only where it and the HD slots
        # overlap (the sparks, lasers and wolf elsewhere put theirs back when
        # they draw), and where the first fight showed them (animated ones out).
        stage, ours = stage_pixels(a.data / 'mods/arcade-stages' / f'stage{ARENA:02d}.ast'), hd_slots()
        mask = ~np.isnan(stage) & ours & (f1a == stage) & (f1a == f1b)
        covered = mask & (sel != stage)
        spoilt = mask & (f2 != stage)
        check(int(covered.sum()) > 0, f'selector after the fight: {int(covered.sum())} stage pixels under HD tiles and portraits')
        loads = g.log().count(f'arcade stages: stage {ARENA} loaded')
        check(loads == 1, f'stage {ARENA} pack loaded {loads} time(s): once, so the second fight did not reload it')
        check(int(spoilt.sum()) == 0, f'second fight, same stage: {int(spoilt.sum())} stage pixels not put back')
    finally:
        g.stop()
    # 3. Team Battle grid, Tag page (a new game: the grid as ref_scenes opens it)
    g = B.Game('f28-team', a.exe, a.data)
    try:
        S.team(True)(g)
        g.press(R2); time.sleep(2)
        n = grows(g, 3, lambda: g.press(S.RIGHT))
        g.shot(a.out / 'team-grid-tag.png')
        check(n > 0, f'Team Battle grid, Tag page: {n} primitives from the upper half in 3 s')
    finally:
        g.stop()
    print('FAILED' if failed else 'all checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
