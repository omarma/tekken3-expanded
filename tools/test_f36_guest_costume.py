#!/usr/bin/env python3
"""F36 (GH#204): a CPU guest draws its costume among its TTT1 ones (CPU COSTUME).

    python tools/test_f36_guest_costume.py [--mode arcade|timeattack|survival|team] [--guest lee]
                                           [--seed N] [--costume ttt|tekken3] [--build build-rel-lite]

Player 1 picks Jin (stock page), the CPU's fighter becomes the guest as in
tools/test_cpu_ending_pack.py (Arcade: stage 2 of the opponents' list, stage 1
won by emptying player 2's life; the other modes: written while the first fight
loads, the CPU team's first member too), costume 0 (punch) as the game's.
TEKKEN3_CPU_COSTUME and TEKKEN3_CPU_MOVESET_SEED set the row and the draw.

In the guest's fight: ttt, the log has one "Guest models: CPU P2 fighter <id>
draws its costume <c> among <n>" for it, n is the number of the guest's
-arcade-P<k>.3dm files, the model read is that costume's ("<Name> model:
costume <c>"), the actor keeps the game's costume (punch or kick); tekken3, no draw and
the model of costume 1. Prints the drawn costume. Exit status 1 on a failure.
Not covered: a Continue (a forced loss here goes straight to Game Over).
Headless, software renderer, keyboard only (never the player's pad).
"""
import argparse, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

LIST, STATE, PHASE, MODE = 0x800AFB18, 0x800AE204, 0x800AE224, 0x800AFA88
MODES = {'arcade': 0, 'team': 2, 'timeattack': 3, 'survival': 4}
CPU_TEAM, CPU_FIGHTER, CPU_COSTUME = 0x800AFAEE, 0x800ADD5E, 0x800ADD9A
P2, P1_LIFE = 0x800AAAB4, 0x800A961E


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', choices=tuple(MODES), default='arcade')
    ap.add_argument('--guest', default='lee')
    ap.add_argument('--seed', default='1')
    ap.add_argument('--costume', choices=('ttt', 'tekken3'), default='ttt')
    ap.add_argument('--build', default='build-rel-lite')
    a = ap.parse_args()
    build = L.ROOT / a.build
    files = sorted(build.glob(f'mods/ttt1/{a.guest.capitalize()}-TTT1-arcade-P*.3dm'))
    s = L.Session(guest=a.guest, build=build,
                  env={'TEKKEN3_GUEST_P2': a.guest, 'TEKKEN3_NATIVE_MOVES': '0',
                       'TEKKEN3_CPU_COSTUME': a.costume, 'TEKKEN3_CPU_MOVESET_SEED': a.seed},
                  line=2 if a.mode == 'team' else 0)
    failures, reached, actor_costume = [], False, None
    try:
        if a.mode == 'team':
            if not s.boot: s.write(MODE, 2); s.write(PHASE, 0, 2); s.write(STATE, 10, 2)
            time.sleep(3)
            s.press(0xbfff); time.sleep(.8)                         # a team of one
            for _ in range(6):
                s.press(0xfff7)                                     # Start: the teams are drawn
                if s.value(STATE) != 10: break
                time.sleep(.8)
        else:
            s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'no stock selector grid', 20)
            s.write(MODE, MODES[a.mode])
            for _ in range(23):
                if s.value(0x80118668) == 9: break
                s.press(0xff7f)
            s.press(0x7fff)
        s.wait(lambda: s.value(STATE) in (8, 11), 'no loading screen', 15)
        if a.mode == 'arcade': s.write(LIST + 4, s.cid_p2, 1); s.write(LIST + 5, 0, 1)
        t0, start = time.monotonic(), None
        while time.monotonic() - t0 < 300:
            if s.process.poll() is not None: raise RuntimeError('the game exited')
            state, phase = s.value(STATE), s.value(PHASE, 2)
            if (state == 11 or state == 8 and phase <= 3) and a.mode != 'arcade' and start is None:
                s.write(CPU_FIGHTER, s.cid_p2, 2); s.write(CPU_COSTUME, 0, 2)
                if a.mode == 'team': s.write(CPU_TEAM, s.cid_p2 * 4, 1)
            elif state == 8 and phase >= 6 and s.actor(1)[2] != s.cid_p2 and s.value(P2 + 0x3F4) > 0xFFFF:
                s.write(P2 + 0x3F6, 0, 2)                           # another opponent first: won
            elif state == 8 and phase == 8 and s.actor(1)[2] == s.cid_p2:
                start = start or time.monotonic()
                actor_costume = s.value(0x800a923c + 0x188c, 2) & 3     # ID * 4 + costume (roster.c)
                if time.monotonic() - start > 4: break
            elif state not in (8, 9, 10, 11): s.press(0xfff7)
            time.sleep(.25)
        if start is None: raise RuntimeError("the guest's fight was not reached")
        mode = s.value(MODE)
        if mode != MODES[a.mode]: failures.append(f'the fight ran in mode {mode}, not {a.mode}')
        log = s.log()
        draws = re.findall(rf'Guest models: CPU P2 fighter {s.cid_p2} draws its costume (\d) among (\d)', log)
        name = {'armorking': 'Armor King', 'pjack': 'P.Jack'}.get(a.guest, a.guest.capitalize())
        models = re.findall(rf'{re.escape(name)} model: costume (\d)', log)
        if a.costume == 'ttt':
            if len(files) < 2:
                if draws: failures.append(f'a draw for a guest with one costume: {draws}')
                drawn = 1
            elif len(draws) != 1: failures.append(f'{len(draws)} draws in the log, not one: {draws}'); drawn = None
            else:
                drawn, among = int(draws[0][0]), int(draws[0][1])
                if among != len(files): failures.append(f'drawn among {among}, {len(files)} costume files')
        else:
            if draws: failures.append(f'a draw under TEKKEN 3: {draws}')
            drawn = 1
        if drawn and (not models or int(models[-1]) != drawn):
            failures.append(f'model read {models[-1:] or "none"}, drawn costume {drawn}')
        # No other costume read after the draw (the fight's first frames once reloaded the game's).
        after = log.split('Guest models: CPU P2', 1)[1] if draws else ''
        other = [c for c in re.findall(rf'{re.escape(name)} model: costume (\d)', after) if drawn and int(c) != drawn]
        if other: failures.append(f'costume(s) {other} read after the draw')
        # The game's costume stays: punch or kick in these modes, never the third.
        if actor_costume not in (0, 1): failures.append(f"the actor's costume is {actor_costume}, not the game's")
        print(f'{a.mode} {a.guest} seed {a.seed} {a.costume}: drawn costume {drawn} of {len(files)}, '
              f'models read {models}, actor costume {actor_costume}')
    finally:
        s.stop()
    for f in failures: print('ECHEC', f)
    print('OK' if not failures else 'ECHEC')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
