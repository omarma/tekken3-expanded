#!/usr/bin/env python3
"""Unknown's PS2 weapons converted for the engine (F29, GH#120, step 3).

    python tools/ps2/ttt_weapons.py DISC [OUT] [--sheet PNG]

Reads the katana (Yoshimitsu's style) and the dagger (Kunimitsu's) of both of
Unknown's costumes from the player's TTT PS2 disc (tools/ps2/ttt_models.py),
rebuilds them the way the arcade models its own weapons and writes the pack
the engine loads (OUT: unknown-weapons.bin, made by ttt_laser_install.py with
the PS2 effects). Nothing read here goes into git.

Frame. The PS2 hand nodes' frames are TTT1's (the T3 bones') scaled by 1.2,
with neither rotation nor offset: with the root's rotation in its hand node
(ttt_models.WEAPONS), the dagger lies along -z from z 120 to -401 over x 47..93,
y 13..34 of the frame of TTT1's +0xC58 node (T3 bone 6), where TTT1 starts and
ends Unknown's energy blade (60, 30, -80) -> (60, 30, -400); the katana along
+z from -135 to 687 in +0xD98's (bone 10), blade (60, -30, 70) -> (60, -30, 800).

Construction. TTT1 builds Yoshimitsu's sword (model slot 8, part 20) and
Kunimitsu's knife (part 16) as a few cross-sections along the blade joined by
long quads: a box for the handle and the guard, a point of triangles. The PS2
weapons are rebuilt the same way, on their own outline:
- levels: the PS2 mesh's own z levels (grouped within GAP), each sliced where
  it is widest (a guard's face), then only those a straight line between their
  neighbours does not give within EPSILON (Douglas-Peucker on the extremes);
- a ring per level: the 4 points of the slice furthest along -x, +y, +x, -y
  (the outline seen from the face and from the edge stays the PS2's);
- 4 quads between two rings, one closing each end (a ring reduced to the
  point makes triangles);
- each corner's UV: the PS2 surface's nearest point, looked for a little
  inside its own quad (a corner on an edge sits on a texture seam), from the
  opaque pass, then from the additive one for the glow drawn on the same
  polygons.
Reductions that removed vertices (quadric edge collapse) thinned the blades
into lines or ate the guards; the user turned them down.
"""
from __future__ import annotations

import argparse
import collections
import struct
import sys
from pathlib import Path

import ttt_disc as T
import ttt_models as M

SCALE = 1 / 1.2
GAP, EPSILON = 1.0, 2.0          # level grouping and outline tolerance, arcade units
INSET = 0.08                     # how far inside its polygon a corner reads its UV
BONES = {M.STYLE_KATANA: 10, M.STYLE_DAGGER: 6}     # T3 bone of the hand node (TTT1 rows 20 / 16)


def to_bone(point, rotation):
    """A point of the weapon's root frame in the T3 bone's (row vectors)."""
    return tuple(sum(point[i] * rotation[i][k] for i in range(3)) * SCALE for k in range(3))


def window_key(tex0):
    return tex0['tbp'], tex0['tw'], tex0['th'], tex0['cbp']


def _sub(a, b):
    return [a[k] - b[k] for k in range(3)]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def slice_points(tris, z):
    """Where the triangles' edges cross the plane z (their corners on it included)."""
    out = []
    for t in tris:
        P = t['points']
        for a, b in ((0, 1), (1, 2), (2, 0)):
            za, zb = P[a][2], P[b][2]
            if za == z:
                out.append(tuple(P[a]))
            elif (za - z) * (zb - z) < 0:
                s = (z - za) / (zb - za)
                out.append(tuple(P[a][k] + (P[b][k] - P[a][k]) * s for k in range(3)))
    return out


def ring(tris, z):
    """The 4 points of a slice furthest along -x, +y, +x, -y (None: nothing there)."""
    S = slice_points(tris, z)
    if not S:
        return None
    return [(p[0], p[1], z) for p in (min(S, key=lambda p: p[0]), max(S, key=lambda p: p[1]),
                                      max(S, key=lambda p: p[0]), min(S, key=lambda p: p[1]))]


