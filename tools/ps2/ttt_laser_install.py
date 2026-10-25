#!/usr/bin/env python3
"""Devil's and Angel's PS2 laser: its textures, read on your Tekken Tag
Tournament (USA) PS2 disc (SLUS-20001) and converted for Tekken 3.

    python tools/ps2/ttt_laser_install.py --ttt-disc DISC [--out DIR]
    python tools/ps2/ttt_laser_install.py --ttt-disc DISC --check
    python tools/ps2/ttt_laser_install.py --ttt-disc DISC --sheet PS2.png --sheet-ps1 PS1.png --sheet-angel ANGEL.png

Under a second. On the PS2 the beam is a run of additive quads, each with one
of 8 64x32 4-bit textures, and an orb of 15 64x64 images grows and fades at
the forehead (TIPS). Devil and Angel share one set, byte for byte: TEKKEN.BIN
files 585 (Devil's), 588 (Angel's) and 591 (not identified) each hold it, as GS uploads; the first
that has it is read. The set is found by its uploads' sizes (one 128x128,
fifteen 64x64, sixteen 64x32, each image followed by its palette), not at a
fixed offset, and checked by sha256: another version of the disc is refused
with a message, and the lasers keep the arcade's yellow beam.

Kept whole, in the disc's order: 0 a 128x128 image (a ring; the last of the
run of 128x128 images before the laser's own container), 1..15 the orb,
16..23 the beam's series A, 24..31 its series B (the same drawings, shifted).

ps2-laser.tim (laser_version.FILE): the 32 images as 4-bit TIMs end to end,
as the strong-hit effect packs (*-hiteffect.tim): each its 16-colour CLUT
then its pixels, coordinates zero (the game places them). The indices are
the disc's (PSMT4 and the PS1 both put the left pixel in the low nibble).
The PS2 palettes are 32-bit, alpha 0x80 in every colour of the 32: the PS2
blends them with a fixed factor (Cs * FIX / 128 + Cd, FIX 0x80), the alpha
plays no part. Each colour becomes 15 bits (nearest), with the STP bit set:
the PS1's additive mode only blends texels that have it. Black is 0x0000,
transparent, which adds nothing either.

ps2-laser-angel.tim (laser_version.ANGEL_FILE): Angel's, the same images with
yellow palettes. Her laser is yellow in Tekken Tag Tournament 2 (on the PS2,
her file has the same purple palettes as Devil's): our choice, made from the
purple ones here, nothing more is read on the disc. Each colour's brightness
is placed on one gradient, black -> gold -> white (gold()), so the hearts of
the orb and of the beam stay white as in the purple. Devil's is the disc's.

With them, the PS2 strong-hit effects of Jin, Heihachi, Kazuya, Devil and
Angel (laser_version.HITSPARK_FILES, ttt_hitspark_ps2.py): the rest of the
PS2 EFFECTS content, read on the same disc.

The files and version.txt (laser_version.LASER_VERSION) go to a temporary
folder that then replaces DIR (default workspace/ttt-ps2/laser-pack);
CMakeLists.txt stages it beside the game as mods/ttt-ps2-laser. --check only
says whether DISC holds the set; --sheet / --sheet-ps1 / --sheet-angel draw
the control sheets: the disc's colours, Devil's file's 15-bit ones and Angel's. Nothing from the
disc goes into git.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ps2'))
import laser_version as version  # noqa: E402
import ttt_disc  # noqa: E402

DEFAULT_OUT = ROOT / 'workspace/ttt-ps2/laser-pack'

ENTRIES = (585, 588, 591)               # TEKKEN.BIN files with the set: Devil, Angel, ? (582 has not)
SHAPE = [(128, 128)] + [(64, 64)] * 15 + [(64, 32)] * 16
# The 32 images' pixels and palettes, end to end, as on the disc.
SHA256 = '15d310a5a29fd68cd26221d7ce0e49552d5c11458376bdd61756871217c7e371'
NOT_FOUND = ("Devil's and Angel's PS2 laser textures were not found, their lasers keep the arcade's yellow beam")
# Angel's gradient (gold()): its colour, the gain on a colour's brightest
# channel, and the brightness (luma) from which it goes on to white.
GOLD, GOLD_GAIN, WHITE_FROM = (255, 200, 40), 1.15, 0.55


def find_set(data: bytes):
    """The 32 (image, palette) uploads of the laser in one TEKKEN.BIN file, or None."""
    pairs = ttt_disc.textures(data)
    for s in range(len(pairs) - len(SHAPE) + 1):
        run = pairs[s:s + len(SHAPE)]
        if [(u.width, u.height) for u, _ in run] == SHAPE:
            return run
    return None


def digest(run) -> str:
    return hashlib.sha256(b''.join(u.data + p.data for u, p in run)).hexdigest()


def laser_set(disc: Path):
    """(TEKKEN.BIN entry, the 32 uploads) on DISC; ttt_disc.DiscError on another disc."""
    try:
        with ttt_disc.Disc(disc) as d:
            tekken = ttt_disc.TekkenBin(d)
            other = None
            for k in ENTRIES:
                run = find_set(tekken.read(k))
                if run and digest(run) == SHA256:
                    return k, run
                other = other or (run and k)
    except ttt_disc.DiscError as error:
        raise ttt_disc.DiscError(f'{error}: not Tekken Tag Tournament USA (SLUS-20001) for PS2. {NOT_FOUND}') from None
    except (OSError, struct.error) as error:
        raise ttt_disc.DiscError(f'{disc}: unreadable ({error}). {NOT_FOUND}') from None
    why = f'file {other} holds other textures' if other else f'files {", ".join(map(str, ENTRIES))} do not hold them'
    raise ttt_disc.DiscError(f'{disc}: not Tekken Tag Tournament USA (SLUS-20001) for PS2 ({why}). {NOT_FOUND}')


def found(disc: Path) -> bool:
    try:
        laser_set(disc)
    except ttt_disc.DiscError:
        return False
    return True


def colour15(r: int, g: int, b: int) -> int:
    """A PS2 palette colour for the PS1's additive mode."""
    r, g, b = (min(31, (c + 4) >> 3) for c in (r, g, b))
    v = r | g << 5 | b << 10
    return v | 0x8000 if v else 0


