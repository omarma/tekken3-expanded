#!/usr/bin/env python3
"""B87 (GH#142): holes in the T3 arcade stages under the K.O. cameras (the
K.O.'s slow motion, its REPLAY, the winner's pose), measured.

    python ressources/slot.py --kind game --who b87 --prio 2 -- \\
        python tools/test_arcade_stage_holes.py workspace/b87/check --build build-dbg --arenas 0-12 [--aspect 4:3]

(a PSX_DEBUG_TOOLS=ON build with the arcade stage packs; a Python with numpy
and Pillow)

T3 never clears its 3D frame (TIPS sections 31, 93): a place nothing of the
frame covers keeps an older frame. TEKKEN3_ARCADE_STAGES_HOLES puts magenta
under everything (far background included): every magenta pixel of a
screenshot is such a place, slits a pixel wide and transparent texels with
nothing behind included, which polygon coverage (stage_check.coverage)
counts as covered.

One run per arena: a cold start (stage_check.Game: OpenGL x1 in a window,
the software renderer without one draws no 16:9 margins), Arcade on the
arena, a few seconds of fight (screenshots every second), then --kos rounds
ended by a jab on player 2 left at 1 of life (a life written to 0 gives no
replay), screenshots as fast as they come until the next round: slow
motion, REPLAY and, at the match's end, YOU WIN. A frame with more than
--cut of the picture magenta is the unfinished last frame before a cut (B79)
and does not count. Fails when a frame has more than --limit magenta pixels:
on dev before B87, 58 samples of 4 160 (13 arenas, 16:9), up to 3 711 pixels;
after it, 0 of 3 784, at most 29 (TIPS section 161).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/arcade_stages'))
import stage_check as sc  # noqa: E402

P1_LIFE, P2_LIFE = 0x800A961E, 0x800AAEAA   # u16, given in phase 8 (TIPS section 94)
TIMER = 0x800ADBCC                          # frames left in the round, from 2400
FORWARD, JAB = 0xFFDF, 0x7FDF               # right; right + square ('press' wants an integer)


def ranges(text):
    out = []
    for part in text.split(','):
        a, _, b = part.partition('-')
        out += range(int(a), int(b or a) + 1)
    return out


def magenta(png: Path):
    a = np.asarray(Image.open(png).convert('RGB'))
    m = (a[..., 0] >= 230) & (a[..., 1] <= 24) & (a[..., 2] >= 230)
    return int(m.sum()), float(m.mean())


def one(args, arena: int) -> dict:
    out = Path(args.out).resolve() / f'a{arena:02}-{args.aspect.replace(":", "x")}'
    out.mkdir(parents=True, exist_ok=True)
    g = sc.Game(Path(args.build).resolve(), out / 'run', 'mod', args.renderer, Path(args.packs).resolve(),
                widescreen=args.aspect == '16:9',
                env_extra={'TEKKEN3_ARCADE_STAGES_HOLES': '1', **dict(e.split('=', 1) for e in args.env)})
    samples, last = [], [-1]

    def take(label):
        n = g.q(cmd='gpu_ring_stats')['newest_frame']
        if n == last[0]:
            return
        last[0] = n
        png = out / f'{label}-{n:06}.png'
        g.q(cmd='screenshot', path=str(png))
        px, share = magenta(png)
        cut = share > args.cut
        s = dict(label=label, frame=n, holes=px, cut=cut, bad=not cut and px > args.limit)
        samples.append(s)
        if not s['bad'] and not (cut and args.keep_cuts):
            png.unlink()

    try:
        sc.to_fight(g, arena)
        g.wait(lambda: g.value(sc.PHASE, 2) == 8 and g.value(P1_LIFE, 2) > 0 and g.value(P2_LIFE, 2) > 0,
               'the lives never came', 30)
        full = g.value(P1_LIFE, 2), g.value(P2_LIFE, 2)
        end, nxt = time.monotonic() + args.fight, 0.0
        while time.monotonic() < end and g.value(sc.SCREEN) == 8:
            g.write(P1_LIFE, full[0], 2); g.write(P2_LIFE, full[1], 2); g.write(TIMER, 2400, 2)
            g.q(cmd='set_input', buttons=f'{FORWARD:04x}', port=1)
            if time.monotonic() > nxt:
                take('fight')
                nxt = time.monotonic() + 1
            time.sleep(.05)
        g.q(cmd='set_input', buttons='ffff', port=1)
        for ko in range(args.kos):
            g.wait(lambda: g.value(sc.SCREEN) != 8 or g.value(P2_LIFE, 2) > 0, 'no round running', 60)
            if g.value(sc.SCREEN) != 8:
                break
            time.sleep(1.5)
            t0 = time.monotonic()
            while g.value(sc.SCREEN) == 8 and g.value(P2_LIFE, 2) > 0 and time.monotonic() - t0 < 30:
                g.write(P2_LIFE, 1, 2); g.write(P1_LIFE, full[0], 2); g.write(TIMER, 2400, 2)
                g.q(cmd='set_input', buttons=f'{FORWARD:04x}', port=1)
                time.sleep(.2)
                g.q(cmd='press', buttons=JAB, frames=3)
                time.sleep(.15)
            g.q(cmd='set_input', buttons='ffff', port=1)
            t0 = time.monotonic()
            while time.monotonic() - t0 < args.ko_seconds:
                if g.value(sc.SCREEN) != 8 or (time.monotonic() - t0 > 2 and g.value(P2_LIFE, 2) == full[1]):
                    break
                take(f'ko{ko + 1}')
    finally:
        g.stop()
    (out / 'samples.json').write_text(json.dumps(samples, indent=0))
    counted = [s for s in samples if not s['cut']]
    res = dict(arena=arena, samples=len(counted), cuts=len(samples) - len(counted),
               bad=sum(s['bad'] for s in counted),
               fight_max=max([s['holes'] for s in counted if s['label'] == 'fight'] or [0]),
               ko_max=max([s['holes'] for s in counted if s['label'] != 'fight'] or [0]),
               ko_with_holes=sum(s['holes'] >= 8 for s in counted if s['label'] != 'fight'),
               ko_samples=sum(s['label'] != 'fight' for s in counted))
    print(f'arena {arena}: {res["bad"]} of {res["samples"]} samples over {args.limit} magenta pixels; worst fight '
          f'{res["fight_max"]}, K.O. {res["ko_max"]}; K.O. samples with holes {res["ko_with_holes"]} of '
          f'{res["ko_samples"]}', flush=True)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--arenas', default='0-12')
    ap.add_argument('--aspect', choices=('16:9', '4:3'), default='16:9')
    ap.add_argument('--renderer', default='opengl')
    ap.add_argument('--fight', type=float, default=5, help='seconds of fight before the K.O.s')
    ap.add_argument('--kos', type=int, default=2)
    ap.add_argument('--ko-seconds', type=float, default=25)
    ap.add_argument('--limit', type=int, default=300, help='magenta pixels that fail a frame')
    ap.add_argument('--cut', type=float, default=0.02, help='magenta share of an unfinished frame before a cut')
    ap.add_argument('--keep-cuts', action='store_true')
    ap.add_argument('--packs', default=str(sc.PACKS))
    ap.add_argument('--env', action='append', default=[], help='NAME=VALUE for the game (a build without the switch)')
    args = ap.parse_args()
    results = [one(args, a) for a in ranges(args.arenas)]
    (Path(args.out) / f'summary-{args.aspect.replace(":", "x")}.json').write_text(json.dumps(results, indent=1))
    bad = sum(r['bad'] for r in results)
    print(f'{bad} failing samples of {sum(r["samples"] for r in results)} on {len(results)} arenas ({args.aspect})')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
