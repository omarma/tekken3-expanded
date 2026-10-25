#!/usr/bin/env python3
"""Yoshimitsu's sword breaks the ball in Tekken Ball (B92, GH#146).

    python tools/test_ball_sword.py [--fighter yoshimitsu|unknown|<native>] [--moves t3|ttt1]
                                    [--expect broken|shot] [--build build-rel-lite] [--memcard-dir saves]

The check (the bug back: Unknown on Yoshimitsu's moves sends the ball as a
plain unblockable instead of breaking it):
    --fighter unknown --expect broken
    --fighter yoshimitsu --moves ttt1 --expect broken
    --fighter yoshimitsu --moves t3 --expect broken      (the reference)
    --fighter jin --moves ttt1 --expect shot             (no sword: untouched)

T3's ball (ovl3 ball_move, 0x800B1734) breaks on an unblockable hit (move
id 0x607 or 0x706, actor +0x64) from a fighter whose moves key (+0x16) is
4, Yoshimitsu's, unless it is the throw 0x181 or an effect capsule; any
other unblockable sends it homing at the opponent. Every guest fights with
key 23, so Unknown on Yoshimitsu's moves sent it.

Boots a private copy of the build (tools/test_ball_backdash.py: software,
headless, x1, copy of the memory card), takes Tekken Ball, player 1 the
fighter asked for (a guest at the loading screen; Unknown starts on
Yoshimitsu's moves through TEKKEN3_TETSUJIN_MOVESET). While the ball floats
at the serve (state 9, it keeps the x it is given), the fight is saved;
each trial reloads it, puts the ball in front of player 1 and starts one of
its unblockable moves through the pending transition (+0x1A0), then reads
the ball at the first contact: state 7 broken, state 2 homing a shot.
Distances are tried from near to far until one connects.
"""
import argparse, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_ball_backdash as bench
from test_ball_backdash import ACTOR, STRIDE, SCREEN, PHASE, LOADING_P1, Game, to_mode, pick, signed, guest_id

BALL_STATE = 0x800add74                      # BallState pointer (ovl3 ball_frame)
SLOT = 10
UNBLOCKABLE = (0x607, 0x706)
DISTANCES = (800, 1000, 1200, 1400, 1600, 1800, 2000, 2200)
CONTACTS, MOVES = 6, 40                      # contacts measured, moves tried, then stop
SWORD_SITE, SWORD_STOCK = 0x800b1734, 0x86430016      # lh v1, 0x16(s2): the key test


def unblockables(g):
    """Player 1's records whose move id is an unblockable, by alias, from its
    alias table (0x800ADC20 +12; TTT1 moves are aliases 8192 + i)."""
    table = g.value(g.value(0x800adc20) + 12)
    words = g.read(table, 0x4000 * 4)
    seen, found = set(), []
    for alias in range(0x4000):
        record = struct.unpack_from('<I', words, alias * 4)[0]
        if record < 0x80000000 or record in seen: continue
        seen.add(record)
        try: rec = g.read(record, 0x38)
        except RuntimeError: continue
        move_id, damage = struct.unpack_from('<H', rec, 8)[0], struct.unpack_from('<h', rec, 0x14)[0]
        if move_id in UNBLOCKABLE and damage > 0 and rec[0x2d]: found.append((alias, record, move_id, damage))
    return found


