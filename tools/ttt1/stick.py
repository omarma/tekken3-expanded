#!/usr/bin/env python3
"""Mokujin's wooden sword on Yoshimitsu's moves (F32 E5), Tetsujin's sword and
dagger on Yoshimitsu's and Kunimitsu's (B177, GH#223).

Tekken 3 PS1 draws Mokujin's sword as part 18 of his model, shown only while
his moves key (+0x16) is 4 (fighter_mokujin_part18_show, t3-ps1
src/fin/80035DEC.c). TTT1 has no such mesh: when a fighter of body 15
(Mokujin, Tetsujin, Kinjin) fights with Yoshimitsu's moves (character / table
0xF0004) or Kunimitsu's (0xF001A), it draws the weapon by code
(fighter_quad_strip_f0004_init_maybe / _draw_maybe and their f001a twins,
ttt-ps1 src/combat/80102A38.c, called by fighter_draw at every frame), opaque
textured quads (0x2C, colour 0x808080) in the frame of a hand node, back
faces culled, each at the order table entry of (z0 + z3) / 2:

  sword    20 points 0x80193BC4 (8 bytes each: x, y, z, pad), 18 quads 0x80193E3C,
           hand node +0xD98 (TTT1 row 20, T3 bone 10), moves key 4
  dagger   17 points 0x80193C64, 17 quads 0x80193F14, hand node +0xC58
           (TTT1 row 16, T3 bone 6), moves key 26; not drawn in mode 5
  quads    12 bytes: u32 corners (i0 << 24 | i1 << 16 | i2 << 8 | i3), then
           u0 v0 .. u3 v3 in the character's own atlas
  texture  slot 30 (0x1E): 4 bits, palette x + 0x10; slot 31 (0x1F): 4 bits,
           palette x + 0x60; slot 101 (0x65): 8 bits, palette + 0, u >> 1;
           Tetsujin 100 (0x64) and Kinjin 107 (0x6B): 8 bits, palette + 0,
           v + 0x40 (the lower copy of the shine, which scrolls)

The converted Mokujin has nothing on part 18 (PS1 row 21), so T3's switch
shows nothing, and the guests have no such switch: the runtime draws the
cabinet's weapon instead, after the head like Unknown's hilt
(tools/ttt1/hilt.py, whose way this follows). prims() hands the quads to
texpack.plan() so that their image is kept; write() takes their UVs through
the packing into a .stick file next to the model, one block per weapon:

    'STK1', u16 points, u16 quads, u16 material (PS1: palette | 0x8000
    for 8 bits), u16 T3 bone, u16 moves key, u16 0,
    then points x (s16 x, y, z), then per quad: 4 x u8 corner, 4 x u16 UV (u | v << 8,
    folded into the costume band)

Mokujin's file holds the sword alone (as F32 E5 wrote it), Tetsujin's and
Kinjin's the sword, then the dagger. Read at load by read_stick()
(src/tekken3_ttt1_mod.c), drawn by src/tekken3_ttt1_renderer.c. No file: no
weapon (anyone but these).
"""
import struct

SWORD = (0x193BC4, 20, 0x193E3C, 18, 10, 4)      # points, count, quads, count, T3 bone, moves key
DAGGER = (0x193C64, 17, 0x193F14, 17, 6, 26)
# slot: (page, palette, u shift, v offset, weapons)
SLOTS = {0x1E: (0x00, 0x10 >> 4, 0, 0, (SWORD,)), 0x1F: (0x00, 0x60 >> 4, 0, 0, (SWORD,)),
         0x65: (0x80, 0, 1, 0, (SWORD,)),
         0x64: (0x80, 0, 0, 0x40, (SWORD, DAGGER)), 0x6B: (0x80, 0, 0, 0x40, (SWORD, DAGGER))}


def _quads(ram, slot):
    """Per weapon of this slot: (weapon, [(family, material, UVs) per quad])."""
    if slot not in SLOTS: return []
    page, palette, shift, v0, weapons = SLOTS[slot]
    out = []
    for w in weapons:
        quads = []
        for q in range(w[3]):
            uv = ram[w[2] + 12 * q + 4:w[2] + 12 * q + 12]
            quads.append((1, page << 16 | palette, [(uv[2 * k] >> shift, uv[2 * k + 1] + v0) for k in range(4)]))
        out.append((w, quads))
    return out


def prims(ram, slot):
    """The weapons' quads as texpack sees a model's polygons: (family, material
    (page << 16 | palette), UVs), or [] for anyone but Mokujin and Tetsujin."""
    return [p for _, quads in _quads(ram, slot) for p in quads]


def write(path, ram, slot, ps1_uv):
    """Writes the .stick of this costume (texpack.plan() must have had prims());
    ps1_uv(page, palette, u, v) -> (material, UV) is the converter's. Returns
    the number of weapons written (0: the file is removed)."""
    weapons = _quads(ram, slot)
    if not weapons:
        path.unlink(missing_ok=True)
        return 0
    data = bytearray()
    for (points_at, points, quads_at, count, bone, key), quads in weapons:
        uvs, materials = [], set()
        for _, mat, uv in quads:
            got = [ps1_uv(mat >> 16, mat & 0xffff, u, v) for u, v in uv]
            materials.update(m for m, _ in got)
            uvs.append([e for _, e in got])
        if len(materials) != 1: raise ValueError(f'arme : {len(materials)} materiaux apres rangement')
        data += b'STK1' + struct.pack('<6H', points, count, materials.pop(), bone, key, 0)
        for i in range(points): data += ram[points_at + 8 * i:points_at + 8 * i + 6]
        for q in range(count):
            corners = struct.unpack_from('<I', ram, quads_at + 12 * q)[0]
            data += bytes([corners >> 24, corners >> 16 & 255, corners >> 8 & 255, corners & 255])
            data += struct.pack('<4H', *uvs[q])
    path.write_bytes(bytes(data))
    return len(weapons)
