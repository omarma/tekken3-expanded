#!/usr/bin/env python3
"""B77: holes in the TTT stages under the throw, K.O. replay and YOU WIN
cameras, measured.

    python ressources/slot.py --kind game --who b77 --prio 2 -- \\
        python tools/test_ttt_stage_holes.py workspace/b77/run --build build-dbg --stages 0-14 [--aspect 4:3]

(a PSX_DEBUG_TOOLS=ON build with the TTT1 catalogue, the T3 and TTT stage
packs; a Python with Pillow, as stage_check.py --coverage)

T3 never clears its 3D frame (TIPS sections 31, 93): a place no primitive of
the frame covers keeps an older frame, the "smear" the player sees. One run
per stage: a cold start of the build (stage_check.Game: OpenGL x1 in a
window, the software renderer without one draws no 16:9 margins), Arcade on
TTT stage n (STAGES = TTT, the arena of every fighter record set to n; 13
and 14 forced by TEKKEN3_TTT_STAGES_FORCE in arenas 10 and 6), player 1
walking in and throwing (1+3; lives and round timer held), then each round
ended by a jab on player 2 left at 1 of life (a life written to 0 gives no
replay): the K.O.'s slow motion, its REPLAY and, at the match's end, the
winner's pose.

Each sample is one frame's GP0 commands (gpu_frame_dump) rasterized on the
16:9 canvas (stage_check.coverage): the uncovered share of the 4:3 picture
and of each margin. Samples are taken while the camera is the fight's
(0x800A8C70 = 1) every few seconds, and as fast as the dumps go while it is
another (throws), and through each K.O. (replay, YOU WIN); with --lose,
through the CONTINUE? countdown of a fight player 1 then loses (its camera
looks from above). A sample with an uncovered share above --limit in the
4:3 picture, or above --margin-limit in a 16:9 margin, fails the check (4:3:
the picture only); a frame with no primitive at all (a screen change) does
not count. Blind spot: a primitive counts as covering even where its texels
are transparent (TIPS, B77: a magenta screen behind the stage, a diagnostic
patch, measured those).

--source t3 runs the same on the T3 arcade stage of the arena (Arcade
Stages), --source ps1 with both stage mods off (the PS1 stage): references.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/arcade_stages'))
import stage_check as sc  # noqa: E402

CAMERA_MODE = 0x800A8C70        # 1 = the fight's camera (B74: 6 = a throw's)
P1_LIFE, P2_LIFE = 0x800A961E, 0x800AAEAA  # u16, the round ends at 0 (TIPS section 94)
TIMER = 0x800ADBCC              # frames left in the round, from 2400
FORWARD, THROW, JAB = 0xFFDF, 0x3FDF, 0x7FDF  # right; right + square + cross (1+3); right + square
TTT_ARENA = {13: 10, 14: 6}     # Eddy-A, Unknown: no arena of their own, forced in these


def stages_of(text):
    out = []
    for part in text.split(','):
        a, _, b = part.partition('-')
        out += range(int(a), int(b or a) + 1)
    return out


class Sampler:
    def __init__(self, g, out: Path, limit: float, margin_limit: float, keep: int):
        self.g, self.out, self.limit, self.margin_limit, self.keep = g, out, limit, margin_limit, keep
        self.samples, self.last_frame, self.kept = [], -1, 0

    def take(self, label):
        g = self.g
        n = g.q(cmd='gpu_ring_stats')['newest_frame'] - 1
        if n == self.last_frame:
            return None
        self.last_frame = n
        cam = g.value(CAMERA_MODE, 2)
        phase = g.value(sc.PHASE, 2)
        entries = g.q(cmd='gpu_frame_dump', frame=n, count=40000)['entries']
        shares = sc.coverage(entries)
        s = dict(label=label, frame=n, camera=cam, phase=phase, left=shares[0], picture=shares[1], right=shares[2])
        # a frame with no primitive at all (a screen change) is no stage hole
        s['empty'] = min(shares) == 1.0
        s['bad'] = not s['empty'] and (shares[1] > self.limit or
                                       (self.margin_limit is not None and max(shares[0], shares[2]) > self.margin_limit))
        self.samples.append(s)
        if s['bad'] and self.kept < self.keep:      # the evidence: holes mask and the frame
            self.kept += 1
            stem = self.out / f'{label}-{n}'
            sc.coverage(entries, stem.with_suffix('.holes.png'))
            with gzip.open(stem.with_suffix('.gp0.json.gz'), 'wt') as f:
                json.dump(entries, f)
            try:
                g.q(cmd='screenshot', path=str(stem.with_suffix('.png')))
            except RuntimeError:
                pass
        return s


def one_stage(args, stage: int) -> dict:
    out = Path(args.out).resolve() / f'{args.source}-{stage:02}-{args.aspect.replace(":", "x")}'
    out.mkdir(parents=True, exist_ok=True)
    arena = TTT_ARENA.get(stage, stage)
    env = dict(e.split('=', 1) for e in args.env)
    if args.source == 'ttt' and stage in TTT_ARENA:
        env['TEKKEN3_TTT_STAGES_FORCE'] = f'{stage}@8'
    mode = 'off' if args.source == 'ps1' else 'mod'
    g = sc.Game(Path(args.build).resolve(), out / 'run', mode, args.renderer, Path(args.packs).resolve(),
                widescreen=args.aspect == '16:9',
                ttt=Path(args.ttt_packs).resolve() if args.source in ('ttt', 'ps1') else None,
                ttt1=args.ttt1, env_extra=env)
    # 4:3: no margins drawn at all, only the picture counts
    sm = Sampler(g, out, args.limit, args.margin_limit if args.aspect == '16:9' else None, args.keep)
    try:
        sc.to_fight(g, arena)
        print(f'stage {stage}: arena {g.value(sc.ARENA, 2)}, fight running', flush=True)
        # the lives are given in phase 8 (TIPS section 94)
        g.wait(lambda: g.value(sc.PHASE, 2) == 8 and g.value(P1_LIFE, 2) > 0 and g.value(P2_LIFE, 2) > 0,
               'the lives never came', 30)
        full = g.value(P1_LIFE, 2), g.value(P2_LIFE, 2)
        end = time.monotonic() + args.fight
        next_fight = next_throw = 0.0
        throws = 0
        prev_cam = 1
        cams = {}
        while time.monotonic() < end:
            if g.value(sc.SCREEN) != 8:
                break
            cam = g.value(CAMERA_MODE, 2)
            cams[cam] = cams.get(cam, 0) + 1
            g.write(P1_LIFE, full[0], 2)        # nobody wins this part
            g.write(P2_LIFE, full[1], 2)
            g.write(TIMER, 2400, 2)
            if cam != 1:
                throws += prev_cam == 1
                g.q(cmd='set_input', buttons='ffff', port=1)
                sm.take('throw')
            else:
                if time.monotonic() > next_throw:   # walk in, 1+3
                    g.q(cmd='press', buttons=THROW, frames=3)
                    next_throw = time.monotonic() + .4
                else:
                    g.q(cmd='set_input', buttons=f'{FORWARD:04x}', port=1)
                if time.monotonic() > next_fight:
                    sm.take('fight')
                    next_fight = time.monotonic() + 3
            prev_cam = cam
            time.sleep(.03)
        g.q(cmd='set_input', buttons='ffff', port=1)
        print(f'stage {stage}: {throws} throw cameras; camera modes polled {cams}', flush=True)
        for ko in range(args.kos):
            # player 2's life to 0 in a running round: the K.O., its replay and
            # (the match's end) the winner's pose, until the next round gives
            # the lives back
            g.wait(lambda: g.value(sc.SCREEN) != 8 or g.value(P2_LIFE, 2) > 0, 'no round running', 60)
            if g.value(sc.SCREEN) != 8:
                break
            time.sleep(2)
            # a hit ends it (a life written to 0 has no replay): player 2 at
            # 1, player 1 walks in with jabs
            t0 = time.monotonic()
            while g.value(sc.SCREEN) == 8 and g.value(P2_LIFE, 2) > 0 and time.monotonic() - t0 < 30:
                g.write(P2_LIFE, 1, 2)
                g.write(P1_LIFE, full[0], 2)
                g.q(cmd='press', buttons=JAB, frames=3)
                time.sleep(.15)
            g.q(cmd='set_input', buttons='ffff', port=1)
            t0 = time.monotonic()
            while time.monotonic() - t0 < args.ko_seconds:
                if g.value(sc.SCREEN) != 8 or (time.monotonic() - t0 > 1 and g.value(P2_LIFE, 2) > 0):
                    break
                s = sm.take(f'ko{ko + 1}')
                if s and args.shots and len(sm.samples) % args.shots == 0:
                    g.q(cmd='screenshot', path=str(out / f'ko{ko + 1}-{s["frame"]}-cam{s["camera"]}-ph{s["phase"]}.png'))
                time.sleep(.02)
            print(f'stage {stage}: K.O. {ko + 1} sampled', flush=True)
        if args.lose:
            # the next fight lost by player 1 (life written to 0 each round):
            # YOU LOSE, then the CONTINUE? countdown's camera from above
            t0 = time.monotonic()
            while time.monotonic() - t0 < 90 and g.value(sc.PHASE, 2) < 10:
                if g.value(sc.SCREEN) == 8 and g.value(sc.PHASE, 2) == 8 and g.value(P1_LIFE, 2) > 0:
                    time.sleep(1)
                    g.write(P1_LIFE, 0, 2)
                time.sleep(.2)
            t0 = time.monotonic()
            while time.monotonic() - t0 < args.ko_seconds and g.value(sc.SCREEN) == 8 and g.value(sc.PHASE, 2) >= 10:
                sm.take('continue')
                time.sleep(.02)
            print(f'stage {stage}: CONTINUE? sampled', flush=True)
    finally:
        g.stop()
    for line in g.log.read_text(errors='replace').splitlines():
        if line.startswith('arcade stages') and ('loaded' in line or 'stage ' in line[:40]):
            print('  ' + line)
    (out / 'samples.json').write_text(json.dumps(sm.samples, indent=1))
    worst = {}
    for s in sm.samples:
        if s['empty']:
            continue
        k = s['label'] if not s['label'].startswith('ko') else 'ko'
        w = worst.setdefault(k, [0, 0, 0.0, 0.0, 0.0])
        w[0] += 1
        w[1] += s['bad']
        w[2] = max(w[2], s['left']); w[3] = max(w[3], s['picture']); w[4] = max(w[4], s['right'])
    for k, w in worst.items():
        margins = f'left {w[2]:.4f}, ' if args.aspect == '16:9' else ''
        right = f', right {w[4]:.4f}' if args.aspect == '16:9' else ''
        print(f'stage {stage} {k}: {w[1]} of {w[0]} samples failing; worst {margins}picture {w[3]:.4f}{right}',
              flush=True)
    return dict(stage=stage, bad=sum(s['bad'] for s in sm.samples), samples=len(sm.samples), worst=worst)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--build', default='build-dbg')
    ap.add_argument('--stages', default='0-14')
    ap.add_argument('--source', choices=('ttt', 't3', 'ps1'), default='ttt')
    ap.add_argument('--aspect', choices=('16:9', '4:3'), default='16:9')
    ap.add_argument('--renderer', default='opengl')
    ap.add_argument('--fight', type=float, default=60, help='seconds of fight, player 1 throwing')
    ap.add_argument('--kos', type=int, default=2)
    ap.add_argument('--lose', action='store_true', help='then a fight lost by player 1: the CONTINUE? countdown')
    ap.add_argument('--ko-seconds', type=float, default=20)
    ap.add_argument('--limit', type=float, default=0.002, help='uncovered share of the 4:3 picture that fails a sample')
    ap.add_argument('--margin-limit', type=float, default=0.06,
                    help='uncovered share of a 16:9 margin that fails a sample (the TTT stages have no geometry in '
                         'parts of the margins, under the round start camera: up to 0.053 measured)')
    ap.add_argument('--shots', type=int, default=0, help='a screenshot every n K.O. samples (to look at)')
    ap.add_argument('--keep', type=int, default=12, help='failing samples kept as pictures, per stage')
    ap.add_argument('--packs', default=str(sc.PACKS))
    ap.add_argument('--ttt-packs', default=str(sc.TTT_PACKS))
    ap.add_argument('--ttt1', default=str(ROOT / 'workspace/ttt1-catalogue'))
    ap.add_argument('--env', action='append', default=[])
    args = ap.parse_args()
    results = [one_stage(args, s) for s in stages_of(args.stages)]
    bad = sum(r['bad'] for r in results)
    print(f'{bad} failing samples of {sum(r["samples"] for r in results)} on {len(results)} stages '
          f'({args.source}, {args.aspect})')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
