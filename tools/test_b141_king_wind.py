#!/usr/bin/env python3
"""B141 (GH#192): the wind of Tekken 3 arcade's stage 11 (King) on the accessory bones.

    python C:/TekkenProject/ressources/slot.py --kind game --who b141 -- \\
        python tools/test_b141_king_wind.py --build build-rel-lite \\
            [--cases 11:on,11:on:nowind,9:on,11:off] [--frames 1024]

T3 arcade (0x801E6ACC at each fighter's load, in a fight, scene 4, on stage 11
only) draws one of 8 directions for the fight; 0x8019C738 blows it every frame
in 16-frame gusts and its accessory solver (0x8019B6D8) pulls a bone in the
air sideways by it. The PS1 has neither. Each case is a cold start of a private
copy of the build (stage_check.py: software renderer, headless, no pad but the
menus' presses), Arcade, Xiaoyu (under the cursor) idle against the CPU, every
fight on the arena of the case, Arcade Stages on or off; `:nowind` adds
TEKKEN3_TTT_WIND=0 (the build without the wind, as dev before B141). The mod's
probe (TEKKEN3_ARCADE_STAGES_PROBE) writes, every frame T3's stage is drawn,
`wind <frame> <x> <z>` and `acc <frame>` with player 1's accessory bones 18..21
(x axis of the local matrix, actor + 0xF74 + 32 * bone): the debug server is
too slow to read them every frame.

The measure is the wind's signature: for each bone, the DFT magnitude of its
direction at the gusts' period (16 frames) against the mean at neighbouring
frequencies; the case's score is its bones' largest. MAME, same fight (B141
notes): stage 11 4.6 to 7.3, stage 9 1.2 to 1.8.

Fails when the wind is missing on stage 11 with Arcade Stages on (score below
--min-wind or no non-zero wind line), or shows anywhere else (score above
--max-calm or a non-zero wind line). With the mod off nothing of it runs (no
probe): the case checks the arena and that the mod drew nothing.
"""
from __future__ import annotations

import argparse
import cmath
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools' / 'arcade_stages'))
import stage_check  # noqa: E402
from stage_check import Game, to_fight  # noqa: E402

FRAME = 0x800A08F0
ACTOR = 0x800A9228
BONES = ACTOR + 0xF74 + 32 * 18           # bones 18..21, 32 bytes each (rotation first)


def s16(b, o):
    return int.from_bytes(b[o:o + 2], 'little', signed=True)


def sample(probe: Path, since: int):
    """{frame: 4 bones' x axes} from the probe's acc lines (once per frame the
    stage is drawn), from frame `since` on."""
    out = {}
    if not probe.exists():
        return out
    for line in probe.read_text(errors='replace').splitlines():
        if line.startswith('acc '):
            v = [int(t) for t in line.split()[1:]]
            if v[0] >= since:
                out[v[0]] = [tuple(v[1 + 3 * k:4 + 3 * k]) for k in range(4)]
    return out


def magnitude(t, x, f):
    m = sum(x) / len(x)
    return abs(sum((v - m) * cmath.exp(-2j * math.pi * f * ti) for ti, v in zip(t, x))) / len(x)


def score(samples):
    """Per bone, the largest (over its axis' 3 components) magnitude at period
    16 against the mean of 6 neighbouring frequencies; frames as sampled."""
    t = sorted(samples)
    span = t[-1] - t[0] + 1
    out = []
    for bone in range(4):
        best = 0.0
        for c in range(3):
            x = [samples[f][bone][c] for f in t]
            if len(set(x)) < 2:
                continue
            peak = magnitude(t, x, 1 / 16)
            around = [magnitude(t, x, (span / 16 + d) / span) for d in (-12, -9, -6, 6, 9, 12)]
            best = max(best, peak / (sum(around) / len(around) or 1))
        out.append(best)
    return out


def gust_degrees(samples):
    """Per bone, the swing at the gusts' period: the DFT amplitude at 1/16 of
    its x axis (unit vector), in degrees."""
    t = sorted(samples)
    out = []
    for bone in range(4):
        a = 0.0
        for c in range(3):
            x = [samples[f][bone][c] / 4096 for f in t]
            a += (2 * magnitude(t, x, 1 / 16)) ** 2
        out.append(math.degrees(math.sqrt(a)))
    return out


def wind_lines(probe: Path, since: int):
    if not probe.exists():
        return 0, 0
    lines = [l.split() for l in probe.read_text(errors='replace').splitlines() if l.startswith('wind ')]
    lines = [l for l in lines if int(l[1]) >= since]
    return len(lines), sum(1 for l in lines if int(l[2]) or int(l[3]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build-rel-lite')
    ap.add_argument('--packs', default=str(stage_check.PACKS))
    ap.add_argument('--cases', default='11:on,11:on:nowind,9:on,11:off')
    ap.add_argument('--frames', type=int, default=1024)
    ap.add_argument('--min-wind', type=float, default=3.0)
    ap.add_argument('--max-calm', type=float, default=2.5)
    ap.add_argument('--out', default=str(ROOT / 'workspace/b141'))
    args = ap.parse_args()
    failures = []
    for case in args.cases.split(','):
        arena, mode, *flag = case.split(':')
        arena, nowind = int(arena), flag == ['nowind']
        out = Path(args.out).resolve() / case.replace(':', '-')
        out.mkdir(parents=True, exist_ok=True)
        g = Game((ROOT / args.build).resolve(), out / 'run', 'mod' if mode == 'on' else 'off', 'software',
                 Path(args.packs).resolve(), env_extra={'TEKKEN3_TTT_WIND': '0'} if nowind else None)
        try:
            to_fight(g, arena)
            got = g.value(stage_check.ARENA, 2)
            since = g.value(FRAME)
            time.sleep(args.frames / 60 + 2)
        finally:
            g.stop()
        probe = out / 'run/probe.txt'
        samples = sample(probe, since)
        lines, windy = wind_lines(probe, since)
        expect = arena == 11 and mode == 'on' and not nowind
        if mode == 'off':       # the mod draws nothing: no probe, nothing to blow
            bones, swing, ok = [], [], got == arena and not probe.exists()
        else:
            bones = score(samples) if len(samples) > 64 else [0.0]
            swing = gust_degrees(samples) if len(samples) > 64 else []
            best = max(bones)
            ok = got == arena and len(samples) > 64 and (
                (best >= args.min_wind and windy > 0) if expect else (best <= args.max_calm and windy == 0))
        print(f'{case:12}: arena {got}, {len(samples)} frames, period-16 score per bone '
              + (' '.join(f'{b:.1f}' for b in bones) or 'n/a (mod off)')
              + (' (gust swing ' + ' '.join(f'{d:.1f}' for d in swing) + ' deg)' if swing else '') + f'; wind lines {windy}/{lines} non-zero; '
              + ('wind expected' if expect else 'calm expected') + (' OK' if ok else ' FAIL'), flush=True)
        if not ok:
            failures.append(case)
    if failures:
        print('FAIL: ' + ', '.join(failures))
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
