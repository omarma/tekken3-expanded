#!/usr/bin/env python3
"""F09: a cinematic's black loading is short and runs unpaced, the cinematic and the title after it never do.

    python tools/test_cine_fast_load.py OUT [--build build-rel-lite] [--mods off,on,check]

Boots tools/cine_drive.py's private copy (software x1, headless) once per setting of the speed mods
(off: none; on: psx.enhancement.fast-loading, uncapped), Start at the title, then no input: the
attract's first Embu is the cinematic engine's TTT Embu. The engine logs its pace decisions
("Cine scene: frame N, pace ...", src/tekken3_cine_scene.c); the runtime's load_transitions give
the frames actually run unpaced (turbo). Each run fails if the black (the scene loading, the
characters read ahead) or the way back to the title is unpaced for less than 95 % of its frames
(the loading slow again), if a single frame of the cinematic or of the title runs unpaced (the
speed-up past the black), or if the characters read ahead take more than READ_AHEAD_MAX frames
(their files read through the emulated drive again: 554 frames for the Embu's seven). check: the
drive reads them as before (TEKKEN3_CINE_SWAP_CHECK=1) and every file must match the disc image's
bytes (src/tekken3_cine_swap.c). OUT/<setting>/game.log, OUT/<setting>/pace.txt. Run through
ressources/slot.py (--kind game). Frames, not seconds: headless runs unpaced everywhere.
"""
import argparse, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

FAST_ON = ('format_version = 2\n\n[[package]]\nid = "psx.enhancement.fast-loading"\n\n[[feature]]\n'
           'package_id = "psx.enhancement.fast-loading"\nid = "fast-loading"\nenabled = true\n'
           '[feature.values]\nuncapped = "true"\n')
MODS = {'off': 'format_version = 2\n', 'on': FAST_ON, 'check': 'format_version = 2\n'}
PACE = re.compile(r'Cine scene: frame (\d+), pace (.+)')
CHECK = re.compile(r'Cine swap: check, file (\d+) (.+)')
UNPACED = ('unpaced, the loading', 'unpaced, the reading ahead', 'unpaced, back to the title')
HELD = ('held, the scene', 'held, the title')
READ_AHEAD_MAX = 120


def turbo_frames(edges, a, b):
    """Frames in [a, b) run unpaced, from the runtime's turbo edges."""
    n, on, at = 0, 0, None
    for e in edges:
        if on and at is not None: n += max(0, min(e['frame'], b) - max(at, a))
        on, at = e['turbo'], e['frame']
    if on and at is not None: n += max(0, b - max(at, a))
    return n


def run(build, out, setting):
    out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_CINE_SWAP_CHECK': '1'} if setting == 'check' else {}
    g = cd.Game(build, out, env, False, mods_state=MODS[setting])
    menu, done = False, False
    try:
        f0 = g.frame(); end = time.monotonic() + 900
        while time.monotonic() < end:
            if not menu and g.value(cd.STATE, 2) == 3 and g.frame() - f0 > 300:
                g.press(cd.START); menu = True
            paces = PACE.findall(g.log())
            if any(p == 'held, the title' for _, p in paces) and paces[-1][1] == "the player's":
                done = True; break
            time.sleep(.1)
        edges = g.q(cmd='load_transitions', count=512)['edges']
    finally:
        g.stop()
    log = (out / 'game.log').read_text(errors='replace')
    paces = [(int(f), p) for f, p in PACE.findall(log)]
    if not done: print(f'{setting}: the Embu and the title after it never went by'); return False
    rows, ok = [], True
    for (a, p), (b, _) in zip(paces, paces[1:]):
        t = turbo_frames(edges, a, b)
        bad = (p in UNPACED and t < .95 * (b - a)) or (p in HELD and t > 0) or \
              (p == 'unpaced, the reading ahead' and setting != 'check' and b - a > READ_AHEAD_MAX)
        ok &= not bad
        rows.append(f'{a:7d} {b - a:5d} frames, {t:5d} unpaced  {p}{"  <- ECHEC" if bad else ""}')
    if setting == 'check':
        checks = CHECK.findall(log)
        wrong = [f'file {f} {x}' for f, x in checks if x != 'as on the disc image']
        ok &= bool(checks) and not wrong
        rows.append(f'{len(checks)} files compared with the disc image' +
                    ('  <- ECHEC: ' + '; '.join(wrong) if wrong else '' if checks else '  <- ECHEC (none)'))
    (out / 'pace.txt').write_text('\n'.join(rows) + '\n')
    print(f'mods {setting}:'); print('\n'.join('  ' + r for r in rows))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--mods', default='off,on,check')
    a = ap.parse_args()
    ok = all([run(ROOT / a.build, a.out / s, s) for s in a.mods.split(',')])
    print('OK' if ok else 'ECHEC')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
