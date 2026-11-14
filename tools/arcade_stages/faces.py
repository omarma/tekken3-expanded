#!/usr/bin/env python3
"""The stock fighters' HD selector faces from Tekken 3 arcade (B186, GH#239).

    python tools/arcade_stages/faces.py --tekken3 tekken3.zip --out DIR [--board PNG]

Written by install.py beside the arcade stage packs (mods/arcade-stages):
face-NN-tile-hd.bin (64 x 116) and face-NN-portrait-hd.bin (168 x 252),
15-bit texels as tools/ttt1/ui.py writes the guests' HD tile and portrait
(F28), NN the PS1 character ID. src/tekken3_ttt1_roster.c draws the selector
grids' 32 x 58 tiles and the 126 x 252 portraits from them above native
resolution, like the guests'.

The arcade's selector (archive 11: 44 x 58 tiles, 8 bits; archive 16:
168 x 252 portraits, colour 0 transparent) holds each face in its portrait
about 2 to 2.5 times as fine as in its tile, at the same pose for all but
Kuma, whose tile is his portrait mirrored. FRAMES gives where each tile lies
in its portrait (measured by template matching, Kuma by hand): the HD tile is
that rectangle, resampled to 64 x 116 (the 44 -> 32 squeeze of the PS1 tile,
twice as fine), over the arcade tile's own background enlarged and blurred.
Gon and Dr. B (PS1 only) and Anna (drawn otherwise on the arcade) get none:
the runtime doubles their PS1 tile itself, as every tile without these files.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/arcade_stages'), str(ROOT / 'tools/ttt1')]

TILE_ARCHIVE, PORTRAIT_ARCHIVE = 11, 16
TILE_W, TILE_H, PORTRAIT_W, PORTRAIT_H = 64, 116, 168, 252
# PS1 ID: (tile (header, file), portrait (header, file), scale, x0, y0, mirrored)
# x0, y0: the tile's top left corner in the (mirrored) portrait; the tile
# spans 44 * scale x 58 * scale portrait texels.
FRAMES = {
    0: ((0, 0), (0, 0), 2.000, 40.0, 56.0, False),     # Paul
    1: ((0, 1), (0, 1), 2.400, 31.2, 62.4, False),     # Law
    2: ((0, 2), (0, 2), 2.300, 29.9, 46.0, False),     # Lei
    3: ((0, 3), (0, 3), 2.400, 45.6, 38.4, False),     # King
    4: ((0, 4), (0, 4), 2.000, 64.0, 46.0, False),     # Yoshimitsu
    5: ((0, 5), (0, 5), 2.450, 26.9, 44.1, False),     # Nina
    6: ((0, 6), (0, 6), 2.250, 31.5, 69.7, False),     # Hwoarang
    7: ((0, 7), (0, 7), 2.425, 29.1, 43.6, False),     # Xiaoyu
    8: ((0, 8), (0, 8), 2.300, 41.4, 52.9, False),     # Eddy
    9: ((0, 9), (0, 9), 2.225, 35.6, 51.2, False),     # Jin
    10: ((0, 10), (0, 10), 2.325, 20.9, 46.5, False),  # Julia
    11: ((0, 11), (0, 11), 2.500, 11.0, 25.0, True),   # Kuma: his tile is the portrait mirrored
    12: ((0, 12), (0, 12), 2.300, 32.2, 62.1, False),  # Bryan
    13: ((0, 13), (0, 13), 2.100, 33.6, 46.2, False),  # Heihachi
    14: ((0, 14), (0, 14), 1.975, 23.7, 39.5, False),  # Ogre
    15: ((0, 15), (0, 15), 2.325, 37.2, 65.1, False),  # Mokujin
    16: ((1, 0), (1, 0), 2.275, 18.2, 52.3, False),    # Gun Jack
    20: ((1, 1), (1, 1), 2.150, 32.2, 51.6, False),    # True Ogre
}


def tile_name(i: int) -> str: return f'face-{i:02}-tile-hd.bin'
def portrait_name(i: int) -> str: return f'face-{i:02}-portrait-hd.bin'


def names():
    return [n for i in FRAMES for n in (tile_name(i), portrait_name(i))]


def _tim(data: bytes):
    """(RGBA image, palette indices) of an 8-bit TIM with its CLUT; colour 0 transparent."""
    import numpy as np
    from PIL import Image
    assert struct.unpack_from('<2I', data, 0) == (0x10, 9), 'not an 8-bit TIM with a CLUT'
    size, _, _, cw, ch = struct.unpack_from('<I4H', data, 8)
    pal = np.frombuffer(data, '<u2', cw * ch, 20).astype(np.uint32)
    q = 8 + size
    _, _, _, w, h = struct.unpack_from('<I4H', data, q)
    words = np.frombuffer(data, '<u2', w * h, q + 12)
    idx = np.stack([words & 255, words >> 8], -1).reshape(h, w * 2)
    c = pal[idx]
    rgb = (np.stack([c & 31, (c >> 5) & 31, (c >> 10) & 31], -1) * 255 + 15) // 31
    alpha = np.where(c == 0, 0, 255)[..., None]
    return Image.fromarray(np.concatenate([rgb, alpha], -1).astype(np.uint8), 'RGBA')


def _archive(arcade, k: int):
    """{(header, file): RGBA image} of archive k (each file one LZ-packed TIM)."""
    import recon
    out = {}
    for hi, (_, files) in enumerate(arcade.archive(k)):
        for fi, (a, n) in enumerate(files):
            out[hi, fi] = _tim(recon.ttt1.lz(arcade.rom(a, n), 0))
    return out


def faces(arcade):
    """{PS1 ID: (HD tile, portrait)} as RGBA images."""
    from PIL import Image, ImageFilter
    tiles, portraits = _archive(arcade, TILE_ARCHIVE), _archive(arcade, PORTRAIT_ARCHIVE)
    out = {}
    for i, (t, p, s, x0, y0, mirrored) in FRAMES.items():
        tile, portrait = tiles[t], portraits[p]
        assert tile.size == (44, 58) and portrait.size == (PORTRAIT_W, PORTRAIT_H), (i, tile.size, portrait.size)
        src = portrait.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirrored else portrait
        box = (x0, y0, x0 + 44 * s, y0 + 58 * s)
        face = src.convert('RGBa').resize((TILE_W, TILE_H), Image.Resampling.LANCZOS, box=box).convert('RGBA')
        back = tile.convert('RGB').resize((TILE_W, TILE_H), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(2))
        hd = Image.alpha_composite(back.convert('RGBA'), face)
        out[i] = (hd, portrait)
    return out


def write(arcade, out: Path, say=print):
    import ui
    for i, (tile, portrait) in faces(arcade).items():
        (out / tile_name(i)).write_bytes(ui.rgb15_bytes(tile))
        (out / portrait_name(i)).write_bytes(ui.rgb15_bytes(portrait, stp=True))
    say(f'stock faces: {len(FRAMES)} HD tiles and portraits')


def board(arcade, path: Path):
    """PS1-free check: arcade tile | HD tile, per ID, three times as large."""
    from PIL import Image
    tiles = _archive(arcade, TILE_ARCHIVE)
    made = faces(arcade)
    z, pad = 3, 6
    img = Image.new('RGB', (len(made) * (2 * TILE_W * z + 3 * pad), TILE_H * z + 2 * pad), (24, 24, 28))
    for n, (i, (hd, _)) in enumerate(made.items()):
        x = n * (2 * TILE_W * z + 3 * pad) + pad
        img.paste(tiles[FRAMES[i][0]].convert('RGB').resize((TILE_W * z, TILE_H * z), Image.Resampling.NEAREST), (x, pad))
        img.paste(hd.convert('RGB').resize((TILE_W * z, TILE_H * z), Image.Resampling.NEAREST), (x + TILE_W * z + pad, pad))
    img.save(path)


def main(argv=None):
    import decode
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--tekken3', type=Path, required=True)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--board', type=Path)
    a = ap.parse_args(argv)
    arcade = decode.Arcade(a.tekken3, cache=False)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        write(arcade, a.out)
    if a.board:
        board(arcade, a.board)
    return 0


if __name__ == '__main__':
    sys.exit(main())
