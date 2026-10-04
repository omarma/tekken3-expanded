"""Graft Angel's wings onto the TTT1 Jin model (Devil Jin easter egg).

In the TTT1 bank, Angel's wings (model 109 + 67) are the second torso mesh,
row 2: 34 vertices of their own behind the back, 60 polygons, and 37 pose
variants (the flap, chosen through row 1's pose table, word 13). The same row
also redraws 24 polygons of Angel's back from the torso buffer (47 borrowed
slots); those are dropped.

Jin cannot take them in row 2: his pelvis (row 4) reads the torso's buffer up
to slot 108, and a list drawn in between would overwrite it. The wings go
instead to the first free accessory row (24), parented to the chest (TTT1
part 1) with no offset and no rest rotation, so their vertices stay in the
chest frame they were modelled in. Nothing after row 24 reads the buffer.

Textures: the four wing images (16 x 64 halfwords at x 80..111 of page 1) move
to x 208..239 of page 3, which keeps every UV; Jin uses x < 136. Their
16-colour palette goes to (240, 3), a slot Jin leaves free. The image at
(80, 0) is declared 8-bit with Angel's 256-colour palette but sampled as
4-bit by the wing material: it is rewritten as 4-bit.

All 37 poses come along with Angel's table of poses (graft_model, flap): the PS1 engine
picks the pose from the airborne state for True Ogre only, and the runtime does the same
for these wings (tekken3_ttt1_mod.c, wings_step). `flap=False` keeps a single pose.
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/ttt1/model')]
from fmt import block, nrows, parse_b, prim_verts, row  # noqa: E402
import simulate as SM                                   # noqa: E402

ANGEL_SLOT = 67
DONOR_ROW = 2                  # Angel's wings
HOST_ROW = 24                  # first accessory row, empty in Jin costume 1
CHEST = 1                      # TTT1 part of the chest
SRC_X, DST_X = 80, 208         # halfword x of the wing images: page 1 -> page 3, same u
WING_PAGE = 3
WING_CLUT = (240, 3)           # palette slot (x, y) in the costume's palette rows
ROW_FMT = '<14i'


def _wing_prims(model):
    """(family, prim record, (mat, uv indices)) of the polygons that only use
    the row's own vertices, and the size of its borrowed part."""
    a = SM.vlist(model, DONOR_ROW, True)
    borrowed = len(a['g1']) + len(a['g2'])
    fams = parse_b(block(model, row(model, DONOR_ROW)[1]))
    keep = [[] for _ in range(4)]
    for k, fam in enumerate(fams):
        for i, rec in enumerate(fam):
            if min(prim_verts(k, rec)) >= borrowed:
                keep[k].append(i)
    return keep, borrowed


def _prims_block(model, keep, borrowed):
    """Polygon block (word 1) with the kept records, vertex slots rebased on the
    new list, which has no borrowed part."""
    fams = parse_b(block(model, row(model, DONOR_ROW)[1]))
    out = b''
    for k, fam in enumerate(fams):
        recs = []
        for i in keep[k]:
            rec = bytearray(fam[i]); w = struct.unpack_from('<I', rec, 0)[0]
            for sh in ((0, 7, 14) if k in (0, 2) else (0, 7, 14, 23)):
                sl = ((w >> sh) & 0x1fc) // 4 - borrowed
                w = (w & ~(0x1fc << sh)) | ((sl * 4) << sh)
            struct.pack_into('<I', rec, 0, w & 0xffffffff)
            recs.append(bytes(rec))
        out += struct.pack('<I', len(recs)) + b''.join(recs)
    return out


