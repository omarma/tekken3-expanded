#!/usr/bin/env python3
"""F09: a cinematic's black loading is short and runs unpaced, the cinematic and the title after it never do.

    python tools/test_cine_fast_load.py OUT [--build build-rel-lite] [--mods off,on,check]
                                        [--start black,scene]

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

--start (B109): Start pressed during the TTT Embu instead, mods off: in the black (held from the
fight's phase 3, seen in phases 4 to 6) or 300 frames into the cinematic. The demo fight's mode
takes Start to the modes menu (fight_reset_check, state_leave_to(4)); the characters read ahead
cannot be left, the game reads no pad in the engine's one call. Each run fails if the menu does
not come, if the pace is not the player's again within LEFT_MAX frames of the game taking Start
(the black: once its phase 3 is over) or leaves it afterwards, if the cinematic still plays or its
scene still loads ("Cine scene: left" never logged), or if an Arcade with a guest (Kazuya) then
started from that menu does not reach its first round (the game stuck or gone). OUT/start-<moment>/game.log, OUT/start-<moment>/pace.txt.
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
LEFT_MAX = 120


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


def run_start(build, out, moment):
    """B109: Start during the TTT Embu, then the modes menu, the player's pace, a fight that loads."""
    out.mkdir(parents=True, exist_ok=True)
    g = cd.Game(build, out, {}, False, mods_state=MODS['off'])
    rows, ok, menu, pressed, guest = [], True, False, None, 'kazuya'
    try:
        f0 = g.frame(); end = time.monotonic() + 900
        while time.monotonic() < end and pressed is None:
            st = g.value(cd.STATE, 2)
            if not menu and st == 3 and g.frame() - f0 > 300:
                g.press(cd.START); menu = True
            found = PACE.findall(g.log()); paces = [p for _, p in found]
            scene = next((int(f) for f, p in found if p == 'held, the scene'), None)
            # The black: the fight's phase 3 loads in one call (the pad unread), phase 4 waits 60
            # frames, too short to aim at headless: Start held from phase 3 until the game takes it.
            if moment == 'black' and paces and paces[-1] == 'unpaced, the loading' and st == 8:
                pressed = g.frame(); at = (st, g.value(cd.PHASE, 2))
                g.q(cmd='press', buttons=cd.START, frames=1200)
                g.wait(lambda: g.value(cd.STATE, 2) != 8 or g.value(cd.PHASE, 2) == 17, 'the black never ended', 60)
                taken = g.frame(); at += (g.value(cd.STATE, 2), g.value(cd.PHASE, 2))
            elif moment == 'scene' and scene is not None and g.frame() - scene > 300:
                pressed = taken = g.frame(); at = (st, g.value(cd.PHASE, 2)); g.press(cd.START)
            time.sleep(.02)
        if pressed is None: print(f'start {moment}: the moment never came'); return False
        rows.append(f'Start at frame {pressed}, state {at[0]} phase {at[1]}' +
                    (f', taken by frame {taken}: state {at[2]} phase {at[3]}' if len(at) > 2 else ''))
        try:
            g.wait(lambda: g.value(cd.STATE, 2) == 4, 'no modes menu', 60)
        except AssertionError:
            rows.append('the modes menu never came  <- ECHEC'); ok = False
        if ok:
            # Not long: the menu goes back to the title after 481 frames without input
            # (0x1E1, ovl5), a few seconds headless.
            time.sleep(.5)
            menu_frame = g.frame()
            try:
                cd.to_arcade_guest(g, guest)
                g.wait(lambda: g.value(cd.STATE, 2) == 8 and g.value(cd.PHASE, 2) == 8, 'no round', 180)
                rows.append(f'Arcade with {guest} from the menu: first round at frame {g.frame()}')
            except Exception as e:
                rows.append(f'Arcade with {guest} from the menu: {e}  <- ECHEC'); ok = False
            rows.append(f'menu at frame {menu_frame}')
    finally:
        alive = g.process.poll() is None
        g.stop()
    log = (out / 'game.log').read_text(errors='replace')
    paces = [(int(f), p) for f, p in PACE.findall(log)]
    after = [(f, p) for f, p in paces if f >= pressed]
    back = next((f for f, p in after if p == "the player's"), None)
    if back is None or back - taken > LEFT_MAX:
        rows.append(f"pace after Start: {after}  <- ECHEC (not the player's within {LEFT_MAX} frames)"); ok = False
    elif any(p != "the player's" for f, p in after if f > back):
        rows.append(f"pace after Start: {after}  <- ECHEC (left the player's again)"); ok = False
    else:
        rows.append(f"pace the player's again {back - taken} frames after the game took Start")
    if 'Cine scene: left' not in log: rows.append('no "Cine scene: left" in the log  <- ECHEC'); ok = False
    if not alive: rows.append('the game was gone at the end  <- ECHEC'); ok = False
    for l in log.splitlines():
        if l.startswith(('Cine scene:', 'Cine:')) and 'pace' not in l and 'hold' not in l: rows.append('  log: ' + l)
    (out / 'pace.txt').write_text('\n'.join(rows) + '\n')
    print(f'start {moment}:'); print('\n'.join('  ' + r for r in rows))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--mods', default='off,on,check')
    ap.add_argument('--start', default='', help='B109: black,scene (Start pressed then), in place of --mods')
    a = ap.parse_args()
    if a.start: ok = all([run_start(ROOT / a.build, a.out / f'start-{m}', m) for m in a.start.split(',')])
    else: ok = all([run(ROOT / a.build, a.out / s, s) for s in a.mods.split(',')])
    print('OK' if ok else 'ECHEC')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
