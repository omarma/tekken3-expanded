#!/usr/bin/env python3
"""Yoshimitsu's Flash holds the blade up as in TTT1 (GH#122).

    python tools/test_yoshimitsu_flash.py --build build-rel-lite [--fighter yoshimitsu|unknown] [--trace] [--tag NAME]

The Flash is the pack's record 325 (TTT1 0x80054764), active frames 4-12,
hit limbs 22 (the sword's tip, marker TTT1_PACK_BLADE_TIP) swept and 10 -> 22
(hand to tip). From the guard, b+1+4 together plays b+1 (record 206, TTT1
0x80043AA8, a hand cut active on frame 17); the Flash comes from 206 by 4
in its first frames, or from b held (record 26) by b+1+4, in TTT1 as here.
In the arcade (MAME, Yoshimitsu against a still Jin pushed back to about
1000) the blade stands straight up in front of him, the tip about 730
above the hand, and it touches no standing opponent; b+1 from there hits.

Native Yoshimitsu on his TTT1 moves (TEKKEN3_NATIVE_MOVES=1, Arcade
selector) and Unknown on his moves (TEKKEN3_TETSUJIN_MOVESET=yoshimitsu,
Tag page) walk up to a still Jin, then from a saved state: b+1, which must
hit; then b+1 and 4, which must play the Flash with player 1's hand-to-tip
capsule (actor +0x1AC + 24) standing up from the hand (tip at least 500
higher, at most 300 to the side) and miss Jin. Before the fix the native's
blade lay flat to the side (his T3 hand bone is turned a quarter turn from
Unknown's) and the Flash hit Jin against him for 31. Capsules are read
while the game runs: a sample written half-way is skipped (the hand and the
tip at the same point). --trace prints every sample of the Flash.
"""
import argparse, os, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T
import test_guest_accessories as A
from test_yoshimitsu_win_sparks import Game

T.WORK = ROOT / 'workspace/yoshimitsu-flash'
YOSHIMITSU, JIN = 4, 9
ACTOR, STRIDE, LIFE = T.ACTOR, T.STRIDE, T.LIFE
OPPONENT, OPPONENT_COSTUME = 0x800add5e, 0x800add9a
ROUND_CLOCK = 0x800adbcc
B_PLUS_1, FLASH = 206, 325
P = T.pad
INPUTS = {B_PLUS_1: [(3, P(T.L, T.SQ)), (90, 0xffff)],
          FLASH: [(3, P(T.L, T.SQ)), (3, P(T.CI)), (90, 0xffff)]}


def word(b, o): return struct.unpack_from('<I', b, o)[0]


def cursor_to(g, cid):
    for n in range(60):
        if g.value(T.CURSOR_CHAR) == cid: return
        before = g.value(T.CURSOR_CHAR)
        g.q(cmd='press', buttons=T.RIGHT, frames=4); time.sleep(.35)
        if n % 12 == 11 or g.value(T.CURSOR_CHAR) == before:
            g.q(cmd='press', buttons=0xffbf, frames=4); time.sleep(.35)     # down
    raise AssertionError(f'P1 cursor did not reach character {cid}')


def start_native(g):
    """Arcade selector, Square on Yoshimitsu; Jin forced at the loading
    screen (state 11, a fifth of a second), read without pauses."""
    T.to_selector(g)
    cursor_to(g, YOSHIMITSU)
    end, pressed = time.monotonic() + 60, 0
    while (state := g.value(T.STATE)) != 11:
        if state == 8 and g.value(T.PHASE, 2) >= 3: raise AssertionError('the fight started before the loading screen was seen')
        if time.monotonic() > end: raise AssertionError('loading screen not reached')
        if state == 9 and time.monotonic() - pressed > 1:
            g.q(cmd='press', buttons=T.SQUARE, frames=12); pressed = time.monotonic()
    g.write(OPPONENT, JIN, 2); g.write(OPPONENT_COSTUME, 0, 2)
    g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8, 'round did not start', 150)
    assert T.actor(g, 0)[2] == YOSHIMITSU and T.actor(g, 1)[2] == JIN, 'not Yoshimitsu against Jin'
    assert 'P1 Yoshimitsu on the TTT1 moveset' in g.log(), 'Yoshimitsu is not on his TTT1 moves'


def start_unknown(g, build):
    catalogue = [l.split()[0] for l in (build / 'mods/ttt1/guests.txt').read_text().splitlines() if l.split()]
    A.to_tag_page(g, len(catalogue))
    A.fight(g, catalogue.index('unknown'), len(catalogue), 1)


def records_base(g):
    found = re.findall(r'installed P1 alias table, original=\w+ custom=\w+ records=([0-9A-F]{8})', g.log())
    assert found, 'no alias table installed for player 1'
    return int(found[-1], 16)


