#!/usr/bin/env python3
"""B32 (GH#47): a guest's icon must grey like a stock fighter's.

    python3 tools/test_grey_tiles.py [--build build-rel-lite] [--guest kazuya]

The game greys a chosen or defeated fighter's icon (Team Battle grid,
FIGHT screen, results) with one ramp for all at (256, 501): index 0 black
up to light grey at 255, so each pixel gets the grey of its index. That
only looks right when the icon's palette runs dark to light, as the stock
ones do. On the Team Battle Tag page this reads the ramp, then each
icon's palette and pixels from VRAM, and correlates each pixel's
luminance with the ramp's at its index: stock icons give about +0.98; a
guest's came out negative (inverted grey) before the fix.
"""
import argparse, statistics, struct, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ttt1_live import Session, PAD_R2, ROOT

TAG_BASE, TILE_W, TILE_H = 16, 16, 58          # src/tekken3_ttt1_roster.c


def lum(c): return (c & 31) * 299 + (c >> 5 & 31) * 587 + (c >> 10 & 31) * 114


def words(b): return struct.unpack(f'<{len(b) // 2}H', b)


def palette_row(s, x, y):
    """256 colours: vram_peek reads 128 pixels wide at most."""
    return words(s.vram(x, y, 128, 1) + s.vram(x + 128, y, 128, 1))


def correlation(s, ramp, x, y, palette_x, palette_y):
    """Pixel-weighted correlation of an 8bpp 32 x 58 icon's luminance with
    the ramp's, the icon at halfword (x, y), its palette at (palette_x, palette_y)."""
    palette = palette_row(s, palette_x, palette_y)
    pixels = s.vram(x, y, TILE_W, TILE_H)
    used = [p for p in pixels if p]                # index 0: transparent
    return statistics.correlation([lum(palette[p]) for p in used], [lum(ramp[p]) for p in used])


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--build', default='build-rel-lite')
    a.add_argument('--guest', default='kazuya')
    args = a.parse_args()
    s = Session(guest=args.guest, build=ROOT / args.build)
    try:
        s.write(0x800afa88, 2); s.write(0x800ae224, 0, 2); s.write(0x800ae204, 10, 2)
        time.sleep(1.2); s.press(0x7fff)
        s.press(PAD_R2); time.sleep(1.5)                 # the Tag page: the guests' tiles are up
        ramp = palette_row(s, 256, 501)
        assert [lum(c) for c in ramp] == sorted(lum(c) for c in ramp), 'the stock ramp is not dark to light'
        stock = {}
        for cid in range(21):                            # the stock sheet, from the icon table
            uv, page = s.value(0x8002152c + cid * 8), s.value(0x8002152c + cid * 8 + 4, 2)
            if (page >> 7 & 3) != 1: continue            # 8bpp icons only
            x, y = (page & 15) * 64 + (uv & 255) // 2, (page >> 4 & 1) * 256 + (uv >> 8 & 255)
            clut = uv >> 16
            stock[cid] = correlation(s, ramp, x, y, (clut & 63) * 16, clut >> 6)
        guests = {}
        for k, name in enumerate(n.split()[0] for n in (s.assets / 'guests.txt').read_text().splitlines() if n.split()):
            if k >= TAG_BASE + 2: break
            x = 384 + (k % 8 if k < TAG_BASE else k - TAG_BASE) * TILE_W
            y = 16 + (k // 8) * TILE_H if k < TAG_BASE else 144
            guests[name] = correlation(s, ramp, x, y, 0, 480 + k if k < TAG_BASE else 498 + k - TAG_BASE)
        for label, table in (('stock', stock), ('guest', guests)):
            for key, c in table.items(): print(f'{label} {key!s:10} {c:+.3f}')
        bad = {n: round(c, 3) for n, c in guests.items() if c < 0.8}
        assert stock and min(stock.values()) > 0.8, stock
        assert not bad, f'guest icons whose palette runs against the grey ramp: {bad}'
        print('OK: every guest icon greys in the stock order')
    finally:
        s.stop()


if __name__ == '__main__':
    main()
