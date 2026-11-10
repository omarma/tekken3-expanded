#!/usr/bin/env python3
"""Jin's Tekken 5 DR moves, experimental (F34): the CPU's draw and the card's choices.

    python tools/test_f34_jin_dr.py --build DIR [--case draws|card] [--setting random|dr|ttt1|original]
        [--fights 12] [--expect-dr 0|1] [--shots DIR]

DIR is a build whose mods/ttt1 is the catalogue to test: with Jin's DR moves
(tools/dr_setup.py, the line "9 jin 9 dr" of natives.txt) or without.
From Practice's selector save (slot 8, workspace/fixtures/ps1-saves),
without a player:
    draws  Arcade, the first fighter under the cursor, Jin written as the
           CPU's fighter (0x800ADD5E) between the grid and the loading
           screen; the log's "CPU P2 fighter 9 draws N choice(s) -> S" line
           of each fight. With DR: 3 choices; RANDOM never draws dr, the
           TEKKEN 5 DR setting always does. Without DR: 2 choices, never dr.
           Jin loaded twice in a row is drawn once (the draw holds for
           that fighter): fewer lines than fights is normal.
    card   Practice, player 1 on Jin, the MOVESET card opened with square
           and walked with Right: T3 -> TTT1 -> DR (TEKKEN 5 DR) -> T3 with DR (two states
           without), a shot of each state (--shots), then DR taken: the
           fight loads Jin on the Jin-DR pack ("on the dr moveset").
Build: rel-lite (debug server lite).
"""
import argparse, collections, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L
from test_cpu_moveset_draw import MODES

START_SELECT, UP, RIGHT, CROSS, SQUARE = 0xfff6, 0xffef, 0xffdf, 0xbfff, 0x7fff
SCREEN, CPU_FIGHTER, P1_CURSOR = 0x800ae204, 0x800add5e, 0x80098106
JIN = 9
DRAW = re.compile(r'Native moves: CPU P(\d) fighter (\d+) draws (\d+) choice\(s\) -> (\S+)')


def arcade_fight(s):
    """Arcade from the selector save, the first fighter, Jin as the CPU's: the loading screen."""
    s.q(cmd='savestate', op='load', slot=8); s.q(cmd='clear_input')
    s.wait(lambda: s.value(SCREEN) == 9, 'the Practice selector', 20)
    time.sleep(.5)
    s.press(START_SELECT)
    s.wait(lambda: s.value(SCREEN) == 4, 'the modes menu', 15)
    time.sleep(.8)
    for _ in range(MODES['arcade']): s.press(UP)
    for _ in range(40):
        if s.value(SCREEN) == 11: return
        s.press(CROSS)
        # Between the grid and the loading screen the game has written its opponent:
        # Jin over it, until the mod's draw on the loading screen has read it.
        end = time.monotonic() + .8
        while time.monotonic() < end:
            if s.value(SCREEN) in (9, 10, 11): s.write(CPU_FIGHTER, JIN, 2)
            if s.value(SCREEN) == 11: break
        if s.value(SCREEN) == 11:
            for _ in range(20): s.write(CPU_FIGHTER, JIN, 2)
            return
    raise AssertionError('the loading screen was never reached')