def play(g, base, move, trace):
    """From the saved state: the move's input, then samples until it ends.
    Returns the records played, whether Jin was hit, and the Flash's
    hand-to-tip capsules over its active frames."""
    g.q(cmd='savestate', op='load', slot=9); time.sleep(.3)
    g.write(ROUND_CLOCK, 0x7000, 2)
    life, jin = g.value(ACTOR + STRIDE + LIFE, 2), g.value(ACTOR + STRIDE + 0x54)
    T.route(g, INPUTS[move])
    # Player 1's record, frame and capsules only (one short read, many per
    # frame); Jin's record and life every few reads.
    span = 0x1ac + 48 - 0x54
    played, blades, hit, f0, n = [], [], False, g.q(cmd='frame')['frame'], 0
    while True:
        b = g.read(ACTOR + 0x54, span)
        record, frame = word(b, 0), struct.unpack_from('<h', b, 4)[0]
        index = (record - base) // 56 if base <= record < base + 2048 * 56 and (record - base) % 56 == 0 else -1
        if not played or played[-1] != index: played.append(index)
        if index == FLASH and 4 <= frame <= 12:
            hand, tip = (struct.unpack_from('<3i', b, 0x1ac + 24 + 12 * k - 0x54) for k in (0, 1))
            if hand != tip and (frame, hand, tip) not in blades:
                if trace: print(f'    frame {frame:2d} hand {hand} tip {tip}')
                blades.append((frame, hand, tip))
        n += 1
        if n % 8 == 0:
            j = g.read(ACTOR + STRIDE + 0x54, LIFE + 2 - 0x54)
            hit = hit or word(j, 0) != jin or struct.unpack_from('<h', j, len(j) - 2)[0] < life
            if g.q(cmd='frame')['frame'] >= f0 + 80: return played, hit, blades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True)
    ap.add_argument('--fighter', default='yoshimitsu', choices=('yoshimitsu', 'unknown'))
    ap.add_argument('--walk', type=int, default=40, help='frames of forward walk up to Jin')
    ap.add_argument('--trace', action='store_true')
    ap.add_argument('--tag', default=None)
    a = ap.parse_args()
    T.WORK.mkdir(parents=True, exist_ok=True)
    build = Path(a.build).resolve()
    guest = a.fighter == 'unknown'
    env = {'TEKKEN3_TETSUJIN_MOVESET': 'yoshimitsu'} if guest else {'TEKKEN3_NATIVE_MOVES': '1'}
    g = Game(build, a.tag or f'flash-{a.fighter}', env)
    try:
        if guest: start_unknown(g, build)
        else: start_native(g)
        g.write(ACTOR + STRIDE + 0xc5, 0, 1)            # Jin stands still
        clock = g.value(ROUND_CLOCK, 2)                 # past ROUND 1 / READY: the clock runs
        g.wait(lambda: g.value(ROUND_CLOCK, 2) != clock, 'the round clock never ran', 30)
        time.sleep(.5)
        base = records_base(g)
        T.route(g, [(a.walk, P(T.R)), (20, 0xffff)]); time.sleep((a.walk + 25) / 60 + .3)
        g.q(cmd='savestate', op='save', slot=9)
        played, hit, _ = play(g, base, B_PLUS_1, False)
        print(f'{a.fighter}: b+1 plays {played}, Jin ' + ('hit' if hit else 'not hit'))
        if B_PLUS_1 not in played: raise SystemExit('FAIL: b+1 did not play record 206')
        if not hit: raise SystemExit('FAIL: b+1 missed Jin: not in range')
        # Few samples come out whole (2 or 3 a Flash): again until one does.
        for _ in range(3):
            played, hit, blades = play(g, base, FLASH, a.trace)
            if blades or hit: break
    finally:
        if g.process.poll() is None: g.q(cmd='clear_input')
        g.stop()
    print(f'{a.fighter}: b+1, 4 plays {played}, Jin ' + ('hit' if hit else 'not hit') +
          f', {len(blades)} samples of the blade in frames 4-12')
    if FLASH not in played: raise SystemExit('FAIL: b+1, 4 did not play the Flash (record 325)')
    if not blades: raise SystemExit('FAIL: no capsule of the Flash sampled in its active frames')
    for frame, hand, tip in blades:
        up, side = hand[1] - tip[1], ((tip[0] - hand[0]) ** 2 + (tip[2] - hand[2]) ** 2) ** .5
        print(f'  frame {frame:2d}: tip {up} above the hand, {side:.0f} to the side')
        if up < 500 or side > 300: raise SystemExit(f'FAIL: the blade does not stand up from the hand at frame {frame}')
    if hit: raise SystemExit('FAIL: the Flash hit Jin standing against Yoshimitsu (TTT1 misses him)')
    print(f'PASS: {a.fighter}: the Flash holds the blade up and misses a standing Jin, as in TTT1')


if __name__ == '__main__':
    main()
