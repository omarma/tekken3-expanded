#!/usr/bin/env python3
"""B75 (GH#130): the attract's demo fight with the mod's content (src/tekken3_ttt1_roster.c demo_fighters,
src/tekken3_native_moves.c, src/tekken3_stage_source.c).

    python tools/test_attract_demo.py OUT [--build build-rel-lite] [--guest jun] [--p2 paul] [--embus 0]

Boots a private copy (tools/cine_drive.py's Game: software x1, headless) and lets the attract play with no
input, TEKKEN3_ATTRACT_DEMO=GUEST,P2 (the guest starts the demo's turn, P2 is player 2 in every demo: a
native, or a guest for the Embus after a guest's demo), TEKKEN3_CPU_MOVESET=ttt1, TEKKEN3_STAGES=auto. The
first demo fight must be the guest against P2 (0x800ADD5C), a native P2 on its TTT1 moves, and the guest's
TTT stage decided and loaded; the second demo the next fighter of the turn against P2. --embus N goes on
through N Embus of the attract (counted by the rotation's decisions in the log, "Cine trigger: Embu rotation":
the cinematic engine's TTT Embu leaves state 6 at once for its scene's fight, then the game's own, the guests'
and T3's variants, TIPS § 135) and checks each one: the engine's scene ends; the game's own Embu keeps Tekken
3's stage, the guests' grafts its cast's guests, not a fighter of the demo before it (natives on their TTT1
moves stayed the players' identities there: B75), T3's variants none. Screenshots of the
game's Embu in OUT/embu-*.png. Exit 1 otherwise. OUT/states.txt, OUT/game.log. Run through
ressources/slot.py (--kind game).
"""
import argparse, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

MODE, FIGHTERS, DEMO, GUEST_ID = 0x800afa88, 0x800add5c, 6, 23
T3_KEYS = ['paul', 'law', 'lei', 'king', 'yoshimitsu', 'nina', 'hwoarang', 'xiaoyu', 'eddy', 'jin', 'julia', 'kuma',
           'bryan', 'heihachi', 'ogre', 'mokujin', 'gunjack', 'gon', 'anna', 'drb']
T3_NAMES = {'Paul', 'Law', 'Lei', 'King', 'Yoshimitsu', 'Nina', 'Hwoarang', 'Xiaoyu', 'Eddy', 'Jin', 'Julia',
            'Kuma', 'Bryan', 'Heihachi', 'Ogre', 'Mokujin', 'Anna'}
TRIGGER, DEMO_LINE = 'Cine trigger: Embu rotation, ', 'attract demo,'


