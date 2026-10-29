#!/usr/bin/env python3
"""B114 (GH#165): the caged Panda of TTT's School stage (TTT stage 7) leaves
when Panda takes part, as in TTT1.

    python ressources/slot.py --kind game --who b114 --prio 2 -- \\
        python tools/test_ttt_school_cage.py --build build-rel-lite [--cases panda1,panda2,kuma,none,switch]
        [--sweep] [--yaws 900,960,1024] [--distance 2200] [--out workspace/b114/board]

TTT1 (0x8015F6A4, TIPS section 189): with Panda's models 0x5D / 0x17
(Kuma's kick costumes) among the team members or fighters, or True Ogre,
stage 7 loads archive 5 file 12 (the cage's texture with an all-zero CLUT)
and never runs the machine that animates the Panda in it. Ours: Kuma (ID 11)
in costume 1 (Panda) on either side (True Ogre never fights on TTT stage 7
here: stage 14 or the PS1's dark arena).

Cold start of the build (software renderer, headless, x1), Arcade, TTT stage
7 forced in the fight (TEKKEN3_TTT_STAGES_FORCE=7@8, STAGES = TTT), the
engine's probe on (TEKKEN3_ARCADE_STAGES_PROBE). Player 1 picks on the
selector as Jin; both fighters (ID, costume) are written during the
loading screen. Lives held. The fight axis (0x800A9188) is turned by
--yaws (offsets from its value at the round start) so that the camera faces
the cage (tile 125 of the stage, about +960), the fighters held --distance
apart so that it shows between them; --sweep takes a picture every 256
units instead, to find that angle.

Cases: panda1 (Panda vs Jin), panda2 (Jin vs Panda), kuma (Kuma vs Jin),
none (Jin vs Jin), switch (Jin vs Jin, then player
1's fighter word set to Panda and back during the fight: the pack stays
loaded, the cage empties and fills again). Pictures:
OUT/<case>-<offset>-<k>.png. Checked from the probe: the
stage 7 machine runs (ttanim ... 1) only without Panda, the CLUT is cleared
(tz) when she comes, and copies resume when she leaves.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import test_devil_jin as T  # noqa: E402
from test_yoshimitsu_win_sparks import Game  # noqa: E402

AXIS = 0x800A9188
FIGHTERS, COSTUMES = 0x800ADD5C, 0x800ADD98      # u16 per player: the fight's IDs and costumes
P1_LIFE, P2_LIFE = 0x800A961E, 0x800AAEAA
KUMA, JIN = 11, 9
# (player 1: ID, costume), (player 2: ID, costume), cage empty
CASES = {
    'panda1': ((KUMA, 1), (JIN, 0), True),
    'panda2': ((JIN, 0), (KUMA, 1), True),
    'kuma': ((KUMA, 0), (JIN, 0), False),
    'none': ((JIN, 0), (JIN, 1), False),
    'switch': ((JIN, 0), (JIN, 1), False),
}


def start(g, p1, p2):
    """Arcade, Jin on the selector; both fighters written during the
    loading screen (Kuma is locked on a fresh card)."""
    T.to_selector(g)
    T.cursor_to(g, JIN)
    end, pressed, seen, presses = time.monotonic() + 60, 0, set(), 0
    while (state := g.value(T.STATE)) != 11:
        seen.add(state)
        if state == 8 and g.value(T.PHASE, 2) >= 3:
            raise AssertionError('the fight started before the loading screen was seen')
        if time.monotonic() > end:
            g.shot('stuck')
            raise AssertionError(f'loading screen not reached (states {sorted(seen)})')
        if state == 9 and time.monotonic() - pressed > 1:
            # the first two presses after the cursor's moves do not choose
            g.q(cmd='press', buttons=T.SQUARE if presses < 2 else T.CROSS, frames=12)
            pressed, presses = time.monotonic(), presses + 1
        time.sleep(.05)
    for p, (cid, costume) in enumerate((p1, p2)):
        g.write(FIGHTERS + 2 * p, cid, 2)
        g.write(COSTUMES + 2 * p, costume, 2)
    g.wait(lambda: g.value(T.STATE) == 8 and g.value(T.PHASE, 2) >= 8, 'round did not start', 150)


def fighters(g):
    return [(g.value(FIGHTERS + 2 * p, 2), g.value(COSTUMES + 2 * p, 2)) for p in (0, 1)]


def hold(g):
    for a in (P1_LIFE, P2_LIFE):
        g.write(a, 200, 2)


def spread(g, distance):
    """The fighters `distance` apart on their line, around their middle
    (tools/test_poison_mist.place): the camera draws back and the cage shows
    between them."""
    p1, p2 = (struct.unpack('<3i', g.read(T.ACTOR + p * T.STRIDE, 12)) for p in (0, 1))
    dx, dz = p2[0] - p1[0], p2[2] - p1[2]
    n = (dx * dx + dz * dz) ** .5 or 1
    mx, mz = (p1[0] + p2[0]) / 2, (p1[2] + p2[2]) / 2
    for p, k in ((0, -.5), (1, .5)):
        x, z = int(mx + dx / n * distance * k), int(mz + dz / n * distance * k)
        for off, v in ((0, x), (8, z), (0xf68, x), (0xf70, z)):
            g.write(T.ACTOR + p * T.STRIDE + off, v)


def turn(g, yaw, distance):
    """The axis turned to `yaw`, held while the camera follows."""
    for _ in range(12):
        hold(g)
        if distance:
            spread(g, distance)
        g.write(AXIS, yaw & 0xFFFFFFFF, 4)
        time.sleep(.12)


def probe_lines(path):
    return path.read_text(errors='replace').splitlines() if path.exists() else []


def anim_summary(lines, start=0):
    """(frames with the machine on, frames off, CLUT clears, copies) from line `start`."""
    on = off = clears = copies = 0
    for line in lines[start:]:
        w = line.split()
        if not w:
            continue
        if w[0] == 'ttanim' and w[2] == '7':
            if len(w) > 9 and w[9] == '0':
                off += 1
            else:
                on += 1
        elif w[0] == 'tz':
            clears += 1
        elif w[0] == 'tm':
            copies += 1
    return on, off, clears, copies


def first(lines, start, active):
    """Index of the first stage 7 frame from `start` whose machine is on
    (active=1) or off (0): the frame the write is seen."""
    for i in range(start, len(lines)):
        w = lines[i].split()
        if len(w) > 9 and w[0] == 'ttanim' and w[2] == '7' and w[9] == str(active):
            return i
    return len(lines)


def case(build, out, name, yaws, sweep, distance):
    p1, p2, empty = CASES[name]
    probe = out / f'{name}-probe.txt'
    probe.unlink(missing_ok=True)
    env = {'TEKKEN3_STAGES': 'ttt', 'TEKKEN3_TTT_STAGES_FORCE': '7@8', 'TEKKEN3_ARCADE_STAGES_LOG': '1',
           'TEKKEN3_ARCADE_STAGES_PROBE': str(probe)}
    T.WORK = out
    g = Game(build, name, env)
    ok = True
    try:
        start(g, p1, p2)
        who = fighters(g)
        print(f'{name}: fighters {who}', flush=True)
        base = g.value(AXIS)
        if sweep:
            for k in range(16):
                turn(g, base + 256 * k, distance)
                g.shot(f'sweep-{k:02}')
            return True
        for k in range(2):                  # the Panda moves between pictures
            for off in yaws:
                turn(g, base + off, distance)
                g.shot(f'{off}-{k}')
            time.sleep(1.5)
        yaw = base + yaws[len(yaws) // 2]
        lines = probe_lines(probe)
        on, off, clears, copies = anim_summary(lines)
        want = (on == 0 and off > 0 and clears >= 1) if empty else (on > 0 and off == 0 and copies > 0)
        print(f'{name}: machine on {on} frames, off {off}, CLUT cleared {clears}, copies {copies}: '
              f'{"empty cage" if empty else "caged Panda"} {"OK" if want else "FAILED"}', flush=True)
        ok &= want
        if name == 'switch':
            mark = len(lines)
            g.write(FIGHTERS, KUMA, 2); g.write(COSTUMES, 1, 2)          # Panda for the test only
            time.sleep(2)
            turn(g, yaw, distance); g.shot('3-panda')
            lines = probe_lines(probe)
            mark = first(lines, mark, 0)
            on, off, clears, copies = anim_summary(lines, mark)
            step = off > 0 and on == 0 and clears == 1 and copies == 0
            print(f'switch to Panda: machine off {off} frames, on {on}, CLUT cleared {clears}, copies {copies}: '
                  f'{"OK" if step else "FAILED"}', flush=True)
            ok &= step
            mark = len(lines)
            g.write(FIGHTERS, JIN, 2); g.write(COSTUMES, 0, 2)
            time.sleep(2)
            turn(g, yaw, distance); g.shot('4-back')
            lines = probe_lines(probe)
            mark = first(lines, mark, 1)
            on, off, clears, copies = anim_summary(lines, mark)
            step = on > 0 and off == 0 and copies > 0 and clears == 0
            print(f'switch back: machine on {on} frames, off {off}, copies {copies}: {"OK" if step else "FAILED"}',
                  flush=True)
            ok &= step
        return ok
    finally:
        g.stop()
        log = (out / f'{name}.log')
        if log.exists():
            for line in log.read_text(errors='replace').splitlines():
                if 'TTT stage' in line and ('load' in line or 'force' in line):
                    print('  ' + line.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--build', type=Path, default=ROOT / 'build-rel-lite')
    ap.add_argument('--cases', default='panda1,panda2,kuma,none,switch')
    ap.add_argument('--yaws', default='900,960,1024', help='axis offsets from the round start that face the cage')
    ap.add_argument('--distance', type=int, default=2200, help='fighters held this far apart (0: left alone)')
    ap.add_argument('--sweep', action='store_true')
    ap.add_argument('--out', type=Path, default=ROOT / 'workspace/b114/board')
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = args.cases.split(',')
    results = {n: case(args.build.resolve(), out, n, [int(v, 0) for v in args.yaws.split(',')], args.sweep,
                     args.distance) for n in (names[:1] if args.sweep else names)}
    print('summary: ' + ', '.join(f'{n} {"OK" if r else "FAILED"}' for n, r in results.items()))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == '__main__':
    main()
