#!/usr/bin/env python3
"""Tetsujin's and Kinjin's tail on Roger's and Alex's moves (feat/tetsujin-tail, GH#223).

Neither TTT1 nor Tekken 3 gives Tetsujin a tail: TTT1's Tetsujin has no
accessory block and no piece, whatever moveset he draws (TIPS.md section 78).
Tekken 5 Dark Resurrection does it for Mokujin: his combat model carries a
hidden tail (a mesh group on joint 114, four soft bones 111..114 under the
pelvis, sprung by the game's MOP physics, textured like his body), shown when
he fights with Roger Jr.'s moves (handoff/mokujin-roger-tail.md). This is that
tail for Tetsujin, with Mokujin's shapes and proportions (measured in the ISO,
model 1992, mesh group 1): three identical bars, eight-sided and bevelled at
both ends, two interlocked chain links at each joint (root, between the bars,
before the ball), and a round ball at the end. 234 quads (Mokujin's: 544
triangles), in Tetsujin's own metal.

Texture: the body's own. Every textured polygon of Tetsujin's body reads his
reflection tile (8 bits, halfwords (0, 64) 64 x 64 of the costume band: u 0..127,
v 64..127 of the page; the one F38 slides with the camera, GH#224); the tail
takes the material of his sword's blade (the first block of his .stick,
tools/ttt1/stick.py: the body's page and palette) and spreads its UVs over that
tile, around each bar and the ball and along them. Kinjin's costume has the same
tile on his gold palette, so his tail is gold. The game lights it as the body
(src/tekken3_ttt1_mod.c, normals from the quads).

Physics: four springs (the three bars, then the ball), as Mokujin's bones
111..114. Each segment's points are in its own frame, x along it from its joint;
the links of a joint belong to the segment that starts there.

File `<Name>-TTT1-arcade-P<n>.tail`, next to the model, written from the .stick:

    'TAL1', u16 segments, u16 material, u16 T3 root bone, u16 moves key,
    s16 root offset (x, y, z) in the root bone's frame,
    s16 rest direction (x, y, z) in the root bone's frame (4096 = 1),
    u16 stiffness, u16 damping, u16 gravity (stiffness and damping: 256 = 1;
    gravity: world units per frame per frame x 16), u16 0,
    then per segment: u16 length, u16 points, u16 quads, u16 0, the points
    (s16 x, y, z; x along the segment, from its joint), then per quad 4 x u8
    corner (PS1 order: two corners of one edge, then the two facing them; the
    face looks where (p1 - p0) x (p2 - p0) points) and 4 x u16 UV (u | v << 8).

Read at load by read_tail() (src/tekken3_ttt1_mod.c), which also moves the
chain at every frame; drawn after the head by src/tekken3_ttt1_renderer.c.

    python tools/ttt1/tail.py <Name>-TTT1-arcade-P<n>.stick [<out.tail>]
"""
import math, struct, sys
from pathlib import Path

ROGER_MOVESET = 31            # Roger's TTT1 moveset, Alex's too (tools/data/ttt1_characters.json)
ROOT_BONE = 0                 # T3 bone 0, the pelvis; in the TTT1 model's frame +y is up, +z the front
# Where Mokujin's tail starts in DR: 44 % of his height (829 of 1868), the centre of its first links 34 behind
# the surface of his back. Tetsujin (TTT1 model in his guard, the pelvis 1017 above the floor, 1899 high): his
# barrel's back is at z -270 there (workspace profile, tetsujin_back.py), so 0.444 x 1899 - 1017 = -174 and
# -270 - 34 x 1.05 = -306.
ROOT_OFFSET = (0, -174, -306)
REST = (0.0, -0.5, -0.866)    # back and down, 30 degrees under the horizontal
STIFFNESS, DAMPING, GRAVITY = 40, 225, 64