def levels(tris, gap=GAP, epsilon=EPSILON):
    """The rings kept, from the pommel to the point."""
    zs = sorted({p[2] for t in tris for p in t['points']})
    groups = [[zs[0]]]
    for z in zs[1:]:
        if z - groups[-1][-1] <= gap:
            groups[-1].append(z)
        else:
            groups.append([z])
    width = lambda r: 0 if r is None else (r[2][0] - r[0][0]) + (r[1][1] - r[3][1])
    Z = [max(g, key=lambda z: width(ring(tris, z))) for g in groups]
    Z[0], Z[-1] = zs[0], zs[-1]
    rings = [r for r in (ring(tris, z) for z in Z) if r is not None]
    profile = lambda r: [r[0][0], r[2][0], r[1][1], r[3][1], r[0][1], r[2][1], r[1][0], r[3][0]]

    def keep(a, b):
        if b - a < 2:
            return {a, b}
        za, zb, worst, k = rings[a][0][2], rings[b][0][2], 0.0, None
        for i in range(a + 1, b):
            t = (rings[i][0][2] - za) / (zb - za)
            d = max(abs(x - (pa * (1 - t) + pb * t))
                    for x, pa, pb in zip(profile(rings[i]), profile(rings[a]), profile(rings[b])))
            if d > worst:
                worst, k = d, i
        return {a, b} if worst <= epsilon else keep(a, k) | keep(k, b)
    return [rings[i] for i in sorted(keep(0, len(rings) - 1))]


def nearest_uv(tris, p):
    """UV and window of the triangles' surface point nearest p."""
    best = None
    for t in tris:
        A, B, C = t['points']
        e0, e1, v = _sub(B, A), _sub(C, A), _sub(p, A)
        d00, d01, d11, d20, d21 = _dot(e0, e0), _dot(e0, e1), _dot(e1, e1), _dot(v, e0), _dot(v, e1)
        den = d00 * d11 - d01 * d01
        if den < 1e-12:
            continue
        b1 = min(max((d11 * d20 - d01 * d21) / den, 0.0), 1.0)
        b2 = min(max((d00 * d21 - d01 * d20) / den, 0.0), 1.0 - b1)
        b0 = 1 - b1 - b2
        q = [A[k] * b0 + B[k] * b1 + C[k] * b2 for k in range(3)]
        d = _dot(_sub(q, p), _sub(q, p))
        if best is None or d < best[0]:
            uv = tuple(t['uv'][0][k] * b0 + t['uv'][1][k] * b1 + t['uv'][2][k] * b2 for k in range(2))
            best = (d, uv, t['tex0'])
    return best[1], best[2]


def rebuild(tris: list[dict]) -> list[dict]:
    """tris: the PS2 weapon {points, uv, additive, tex0} in the bone's frame;
    returns its polygons {points (3 or 4, cyclic), uv, additive, tex0}: the
    opaque pass, then the glow on the same polygons."""
    opaque = [t for t in tris if not t['additive']]
    glow = [t for t in tris if t['additive']]
    R = levels(opaque)
    faces = [[r0[k], r0[(k + 1) % 4], r1[(k + 1) % 4], r1[k]] for r0, r1 in zip(R, R[1:]) for k in range(4)]
    faces += [list(reversed(R[0])), list(R[-1])]
    out = []
    for source, additive in ((opaque, False), (glow, True)):
        for f in faces:
            corners = [p for i, p in enumerate(f) if p != f[i - 1]]        # a ring reduced to a point
            if len(corners) < 3:
                continue
            c = [sum(p[k] for p in corners) / len(corners) for k in range(3)]
            found = [nearest_uv(source, tuple(p[k] + INSET * (c[k] - p[k]) for k in range(3))) for p in corners]
            out.append(dict(points=[tuple(p) for p in corners], uv=[u for u, _ in found], additive=additive,
                            tex0=found[0][1]))
    return out


