#!/usr/bin/env python3
"""B94 (GH#133, Ogre's win poses): what the winner's scene leaves uncovered
on the arcade stages, measured by the magenta of B87.

    python ressources/slot.py --kind game --who b94 --prio 2 -- \\
        python tools/arcade_stages/win_pose_check.py OUT --build build-dbg --fighter ogre --arenas 0-12
        [--source t3|ttt] [--buttons triangle,square,cross,circle] [--aspect 16:9|4:3] [--mode mod|off]

(a PSX_DEBUG_TOOLS=ON build with the arcade stage packs, and the TTT ones
with --source ttt; a Python with numpy and Pillow)

T3 never clears its 3D frame (TIPS sections 31, 93): a place nothing of the
frame covers keeps an older frame (the "sky" of GH#133). With
TEKKEN3_ARCADE_STAGES_HOLES the stage puts magenta under everything, far
background included (T3 stages and TTT stages): every magenta pixel of a
screenshot is such a place.

One cold start per arena (sky_check.to_fight: Arcade, player 1 forced to
--fighter, every fight on the arena), then per button of --buttons: once a
round runs, player 2's life goes to 0 and the button is held without a break
through the K.O. (the win pose reads it once: Triangle, Square, Cross and
Circle give the four poses, TIPS section 154), screenshots as fast as they
come until the next round; each sample notes the camera's state (round_kind
0x8009546C: 2 the fight and its slow motion, 3..5 the winner's scene) and
pitch (0x800A85C0, negative: looking up). Fails when a sample of the
winner's scene has more than --limit magenta pixels (a frame over --cut of
the picture is the unfinished last one before a cut, B79, and does not
count). --mode off: the PS1 stage (Arcade Stages off), no magenta: a
reference of the pitches only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sky_check as K  # noqa: E402
import stage_check as S  # noqa: E402

ROUND_KIND = 0x8009546C
BUTTONS = dict(triangle=0xEFFF, circle=0xDFFF, cross=0xBFFF, square=0x7FFF)


def magenta(png: Path):
    a = np.asarray(Image.open(png).convert('RGB'))
    m = (a[..., 0] >= 230) & (a[..., 1] <= 24) & (a[..., 2] >= 230)
    return int(m.sum()), float(m.mean())


def one(args, arena: int) -> dict:
    out = Path(args.out).resolve() / f'{args.source}{arena:02}-{args.aspect.replace(":", "x")}'
    out.mkdir(parents=True, exist_ok=True)
    # the stage's source forced (STAGES auto lets player 2's native decide)
    env = {'TEKKEN3_NATIVE_MOVES': '0', 'TEKKEN3_ARCADE_STAGES_HOLES': '1', 'TEKKEN3_STAGES': args.source}
    fight_arena = arena
    if args.source == 'ttt' and arena in K.TTT_ARENA:
        fight_arena = K.TTT_ARENA[arena]
        env['TEKKEN3_TTT_STAGES_FORCE'] = f'{arena}@8'
    g = S.Game(Path(args.build).resolve(), out / 'run', args.mode, args.renderer, Path(args.packs).resolve(),
               widescreen=args.aspect == '16:9', env_extra=env,
               ttt=Path(args.ttt_packs).resolve() if args.source == 'ttt' else None, ttt1=args.ttt1)
    fighter = K.FIGHTERS[args.fighter] if args.fighter in K.FIGHTERS else int(args.fighter, 0)
    samples, last = [], [-1]

    def take(button):
        n = g.q(cmd='gpu_ring_stats')['newest_frame']
        if n == last[0]:
            return
        last[0] = n
        kind, pitch, move = g.value(ROUND_KIND, 1), K.s12(g.value(K.CAMERA)), g.value(K.ACTOR + K.MOVE, 2)
        png = out / f'{button}-{n:06}.png'
        g.q(cmd='screenshot', path=str(png))
        px, share = magenta(png) if args.mode == 'mod' else (0, 0.0)
        cut = share > args.cut
        scene = 3 <= kind <= 5
        s = dict(button=button, frame=n, kind=kind, pitch=pitch, move=move, holes=px, cut=cut,
                 bad=scene and not cut and px > args.limit)
        samples.append(s)
        if not (s['bad'] or (args.keep and scene)):
            png.unlink()

    try:
        K.to_fight(g, fight_arena, fighter)
        for button in args.buttons.split(','):
            g.wait(lambda: g.value(S.SCREEN) == 8 and g.value(S.PHASE, 2) >= 8
                   and g.value(K.ACTOR + K.STRIDE + K.LIFE, 2) > 0 and g.value(ROUND_KIND, 1) == 2, 'no round to win', 120)
            time.sleep(1.5)
            g.q(cmd='write_ram', addr=f'{K.ACTOR + K.STRIDE + K.LIFE:08x}', bytes='0000')
            g.q(cmd='press', buttons=BUTTONS[button], frames=int(args.seconds * 60))
            t0 = time.monotonic()
            while time.monotonic() - t0 < args.seconds:
                if g.value(S.SCREEN) != 8 or (time.monotonic() - t0 > 3 and g.value(ROUND_KIND, 1) == 1):
                    break       # the next round's intro (or the match is over)
                take(button)
            g.q(cmd='set_input', buttons='ffff', port=1)
            # a match won: Arcade's next fight, on the same arena (the next
            # wait covers its loading screen)
    finally:
        g.stop()
    log = (out / 'run/game.log').read_text(errors='replace')
    loaded = re.findall(r'arcade stages: (TTT stage|stage) (\d+) loaded', log)
    if not loaded or any((kind == 'TTT stage') != (args.source == 'ttt') for kind, n in loaded):
        raise SystemExit(f'not the stage wanted: {loaded}')
    (out / 'samples.json').write_text(json.dumps(samples, indent=0))
    scene = [s for s in samples if 3 <= s['kind'] <= 5 and not s['cut']]
    res = dict(source=args.source, arena=arena, fighter=fighter, samples=len(samples), scene=len(scene),
               bad=sum(s['bad'] for s in scene), worst=max([s['holes'] for s in scene] or [0]),
               with_holes=sum(s['holes'] >= 8 for s in scene), lowest_pitch=min([s['pitch'] for s in scene] or [0]),
               moves=sorted({s['move'] for s in scene}),
               by_button={b: dict(n=sum(s['button'] == b for s in scene),
                                  worst=max([s['holes'] for s in scene if s['button'] == b] or [0]),
                                  lowest_pitch=min([s['pitch'] for s in scene if s['button'] == b] or [0]))
                          for b in args.buttons.split(',')})
    print(f'{args.source} {arena:2}: {res["bad"]} of {res["scene"]} scene samples over {args.limit} magenta pixels; '
          f'worst {res["worst"]}, with holes {res["with_holes"]}, lowest pitch {res["lowest_pitch"]}; '
          + ', '.join(f'{b} {v["n"]}/{v["worst"]}/{v["lowest_pitch"]}' for b, v in res['by_button'].items()),
          flush=True)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--fighter', default='ogre', help='gunjack, ogre, trueogre or a T3 number')
    ap.add_argument('--arenas', default='0-12')
    ap.add_argument('--source', choices=('t3', 'ttt'), default='t3')
    ap.add_argument('--buttons', default='triangle,square,cross,circle')
    ap.add_argument('--aspect', choices=('16:9', '4:3'), default='16:9')
    ap.add_argument('--renderer', default='opengl')
    ap.add_argument('--mode', choices=('mod', 'off'), default='mod')
    ap.add_argument('--seconds', type=float, default=16, help='at most, from the K.O. to the next round')
    ap.add_argument('--limit', type=int, default=300, help='magenta pixels that fail a frame (B87)')
    ap.add_argument('--cut', type=float, default=0.02, help='magenta share of an unfinished frame before a cut')
    ap.add_argument('--keep', action='store_true', help="keep every screenshot of the winner's scene")
    ap.add_argument('--packs', default=str(S.PACKS))
    ap.add_argument('--ttt-packs', default=str(S.TTT_PACKS))
    ap.add_argument('--ttt1', default=str(S.ROOT / 'workspace/ttt1-catalogue'))
    args = ap.parse_args()
    results = [one(args, a) for a in ranges(args.arenas)]
    name = f'summary-{args.source}-{args.fighter}-{args.aspect.replace(":", "x")}.json'
    (Path(args.out) / name).write_text(json.dumps(results, indent=1))
    bad = sum(r['bad'] for r in results)
    print(f'{bad} failing samples of {sum(r["scene"] for r in results)} on {len(results)} arenas '
          f'({args.source}, {args.fighter}, {args.aspect})')
    sys.exit(1 if bad else 0)


def ranges(text):
    out = []
    for part in text.split(','):
        a, _, b = part.partition('-')
        out += range(int(a), int(b or a) + 1)
    return out


if __name__ == '__main__':
    main()
