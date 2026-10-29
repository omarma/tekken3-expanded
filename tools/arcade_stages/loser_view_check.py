#!/usr/bin/env python3
"""B110 (GH#156, the loser's view): YOU LOSE, CONTINUE? and GAME OVER keep
the PS1's camera on the T3 arcade stages, as on every other stage.

    python ressources/slot.py --kind game --who b110 --prio 2 -- \\
        python tools/arcade_stages/loser_view_check.py OUT --build build-dbg --arenas 0-12
        [--mode mod|off] [--time-attack] [--aspect 16:9|4:3]

(a PSX_DEBUG_TOOLS=ON build with the arcade stage packs; a Python with
numpy and Pillow)

One cold start per arena (stage_check.Game, TEKKEN3_STAGES=t3, every
fighter record on the arena, TIPS section 25): Arcade (or Time Attack),
player 1 as the selector leaves him, K.O.'d in each round he runs (life
0x800A961E to 0) until the match is lost. Then, as fast as frames come
until the screen leaves the fight, each sample of the loser's view
(round_kind 0x8009546C = 6, K.O. so camera_fixed_view 0x800B040C = 1) notes
the camera's eye height (0x800A85D8) and the magenta pixels of
TEKKEN3_ARCADE_STAGES_HOLES (stage_check, B87). Fails when the eye is not
the PS1's -0x1EAD (B87's arcade view was z * 8000 / 955 up, -5827) or a
frame has more than --limit magenta pixels. --mode off: the PS1 stage, a
reference of the height only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stage_check as S  # noqa: E402
from win_pose_check import ranges, magenta  # noqa: E402

ACTOR, STRIDE, LIFE = 0x800A9228, 0x188C, 0x3F6
ROUND_KIND, FIXED_VIEW, EYE_Y = 0x8009546C, 0x800B040C, 0x800A85D8
PS1_HEIGHT = -0x1EAD
TIME_ATTACK_LINE = 4    # the modes menu's line (VS hidden without a second pad)


def s32(v):
    return v - (1 << 32) if v >> 31 else v


def one(args, arena: int) -> dict:
    out = Path(args.out).resolve() / f'{args.mode}{arena:02}'
    out.mkdir(parents=True, exist_ok=True)
    env = {'TEKKEN3_NATIVE_MOVES': '0', 'TEKKEN3_ARCADE_STAGES_HOLES': '1', 'TEKKEN3_STAGES': 't3'}
    g = S.Game(Path(args.build).resolve(), out / 'run', args.mode, args.renderer, Path(args.packs).resolve(),
               widescreen=args.aspect == '16:9', env_extra=env)
    samples, last = [], [-1]
    try:
        g.q(cmd='turbo', enabled=1)

        def menu():
            if g.value(S.SCREEN) == 3:
                g.write(0x80097f26, 1); g.write(0x80097f27, 1); g.write(0x80097f1e, 1)
                g.press(S.START)
            return g.value(S.SCREEN) == 4
        g.wait(menu, 'the modes menu never came', 180)
        g.q(cmd='turbo', enabled=0)
        time.sleep(.3)
        g.write(S.LINE, TIME_ATTACK_LINE if args.time_attack else 0, 4)
        g.press(S.CROSS)
        g.wait(lambda: g.value(S.SCREEN) == 9, 'the selector never came', 30)
        time.sleep(1.5)
        S.force_arena(g, arena)

        def chosen():
            if g.value(S.SCREEN) == 9:
                g.press(S.CROSS); time.sleep(.4)
            return g.value(S.SCREEN) == 8 and g.value(S.PHASE, 2) >= 6
        g.wait(chosen, 'the fight never came', 150)
        mode = g.value(0x800AFA88, 1)
        while g.value(S.SCREEN) == 8 and g.value(ROUND_KIND, 1) != 6:
            if g.value(ROUND_KIND, 1) == 2 and g.value(ACTOR + LIFE, 2) > 0:
                time.sleep(1.0)
                if g.value(ROUND_KIND, 1) == 2:
                    g.write(ACTOR + LIFE, 0, 2)
            time.sleep(.05)
        while g.value(S.SCREEN) == 8:
            n = g.q(cmd='gpu_ring_stats')['newest_frame']
            if n == last[0] or g.value(ROUND_KIND, 1) != 6 or not g.value(FIXED_VIEW):
                time.sleep(.005)
                continue
            last[0] = n
            eye = s32(g.value(EYE_Y))
            png = out / f'{n:06}.png'
            g.q(cmd='screenshot', path=str(png))
            px = magenta(png)[0] if args.mode == 'mod' else 0
            bad = eye != PS1_HEIGHT or px > args.limit
            samples.append(dict(frame=n, eye=eye, holes=px, bad=bad))
            if not (bad or args.keep):
                png.unlink()
    finally:
        g.stop()
    (out / 'samples.json').write_text(json.dumps(samples, indent=0))
    res = dict(mode=args.mode, arena=arena, game_mode=mode, samples=len(samples), bad=sum(s['bad'] for s in samples),
               heights=sorted({s['eye'] for s in samples}), worst=max([s['holes'] for s in samples] or [0]))
    if not samples:
        res['bad'] = 1      # no loser's view seen
    print(f'{args.mode} {arena:2} (game mode {mode}): {res["samples"]} samples of the loser\'s view, '
          f'heights {res["heights"]}, worst {res["worst"]} magenta pixels, {res["bad"]} failing', flush=True)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--arenas', default='0-12')
    ap.add_argument('--mode', choices=('mod', 'off'), default='mod')
    ap.add_argument('--time-attack', action='store_true')
    ap.add_argument('--aspect', choices=('16:9', '4:3'), default='16:9')
    ap.add_argument('--renderer', default='software')
    ap.add_argument('--limit', type=int, default=300, help='magenta pixels that fail a frame (B87)')
    ap.add_argument('--keep', action='store_true', help='keep every screenshot of the loser\'s view')
    ap.add_argument('--packs', default=str(S.PACKS))
    args = ap.parse_args()
    results = [one(args, a) for a in ranges(args.arenas)]
    (Path(args.out) / f'summary-{args.mode}.json').write_text(json.dumps(results, indent=1))
    bad = sum(r['bad'] for r in results)
    print(f'{bad} failing samples on {len(results)} arenas ({args.mode})')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
