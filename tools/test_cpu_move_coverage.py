#!/usr/bin/env python3
"""Does the CPU use a move of a native's TTT1 moves? (default: Paul's Turn Thruster, SS+1)

    python3 tools/test_cpu_move_coverage.py find  [--native paul]     # player 1 plays the move, prints its records
    python3 tools/test_cpu_move_coverage.py watch [--native paul] [--seconds 240]   # the CPU is that native, counts its records

find: Paul on TTT1 picked on the Arcade grid; Up (a sidestep) then square (button 1)
a few times, and every record of player 1 (acteur +0x54) seen after it, next to
a plain square (the jab) for reference. watch: the opponent is written as the
native at the loading screen, TEKKEN3_CPU_MOVESET=ttt1, player 1 stands still
with a full life bar; the histogram of the CPU's records is printed, as
`record -> count`, with the records found by `find` marked.
"""
import argparse, collections, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L
from test_native_moves import NATIVES, PAD_RIGHT, PAD_DOWN, PAD_SQUARE, PAD_CROSS
from test_cpu_moveset_draw import START_SELECT, UP, CROSS

ACTOR = (0x800a9228, 0x800a9228 + 0x188c)
PAD_UP = UP

def to_arcade(s, env_note=''):
    s.q(cmd='savestate', op='load', slot=8); s.q(cmd='clear_input')
    s.wait(lambda: s.value(0x800ae204) == 9, 'the Practice selector', 20)
    time.sleep(.5); s.press(START_SELECT)
    s.wait(lambda: s.value(0x800ae204) == 4, 'the modes menu', 15)
    time.sleep(.8)
    for _ in range(6): s.press(UP)
    s.press(CROSS)
    s.wait(lambda: s.value(0x800ae204) == 9 and s.value(0x80118648) == 21, 'the Arcade grid', 30)
    time.sleep(1.5)

def pick_paul(s, cid):
    for i in range(48):
        if s.value(0x80118668) == cid: break
        before = s.value(0x80118668)
        s.press(PAD_RIGHT)
        if i % 12 == 11 or s.value(0x80118668) == before: s.press(PAD_DOWN)
    else: raise AssertionError('cursor never reached the native')
    s.press(PAD_SQUARE)
    s.wait(lambda: 'opens the MOVESET card' in s.log(), 'no card', 5)
    s.press(PAD_RIGHT)
    s.wait(lambda: 'highlights TTT1 moves' in s.log(), 'no TTT1 card', 5)
    s.press(PAD_CROSS)
    s.wait(lambda: 'takes TTT1 moves' in s.log(), 'card not taken', 5)

def in_fight(s): return s.value(0x800ae204) == 8 and s.value(0x800ae224, 2) >= 6

def find(a):
    cid = NATIVES[a.native]
    s = L.Session(build=Path(a.build), slot=8, env={'TEKKEN3_NATIVE_MOVES': ''})
    try:
        to_arcade(s); pick_paul(s, cid)
        s.wait(lambda: in_fight(s) and s.value(ACTOR[0] + 0x54) != 0, 'the fight', 120)
        time.sleep(4)                                     # the round's intro
        def seq(inputs):
            seen = []
            life = s.value(ACTOR[0] + 0x3f6, 2)
            s.q(cmd='press', buttons=inputs[0], frames=3)
            t = time.time()
            if len(inputs) > 1:
                time.sleep(.12); s.q(cmd='press', buttons=inputs[1], frames=3)
            while time.time() - t < 1.6:
                r = s.value(ACTOR[0] + 0x54)
                if not seen or seen[-1] != r: seen.append(r)
                time.sleep(.02)
            time.sleep(1.2)
            if s.value(ACTOR[0] + 0x3f6, 2) < life: return None      # hit meanwhile: its records are not ours
            return [hex(x) for x in seen]
        out = dict(jab=[x for x in (seq([PAD_SQUARE]) for _ in range(6)) if x],
                   sidestep_then_1=[x for x in (seq([PAD_UP, PAD_SQUARE]) for _ in range(14)) if x])
        print(json.dumps(out, indent=1))
    finally: s.stop()

def watch(a):
    cid = NATIVES[a.native]
    s = L.Session(build=Path(a.build), slot=8, env={'TEKKEN3_NATIVE_MOVES': '', 'TEKKEN3_CPU_MOVESET': 'ttt1'})
    marks = {int(x, 16) for x in a.mark}
    try:
        to_arcade(s)
        for _ in range(40):
            if s.value(0x800ae204) == 11: break
            s.press(CROSS); time.sleep(.5)
        s.write(0x800add5e, cid, 2); s.write(0x800add9a, 0, 2)
        s.wait(lambda: in_fight(s) and s.value(ACTOR[1] + 0x54) != 0, 'the fight', 120)
        assert f'P2 {a.native.capitalize()} on the TTT1 moveset' in s.log(), 'the CPU is not on the TTT1 moves'
        life = s.value(ACTOR[0] + 0x3f6, 2)
        records, last, changes = collections.Counter(), None, 0
        running = s.game_until(a.seconds)
        while running():
            r = s.value(ACTOR[1] + 0x54)
            if r != last: records[r] += 1; last = r; changes += 1
            if s.value(ACTOR[0] + 0x3f6, 2) < life // 2: s.write(ACTOR[0] + 0x3f6, life, 2)
            time.sleep(.02)
        print(f'{changes} record changes, {len(records)} distinct records')
        for r, n in records.most_common():
            print(f'  {r:08x} {n}' + ('  <- searched' if r in marks else ''))
        print('searched records seen:', sorted(hex(r) for r in marks if r in records) or 'none')
    finally: s.stop()

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('find', 'watch'))
    ap.add_argument('--native', default='paul', choices=sorted(NATIVES))
    ap.add_argument('--seconds', type=int, default=240)
    ap.add_argument('--mark', nargs='*', default=[], help='records (hex) to look for')
    ap.add_argument('--build', default=str(L.ROOT / 'build-rel'))
    a = ap.parse_args()
    (find if a.mode == 'find' else watch)(a)
