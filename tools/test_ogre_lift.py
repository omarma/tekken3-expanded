#!/usr/bin/env python3
"""Ogre's cutscene lifts the stage 9 boss (F07, src/tekken3_ttt1_roster.c).

    python tools/test_ogre_lift.py OUT --boss heihachi|devil|angel|unknown
        [--player paul|heihachi|<guest key>] [--build build-f07] [--shots] [--visible]

Cold boot (tools/ttt1_live.py), ARCADE, the player's cell (stock grid for a
native, the Tag page for a guest), Square. The stage 9 boss is set through
TEKKEN3_CPU_GUESTS (`0,0,1,<boss>`; `0,0,0` for Heihachi); once the mod has
written the opponent list, the first fight counts as stage 9, Ogre comes
next. Rounds are won by emptying player 2's life in turbo, in real time
from Ogre's K.O. on. During the cutscene (state 8, phases 16-17) the
player's actor must be the boss (Jin for a Heihachi player and a Heihachi
boss) and its root (actor +0x908..+0x90C, three halfwords) must travel:
the largest range of one coordinate over phase 17 (Heihachi about 1 900,
a fighter left in guard a few units). Then phase 20 must give the player
its own fighter back against True Ogre. The log must say "Ogre's cutscene
lifts", and not "unmapped native entry". --shots: a screenshot every 15 frames of the cutscene into OUT. One game:
run it through slot.py. Exit status 1 on any failure. Time Attack plays no
cutscene (phase 16 goes straight to 20): Arcade only.
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt1_live as L

STATE, PHASE, STAGE, OPPONENTS = 0x800AE204, 0x800AE224, 0x800AFAAC, 0x800AFB18
ACTOR, ACTOR_SIZE, P2_LIFE = 0x800A9228, 0x188C, 0x800AAEA8
NATIVES = {'paul': 0, 'law': 1, 'jin': 9, 'heihachi': 13}
BOSS_NAMES = {'heihachi': 'Heihachi', 'devil': 'Devil', 'angel': 'Angel', 'unknown': 'Unknown'}
RISE = 400          # root travel over phase 17 (Heihachi: about 1 900)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--boss', default='heihachi', choices=sorted(BOSS_NAMES))
    ap.add_argument('--player', default='paul')
    ap.add_argument('--build', default='build-f07')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--shots', action='store_true')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    native = a.player in NATIVES
    env = {'TEKKEN3_NATIVE_MOVES': '0',
           'TEKKEN3_CPU_GUESTS': '0,0,0' if a.boss == 'heihachi' else f'0,0,1,{a.boss}'}
    s = L.Session(guest='kazuya' if native else a.player, visible=a.visible, build=L.ROOT / a.build, env=env)
    catalogue = [l.split()[0] for l in (s.assets / 'guests.txt').read_text().splitlines() if l.split()]
    player_id = NATIVES[a.player] if native else s.cid
    want = (9 if a.player == 'heihachi' else 13) if a.boss == 'heihachi' else L.GUEST_ID + catalogue.index(a.boss)
    q = s.q

    def press(b):
        q(cmd='input_route_clear'); q(cmd='input_route_append', frames=3, buttons=b)
        q(cmd='input_route_append', frames=12, buttons=0xFFFF); q(cmd='input_route_start')
        while q(cmd='input_route_status').get('active'): time.sleep(.02)

    def h(a_, n=2):
        v = s.value(a_, n)
        return v - (1 << 8 * n) if v >> (8 * n - 1) else v

    failures, rows, samples, after = [], [], [], None
    try:
        s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'selector', 60)
        if native:
            for step in range(36):                  # along a row, then the row below
                if s.value(0x80118668) == player_id: break
                press(0xffbf if step % 12 == 11 else 0xff7f)
            else: raise RuntimeError(f'no cell for {a.player}')
        else:
            press(L.PAD_R2); time.sleep(2)
            row, col = L.tag_place(s.index, s.catalogue_size)
            for _ in range(12):
                r, c = L.tag_place(s.value(0x80118650), s.catalogue_size)
                if (r, c) == (row, col): break
                press(0xffbf if r < row else 0xffef if r > row else 0xffdf if c < col else 0xff7f)
            s.wait(lambda: s.value(0x80118668) == s.cid, 'guest cell', 10)
        press(0x7fff)
        q(cmd='turbo', enabled=1)
        end, staged = time.monotonic() + 1500, False
        while True:
            if time.monotonic() > end: raise RuntimeError(f'no cutscene: state {s.value(STATE)}')
            st, ph = s.value(STATE), s.value(PHASE, 2)
            if st == 11 and not staged and s.value(STAGE, 1) == 0 and s.value(OPPONENTS + 36, 1) == 14:
                boss = s.value(OPPONENTS + 32, 1)
                if a.boss == 'heihachi' or boss >= L.GUEST_ID:    # the mod's own list written
                    print('stage 9 boss', boss, flush=True)
                    s.write(STAGE, 8, 1); staged = True
            if st == 8 and 6 <= ph < 9:
                life = s.value(P2_LIFE)
                if life >> 16: s.write(P2_LIFE, life & 0xFFFF)
            if st == 8 and ph >= 16: break
            time.sleep(.01)
        q(cmd='turbo', enabled=0)
        f0 = q(cmd='frame')['frame']; last = None; shot = -99
        while (f := q(cmd='frame')['frame'] - f0) < 3000:
            st, ph = s.value(STATE), s.value(PHASE, 2)
            if (st, ph) != last:
                print(f, 'state', st, 'phase', ph, flush=True); rows.append([f, st, ph]); last = (st, ph)
            if st == 8 and ph == 17:
                samples.append([f, s.value(ACTOR + 0x18, 2), h(ACTOR + 0x908), h(ACTOR + 0x90A), h(ACTOR + 0x90C),
                                s.value(ACTOR + 0x54)])
                if a.shots and f - shot >= 15:
                    try: q(cmd='screenshot_file', path=str(a.out / f'{f:05d}.png'))
                    except Exception: pass
                    shot = f
            if st == 8 and 6 <= ph < 9 and s.value(ACTOR + ACTOR_SIZE + 0x18, 2) == 20:
                after = s.value(ACTOR + 0x18, 2)
                break
            time.sleep(.01)
    finally:
        s.stop()
    (a.out / 'samples.json').write_text(json.dumps({'states': rows, 'phase17': samples}))
    log = s.log()
    (a.out / 'game.log').write_text(log)
    if "Ogre's cutscene lifts" not in log: failures.append('log without "Ogre\'s cutscene lifts"')
    if 'unmapped native entry' in log: failures.append('log with "unmapped native entry"')
    ids = sorted({x[1] for x in samples})
    if ids != [want]: failures.append(f'lifted actor {ids}, expected {want}')
    rise = max(max(x[k] for x in samples) - min(x[k] for x in samples) for k in (2, 3, 4)) if samples else 0
    if rise < RISE: failures.append(f'the root moved {rise}, under {RISE}')
    records = len({x[5] for x in samples})
    if after != player_id: failures.append(f'after the cutscene P1 is {after}, expected {player_id}')
    print(f'{a.player} vs {a.boss}: phase 17 {len(samples)} samples, actor {ids}, root travel {rise}, '
          f'{records} records, back to {after}')
    for x in failures: print('ECHEC', x)
    print('OK' if not failures else 'ECHEC')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
