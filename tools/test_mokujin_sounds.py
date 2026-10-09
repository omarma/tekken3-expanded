#!/usr/bin/env python3
"""Which sounds Mokujin (ID 15) plays when he wins, per moveset key he drew.

    python3 tools/test_mokujin_sounds.py --build <build-opt-dbg> [--key 16] [--mods none]

Cold start, Arcade selector, Mokujin unlocked and picked. Once the round is
running (state 8, phase 8) actor+0x16 (the key of the moves, drawn by
0x8004F2DC) is overwritten with --key, player 2's life set to 0, and every
sound event (TEKKEN3_TTT1_SOUND_LOG: player, event, caller) from the K.O. on is
printed. --mods none runs without the mods directory (T3 as the disc has it).
Measurement only: the test proves which events play, not how they sound.
"""
import argparse, os, re, shutil, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T

T.WORK = ROOT / 'workspace/mokujin-sounds'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--key', type=int, default=-1, help='moveset key to force (-1: keep the draw)')
    ap.add_argument('--mods', choices=('all', 'none'), default='all')
    ap.add_argument('--donor', type=int, default=-1, help='make the draw pick this key (mask 0x80097EF0)')
    ap.add_argument('--tag', default=None)
    ap.add_argument('--char', type=int, default=15)
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    build = Path(a.build).resolve()
    tag = a.tag or f'k{a.key}-{a.mods}'
    if a.mods == 'none':
        empty = T.WORK / 'empty-build'
        shutil.rmtree(empty, ignore_errors=True); empty.mkdir()
        for n in ('Tekken_3_Recompiled', 'bios'): (empty / n).symlink_to(build / n)
        (empty / 'mods').mkdir()
        build = empty
    g = T.Game(build, tag, {'TEKKEN3_TTT1_SOUND_LOG': '1', 'TEKKEN3_NATIVE_MOVES': '0'})
    try:
        T.to_selector(g)
        if os.environ.get('EXPLORE'):
            vals = []
            for _ in range(24):
                vals.append(g.value(T.CURSOR_CHAR)); g.q(cmd='press', buttons=T.RIGHT, frames=4, port=1); time.sleep(.3)
            print('cursor values on RIGHT:', vals); return
        # Mokujin is not on the grid's path: take Paul, then write the ID the
        # loading screen reads (0x800ADD5C, one half per player) until the fight.
        for _ in range(60):
            if g.value(T.CURSOR_CHAR) == 0: break
            g.q(cmd='press', buttons=T.RIGHT, frames=6, port=1); time.sleep(.5)
        else: raise AssertionError('cursor did not reach Paul')
        g.press(T.SQUARE, frames=12)
        def force():
            if g.value(T.STATE) == 11:
                g.q(cmd='write_ram', addr='800add5c', bytes=a.char.to_bytes(2, 'little').hex())
            if a.donor >= 0 and g.value(T.STATE) in (11, 8) and g.value(T.PHASE, 2) < 7:
                # The draw (0x8004F2DC) picks among 0x80097EF0 & 0x13FFF: leave one donor.
                g.q(cmd='write_ram', addr='80097ef0', bytes=(1 << a.donor).to_bytes(4, 'little').hex())
        seen = []
        def fight2():
            k = (g.value(T.STATE), g.value(T.PHASE, 2))
            if not seen or seen[-1] != k: seen.append(k)
            return k[0] == 8 and k[1] >= 8
        try: g.wait(fight2, 'round did not start', 150, lambda: (g.press(T.SQUARE, frames=12) if seen and seen[-1][0] == 9 else None, force()))
        except AssertionError:
            print('states seen', seen, 'cursor', g.value(T.CURSOR_CHAR)); g.shot('stuck'); raise
        ident = T.actor(g, 0)
        print('actor +0x14,+0x16,+0x18 =', ident[:3], 'opponent', T.actor(g, 1)[:3])
        if a.key >= 0:
            g.q(cmd='write_ram', addr=f'{0x800a923c + 2:08x}', bytes=a.key.to_bytes(2, 'little').hex())
            print('forced key', a.key, '->', T.actor(g, 0)[1])
        time.sleep(1.5)
        mark = len(g.log())
        # K.O.: player 2's life to 0.
        g.q(cmd='write_ram', addr=f'{T.ACTOR + T.STRIDE + T.LIFE:08x}', bytes='0000')
        time.sleep(14)
        lines = [l for l in g.log()[mark:].splitlines() if 'SOUNDLOG' in l or 'TTT1 characters' in l or 'announced' in l]
        print(f'{len(lines)} sound lines after the K.O.')
        for l in lines[:80]: print('  ', l)
        print('key now', T.actor(g, 0)[1], 'state', g.value(T.STATE), 'phase', g.value(T.PHASE, 2))
        (T.WORK / f'{tag}.sounds.txt').write_text('\n'.join(lines))
    finally:
        g.stop()


if __name__ == '__main__':
    main()
