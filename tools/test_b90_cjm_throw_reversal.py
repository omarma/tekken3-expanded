#!/usr/bin/env python3
"""Anna's Chaos Judgement (TTT1 moves) parries a throw whoever throws (B90, GH#144).

    python tools/test_b90_cjm_throw_reversal.py [--build build-b90-dbg] [--case all|<name>] [--exe <other exe>]

Practice, player 1 in Anna's Chaos Judgement (back + 4: records 303 / 304 of
her pack, aliases 0x539 / 0x53A), the dummy (CONTROLLER, its pad on the debug
server's port 2) throws her 10 and 14 frames later. TTT1 gives the stance the
rule "on a hit by a clip of group 0x19C (the standard throws 1+3 / 2+4) ->
854 (alias 0xF11)": she kicks the thrower away (25 damage), the pair taken by
her side (player 1's throw flag +0x74 > 0). Thrown, player 1's flag goes
negative instead.

  nina_t3_13 / nina_t3_24  Nina on her Tekken 3 moves throws (1+3 / 2+4):
                           parried. The bug: thrown - Tekken 3 has no group
                           0x19C, and player 1's on-hit rules were read against
                           player 1 itself (the stale +0x22, B90).
  anna_ttt                 every native on its TTT1 moves (TEKKEN3_NATIVE_MOVES=1),
                           Anna throws Anna: parried (player 1's side of the bug).
  unknown                  player 1 Unknown, switched to Anna's style (L1): parried.
  stand                    Anna standing, no stance: thrown.
  anna_t3                  every native on its Tekken 3 moves: Anna's own T3
                           stance (0xF42) parries no throw, thrown as before.

Build: pad 2 needs the debug server's port 2 (PSX_DEBUG_TOOLS=ON), and the
build's mods/ttt1 the imported catalogue (a ninja removes a junction there).
Exit status 1 when a case's outcome is wrong, 2 when a throw never reached
player 1 in the stance, three times (nothing measured).
"""
import argparse, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_b73_stagger_guard as b73

b73.WORK = ROOT / 'out/b90'
STATE, CURSOR_CHAR, GRID, LINE, VICTIM = b73.STATE, b73.CURSOR_CHAR, b73.GRID, b73.LINE, b73.VICTIM
ACTOR, STRIDE, TOTAL, DUMMY = b73.ACTOR, b73.STRIDE, b73.TOTAL, b73.DUMMY
START, CROSS, SQUARE, TRIANGLE, CIRCLE = b73.START, b73.CROSS, b73.SQUARE, b73.TRIANGLE, b73.CIRCLE
RIGHT, LEFT, DOWN, NONE, L1 = b73.RIGHT, b73.LEFT, b73.DOWN, b73.NONE, 0xfbff
IDS = {'anna': 18, 'nina': 5}
GUEST_ID = 23                     # the guests' IDs follow mods/ttt1/guests.txt from 23
THROWS = {'13': SQUARE & CROSS, '24': TRIANGLE & CIRCLE}

# name: (moves, dummy, Unknown's style, throw, stance, expected)
CASES = {
    'nina_t3_13': ('card', 'nina', None, '13', True, 'parried'),
    'nina_t3_24': ('card', 'nina', None, '24', True, 'parried'),
    'stand': ('card', 'nina', None, '13', False, 'thrown'),
    'anna_ttt': ('ttt1', 'anna', None, '13', True, 'parried'),
    'unknown': ('card', 'nina', 'Anna', '13', True, 'parried'),
    'anna_t3': ('t3', 'nina', None, '13', True, 'thrown'),
}


class Game(b73.Game):
    def __init__(self, build, tag, exe, moves):
        forced = {'ttt1': '1', 't3': '0'}.get(moves)     # TEKKEN3_NATIVE_MOVES, which Game leaves out
        popen = b73.subprocess.Popen
        def started(*args, **kw):
            if forced and 'env' in kw: kw['env'] = dict(kw['env'], TEKKEN3_NATIVE_MOVES=forced)
            return popen(*args, **kw)
        b73.subprocess.Popen = started
        try: super().__init__(build, tag, exe=exe)
        finally: b73.subprocess.Popen = popen


