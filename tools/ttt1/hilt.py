#!/usr/bin/env python3
"""Hilt of Unknown's glowing blade (B107, GH#150).

When Unknown fights with Yoshimitsu's moves (moveset 4) or Kunimitsu's (26),
TTT1 draws the hilt of her energy blade by code, not from her model:
0x801042B0 (called by 0x80103940 / 0x80103E18, the routines that draw
Tetsujin's sword and dagger, from 0x8010B2C8) transforms 16 points in the
frame of her hand node and draws 14 opaque textured quads (0x2C), back faces
culled, each at the order table entry of (z0 + z3) / 2:

  points   Yoshimitsu 0x80193AC4, hand node +0xD98 (TTT1 row 20, T3 bone 10)
           Kunimitsu  0x80193B44, hand node +0xC58 (TTT1 row 16, T3 bone 6)
  quads    0x80193D94, 12 bytes: u32 corners (i0 << 24 | i1 << 16 | i2 << 8 | i3),
           then u0 v0 .. u3 v3; costume 1 (model slot 0x70) takes the UVs of the
           same table at 0x80193CEC (identical in the ROM)
  texture  8 bits, x + 0x98 in the character's atlas; costume 1 v + 0, palette
           row + 2; costume 2 v + 0x60, palette row + 1 (0x8010408C)

No polygon of the model reads that image: the texture packer used to move it
(costume 1) or drop it (costume 2, step 5). prims() hands the quads to
texpack.plan() so the image is kept like any read one; write() then takes their
UVs through the packing, as the converter does the model's, into a .hilt
file next to the model:

    'HLT1', u16 styles (2), u16 quads (14), u16 material (PS1: palette | 0x8000 for 8 bits),
    u16 0, then per style: u16 moveset, u16 T3 bone, 16 x (s16 x, y, z);
    then per quad: 4 x u8 corner, 4 x u16 UV (u | v << 8, folded into the costume band)

Read at load by read_hilt() (src/tekken3_ttt1_mod.c), drawn with the blade
(src/tekken3_ttt1_renderer.c). No file: no hilt (any other guest).
"""
import struct

UNKNOWN_SLOTS = (0x70, 0x71)             # Unknown's two costumes (TTT1 body 0x21)
QUADS, UVS_COSTUME1 = 0x193D94, 0x193CEC
STYLES = ((4, 0x193AC4, 10), (26, 0x193B44, 6))   # moveset, points, T3 bone of the hand node
POINTS, COUNT = 16, 14
PAGE = 0x80 | (0x98 >> 6)                # 8 bits, the atlas page holding x + 0x98


def prims(ram, slot):
    """The hilt's quads as texpack sees a model's polygons: (family, material
    (page << 16 | palette), UVs), or [] for anyone but Unknown."""
    if slot not in UNKNOWN_SLOTS: return []
    v0, row = (0, 2) if slot == 0x70 else (0x60, 1)
    table = UVS_COSTUME1 if slot == 0x70 else QUADS
    out = []
    for q in range(COUNT):
        uv = ram[table + 12 * q + 4:table + 12 * q + 12]
        out.append((1, PAGE << 16 | row << 6, [(uv[2 * k], uv[2 * k + 1] + v0) for k in range(4)]))
    return out


def write(path, ram, slot, ps1_uv):
    """Writes the .hilt of this costume (texpack.plan() must have had prims());
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
    if len(materials) != 1: raise ValueError(f'poignee : {len(materials)} materiaux apres rangement')
    data = bytearray(b'HLT1' + struct.pack('<4H', len(STYLES), COUNT, materials.pop(), 0))
    for moveset, points, bone in STYLES:
        data += struct.pack('<2H', moveset, bone)
        for i in range(POINTS): data += ram[points + 8 * i:points + 8 * i + 6]
    for q in range(COUNT):
        corners = struct.unpack_from('<I', ram, QUADS + 12 * q)[0]
        data += bytes([corners >> 24, corners >> 16 & 255, corners >> 8 & 255, corners & 255])
        data += struct.pack('<4H', *uvs[q])
    path.write_bytes(bytes(data))
    return True
