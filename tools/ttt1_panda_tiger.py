#!/usr/bin/env python3
"""Panda and Tiger faces: the TTT1 loading portraits for Kuma's kick costume and Eddy's third.

    python3 tools/ttt1_panda_tiger.py [--out DIR]

Tekken 3 PS1 has no portrait of its own for Panda (Kuma, ID 11, costume 2)
nor for Tiger (Eddy, ID 8, costume 3): the game only swaps the name, the
selector, loading and team screens keep Kuma's and Eddy's faces. TTT1 has
both. Its loading portraits are raw 8-bit TIMs in the banked ROM (39 456
bytes each, 76 x 256 halfwords, from 0xDDECC8); Panda is the 31st, Tiger the
36th. Each becomes an interface pack like a guest's (tools/ttt1/ui.py:
portrait, selector and loading tiles cut from the portrait), which the
runtime shows once the costume is confirmed (src/tekken3_ttt1_roster.c,
`alt_face`).

Output: Panda-T3-ui.jui and Tiger-T3-ui.jui (with source PNGs) in --out
(default workspace/ttt1-import/panda-tiger/guest), staged by
tools/ttt1_stage_roster.py. Game data never leaves workspace/ (ignored by git).
"""
import argparse, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1')]
WORK = ROOT / 'workspace/ttt1-import'
PORTRAITS, PORTRAIT_SIZE, PORTRAIT_COUNT = 0xDDECC8, 39456, 38
# name: (index among the loading portraits, tile frame in portrait pixels).
# The frames take the head as the stock tiles of Kuma and Eddy do.
FACES = {'Panda': (30, (14, 18, 138, 178)),
         'Tiger': (35, (10, 64, 134, 224))}
# Their tiles share a 128-wide strip of palettes with their grey copies
# (src/tekken3_ttt1_roster.c, ALT_PALETTE_Y): 127 colours and transparent.
TILE_COLORS = 128


def portrait(bank, index):
    """The index-th loading portrait, 152 x 256 RGBA (colour 0 transparent)."""
    import ui_art
    o = PORTRAITS + index * PORTRAIT_SIZE
    tag, flags, clut_bytes = struct.unpack_from('<3I', bank, o)
    w, h = struct.unpack_from('<2H', bank, o + 8 + clut_bytes + 8)
    if (tag, flags, clut_bytes, w, h) != (16, 9, 524, 76, 256):
        raise SystemExit(f'portrait {index}: not a 76 x 256 8-bit TIM at {o:#x}')
    pal = struct.unpack_from('<256H', bank, o + 20)
    return ui_art.rgba(bank[o + 8 + clut_bytes + 12:o + PORTRAIT_SIZE], w, h, pal)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=Path, default=WORK / 'panda-tiger/guest')
    a = ap.parse_args()
    import ui_art, ui as U
    bank_path = WORK / 'ttt1/bankedroms.bin'
    if not bank_path.is_file(): raise SystemExit(f'{bank_path} missing: run tools/ttt1_setup.py first')
    bank = bank_path.read_bytes()
    a.out.mkdir(parents=True, exist_ok=True)
    for name, (index, box) in FACES.items():
        face = portrait(bank, index)
        face.save(a.out / f'{name}-TTT1-portrait.png')
        images, how = ui_art.t3_images(face, box=box)
        pack, _ = U.pack(images, tile_colors=TILE_COLORS)
        for iname, *_ in U.SPECS: images[iname].save(a.out / f'{name}-T3-{iname}-source.png')
        (a.out / f'{name}-T3-ui.jui').write_bytes(pack)
        print(f'{name}: portrait {index}, {len(pack)} bytes, tiles: {how}')


if __name__ == '__main__':
    main()