def convert(data: bytes, parsed: list[dict] | None = None) -> dict:
    """{style: {bone, polygons in the T3 bone's frame, source triangles}} for one costume."""
    parsed = parsed if parsed is not None else M.strips(data)
    out = {}
    for style in (M.STYLE_KATANA, M.STYLE_DAGGER):
        w = M.weapon(data, style, parsed)
        tris = [dict(t, points=[to_bone(p, w['rotation']) for p in t['points']]) for t in w['triangles']]
        out[style] = dict(bone=BONES[style], polygons=rebuild(tris), source=len(tris))
    return out


def windows_used(conv: dict) -> dict:
    """{window: (u0, v0, u1, v1)} texel boxes the polygons read."""
    box = {}
    for w in conv.values():
        for t in w['polygons']:
            k = window_key(t['tex0'])
            for s, tt in t['uv']:
                u, v = s * t['tex0']['tw'], tt * t['tex0']['th']
                b = box.get(k, (u, v, u, v))
                box[k] = (min(b[0], u), min(b[1], v), max(b[2], u), max(b[3], v))
    return box


def colour15(r: int, g: int, b: int, additive: bool) -> int:
    """15 bits, nearest; additive images set STP on every colour but black (the
    PS1 only blends texels that have it), opaque ones keep black opaque (0x8000)."""
    r, g, b = (min(31, (c + 4) >> 3) for c in (r, g, b))
    v = r | g << 5 | b << 10
    return (v | 0x8000 if v else 0) if additive else (v or 0x8000)


def sixteen(colours: collections.Counter) -> list:
    """Up to 16 RGB colours for a weighted set (k-means from the most used)."""
    keys = sorted(colours, key=lambda c: -colours[c])
    centres = [list(c) for c in keys[:16]]
    for _ in range(8):
        sums = [[0, 0, 0, 0] for _ in centres]
        for c, n in colours.items():
            k = min(range(len(centres)), key=lambda i: sum((c[j] - centres[i][j]) ** 2 for j in range(3)))
            for j in range(3):
                sums[k][j] += c[j] * n
            sums[k][3] += n
        centres = [[s[j] / s[3] for j in range(3)] if s[3] else centres[i] for i, s in enumerate(sums)]
    return [tuple(round(x) for x in c) for c in centres]