def draws(a):
    env = {'TEKKEN3_NATIVE_MOVES': ''}
    if a.setting: env['TEKKEN3_CPU_MOVESET'] = a.setting
    env['TEKKEN3_CPU_MOVESET_SEED'] = a.seed
    s = L.Session(build=Path(a.build), slot=8, env=env)
    count, seen, failures = collections.Counter(), 0, []
    try:
        for i in range(a.fights):
            for attempt in range(3):
                try: arcade_fight(s); break
                except AssertionError as e: print('retry:', e, flush=True)
            else: raise AssertionError('three tries failed')
            time.sleep(1.5)
            lines = DRAW.findall(s.log()); fresh = lines[seen:]; seen = len(lines)
            for p, fid, n, source in fresh:
                print(f'fight {i + 1}: CPU P{p} fighter {fid}: {n} choices -> {source}', flush=True)
                if int(fid) != JIN: continue
                count[source] += 1
                want_n = 3 if a.expect_dr else 2
                if int(n) != want_n: failures.append(f'fight {i + 1}: {n} choices, {want_n} expected')
                if source == 'dr' and (a.setting != 'dr' or not a.expect_dr):
                    failures.append(f'fight {i + 1}: Jin drew dr with CPU MOVESET {a.setting or "random"}')
                if a.setting == 'dr' and a.expect_dr and source != 'dr':
                    failures.append(f'fight {i + 1}: Jin drew {source} with CPU MOVESET TEKKEN 5 DR')
    finally:
        s.stop()
    print(dict(count), 'Jin draws in', a.fights, 'fights')
    # The CPU draws once per fighter it loads (drawn_id): Jin twice in a row logs one draw.
    if not count: failures.append('no Jin draw: the forced CPU fighter did not hold')
    return failures


def card(a):
    s = L.Session(build=Path(a.build), slot=8, env={'TEKKEN3_NATIVE_MOVES': ''})
    shots = Path(a.shots) if a.shots else None
    if shots: shots.mkdir(parents=True, exist_ok=True)
    failures = []
    try:
        s.q(cmd='savestate', op='load', slot=8); s.q(cmd='clear_input')
        s.wait(lambda: s.value(SCREEN) == 9, 'the Practice selector', 20)
        time.sleep(1)
        for _ in range(30):
            if s.value(P1_CURSOR, 1) == JIN: break
            s.press(RIGHT); time.sleep(.2)
        else: raise AssertionError('the cursor never reached Jin')
        start = len(s.log())
        s.press(SQUARE); time.sleep(.6)
        states = 3 if a.expect_dr else 2
        order = ['T3', 'ttt1', 'dr'][:states] + ['T3']
        for k, name in enumerate(order):
            if k:
                s.press(RIGHT); time.sleep(.6)
            if shots: s.q(cmd='screenshot_file', path=str((shots / f'card-{k}-{name}.png').resolve()))
        log = s.log()[start:]
        seen = re.findall(r'P1 highlights (\S+) moves', log)
        print('card states:', ['T3'] + seen, flush=True)
        if seen != order[1:]: failures.append(f'card states {seen}, {order[1:]} expected')
        if a.expect_dr:
            s.press(RIGHT); time.sleep(.6); s.press(RIGHT); time.sleep(.6)      # T3 -> TTT1 -> DR
            s.press(CROSS); time.sleep(1)
            s.wait(lambda: 'P1 takes dr moves' in s.log(), 'DR never taken', 10)
            # The dummy (player 2): Jin again, on Tekken 3's moves (the card's choice is per slot).
            end = time.monotonic() + 120
            while 'on the dr moveset (Jin-DR' not in s.log():
                if time.monotonic() > end: raise AssertionError('Jin never loaded on Jin-DR')
                if s.value(SCREEN) == 9: s.press(CROSS)
                time.sleep(1)
            print('fight: Jin on the Jin-DR pack', flush=True)
            if shots:
                s.wait(lambda: s.value(SCREEN) == 8, 'the fight', 120); time.sleep(4)
                s.q(cmd='screenshot_file', path=str((shots / 'fight-jin-dr.png').resolve()))
    finally:
        s.stop()
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', required=True)
    ap.add_argument('--case', default='draws', choices=['draws', 'card'])
    ap.add_argument('--setting', default='')
    ap.add_argument('--seed', default='1')
    ap.add_argument('--fights', type=int, default=12)
    ap.add_argument('--expect-dr', type=int, default=1, choices=[0, 1])
    ap.add_argument('--shots')
    a = ap.parse_args()
    failures = draws(a) if a.case == 'draws' else card(a)
    for f in failures: print('FAIL', f)
    print('OK' if not failures else f'{len(failures)} failure(s)')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
