#!/usr/bin/env python3
"""The CPU's moveset draw, counted over Arcade fights without a player.

    python3 tools/test_cpu_moveset_draw.py [--fights 40] [--setting random|original|ttt1]

From Practice's selector save (slot 8, workspace/fixtures) each fight goes to
the modes menu, Arcade, the first character, and stops at the loading screen:
the "CPU P2 fighter ... draws" line of the log gives what the CPU drew. Prints
the count per choice. Build: build-rel (rel-lite, debug server lite).
"""
import argparse, collections, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

START_SELECT, UP, CROSS = 0xfff6, 0xffef, 0xbfff
DRAW = re.compile(r'Native moves: CPU P(\d) fighter (\d+) draws (\d+) choice\(s\) -> (\S+)')

MODES = {'arcade': 6, 'vs': 5, 'team': 4, 'timeattack': 3, 'survival': 2}    # Ups from TEKKEN FORCE

def one_fight(s, mode='arcade'):
    s.q(cmd='savestate', op='load', slot=8); s.q(cmd='clear_input')
    s.wait(lambda: s.value(0x800ae204) == 9, 'the Practice selector', 20)
    time.sleep(.5)
    s.press(START_SELECT)
    s.wait(lambda: s.value(0x800ae204) == 4, 'the modes menu', 15)
    time.sleep(.8)
    for _ in range(MODES[mode]): s.press(UP)     # from Force to the mode
    for _ in range(40):
        if s.value(0x800ae204) == 11: return
        s.press(CROSS); time.sleep(.5)
        if mode == 'team': s.press(0xffdf); time.sleep(.3)    # Right: a character is not taken twice in a team
    raise AssertionError('the loading screen was never reached')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fights', type=int, default=40)
    ap.add_argument('--setting', default='')
    ap.add_argument('--seed', default='')
    ap.add_argument('--mode', default='arcade', choices=sorted(MODES))
    ap.add_argument('--build', default=str(L.ROOT / 'build-rel'))
    a = ap.parse_args()
    env = {'TEKKEN3_NATIVE_MOVES': ''}
    if a.setting: env['TEKKEN3_CPU_MOVESET'] = a.setting
    if a.seed: env['TEKKEN3_CPU_MOVESET_SEED'] = a.seed
    s = L.Session(build=Path(a.build), slot=8, env=env)
    count, seen, done = collections.Counter(), 0, 0
    try:
        for i in range(a.fights):
            for attempt in range(3):             # a slow machine may drop a press
                try: one_fight(s, a.mode); break
                except AssertionError as e: print('retry:', e, flush=True)
            else: raise AssertionError('three tries failed')
            time.sleep(1.5)
            lines = DRAW.findall(s.log())
            fresh = lines[seen:]; seen = len(lines)
            for p, fid, n, source in fresh:
                count[source] += 1
                print(f'fight {i+1}: CPU P{p} fighter {fid}: {n} choices -> {source}', flush=True)
            done += 1
    finally:
        s.stop()
    print(dict(count), 'in', done, 'fights')

if __name__ == '__main__': main()
