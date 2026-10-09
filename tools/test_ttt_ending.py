#!/usr/bin/env python3
"""A TTT ending at the end of a guest's Arcade, with TTT Cinematics as
installed (src/tekken3_embu_scenes.c, tools/ttt_cinematics.py).

    python3 tools/test_ttt_ending.py OUT --p1 kazuya|armorking [--build build-opt-dbg] [--visible] [--shots]

Cold boot, Start at the title, Cross on ARCADE, R2 (the Tag page), the
guest's cell, Square. The first fight counts as stage 9 (its index written
once it loads), True Ogre next; every round is won by emptying player 2's
life in turbo, True Ogre's in real time. Then the ending must play: the
log's "TTT Cinematics: <p1>'s ending selected", "Ending: P2 reloaded",
"Fight cinematic: started" and "over", "Ending: credits", and the cutscene
(state 8, phase 17) must last at least 1 000 frames. --shots: a screenshot
every 30 frames of the cutscene into OUT. Debug server build (build-opt-dbg
or rel-lite) with the TTT1 catalogue and TTT Cinematics prepared beside it;
one game: run through slot.py. Exit status 1 on any failure.
"""
import argparse, json, socket, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

STATE, PHASE, P2_LIFE = 0x800AE204, 0x800AE224, 0x800AAEA8


def start(self, log, port):
    deadline = time.monotonic() + 30
    while True:
        try:
            with socket.create_connection(('127.0.0.1', port), .2): break
        except OSError:
            if time.monotonic() > deadline: raise
            time.sleep(.1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--p1', default='kazuya')
    ap.add_argument('--build', default='build-opt-dbg')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--shots', action='store_true')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    build = L.ROOT / a.build
    if not (build / 'mods/ttt-cinematics/cinematics.txt').is_file():
        sys.exit(f'{build}/mods/ttt-cinematics is not prepared (tools/ttt_cinematics.py)')
    L.Session.start = start
    s = L.Session(guest=a.p1, visible=a.visible, build=build, env={'TEKKEN3_NATIVE_MOVES': '0'}); q = s.q

    def press(b):
        q(cmd='input_route_clear'); q(cmd='input_route_append', frames=3, buttons=b)
        q(cmd='input_route_append', frames=12, buttons=0xFFFF); q(cmd='input_route_start')
        while q(cmd='input_route_status').get('active'): time.sleep(.02)

    failures, rows, cine = [], [], 0
    try:
        q(cmd='clear_input'); q(cmd='turbo', enabled=1)
        s.wait(lambda: s.value(STATE) in (1, 3), 'title', 120)
        while s.value(STATE) != 4:
            if s.value(STATE) in (1, 3): press(0xFFF7)
            time.sleep(.3)
        time.sleep(.5); press(0xBFFF)                              # ARCADE, under the cursor
        s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'selector', 60)
        q(cmd='turbo', enabled=0)
        press(L.PAD_R2); time.sleep(2)
        row, col = L.tag_place(s.index, s.catalogue_size)
        for _ in range(12):
            r, c = L.tag_place(s.value(0x80118650), s.catalogue_size)
            if (r, c) == (row, col): break
            press(0xffbf if r < row else 0xffef if r > row else 0xffdf if c < col else 0xff7f)
        s.wait(lambda: s.value(0x80118668) == s.cid, 'guest cell', 10)
        press(0x7fff)
        q(cmd='turbo', enabled=1)
        end = time.monotonic() + 1500
        while True:
            if time.monotonic() > end: raise RuntimeError(f'no True Ogre: state {s.value(STATE)}')
            st, ph, p2 = s.value(STATE), s.value(PHASE, 2), s.value(0x800AAAB4 + 0x18, 2)
            if st == 11 and s.value(0x800AFAAC, 1) == 0: s.write(0x800AFAAC, 8, 1)    # stage 9, Ogre next
            if st == 8 and 6 <= ph < 9:
                life = s.value(P2_LIFE)
                if life >> 16: s.write(P2_LIFE, life & 0xFFFF)
            if p2 == 20: break                                     # True Ogre: real time from here
            time.sleep(.01)
        q(cmd='turbo', enabled=0)
        f0 = q(cmd='frame')['frame']; last = None; shot = -99
        while (f := q(cmd='frame')['frame'] - f0) < 9000:
            st, ph = s.value(STATE), s.value(PHASE, 2)
            if st == 8 and 6 <= ph < 9 and s.value(0x800AAAB4 + 0x18, 2) == 20:
                life = s.value(P2_LIFE)
                if life >> 16: s.write(P2_LIFE, life & 0xFFFF)
            if (st, ph) != last:
                print(f, 'state', st, 'phase', ph, flush=True); rows.append([f, st, ph]); last = (st, ph)
            if st == 8 and ph == 17:
                cine += 1
                if a.shots and f - shot >= 30:
                    try: q(cmd='screenshot_file', path=str(a.out / f'{f:05d}.png'))
                    except Exception: pass
                    shot = f
            if st == 19 and ph >= 3: break                         # the credits
            time.sleep(.01)
    finally:
        s.stop()
    (a.out / 'states.json').write_text(json.dumps(rows))
    log = s.log()
    for want in (f"TTT Cinematics: {a.p1}'s ending selected", 'Ending: P2 reloaded', 'Fight cinematic: started',
                 'Fight cinematic: over', 'Ending: credits'):
        if want not in log: failures.append(f'log without "{want}"')
    for bad in ('rejected', 'no TTT1 moves', 'not the Arcade overlay'):
        if bad in log: failures.append(f'log with "{bad}"')
    if cine < 1000: failures.append(f'the cutscene lasted {cine} polled frames, under 1 000')
    print(f'{a.p1}: cutscene {cine} frames, states {rows[-3:]}')
    for x in failures: print('ECHEC', x)
    print('OK' if not failures else 'ECHEC')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