def _texture_block(model, keep):
    """Texture block (word 2), TTT1 layout (fmt.parse_c_ttt1): u32 offset of the
    UV table, u32 materials, UV table, then per family a count byte and per
    polygon a material byte and its UV indices. Keeps the kept polygons and
    moves the wing material to page 3 with the new palette."""
    c = block(model, row(model, DONOR_ROW)[2])
    uvoff = struct.unpack_from('<I', c, 0)[0]
    mats = [struct.unpack_from('<I', c, o)[0] for o in range(4, uvoff, 4)]
    srcoff = struct.unpack_from('<H', c, uvoff)[0]
    clut = (WING_CLUT[1] << 6) | (WING_CLUT[0] >> 4)
    head = struct.pack('<I', uvoff)
    for m in mats:
        if (m >> 16) & 15 == SRC_X // 64 and not (m >> 16) & 0x180:
            m = (m & ~0xf0000 & ~0xffff) | (WING_PAGE << 16) | clut
        head += struct.pack('<I', m)
    p = uvoff + srcoff; tail = b''
    for k in range(4):
        n = c[p]; p += 1; nv = 4 if k & 1 else 3
        recs = [c[p + i * (1 + nv):p + (i + 1) * (1 + nv)] for i in range(n)]
        p += n * (1 + nv)
        kept = [recs[i] for i in keep[k]]
        tail += bytes([len(kept)]) + b''.join(kept)
    return head + c[uvoff:uvoff + srcoff] + tail


def _scaled(verts, scale):
    """Vertices scaled about the wings' root: the mean of the vertices nearest
    the back (largest y, within 40 units), so the root stays on the body."""
    if scale == 1: return verts
    top = max(v[1] for v in verts)
    root = [v for v in verts if v[1] >= top - 40]
    pivot = [sum(v[k] for v in root) / len(root) for k in range(3)]
    return [tuple(round(pivot[k] + (v[k] - pivot[k]) * scale) for k in range(3)) + (v[3],) for v in verts]


def _positions_block(model, variant, scale=1, back=0):
    """Positions of the wings (read through row 23, word 12): one pose, own
    vertices only, every tail group empty (TTT1 layout, simulate.variants).
    `back` pushes them away from the back (chest frame: -y is behind). Jin's
    back is thicker than Angel's (-154..-163 against -105 where the wing
    plates sit at -134..-144): unpushed, the plates are inside his back."""
    a = SM.vlist(model, DONOR_ROW, True, variant)
    verts = [(x, y - back, z, w) for x, y, z, w in _scaled(a['verts'], scale)]
    out = struct.pack('<I', a['head']) + struct.pack('<I', 0) + struct.pack('<I', 0)
    out += struct.pack('<I', len(verts)) + b''.join(struct.pack('<4h', *v) for v in verts)
    return out + struct.pack('<I', 0) * 6


