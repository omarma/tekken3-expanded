#!/usr/bin/env python3
"""B78: the TTT Embu of the attract after an Arcade game is drawn from its own camera.

    python tools/test_cine_embu_after_arcade.py OUT [--guest kazuya] [--build build-rel-lite]
                                                 [--keep-flag] [--cold] [--reference DIR] [--visible]

Arcade with a guest (tools/cine_drive.py), player 1 idle until the game over,
then the attract's TTT Embu (the engine's scene, `attract every=2`, TIPS 115),
frames 800, 1200, 1700 and 2100 held and shot. The winner's camera at the end
of a match (0x8006895C) may leave the fixed view on (camera_fixed_view
0x800B040C), which the fight clears at its phase 7 and the scene skipped:
the fighters' view matrix (0x800ADE20) was the fixed view's, the camera's
world matrix (0x800ADF70) recentred by 0xA3A, and the Embu's Jin faced the
camera at 800, Xiaoyu stood too close at 1200, Hwoarang and Devil Jin were out
of the frame at 1700 and 2100. How the CPU wins decides it: the flag is set to
1 as the scene loads, unless --keep-flag. Each held frame must have the flag
off and the fighters' view matrix equal to the world matrix. --cold plays the
attract's Embu from a cold start (no Arcade), the reference; --reference DIR
also wants the shots identical to DIR's. Exit 1 on a failure. OUT/result.json.
Run through ressources/slot.py (--kind game), one game per run.
"""
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cine_drive as cd

FIXED_VIEW, VIEW, WORLD = 0x800b040c, 0x800ade20, 0x800adf70
HELD = (800, 1200, 1700, 2100)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path)
    ap.add_argument('--guest', default='kazuya')
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--keep-flag', action='store_true')
    ap.add_argument('--cold', action='store_true')
    ap.add_argument('--reference', type=Path)
    ap.add_argument('--visible', action='store_true')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_CINE_HOLD': ','.join(map(str, HELD)), 'TEKKEN3_CINE_HOLD_TICKS': '600'}
    g = cd.Game(ROOT / a.build, a.out, env, a.visible, mods_state='format_version = 2\n')
    frames, failed, flag_found = {}, [], None
    try:
        if a.cold: g.q(cmd='turbo', enabled=1)
        else:
            cd.to_arcade_guest(g, a.guest)
            g.q(cmd='turbo', enabled=1)
        end = time.monotonic() + 1800
        while 'Cine scene: loading' not in g.log():
            if time.monotonic() > end: raise AssertionError('the TTT Embu never came')
            time.sleep(.05)
        g.q(cmd='turbo', enabled=0)
        flag_found = g.value(FIXED_VIEW)
        print(f'camera_fixed_view as the scene loads: {flag_found}')
        if not a.cold and not a.keep_flag: g.write(FIXED_VIEW, 1)
        seen = set()
        while len(seen) < len(HELD):
            if time.monotonic() > end: raise AssertionError(f'held frames seen: {sorted(seen)}')
            log = g.log()
            if 'Cine scene: over' in log: break
            for h in map(int, re.findall(r'Cine: hold frame (\d+)', log)):
                if h in seen: continue
                seen.add(h); time.sleep(.3)
                shot = a.out / f'cine_{h:05d}.png'
                g.q(cmd='screenshot_file', path=str(shot.resolve()))
                flag, view, world = g.value(FIXED_VIEW), g.read(VIEW, 32), g.read(WORLD, 32)
                ok = flag == 0 and view == world
                frames[h] = {'fixed_view': flag, 'view': view.hex(), 'world': world.hex(), 'ok': ok}
                print(f'frame {h}: fixed view {flag}, view matrix {"=" if view == world else "!="} world matrix:',
                      'OK' if ok else 'ECHEC', flush=True)
                if not ok: failed.append(h)
            time.sleep(.05)
    finally:
        g.stop()
    if sorted(frames) != list(HELD): failed.append('frames'); print('held frames missing:', sorted(frames))
    if a.reference:
        try:
            from PIL import Image, ImageChops
            def identical(x, y):
                return ImageChops.difference(Image.open(x).convert('RGB'), Image.open(y).convert('RGB')).getbbox() is None
        except ImportError:         # the game's PNGs of the same image are the same bytes
            def identical(x, y): return x.read_bytes() == y.read_bytes()
        for h in HELD:
            mine, ref = a.out / f'cine_{h:05d}.png', a.reference / f'cine_{h:05d}.png'
            same = mine.is_file() and ref.is_file() and identical(mine, ref)
            print(f'frame {h}: shot {"identical to" if same else "differs from"} the reference')
            if not same: failed.append(f'shot {h}')
    (a.out / 'result.json').write_text(json.dumps({'flag_found': flag_found, 'frames': frames, 'failed': failed}, indent=1))
    print('OK' if not failed else f'ECHEC {failed}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