def to_practice(g, moves, victim, unknown):
    """Practice, player 1 on Anna: her TTT1 MOVESET card ('card'), or no card
    with every native on one moveset ('ttt1' / 't3'). The dummy's character
    (and Unknown for player 1) written while the fight loads, then CONTROLLER."""
    g.q(cmd='turbo', enabled=1)
    g.wait(lambda: g.value(STATE) == 4, 'mode menu', 240, lambda: g.press(START))
    g.q(cmd='turbo', enabled=0); time.sleep(1)
    g.write(LINE, bytes([b73.menu_line(g, b73.PRACTICE)]))
    g.wait(lambda: g.value(STATE) == 9 and g.value(GRID) == 21, 'selector', 90,
           lambda: (g.press(CROSS), time.sleep(.4)))
    time.sleep(1.5)
    for k in range(48):
        if g.value(CURSOR_CHAR) == IDS['anna']: break
        before = g.value(CURSOR_CHAR)
        g.press(RIGHT)
        if k % 12 == 11 or g.value(CURSOR_CHAR) == before: g.press(DOWN)
    assert g.value(CURSOR_CHAR) == IDS['anna'], ('cursor', g.value(CURSOR_CHAR))
    if moves == 'card':
        g.wait(lambda: 'P1 opens the MOVESET card' in g.log(), 'no MOVESET card', 10,
               lambda: (g.press(SQUARE), time.sleep(1)))
        g.press(RIGHT)
        g.wait(lambda: 'P1 highlights TTT1 moves' in g.log(), 'no TTT1 line', 5)
        g.press(CROSS)
        g.wait(lambda: 'P1 takes' in g.log(), 'card not taken', 5)
    else:
        g.press(SQUARE)
    time.sleep(1.5)
    keys = [l.split()[0] for l in (g.run / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    end, last, written = time.monotonic() + 60, 0, False
    while time.monotonic() < end:
        st = g.value(STATE)
        if st == 8: break
        # Once player 1's pad has picked the dummy (its card's Cross, or a
        # plain Cross without a card), the loading choices are written on
        # every pass: the loading screen (state 11) is too brief to catch.
        if 'P2 takes' in g.log() or (moves != 'card' and last) or st in (10, 11):
            g.write(VICTIM, struct.pack('<H', IDS[victim])); g.write(0x800add9a, b'\0\0')
            if unknown:
                g.write(0x800add5c, struct.pack('<H', GUEST_ID + keys.index('unknown'))); g.write(0x800add98, b'\0\0')
            written = True
        if st == 9 and time.monotonic() - last > 1:
            g.press(CROSS if moves != 'card' or 'P2 opens the MOVESET card' in g.log() else SQUARE)
            last = time.monotonic()
        time.sleep(.01)
    assert written, 'the dummy was never written'
    g.wait(lambda: g.value(STATE) == 8 and g.value(0x800ae224, 2) >= 6, 'fight', 120)
    for _ in range(10):
        time.sleep(1.5); g.press(CROSS); time.sleep(1.5)
        before = b73.distance(g)
        g.q(cmd='set_input', buttons=f'{RIGHT if b73.x(g, 0) < b73.x(g, 1) else LEFT:04x}'); g.frames(20)
        walking = g.value(ACTOR + 0xa0, 2) != 3
        g.q(cmd='clear_input')
        if walking and b73.distance(g) < before - 30: break
    else: raise AssertionError('player 1 never walked')
    time.sleep(1)
    g.write(DUMMY, bytes([8]))


def unknown_style(g, style):
    """L1 until player 1's Unknown switches to that style (each L1 takes another at random)."""
    for _ in range(80):
        switches = [l for l in g.log().splitlines() if 'P1 Unknown switches to' in l]
        if switches and f'switches to {style} ' in switches[-1]: return
        g.q(cmd='input_route_clear')
        g.q(cmd='input_route_append', frames=2, buttons=L1); g.q(cmd='input_route_append', frames=40, buttons=NONE)
        g.q(cmd='input_route_start'); time.sleep(1.2)
    raise AssertionError(f'Unknown never switched to {style}')


# Records 303 (16 frames) then 304 (20, its rules from frame 1) carry the rule;
# 304 ends on 305 (no rule, +0xA0 still 0x2130), and a throw landing there
# throws her, in TTT1's data too. A contact past this many frames after 303
# says nothing.
STANCE, STANCE_FRAMES = 0x212f, 34


def attempt(g, back, stance, throw, delay):
    """'parried', 'thrown', 'late' (thrown, out of the stance) or None (the
    throw never reached player 1), and the timeline."""
    g.q(cmd='savestate', op='load', slot=1); time.sleep(.3)
    g.q(cmd='set_input', buttons='ffff', port=2)
    total0 = g.value(TOTAL, 2)
    g.q(cmd='input_route_clear')
    for n, pad in ([(4, back), (4, back & CIRCLE), (120, NONE)] if stance else [(128, NONE)]):
        g.q(cmd='input_route_append', frames=n, buttons=pad)
    g.q(cmd='input_route_start')
    plan = [(delay, THROWS[throw]), (delay + 4, NONE)]
    start, k, seen, outcome, entered = g.frame(), 0, [], None, None
    while g.frame() - start < 140:
        f = g.frame() - start
        while k < len(plan) and f >= plan[k][0]:
            g.q(cmd='set_input', buttons=f'{plan[k][1]:04x}', port=2); k += 1
        v = g.read(ACTOR, STRIDE * 2)
        moves = tuple(struct.unpack_from('<H', v, p * STRIDE + 0xa0)[0] for p in (0, 1))
        flag = struct.unpack_from('<h', v, 0x74)[0]
        row = moves + (flag, g.value(TOTAL, 2) - total0)
        if not seen or seen[-1][1:] != row: seen.append((f,) + row)
        if entered is None and moves[0] == STANCE: entered = f
        if outcome is None and flag < 0:
            outcome = 'late' if stance and (entered is None or f - entered > STANCE_FRAMES) else 'thrown'
        if outcome is None and flag > 0: outcome = 'parried'
        time.sleep(.002)
    g.q(cmd='set_input', buttons='ffff', port=2)
    if outcome == 'parried' and seen[-1][4] <= 0: outcome = 'parried, no damage'
    return outcome, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-b90-dbg')
    ap.add_argument('--exe')
    ap.add_argument('--case', default='all', choices=['all'] + list(CASES))
    ap.add_argument('--delays', default='10,14')
    a = ap.parse_args()
    wanted = list(CASES) if a.case == 'all' else [a.case]
    setups = {}
    for name in wanted: setups.setdefault(CASES[name][:3], []).append(name)
    failed = unmeasured = False
    for (moves, victim, unknown), names in setups.items():
        g = Game((ROOT / a.build).resolve(), f'b90-{names[0]}', a.exe, moves)
        try:
            to_practice(g, moves, victim, unknown)
            on_right = b73.approach(g, 700)
            if unknown:
                unknown_style(g, unknown)
                for _ in range(4):          # her switches can leave her far away
                    time.sleep(1); on_right = b73.approach(g, 700)
                    if b73.distance(g) < 1400: break
            back = RIGHT if on_right else LEFT
            for name in names:
                _, _, _, throw, stance, expected = CASES[name]
                for delay in (int(d) for d in a.delays.split(',')):
                    for _ in range(3):
                        outcome, seen = attempt(g, back, stance, throw, delay)
                        if outcome == 'late' and expected == 'thrown': outcome = 'thrown'
                        if outcome and outcome != 'late': break
                    if outcome == 'late': outcome = None
                    ok = outcome == expected
                    print(f'{name} +{delay}: {outcome or "no throw"}, expected {expected} -> '
                          f'{"ok" if ok else "FAIL" if outcome else "unmeasured"}', flush=True)
                    print('   ', ' '.join(f'{f}:{m1:x}/{m2:x} t{t}[{d}]' for f, m1, m2, t, d in seen), flush=True)
                    if not outcome: unmeasured = True
                    elif not ok: failed = True
        finally:
            g.stop()
    sys.exit(1 if failed else 2 if unmeasured else 0)


if __name__ == '__main__': main()
