#!/usr/bin/env python3
"""Lows pass under Yoshimitsu's Flea (u+1+2) on his TTT1 moves too, and under Unknown's in his style (B179, GH#221).

    python tools/test_b179_flea_low.py [--build build-b179-dbg] [--case all|<name>] [--exe <other exe>]
                                       [--delays 8,16,24,32] [--lows d3,d34] [--dummy hwoarang]

Practice, player 1 Yoshimitsu (or Unknown in his style) jumps on his sword
(u+1+2), the dummy (CONTROLLER, its pad on the debug server's port 2) plays a
low of id 0x10F N frames later. Both engines let such a low pass under a
fighter whose window kind (attributes bits 11..15) is the low crush - T3 12
(hit_contact_check 0x8004406C), TTT1 13 (hit_detect 0x800FB148) - and the
Flea's own attack, the blade, hits the attacker. Outcome per try, from the
moves played (+0xA0) and Practice's damage counter: 'hit' (player 1 left the
sword for a reaction, 0xD56: the bug, kind 13 read by T3), 'countered' (the
counter went up, player 1 still on the sword), 'none' (no contact: the low
came too late or too far, says nothing). The cases with Tekken 3 moves are
the reference, the others must match it.

Build: pad 2 needs the debug server's port 2 (PSX_DEBUG_TOOLS=ON), and the
build's mods/ttt1 the imported catalogue at import version 20 or later (or
retouched by tools/ttt1_retrofit_window_kinds.py: a relink stages the
workspace's packs again). Exit status 1 when a try was hit, 2 when a case
had no contact at all (nothing measured).
"""
import argparse, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_b73_stagger_guard as b73
import test_b90_cjm_throw_reversal as b90

b73.WORK = ROOT / 'out/b179'
ACTOR, STRIDE, DUMMY = b73.ACTOR, b73.STRIDE, b73.DUMMY
SQUARE, TRIANGLE, CROSS, CIRCLE = b73.SQUARE, b73.TRIANGLE, b73.CROSS, b73.CIRCLE
RIGHT, LEFT, DOWN, UP, NONE = b73.RIGHT, b73.LEFT, b73.DOWN, b73.UP, b73.NONE
b90.IDS.update({'yoshimitsu': 4, 'paul': 0, 'xiaoyu': 7, 'jin': 9, 'hwoarang': 6, 'king': 3, 'lei': 2, 'law': 1})

# The dummy's lows (its pad, facing left: back is RIGHT). d1 is a low jab of id 0x31F: it hits the Flea in T3 too.
LOWS = {'d4': DOWN & CIRCLE, 'd1': DOWN & SQUARE, 'd3': DOWN & CROSS, 'db4': DOWN & RIGHT & CIRCLE,
        'db3': DOWN & RIGHT & CROSS, 'd34': DOWN & CROSS & CIRCLE, 'df4': DOWN & LEFT & CIRCLE}

# Player 1's Flea: the rise and the stance on the sword, T3 records / TTT1 pack aliases.
FLEA = {0x455, 0x456, 0x2118, 0x2119}

# name: (moves, dummy, Unknown's style, lows, expected). The lows are those of
# id 0x10F that reach the fighter on the sword before its blade reaches them:
# Paul's d+3 and d+3+4 Yoshimitsu, Hwoarang's d+3 / d/b+3 and Jin's d/b+4
# Unknown, whose body is not his (Paul's never reach her).
CASES = {
    'yoshi_t3': ('t3', 'paul', None, 'd3,d34', 'countered'),
    'yoshi_t3_hwoarang': ('t3', 'hwoarang', None, 'd3,db3', 'countered'),
    'yoshi_ttt': ('card', 'paul', None, 'd3,d34', 'countered'),
    'unknown': ('t3', 'hwoarang', 'Yoshimitsu', 'd3,db3', 'countered'),
    'unknown_jin': ('t3', 'jin', 'Yoshimitsu', 'db4', 'countered'),
}


class Game(b90.Game):
    # The card's log line now names the line in lower case ('highlights ttt1 moves').
    def log(self): return super().log().replace('highlights ttt1 moves', 'highlights TTT1 moves')


def approach(g, reach):
    """Walks player 1 in (one held press: taps would dash), then savestate 1."""
    on_right = b73.x(g, 0) > b73.x(g, 1)
    g.q(cmd='set_input', buttons='ffff', port=2)
    g.write(DUMMY, bytes([0]))           # standing still while player 1 walks in (CONTROLLER mirrors him)
    g.q(cmd='set_input', buttons=f'{b73.mirror(RIGHT) if on_right else RIGHT:04x}')
    end = time.monotonic() + 20
    while time.monotonic() < end and b73.distance(g) > reach: time.sleep(.01)
    g.q(cmd='clear_input'); g.frames(40)
    g.write(DUMMY, bytes([8])); g.frames(5)
    print(f'distance {b73.distance(g):.0f}', flush=True)
    g.q(cmd='savestate', op='save', slot=1); time.sleep(.5)
    return on_right