# Mokujin's tail in Dark Resurrection's units (Mokujin 1868 high), times SCALE for Tetsujin.
SCALE = 1.05
STEP = 324                    # joint to joint
BAR = (32, 292, 36, 31.5)     # a bar: from x, to x, half width, half height (72 x 63, 260 long)
BEVEL = (14, 0.7)             # each end: length of the bevel, size of the end face
LINK = (36.5, 22, 11, 5)      # a chain link: half length, half width, width of the ring, half thickness
LINKS = (-18, 18)             # the two links of a joint, centred either side of it
BALL = (104, 64)              # the ball: centre from the last joint, radius
SIDES, LINK_SIDES, BALL_SIDES, BALL_BANDS = 8, 6, 8, 6
TILE = (0, 127, 64, 127)      # the reflection tile in the page: u from, u to, v from, v to


def tile_u(f): return TILE[0] + f * (TILE[1] - TILE[0])
def tile_v(f): return TILE[2] + f * (TILE[3] - TILE[2])


class Mesh:
    def __init__(self): self.points, self.quads = [], []

    def add(self, pts):
        base = len(self.points); self.points += pts; return base

    def quad(self, c, out, uv):
        """Corners in PS1 order (c0 c1 one edge, c2 c3 facing), turned so their face looks along
        `out`: the renderer keeps a quad whose (p1 - p0) x (p2 - p0) faces the camera. `uv`: (u, v)
        of each corner."""
        p = [self.points[k] for k in c[:3]]
        u = [p[1][i] - p[0][i] for i in range(3)]; w = [p[2][i] - p[0][i] for i in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        if sum(n[i] * out[i] for i in range(3)) < 0:
            c = (c[1], c[0], c[3], c[2]); uv = (uv[1], uv[0], uv[3], uv[2])
        self.quads.append((tuple(c), tuple(min(255, round(a)) | min(255, round(b)) << 8 for a, b in uv)))


def centre(mesh, c): return [sum(mesh.points[k][i] for k in c) / len(c) for i in range(3)]


def bar(mesh):
    x0, x1, hy, hz = BAR; b, e = BEVEL
    rings = [(x0, e), (x0 + b, 1), (x1 - b, 1), (x1, e)]
    rv = [tile_v((x - x0) / (x1 - x0)) for x, _ in rings]
    a = [mesh.add([(x, k * hy * math.cos(t), k * hz * math.sin(t))
                   for t in (2 * math.pi * (j + .5) / SIDES for j in range(SIDES))]) for x, k in rings]
    for r in range(3):
        for j in range(SIDES):
            n = (j + 1) % SIDES
            c = (a[r] + j, a[r] + n, a[r + 1] + j, a[r + 1] + n)
            u0, u1 = tile_u(j / SIDES), tile_u((j + 1) / SIDES)
            m = centre(mesh, c); mesh.quad(c, (0, m[1], m[2]), ((u0, rv[r]), (u1, rv[r]), (u0, rv[r + 1]), (u1, rv[r + 1])))
    for ring, out in ((a[0], (-1, 0, 0)), (a[3], (1, 0, 0))):         # the end faces, three quads each
        for c in ((0, 1, 7, 2), (2, 3, 7, 6), (3, 4, 6, 5)):
            uv = [(tile_u(.5 + .4 * math.cos(2 * math.pi * (k + .5) / SIDES)),
                   tile_v(.5 + .4 * math.sin(2 * math.pi * (k + .5) / SIDES))) for k in c]
            mesh.quad(tuple(ring + k for k in c), out, uv)


def link(mesh, cx, axis):
    """A flat oval ring in the plane of x and `axis` (1: y, 2: z), both faces."""
    hl, hw, width, ht = LINK
    other = 3 - axis
    def pt(x, w, h):
        p = [x, 0, 0]; p[axis] = w; p[other] = h; return tuple(p)
    ang = [2 * math.pi * j / LINK_SIDES for j in range(LINK_SIDES)]
    faces = []
    for h in (ht, -ht):
        outer = mesh.add([pt(cx + hl * math.cos(t), hw * math.sin(t), h) for t in ang])
        inner = mesh.add([pt(cx + (hl - width) * math.cos(t), (hw - width) * math.sin(t), h) for t in ang])
        faces.append((outer, inner, h))
    for outer, inner, h in faces:
        out = [0, 0, 0]; out[other] = 1 if h > 0 else -1
        for j in range(LINK_SIDES):
            n = (j + 1) % LINK_SIDES
            u0, u1 = tile_u(j / LINK_SIDES), tile_u((j + 1) / LINK_SIDES)
            mesh.quad((outer + j, outer + n, inner + j, inner + n), out,
                      ((u0, tile_v(.3)), (u1, tile_v(.3)), (u0, tile_v(.7)), (u1, tile_v(.7))))


def ball(mesh, cx):
    r = BALL[1]
    lat = [math.pi * k / BALL_BANDS for k in range(1, BALL_BANDS)]
    poles = mesh.add([(cx - r, 0, 0), (cx + r, 0, 0)])
    rings = [mesh.add([(cx - r * math.cos(f), r * math.sin(f) * math.cos(t), r * math.sin(f) * math.sin(t))
                       for t in (2 * math.pi * j / BALL_SIDES for j in range(BALL_SIDES))]) for f in lat]
    def out(c): m = centre(mesh, c); return (m[0] - cx, m[1], m[2])
    for j in range(BALL_SIDES):
        n = (j + 1) % BALL_SIDES
        u0, u1, um = tile_u(j / BALL_SIDES), tile_u((j + 1) / BALL_SIDES), tile_u((j + .5) / BALL_SIDES)
        last = len(rings) - 1
        for c, v0, v1 in (((rings[0] + j, rings[0] + n, poles, poles), tile_v(1 / BALL_BANDS), tile_v(0)),     # the ends:
                          ((rings[last] + j, rings[last] + n, poles + 1, poles + 1),                            # a triangle
                           tile_v(1 - 1 / BALL_BANDS), tile_v(1))):                                             # (2, 3 = pole)
            mesh.quad(c, out(c), ((u0, v0), (u1, v0), (um, v1), (um, v1)))
        for k in range(last):
            c = (rings[k] + j, rings[k] + n, rings[k + 1] + j, rings[k + 1] + n)
            va, vb = tile_v((k + 1) / BALL_BANDS), tile_v((k + 2) / BALL_BANDS)
            mesh.quad(c, out(c), ((u0, va), (u1, va), (u0, vb), (u1, vb)))


def material(stick):
    """Material of the sword's blade (the first STK1 block): the body's page and palette."""
    if stick[:4] != b'STK1': raise ValueError('pas un .stick')
    return struct.unpack_from('<3H', stick, 4)[2]


def segments():
    """(length, points, quads) per segment, in Tetsujin's units: three bars, then the ball."""
    out = []
    for s in range(4):
        m = Mesh()
        for k, cx in enumerate(LINKS): link(m, cx, 1 + (k + s) % 2)
        if s < 3: bar(m); length = STEP
        else: ball(m, BALL[0]); length = BALL[0]
        pts = [tuple(round(v * SCALE) for v in p) for p in m.points]
        out.append((round(length * SCALE), pts, m.quads))
    return out


def build(stick):
    return material(stick), segments()


def write(path, stick_path):
    """Writes the .tail beside a Tetsujin / Kinjin model from its .stick. Returns the quad count
    (0: no .stick or no sword in it, the .tail is removed)."""
    path, stick_path = Path(path), Path(stick_path)
    if not stick_path.is_file():
        path.unlink(missing_ok=True); return 0
    mat, segs = build(stick_path.read_bytes())
    data = bytearray(b'TAL1' + struct.pack('<4H', len(segs), mat, ROOT_BONE, ROGER_MOVESET))
    data += struct.pack('<3h', *ROOT_OFFSET) + struct.pack('<3h', *(round(c * 4096) for c in REST))
    data += struct.pack('<4H', STIFFNESS, DAMPING, GRAVITY, 0)
    total = 0
    for length, points, quads in segs:
        data += struct.pack('<4H', length, len(points), len(quads), 0)
        for p in points: data += struct.pack('<3h', *p)
        for corners, uv in quads: data += bytes(corners) + struct.pack('<4H', *uv)
        total += len(quads)
    path.write_bytes(bytes(data))
    return total


if __name__ == '__main__':
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix('.tail')
    print(out, write(out, src), 'quads')