def turn(decision):
    """The rotation's turn a decision line names: 'TTT' (the engine's .cine), 'guests', 'v0'..."""
    first = decision.split('\n', 1)[0][len(TRIGGER):]
    if '.cine' in first: return 'TTT'
    return 'v' + first.split()[3] if first.startswith("the game's") else first.split()[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--guest', default='jun')
    ap.add_argument('--p2', default='paul')
    ap.add_argument('--embus', type=int, default=0)
    ap.add_argument('--minutes', type=float, default=30)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_ATTRACT_DEMO': f'{a.guest},{a.p2}', 'TEKKEN3_CPU_MOVESET': 'ttt1', 'TEKKEN3_STAGES': 'auto'}
    g = cd.Game(ROOT / a.build, a.out, env, False)
    guest = GUEST_ID + g.catalogue.index(a.guest)
    native = a.p2 in T3_KEYS
    p2_id = T3_KEYS.index(a.p2) if native else GUEST_ID + g.catalogue.index(a.p2)
    rows, last, demos, embus, shot, fails, own, away = [], None, [], [], -1, [], False, True
    try:
        f0 = g.frame(); end = time.monotonic() + a.minutes * 60
        while time.monotonic() < end and g.process.poll() is None:
            f = g.frame() - f0
            st, ph, mode = g.value(cd.STATE, 2), g.value(cd.PHASE, 2), g.value(MODE, 4)
            if (st, ph) != last:
                fi = g.read(FIGHTERS, 4)
                pair = (int.from_bytes(fi[:2], 'little'), int.from_bytes(fi[2:], 'little'))
                rows.append(f'{f:6d} state {st:2d} phase {ph:3d} mode {mode} fighters {pair[0]},{pair[1]}')
                log = g.log()
                # A demo's round under way, the cinematic engine's scenes left out (a "Cine scene" line open).
                scene = log.count('Cine scene: loading') > log.count('Cine scene: over')
                if st == 8 and ph == 8 and mode == DEMO and not scene and away:
                    demos.append((pair, len(log))); away = False
                if st != 8: away = True
                while log.count(TRIGGER) > len(embus): embus.append(len(demos))
                r = log.rfind(TRIGGER)
                own = st == 6 and r > log.rfind(DEMO_LINE) and turn(log[r:]) != 'TTT'
                last = (st, ph)
            if own and f // 600 != shot:
                shot = f // 600
                g.q(cmd='screenshot_file', path=str((a.out / f'embu-{f:06d}.png').resolve()))
            # Done: two demos, and the demo after the last Embu asked for begun.
            if len(demos) >= 2 and (a.embus == 0 or (len(embus) >= a.embus and len(demos) > embus[a.embus - 1])):
                break
            time.sleep(.02)
        alive = g.process.poll() is None
    finally:
        (a.out / 'states.txt').write_text('\n'.join(rows) + '\n')
        log = g.log()
        g.stop()
    if not alive: fails.append('the game exited')
    if len(demos) < 2: fails.append(f'{len(demos)} demo fight(s) seen, not 2')
    if demos:
        (p1, p2), at = demos[0]
        print(f'demo 1: fighters {p1}, {p2}')
        if (p1, p2) != (guest, p2_id): fails.append(f'demo 1: {p1}, {p2}, not {guest} ({a.guest}), {p2_id} ({a.p2})')
        fight = log[log.rfind(DEMO_LINE, 0, at):at]
        m = re.search(r"TTT Stages: Attract demo fight in arena (\d+), P1's guest (\w+) decides, STAGES auto -> (\w+) stage (\d+)", fight)
        print('demo 1 stage:', m.groups() if m else None)
        if not m or m.group(2) != a.guest or m.group(3) != 'TTT': fails.append('demo 1: no TTT stage decided for the guest')
        if not re.search(r'arcade stages: TTT stage \d+ loaded', fight): fails.append('demo 1: no TTT stage loaded')
        if native and (f'Native moves: CPU P2 fighter {p2_id} draws' not in fight or
                       not re.search(r'P2 [\w .-]+ on the TTT1 moveset', fight)):
            fails.append('demo 1: player 2 not on its TTT1 moves')
    if len(demos) >= 2:
        (p1, p2), _ = demos[1]
        print(f'demo 2: fighters {p1}, {p2}')
        if p1 == guest or p2 != p2_id: fails.append(f'demo 2: {p1}, {p2}: the turn did not move on')
    triggers = [m.start() for m in re.finditer(TRIGGER, log)]
    for i, start in enumerate(triggers[:a.embus]):
        # The Embu's own lines: from its trigger to the next demo's, after the demo before it.
        stop = log.find(DEMO_LINE, start)
        part = log[start:stop if stop >= 0 else len(log)]
        before = log[log.rfind(DEMO_LINE, 0, start):start].split('\n', 1)[0]
        kind = turn(part); own_embu = kind != 'TTT'
        grafted = re.findall(r"TTT1 Embu: P\d (.+?) on \w+'s model", part)
        print(f'Embu {i + 1} (after "{before}"): {kind}, {"the game" if own_embu else "the cinematic engine"}' +
              (f', grafted {sorted(set(grafted))}' if own_embu else ''))
        if own_embu:
            if re.search(r'arcade stages: TTT stage \d+ loaded', part): fails.append(f'Embu {i + 1}: a TTT stage')
            wrong = sorted(set(grafted) & T3_NAMES)
            if wrong: fails.append(f'Embu {i + 1}: natives grafted in place of the cast: {wrong}')
            if kind == 'guests' and not grafted: fails.append(f'Embu {i + 1}: no guest of the cast grafted')
            if kind != 'guests' and grafted: fails.append(f'Embu {i + 1} ({kind}): guests grafted {sorted(set(grafted))}')
        elif 'Cine scene: over' not in part: fails.append(f'Embu {i + 1}: the scene did not end')
    if len(triggers) < a.embus: fails.append(f'{len(triggers)} Embu(s) seen, not {a.embus}')
    print('OK' if not fails else 'ECHEC: ' + '; '.join(fails))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