def gold(r: int, g: int, b: int):
    """A purple colour of the set, in Angel's yellow: its brightest channel
    sets how far along black -> gold it goes, its luma above WHITE_FROM how
    far on to white."""
    t = min(1.0, max(r, g, b) / 255 * GOLD_GAIN)
    w = max(0.0, ((0.299 * r + 0.587 * g + 0.114 * b) / 255 - WHITE_FROM) / (1 - WHITE_FROM))
    return tuple(round(min(255.0, t * (c + (255 - c) * w))) for c in GOLD)


def tim(width: int, height: int, pixels: bytes, clut) -> bytes:
    """A 4-bit TIM with its CLUT, coordinates zero."""
    return (struct.pack('<II', 0x10, 0x8) + struct.pack('<I4H', 12 + 32, 0, 0, 16, 1) + struct.pack('<16H', *clut)
            + struct.pack('<I4H', 12 + len(pixels), 0, 0, width // 4, height) + pixels)


def build(run, recolour=None) -> bytes:
    """The TIMs of the set; recolour: (r, g, b) -> (r, g, b) on each palette colour first (gold: Angel's)."""
    out = bytearray()
    for u, p in run:
        colours = [tuple(p.data[4 * i:4 * i + 3]) for i in range(16)]
        clut = [colour15(*(recolour(*c) if recolour else c)) for c in colours]
        out += tim(u.width, u.height, u.data, clut)
    return bytes(out)


def read_pack(pack: bytes):
    """[(width, height, pixels, 16 colours of 15 bits)] of a ps2-laser.tim."""
    images, i = [], 0
    while i < len(pack):
        magic, flags, clut_size = struct.unpack_from('<3I', pack, i)
        if magic != 0x10 or flags != 0x8 or clut_size != 44:
            raise ValueError(f'not a 4-bit TIM at {i:#x}')
        clut = struct.unpack_from('<16H', pack, i + 20)
        size, _, _, w, h = struct.unpack_from('<I4H', pack, i + 52)
        images.append((4 * w, h, pack[i + 64:i + 52 + size], clut))
        i += 52 + size
    return images


def sheet(images, out: Path, labels=None):
    """8 x 4 cells of 200 px, each image x3 at (4, 16), its label in yellow:
    the study's layout (etude-hitspark-ps2, planches/ps2-devil-laser-set.png).
    images: [(width, height, pixels, 16 (r, g, b))]."""
    from PIL import Image, ImageDraw
    page = Image.new('RGB', (1600, 800))
    draw = ImageDraw.Draw(page)
    for k, (w, h, pixels, colours) in enumerate(images):
        x, y = 200 * (k % 8), 200 * (k // 8)
        im = Image.frombytes('P', (w, h), bytes(v for b in pixels for v in (b & 15, b >> 4)))
        im.putpalette([c for rgb in colours for c in rgb])
        cell = Image.new('RGB', (200, 200))
        cell.paste(im.convert('RGB').resize((3 * w, 3 * h), Image.NEAREST), (4, 16))
        page.paste(cell, (x, y))
        draw.text((x + 2, y + 2), labels[k] if labels else f'{k} {w}x{h}', fill=(255, 255, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    page.save(out)


def ps2_images(run):
    return [(u.width, u.height, u.data, [tuple(p.data[4 * i:4 * i + 3]) for i in range(16)]) for u, p in run]


def ps1_images(pack: bytes):
    return [(w, h, pixels, [((v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3) for v in clut])
            for w, h, pixels, clut in read_pack(pack)]


def install(disc: Path, out: Path = DEFAULT_OUT, say=print) -> Path:
    import ttt_hitspark_ps2
    start = time.time()
    entry, run = laser_set(disc)
    pack, angel = build(run), build(run, gold)
    hitsparks = ttt_hitspark_ps2.files(disc)
    temp = out.with_name(out.name + '.new')
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    (temp / version.FILE).write_bytes(pack)
    (temp / version.ANGEL_FILE).write_bytes(angel)
    for name in version.HITSPARK_FILES: (temp / name).write_bytes(hitsparks[name])
    (temp / version.STAMP).write_text(f'{version.LASER_VERSION}\n', encoding='utf-8')
    shutil.rmtree(out, ignore_errors=True)
    temp.replace(out)
    say(f"Devil's and Angel's PS2 laser version {version.LASER_VERSION}: {len(run)} images from TEKKEN.BIN file "
        f'{entry}, Devil {len(pack)} and Angel {len(angel)} bytes, and the strong-hit effects of '
        f'{", ".join(n.split("-")[0] for n in version.HITSPARK_FILES)} in {out} ({time.time() - start:.1f} s)')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--ttt-disc', type=Path, required=True, help='Tekken Tag Tournament USA PS2 disc (.cue, .bin or .iso)')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--check', action='store_true', help='only say whether the disc holds the laser textures')
    ap.add_argument('--sheet', type=Path, help="draw the set in the disc's colours (no file made)")
    ap.add_argument('--sheet-ps1', type=Path, help="draw the set in Devil's file's 15-bit colours (no file made)")
    ap.add_argument('--sheet-angel', type=Path, help="draw the set in Angel's file's colours (no file made)")
    args = ap.parse_args(argv)
    try:
        if args.check:
            entry, _ = laser_set(args.ttt_disc)
            print(f'{args.ttt_disc}: the laser textures are there (TEKKEN.BIN file {entry})')
            return 0
        if args.sheet or args.sheet_ps1 or args.sheet_angel:
            entry, run = laser_set(args.ttt_disc)
            if args.sheet:
                sheet(ps2_images(run), args.sheet, [f'{entry}+{u.at:#x} {u.width}x{u.height}' for u, _ in run])
            if args.sheet_ps1:
                sheet(ps1_images(build(run)), args.sheet_ps1)
            if args.sheet_angel:
                sheet(ps1_images(build(run, gold)), args.sheet_angel)
            return 0
        install(args.ttt_disc.resolve(), args.out.resolve())
    except ttt_disc.DiscError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
