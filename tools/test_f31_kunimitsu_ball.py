#!/usr/bin/env python3
"""Kunimitsu's blade breaks the ball in Tekken Ball, as Yoshimitsu's sword (F31, GH#195).

    python tools/test_f31_kunimitsu_ball.py --build build-rel-lite
        [--case kunimitsu kunimitsu-cpu unknown tetsujin yoshimitsu jin] [--memcard-dir saves]

T3's ball (ovl3 ball_move, 0x800B1734, t3-ps1 src/ovl3_ball/800B065C.c)
breaks on an unblockable hit (move id +0x64 0x607 or 0x706) by moves key 4,
Yoshimitsu's, unless it is the throw 0x181 or an effect capsule; any other
unblockable sends it homing at the opponent. B92 rewrote that test into a mask
per player (tekken3_ttt1_ball_sword_tick); F31 sets the bit for Kunimitsu's
TTT1 moves too (moveset 26). Before: Kunimitsu's unblockables (Deadly Stab,
Deadly Slice, Heaven Divide...) only sent homing shots.

Cases, each from a cold start (tools/test_ball_sword.py's bench: private copy
of the build, software, headless, a copy of the memory card), Tekken Ball,
the hitter's unblockables tried from the saved serve with the ball in front
of it until 6 of them touch the ball:
    kunimitsu      player 1 Kunimitsu                                   broken
    kunimitsu-cpu  player 2 (the CPU) Kunimitsu, player 1 Jin            broken
    unknown        Unknown on Kunimitsu's moves (TEKKEN3_TETSUJIN_MOVESET) broken
    tetsujin       Tetsujin drawing Kunimitsu's moves                    broken
    yoshimitsu     T3's Yoshimitsu, the reference                        broken
    jin            a native without a blade                              shot, key test untouched
"broken" = at least one contact breaks the ball (T3's Yoshimitsu sends a few:
the throw 0x181, effect capsules); "shot" = none does.
"""
import argparse, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_ball_backdash as bench
from test_ball_backdash import ACTOR, STRIDE, SCREEN, PHASE, LOADING_P1, Game, to_mode, pick, signed, guest_id
from test_ball_sword import BALL_STATE, SLOT, UNBLOCKABLE, DISTANCES, SWORD_SITE, SWORD_STOCK

CPU_FIGHTER, CPU_COSTUME = 0x800add5e, 0x800add9a
CONTACTS, MOVES = 6, 40
# case: (player 1, player 2 written at loading or None, hitter, env, expected)
CASES = {
    'kunimitsu':     ('kunimitsu', None, 0, {}, 'broken'),
    'kunimitsu-cpu': ('jin', 'kunimitsu', 1, {}, 'broken'),
    'unknown':       ('unknown', None, 0, {'TEKKEN3_TETSUJIN_MOVESET': 'Kunimitsu'}, 'broken'),
    'tetsujin':      ('tetsujin', None, 0, {'TEKKEN3_TETSUJIN_MOVESET': 'Kunimitsu'}, 'broken'),
    'yoshimitsu':    ('yoshimitsu', None, 0, {}, 'broken'),
    'jin':           ('jin', None, 0, {}, 'shot'),
}


def unblockables(g, player):
    """The player's records whose move id is an unblockable, by alias, from
    its alias table (0x800ADC20 + 4 * player, +12; TTT1 moves are 8192 + i)."""
    table = g.value(g.value(0x800adc20 + 4 * player) + 12)
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


def trial(g, ball, player, alias, record, distance):
    """One move by `player` from the saved serve with the ball `distance` in
    front of it. Returns (state, homing, move id at contact) or None."""
    g.q(cmd='savestate', op='load', slot=SLOT)
    g.wait_frames(2)
    me, other = ACTOR + player * STRIDE, ACTOR + (1 - player) * STRIDE
    x1, x2 = signed(g.value(me)), signed(g.value(other))
    x = x1 + (distance if x2 > x1 else -distance)
    z = signed(g.value(me + 8))
    pending = struct.pack('<HHI', alias, g.value(me + 0x1a2, 2), record)
    g.q(cmd='write_ram', addr=f'{ball + 0x68:08x}', bytes=struct.pack('<i', x).hex())
    g.q(cmd='write_ram', addr=f'{ball + 0x70:08x}', bytes=struct.pack('<i', z).hex())
    g.q(cmd='write_ram', addr=f'{me + 0x1a0:08x}', bytes=pending.hex())   # one write: one frame
    end = g.frame() + 120
    while g.frame() < end:
        b = g.read(ball, 0xb4)
        state = struct.unpack_from('<h', b, 0)[0]
        if state != 9:
            return state, struct.unpack_from('<h', b, 0xb2)[0], g.value(me + 0x64, 2)
    return None