def _variant_starts(model, r):
    """Offsets, in the model, of the pose variants chained in the positions block of row r."""
    p = row(model, r)[12]; starts = []
    for a in SM.variants(block(model, p), True):
        starts.append(p); q = a['used']
        for bits, vals in zip((16, 16, 16, 16, 16, 8), a['tails']):
            per = {16: 2, 8: 4}[bits]; q += 4 + 4 * ((len(vals) + per - 1) // per)
        p += q
    return starts


def graft_model(jin, angel, variant=0, scale=1, back=0, flap=True):
    """Jin's TTT1 model with Angel's wings in row 24. With `flap`, all of Angel's pose variants
    come along with his table of poses (word 13 of row 1), put on row 23 whose positions the
    wings read; the runtime plays them (tekken3_ttt1_mod.c wings_step) as it does Angel's."""
    if nrows(jin) <= HOST_ROW or row(jin, HOST_ROW)[10] or row(jin, HOST_ROW - 1)[12] > 2:
        raise ValueError(f'row {HOST_ROW} of the host model is not free')
    keep, borrowed = _wing_prims(angel)
    out = bytearray(jin)

    def put(b):
        off = len(out); out.extend(b + b'\0' * (-len(b) % 4)); return off
    w = list(row(angel, DONOR_ROW))
    new = [0] * 14
    new[0] = put(block(angel, w[0]))                        # normals, unchanged
    new[1] = put(_prims_block(angel, keep, borrowed))
    new[2] = put(_texture_block(angel, keep))
    new[6] = CHEST
    new[10] = 1
    struct.pack_into(ROW_FMT, out, 24 + HOST_ROW * 56, *new)
    prev = list(row(jin, HOST_ROW - 1))
    if not flap:
        prev[12] = put(_positions_block(angel, variant, scale, back))
    else:
        old = _variant_starts(angel, DONOR_ROW - 1)
        first = len(out); at = {}
        for v, start in enumerate(old):
            at[start] = put(_positions_block(angel, v, scale, back))
        prev[12] = first
        table = struct.unpack(f'<{len(block(angel, row(angel, DONOR_ROW - 1)[13])) // 4}I',
                              block(angel, row(angel, DONOR_ROW - 1)[13]))
        prev[13] = put(b''.join(struct.pack('<I', at.get(e, first)) for e in table))
    struct.pack_into(ROW_FMT, out, 24 + (HOST_ROW - 1) * 56, *prev)
    return bytes(out), sum(len(k) for k in keep)


def wing_palette(tex):
    """Angel's 16-colour wing palette (list of 16 PS1 colours)."""
    import texpack
    for t in texpack.read_tims(tex):
        if t['x'] == SRC_X and t['y'] == 64:
            return list(t['pal'][4])
    raise ValueError('wing image not found in the donor textures')


def graft_textures(jin_tex, angel_tex, palette):
    """Jin's texture entry with the four wing images appended at page 3."""
    import texpack
    pal = (WING_CLUT[0], WING_CLUT[1], 16, 1, list(palette))
    tims = b''.join(texpack.write_tim(t['bpp'], t['x'], t['y'], t['w'], t['h'], t['pix'], t['pal'])
                    for t in texpack.read_tims(jin_tex))
    if bytes(jin_tex[:len(tims)]) != tims:
        raise ValueError('host texture entry does not round-trip')
    out, end = tims, bytes(jin_tex[len(tims):])          # the entry ends with a zero word
    for t in texpack.read_tims(angel_tex):
        if SRC_X <= t['x'] < SRC_X + 32:
            # always written as 4-bit: (80, 0) is declared 8-bit, same halfwords
            out += texpack.write_tim(0, t['x'] - SRC_X + DST_X, t['y'], t['w'], t['h'], t['pix'], pal)
    return out + end


def drop_unused(tex, model):
    """Removes the images no polygon samples. For Jin costume 1 that is the six
    face sources (expressions, Devil face, tattooed forehead: 5 632 halfwords),
    which Devil Jin never shows (tekken3_ttt1_face is skipped for him); without
    them the wings fit the 16 384-halfword budget at full size."""
    import texpack
    tiles = texpack.read_tims(tex); used = set()
    for _, mat, uv in texpack._prims(model):
        for u, v in uv:
            mode, X = texpack._corner(mat >> 16, u)
            hit = [i for i, t in enumerate(tiles) if t['bpp'] == mode and texpack._hit(t, X, v, True)]
            used.update(hit[:1])
    out = b''.join(texpack.write_tim(t['bpp'], t['x'], t['y'], t['w'], t['h'], t['pix'], t['pal'])
                   for i, t in enumerate(tiles) if i in used)
    return out + b'\0' * 4, len(tiles) - len(used)


# --- colours ------------------------------------------------------------------

def _rgb(c): return (c & 31, (c >> 5) & 31, (c >> 10) & 31)


def _ps1(r, g, b):
    c = int(r) | int(g) << 5 | int(b) << 10
    return c or 0x8000                 # 0x0000 is transparent on the PS1: opaque black is 0x8000


def recolour(palette, mode, light=8):
    """white  : Angel's palette as is
    invert : 31 - each channel (shading inverted too)
    black  : luminance remapped to near black, shading kept: the lightest
             feather gets `light` out of 31 per channel (the engine's lighting
             brightens the texture further)
    red    : as black, with a dark red tint in the highlights
    Index 0 (transparent) and any 0x0000 entry are left untouched."""
    out = []
    lum = [sum(_rgb(c)) / 3 for c in palette]
    lit = [l for c, l in zip(palette, lum) if c]
    lo, hi = min(lit), max(lit)
    for c, l in zip(palette, lum):
        if c == 0 or mode == 'white':
            out.append(c); continue
        r, g, b = _rgb(c)
        if mode == 'invert':
            out.append(_ps1(31 - r, 31 - g, 31 - b) | (c & 0x8000)); continue
        t = (l - lo) / (hi - lo) if hi > lo else 0.5          # 0 = darkest feather, 1 = lightest
        v = 1 + (light - 1) * t                               # 1..light out of 31
        if mode == 'black':
            out.append(_ps1(v, v, v * 1.1) | (c & 0x8000))
        elif mode == 'red':
            out.append(_ps1(v * 1.6, v * 0.6, v * 0.7) | (c & 0x8000))
        else:
            raise ValueError(mode)
    return out
