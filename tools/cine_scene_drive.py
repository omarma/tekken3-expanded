#!/usr/bin/env python3
"""Test bench of the cinematic engine's scene loading (src/tekken3_cine_scene.c):
a .cine played out of a fight, its arena and fighters loaded by the engine.

    python tools/cine_scene_drive.py OUT [--cine kazuya] [--from 4] [--black]
                                     [--shots N] [--hold F1,F2,...] [--build build-rel-lite] [--visible] [--env K=V ...]

Boots a private copy of the build (software renderer, x1, headless unless
--visible; tools/cine_drive.py's Game) with TEKKEN3_CINE_SCENE_TEST set:
--from 4 (default) Start on "Namco presents", the scene plays from the modes
menu; --from 3 from the title, without input; --from 8 from an Arcade
fight (Kazuya, the Tag page), 120 frames into its first round. Polls state and phase (OUT/
states.json), a screenshot every N frames while it plays (state 8, phase 17)
and one after; checks the game reaches the attract (state 2 or 3) and goes on.
--hold: the engine holds these frames of the .cine (TEKKEN3_CINE_HOLD) and
each one's screenshot is OUT/cine_<frame>.png, at that exact frame (a side by
side with the PS2: tools/ps2/ttt_compare_shots.py).
The .cine is mods/ttt-cinematics/<cine>.cine of the build. Run through
ressources/slot.py (--kind game).
"""
import argparse, json, re, struct, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

STATE, PHASE, START = cd.STATE, cd.PHASE, cd.START


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--cine', default='kazuya')
    ap.add_argument('--from', dest='start', type=int, default=4, choices=(3, 4, 8))
    ap.add_argument('--black', action='store_true', help='no loading screen')
    ap.add_argument('--shots', type=int, default=0)
    ap.add_argument('--hold', default='', help='frames of the .cine to hold and screenshot')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--visible', action='store_true')
    ap.add_argument('--env', action='append', default=[], help='KEY=VALUE for the game (TEKKEN3_CINE_RECORD=...)')
    ap.add_argument('--video', action='append', default=[], help='KEY=VALUE of settings.toml [video] (supersampling=4 for a film)')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    build = ROOT / a.build
    cine = (build / 'mods/ttt-cinematics' / f'{a.cine}.cine').resolve()
    env = dict(e.split('=', 1) for e in a.env)
    if a.hold: env['TEKKEN3_CINE_HOLD'] = a.hold
    env['TEKKEN3_CINE_SCENE_TEST'] = f'{cine.as_posix()}@{a.start}:{120 if a.start == 8 else 30}:{int(a.black)}'
    g = cd.Game(build, a.out, env, a.visible, a.video)
    rows, last, shot, ok, taken = [], None, -10 ** 9, False, set()
    try:
        g.q(cmd='turbo', enabled=1)
        f0 = g.frame()
        end = time.monotonic() + 600
        if a.start == 8: cd.to_arcade_guest(g, 'kazuya')
        while 'Cine scene: loading' not in g.log():
            if time.monotonic() > end: raise AssertionError('the scene never started')
            if a.start == 4 and g.value(STATE) == 3: g.press(START)
            time.sleep(.05)
        g.q(cmd='turbo', enabled=0)
        while 'Cine scene: over' not in g.log():
            f = g.frame() - f0
            if time.monotonic() > end: raise AssertionError('the scene never ended')
            st, ph = g.value(STATE), g.value(PHASE, 2)
            if (st, ph) != last:
                print(f, 'state', st, 'phase', ph, flush=True); rows.append([f, st, ph]); last = (st, ph)
            for held in re.findall(r'Cine: hold frame (\d+)', g.log()):
                if held in taken: continue
                time.sleep(.15); taken.add(held)
                g.q(cmd='screenshot_file', path=str(a.out / f'cine_{int(held):05d}.png'))
                # Both actors' T3 bones there (world position, actor + 0x908 + 68 * bone, 20 bones).
                bones = [[list(struct.unpack('<3i', g.read(0x800a9228 + p * 0x188c + 0x908 + 68 * b, 12))) for b in range(20)]
                         for p in range(2)]
                (a.out / f'cine_{int(held):05d}.json').write_text(json.dumps(bones))
            if a.shots and f - shot >= a.shots and (st == 11 or (st == 8 and ph in (3, 4, 17))):
                try: g.q(cmd='screenshot_file', path=str(a.out / f'{f:05d}.png'))
                except RuntimeError: pass                          # the display off (--black)
                shot = f
            time.sleep(.02)
        t = time.monotonic() + 30
        while time.monotonic() < t:
            st, ph = g.value(STATE), g.value(PHASE, 2)
            if (st, ph) != last:
                print(g.frame() - f0, 'state', st, 'phase', ph, flush=True); rows.append([g.frame() - f0, st, ph]); last = (st, ph)
            if st == 3: break
            time.sleep(.05)
        f1 = g.frame(); time.sleep(2); f2 = g.frame()
        g.q(cmd='screenshot_file', path=str(a.out / 'after.png'))
        ok = g.value(STATE) in (2, 3, 6) and f2 > f1 + 30
        print(f'after the scene: state {g.value(STATE)} phase {g.value(PHASE, 2)}, {f2 - f1} frames in 2 s:', 'OK' if ok else 'ECHEC')
    finally:
        (a.out / 'states.json').write_text(json.dumps(rows))
        g.stop()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
