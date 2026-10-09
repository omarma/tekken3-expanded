#!/usr/bin/env python3
"""Tekken Ball: the MOVESET card and the CPU's moveset draw (B33, GH#53).

    python3 tools/test_ball_moveset.py [--native jin] [--t3] [--cpu ttt1|original] [--build build-rel-lite]

From Practice's selector save (slot 8, workspace/fixtures): unlocks Tekken
Ball (0x80097F26/27), Start + Select to the modes menu, Tekken Ball, walks
the grid to the native, square opens its MOVESET card, right (unless --t3)
switches it to TEKKEN TAG TOURNAMENT, X takes it, X takes the ball. At the
loading screen the CPU's fighter is made Paul, so it has a moveset to draw
(TEKKEN3_CPU_MOVESET=--cpu). Checks in the log and in the fight: player 1
on the moves it chose, d/b+1 played from the TTT1 pack or not, the CPU on
the moves the setting gives. Build: rel-lite (debug server lite).
"""
import argparse, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

SCREEN, PHASE, MODE, BLOCKS = 0x800ae204, 0x800ae224, 0x800afa88, 0x800b8d70
ACTOR, STRIDE = 0x800a9228, 0x188c
START_SELECT, CROSS, SQUARE, RIGHT, LEFT, UP, DOWN = 0xfff6, 0xbfff, 0x7fff, 0xffdf, 0xff7f, 0xffef, 0xffbf
DOWN_BACK_1 = 0x7f3f                                  # down + left + square: P1 faces right
BALL_LINE, PAUL = 6, 0
CELLS = {'law': (0, 0), 'paul': (6, 0), 'xiaoyu': (0, 1), 'yoshimitsu': (1, 1), 'nina': (2, 1),
         'heihachi': (3, 1), 'king': (4, 1), 'lei': (5, 1), 'jin': (6, 1), 'hwoarang': (0, 2),
         'bryan': (2, 2), 'anna': (5, 2), 'eddy': (6, 2)}
IDS = {'paul': 0, 'law': 1, 'lei': 2, 'king': 3, 'yoshimitsu': 4, 'nina': 5, 'hwoarang': 6,
       'xiaoyu': 7, 'eddy': 8, 'jin': 9, 'bryan': 12, 'heihachi': 13, 'anna': 18}


def in_pack(address): return 0x9f000000 <= address < 0x9f400000


def to_ball_grid(s):
    s.wait(lambda: s.value(SCREEN) == 9, 'the Practice selector', 20)
    time.sleep(.5)
    s.write(0x80097f26, 1, 1); s.write(0x80097f27, 1, 1)
    s.press(START_SELECT)
    s.wait(lambda: s.value(SCREEN) == 4, 'the modes menu', 15)
    time.sleep(.3)
    s.write(0x80097f40, BALL_LINE); s.press(CROSS)
    s.wait(lambda: s.value(SCREEN) == 10 and s.value(MODE) == 7 and s.value(BLOCKS) == 3, 'TEKKEN BALL SELECT', 20)
    time.sleep(1)


def run(s, native, ttt1, cpu):
    to_ball_grid(s)
    col, row = CELLS[native]
    for _ in range(20):
        x, y = s.value(BLOCKS + 8), s.value(BLOCKS + 12)
        if (x, y) == (col, row): break
        s.press(DOWN if y < row else UP if y > row else RIGHT if x < col else LEFT)
    else: raise AssertionError(f'the grid cursor never reached {native}')
    s.press(SQUARE)
    s.wait(lambda: 'P1 opens the MOVESET card' in s.log(), 'square did not open the MOVESET card (the bug)', 5)
    if ttt1:
        s.press(RIGHT)
        s.wait(lambda: 'P1 highlights TTT1 moves' in s.log(), 'right did not switch to TTT1 moves', 5)
    s.shot(f'ball-{native}-card')
    s.press(CROSS)
    s.wait(lambda: f'P1 takes {"TTT1" if ttt1 else "T3"} moves' in s.log(), 'X did not take the card', 5)
    s.wait(lambda: s.value(BLOCKS) == 15, 'the ball choice never came', 10)
    assert s.value(BLOCKS + 56) >> 2 == IDS[native], ('another fighter was picked', s.value(BLOCKS + 56))
    # X takes the ball; the loading screen (11) lasts some twenty frames.
    s.q(cmd='set_input', buttons=CROSS)
    end = time.monotonic() + 10
    while s.value(SCREEN) != 11:
        if time.monotonic() > end: raise AssertionError('the loading screen never came')
    s.q(cmd='set_input', buttons=0xffff)
    s.write(0x800add5e, PAUL, 2)                      # the CPU: a native with a moveset to draw
    s.wait(lambda: s.value(SCREEN) == 8 and s.value(PHASE, 2) >= 6 and s.value(ACTOR + 0x54) != 0,
           'the fight never started', 90)
    log = s.log()
    name = native.capitalize()
    assert (f'P1 {name} on the TTT1 moveset' in log) == ttt1, f'P1 is not on the {"TTT1" if ttt1 else "T3"} moves'
    drawn = re.findall(r'Native moves: CPU P2 fighter 0 draws \d+ choice\(s\) -> (\S+)', log)
    assert drawn, 'the CPU drew no moveset'
    expected = 'T3' if cpu == 'original' else cpu
    assert drawn[-1] == expected, ('CPU drew', drawn[-1], 'expected', expected)
    assert in_pack(s.value(0x800adc20)) == ttt1, 'P1 moves header not where expected'
    assert in_pack(s.value(0x800adc24)) == (expected != 'T3'), 'P2 moves header not where expected'
    s.write(ACTOR + STRIDE + 0xc5, 0, 1)             # the opponent stays idle
    time.sleep(3)
    records = set()
    s.q(cmd='set_input', buttons=DOWN_BACK_1)
    until = s.game_until(1.2)
    shot = False
    while until():
        records.add(s.value(ACTOR + 0x54))
        if not shot and s.value(ACTOR + 0x58, 2) >= 8:
            s.q(cmd='set_input', buttons=0xffff); s.shot(f'ball-{native}-{"ttt1" if ttt1 else "t3"}-db1'); shot = True
    s.q(cmd='set_input', buttons=0xffff)
    from_pack = [hex(r) for r in records if in_pack(r)]
    print('P1 d/b+1 records:', sorted(hex(r) for r in records))
    print('CPU draw:', drawn[-1])
    if ttt1: assert from_pack, 'd/b+1 played no TTT1 record'
    else: assert not from_pack, ('d/b+1 played a TTT1 record on T3 moves', from_pack)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--native', default='jin', choices=sorted(CELLS))
    ap.add_argument('--t3', action='store_true')
    ap.add_argument('--cpu', default='ttt1', choices=['ttt1', 'original'])
    ap.add_argument('--build', default=str(L.ROOT / 'build-rel-lite'))
    a = ap.parse_args()
    s = L.Session(build=Path(a.build), slot=8, env={'TEKKEN3_NATIVE_MOVES': '', 'TEKKEN3_CPU_MOVESET': a.cpu})
    try:
        run(s, a.native, not a.t3, a.cpu)
        print('OK')
    finally:
        s.stop()


if __name__ == '__main__':
    main()
