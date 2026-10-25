#!/usr/bin/env python3
"""The Mishima's PS2 strong-hit effects, read on your Tekken Tag Tournament
(USA) PS2 disc (SLUS-20001) and converted to TTT Hitspark's 64 x 64 packs.

    python tools/ps2/ttt_hitspark_ps2.py --ttt-disc DISC --out DIR
    python tools/ps2/ttt_hitspark_ps2.py --ttt-disc DISC --sheet SHEET.png

Made by ttt_laser_install.py with the lasers (the PS2 EFFECTS content, TIPS
section 164); this file alone writes them for a check.

On the PS2 each Mishima has his own strong-hit animation: 128 x 128 4-bit
images, each with its own 16-colour palette (the colours fade from one to
the next), one image a frame (the hit spark study, etude-hitspark-ps2).
In TEKKEN.BIN the set is one run of 0x2100-byte GS uploads (image, then
palette), which runs on across the table's file boundaries: it is read by
its place in TEKKEN.BIN, not in one file. Its head (the set's table and the
top of image 0) is stored compressed, in a format not read here: image 0 is
left out and the animation starts on image 1 (Jin 29 images, Heihachi 33,
Kazuya and Devil 37). Each set is checked by sha256: another version of the
disc is refused.

Conversion: each 2 x 2 block keeps its brightest texel (the image's own
palette), which keeps the PS2's one-texel lightning strokes; colours 8 -> 5
bits with the STP bit (the PS1's additive mode blends only texels that have
it), black transparent. At most 32 images (the engine reads the frame from
the game's UV, 2 x 16 cells): Heihachi's, Kazuya's and Devil's last, the
palest, go. Angel's (on the PS2 the same as Devil's)
is Devil's with gold palettes (ttt_laser_install.gold, as her laser).

Pack (the engine's .hfx, src/tekken3_ttt1_combat.c): 'HFX6', u16 version 1,
images n, side 64, palettes n, flags 1 (the palettes fade it), 0; n palettes
of 16 colours; n images of 64 lines of 32 bytes (the left texel in the low
nibble).
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ps2'))
import ttt_disc  # noqa: E402

STRIDE, IMAGE, SIDE, MOST = 0x2100, 128 * 128 // 2, 64, 32
PALETTE_AT = IMAGE + 96                 # the palette's 64 bytes, after its upload header
# name: (TEKKEN.BIN file, where image 1's pixels are in it, images 1.., sha256 of their pixels and palettes)
SETS = {
    'Jin': (393, 0xe2f0, 29,
                 '44766ecc967c0186d60276d7bf7515dafcac2eeedebf498c5605f27a23a9f76e'),
    'Heihachi': (441, 0x135b10, 33,
                 '2fa6f4134486a488ec6b0000899bd2d07ca0781aa55aa0931bf88ab707f2c43b'),
    'Kazuya': (510, 0x47330, 37,
                 '1d4eaecc4161eb85bbe3d36edec8c030f67eccd7574f7169d422f6fec08d5b81'),
    'Devil': (585, 0x166350, 37,
                 'bc2f87380aaeea62ad0be7e54747c05c762cf7d2624c50510116daa802994f69'),
}
NOT_FOUND = "the Mishima's PS2 strong-hit effects were not found, they keep TTT1's"


def read_set(d: ttt_disc.Disc, tekken: ttt_disc.TekkenBin, name: str):
    """[(pixels, 64 palette bytes)] of `name`'s images 1.. from TEKKEN.BIN."""
    entry, offset, count, _ = SETS[name]
    at = tekken.entries[entry][0] * 2048 + offset
    size = (count - 1) * STRIDE + PALETTE_AT + 64
    data = d.read(tekken.lba + at // 2048, size + 2048)[at % 2048:at % 2048 + size]
    return [(data[k * STRIDE:k * STRIDE + IMAGE], data[k * STRIDE + PALETTE_AT:k * STRIDE + PALETTE_AT + 64])
            for k in range(count)]


def digest(images) -> str:
    return hashlib.sha256(b''.join(p + c for p, c in images)).hexdigest()


def sets(disc: Path):
    """{name: images} on DISC; ttt_disc.DiscError on another disc."""
    try:
        with ttt_disc.Disc(disc) as d:
            tekken = ttt_disc.TekkenBin(d)
            out = {name: read_set(d, tekken, name) for name in SETS}
    except ttt_disc.DiscError as error:
        raise ttt_disc.DiscError(f'{error}: not Tekken Tag Tournament USA (SLUS-20001) for PS2. {NOT_FOUND}') from None
    except (OSError, struct.error) as error:
        raise ttt_disc.DiscError(f'{disc}: unreadable ({error}). {NOT_FOUND}') from None
    for name, images in out.items():
        want = SETS[name][3]
        if want and digest(images) != want:
            raise ttt_disc.DiscError(f'{disc}: not Tekken Tag Tournament USA (SLUS-20001) for PS2 '
                                     f"({name}'s set differs). {NOT_FOUND}")
    return out


def colours(palette: bytes):
    return [tuple(palette[4 * i:4 * i + 3]) for i in range(16)]


def shrink(pixels: bytes, palette) -> bytes:
    """128 x 128 -> 64 x 64 indices, each 2 x 2 block's brightest texel, packed."""
    luma = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in palette]
    row = lambda y: [v for b in pixels[y * 64:y * 64 + 64] for v in (b & 15, b >> 4)]
    out = bytearray()
    for y in range(SIDE):
        top, bottom = row(2 * y), row(2 * y + 1)
        line = [max((top[2 * x], top[2 * x + 1], bottom[2 * x], bottom[2 * x + 1]), key=lambda i: luma[i])
                for x in range(SIDE)]
        out += bytes(line[x] | line[x + 1] << 4 for x in range(0, SIDE, 2))
    return bytes(out)


