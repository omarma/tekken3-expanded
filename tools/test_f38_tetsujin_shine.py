#!/usr/bin/env python3
"""Tetsujin's scrolling reflection (F38).

    python tools/test_f38_tetsujin_shine.py --exe RUN/Tekken_3_Expanded.exe [--costume 0|2] [--off]
        [--samples 60] [--shots DIR]

Practice from the selector save (slot 8, workspace/fixtures/ps1-saves): the Tetsujin guest is player 1
(tools/ttt1/combos.py start), costume 0 (Tetsujin, P1 files) or 2 (Start: Kinjin, P3 files). Player 1
sidesteps up and down, which turns the camera. Each sample reads the camera yaw (0x800A85C4), the actor's
root byte (+0x26) and the two reflection tiles in VRAM (player 1's band: (384, 64) 64 x 64 and
(384, 192) 32 x 64), and finds which wrapped shift of the .tim's tile they hold.
TTT1 (draw_scrolling_tiles 0x80167CF8): dx = ((-yaw >> 6) & 63) * w / 64, dy = ((root & 255) >> 2) * h / 64.
Passes when every sample holds exact wrapped shifts of both tiles, dx between the yaws read just
before and after (give or take 1), and the shifts took at least 5 values in x and y. --off (TEKKEN3_F38_SHINE=0, the build before F38): the tiles never move.
Build: rel-lite (debug server lite).
"""
import argparse, os, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]

TILES = [(0, 64, 64, 64), (64, 64, 32, 64)]          # (x, y, w, h) in the costume band, halfwords
YAW, ACTOR0 = 0x800a85c4, 0x800a9228


def tim_tiles(path):
    import texpack
    tiles = texpack.read_tims(path.read_bytes())
    out = []
    for x, y, w, h in TILES:
        t = next(t for t in tiles if (t['x'], t['y'], t['w'], t['h']) == (x, y, w, h))
        out.append(t['pix'])
    return out


def shifted(pix, w, h, dx, dy):
    return [pix[((j + dy) % h) * w + (i + dx) % w] for j in range(h) for i in range(w)]