def run(build, memcards, case):
    p1, p2, hitter, env, expect = CASES[case]
    env = dict(env, TEKKEN3_NATIVE_MOVES='0')
    g = Game(build, memcards, env)
    try:
        to_mode(g, 'ball')
        pick(g, 'ball', p1 if p1 in bench.IDS else 'jin')
        p1_id = None if p1 in bench.IDS else guest_id(build, p1)
        p2_id = None if p2 is None else guest_id(build, p2)
        for _ in range(30):
            if p1_id is not None: g.write(LOADING_P1, p1_id, 2)
            if p2_id is not None: g.write(CPU_FIGHTER, p2_id, 2); g.write(CPU_COSTUME, 0, 2)
            time.sleep(.01)
        g.wait(lambda: g.value(SCREEN) == 8 and g.value(PHASE, 2) >= 6 and g.value(ACTOR + 0x54) != 0,
               'the fight never started', 90)
        ball = g.value(BALL_STATE) if g.value(BALL_STATE) >= 0x80000000 else BALL_STATE
        g.wait(lambda: g.value(ball, 2) == 9, 'the ball never floated at the serve', 30)
        me = ACTOR + hitter * STRIDE
        g.wait(lambda: g.value(me + 0x1a4) == 0, 'the hitter never settled', 5)
        g.q(cmd='turbo', enabled=0)
        g.q(cmd='savestate', op='save', slot=SLOT)
        keys = [g.value(ACTOR + p * STRIDE + 0x16, 2) for p in (0, 1)]
        site = g.value(SWORD_SITE)
        test = 'stock' if site == SWORD_STOCK else f'patched, mask {g.value(SWORD_SITE + 4) & 0xffff}'
        moves = unblockables(g, hitter)
        print(f'F31 {case}: keys {keys}, hitter P{hitter + 1}, key test {test}, '
              f'unblockables {[(al, f"{mid:#x}", d) for al, _, mid, d in moves]}', flush=True)
        assert moves, 'no unblockable move found for the hitter'
        if p2 is not None: assert keys[1] == 23, f'player 2 is not the guest: key {keys[1]}'
        results = []
        for alias, record, move_id, damage in moves[:MOVES]:
            for d in DISTANCES:
                r = trial(g, ball, hitter, alias, record, d)
                if r is None: continue
                state, homing, at = r
                # Bounced off the body, or another move by then: farther.
                if at not in UNBLOCKABLE or not (state == 7 or (state == 2 and homing)): continue
                outcome = 'broken' if state == 7 else 'shot'
                print(f'  alias {alias} id {move_id:#x} damage {damage}: ball at {d} -> {outcome}', flush=True)
                results.append(outcome)
                break
            else: print(f'  alias {alias} id {move_id:#x}: no contact', flush=True)
            if len(results) >= CONTACTS: break
        for line in g.log().splitlines():
            if 'draws' in line or 'starts on' in line: print(' ', line)
        ok = bool(results) and (('broken' in results) == (expect == 'broken'))
        if case == 'jin': ok = ok and site == SWORD_STOCK
        print(f'RESULT {case}: {results} expect {expect} -> {"OK" if ok else "KO"}', flush=True)
        return ok
    except BaseException:
        print(g.log()[-3000:]); raise
    finally: g.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--case', nargs='+', default=list(CASES), choices=list(CASES))
    ap.add_argument('--build', default=str(ROOT / 'build-rel-lite'))
    ap.add_argument('--memcard-dir', default=str(ROOT / 'saves'))
    a = ap.parse_args()
    build = Path(a.build)
    assert (build / 'mods/ttt1/guests.txt').is_file(), f'no TTT1 catalogue in {build}/mods/ttt1'
    verdicts = {case: run(build, Path(a.memcard_dir), case) for case in a.case}
    print('SUMMARY', ' '.join(f'{c}={"OK" if v else "KO"}' for c, v in verdicts.items()))
    sys.exit(0 if all(verdicts.values()) else 1)


if __name__ == '__main__':
    main()
