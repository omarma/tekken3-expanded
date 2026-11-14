#!/usr/bin/env python3
"""B171 (GH#219): a native on its TTT1 model keeps its model when a challenger joins an Arcade fight
("A NEW CHALLENGER ENTERS!!": Start on the other pad; Time Attack and Survival take no challenger).

    python tools/test_b171_challenger_costume.py [--mode arcade|timeattack|survival] [--costume ttt|tekken3]
        [--moves 0|1] [--joiner 2|1] [--seed N] [--vs] [--shots] [--build build-rel-lite] [--mods DIR]

A private copy of the build (test_stage_options.Game: headless, software x1, keyboard pads, a copy of
saves/), TEKKEN3_CPU_COSTUME=--costume, TEKKEN3_CPU_MOVESET_SEED=--seed, TEKKEN3_NATIVE_MOVES=--moves.
The player on pad 3 - joiner takes the fighter under the cursor with cross; once the round runs, the
other pad presses Start. Every model the mod loads ("<name> (TTT1 model) model: costume N" in the log)
while the fight is still shown (screens 8 and 1, before the selector) is a swap: FAIL if any, or if
nobody joined. --vs: then the VS fight, the joiner picking with square, the player with cross: each
fighter's model must be its pick's (files P1, P2). --shots: screenshots around the join
(workspace/b171/<tag>/). --mods: a folder with the TTT1 catalogue (ttt1/, an install's).

Pad 2 injection: a debug build, or rel-lite with apply_p2_override_to_sio (psxrecomp main.cpp) also
under PSX_DEBUG_SERVER_LITE (a local patch, not committed). Before the fix: FAIL; after: PASS.
"""
import argparse, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_stage_options as S

FIGHTERS, COSTUMES, HUMAN = 0x800add5c, 0x800add98, 0x800ae1f8
SQUARE = 0x7fff
NAMES = ['Paul', 'Law', 'Lei', 'King', 'Yoshimitsu', 'Nina', 'Hwoarang', 'Xiaoyu', 'Eddy', 'Jin', 'Julia',
         'Kuma', 'Bryan', 'Heihachi', 'Ogre', 'Mokujin', 'Gun Jack', 'Gon', 'Anna', 'Dr. B', 'True Ogre', 'Crow']
