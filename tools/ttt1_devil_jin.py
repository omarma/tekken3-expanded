#!/usr/bin/env python3
"""Build the "Devil Jin" easter-egg model: TTT1 arcade Jin, costume 1, with his Devil face.

    python3 tools/ttt1_devil_jin.py [--face faces.png] [--out DIR]

The arcade ROM ships every Jin costume with six face-expression images and a
tattooed forehead that the model never points at. Expression 5 of costume 1
(texture TIM at VRAM (32, 0)) is the Devil face: red eye, dark line between
the brows. The TIM at (64, 96) is the forehead with the Devil tattoo. This tool
copies their pixels over the images the model does display (the neutral face
at (32, 64) and the plain forehead at (80, 96)), so the model and its UVs stay
untouched, then converts the model to the PS1 format like any TTT1 guest
(tools/ttt1/model/convert.py, texpack.py).

--face replaces the Devil face with a hand-edited 32 x 64 indexed PNG that
uses the original palette (see workspace/ttt1-import/devil-jin/).

Output: Jin-TTT1-arcade-P1.{3dm,relocs,tim} and Jin-T3-devil-name.4bpp in --out (default
workspace/ttt1-import/devil-jin/guest). The runtime reads them from the TTT1
asset root when Jin is confirmed with both punch buttons. Game data never
leaves workspace/ (ignored by git).
"""
import argparse, struct, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt1'), str(ROOT / 'tools/ttt1/model')]
WORK = ROOT / 'workspace/ttt1-import'
DIRECTORY = 0x302238
SLOT = 18                      # Jin, costume 1 (punch) in the TTT1 bank
MODEL_ENTRY = 109 + SLOT       # models follow the 109 texture entries
DEVIL_FACE, SHOWN_FACE = (32, 0), (32, 64)
TATTOO, SHOWN_FOREHEAD = (64, 96), (80, 96)


def tims(blob):
    """(offset, pixel block) for every TIM of a texture entry."""
    out, p = [], 0
    while p + 8 <= len(blob):
        magic, flags = struct.unpack_from('<II', blob, p)
        if magic != 16:
            break
        q = p + 8
        if flags & 8:                                   # palette block first
            q += struct.unpack_from('<I', blob, q)[0]
        size, x, y, w, h = struct.unpack_from('<I4H', blob, q)
        out.append(dict(pos=(x, y), size=(w, h), pixels=(q + 12, q + size)))
        p = q + size
    return out


def find(entries, pos):
    hits = [t for t in entries if t['pos'] == pos]
    if len(hits) != 1:
        raise SystemExit(f'expected one TIM at {pos}, found {len(hits)}')
    return hits[0]


def copy_pixels(blob, entries, src, dst):
    s, d = find(entries, src), find(entries, dst)
    if s['size'] != d['size']:
        raise SystemExit(f'TIM {src} {s["size"]} and {dst} {d["size"]} differ in size')
    blob[d['pixels'][0]:d['pixels'][1]] = blob[s['pixels'][0]:s['pixels'][1]]


def put_png(blob, entries, dst, png):
    """Write an indexed PNG (original palette, same size) into a TIM's pixels."""
    from PIL import Image
    d = find(entries, dst)
    im = Image.open(png)
    w, h = d['size'][0] * 2, d['size'][1]              # 8-bit TIM: 2 pixels per halfword
    if im.mode != 'P' or im.size != (w, h):
        raise SystemExit(f'{png}: expected an indexed {w} x {h} PNG, got {im.mode} {im.size}')
    blob[d['pixels'][0]:d['pixels'][1]] = im.tobytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--face', type=Path, help='hand-edited Devil face (indexed PNG, 32 x 64)')
    ap.add_argument('--ram', type=Path, default=WORK / 'captures/jun-select-ram.bin',
                    help='any TTT1 select-screen RAM capture (for the bank directory)')
    ap.add_argument('--out', type=Path, default=WORK / 'devil-jin/guest')
    a = ap.parse_args()

    import convert, texpack, check_texpack
    from fmt import load
    ram = a.ram.read_bytes()
    bank = (WORK / 'ttt1/bankedroms.bin').read_bytes()
    entry = lambda i: struct.unpack_from('<II', ram, DIRECTORY + i * 8)
    mo, mn = entry(MODEL_ENTRY)
    to, tn = entry(SLOT)
    model, tex = bank[mo:mo + mn], bytearray(bank[to:to + tn])

    entries = tims(tex)
    if a.face:
        put_png(tex, entries, SHOWN_FACE, a.face)
    else:
        copy_pixels(tex, entries, DEVIL_FACE, SHOWN_FACE)
    copy_pixels(tex, entries, TATTOO, SHOWN_FOREHEAD)

    a.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src_model, src_tex = Path(tmp) / 'ttt1.3dm', Path(tmp) / 'ttt1.tex'
        src_model.write_bytes(model)
        src_tex.write_bytes(tex)
        src = load(src_model)
        report = texpack.plan(bytes(tex), src)
        ps1, relocs = convert.convert(src)
        base = a.out / 'Jin-TTT1-arcade-P1'
        base.with_suffix('.3dm').write_bytes(ps1)
        base.with_suffix('.relocs').write_bytes(struct.pack(f'<{len(relocs)}I', *relocs))
        base.with_suffix('.tim').write_bytes(texpack.repack(bytes(tex)))
        lost = convert.unplaced(src)
        bad = check_texpack.main(src_model, src_tex, base.with_suffix('.3dm'), base.with_suffix('.tim'))
    print(f'model: {len(ps1)} bytes, {len(relocs)} relocations; textures: {report["total"]} halfwords, '
          f'{len(report["moved"])} moved, {len(report["reduced"])} reduced to 16 colours')
    if lost:
        print(f'WARNING: TTT1 rows with a mesh but no PS1 place: {lost}')
    if bad:
        print(f'WARNING: texture mismatches: {bad}')
    # Name above the life bar, in the PS1 name font (as for the guests).
    import glyphs
    img, _ = glyphs.name_image('DEVIL JIN')
    px = img.tobytes()
    (a.out / 'Jin-T3-devil-name.4bpp').write_bytes(bytes(px[i] | px[i + 1] << 4 for i in range(0, len(px), 2)))
    print(f'name: DEVIL JIN, {img.width} px')
    print('->', base.parent)


if __name__ == '__main__':
    main()
