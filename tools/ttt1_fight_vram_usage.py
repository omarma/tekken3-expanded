#!/usr/bin/env python3
"""Which VRAM a fight reads or writes, arena by arena, from the GPU commands.

    python3 tools/ttt1_fight_vram_usage.py <arena> [<arena> ...] [--frames 90]

Player 1 picks Jin on the stock page of the cabinet selector; the Arcade
list is rewritten so that stages 2.. are Paul, and Paul's record gets the
arena of the next stage (byte 10) before each one: every fight is a stock
one, in the arena asked for. During each fight the GP0 ring
(gpu_frame_dump) is read over --frames frames, from the round intro to the
K.O., and every VRAM texel the frame touches is marked:

- textured polygons and sprites: the texels their UVs cover in their
  texture page (4, 8 or 15 bits), and their CLUT row (16 or 256 entries);
- image uploads (0xA0) and VRAM copies (0x80): their rectangles.

The maps land in workspace/ttt1-fight-vram/arena-<n>.bin (1024 x 512
bytes, 1 = used) and a PNG per arena; --union writes the union
of all maps and lists the 32 x N columns, each inside one 64-wide texture
page, that no arena uses: where player 2's tiles can go.
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from ttt1_live import Session

OUT = ROOT / 'workspace/ttt1-fight-vram'
W, H = 1024, 512
STATE, PHASE, STAGE = 0x800AE204, 0x800AE224, 0x800AFAAC
LIST, P2_LIFE = 0x800AFB18, 0x800AAAB4 + 0x3F4
PAUL_ARENA = 0x800221A0 + 10          # byte 10 of Paul's record


def mark(used, x0, y0, w, h):
    for y in range(max(0, y0), min(H, y0 + h)):
        row = used[y]
        for x in range(max(0, x0), min(W, x0 + w)):
            row[x] = 1


def texels(used, page, uvs, clut):
    """Mark the texels a primitive samples, and its CLUT."""
    bx, by, depth = (page & 15) * 64, (page >> 4 & 1) * 256, page >> 7 & 3
    us, vs = [u for u, _ in uvs], [v for _, v in uvs]
    div = (4, 2, 1, 1)[depth]
    x0, x1 = bx + min(us) // div, bx + max(us) // div
    mark(used, x0, by + min(vs), x1 - x0 + 1, max(vs) - min(vs) + 1)
    if depth < 2 and clut is not None:
        mark(used, (clut & 63) * 16, clut >> 6 & 511, 16 if depth == 0 else 256, 1)


def decode(entries, used, state):
    """GP0 entries of one frame -> marks. state keeps the draw mode (E1)."""
    for e in entries:
        w = [int(x, 16) for x in e['w']]
        if not w: continue
        op = w[0] >> 24
        if op == 0xE1:
            state['page'] = w[0] & 0x1FF
        elif 0x20 <= op < 0x40 and op & 4:                   # textured polygon
            n, gouraud = (4 if op & 8 else 3), op & 0x10
            i, uvs, clut, page = 1, [], None, state['page']
            for k in range(n):
                if k and gouraud: i += 1
                i += 1                                         # vertex
                if i >= len(w): break
                uv = w[i]; i += 1
                uvs.append((uv & 255, uv >> 8 & 255))
                if k == 0: clut = uv >> 16
                if k == 1: page = uv >> 16 & 0x1FF; state['page'] = page
            if len(uvs) == n: texels(used, page, uvs, clut)
        elif 0x60 <= op < 0x80 and op & 4 and len(w) >= 3:     # textured sprite
            u, v, clut = w[2] & 255, w[2] >> 8 & 255, w[2] >> 16
            size = op & 0x18
            if size == 0 and len(w) >= 4: sw, sh = w[3] & 0xFFFF, w[3] >> 16
            else: sw = sh = {0x08: 1, 0x10: 8, 0x18: 16}.get(size, 1)
            texels(used, state['page'], [(u, v), (min(255, u + sw - 1), min(255, v + sh - 1))], clut)
        elif op == 0xA0 and len(w) >= 3:                       # upload
            mark(used, w[1] & 1023, w[1] >> 16 & 511, (w[2] & 0xFFFF) or 1024, (w[2] >> 16) or 512)
        elif op == 0x80 and len(w) >= 4:                       # VRAM copy
            sw, sh = (w[3] & 0xFFFF) or 1024, (w[3] >> 16) or 512
            mark(used, w[1] & 1023, w[1] >> 16 & 511, sw, sh)
            mark(used, w[2] & 1023, w[2] >> 16 & 511, sw, sh)


def run(arenas, frames):
    OUT.mkdir(parents=True, exist_ok=True)
    s = Session()
    try:
        s.wait(lambda: s.value(STATE) == 9 and s.value(0x80118648) == 21, 'selector', 20)
        for _ in range(23):
            if s.value(0x80118668) == 9: break
            s.press(0xff7f)
        s.press(0x7fff)
        s.wait(lambda: s.value(STATE) == 11, 'loading', 15)
        for k in range(1, len(arenas) + 1): s.write(LIST + 4 * k, 0, 1)      # Paul
        done, t0 = set(), time.monotonic()
        while len(done) < len(arenas) and time.monotonic() - t0 < 900:
            state, phase, stage = s.value(STATE), s.value(PHASE, 2), s.value(STAGE)
            if state == 8 and 1 <= stage <= len(arenas) and stage not in done and phase >= 3:
                arena = arenas[stage - 1]
                used = [bytearray(W) for _ in range(H)]
                st, seen = dict(page=0), set()
                end = time.monotonic() + 40
                while len(seen) < frames and time.monotonic() < end:
                    stats = s.q(cmd='gpu_ring_stats')
                    last = int(stats.get('newest_frame', 0)) - 1         # the newest is still being drawn
                    if last and last not in seen:
                        d = s.q(cmd='gpu_frame_dump', frame=last, count=65536)
                        decode(d.get('entries', []), used, st); seen.add(last)
                    if len(seen) == frames // 2 and s.value(P2_LIFE) > 0xFFFF:
                        s.write(P2_LIFE + 2, 0, 2)                    # K.O. effects too
                    time.sleep(.05)
                (OUT / f'arena-{arena:02}.bin').write_bytes(b''.join(used))
                done.add(stage); print(f'arena {arena}: {len(seen)} frames', flush=True)
                if stage < len(arenas): s.write(PAUL_ARENA, arenas[stage], 1)
            if state == 8 and phase >= 6 and s.value(P2_LIFE) > 0xFFFF and (stage == 0 or stage in done):
                if stage == 0: s.write(PAUL_ARENA, arenas[0], 1)
                s.write(P2_LIFE + 2, 0, 2)
            elif state not in (8, 9, 11):
                s.press(0xfff7)
            time.sleep(.1)
    finally:
        s.stop()


def union():
    maps = sorted(OUT.glob('arena-*.bin'))
    total = bytearray(W * H)
    for m in maps:
        b = m.read_bytes()
        total = bytearray(a | c for a, c in zip(total, b))
    (OUT / 'union.bin').write_bytes(bytes(total))
    try:
        from PIL import Image
        for m in maps + [OUT / 'union.bin']:
            Image.frombytes('L', (W, H), bytes(255 * v for v in m.read_bytes())).save(m.with_suffix('.png'))
    except ImportError:
        pass
    print(f'{len(maps)} arenas')
    # Free 32-wide columns inside one 64-wide page: longest free run of rows.
    for x in range(0, W, 32):
        best = run_start = 0; cur = 0
        for y in range(H):
            if any(total[y * W + x:y * W + x + 32]): cur = 0
            else:
                cur += 1
                if cur > best: best, run_start = cur, y - cur + 1
        if best >= 32: print(f'x {x}..{x + 31}: free rows {run_start}..{run_start + best - 1} ({best})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('arenas', nargs='*', type=int)
    ap.add_argument('--frames', type=int, default=90)
    ap.add_argument('--union', action='store_true')
    a = ap.parse_args()
    if a.arenas: run(a.arenas, a.frames)
    if a.union: union()


if __name__ == '__main__':
    main()
