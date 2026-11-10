#!/usr/bin/env python3
"""Animations de Tekken : Dark Resurrection PSP (ULUS10139), lues depuis l'ISO (tools/psp/dr_iso.py).

Format relevé le 2026-10-13 dans le code du jeu (désassemblé par PPSSPP : la RAM relevée garde les
marqueurs du JIT et le décodeur utilise la VFPU) ; TIPS.md section 49 quater.

Paquet (sous-fichier 0 du conteneur +9 d'un personnage, ou fichier 4996 pour les animations communes) :
u16 0x64, u16 nombre d'animations, u16 nombre d'os (23), 23 u16 types d'os (TKMovesets : 4..7 =
rotation en s16, sinon 3 flottants), alignement 4, u32 offset de chaque animation (bit 0 ignoré).
Une animation (le format 0x64 de T5 / DR PS3 sans son en-tête commun) :
  +0 u16 nombre d'images, +2 u8 échelle des rotations (1 << b), +3 u8 échelle des positions,
  +4 u16 3 (os en position), +6 3 flottants (pas des positions : os 0, 1, 6), +0x12 pose de base
  (os 0, 1, 6 : 3 flottants ; les autres : 3 s16, angle x pi / 32768), +0xAE u32 offset de chaque
  bloc de 16 images (depuis +0xAE), puis les blocs.
Bloc : pour chaque os, 3 canaux ; un canal est un flux de bits (poids fort d'abord) : 6 bits = sa
longueur en octets, 4 bits = classe de la valeur initiale, puis jusqu'à 15 codes de 4 bits. Classe c
-> CLASSES[c] = (bits, décalage) : valeur = s16(bits lus) + décalage ; 0 = nul ; 14 = répéter le
code précédent (4 bits : nombre) ; 15 = fin. Les valeurs lues sont des accélérations : vitesse +=
valeur, position += vitesse (image f : bloc (f - 1) >> 4, (f - 1) & 15 pas).
Rotation (0x0896B1F4, VFPU) : angles a = base + valeur x échelle ; axe d = (cos a0 sin a1, -sin a0,
cos a0 cos a1), quaternion (d sin(a2 / 2), cos(a2 / 2)). Position : base + valeur x échelle de l'os.
"""
import math, struct

CLASSES = [(0, 0), (2, 1), (2, -4), (4, 5), (4, -20), (6, 21), (6, -84), (8, 85), (8, -340), (10, 341),
           (10, -1364), (12, 1365), (12, -5460), (16, 0), (16, 0), (99, 0)]   # RAM 0x08B3055C
REPEAT, END = 14, 15
PI = struct.unpack('<f', struct.pack('<f', math.pi))[0]                      # 0x08B30530
STEP = 2.0 ** -15                                                            # 0x08B30534
POS_BONES = (0, 1, 6)                                                        # masque ~0xFFFFFFBC du jeu
BASE, TABLE, BONES = 0x12, 0xAE, 23


def f32(x): return struct.unpack('<f', struct.pack('<f', x))[0]
def s16(v): return v - 0x10000 if v & 0x8000 else v


def pack_offsets(pack, off=0):
    """Offsets (relatifs au paquet) des animations d'un paquet 0x64."""
    n, bones = struct.unpack_from('<HH', pack, off + 2)
    tab = off + 6 + 2 * bones + (0 if bones & 1 else 2)
    return [struct.unpack_from('<I', pack, tab + 4 * i)[0] & ~1 for i in range(n)]


class Bits:
    def __init__(s, data, pos): s.d, s.bit = data, pos * 8
    def read(s, n):
        v = 0
        for _ in range(n):
            v = v << 1 | (s.d[s.bit >> 3] >> (7 - (s.bit & 7)) & 1); s.bit += 1
        return v


def channels(anim, frame, bones=BONES, table=TABLE):
    """Valeurs entières des 3 canaux de chaque os à l'image `frame` (>= 1), comme 0x0896B1F4."""
    n = struct.unpack_from('<H', anim, 0)[0]
    f = (frame if frame + 1 < n else n - 1) - 1
    block, steps = f >> 4, f & 15
    p = table + struct.unpack_from('<I', anim, table + 4 * block)[0]
    out = []
    for b in range(bones):
        vals = []
        for c in range(3):
            r = Bits(anim, p)
            length = r.read(6); cls = r.read(4)
            bits, add = CLASSES[cls]
            pos, vel, code, rep = s16(r.read(bits)) + add, 0, cls, 0
            for _ in range(steps):
                if rep: rep -= 1
                else:
                    k = r.read(4)
                    if k == REPEAT: rep = r.read(4) - 1
                    else: code = k
                if code == END: break
                bits, add = CLASSES[code]
                d = s16(r.read(bits)) + add if code else 0
                vel += d; pos += vel
            vals.append(pos); p += length
        out.append(vals)
    return out