def image(sheets, palettes, window, box, additive):
    """A 4-bit TIM of the texels a window's box reads (the window repeats, as on
    the GS), its width a multiple of 4; index 0 is transparent black."""
    tbp, tw, th, cbp = window
    u0, v0 = int(box[0]), int(box[1])
    w = (int(box[2] + .999) - u0 + 1 + 3) // 4 * 4
    h = int(box[3] + .999) - v0 + 1
    tex0 = dict(tbp=tbp, tw=tw, th=th, cbp=cbp)
    texels = []
    for y in range(h):
        for x in range(w):
            c = M.texel(sheets, palettes, tex0, ((u0 + x) % tw + .5) / tw, ((v0 + y) % th + .5) / th)
            texels.append(None if c is None or c[3] < 0x40 or (additive and not any(c[:3])) else c[:3])
    colours = collections.Counter(c for c in texels if c is not None)
    palette = sixteen(colours) if colours else [(0, 0, 0)]
    index = {c: 1 + min(range(len(palette)), key=lambda i: sum((c[j] - palette[i][j]) ** 2 for j in range(3)))
             for c in colours}
    clut = [0] + [colour15(*c, additive) for c in palette[:15]]
    clut += [0] * (16 - len(clut))
    if len(palette) > 15:                     # 15 colours and transparency: merge the 16th into its nearest
        last = palette[15]
        near = 1 + min(range(15), key=lambda i: sum((last[j] - palette[i][j]) ** 2 for j in range(3)))
        index = {c: (near if i == 16 else i) for c, i in index.items()}
    nibbles = [index.get(c, 0) if c is not None else 0 for c in texels]
    pixels = bytes(nibbles[i] | nibbles[i + 1] << 4 for i in range(0, len(nibbles), 2))
    tim = (struct.pack('<II', 0x10, 0x8) + struct.pack('<I4H', 12 + 32, 0, 0, 16, 1) + struct.pack('<16H', *clut)
           + struct.pack('<I4H', 12 + len(pixels), 0, 0, w // 4, h) + pixels)
    return tim, (u0, v0, w, h)


MAGIC, FORMAT = b'UPW1', 2
GPU_ORDER = {3: (0, 1, 2), 4: (0, 1, 3, 2)}     # a cyclic quad's corners as POLY_FT4 takes them


def costume_block(data: bytes) -> bytes:
    """One costume: u16 styles, u16 images; the images (4-bit TIMs, u32 size
    first); then per style u16 moveset, T3 bone, points, polygons; the points
    (s16 x, y, z of the bone's frame); the polygons (16 bytes: u8 corners 3 or
    4, u8 image, u8 flags (1 = additive), u8 0, 4 x u8 point, 4 x (u8 u, v),
    corners in the GPU's order: 0, 1, 3, 2 of the quad's cycle)."""
    conv = convert(data)
    sheets, palettes = M.textures(data)
    boxes = windows_used(conv)
    additive_windows = {window_key(t['tex0']) for w in conv.values() for t in w['polygons'] if t['additive']}
    images, place = [], {}
    for k, box in sorted(boxes.items()):
        tim, origin = image(sheets, palettes, k, box, k in additive_windows)
        place[k] = (len(images), origin)
        images.append(tim)
    out = bytearray(struct.pack('<2H', len(conv), len(images)))
    for tim in images:
        out += struct.pack('<I', len(tim)) + tim
    for style, w in sorted(conv.items()):
        points, corner = [], {}
        for t in w['polygons']:
            for p in t['points']:
                key = tuple(round(c) for c in p)
                if key not in corner:
                    corner[key] = len(points)
                    points.append(key)
        if len(points) > 255:
            raise ValueError(f'style {style}: {len(points)} points, more than a byte indexes')
        out += struct.pack('<4H', style, w['bone'], len(points), len(w['polygons']))
        for p in points:
            out += struct.pack('<3h', *p)
        for t in w['polygons']:
            k = window_key(t['tex0'])
            n, (u0, v0, iw, ih) = place[k]
            order = GPU_ORDER[len(t['points'])]
            idx = [corner[tuple(round(c) for c in t['points'][i])] for i in order] + [0] * (4 - len(order))
            uv = []
            for i in order:
                s, tt = t['uv'][i]
                uv += [min(iw - 1, max(0, round(s * k[1] - u0))), min(ih - 1, max(0, round(tt * k[2] - v0)))]
            uv += [0] * (8 - len(uv))
            out += struct.pack('<4B4B8B', len(order), n, 1 if t['additive'] else 0, 0, *idx, *uv)
    return bytes(out)


def build(disc: Path) -> bytes:
    """The pack of both of Unknown's costumes ('UPW1', u16 format, u16 costumes)."""
    with T.Disc(disc) as d:
        models = M.Models(d)
        blocks = [costume_block(models.pack(models.model(M.UNKNOWN, c))) for c in (0, 1)]
    return MAGIC + struct.pack('<2H', FORMAT, len(blocks)) + b''.join(blocks)


def read(pack: bytes) -> list[dict]:
    """The costumes of a pack: {images: [(width, height, pixels, clut)],
    styles: {style: dict(bone, points, polygons: [dict(corners, image, uv, additive)])}},
    corners and UVs in the GPU's order."""
    if pack[:4] != MAGIC or struct.unpack_from('<H', pack, 4)[0] != FORMAT:
        raise ValueError(f'not a UPW1 pack of format {FORMAT}')
    count, o, out = struct.unpack_from('<H', pack, 6)[0], 8, []
    for _ in range(count):
        styles, n = struct.unpack_from('<2H', pack, o)
        o += 4
        images = []
        for _ in range(n):
            size = struct.unpack_from('<I', pack, o)[0]
            tim = pack[o + 4:o + 4 + size]
            o += 4 + size
            clut = struct.unpack_from('<16H', tim, 20)
            hw, h = struct.unpack_from('<2H', tim, 52 + 8)
            images.append((4 * hw, h, tim[64:], clut))
        st = {}
        for _ in range(styles):
            style, bone, npoints, npolys = struct.unpack_from('<4H', pack, o)
            o += 8
            points = [struct.unpack_from('<3h', pack, o + 6 * i) for i in range(npoints)]
            o += 6 * npoints
            polys = []
            for _ in range(npolys):
                f = struct.unpack_from('<4B4B8B', pack, o)
                o += 16
                k = f[0]
                polys.append(dict(corners=f[4:4 + k], image=f[1], additive=bool(f[2] & 1),
                                  uv=[f[8 + 2 * i:10 + 2 * i] for i in range(k)]))
            st[style] = dict(bone=bone, points=points, polygons=polys)
        out.append(dict(images=images, styles=st))
    return out


def sheet(pack: bytes, out: Path):
    """Draws the pack as the engine would see it (Pillow): per costume and style,
    the bone's xz and yz planes, opaque polygons then additive ones, on dark grey."""
    from PIL import Image
    costumes = read(pack)
    W, H, S = 220, 620, 0.5
    img = Image.new('RGB', (W * 2 * 2 * len(costumes), H), (28, 28, 28))
    px = img.load()
    for c, costume in enumerate(costumes):
        for s, (style, w) in enumerate(sorted(costume['styles'].items())):
            for view, (a, b) in enumerate(((0, 2), (1, 2))):
                ox = ((c * 2 + s) * 2 + view) * W
                for additive in (False, True):
                    for t in w['polygons']:
                        if t['additive'] != additive:
                            continue
                        iw, ih, pixels, clut = costume['images'][t['image']]
                        P = [w['points'][i] for i in t['corners']]
                        q = [(ox + W / 2 + (p[a] - 60) * S,
                              H / 2 - (p[b] - (300 if style == M.STYLE_KATANA else -150)) * S) for p in P]
                        for tri in ((0, 1, 2),) if len(P) == 3 else ((0, 1, 2), (1, 3, 2)):   # GPU order
                            _fill(px, img.size, [q[i] for i in tri], [t['uv'][i] for i in tri], iw, pixels, clut,
                                  additive)
    img.save(out)


def _fill(px, size, q, uv, iw, pixels, clut, additive):
    (x0, y0), (x1, y1), (x2, y2) = q
    den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(den) < 1e-9:
        return
    for y in range(max(0, int(min(y0, y1, y2))), min(size[1], int(max(y0, y1, y2)) + 1)):
        for x in range(max(0, int(min(x0, x1, x2))), min(size[0], int(max(x0, x1, x2)) + 1)):
            l0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / den
            l1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / den
            l2 = 1 - l0 - l1
            if min(l0, l1, l2) < -1e-6:
                continue
            u = round(l0 * uv[0][0] + l1 * uv[1][0] + l2 * uv[2][0])
            v = round(l0 * uv[0][1] + l1 * uv[1][1] + l2 * uv[2][1])
            i = v * iw + u
            nib = (pixels[i // 2] >> (4 * (i & 1))) & 15 if i // 2 < len(pixels) else 0
            col = clut[nib]
            if col == 0:
                continue
            rgb = ((col & 31) << 3, (col >> 5 & 31) << 3, (col >> 10 & 31) << 3)
            if additive:
                old = px[x, y]
                rgb = tuple(min(255, old[k] + rgb[k]) for k in range(3))
            px[x, y] = rgb


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('disc', type=Path)
    ap.add_argument('out', type=Path, nargs='?', help='write the pack (unknown-weapons.bin) here')
    ap.add_argument('--sheet', type=Path, help='draw the pack (Pillow)')
    args = ap.parse_args(argv)
    pack = build(args.disc)
    if args.sheet:
        sheet(pack, args.sheet)
    for c, costume in enumerate(read(pack)):
        print(f'costume {c + 1}: images {[(w, h) for w, h, _, _ in costume["images"]]}')
        for style, w in costume['styles'].items():
            quads = sum(len(t['corners']) == 4 for t in w['polygons'])
            print(f'  style {style}: T3 bone {w["bone"]}, {len(w["points"])} points, {len(w["polygons"])} polygons '
                  f'({quads} quads; {sum(t["additive"] for t in w["polygons"])} additive)')
    if args.out:
        args.out.write_bytes(pack)
        print(len(pack), 'bytes ->', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
