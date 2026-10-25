#!/usr/bin/env python3
"""Build the "Devil Jin" easter-egg model: TTT1 arcade Jin, costume 1, with his Devil face.

    python3 tools/ttt1_devil_jin.py [--face faces.png] [--wings none|black|...] [--plain] [--out DIR]

--plain keeps Jin's own face and forehead, without wings: the same model
before his transformation (Kazuya's TTT ending, tools/ps2/).

The arcade ROM ships every Jin costume with six face-expression images and a
tattooed forehead that the model never points at. Expression 5 of costume 1
(texture TIM at VRAM (32, 0)) is the Devil face: red eye, dark line between
the brows. The TIM at (64, 96) is the forehead with the Devil tattoo. This tool
copies their pixels over the images the model does display (the neutral face
at (32, 64) and the plain forehead at (80, 96)), so the model and its UVs stay
untouched, then converts the model to the PS1 format like any TTT1 guest
(tools/ttt1/model/convert.py, texpack.py).

By default Angel's wings are grafted on his back, black (lightest feather at
4/31, 1.15 x Angel's size, pushed 40 units back off his thicker back,
chosen in game on 2026-10-02;
tools/ttt1_devil_jin_wings.py).
--wings none gives the model without wings.

--eyes also writes Jin-TTT1-arcade-P1.face (the cinematics' eyes, as a guest's
.face: tools/ttt1_import.py faces()), costume 1's expressions kept whole in the
atlas. Over the Devil face, each expression is that face where the plain
expression differs from the plain neutral face (the eyes), the Devil face
elsewhere: his eyes close without losing the Devil's marks.

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
    ap.add_argument('--plain', action='store_true', help="Jin's own face and forehead, no wings")
    ap.add_argument('--out', type=Path, default=WORK / 'devil-jin/guest')
    ap.add_argument('--wings', choices=('none', 'white', 'invert', 'black', 'red'), default='black',
                    help="graft Angel's wings in this colour (tools/ttt1_devil_jin_wings.py)")
    ap.add_argument('--wing-light', type=float, default=4,
                    help='black/red wings: lightest feather, out of 31 per channel')
    ap.add_argument('--wing-scale', type=float, default=1.15, help='size of the wings (1 = Angel\'s)')
    ap.add_argument('--wing-back', type=int, default=40, help='push the wings back, in model units')
    ap.add_argument('--wing-pose', type=int, default=0, help='pose of the wings, 0..36 (with --no-flap)')
    ap.add_argument('--no-flap', action='store_true', help='keep one pose of the wings (they do not flap)')
    ap.add_argument('--eyes', action='store_true', help="write the .face of costume 1's expressions (cinematics' eyes)")
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
    shown_px = bytes(tex[slice(*find(entries, SHOWN_FACE)['pixels'])])
    if a.plain:
        a.wings = 'none'
    elif a.face:
        put_png(tex, entries, SHOWN_FACE, a.face)
    else:
        copy_pixels(tex, entries, DEVIL_FACE, SHOWN_FACE)
    if not a.plain:
        copy_pixels(tex, entries, TATTOO, SHOWN_FOREHEAD)
    face = None
    if a.eyes:
        from ttt1_import import faces
        face = faces(ram, SLOT)
        if not face: raise SystemExit(f'no face expressions for slot {SLOT}')
        if not a.plain:
            devil = tex[slice(*find(entries, SHOWN_FACE)['pixels'])]
            for x, y in face[1]:
                if (x, y) == DEVIL_FACE: continue
                lo, hi = find(entries, (x, y))['pixels']
                tex[lo:hi] = bytes(e if e != n else d for e, n, d in zip(tex[lo:hi], shown_px, devil))
    if a.wings != 'none':
        import ttt1_devil_jin_wings as wings
        ao, an = entry(109 + wings.ANGEL_SLOT)
        to_, tn_ = entry(wings.ANGEL_SLOT)
        angel, angel_tex = bank[ao:ao + an], bank[to_:to_ + tn_]
        model, polys = wings.graft_model(model, angel, a.wing_pose, a.wing_scale, a.wing_back, not a.no_flap)
        tex = bytearray(wings.graft_textures(tex, angel_tex,
                                             wings.recolour(wings.wing_palette(angel_tex), a.wings, a.wing_light)))
        tex, dropped = wings.drop_unused(bytes(tex), model)
        tex = bytearray(tex)
        print(f'wings: {polys} polygons, {"one pose " + str(a.wing_pose) if a.no_flap else "37 poses"}, {a.wings}, x{a.wing_scale}, back {a.wing_back}; {dropped} unused images dropped')

    a.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src_model, src_tex = Path(tmp) / 'ttt1.3dm', Path(tmp) / 'ttt1.tex'
        src_model.write_bytes(model)
        src_tex.write_bytes(tex)
        src = load(src_model)
        shown, sources, (blink, flag_a, flag_b) = face or ((), [], (0, 0, 0))
        report = texpack.plan(bytes(tex), src, [shown] + [(x, y) + shown[2:] for x, y in sources] if face else ())
        ps1, relocs = convert.convert(src)
        base = a.out / 'Jin-TTT1-arcade-P1'
        base.with_suffix('.3dm').write_bytes(ps1)
        base.with_suffix('.relocs').write_bytes(struct.pack(f'<{len(relocs)}I', *relocs))
        base.with_suffix('.tim').write_bytes(texpack.repack(bytes(tex)))
        base.with_suffix('.face').unlink(missing_ok=True)
        if face:
            # As tools/ttt1_import.py model(): read by tekken3_ttt1_face_tick().
            placed = [texpack.face_at(*shown)] + [texpack.face_at(x, y, *shown[2:]) for x, y in sources]
            if None in placed: raise SystemExit('the face expressions did not fit the atlas whole')
            base.with_suffix('.face').write_bytes(b'FACE' + struct.pack(
                f'<6H{2 * len(sources)}H2H', *placed[0], *shown[2:], blink, len(sources), *sum(placed[1:], ()),
                flag_a, flag_b))
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
