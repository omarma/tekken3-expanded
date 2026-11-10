#!/usr/bin/env python3
"""Springs of the accessory bones (tails, hair, skirts, coat tails...) of a TTT1
model slot, as the arcade swings them (F03, TIPS.md § 78).

TTT1's accessory solver (0x80163B68) takes its parameters from a table of six
pointers per model slot at 0x8019D674 (one per bone 18..23, 0 = rigid), loaded
by 0x801648E0 into actor +0x12D4. Each block is eight halfwords (+0 switch, 32
in every guest block; +2 smoothing of the tip; +4 / +6 stiffness and damping;
+8; +10 sway; +12 collision mode, 0 for none) and four more when +12 is not 0
(+14 bone collided with, +16..+20 offset, +22 radius). Tekken 3's solver
(0x80037CBC) reads the same fields from +4 on. Mode 2 keeps the tip outside a
cylinder around bone +14 (+22 = radius); mode 1 (accessory_bound_target,
ttt-ps1 src/fin/80163554.c) bounds the bone's direction by the direction of a
point of bone +14 (+16..+20): +22 is then an entry of the sign table
0x8019E22C (6 bytes, pitch weight at +4, yaw weight at +5), and the bone does
not turn past w_yaw * yaw + w_pitch * pitch of that point (Heihachi's coat tail
against his thigh, F32).

The converter (tools/ttt1/model/convert.py) puts TTT1 accessory rows 24..29
(bones 18..23) on PS1 parts 18..21 (rows 21..24), the rest into another part
(second mesh, rigid). For each PS1 part 18..21 the .acc file gives the TTT1
bone drawn there and its block:

    'ACC1', u16 4, u16 entry size (28), then per PS1 bone 18..21:
    u16 TTT1 bone (0xFFFF: rigid), u16 bound weights, 12 x s16 block (zeros past +16 without collision)

The bound weights are 0 but in mode 1: s8 pitch weight (low byte), s8 yaw
weight (high byte) of the sign table entry +22 (0 in a file before import
version 17: no bound, as before).

Read at load by read_accessories() (src/tekken3_ttt1_mod.c). No file: every
accessory bone stays rigid.

    python tools/ttt1/accessories.py <select RAM> <slot> <TTT1 .3dm> <out .acc>
"""
import struct, sys
from pathlib import Path

TABLE = 0x19D674                         # 0x8019D674 in a RAM image from 0x80000000
SIGNS = 0x19E22C                         # 0x8019E22C: sign table, 6 bytes per entry (mode 1 bounds)
ENTRY, BONES = 28, (18, 19, 20, 21)
PS1_ROW = {b: b + 3 for b in BONES}      # PS1 part 18..21 -> row 21..24


def blocks(ram, slot):
    """TTT1 bone 18..23 -> its 12-halfword block, for this model slot."""
    out = {}
    for i in range(6):
        p = struct.unpack_from('<I', ram, TABLE + 24 * slot + 4 * i)[0]
        if not p: continue
        b = list(struct.unpack_from('<12h', ram, p & 0x3FFFFF))
        if not b[6]: b[8:] = [0, 0, 0, 0]          # no collision: a 16-byte block
        out[18 + i] = b
    return out


def keep_rows(ram, slot):
    """TTT1 rows (24..29) of the bones the arcade bounds (mode 1): the converter keeps them on a
    swinging part of their own, carrying no baked piece, when it can (convert.convert(keep=...)).
    Heihachi's coat panels (LK, RK) are bounded by one thigh each: baked onto the left one, the
    right one swung with it and went into the right thigh. Mode 2 (collision) is left out: every
    mode 2 bone already swings on its own part, and Baek's costume 2 carries a baked piece on its
    own (validated as it is)."""
    return {b + 6 for b, block in blocks(ram, slot).items() if block[6] == 1}


def bound(ram, block):
    """The mode 1 bound weights of a block as the .acc halfword (pitch low byte,
    yaw high byte), 0 for another mode."""
    if block[6] != 1: return 0
    pitch, yaw = struct.unpack_from('<bb', ram, SIGNS + 6 * block[11] + 4)
    return (pitch & 0xFF) | (yaw & 0xFF) << 8


def entries(ram, slot, s2t):
    """PS1 bone 18..21 -> (TTT1 bone, block, bound weights), with the layout of
    the conversion (convert.S2T: PS1 row -> TTT1 row)."""
    table, out = blocks(ram, slot), {}
    for b in BONES:
        t = s2t.get(PS1_ROW[b])
        if t is not None and t >= 24 and t - 6 in table: out[b] = (t - 6, table[t - 6], bound(ram, table[t - 6]))
    return out


def pack(entries_):
    data = bytearray(b'ACC1' + struct.pack('<HH', len(BONES), ENTRY))
    for b in BONES:
        bone, block, weights = entries_.get(b, (0xFFFF, [0] * 12, 0))
        data += struct.pack('<HH12h', bone, weights, *block)
    return bytes(data)


def read(path):
    """{PS1 bone: {'ttt1_bone', 'block'}} of a .acc file; {} without one."""
    path = Path(path)
    if not path.is_file(): return {}
    d = path.read_bytes()
    assert d[:4] == b'ACC1', path
    count, size = struct.unpack_from('<HH', d, 4)
    out = {}
    for i in range(count):
        bone, weights, *block = struct.unpack_from('<HH12h', d, 8 + size * i)
        if bone != 0xFFFF: out[BONES[i]] = dict(ttt1_bone=bone, block=block, bound=weights)
    return out


def write(path, ram, slot, s2t):
    """Writes the .acc of a converted model; returns the report entry."""
    e = entries(ram, slot, s2t)
    Path(path).write_bytes(pack(e))
    table = blocks(ram, slot)
    drawn = {t - 6 for t in s2t.values() if t >= 24}
    return dict(swinging={str(b): t for b, (t, _, _) in e.items()},
                bounded={str(b): t for b, (t, _, w) in e.items() if w},
                rigid=sorted(set(table) - {t for t, _, _ in e.values()}),      # baked into another part, or not drawn
                not_drawn=sorted(set(table) - drawn))


def main(argv=sys.argv[1:]):
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'model'))
    import convert
    from fmt import load
    ram, slot, model, out = Path(argv[0]).read_bytes(), int(argv[1]), load(argv[2]), argv[3]
    convert.convert(model, keep=keep_rows(ram, slot))
    print(write(out, ram, slot, {s: t for s, t in convert.S2T.items() if s > 20}))


if __name__ == '__main__':
    main()