def trial(g, ball, alias, record, distance):
    """One move from the saved serve with the ball `distance` in front of
    player 1. Returns (state, homing, move id at contact) or None."""
    g.q(cmd='savestate', op='load', slot=SLOT)
    g.wait_frames(2)
    x1, x2 = signed(g.value(ACTOR)), signed(g.value(ACTOR + STRIDE))
    x = x1 + (distance if x2 > x1 else -distance)
    z = signed(g.value(ACTOR + 8))
    pending = struct.pack('<HHI', alias, g.value(ACTOR + 0x1a2, 2), record)
    g.q(cmd='write_ram', addr=f'{ball + 0x68:08x}', bytes=struct.pack('<i', x).hex())
    g.q(cmd='write_ram', addr=f'{ball + 0x70:08x}', bytes=struct.pack('<i', z).hex())
    g.q(cmd='write_ram', addr=f'{ACTOR + 0x1a0:08x}', bytes=pending.hex())   # one write: one frame
    end = g.frame() + 120
    while g.frame() < end:
        b = g.read(ball, 0xb4)
        state = struct.unpack_from('<h', b, 0)[0]
        if state not in (9,):
            return state, struct.unpack_from('<h', b, 0xb2)[0], g.value(ACTOR + 0x64, 2)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fighter', default='unknown')
    ap.add_argument('--moves', default='t3', choices=('t3', 'ttt1'), help='a native\'s moves (TEKKEN3_NATIVE_MOVES)')
    ap.add_argument('--expect', choices=('broken', 'shot'), help='broken: one sword contact at least breaks the ball; shot: none does')
    ap.add_argument('--env', action='append', default=[], help='KEY=VALUE for the game (repeatable)')
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'))
    a = ap.parse_args()
    build = Path(a.build)
    assert (build / 'mods/ttt1/guests.txt').is_file(), f'no TTT1 catalogue in {build}/mods/ttt1'
    env = {'TEKKEN3_NATIVE_MOVES': '1' if a.moves == 'ttt1' else '0'}
    if a.fighter == 'unknown': env['TEKKEN3_TETSUJIN_MOVESET'] = 'Yoshimitsu'
    env.update(e.split('=', 1) for e in a.env)
    g = Game(build, Path(a.memcard_dir), env)
    try:
        to_mode(g, 'ball')
        native = a.fighter if a.fighter in bench.IDS else 'jin'
        pick(g, 'ball', native)
        if a.fighter not in bench.IDS:
            gid = guest_id(build, a.fighter)
            for _ in range(30): g.write(LOADING_P1, gid, 2); time.sleep(.01)
        g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6 and g.value(ACTOR + 0x54) != 0,
               'the fight never started', 90)
        ball = g.value(BALL_STATE) if g.value(BALL_STATE) >= 0x80000000 else BALL_STATE
        g.wait(lambda: g.value(ball, 2) == 9, 'the ball never floated at the serve', 30)
        g.wait(lambda: g.value(ACTOR + 0x1a4) == 0, 'player 1 never settled', 5)
        g.q(cmd='turbo', enabled=0)
        g.q(cmd='savestate', op='save', slot=SLOT)
        key, site = g.value(ACTOR + 0x16, 2), g.value(SWORD_SITE)
        moves = unblockables(g)
        print(f'B92 {a.fighter} moves={a.moves} key {key} ball {ball:#x} '
              f'key test {"stock" if site == SWORD_STOCK else f"patched, mask {g.value(SWORD_SITE + 4) & 0xffff}"} '
              f'unblockables {[(al, f"{mid:#x}", d) for al, _, mid, d in moves]}', flush=True)
        assert moves, 'no unblockable move found for player 1'
        results = []
        for alias, record, move_id, damage in moves[:MOVES]:
            for d in DISTANCES:
                r = trial(g, ball, alias, record, d)
                if r is None: continue
                state, homing, at = r
                # Bounced off the body (state 2, not homing), or another
                # move by then: the strike never reached it, farther.
                if at not in UNBLOCKABLE or not (state == 7 or (state == 2 and homing)): continue
                outcome = 'broken' if state == 7 else 'shot'
                print(f'  alias {alias} id {move_id:#x} damage {damage}: ball at {d} -> {outcome} '
                      f'(state {state}, homing {homing})', flush=True)
                results.append(outcome)
                break
            else: print(f'  alias {alias} id {move_id:#x}: no contact', flush=True)
            if len(results) >= CONTACTS: break
        print(f'RESULT {a.fighter} {a.moves}: {results}', flush=True)
        assert results, 'no unblockable contact with the ball'
        # T3's own Yoshimitsu sends some (0x181, effect capsules): broken =
        # at least one sword contact breaks it, shot = none does.
        if a.expect == 'broken': assert 'broken' in results, f'the sword never broke the ball: {results}'
        if a.expect == 'shot': assert 'broken' not in results, f'the ball broke: {results}'
        for line in g.log().splitlines():
            if line.startswith('B92') or 'draws' in line or 'starts on' in line or 'Native moves' in line: print(line)
    except BaseException:
        print(g.log()[-3000:]); raise
    finally: g.stop()


if __name__ == '__main__':
    main()