MODEL = re.compile(r'^(\S+) \(TTT1 model\) model: costume (\d)', re.M)
DRAW = re.compile(r'Native models: CPU P(\d) fighter (\d+) draws its (\w+) model')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='arcade', choices=['arcade', 'timeattack', 'survival'])
    ap.add_argument('--costume', default='ttt', choices=['ttt', 'tekken3'])
    ap.add_argument('--moves', default='', help='TEKKEN3_NATIVE_MOVES (0 T3, 1 TTT1); unset: the cards')
    ap.add_argument('--joiner', type=int, default=2, choices=[1, 2])
    ap.add_argument('--seed', default='1')
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--mods', default=str(ROOT / 'workspace/b171/mods-extra'))
    ap.add_argument('--shots', action='store_true')
    ap.add_argument('--vs', action='store_true', help='then the VS fight: the joiner picks with square (LP), the player cross (LK)')
    a = ap.parse_args()
    env = {'TEKKEN3_CPU_COSTUME': a.costume, 'TEKKEN3_CPU_MOVESET_SEED': a.seed}
    if a.moves: env['TEKKEN3_NATIVE_MOVES'] = a.moves
    tag = f'{a.mode}-{a.costume}-j{a.joiner}-{a.moves or "card"}-{a.seed}'
    shots = ROOT / 'workspace/b171' / tag
    if a.shots: shots.mkdir(parents=True, exist_ok=True)
    player_port, joiner_port = (1, 2) if a.joiner == 2 else (2, 1)
    g = S.Game(Path(a.build), a.mods, env, f'b171-{tag}', pad2=True)
    ok = False
    try:
        g.wait(lambda: g.screen() >= 2, 'the game did not boot', 90)
        g.q(cmd='press', buttons=0xffff, frames=2, port=2)       # pad 2 plugged: VS and challengers
        g.modes_menu()
        lui, ori = g.value(0x800db5d0), g.value(0x800db5d8)
        state = (lui & 0xffff) << 16 | (ori & 0xffff)
        labels = [g.string(g.value(state + 16 + 8 * i)) for i in range(g.value(state + 4))]
        g.write(0x80097f40, labels.index(S.MODES[a.mode]), 1); time.sleep(.2)
        g.press(S.CROSS, port=player_port)
        g.wait(lambda: g.screen() == 9, 'no selector'); time.sleep(1.5)
        g.write(0x8009f2a8, int(a.seed) * 2654435761 & 0xffffffff)     # the game's draw (TIPS.md section 25)
        end = time.monotonic() + 40
        while g.screen() not in (11, 8):
            if time.monotonic() > end:
                g.q(cmd='screenshot', path=str(ROOT / 'workspace/b171/stuck.png')); raise AssertionError('no loading screen')
            g.press(S.CROSS, port=player_port); time.sleep(1)
        time.sleep(.5)
        p = player_port - 1; c = 1 - p
        print(f'player P{p + 1} fighter {g.value(FIGHTERS + 2 * p, 2)} costume {g.value(COSTUMES + 2 * p, 2)}, '
              f'CPU P{c + 1} fighter {g.value(FIGHTERS + 2 * c, 2)} costume {g.value(COSTUMES + 2 * c, 2)}')
        g.wait(lambda: g.screen() == 8 and g.value(S.PHASE, 2) == 8, 'no fight', 90)
        time.sleep(3)                                          # the round runs
        before = MODEL.findall(g.log())
        print('models loaded before the join:', before[-4:])
        print('draws:', DRAW.findall(g.log()))
        if a.shots: g.q(cmd='screenshot', path=str(shots / 'f0000-before.png'))
        f0 = g.frame()
        g.q(cmd='press', buttons=S.START, frames=4, port=joiner_port)
        rows, last = [], None
        end = time.monotonic() + 12
        while time.monotonic() < end:
            f = g.frame()
            row = (g.screen(), g.value(S.PHASE, 2), g.value(HUMAN, 2), g.value(HUMAN + 2, 2), len(MODEL.findall(g.log())) - len(before), g.value(FIGHTERS), g.value(0x800afa88))
            if row != last: rows.append((f - f0, row)); last = row
            if a.shots and (f - f0) < 150:
                g.q(cmd='screenshot', path=str(shots / f'f{f - f0:04d}.png'))
            if row[0] in (9, 10) and f - f0 > 60: break
            time.sleep(.005)
        for r in rows: print('  frame +%d screen %d phase %d human %d/%d, models loaded since %d, fighters %08x mode %d' % ((r[0],) + r[1]))
        # Swaps while the fight shows (screens 8 and 1); the selector's own loads are not. The log is
        # read a poll late: a load seen on the last sample before the selector is the selector's.
        swaps = [r for i, r in enumerate(rows) if r[1][4] and r[1][0] in (8, 1) and i + 1 < len(rows) and rows[i + 1][1][0] in (8, 1)]
        after = MODEL.findall(g.log())[len(before):]
        log_after = g.log().split('\n')
        print('models loaded after the join:', after)
        print('draws:', DRAW.findall(g.log()))
        joined = any(r[1][2] and r[1][3] for r in rows)
        ok = joined and not swaps
        print('PASS' if ok else 'FAIL: a model swapped at the join' if joined else 'FAIL: nobody joined')
        if a.vs:
            # The VS fight that follows: each side's model is its pick's (square P1 file, cross P2),
            # nothing left of the CPU's draw.
            mark = len(MODEL.findall(g.log()))
            end = time.monotonic() + 40
            while g.screen() not in (11, 8):
                if time.monotonic() > end: raise AssertionError('no VS loading screen')
                g.press(SQUARE, port=joiner_port); g.press(S.CROSS, port=player_port); time.sleep(.5)
            g.wait(lambda: g.screen() == 8 and g.value(S.PHASE, 2) == 8, 'no VS fight', 90)
            time.sleep(2)
            j = joiner_port - 1; p = player_port - 1
            fj, fp = g.value(FIGHTERS + 2 * j, 2), g.value(FIGHTERS + 2 * p, 2)
            loads = MODEL.findall(g.log())[mark:]
            print(f'VS: joiner P{j + 1} fighter {fj} costume {g.value(COSTUMES + 2 * j, 2)}, player P{p + 1} fighter {fp} '
                  f'costume {g.value(COSTUMES + 2 * p, 2)}; models loaded {loads}')
            last = dict(MODEL.findall(g.log()))     # each fighter's last model (kept when unchanged): its file P<n>
            got = (last.get(NAMES[fj] if fj < len(NAMES) else ''), last.get(NAMES[fp] if fp < len(NAMES) else ''))
            vs_ok = fj == fp or got == ('1', '2')
            print('VS PASS' if vs_ok else f'VS FAIL: joiner / player files {got}, want (1, 2)')
            ok = ok and vs_ok
    finally:
        g.stop()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
