#!/usr/bin/env python3
"""Tekken Force in 16:9: are both margins redrawn on every frame? (B34)

    python3 tools/test_force_margins.py [--state stage4.pst] [--samples 60] [--build build-rel-lite]

The 16:9 sidecar keeps its pixels between gameplay frames (TIPS § 31), so a
margin area that no primitive covers keeps the last thing drawn there: on the
last stage (Heihachi's bridge) enemies froze in the top corners. Each sample
walks right for a moment, stops, and rasterizes that frame's GP0 primitives
(gpu_frame_dump) plus the cells and underlay the sidecar adds itself
(force_reveals: cells and their last-row filler; the 0x800B6B18/28 underlay rule of gp0_exec_mono_rect) over the
16:9 canvas. Fails when a margin keeps more than 2 % uncovered for 3 samples
in a row.

--state: a save state taken in the stage (slot file of the debug server). Without
it, the run plays Tekken Force from the private selector save (invincible, level
clock held) until the stage id 0x800ADC84 reaches --stage (about 13 min for 0x12).
Needs an OpenGL window (wide shots and native-wide only engage in a visible game)
and a debug server (PSX_DEBUG_SERVER_LITE build).
"""
import argparse, shutil, sys, time
from pathlib import Path
from PIL import Image, ImageDraw

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent / 'perf')]
from bench import PerfSession
from ttt1_force import to_force

STATE, PHASE, LIFE, TIMER, STAGE = 0x800ae204, 0x800ae224, 0x800a961e, 0x800adbcc, 0x800adc84
M = 61                                         # 16:9 margin of a 368-wide screen, in guest pixels
UNDERLAY = (0xB6B18, 0xB6B28)


def s11(v): v &= 0x7ff; return v - 0x800 if v & 0x400 else v


def shapes(entries):
    """Screen polygons of every polygon and rectangle, in draw order."""
    for e in entries:
        w = [int(x, 16) for x in e['w']]
        if not w: continue
        op = w[0] >> 24
        if 0x20 <= op < 0x40:
            gouraud, quad, tex = op & 0x10, op & 8, op & 4
            pts, i = [], 1
            for k in range(4 if quad else 3):
                if gouraud and k: i += 1
                if i >= len(w): break
                pts.append((s11(w[i]), s11(w[i] >> 16))); i += 1 + (1 if tex else 0)
            if len(pts) == (4 if quad else 3):
                yield e, [pts[0], pts[1], pts[3], pts[2]] if quad else pts
        elif 0x60 <= op < 0x80 and len(w) >= 2:
            x, y = s11(w[1]), s11(w[1] >> 16)
            size = (op >> 3) & 3
            if size:
                W = H = {1: 1, 2: 8, 3: 16}[size]
            else:
                wh = w[3 if op & 4 else 2] if len(w) > (3 if op & 4 else 2) else 0
                W, H = wh & 0x3ff, (wh >> 16) & 0x1ff
            if op == 0x60 and int(e['src'], 16) & 0x1fffff in UNDERLAY:     # extended by the sidecar
                x0, x1 = (-M if x == 0 else x), (368 + M if x + W == 368 else x + W)
                yield e, [(x0, y), (x1, y), (x1, y + H), (x0, y + H)]
            else:
                yield e, [(x, y), (x + W, y), (x + W, y + H), (x, y + H)]


def holes(entries, cells, y0=20, y1=468):
    """Uncovered share of the left and right margins (draw area rows y0..y1)."""
    im = Image.new('L', (368 + 2 * M, 480), 0); d = ImageDraw.Draw(im)
    for _, pts in shapes(entries): d.polygon([(x + M, y) for x, y in pts], fill=255)
    for x, y, filler in cells:
        d.rectangle([x + M, y, x + M + 63, y + 63 + (32 if filler else 0)], fill=255)
    px = im.load()
    def share(xs): return sum(1 for x in xs for y in range(y0, y1) if not px[x, y]) / (len(xs) * (y1 - y0))
    return share(range(M)), share(range(368 + M, 368 + 2 * M))


def hold(s, full):
    if s.value(STATE, 2) == 8 and s.value(PHASE, 2) >= 6:
        full = full or s.value(LIFE, 2)
        if full: s.write(LIFE, full, 2)
        s.write(TIMER, 0x7000, 2)
    return full


def play_to(s, stage):
    s.wait(lambda: s.value(STATE, 2) == 9, 'selector', 30)
    to_force(s)
    s.wait(lambda: s.value(STATE, 2) == 4, 'menu', 15); time.sleep(1.5)
    for _ in range(6): s.q(cmd='press', buttons=0xffbf, frames=8); time.sleep(.6)
    s.q(cmd='press', buttons=0xbfff, frames=4)
    s.wait(lambda: s.value(STATE, 2) == 9 and s.value(0x80118648) == 21, 'force selector', 25); time.sleep(1.5)
    s.q(cmd='press', buttons=0x7fff, frames=4)
    full, i, end = 0, 0, time.monotonic() + 1500
    while not (s.value(STAGE, 2) == stage and s.value(STATE, 2) == 8 and s.value(PHASE, 2) == 8):
        if time.monotonic() > end: raise SystemExit('stage %#x not reached' % stage)
        i += 1; full = hold(s, full)
        s.q(cmd='set_input', buttons=0xff7f if i % 2 else 0x7f7f); time.sleep(.05)
    s.q(cmd='clear_input'); time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=str(Path(__file__).resolve().parents[1] / 'build-rel-lite'))
    ap.add_argument('--state', help='save state in the stage (e.g. state_80079C70_slot03.pst)')
    ap.add_argument('--stage', type=lambda x: int(x, 0), default=0x12)
    ap.add_argument('--samples', type=int, default=60)
    ap.add_argument('--limit', type=float, default=0.02)
    ap.add_argument('--run', type=int, default=3, help='consecutive bad samples that fail')
    a = ap.parse_args()
    s = PerfSession(Path(a.build), 'opengl', True, False, True, guest='jun', slot=7)
    try:
        if a.state:
            shutil.copy2(a.state, s.saves / 'openbios' / Path(a.state).name)
            time.sleep(2); s.q(cmd='savestate', op='load', slot=int(Path(a.state).stem[-2:])); time.sleep(2)
        else:
            play_to(s, a.stage)
        if s.value(STAGE, 2) != a.stage: raise SystemExit('not in stage %#x' % a.stage)
        full, run, worst, bad = 0, 0, (0, 0), []
        for i in range(a.samples):
            for k in range(6):
                full = hold(s, full)
                s.q(cmd='set_input', buttons=0xff7f if k % 2 else 0x7f7f); time.sleep(.1)
            s.q(cmd='clear_input'); time.sleep(.4)
            n = s.q(cmd='gpu_ring_stats')['newest_frame'] - 1
            left, right = holes(s.q(cmd='gpu_frame_dump', frame=n, count=20000)['entries'],
                                s.q(cmd='force_reveals')['cells'])
            worst = (max(worst[0], left), max(worst[1], right))
            run = run + 1 if max(left, right) > a.limit else 0
            print('sample %2d frame %d  left %.3f  right %.3f' % (i, n, left, right), flush=True)
            if run >= a.run: bad.append(i)
        print('worst left %.3f right %.3f' % worst)
        if bad: raise SystemExit('FAIL: a 16:9 margin stays uncovered (samples %s)' % bad)
        print('PASS: both 16:9 margins covered on every sample')
    finally:
        s.q(cmd='clear_input'); s.stop()


if __name__ == '__main__':
    main()