def dump_move(g, label):
    """Player 1's current record (+0x54) and its cancel list, for the report."""
    mi = g.value(ACTOR + 0x54)
    rec = struct.unpack('<14I', g.read(mi, 56))
    print(f'{label}: move {g.value(ACTOR + 0xa0, 2):#x} record {mi:#x}', ' '.join(f'{w:08x}' for w in rec), flush=True)
    print('   limbs', g.read(rec[10], 4).hex(), flush=True)
    c = rec[3]
    for k in range(80):
        row = struct.unpack('<HBBHHBBBB', g.read(c + 12 * k, 12))
        print('   cancel', k, ' '.join(f'{w:x}' for w in row), flush=True)
        if row[0] == 0xc000: break


def attempt(g, delay, low, frames=110, dump=False):
    g.q(cmd='savestate', op='load', slot=1); time.sleep(.3)
    g.q(cmd='set_input', buttons='ffff', port=2)
    g.q(cmd='input_route_clear')
    for n, pad in [(4, UP & SQUARE & TRIANGLE), (frames, NONE)]:
        g.q(cmd='input_route_append', frames=n, buttons=pad)
    g.q(cmd='input_route_start')
    plan = [(delay, low), (delay + 4, NONE)]
    total0 = g.value(b73.TOTAL, 2)
    start, k, seen = g.frame(), 0, []
    while g.frame() - start < frames:
        f = g.frame() - start
        while k < len(plan) and f >= plan[k][0]:
            g.q(cmd='set_input', buttons=f'{plan[k][1]:04x}', port=2); k += 1
        v = g.read(ACTOR, STRIDE * 2)
        moves = tuple(struct.unpack_from('<h', v, p * STRIDE + 0xa0)[0] for p in (0, 1))
        kind = struct.unpack_from('<I', v, 0x60)[0] >> 11 & 31
        p2id = struct.unpack_from('<H', v, STRIDE + 0x64)[0]
        row = moves + (kind, p2id, g.value(b73.TOTAL, 2) - total0)
        if not seen or seen[-1][1:] != row: seen.append((f,) + row)
        if dump and f >= 30: dump_move(g, 'flea'); dump = False
        time.sleep(.002)
    g.q(cmd='set_input', buttons='ffff', port=2)
    # Hit: player 1 left the sword for another move (a reaction: 0xD56...)
    # once on it; the Flea itself lasts past the try. Countered: Practice's
    # damage counter (player 1's hits) went up.
    on_sword = [m1 for _, m1, *_ in seen]
    rise = next((i for i, m in enumerate(on_sword) if m in FLEA), None)
    left = rise is not None and any(m not in FLEA for m in on_sword[rise:])
    outcome = 'hit' if left else 'countered' if seen[-1][-1] > 0 else 'none'
    return outcome, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-b179-dbg')
    ap.add_argument('--exe')
    ap.add_argument('--case', default='all', choices=['all'] + list(CASES))
    ap.add_argument('--delays', default='8,16,24,32')
    ap.add_argument('--lows', help='the lows instead of the case lows')
    ap.add_argument('--range', type=int, default=900)
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--dummy', help="the dummy instead of the case's")
    a = ap.parse_args()
    failed = unmeasured = False
    for name in (list(CASES) if a.case == 'all' else [a.case]):
        moves, victim, unknown, lows, expected = CASES[name]
        victim, lows = a.dummy or victim, a.lows or lows
        # b90.to_practice picks Anna; Yoshimitsu here.
        b90.IDS['anna'] = 4
        g = Game((ROOT / a.build).resolve(), f'b179-{name}', a.exe, moves)
        try:
            b90.to_practice(g, moves, victim, unknown)
            if unknown:                     # her style first: each switch can move her away
                b90.unknown_style(g, unknown); time.sleep(1)
            on_right = approach(g, a.range)
            if a.dump: attempt(g, 200, NONE, dump=True)
            measured = False
            for low in lows.split(','):
                pad = LOWS[low] if not on_right else b73.mirror(LOWS[low])
                for delay in (int(d) for d in a.delays.split(',')):
                    outcome, seen = attempt(g, delay, pad)
                    ok = outcome == expected
                    print(f'{name} {low} +{delay}: {outcome}, expected {expected} -> '
                          f'{"ok" if ok else "no contact" if outcome == "none" else "FAIL"}', flush=True)
                    print('   ', ' '.join(f'{f}:{m1:x}/{m2:x} w{w} id{i:x} [{d}]' for f, m1, m2, w, i, d in seen), flush=True)
                    measured |= outcome != 'none'
                    if outcome == 'hit': failed = True
            if not measured: unmeasured = True
        finally:
            g.stop()
    sys.exit(1 if failed else 2 if unmeasured else 0)


if __name__ == '__main__': main()
