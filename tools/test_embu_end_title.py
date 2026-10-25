#!/usr/bin/env python3
"""B62: after the TTT Embu of the attract (the cinematic engine, `attract rotation=2`), the title, not the intro video.

    python tools/test_embu_end_title.py OUT [--build build-rel-lite]

Boots a private copy (tools/cine_drive.py's Game: software x1, headless), Start at the title to the modes
menu, then no input: the engine's Embu comes first or second (TIPS section 135: on a new save, T3's
variant 0 first). Once it is over (fight phase 17 left), the
next state 3 must be the title alone (its phases 4 on: no intro video, phases 1-2, "Namco presents"), and
once that title is over the attract's cycle 0x80097F3E must be 2, where T3's own Embu leaves it. Exit 1
otherwise. OUT/states.txt. Run through ressources/slot.py (--kind game).
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

CYCLE = 0x80097f3e


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    g = cd.Game(ROOT / a.build, a.out, {}, False)
    rows, last, menu, over, phases, cycle = [], None, False, False, [], None
    try:
        f0 = g.frame(); end = time.monotonic() + 600
        while time.monotonic() < end:
            f = g.frame() - f0
            st, ph = g.value(cd.STATE, 2), g.value(cd.PHASE, 2)
            if (st, ph) != last:
                rows.append(f'{f:6d} state {st:2d} phase {ph:3d} cycle {g.value(CYCLE, 1)}')
                if last == (8, 17): over = True
                if over and st == 3: phases.append((ph, f))
                if over and phases and st != 3:
                    cycle = g.value(CYCLE, 1); phases.append((None, f)); break
                last = (st, ph)
            if not menu and st == 3 and f > 300:
                g.press(cd.START); menu = True
            time.sleep(.01)
    finally:
        (a.out / 'states.txt').write_text('\n'.join(rows) + '\n')
        g.stop()
    if not over: print('the engine\'s Embu never played'); sys.exit(1)
    # A video is phase 1 or 2 held: leaving the title, phase 2 can show for a few frames on the way to
    # the demo (13 frames seen); the intro video holds it thousands.
    held = [(p, phases[i + 1][1] - f) for i, (p, f) in enumerate(phases[:-1])]
    video = [p for p, n in held if p in (1, 2) and n > 120]
    phases = [p for p, _ in held]
    print(f'state 3 after the Embu: phases (frames) {held}, then the cycle at {cycle}')
    ok = not video and 8 in phases and cycle == 2
    print('OK' if ok else 'ECHEC (' + ('the intro video' if video else 'no title' if 8 not in phases else f'cycle {cycle}, not 2') + ')')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
