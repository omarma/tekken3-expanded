#!/usr/bin/env python3
"""Arcade Stages, step E2: one binary file per arcade stage, for the runtime (E4).

    python tools/arcade_stages/pack.py [--stages 0-12] [--check]
    python tools/arcade_stages/pack.py --game ttt [--stages 0-14] [--zip tektagt.zip] [--check]

Writes workspace/arcade-stages/pack/stageNN.ast from the user's tekken3.zip
(never committed). --check reloads every file and compares the commands it
gives with the decoder's for every MAME dump (validate.py captures): the file
holds everything the stage drawing needs. --game ttt (TTT Stages S2): the 15
Tekken Tag Tournament stages from tektagt.zip (ttt.py), format FORMAT_TTT, in
workspace/ttt-stages/pack; --check against both variants' captures.

Format, version FORMAT (TIPS section 91), little-endian, offsets from the
start of the file, every section 4-byte aligned:

  header   char[4] 'ASTG', u16 version, u16 stage, u32 sections, u32 file size
  table    sections x (char[4] id, u32 offset, u32 size)

  VRAM  u32 n; n x (u16 x, y, w, h, then w * h u16): rectangles for
        psx_mod_gpu_high_vram_upload, all in y 512..1023: the textures at their
        System 12 place (stage, objects, animation frames), then the palettes
        moved up from rows 96..224 (one rectangle per run of a row).
  CLUT  u32 n; n x (u16 old x, old y, new x, new y, width, 0): the palette
        relocation (format 2). Every CLUT word in this file is already the
        new one: (new y << 6 | new x / 16), bit 15 set (E3: y + 512).
  TILE  u32 tile size, u32 tiles (256, 16 x 16, row z then column x);
        per tile: u8 OT slot (1..15), u8 OT B, u8 skipped by the game, u8 0,
        u16 vertices, u16 primitives, then vertices (s16 x, y, z, 0: world / 10,
        y down) and primitives (PRIM). The game draws all the tiles with one
        matrix; in a slot, the last primitive of the last tile comes first.
  PRIM  40 bytes: u32 TMD header (decode.KINDS), u8 kind (0 FT3, 1 FT4, 2 F4,
        3 GT3, 4 GT4, 5 G3, 6 G4), u8 GPU code, u8 third culling vertex (2, 3),
        u8 colours given (0, 1, 3, 4), u8 vertex index x 4, u8 (u, v) x 4,
        u16 CLUT, u16 tpage (System 12: bit 11 = y + 512), u8 (r, g, b) x 4
        (0x80 when not given), u8 texture window x, y, w, h (all 0: none).
  FARB  s16 columns, rows, ring, y offset, degrees, pitch factor (low
        resolution), u8 cell rgb[3], top rgb[3], top on, bottom rgb[3],
        bottom on, 0; then u16 cell textures rows x columns, u16 CLUTs rows x
        columns, u8 kinds rows x ring (padded).
  FLOR  s16 kind, fog, s32 near; (u32 w0, w1) x 100 cells (row-major,
        10 x 10), x 400 half cells (20 x 20); u8 texture index x 100 (padded);
        u16 vertices, (s16 x, z) x n; per cell (grid order) u8 sub-quads
        (padded), then u32 four vertex indices per sub-quad; corner uv: for
        1, 2, 4 sub-quads, 4 rotations x n x 4 u16 (u | v << 8).
  TRIG  s16 sine x 4096, cosine x 4096 (4.12), SquareRoot0 table x 192,
        u8 fog ramp x 1024, s16 0x801AEC2C square root table x 192.
  OBJS  (stages 3, 11) u32 models; per model u16 vertices, u16 primitives,
        vertices, PRIM records; then u32 n, n x (u8 model, u8 0, u16 main OT
        rank, u16 private OT size, u16 0) in drawing call order.
  ANIM  (stages 6, 12) u16 destination x, y, w, h, u16 period (frames), u16
        n; n x (u16 x, y) source frames in VRAM.
  ROTT  (stages 3, 11; format 3) u32 x 4096: the objects' rotation table
        0x8021688C (sine | cosine << 16, 4.12), RotMatrix / RotMatrixYXZ.

Format 4 (FORMAT_TTT, TTT Stages S2): the Tekken Tag Tournament stages
(ttt.py; the stage number is TTT's, 0..14). Tekken 3 packs stay format 3.

  header   char[4] 'ASTG', u16 4, u16 stage, u32 sections, u32 file size,
           char[4] source 'TTTA' (TTT arcade), u32 0
  table    sections x (char[4] id, u32 offset, u32 size), from byte 24
  VRAM, CLUT  as format 3: the stage's textures (archive, objects, its files
        of the effects archives 5 / 6: animation frames, stage 4's storm
        skies, stage 14's floor), then the palettes moved up (stage 11's 480
        floor-light CLUTs and stage 14's 32 included).
  TILE  as format 3 (the normal variant), but: tile byte 3 bit 0 = skipped
        with True Ogre; PRIM byte 5 = the GPU code (0x2E: stage 6's
        semi-transparent FT4, abr in the page); PRIM byte 6 = third culling
        vertex | 0x80 masked (never drawn, 0x8015D28C) | 0x40 masked with True
        Ogre | 0x20 frame test before NCLIP | 0x10 no NCLIP (FT4 0x2C000709) |
        0x08 keeps its colours with True Ogre (stage 6's rewritten FT4).
  FAR2  s16 columns, rows, ring, y offset, degrees, pitch factor (low
        resolution); u8 cell rgb[3], top rgb[3], top on, bottom rgb[3], bottom
        on, mode (0 cells, 1 gradient, 2 plain top colour), clamp y <= 0, has
        a lowest y; s16 lowest y; u8 gradient rgb[3], 0; u16 cell textures
        rows x columns, u16 CLUTs rows x columns, u8 kinds rows x ring
        (padded). Cell uv: u = (d * 32) & 0xFF, v = (d & 0x38) * 4.
  STRM  (stage 4) s16 thresholds x 5, 0; u8 rgb, 0 x 6 light colours; 6 flash
        sequences (u8 length, s8 values: 1 lit, 0 normal sky, -1 end; padded);
        6 lit skies (entries 15..20: u16 cell textures, u16 CLUTs, as FAR2);
        (u16 sound, voice) x 5 flash types; (u16 idle frame, counter) x 2
        forced flashes. Logic: ttt.TttStorm.
  FLR2  s16 kind, fog, cell size; u8 columns, rows, kind 2 halved (stage 8),
        0, 0, 0; (u32 w0, w1) x 15 x 15 map cells (CLUT moved up; 0 past
        columns / rows); u8 texture rank x 225 (padded); u8 kind-0 shades x
        1024; u16 vertices, (s16 x, z) x n (padded); u32 quads, u32 four
        vertex indices per quad; corner uv offsets (u16 x 4) for rotation x
        mirror x flip (ttt.FLOOR_CORNERS order).
  LITE  (stage 11) u32 480: the floor-light CLUT table (0x802E6348, CLUT << 16).
  TRG2  s16 sine x 5120 (1.12, cosine = +0x400), SquareRoot0 table x 192.
  OBJS  (stages 3, 11) as format 3, layout word 4 = 1 when drawn only in the
        rankings (stage 11); then s32 x 3 the model frame (0x8019C9CC).
  ROTT  (stages 3, 11) RotMatrix's table 0x8023D2F8.
  TANM  (stages 3, 6, 7, 14) u16 stage, 0; then 0x8015EB70's tables (CLUT
        positions moved up): 3: (u16 x, y) x 64; 6: x 32 even, x 96 odd, u8
        switch x 96, u32 n, (u16 x, y, x, y) x n, (u16 x, y) CLUT x n, CLUT
        destination; 7: s16 x 26 x 7 sequences, (u16 x, y, CLUT x, y) x 53,
        CLUT destination; 14: u8 cycle x 64, (u16 x, y) x 32 CLUTs, CLUT
        destination. Logic: ttt.TttAnim.
  PART  (stage 2) u16 page, u8 u, v, u16 CLUT, 0; (s16 x, y, z, 0) x 4 quad
        corners; u16 at the round start, every n frames, while fewer effects
        than, drawn when SZ >> 5 >=; u16 distance base, random mask; u16 fall
        x mask, y speed, z mask, 0 (texture in VRAM; logic: ttt.TttParticles).
  GLOW  (stage 11, TTT Stages S4) the light beams at the fighters' feet
        (ttt.glow_commands): (s16 x, y, z, 0) x 14 vertices; u8 vertex index
        x 4 x 6 GT4; 6 x (u8 rgb0, 0, rgb1, 0, rgb2, 0, rgb3, 0); u8 strip u x 4;
        u16 page, CLUT (moved up); u8 body parts 14, 17, 0, 0.
  TOGR  u8 True Ogre colour, u8 floor kind with True Ogre (0xFF none), u8 7
        (far background black, no objects, no stage 7 animation), 0.
  MISC  u32 fight axis at the round start (0x80022DD4), u16 main OT ranks of
        OT A and OT B.
  LGHT  (B76) the light on the fighters: the stage's 24-byte entry of TTT's
        table 0x80194164 (entry n + 1, ttt.fighter_light), as it is: the
        first 24 bytes of the PS1's 28-byte entry 0x80096C78 + 28 arena.
  THND  (stage 4, TTT Stages S3) the storm's thunder: u32 n; n x (u16 sound,
        u16 0, u32 frames, u32 offset from the section's start); then mono s16
        PCM at 44 100 Hz. Replayed from tools/data/ttt1_sfx_registers.json
        (indexes 0x1000 | sound: the H8 driver's writes to the C352, measured
        once in MAME as section 62's sounds) over the player's c352 ROM, cut
        as tools/ttt1/sfx.py cuts, x sfx.GAIN. MAME's front output is L = -R
        (to 2 LSB) for these four sounds: summed to mono they vanish, so the
        pack keeps L, which the game plays on both sides.

--game ttt also writes version.txt (version.TTT_STAGES_VERSION) once all 15
packs are made.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/arcade_stages')]
import decode  # noqa: E402
import scene  # noqa: E402

FORMAT = 3
OUT = decode.WORK / 'pack'
OUT_TTT = ROOT / 'workspace/ttt-stages/pack'
KIND_IDS = ['FT3', 'FT4', 'F4', 'GT3', 'GT4', 'G3', 'G4']


def pad4(b: bytes) -> bytes:
    return b + bytes(-len(b) % 4)


def prim_bytes(p: decode.Prim) -> bytes:
    n = len(p.idx)
    idx = list(p.idx) + [0] * (4 - n)
    uv = list(p.uv) + [(0, 0)] * (4 - len(p.uv))
    rgb = list(p.colors) + [p.rgb()] * (4 - len(p.colors))
    out = struct.pack('<I4B', p.header, KIND_IDS.index(p.kind), p.code, p.cull[2], len(p.colors))
    out += bytes(idx) + bytes(c for xy in uv for c in xy)
    out += struct.pack('<2H', p.clut, p.tpage) + bytes(c for col in rgb for c in col)
    out += bytes(p.window or (0, 0, 0, 0))
    assert len(out) == 40
    return out


def prim_from(b: bytes, o: int) -> decode.Prim:
    header, kind, code, cull, ncol = struct.unpack_from('<I4B', b, o)
    name = KIND_IDS[kind]
    n = decode.KINDS[header][1]
    idx = tuple(b[o + 8:o + 8 + n])
    uv = tuple((b[o + 12 + 2 * k], b[o + 13 + 2 * k]) for k in range(n)) if decode.KINDS[header][2] else ()
    clut, tpage = struct.unpack_from('<2H', b, o + 20)
    rgb = [tuple(b[o + 24 + 3 * k:o + 27 + 3 * k]) for k in range(4)]
    colors = tuple(rgb[:ncol]) if ncol else ()
    window = tuple(b[o + 36:o + 40]) if header & 0x80000000 else None
    return decode.Prim(header, name, idx, uv, clut if uv else 0, tpage if uv else 0, colors, window)


def tile_section(geo) -> bytes:
    out = struct.pack('<2I', geo.tile_size, len(geo.tiles))
    for t in geo.tiles:
        out += struct.pack('<4B2H', t.slot, int(t.layer_b), int(t.skipped), 0, len(t.verts), len(t.prims))
        out += b''.join(struct.pack('<4h', *v, 0) for v in t.verts)
        out += b''.join(prim_bytes(p) for p in t.prims)
    return out


# The 64 x 64 strong-hit effect's cells (F12, src/tekken3_ttt1_combat.c hfx_cell): rows 768 and
# 832, and row 896 up to x 768 (the palettes, the 36 images of TTT PS2's sparks, F13), free in every
# stage measured. Not counted as used pages: the palette runs keep the places they had before.
HIT_EFFECT_64_CELLS = ((544, 768, 32, 64), (592, 768, 432, 64), (544, 832, 480, 64), (544, 896, 224, 64))


class Relocation:
    """Palettes moved to the high half (E3: the runtime reads System 12 CLUT
    words, bit 15 = y + 512, but rows 96..224 of the low half belong to the
    PS1 game). Every run of 16-colour cells on a palette row moves as one
    piece, so a CLUT word pointing anywhere in it, 4 or 8 bits, still finds
    its colours; runs go to free places of the high half (no texture there),
    pages without any texture first, bottom right first."""

    def __init__(self, st):
        import numpy as np
        images = [r[1:5] for r in st.rects if r[0] == 'image']
        assert all(y >= 512 for x, y, w, h in images), 'a stage texture in the low half'
        cells = set()
        for k, x, y, w, h in (r[:5] for r in st.rects):
            if k == 'clut':
                assert y + h <= 512, 'a palette in the high half'
                cells |= {(cx, yy) for yy in range(y, y + h) for cx in range(x // 16, (x + w + 15) // 16)}
        for x, y in st.patches:
            cells |= {(x // 16, y)}
        used = np.zeros((512, 1024), bool)
        for x, y, w, h in images:
            used[y - 512:y - 512 + h, x:x + w] = True
        page_used = used.reshape(2, 256, 16, 64).any(axis=(1, 3))      # [row of pages, column]
        for x, y, w, h in HIT_EFFECT_64_CELLS:                          # never a palette there
            used[y - 512:y - 512 + h, x:x + w] = True
        runs = []
        for y in sorted({y for _, y in cells}):
            xs = sorted(cx for cx, yy in cells if yy == y)
            start = prev = xs[0]
            for cx in xs[1:] + [None]:
                if cx != prev + 1:
                    runs.append((y, start, prev + 1 - start))
                    start = cx
                prev = cx
        self.map, self.runs = {}, []
        for y, cx0, n in sorted(runs, key=lambda r: (-r[2], r[0], r[1])):
            spot = self.place(used, page_used, n, prefer_free_pages=True) or self.place(used, page_used, n, False)
            if spot is None:
                raise ValueError(f'stage {st.stage}: no room for a {16 * n}-colour palette run in the high half')
            nx, ny = spot
            used[ny - 512, nx:nx + 16 * n] = True
            self.runs.append((cx0 * 16, y, nx, ny, 16 * n))
            for k in range(n):
                self.map[cx0 + k, y] = (nx // 16 + k, ny)

    @staticmethod
    def place(used, page_used, n, prefer_free_pages):
        w = 16 * n
        for yy in range(511, -1, -1):
            for x in range(1024 - w, -1, -16):
                if used[yy, x:x + w].any():
                    continue
                if prefer_free_pages and page_used[yy // 256, x // 64:(x + w - 1) // 64 + 1].any():
                    continue
                return x, yy + 512
        return None

    def clut(self, word):
        """Old System 12 CLUT word (low half) -> new one (bit 15 set)."""
        if word & 0x8000:
            raise ValueError(f'CLUT {word:04X} already in the high half')
        key = (word & 0x3F, word >> 6 & 0x1FF)
        if key not in self.map:
            raise ValueError(f'CLUT {word:04X} outside the stage palettes')
        nx, ny = self.map[key]
        return (ny << 6 | nx) & 0xFFFF

    def prim(self, p):
        import dataclasses
        return dataclasses.replace(p, clut=self.clut(p.clut)) if p.uv else p

    def word1(self, w1):
        """Floor cell word: CLUT in the high half."""
        return (w1 & 0xFFFF) | self.clut(w1 >> 16) << 16

    def command(self, c):
        """A scene command with its CLUT relocated."""
        return dict(c, clut=self.clut(c['clut'])) if 'clut' in c else c


def save(st: scene.Stage, path: Path):
    import copy
    s = st.stage
    sections = []
    reloc = Relocation(st)
    vram = st.vram
    # VRAM rectangles, in upload order: textures, then the relocated palettes
    blob, count = b'', 0
    for kind, x, y, w, h, bpp in st.rects:
        if kind == 'image':
            blob += struct.pack('<4H', x, y, w, h) + vram[y:y + h, x:x + w].astype('<u2').tobytes()
            count += 1
    for x, y, nx, ny, w in reloc.runs:
        blob += struct.pack('<4H', nx, ny, w, 1) + vram[y, x:x + w].astype('<u2').tobytes()
        count += 1
    sections.append((b'VRAM', struct.pack('<I', count) + blob))
    sections.append((b'CLUT', struct.pack('<I', len(reloc.runs))
                     + b''.join(struct.pack('<6H', x, y, nx, ny, w, 0) for x, y, nx, ny, w in reloc.runs)))
    geo = copy.deepcopy(st.geo)
    for t in geo.tiles:
        t.prims = [reloc.prim(p) for p in t.prims]
    sections.append((b'TILE', tile_section(geo)))
    fb = copy.deepcopy(st.farbg)
    fb.cluts = [[reloc.clut(c) for c in r] for r in fb.cluts]
    farb = struct.pack('<6h', fb.cols, fb.rows, fb.ring, fb.yoff, fb.degrees, fb.pitch)
    farb += bytes(fb.cell_rgb) + bytes(fb.top_rgb) + bytes([fb.top_on]) + bytes(fb.bottom_rgb) + bytes([fb.bottom_on, 0])
    farb += b''.join(struct.pack('<%dH' % fb.cols, *r) for r in fb.desc)
    farb += b''.join(struct.pack('<%dH' % fb.cols, *r) for r in fb.cluts)
    farb += pad4(bytes(k for r in fb.kinds for k in r))
    sections.append((b'FARB', farb))
    fl = copy.deepcopy(st.floor)
    fl.cells = [[(w0, reloc.word1(w1)) for w0, w1 in r] for r in fl.cells]
    fl.halves = [[(w0, reloc.word1(w1)) for w0, w1 in r] for r in fl.halves]
    flor = struct.pack('<2hi', fl.kind, fl.fog, fl.near)
    flor += b''.join(struct.pack('<2I', *c) for r in fl.cells for c in r)
    flor += b''.join(struct.pack('<2I', *c) for r in fl.halves for c in r)
    flor += pad4(bytes(u for r in fl.unique for u in r))
    flor += pad4(struct.pack('<H', len(fl.verts)) + b''.join(struct.pack('<2h', *v) for v in fl.verts))
    flor += pad4(bytes(len(fl.quads[r, c]) for r in range(10) for c in range(10)))
    flor += b''.join(struct.pack('<%dI' % len(fl.quads[r, c]), *fl.quads[r, c]) for r in range(10) for c in range(10))
    for n in (1, 2, 4):
        flor += b''.join(struct.pack('<4H', *q) for rot in fl.uv[n] for q in rot)
    sections.append((b'FLOR', flor))
    t = st.tables
    sections.append((b'TRIG', struct.pack('<4096h4096h192h', *t.sin, *t.cos, *t.sqrt) + t.fog
                     + struct.pack('<192h', *t.sqrt2)))
    if st.objects:
        objs = struct.pack('<I', len(st.objects))
        for m in st.objects:
            objs += struct.pack('<2H', len(m.verts), len(m.prims))
            objs += b''.join(struct.pack('<4h', *v, 0) for v in m.verts)
            objs += b''.join(prim_bytes(reloc.prim(p)) for p in m.prims)
        lay = scene.object_layout(s)
        objs += struct.pack('<I', len(lay)) + b''.join(struct.pack('<2B3H', m, 0, r, n, 0) for m, r, n in lay)
        sections.append((b'OBJS', objs))
    if st.rot_table:
        sections.append((b'ROTT', struct.pack('<4096I', *st.rot_table)))
    if s in decode.ANIMATED:
        frames = st.anim
        anim = struct.pack('<6H', *decode.ANIMATED[s], 16, 64, decode.ANIM_PERIOD, len(frames))
        anim += b''.join(struct.pack('<2H', *f) for f in frames)
        sections.append((b'ANIM', anim))
    head = 16 + 12 * len(sections)
    table, body, off = b'', b'', head
    for sid, data in sections:
        data = pad4(data)
        table += struct.pack('<4s2I', sid, off, len(data))
        body += data
        off += len(data)
    path.write_bytes(struct.pack('<4s2H2I', b'ASTG', FORMAT, s, len(sections), off) + table + body)


def load(path: Path, anim_frame=None) -> scene.Stage:
    """A scene.Stage rebuilt from a pack file alone."""
    import numpy as np
    b = path.read_bytes()
    magic, version, stage, n, size = struct.unpack_from('<4s2H2I', b, 0)
    assert magic == b'ASTG' and version == FORMAT and size == len(b), (magic, version, size, len(b))
    sec = {}
    for i in range(n):
        sid, off, ln = struct.unpack_from('<4s2I', b, 16 + 12 * i)
        sec[sid] = off
    st = scene.Stage.__new__(scene.Stage)
    st.stage = stage
    # VRAM
    o = sec[b'VRAM']
    count = struct.unpack_from('<I', b, o)[0]; o += 4
    v = np.zeros((1024, 1024), np.uint16)
    st.rects = []
    for _ in range(count):
        x, y, w, h = struct.unpack_from('<4H', b, o); o += 8
        v[y:y + h, x:x + w] = np.frombuffer(b, '<u2', w * h, o).reshape(h, w); o += 2 * w * h
        st.rects.append(('rect', x, y, w, h, 0))
    if b'ANIM' in sec and anim_frame is not None:
        a = sec[b'ANIM']
        dx, dy, w, h, period, nf = struct.unpack_from('<6H', b, a)
        sx, sy = struct.unpack_from('<2H', b, a + 12 + 4 * anim_frame)
        v[dy:dy + h, dx:dx + w] = v[sy:sy + h, sx:sx + w].copy()
    st.vram = v
    # tiles
    o = sec[b'TILE']
    tile_size, nt = struct.unpack_from('<2I', b, o); o += 8
    geo = decode.Geometry(tile_size)
    for i in range(nt):
        slot, lb, skipped, _, nv, npr = struct.unpack_from('<4B2H', b, o); o += 8
        verts = [struct.unpack_from('<3h', b, o + 8 * k) for k in range(nv)]; o += 8 * nv
        prims = [prim_from(b, o + 40 * k) for k in range(npr)]; o += 40 * npr
        geo.tiles.append(decode.Tile(i, verts, prims, slot=slot, layer_b=bool(lb), skipped=bool(skipped)))
    st.geo = geo
    # far background
    o = sec[b'FARB']
    cols, rows, ring, yoff, degrees, pitch = struct.unpack_from('<6h', b, o); o += 12
    c = b[o:o + 12]; o += 12
    desc = [list(struct.unpack_from('<%dH' % cols, b, o + 2 * cols * r)) for r in range(rows)]; o += 2 * cols * rows
    cluts = [list(struct.unpack_from('<%dH' % cols, b, o + 2 * cols * r)) for r in range(rows)]; o += 2 * cols * rows
    kinds = [list(b[o + ring * r:o + ring * (r + 1)]) for r in range(rows)]
    st.farbg = scene.FarBg(stage, cols, rows, ring, desc, cluts, kinds, yoff, degrees, pitch,
                           tuple(c[0:3]), tuple(c[3:6]), c[6], tuple(c[7:10]), c[10])
    # floor
    o = sec[b'FLOR']
    kind, fog, near = struct.unpack_from('<2hi', b, o); o += 8
    w = struct.unpack_from('<1000I', b, o); o += 4000
    cells = [[(w[2 * (10 * r + c)], w[2 * (10 * r + c) + 1]) for c in range(10)] for r in range(10)]
    halves = [[(w[200 + 2 * (20 * r + c)], w[201 + 2 * (20 * r + c)]) for c in range(20)] for r in range(20)]
    unique = [list(b[o + 10 * r:o + 10 * r + 10]) for r in range(10)]; o += 100 + (-100 % 4)
    nv = struct.unpack_from('<H', b, o)[0]
    verts = [struct.unpack_from('<2h', b, o + 2 + 4 * k) for k in range(nv)]
    o += len(pad4(bytes(2 + 4 * nv)))
    counts = b[o:o + 100]; o += 100
    quads = {}
    for r in range(10):
        for cc in range(10):
            k = counts[10 * r + cc]
            quads[r, cc] = list(struct.unpack_from('<%dI' % k, b, o)); o += 4 * k
    uv = {}
    for nq in (1, 2, 4):
        uv[nq] = [[struct.unpack_from('<4H', b, o + 8 * (rot * nq + q)) for q in range(nq)] for rot in range(4)]
        o += 8 * 4 * nq
    st.floor = scene.Floor(stage, kind, fog, cells, halves, unique, verts, quads, near, uv)
    o = sec[b'TRIG']
    t = struct.unpack_from('<4096h4096h192h', b, o)
    st.tables = scene.Tables(t[:4096], t[4096:8192], t[8192:], b[o + 16768:o + 16768 + 1024],
                             struct.unpack_from('<192h', b, o + 16768 + 1024))
    st.rot_table = struct.unpack_from('<4096I', b, sec[b'ROTT']) if b'ROTT' in sec else None
    st.objects = []
    if b'OBJS' in sec:
        o = sec[b'OBJS']
        nm = struct.unpack_from('<I', b, o)[0]; o += 4
        for i in range(nm):
            nv, npr = struct.unpack_from('<2H', b, o); o += 4
            verts = [struct.unpack_from('<3h', b, o + 8 * k) for k in range(nv)]; o += 8 * nv
            prims = [prim_from(b, o + 40 * k) for k in range(npr)]; o += 40 * npr
            st.objects.append(decode.Tile(0, verts, prims))
    return st


# ---------------------------------------------------------------------------
# TTT packs (TTT Stages S2): format 4, the source in the header. Tekken 3
# arcade packs stay format 3, byte for byte.
# ---------------------------------------------------------------------------
FORMAT_TTT = 4
SOURCE_TTT = b'TTTA'
# PRIM byte 6 (third culling vertex, 2 or 3) carries in format 4:
PRIM_MASKED, PRIM_MASKED_TO, PRIM_FRAMED, PRIM_NO_NCLIP, PRIM_KEEPS_COLOUR = 0x80, 0x40, 0x20, 0x10, 0x08


def ttt_prim_bytes(p, k, tile, reloc):
    import ttt
    q = reloc.prim(p)
    b = bytearray(prim_bytes(q))
    b[5] = p.code
    flags = 0
    if k in tile.masked_always:
        flags |= PRIM_MASKED
    if k in tile.masked_to:
        flags |= PRIM_MASKED_TO
    if p.header in ttt.FRAME_TESTED:
        flags |= PRIM_FRAMED
    if p.header in ttt.NO_NCLIP:
        flags |= PRIM_NO_NCLIP
    if p.keeps:
        flags |= PRIM_KEEPS_COLOUR
    b[6] |= flags
    return bytes(b)


def ttt_prim_from(b, o):
    import dataclasses
    import ttt
    flags = b[o + 6] & 0xF8
    c = bytearray(b[o:o + 40])
    c[6] &= 7
    p = prim_from(bytes(c), 0)
    q = ttt.TttPrim(**{f.name: getattr(p, f.name) for f in dataclasses.fields(decode.Prim)},
                    semi=bool(b[o + 5] & 2), keeps=bool(flags & PRIM_KEEPS_COLOUR))
    return q, flags


def reloc_xy(reloc, x, y):
    """A CLUT position of the low half -> its place in the high half."""
    w = reloc.clut((y << 6 | x >> 4) & 0x7FFF)
    return (w & 0x3F) << 4 | (x & 15), w >> 6


THUNDER = (0x121, 0x122, 0x123, 0x124)     # ttt.STORM_SOUNDS' sounds, driver IDs


def thunder(c352_rom):
    """[(sound, mono s16 PCM bytes)] of the storm's thunder, replayed from the
    measured table over the c352 ROM (sfx.replay = MAME's recording, sample
    for sample), cut at sfx.SILENCE on either side, x sfx.GAIN, left channel."""
    import json
    import numpy as np
    sys.path[:0] = [str(ROOT / 'tools/ttt1')]
    import sfx
    table = json.loads(sfx.REGISTERS.read_text())['sounds']
    out = []
    for sound in THUNDER:
        e = dict(table[str(0x1000 | sound)])
        n, writes = e['start'], []
        for w in e['writes']:
            n += w[0]
            writes.append((n, w[1], w[2], w[3] if len(w) > 3 else 0xffff))
        e['writes'] = writes
        seg = sfx.replay(c352_rom, e)
        left, right = seg[0::2], seg[1::2]
        loud = np.flatnonzero((np.abs(left) > sfx.SILENCE) | (np.abs(right) > sfx.SILENCE))
        pcm = left[loud[0]:loud[-1] + 1] if len(loud) else left[:0]
        pcm = np.concatenate([np.clip(np.round(pcm * sfx.GAIN), -32768, 32767), np.zeros(32)]).astype('<i2')
        out.append((sound, pcm.tobytes()))
    return out


def thunder_section(sounds):
    head = 4 + 12 * len(sounds)
    table, body = b'', b''
    for sound, pcm in sounds:
        table += struct.pack('<2H2I', sound, 0, len(pcm) // 2, head + len(body))
        body += pcm
    return struct.pack('<I', len(sounds)) + table + body


def save_ttt(st, path, src, c352_rom=None):
    """A ttt.Stage (normal variant) to a format 4 pack; the True Ogre variant
    goes in flags and the TOGR section (src: the ttt.Ttt it came from;
    c352_rom: the sound ROM, for stage 4's thunder)."""
    import ttt
    s = st.stage
    reloc = Relocation(st)
    sections = []
    vram = st.vram
    blob, count = b'', 0
    for r in st.rects:
        kind, x, y, w, h = r[:5]
        if kind == 'image':
            blob += struct.pack('<4H', x, y, w, h) + vram[y:y + h, x:x + w].astype('<u2').tobytes()
            count += 1
    for x, y, nx, ny, w in reloc.runs:
        blob += struct.pack('<4H', nx, ny, w, 1) + vram[y, x:x + w].astype('<u2').tobytes()
        count += 1
    sections.append((b'VRAM', struct.pack('<I', count) + blob))
    sections.append((b'CLUT', struct.pack('<I', len(reloc.runs))
                     + b''.join(struct.pack('<6H', x, y, nx, ny, w, 0) for x, y, nx, ny, w in reloc.runs)))
    # tiles: the normal variant, masks and True Ogre skips as flags
    g, _ = src.stage(s)
    to = ttt.parse_geometry(src, s, g, True) if g is not None else None
    tile = struct.pack('<2I', st.geo.tile_size, len(st.geo.tiles))
    for t in st.geo.tiles:
        t_to = to.tiles[t.index]
        t.masked_always, t.masked_to = t.masked, t_to.masked - t.masked
        tile += struct.pack('<4B2H', t.slot, int(t.layer_b), int(t.skipped), int(t_to.skipped), len(t.verts), len(t.prims))
        tile += b''.join(struct.pack('<4h', *v, 0) for v in t.verts)
        for k, p in enumerate(t.prims):
            tile += ttt_prim_bytes(p, k, t, reloc)
    sections.append((b'TILE', tile))
    fb = st.farbg
    far = struct.pack('<6h', fb.cols, fb.rows, fb.ring, fb.yoff, fb.degrees, fb.pitch)
    far += bytes(fb.cell_rgb) + bytes(fb.top_rgb) + bytes([fb.top_on]) + bytes(fb.bottom_rgb)
    far += bytes([fb.bottom_on, fb.mode, int(fb.clamp_top), int(fb.min_y is not None)])
    far += struct.pack('<h', fb.min_y if fb.min_y is not None else 0) + bytes(fb.gradient) + b'\0'
    far += b''.join(struct.pack('<%dH' % fb.cols, *r) for r in fb.desc)
    far += b''.join(struct.pack('<%dH' % fb.cols, *(reloc.clut(c) if c else 0 for c in r)) for r in fb.cluts)
    far += pad4(bytes(k for r in fb.kinds for k in r))
    sections.append((b'FAR2', far))
    if st.storm is not None:
        sm = st.storm
        strm = struct.pack('<5hH', *sm.thresholds, 0) + b''.join(bytes(c) + b'\0' for c in sm.colours)
        strm += pad4(b''.join(bytes([len(q)]) + bytes(v & 0xFF for v in q) for q in sm.sequences))
        for desc, cluts in sm.skies:
            strm += b''.join(struct.pack('<%dH' % fb.cols, *r) for r in desc)
            strm += b''.join(struct.pack('<%dH' % fb.cols, *(reloc.clut(c) if c else 0 for c in r)) for r in cluts)
        strm += b''.join(struct.pack('<2H', *x) for x in ttt.STORM_SOUNDS)
        strm += b''.join(struct.pack('<2H', *x) for x in ttt.STORM_FORCED)
        sections.append((b'STRM', strm))
        if c352_rom is not None:
            sections.append((b'THND', thunder_section(thunder(c352_rom))))
    fl = st.floor
    if fl is not None:
        flr = struct.pack('<3h', fl.kind, fl.fog, fl.size) + bytes([fl.cols, fl.rows, int(fl.half), 0]) + b'\0\0'
        # map cells past cols / rows (14 x 14 floors) are never drawn: no CLUT to move
        flr += b''.join(struct.pack('<2I', w0, reloc.word1(w1) if r < fl.rows and c < fl.cols else w1 & 0xFFFF)
                        for r in range(15) for c, (w0, w1) in enumerate(fl.cells[r]))
        flr += pad4(bytes(u for r in fl.unique for u in r))
        flr += bytes(fl.ramp)
        flr += pad4(struct.pack('<H', len(fl.verts)) + b''.join(struct.pack('<2h', *v) for v in fl.verts))
        flr += struct.pack('<I', len(fl.quads)) + struct.pack('<%dI' % len(fl.quads), *fl.quads)
        flr += b''.join(struct.pack('<4H', *ttt.FLOOR_CORNERS[(rot, m, f)])
                        for rot in range(4) for m in range(2) for f in range(2))
        sections.append((b'FLR2', flr))
    if st.lights is not None:
        sections.append((b'LITE', struct.pack('<I', len(st.lights))
                         + b''.join(struct.pack('<I', reloc.clut(w >> 16) << 16) for w in st.lights)))
    sections.append((b'TRG2', struct.pack('<5120h192h', *st.sine, *st.sqrt_table)))
    if st.objects:
        objs = struct.pack('<I', len(st.objects))
        for m in st.objects:
            objs += struct.pack('<2H', len(m.verts), len(m.prims))
            objs += b''.join(struct.pack('<4h', *v, 0) for v in m.verts)
            objs += b''.join(prim_bytes(reloc.prim(p)) for p in m.prims)
        lay = ttt.object_layout(s)
        objs += struct.pack('<I', len(lay)) + b''.join(struct.pack('<2B3H', m, 0, r, n, int(s == 11)) for m, r, n in lay)
        objs += struct.pack('<3i', *st.object_frame)
        sections.append((b'OBJS', objs))
    if st.rot_table:
        sections.append((b'ROTT', struct.pack('<4096I', *st.rot_table)))
    if st.anim is not None:
        a = st.anim
        anim = struct.pack('<2H', s, 0)
        if s == 3:
            anim += b''.join(struct.pack('<2H', *q) for q in a.places)
        elif s == 6:
            anim += b''.join(struct.pack('<2H', *q) for q in a.even) + b''.join(struct.pack('<2H', *q) for q in a.odd)
            anim += a.switch + struct.pack('<I', len(a.more))
            anim += b''.join(struct.pack('<4H', *q) for q in a.more)
            anim += b''.join(struct.pack('<2H', *reloc_xy(reloc, *q)) for q in a.cluts)
            anim += struct.pack('<2H', *reloc_xy(reloc, 0x290, 0x60))
        elif s == 7:
            anim += b''.join(struct.pack('<26h', *q) for q in a.sequences)
            anim += b''.join(struct.pack('<4H', x, y, *reloc_xy(reloc, cx, cy)) for x, y, cx, cy in a.frames)
            anim += struct.pack('<2H', *reloc_xy(reloc, 0x2C0, 0x62))
        elif s == 14:
            anim += a.cycle
            anim += b''.join(struct.pack('<2H', *reloc_xy(reloc, (b & 0xF) * 16 + 0x200, 0xE0 + (b >> 4 & 1)))
                             for b in range(32))
            anim += struct.pack('<2H', *reloc_xy(reloc, 0x200, 0x60))
        sections.append((b'TANM', anim))
    if st.particles is not None:
        pt = st.particles
        part = struct.pack('<H2BHH', pt.tpage, pt.uv[0], pt.uv[1], reloc.clut(pt.clut), 0)
        part += b''.join(struct.pack('<4h', *q, 0) for q in pt.quad)
        part += struct.pack('<4H', pt.start, pt.every, pt.most, pt.near)
        part += struct.pack('<2H4H', *pt.distance, *pt.fall, 0)
        sections.append((b'PART', part))
    if getattr(st, 'glow', None) is not None:
        gl = st.glow
        glow = b''.join(struct.pack('<4h', *v, 0) for v in gl.verts)
        glow += bytes(i for q in gl.index for i in q)
        glow += b''.join(bytes(c) + bytes(1) for q in gl.colours for c in q)
        glow += bytes(gl.uv) + struct.pack('<2H', gl.tpage, reloc.clut(gl.clut)) + bytes(list(ttt.GLOW_PARTS) + [0, 0])
        sections.append((b'GLOW', glow))
    fl_to = ttt.parse_floor(src, s, True)
    sections.append((b'TOGR', bytes([st.shade, fl_to.kind if fl_to is not None else 0xFF, 7, 0])))
    a_rank, b_rank = ttt.ot_ranks(s)
    sections.append((b'MISC', struct.pack('<I2H', st.axis, a_rank, b_rank)))
    sections.append((b'LGHT', st.light))
    head = 24 + 12 * len(sections)
    table, body, off = b'', b'', head
    for sid, data in sections:
        data = pad4(data)
        table += struct.pack('<4s2I', sid, off, len(data))
        body += data
        off += len(data)
    path.write_bytes(struct.pack('<4s2H2I4sI', b'ASTG', FORMAT_TTT, s, len(sections), off, SOURCE_TTT, 0) + table + body)


def load_ttt(b, true_ogre=False):
    """A ttt.Stage rebuilt from a format 4 pack alone (true_ogre: the True
    Ogre variant from the flags and TOGR)."""
    import dataclasses
    import numpy as np
    import ttt
    magic, version, stage, n, size, source, _ = struct.unpack_from('<4s2H2I4sI', b, 0)
    assert magic == b'ASTG' and version == FORMAT_TTT and source == SOURCE_TTT and size == len(b)
    sec = {}
    for i in range(n):
        sid, off, ln = struct.unpack_from('<4s2I', b, 24 + 12 * i)
        sec[sid] = off
    st = ttt.Stage.__new__(ttt.Stage)
    st.stage, st.true_ogre = stage, true_ogre
    o = sec[b'VRAM']
    count = struct.unpack_from('<I', b, o)[0]; o += 4
    v = np.zeros((1024, 1024), np.uint16)
    st.rects = []
    for _ in range(count):
        x, y, w, h = struct.unpack_from('<4H', b, o); o += 8
        v[y:y + h, x:x + w] = np.frombuffer(b, '<u2', w * h, o).reshape(h, w); o += 2 * w * h
        st.rects.append(('rect', x, y, w, h, 0))
    st.vram = v
    to = sec[b'TOGR']
    shade, floor_to, to_flags = b[to], b[to + 1], b[to + 2]
    o = sec[b'TILE']
    tile_size, nt = struct.unpack_from('<2I', b, o); o += 8
    geo = decode.Geometry(tile_size)
    for i in range(nt):
        slot, lb, skipped, skipped_to, nv, npr = struct.unpack_from('<4B2H', b, o); o += 8
        verts = [struct.unpack_from('<3h', b, o + 8 * k) for k in range(nv)]; o += 8 * nv
        prims, masked = [], set()
        for k in range(npr):
            p, flags = ttt_prim_from(b, o); o += 40
            if flags & PRIM_MASKED or (true_ogre and flags & PRIM_MASKED_TO):
                masked.add(k)
            if true_ogre and not p.keeps:
                p = dataclasses.replace(p, colors=((shade,) * 3,) * max(1, len(p.colors)))
            prims.append(p)
        t = decode.Tile(i, verts, prims, slot=slot, layer_b=bool(lb), skipped=bool(skipped_to if true_ogre else skipped))
        t.masked = masked
        geo.tiles.append(t)
    st.geo = geo if nt else decode.Geometry(0)
    o = sec[b'FAR2']
    cols, rows, ring, yoff, degrees, pitch = struct.unpack_from('<6h', b, o); o += 12
    c = b[o:o + 14]; o += 14
    min_y = struct.unpack_from('<h', b, o)[0]; o += 2
    gradient = tuple(b[o:o + 3]); o += 4
    table = lambda o: [list(struct.unpack_from('<%dH' % cols, b, o + 2 * cols * r)) for r in range(rows)]
    desc = table(o); o += 2 * cols * rows
    cluts = table(o); o += 2 * cols * rows
    kinds = [list(b[o + ring * r:o + ring * (r + 1)]) for r in range(rows)]
    st.farbg = ttt.TttFarBg(stage, cols, rows, ring, desc, cluts, kinds, yoff, degrees, pitch, tuple(c[0:3]), tuple(c[3:6]),
                            c[6], tuple(c[7:10]), c[10], mode=c[11], clamp_top=bool(c[12]),
                            min_y=min_y if c[13] else None, gradient=gradient)
    st.storm = None
    if b'STRM' in sec:
        o = sec[b'STRM']
        thresholds = list(struct.unpack_from('<5h', b, o)); o += 12
        colours = [tuple(b[o + 4 * k:o + 4 * k + 3]) for k in range(6)]; o += 24
        seqs, p = [], o
        for _ in range(6):
            ln = b[p]
            seqs.append([x - 256 if x > 127 else x for x in b[p + 1:p + 1 + ln]])
            p += 1 + ln
        o += len(pad4(bytes(p - o)))
        skies = []
        for _ in range(6):
            d = table(o); o += 2 * cols * rows
            cl = table(o); o += 2 * cols * rows
            skies.append((d, cl))
        st.storm = ttt.Storm(thresholds, seqs, colours, skies)
    st.floor, st.lights = None, None
    if b'FLR2' in sec:
        o = sec[b'FLR2']
        kind, fog, fsize = struct.unpack_from('<3h', b, o); o += 6
        fcols, frows, half = b[o], b[o + 1], b[o + 2]; o += 6
        w = struct.unpack_from('<450I', b, o); o += 1800
        cells = [[(w[2 * (15 * r + q)], w[2 * (15 * r + q) + 1]) for q in range(15)] for r in range(15)]
        unique = [list(b[o + 15 * r:o + 15 * r + 15]) for r in range(15)]; o += 228
        ramp = list(b[o:o + 1024]); o += 1024
        nv = struct.unpack_from('<H', b, o)[0]
        fverts = [struct.unpack_from('<2h', b, o + 2 + 4 * k) for k in range(nv)]
        o += len(pad4(bytes(2 + 4 * nv)))
        nq = struct.unpack_from('<I', b, o)[0]; o += 4
        quads = list(struct.unpack_from('<%dI' % nq, b, o))
        if true_ogre and floor_to != 0xFF:
            kind = floor_to
        st.floor = ttt.TttFloor(stage, kind, fog, fcols, frows, fsize, cells, unique, fverts, quads, ramp, bool(half))
    if b'LITE' in sec:
        o = sec[b'LITE']
        nl = struct.unpack_from('<I', b, o)[0]
        st.lights = list(struct.unpack_from('<%dI' % nl, b, o + 4))
    o = sec[b'TRG2']
    st.sine = struct.unpack_from('<5120h', b, o)
    st.sqrt_table = struct.unpack_from('<192h', b, o + 10240)
    st.objects, st.object_frame = [], None
    if b'OBJS' in sec:
        o = sec[b'OBJS']
        nm = struct.unpack_from('<I', b, o)[0]; o += 4
        for _ in range(nm):
            nv, npr = struct.unpack_from('<2H', b, o); o += 4
            verts = [struct.unpack_from('<3h', b, o + 8 * k) for k in range(nv)]; o += 8 * nv
            prims = [prim_from(b, o + 40 * k) for k in range(npr)]; o += 40 * npr
            st.objects.append(decode.Tile(0, verts, prims))
        nl = struct.unpack_from('<I', b, o)[0]; o += 4 + 8 * nl
        st.object_frame = list(struct.unpack_from('<3i', b, o))
    st.rot_table = struct.unpack_from('<4096I', b, sec[b'ROTT']) if b'ROTT' in sec else None
    st.anim = None
    o = sec[b'MISC']
    st.axis = struct.unpack_from('<I', b, o)[0]
    st.light = b[sec[b'LGHT']:sec[b'LGHT'] + 24] if b'LGHT' in sec else None
    st.shade, st.patches = shade, []
    return st


def check(stages, pictures=True):
    """Every MAME dump: commands from the pack == the decoder's with the
    CLUTs relocated, and the same picture (no palette over a texture)."""
    import render
    import validate
    arcade = decode.Arcade()
    bad = 0
    for s in stages:
        ref = scene.Stage(arcade, s)
        st = load(OUT / f'stage{s:02}.ast')
        images = [(x, y, w, h) for k, x, y, w, h, _ in ref.rects if k == 'image']
        same_vram = all((st.vram[y:y + h, x:x + w] == ref.vram[y:y + h, x:x + w]).all() for x, y, w, h in images)
        d = validate.DUMPS / f'stage{s:02}'
        regs = validate.gte_lines(d / 'mame.log')
        n = 0
        reloc = Relocation(ref)
        pics = 0
        for name in sorted(regs):
            inputs = validate.frame_inputs(validate.Ram(d / f'{name}.bin'), regs[name], stage=s)
            a, b = ref.frame(**inputs), st.frame(**inputs)
            n += 1
            if [reloc.command(c) for c in a] != b:
                bad += 1
                print(f'stage {s:2} {name}: {len(a)} commands from the decoder, {len(b)} from the pack, differ')
            if pictures:
                g1, g2 = render.Gpu(ref.vram), render.Gpu(st.vram)
                render.run(g1, a); render.run(g2, b)
                if (g1.fb != g2.fb).any():
                    bad += 1
                    print(f'stage {s:2} {name}: {(g1.fb != g2.fb).sum()} pixels differ')
                pics += 1
        print(f'stage {s:2}: {n} frames, pack == decoder (CLUTs relocated): {"yes" if not bad else "NO"}, '
              f'textures {"same" if same_vram else "DIFFER"}, {pics} pictures compared, '
              f'{len(reloc.runs)} palette runs moved')
        bad += not same_vram
    return bad


def check_ttt(stages, pictures=True):
    """Every TTT MAME dump (validate_ttt.py captures): commands from the pack
    == the decoder's with the CLUTs relocated, the same picture, both
    variants (the True Ogre one against its own captures)."""
    import render
    import ttt
    import validate as v3
    import validate_ttt as vt
    src = ttt.Ttt()
    bad = 0
    for s in stages:
        for true_ogre, dumps in ((False, vt.DUMPS), (True, vt.DUMPS.with_name('mame-s2-to'))):
            ref = ttt.Stage(src, s, true_ogre)
            st = load_ttt((OUT_TTT / f'stage{s:02}.ast').read_bytes(), true_ogre)
            reloc = Relocation(ref)
            images = [r[1:5] for r in ref.rects if r[0] == 'image']
            same_vram = all((st.vram[y:y + h, x:x + w] == ref.vram[y:y + h, x:x + w]).all() for x, y, w, h in images)
            d = dumps / f'stage{s:02}'
            regs = vt.lines(d / 'mame.log') if (d / 'mame.log').exists() else {}
            n = pics = errors = 0
            rams = {}
            for name in sorted(regs):
                if not (d / f'{name}.bin').exists():
                    continue
                ram = rams[name] = v3.Ram(d / f'{name}.bin')
                prev = rams.get(name[:-1] + str(int(name[-1]) - 1))
                a = ref.frame(**vt.frame_inputs(src, ref, ram, regs[name], prev))
                b = st.frame(**vt.frame_inputs(src, st, ram, regs[name], prev))
                n += 1
                if [reloc.command(c) for c in a] != b:
                    errors += 1
                    print(f'stage {s:2} {name}: {len(a)} commands from the decoder, {len(b)} from the pack, differ')
                if pictures:
                    g1, g2 = render.Gpu(ref.vram), render.Gpu(st.vram)
                    render.run(g1, a)
                    render.run(g2, b)
                    if (g1.fb != g2.fb).any():
                        errors += 1
                        print(f'stage {s:2} {name}: {(g1.fb != g2.fb).sum()} pixels differ')
                    pics += 1
            print(f'stage {s:2}{" True Ogre" if true_ogre else ""}: {n} frames, pack == decoder (CLUTs relocated): '
                  f'{"yes" if not errors else "NO"}, textures {"same" if same_vram else "DIFFER"}, {pics} pictures compared, '
                  f'{len(reloc.runs)} palette runs moved', flush=True)
            bad += errors + (not same_vram)
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--stages', default='0-12')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--game', choices=('t3', 'ttt'), default='t3',
                    help='ttt: the 15 TTT stage packs (format 4) from tektagt.zip, in workspace/ttt-stages/pack')
    ap.add_argument('--zip', type=Path, help='--game ttt: tektagt.zip read as it is (no development cache)')
    args = ap.parse_args(argv)
    if args.game == 'ttt':
        import ttt
        stages = decode.numbers('0-14' if args.stages == '0-12' else args.stages)
        src = ttt.Ttt(args.zip, cache=args.zip is None)
        OUT_TTT.mkdir(parents=True, exist_ok=True)
        rom = None
        if ttt.STORM_STAGE in stages:
            sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/ttt_stages')]
            import music_install
            rom = music_install.c352_rom(args.zip or ttt.default_zip())
        for s in stages:
            path = OUT_TTT / f'stage{s:02}.ast'
            save_ttt(ttt.Stage(src, s), path, src, rom)
            print(f'TTT stage {s:2}: {path.name} {path.stat().st_size} bytes')
        import version
        if set(version.TTT_STAGES) <= set(stages):
            (OUT_TTT / version.STAMP).write_text(f'{version.TTT_STAGES_VERSION}\n', encoding='utf-8')
        if args.check:
            return 1 if check_ttt(stages) else 0
        return 0
    stages = decode.numbers(args.stages)
    arcade = decode.Arcade()
    OUT.mkdir(parents=True, exist_ok=True)
    for s in stages:
        st = scene.Stage(arcade, s)
        path = OUT / f'stage{s:02}.ast'
        save(st, path)
        print(f'stage {s:2}: {path.name} {path.stat().st_size} bytes')
    if args.check:
        return 1 if check(stages) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