def expected(yaw, root):
    a, b = ((-yaw) >> 6) & 63, (root & 255) >> 2
    return [((a * w // 64) & 63, b * h // 64) for _, _, w, h in TILES]


def vram(g, k):
    x, y, w, h = TILES[k]
    by = y + (128 if x >= 64 else 0)
    r = g.q(dict(cmd='vram_peek', x=384 + x % 64, y=by, w=w, h=h))
    hx = r['hex']
    return [int(hx[i:i + 4], 16) for i in range(0, len(hx), 4)]


def which(pix, got, w, h):
    for dy in range(h):
        for dx in range(w):
            if shifted(pix, w, h, dx, dy) == got: return dx, dy
    return None


START = 3                                             # pad bit of Start: costume 2 at the selector


def start(K, exe, work, costume):
    """combos.start with Tetsujin as player 1, picked with cross (costume 0) or Start (costume 2)."""
    import time
    g = K.Game(exe, 'tetsujin', work)
    try:
        g.q(dict(cmd='turbo', enabled=1))
        g.q(dict(cmd='savestate', op='load', slot=8))
        end = time.monotonic() + 60
        while g.u32(K.STATE) != 9:
            if time.monotonic() > end: raise RuntimeError('Practice selector not reached')
            time.sleep(.3)
        g.wait_frames(30)
        for p in (0, 1):
            for move in [K.held(K.L)] + [K.held(K.R)] * 11 + [K.held(K.D)] + [K.held(K.R)] * 11:
                if g.u8(K.CURSOR + p) == K.JIN: break
                g.tap(move); g.wait_frames(6)
            g.tap(K.held(START if p == 0 and costume == 2 else K.PAD[3])); g.wait_frames(30)
        for adr in K.CHOICE[0]: g.w8(adr, K.GUEST_ID)
        end, nudge = time.monotonic() + 240, time.monotonic() + 10
        while not (g.u32(K.STATE) == 8 and g.u16(K.ACTOR[1] + 0x3f6) > 0):
            if time.monotonic() > end: g.shot('not-loaded.png'); raise RuntimeError('fight not loaded')
            if g.u32(K.STATE) == 9 and time.monotonic() > nudge: g.tap(K.held(K.PAD[3])); nudge = time.monotonic() + 3
            time.sleep(.5)
        g.wait_frames(120)
        g.q(dict(cmd='turbo', enabled=0))
        for attempt in range(8):
            g.tap(K.held(K.PAD[3])); g.wait_frames(60)
            before = g.u32(K.ACTOR[0] + 0x54)
            g.route([(4, K.held(K.PAD[1])), (6, K.NONE)])
            if g.u32(K.ACTOR[0] + 0x54) != before: break
            g.wait_frames(30)
        else:
            raise RuntimeError('1P FREESTYLE not reached')
        g.wait_frames(60)
        return g
    except Exception:
        g.close(); raise


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exe', required=True)
    ap.add_argument('--costume', type=int, default=0, choices=[0, 2])
    ap.add_argument('--off', action='store_true')
    ap.add_argument('--samples', type=int, default=60)
    ap.add_argument('--shots')
    a = ap.parse_args()
    import combos as K
    if a.off: os.environ['TEKKEN3_F38_SHINE'] = '0'
    files = 'P1' if a.costume == 0 else 'P3'
    src = tim_tiles(Path(a.exe).resolve().parent / f'mods/ttt1/Tetsujin-TTT1-arcade-{files}.tim')
    work = ROOT / 'workspace/f38' / f'run-c{a.costume}{"-off" if a.off else ""}'
    g = start(K, Path(a.exe), work, a.costume)
    try:
        shots = Path(a.shots) if a.shots else None
        if shots: shots.mkdir(parents=True, exist_ok=True)
        seen, dys, bad, rows = set(), set(), 0, []
        for s in range(a.samples):
            d = K.U if (s // 10) % 2 == 0 else K.D
            g.route([(2, K.held(d)), (3, K.NONE), (14, K.held(d))])
            yaw0 = struct.unpack('<i', g.rd(YAW, 4))[0]; root0 = g.u8(ACTOR0 + 0x26)
            got = [which(src[k], vram(g, k), TILES[k][2], TILES[k][3]) for k in range(2)]
            yaw1 = struct.unpack('<i', g.rd(YAW, 4))[0]; root1 = g.u8(ACTOR0 + 0x26)
            if a.off: ok = got == [(0, 0), (0, 0)]
            else:
                # The debug server answers one query a frame, so the tiles are read between the
                # yaw read before and the one after: dx on the arc between the two (the camera turns
                # smoothly), give or take 1; dy free (the root byte jumps every frame while moving).
                e0, e1 = expected(yaw0, root0), expected(yaw1, root1)
                def between(d, a, b, w):
                    lo, hi = (a, b) if (b - a) % w <= (a - b) % w else (b, a)
                    return (d - lo + 1) % w <= (hi - lo) % w + 2
                ok = None not in got and all(between(got[k][0], e0[k][0], e1[k][0], (64, 32)[k]) for k in range(2))
            bad += not ok
            seen.add(tuple(got)); dys.add(got[0][1] if got[0] else None)
            rows.append((s, yaw0, root0, got, ok))
            print(f'{s:3d} yaw {yaw0:6d} root {root0:3d} vram {got} expected {expected(yaw0, root0)} {"ok" if ok else "MISMATCH"}',
                  flush=True)
            if shots: g.q(dict(cmd='screenshot_file', path=str((shots / f'{s:03d}.png').resolve())))
        moves = len(seen)
        verdict = bad == 0 and (moves == 1 if a.off else moves >= 5 and len(dys) >= 5)
        print(f'{"PASS" if verdict else "FAIL"}: {bad} mismatches, {moves} distinct shifts, {len(dys)} distinct dy')
        sys.exit(0 if verdict else 1)
    finally:
        g.close()


if __name__ == '__main__':
    main()
