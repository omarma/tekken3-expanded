#!/usr/bin/env python3
"""B143: TTT's stage 11 (King's) at night, True Ogre fighting, drawn at all.

    python ressources/slot.py --kind game --who b143 --prio 2 -- \\
        python tools/test_b143_king_night.py [night11|night6|day11 ...]
            [--build build-rel-lite] [--data MODS] [--out DIR]

(a PSX_DEBUG_SERVER_LITE build; --data: the mods folder of an install, its
stage packs, TTT1 catalogue and music read in place, as
tools/test_b124_true_ogre_night.py)

In the dark arena (0x800AFAA0, True Ogre's fight) Tekken 3's stage_draw
(t3-ps1 decor/8006CC28.c) calls only the arena's TILE, 0x80048374, where the
engine draws a TTT stage at night (B124). Its hook first skipped that TILE
for arena 11 (lit, where 0x8006D014 has drawn the stage): TTT stage 11, the
one TTT stage played on arena 11, was never drawn at night, no floor, no
black far background, and as the game never clears the screen the older
frames stayed (the fighters and menus seen twice). Practice, the STAGE line
(F18) on a TTT stage, TEKKEN3_ARCADE_STAGES_LOG on; each case checks the
night line ("arcade stages: TTT stage n at night") and that the stage draws
in the fight: frame lines with tile primitives, floor quads and the far
background (at night the black TILE over the whole screen):

    night11   both True Ogre, TTT 11: at night, drawn (the bug)
    night6    both True Ogre, TTT 6: at night, drawn (another stage)
    day11     the grid's first fighters, TTT 11: by day, drawn
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import test_b122_gon_stages as b122  # noqa: E402

TRUE_OGRE = 20
NIGHT = re.compile(r'arcade stages: TTT stage (\d+) at night')
FRAME = re.compile(r'arcade stages: frame \d+, \d+ tiles in the cone, (\d+) tile primitives .*?, '
                   r'(\d+) floor quads, (\d+) far background')
CASES = {'night11': (11, True), 'night6': (6, True), 'day11': (11, False)}


def run(name: str, a, out: Path) -> bool:
    stage, ogre = CASES[name]
    line = f'ttt-{stage}'
    g = b122.Game(Path(a.build).resolve(), out / name / 'run', Path(a.data), 'ttt', '1',
                  {'TEKKEN3_STAGE_SELECT': f'vs={line},practice={line}', 'TEKKEN3_ARCADE_STAGES_LOG': '1'})
    try:
        b122.NATIVE['trueogre'] = TRUE_OGRE
        b122.to_menu(g, 1)
        b122.to_mode(g, b122.PRACTICE, 9)
        for _ in range(2):
            if ogre: b122.pick(g, 'trueogre')
            g.press(b122.CROSS); time.sleep(1.5)
        if 'waits on the STAGE band' in g.logtext(): g.press(b122.CROSS)
        g.wait(lambda: 'TTT Stages: Practice fight' in g.logtext(), f'{name}: no decision', 180)
        g.wait(lambda: g.value(b122.SCREEN) == 8 and g.value(b122.PHASE, 2) >= 6, f'{name}: the round never started', 180)
        start = len(g.logtext())
        time.sleep(8)               # several frame lines (every 120 stage frames)
        log = g.logtext()
        g.q(cmd='screenshot', path=str(out / f'{name}.png'))
        dark = g.value(0x800afaa0, 1)
        ids = g.value(b122.FIGHTERS, 2), g.value(b122.FIGHTERS + 2, 2)
    finally:
        g.stop()
    nights = {int(n) for n in NIGHT.findall(log)}
    frames = [tuple(map(int, f)) for f in FRAME.findall(log[start:])]
    drawn = [f for f in frames if f[0] > 0 and f[1] > 0 and f[2] > 0]
    ok = (stage in nights) == ogre and (TRUE_OGRE in ids) == ogre and bool(dark) == ogre and len(drawn) >= 2
    print(f'{name}: fighters {ids}, dark arena {dark}, at night {sorted(nights) or "-"}, '
          f'{len(drawn)}/{len(frames)} frame lines drawn (tiles, floor, far background: {frames[:2]})'
          f'  => {"OK" if ok else "WRONG"}')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cases', nargs='*', default=list(CASES), choices=list(CASES))
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--data', default=str(b122.DATA))
    ap.add_argument('--out', default=str(ROOT / 'workspace/b143'))
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bad = [c for c in a.cases if not run(c, a, out)]
    print(f'b143: {len(a.cases) - len(bad)}/{len(a.cases)} OK' + (f', wrong: {" ".join(bad)}' if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
