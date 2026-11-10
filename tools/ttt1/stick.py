#!/usr/bin/env python3
"""Mokujin's wooden sword on Yoshimitsu's moves (F32 E5).

Tekken 3 PS1 draws it as part 18 of Mokujin's model, shown only while his
moves key (+0x16) is 4 (fighter_mokujin_part18_show, t3-ps1
src/fin/80035DEC.c). TTT1 has no such mesh: when Mokujin fights with
Yoshimitsu's moves (character / table 0xF0004), it draws the sword by code
(fighter_quad_strip_f0004_init_maybe / _draw_maybe, ttt-ps1
src/combat/80102A38.c): 20 points in the frame of the hand node +0xD98 (TTT1
row 20, T3 bone 10, the frame of the sword glow), 18 opaque textured quads
(0x2C, colour 0x808080), back faces culled, each at the order table entry of
(z0 + z3) / 2:

  points   0x80193BC4, 8 bytes each (x, y, z, pad)
  quads    0x80193E3C, 12 bytes: u32 corners (i0 << 24 | i1 << 16 | i2 << 8 | i3),
           then u0 v0 .. u3 v3, in the character's own atlas
  texture  slot 30 (0x1E): 4 bits, palette x + 0x10; slot 31 (0x1F): 4 bits,
           palette x + 0x60; slot 101 (0x65): 8 bits, palette + 0, u >> 1
           (Tetsujin's 100 / 107 are not natives of Tekken 3)

The converted Mokujin has nothing on part 18 (PS1 row 21), so T3's switch
shows nothing: the runtime draws the cabinet's sword instead, after the head
like Unknown's hilt (tools/ttt1/hilt.py, whose way this follows). prims()
hands the quads to texpack.plan() so that their image is kept; write() takes
their UVs through the packing into a .stick file next to the model:

    'STK1', u16 points (20), u16 quads (18), u16 material (PS1: palette | 0x8000
    for 8 bits), u16 T3 bone (10), u16 moves key (4), u16 0,
    then 20 x (s16 x, y, z), then per quad: 4 x u8 corner, 4 x u16 UV (u | v << 8,
    folded into the costume band)

Read at load by read_stick() (src/tekken3_ttt1_mod.c), drawn by
src/tekken3_ttt1_renderer.c. No file: no sword (anyone but Mokujin).
"""
import struct

SLOTS = {0x1E: (0x00, 0x10 >> 4, 0), 0x1F: (0x00, 0x60 >> 4, 0), 0x65: (0x80, 0, 1)}   # page, palette, u shift
POINTS_AT, QUADS_AT = 0x193BC4, 0x193E3C
POINTS, COUNT, BONE, KEY = 20, 18, 10, 4


def prims(ram, slot):
    """The sword's quads as texpack sees a model's polygons: (family, material
    (page << 16 | palette), UVs), or [] for anyone but Mokujin."""
    if slot not in SLOTS: return []
    page, palette, shift = SLOTS[slot]
    out = []
    for q in range(COUNT):
        uv = ram[QUADS_AT + 12 * q + 4:QUADS_AT + 12 * q + 12]
        out.append((1, page << 16 | palette, [(uv[2 * k] >> shift, uv[2 * k + 1]) for k in range(4)]))
    return out


def write(path, ram, slot, ps1_uv):
    """Writes the .stick of this costume (texpack.plan() must have had prims());
    ps1_uv(page, palette, u, v) -> (material, UV) is the converter's. Returns
    True when written, else removes the file."""
    quads = prims(ram, slot)
    if not quads:
        path.unlink(missing_ok=True)
        return False
    uvs, materials = [], set()
    for _, mat, uv in quads:
        got = [ps1_uv(mat >> 16, mat & 0xffff, u, v) for u, v in uv]
        materials.update(m for m, _ in got)
        uvs.append([e for _, e in got])
    if len(materials) != 1: raise ValueError(f'baton : {len(materials)} materiaux apres rangement')
    data = bytearray(b'STK1' + struct.pack('<6H', POINTS, COUNT, materials.pop(), BONE, KEY, 0))
    for i in range(POINTS): data += ram[POINTS_AT + 8 * i:POINTS_AT + 8 * i + 6]
    for q in range(COUNT):
        corners = struct.unpack_from('<I', ram, QUADS_AT + 12 * q)[0]
        data += bytes([corners >> 24, corners >> 16 & 255, corners >> 8 & 255, corners & 255])
        data += struct.pack('<4H', *uvs[q])
    path.write_bytes(bytes(data))
    return True