def hfx(images, recolour=None) -> bytes:
    """The .hfx of a set: one palette an image, at most MOST images."""
    import ttt_laser_install as laser
    images = images[:MOST]
    head = b'HFX6' + struct.pack('<6H', 1, len(images), SIDE, len(images), 1, 0)
    palettes = b''.join(struct.pack('<16H', *(laser.colour15(*(recolour(*c) if recolour else c))
                                             for c in colours(p))) for _, p in images)
    return head + palettes + b''.join(shrink(px, colours(p)) for px, p in images)


def files(disc: Path):
    """{file name: bytes} of the five packs (Angel's: Devil's in gold)."""
    import ttt_laser_install as laser
    found = sets(disc)
    out = {f'{name}-PS2-hiteffect64.hfx': hfx(images) for name, images in found.items()}
    out['Angel-PS2-hiteffect64.hfx'] = hfx(found['Devil'], laser.gold)
    return out


def sheet(disc: Path, out: Path):
    """Each set, its PS2 128 x 128 images over their 64 x 64 conversion (x2)."""
    from PIL import Image, ImageDraw
    import ttt_laser_install as laser
    found = sets(disc)
    rows = [(n, i, None) for n, i in found.items()] + [('Angel', found['Devil'], laser.gold)]
    cols = max(len(i) for _, i, _ in rows)
    page = Image.new('RGB', (cols * 130 + 70, len(rows) * 260))
    draw = ImageDraw.Draw(page)
    for r, (name, images, recolour) in enumerate(rows):
        draw.text((2, r * 260 + 2), name, fill=(255, 255, 0))
        for k, (px, p) in enumerate(images[:MOST]):
            pal = [recolour(*c) if recolour else c for c in colours(p)]
            flat = [c for rgb in pal for c in rgb]
            big = Image.frombytes('P', (128, 128), bytes(v for b in px for v in (b & 15, b >> 4)))
            big.putpalette(flat)
            small = Image.frombytes('P', (64, 64), bytes(v for b in shrink(px, colours(p)) for v in (b & 15, b >> 4)))
            small.putpalette(flat)
            x = 70 + k * 130
            page.paste(big.convert('RGB'), (x, r * 260))
            page.paste(small.convert('RGB').resize((128, 128), Image.NEAREST), (x, r * 260 + 130))
    out.parent.mkdir(parents=True, exist_ok=True)
    page.save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--ttt-disc', type=Path, required=True)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--sheet', type=Path)
    ap.add_argument('--digests', action='store_true', help="print each set's sha256")
    args = ap.parse_args(argv)
    try:
        if args.digests:
            for name, images in sets(args.ttt_disc).items(): print(name, len(images), digest(images))
        if args.sheet: sheet(args.ttt_disc, args.sheet)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            for name, data in files(args.ttt_disc).items(): (args.out / name).write_bytes(data)
    except ttt_disc.DiscError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