def scales(anim):
    rot = f32(f32(float(1 << anim[2])) * PI) * STEP
    k = float(1 << anim[3])
    pos = {b: f32(struct.unpack_from('<f', anim, 6 + 4 * i)[0] * k) for i, b in enumerate(POS_BONES)}
    return f32(rot), pos


def base_pose(anim, bones=BONES):
    out, p = [], BASE
    for b in range(bones):
        if b in POS_BONES: out.append(struct.unpack_from('<3f', anim, p)); p += 12
        else: out.append(tuple(v / 32768 * PI for v in struct.unpack_from('<3h', anim, p))); p += 6
    return out


def pose(anim, frame, quat=True, bones=BONES):
    """Pose de l'image `frame` : par os, (x, y, z, w). Rotations en quaternion (quat) ou en angles.
    Image 0 : la pose de base seule (0x0896B120)."""
    rot, pos = scales(anim)
    base = base_pose(anim, bones)
    ch = channels(anim, frame, bones) if frame > 0 else [[0, 0, 0]] * bones
    out = []
    for b in range(bones):
        if b in POS_BONES:
            out.append(tuple(base[b][i] + ch[b][i] * pos[b] for i in range(3)) + (0.0,)); continue
        a = [base[b][i] + ch[b][i] * rot for i in range(3)]
        if not quat: out.append(tuple(a) + (0.0,)); continue
        d = (math.cos(a[0]) * math.sin(a[1]), -math.sin(a[0]), math.cos(a[0]) * math.cos(a[1]))
        s, c = math.sin(a[2] / 2), math.cos(a[2] / 2)
        out.append((d[0] * s, d[1] * s, d[2] * s, c))
    return out


def pack_types(pack, off=0):
    """Types des os d'un paquet 0x64 (u16 après le nombre d'os) : 4..7 rotation, sinon 3 flottants."""
    n, bones = struct.unpack_from('<HH', pack, off + 2)
    return struct.unpack_from(f'<{bones}H', pack, off + 6)


def pose_types(anim, frame, types):
    """Pose d'une animation d'un paquet 0x64 aux types d'os quelconques (paquet des os souples, sous-fichier
    4 du conteneur +9 : paires échelle (type 3) / rotation (type 7) par noeud MOP ; B3). En-tête : +4 u16
    nombre d'os à flottants, +6 leurs pas, puis la pose de base (3 flottants ou 3 s16 par os), puis la
    table des blocs. Par os : 3 flottants (échelle, position), ou quaternion (x, y, z, w) de la rotation.
    Image 0 ou animation d'une image : la pose de base."""
    nf, rs, ps, npos = struct.unpack_from('<HBBH', anim, 0)
    steps = struct.unpack_from(f'<{npos}f', anim, 6)
    p, base, step, k = 6 + 4 * npos, [], [], 0
    for t in types:
        if 4 <= t <= 7: base.append(tuple(v / 32768 * PI for v in struct.unpack_from('<3h', anim, p))); p += 6; step.append(None)
        else: base.append(struct.unpack_from('<3f', anim, p)); p += 12; step.append(f32(steps[k] * float(1 << ps))); k += 1
    rot = f32(f32(float(1 << rs)) * PI) * STEP
    ch = channels(anim, frame, len(types), p) if frame > 0 and nf > 1 else [[0, 0, 0]] * len(types)
    out = []
    for b, t in enumerate(types):
        if step[b] is not None: out.append(tuple(base[b][i] + ch[b][i] * step[b] for i in range(3))); continue
        a = [base[b][i] + ch[b][i] * rot for i in range(3)]
        d = (math.cos(a[0]) * math.sin(a[1]), -math.sin(a[0]), math.cos(a[0]) * math.cos(a[1]))
        s, c = math.sin(a[2] / 2), math.cos(a[2] / 2)
        out.append((d[0] * s, d[1] * s, d[2] * s, c))
    return out
