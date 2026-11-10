#!/usr/bin/env python3
"""Copie figee pour A3 (moveset DR de Paul) : tools/psp/dr_pose.py de la branche wip/dr/b1-model a
cc442059, celle sur laquelle les animations de Paul DR ont ete calees et validees (2026-10-26). La
version suivante de B1 change des angles (528 valeurs de plus de 2 degres sur le paquet de Paul) :
passer a dr_pose.py quand B1 sera fusionne, apres un nouveau calage et une nouvelle validation.

Pose de combat de Tekken : Dark Resurrection PSP (ULUS10139) : transcription du jeu, au bit pres.

Releve le 2026-10-24 (session B1, details et equations : workspace/dr-b1/code/POSE.md). Transcrit :
- `anim_pose` : tampon de quaternions d'une image (0x0896B1F4 en virgule flottante VFPU, z des os 0, 1
  nie par 0x0896C464, `racine_lacet` = 0x0896C560) ; les entiers des canaux viennent de dr_anim ;
- `pose_locales` = 0x089AE50C : quaternions -> matrices locales des 23 premiers os du jeu (0x90 o par
  os, matrice 4 x 4 par colonnes a +0), puis colonne vertebrale (os 1, 2 = articulations 2, 3)
  recalculee depuis des points fixes (0x08B36370..0x08B363A0) ; orteils (os 17, 21) remis au repos ;
- `hand_table`, `hand_select`, `doigts` = 0x0896ECBC, 0x0896EF88 / 0x0896EDB8 / 0x0896DAB8,
  0x0896F24C : poses des mains (paquet de mains du moveset, moveset + 0x248) -> os 51..80
  (articulations 55..84) ;
- `garde` : la chaine complete depuis l'ISO (animation, squelette, moveset), sans emulateur ;
- `apres_pose` (suite de 0x089AF40C) : regard vers l'adversaire `regard` = 0x08926EF0 (tronc
  0x0892773C, cou 0x08927D08 / 0x089269FC, tete 0x089282C4 / 0x08926AC4), mondes, sol et IK des
  jambes `monde` = 0x089B10B4 (0x089B2AF4, 0x089B0C18, 0x089B0840, 0x089B0754, 0x089B2590,
  bras 0x089B0E6C) ; `monde_final` = 0x089AE260 (apres la mise a jour de l'autre joueur).
  Chemins de code non parcourus par la garde : NotImplementedError avec l'adresse.
Appelants : 0x089AF660 -> 0x089AF994 (animation) puis 0x089AF40C.

Semantique : celle de PPSSPP 1.20.4 avec le JIT x86 (CPUCore = 1 dans le ppsspp.ini de la machine),
qui a produit les instantanes : la VFPU y est du float32 IEEE ordinaire (vdot.t / vtfm / vmmul dans
l'ordre des termes, vdot.q par paires (DPPS), vrsq = 1 / sqrtf, vrcp = 1 / x), sauf vsin / vcos / vrot
qui appellent vfpu_sin / vfpu_cos, transcrits ici avec les tables de PPSSPP (assets/vfpu/*.dat, lues
dans l'installation : variable PPSSPP_VFPU). Pas de numpy : flottants Python arrondis a float32 apres
chaque operation (pour +, -, x, /, racine, le double arrondi double -> float32 est exact).

Usage : dr_pose.py [--snaps dossier] [--iso image]   verification au bit contre les instantanes de
        workspace/dr-b1/code/snaps (0x089AE50C, doigts), puis la chaine complete depuis l'ISO.
"""
import argparse, json, math, os, struct, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPS = ROOT / 'workspace/dr-b1/code/snaps'
VFPU_DAT = Path(os.environ.get('PPSSPP_VFPU', r'C:\Program Files\PPSSPP\assets\vfpu'))
RAM0 = 0x08800000

# ---------------------------------------------------------------- float32
_pk, _up = struct.Struct('<f').pack, struct.Struct('<f').unpack


def f32(x):
    """Arrondi a float32 (debordement -> infini comme le materiel)."""
    try: return _up(_pk(x))[0]
    except OverflowError: return math.copysign(math.inf, x)


def bits(x): return struct.unpack('<I', _pk(x))[0]
def fbits(u): return struct.unpack('<f', struct.pack('<I', u & 0xFFFFFFFF))[0]
def add(a, b): return f32(a + b)
def sub(a, b): return f32(a - b)
def mul(a, b): return f32(a * b)


def div(a, b):
    if b == 0:
        if a == 0 or a != a: return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return f32(a / b)


def sqrtf(a):
    if a < 0: return math.nan
    return f32(math.sqrt(a))


ONE = 1.0
MAXFLOAT = fbits(0x7F7FFFFF)      # vcst MaxFloat
TWO_PI_INV = f32(2 / math.pi)     # vcst 2/PI (PPSSPP : (float)M_2_PI)
PI_2 = f32(math.pi / 2)           # vcst PI/2
SIN_SCALE = f32(3.7252903e-09)    # 0x1p-28f


# ---------------------------------------------------------------- vfpu_sin / vfpu_cos (PPSSPP 1.20.4)
class _SinLut:
    """MIPSVFPUUtils.cpp : vfpu_sin_fixed et ses quatre tables (assets/vfpu)."""
    def __init__(s, d=VFPU_DAT):
        rd = lambda n: (Path(d) / f'{n}.dat').read_bytes()
        b = rd('vfpu_sin_lut8192'); s.l8192 = struct.unpack(f'<{len(b) // 4}I', b)
        b = rd('vfpu_sin_lut_delta'); s.delta = struct.unpack(f'<{len(b)}b', b)
        b = rd('vfpu_sin_lut_interval_delta'); s.idelta = struct.unpack(f'<{len(b) // 2}h', b)
        s.exc = rd('vfpu_sin_lut_exceptions')


_LUT = None


def _lut():
    global _LUT
    if _LUT is None: _LUT = _SinLut()
    return _LUT


def _clz32(x): return 32 - x.bit_length()
def _quantum(x): return 1 if x < (1 << 22) else 1 << (32 - 22 - _clz32(x))
def _trunc(x): return x & (-_quantum(x) & 0xFFFFFFFF)


def _sin_fixed(arg):
    if arg == 0: return 0
    if arg == 0x00800000: return 0x10000000
    T = _lut(); M = 0xFFFFFFFF
    L = T.l8192[(arg >> 13)]; H = T.l8192[(arg >> 13) + 1]
    A = (L + (((((H - L) & M) * (((arg >> 6) & 127) + 0)) & M) >> 7)) & M
    B = (L + (((((H - L) & M) * (((arg >> 6) & 127) + 1)) & M) >> 7)) & M
    a = (A << 5) + (T.delta[2 * (arg >> 6)] * _quantum(A))
    b = (B << 5) + (T.delta[2 * (arg >> 6) + 1] * _quantum(B))
    a &= (1 << 64) - 1; b &= (1 << 64) - 1
    v = ((((a * (64 - (arg & 63)) + b * (arg & 63)) & ((1 << 64) - 1)) >> 6) >> 5) & M
    v = _trunc(v)
    lo = ((169 * ((arg >> 7) + 0)) >> 7) + T.idelta[(arg >> 7) + 0] + 16384
    hi = ((169 * ((arg >> 7) + 1)) >> 7) + T.idelta[(arg >> 7) + 1] + 16384
    while lo < hi:
        m = (lo + hi) // 2
        bb = T.exc[m]
        e = (arg & 0xFFFFFF80) + (bb & 127)
        if e == arg:
            v = (v + _quantum(v) * (-1 if bb >> 7 else 1)) & M
            break
        elif e < arg: lo = m + 1
        else: hi = m
    return v


def _reduce(x):
    u = bits(x); exponent = (u >> 23) & 0xFF; sig = (u & 0x007FFFFF) | 0x00800000
    if exponent < 0x7F:
        sig = 0 if exponent < 0x7F - 23 else sig >> (0x7F - exponent)
    elif exponent > 0x7F:
        if 25 <= exponent - 0x7F < 32: sig = 0
        elif (exponent & 0x9F) == 0x9F: sig = 0
        else: sig = (sig << ((exponent - 0x7F) & 31)) & 0xFFFFFFFF
    return u, exponent, sig


def vfpu_sin(x):
    """sin(x * pi / 2) comme le materiel (PPSSPP vfpu_sin, tables)."""
    u, e, sig = _reduce(x)
    if e == 0xFF: return math.nan
    sign = (u & 0x80000000) ^ ((sig << 7) & 0x80000000)
    sig &= 0x00FFFFFF
    if sig > 0x00800000: sig = 0x01000000 - sig
    r = _sin_fixed(sig)
    return f32((-1.0 if sign else 1.0) * f32(float(r)) * SIN_SCALE) if r else (-0.0 if sign else 0.0)


def vfpu_cos(x):
    u, e, sig = _reduce(fbits(bits(x) & 0x7FFFFFFF))
    if e == 0xFF: return math.nan
    sign = (sig << 7) & 0x80000000
    sig &= 0x00FFFFFF
    if sig >= 0x00800000:
        sig = 0x01000000 - sig; sign ^= 0x80000000
    r = _sin_fixed(0x00800000 - sig)
    return f32((-1.0 if sign else 1.0) * f32(float(r)) * SIN_SCALE) if r else (-0.0 if sign else 0.0)


_ASIN = None


def _asin_lut():
    global _ASIN
    if _ASIN is None:
        rd = lambda n: (VFPU_DAT / f'{n}.dat').read_bytes()
        b = rd('vfpu_asin_lut65536'); c = struct.unpack(f'<{len(b) // 4}i', b)
        lut = [c[3 * i:3 * i + 3] for i in range(len(c) // 3)]
        b = rd('vfpu_asin_lut_indices'); idx = struct.unpack(f'<{len(b) // 2}H', b)
        b = rd('vfpu_asin_lut_deltas'); dl = struct.unpack(f'<{len(b) // 8}Q', b)
        _ASIN = (lut, idx, dl)
    return _ASIN


def _aq(x): return 1 if x < (1 << 23) else 1 << (32 - 23 - _clz32(x))


def vfpu_asin(x):
    """asin(x) / (pi / 2) comme le materiel (PPSSPP vfpu_asin, tables)."""
    u = bits(x); sign = u & 0x80000000; u &= 0x7FFFFFFF
    if u > 0x3F800000: return fbits(0x7F800001 ^ sign)
    v = int(f32(abs(x) * 8388608.0))
    if v == 0: r = 0
    elif v == 1 << 23: r = 1 << 30
    else:
        lut, idx, dl = _asin_lut()
        C = lut[v >> 16]; w = v & 0xFFFF
        t = (((((C[2] * w) >> 16) + C[1]) * w) >> 16) + C[0]
        t &= 0xFFFFFFFF
        ret = t & (-_aq(t) & 0xFFFFFFFF)
        d = dl[idx[v // 21]]
        r = (ret + (3 - ((d >> (3 * (v % 21))) & 7)) * _aq(ret)) & 0xFFFFFFFF
    y = f32(float(r if r < 0x80000000 else r - (1 << 32)) * 9.31322574615478515625e-10)
    return -y if sign else y


# ---------------------------------------------------------------- vecteurs et matrices (VFPU, JIT x86)
# Vecteur : liste de 4 flottants. Matrice : liste de 4 colonnes (comme en memoire, lv.q Cx00..Cx30).
def dot3(a, b):
    """vdot.t : ((a0 b0 + a1 b1) + a2 b2) (JIT : DPPS 0x71 ou MULSS/ADDSS, meme ordre)."""
    return add(add(mul(a[0], b[0]), mul(a[1], b[1])), mul(a[2], b[2]))


def cross(s, t, w=0.0):
    """vcrsp.t : (s1 t2 - s2 t1, s2 t0 - s0 t2, s0 t1 - s1 t0) ; w : voie 4 inchangee."""
    return [sub(mul(s[1], t[2]), mul(s[2], t[1])), sub(mul(s[2], t[0]), mul(s[0], t[2])),
            sub(mul(s[0], t[1]), mul(s[1], t[0])), w]


def scl(v, k, n=4): return [mul(v[i], k) if i < n else v[i] for i in range(4)]
def vadd(a, b, n=4): return [add(a[i], b[i]) if i < n else a[i] for i in range(4)]
def vsub(a, b, n=4): return [sub(a[i], b[i]) if i < n else a[i] for i in range(4)]


def tfm(M, v, n=4):
    """vtfm4.q / vtfm3.t Cd, E(M), v : somme des colonnes de M ponderees, dans l'ordre des colonnes."""
    out = [mul(M[0][r], v[0]) for r in range(n)]
    for j in range(1, n):
        out = [add(out[r], mul(M[j][r], v[j])) for r in range(n)]
    return out


def mmul(A, B):
    """vmmul.q Md, A, B tel qu'ecrit par le jeu (A charge en E) : D = A . B, colonne par colonne."""
    return [tfm(A, B[i]) for i in range(4)]


def rsq(x):
    """vrsq.s (JIT) : 1 / sqrtf(x)."""
    return div(ONE, sqrtf(x))


def normalize(v):
    """0x0882E42C (et sa copie en ligne 0x089AE94C) : xyz / |xyz|, w = 0 ; vrsq NaN ou infini ->
    MaxFloat (vcmp ES + vcmovt)."""
    r = rsq(dot3(v, v))
    if r != r or math.isinf(r): r = MAXFLOAT
    return [mul(v[0], r), mul(v[1], r), mul(v[2], r), 0.0]


def quat_matrix(q, M=None):
    """0x0896D0A0 : quaternion (x, y, z, w) -> colonnes 0..2 (w = 0) et +0x3C = 1 ; translation
    gardee. C'est la transposee de la matrice usuelle (rotation du conjugue)."""
    x, y, z, w = q
    x2, y2, z2 = add(x, x), add(y, y), add(z, z)
    s00, s01, s02, s03 = mul(x, x2), mul(y, x2), mul(z, x2), mul(w, x2)
    s10, s11, s12, s13 = mul(x, y2), mul(y, y2), mul(z, y2), mul(w, y2)
    s20, s21, s22, s23 = mul(x, z2), mul(y, z2), mul(z, z2), mul(w, z2)
    c0 = [sub(ONE, add(s11, s22)), sub(s01, s23), add(s02, s13), 0.0]
    c1 = [add(s01, s23), sub(ONE, add(s22, s00)), sub(s12, s03), 0.0]
    c2 = [sub(s02, s13), add(s12, s03), sub(ONE, add(s00, s11)), 0.0]
    t = list(M[3]) if M else [0.0, 0.0, 0.0, 1.0]
    t[3] = ONE
    return [c0, c1, c2, t]


def euler_matrix(e, M=None, axes=3):
    """0x0896C984 : Rz . Ry . Rx (angles en radians, sinus / cosinus de la VFPU), colonnes 0..2,
    translation gardee. axes = 2 : Ry . Rx seulement (0x0896DAB8)."""
    def sc(a):
        a = mul(a, TWO_PI_INV); return vfpu_sin(a), vfpu_cos(a)
    s, c = sc(e[0])
    R = [[1.0, 0.0, 0.0, 0.0], [0.0, c, s, 0.0], [0.0, -s, c, 0.0]]
    for k in range(1, axes):
        s, c = sc(e[k])
        if k == 1: Q = [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]]
        else: Q = [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]
        R = [tfm(Q, R[j], 3) + [R[j][3]] for j in range(3)]
    t = list(M[3]) if M else [0.0, 0.0, 0.0, 1.0]
    return [R[0], R[1], R[2], t]


def inverse(M):
    """0x0882E5F8 -> 0x08A0B978 : inverse d'une matrice affine (rotation 3 x 3 par les cofacteurs,
    divisee par le determinant ; translation = -R^-1 t). Voies w des colonnes gardees."""
    c0, c1, c2, c3 = M
    k2 = cross(c0, c1); det = dot3(k2, c2)
    k0 = cross(c1, c2); k1 = cross(c2, c0)
    if det == 0: det = ONE
    inv = div(ONE, det)
    n3 = [-c3[0], -c3[1], -c3[2]]
    R = [[mul(k0[j], inv), mul(k1[j], inv), mul(k2[j], inv)] for j in range(3)]
    t = tfm(R, n3, 3)
    return [R[0] + [c0[3]], R[1] + [c1[3]], R[2] + [c2[3]], t + [c3[3]]]


# ---------------------------------------------------------------- 0x089AE50C
ORDER = (0, 0, 0, 0, 1, 13, 0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 18, 19, 20)   # 0x08B36438
P_GENOU_G = (-130.0, 400.0, 0.0, 1.0)     # 0x08B36370 (dans le repere de l'os 13)
P_GENOU_D = (130.0, -400.0, 0.0, 1.0)     # 0x08B36380 (dans le repere de l'os 1 d'origine)
P_AVANT = (400.0, 0.0, 0.0, 1.0)          # 0x08B36390 (repere de l'os 1 d'origine)
P_COLONNE = (130.0, 0.0, 0.0, 1.0)        # 0x08B363A0 (repere de l'os 1 recalcule)
W_UN = 1.0                                # 0x08B362B4


def _gram(a, b):
    """(normalise(b - a (b . a)))."""
    d = dot3(b, a)
    return normalize(vsub(b, scl(a, d)))


def pose_locales(quats, os_, euler):
    """0x089AE50C(joueur, quaternions, os). quats : 23 vecteurs (dr_anim.pose, os 0, 1, 6 = positions,
    z des os 0, 1 nie par le jeu) ; os_ : 23 matrices (colonnes), modifiees en place et rendues ;
    euler : 23 triplets d'angles, table *(*(joueur + 0x8A4) + 0x18) (repos des os 2, 17, 21 ici)."""
    for k in range(22, 2, -1):
        o = ORDER[k]; os_[o] = quat_matrix(quats[k], os_[o])
    v20 = [quats[6][0], 0.0, 0.0, W_UN]           # (os 6 : position, -400 pour la garde de Jin)
    v10, v30, v40, v50 = list(P_GENOU_G), list(P_GENOU_D), list(P_AVANT), list(P_COLONNE)
    m1 = [list(c) for c in os_[1]]
    os_[2] = euler_matrix(euler[2], os_[2])
    v10 = tfm(os_[13], v10); v20 = tfm(os_[13], v20)
    v30 = tfm(m1, v30); v40 = tfm(m1, v40)
    # os 1 : x vers le milieu des deux points, y vers l'avant, z = x ^ y ; puis x vers v20 + v40
    a = normalize(vadd(v30, v10, 3))
    b = _gram(a, v40)
    c = cross(a, b, a[3])
    a = normalize(vadd(v20, v40, 3))
    c = _gram(a, c)
    b = cross(c, a, c[3])
    os_[1] = [a, b, c, os_[1][3]]
    # os 2 : a partir du point P_COLONNE de l'os 1 recalcule
    v50 = tfm(os_[1], v50)
    a = normalize(vsub(v30, v50))
    b = _gram(a, vsub(v40, v50))
    c = cross(a, b, a[3])
    a = normalize(vsub(v40, v50))
    c = _gram(a, c)
    b = cross(c, a, c[3])
    t2 = list(os_[2][3])
    x = normalize(a)
    y = normalize(vsub(b, scl(x, dot3(b, x))))
    z = cross(x, y, x[3])
    os_[2] = [x, y, z, t2]
    m = mmul(inverse(os_[1]), os_[2])
    m[3] = t2
    os_[2] = m
    os_[17] = euler_matrix(euler[17], os_[17])
    os_[21] = euler_matrix(euler[21], os_[21])
    return os_


# ---------------------------------------------------------------- animation : quaternions exacts
PI_F = f32(math.pi)                       # vcst PI
DOT4_PAIRS = True                         # vdot.q du JIT : (p0 + p1) + (p2 + p3) (DPPS 0xF1) ; sinon a la suite


def dot4(a, b):
    p = [mul(a[i], b[i]) for i in range(4)]
    if DOT4_PAIRS: return add(add(p[0], p[1]), add(p[2], p[3]))
    return add(add(add(p[0], p[1]), p[2]), p[3])


def anim_quat(base, ch, rot_scale):
    """0x0896B1F4 (os en rotation) : angles a_k = base_k 2^-15 PI + ch_k echelle, puis
    axe d = (cos a0 sin a1, -sin a0, cos a0 cos a1) (vrot sur a0, a1 x 2/PI), q = (d sin(a2/2), cos(a2/2))
    (vrot sur a2 x 1/PI). base : 3 s16 de la pose de base, ch : 3 entiers des canaux (dr_anim.channels),
    rot_scale : echelle des rotations de l'animation (dr_anim.scales, deja float32)."""
    a = [add(mul(f32(base[k] * 2.0 ** -15), PI_F), mul(float(ch[k]), rot_scale)) for k in range(3)]
    a0, a1, a2 = mul(a[0], TWO_PI_INV), mul(a[1], TWO_PI_INV), mul(a[2], INV_PI)
    c0, s0 = vfpu_cos(a0), vfpu_sin(a0)
    s1, c1 = vfpu_sin(a1), vfpu_cos(a1)
    s2, c2 = vfpu_sin(a2), vfpu_cos(a2)
    d = [mul(c0, s1), mul(-s0, ONE), mul(c0, c1)]
    return [mul(d[0], s2), mul(d[1], s2), mul(d[2], s2), mul(ONE, c2)]


def matrix_quat(M):
    """0x0896D298 : matrice (colonnes) -> quaternion de la convention de 0x0896D0A0 (le conjugue de
    l'usuel) : |x|, |y|, |z|, |w| par les racines des quatre combinaisons de la diagonale, signes
    pris sur la plus grande des trois premieres."""
    d0, d1, d2 = M[0][0], M[1][1], M[2][2]
    q4 = 0.25
    sx = dot4([d0, -d1, -d2, ONE], [q4] * 4)
    sy = dot4([-d0, d1, -d2, ONE], [q4] * 4)
    sz = dot4([-d0, -d1, d2, ONE], [q4] * 4)
    sw = dot4([-sx, -sy, -sz, ONE], [ONE] * 4)
    r = [abs(sqrtf(max(v, 0.0))) if v == v else v for v in (sx, sy, sz, sw)]
    x, y, z, w = r
    f15 = sub(M[1][0], M[0][1]); f12 = sub(M[0][2], M[2][0]); f13 = sub(M[2][1], M[1][2])
    f4 = add(M[0][1], M[1][0]); f3 = add(M[1][2], M[2][1]); f1 = add(M[2][0], M[0][2])
    if sy < sx and sz < sx:                     # x le plus grand
        if f4 < 0: y = -y
        if f1 < 0: z = -z
        if f13 < 0: w = -w
    elif sy < sx or not sz < sy:               # z le plus grand
        if f1 < 0: x = -x
        if f3 < 0: y = -y
        if f15 < 0: w = -w
    else:                                       # y le plus grand
        if f3 < 0: z = -z
        if f4 < 0: x = -x
        if f12 < 0: w = -w
    return [x, y, z, w]


IDENT = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
LACET_SEUIL = fbits(0x3F3504F2)           # 0x08B30558
LACET_AXE = (0.0, -1.0, 0.0, 0.0)         # 0x08B30554 : (0, -1, 0)


def atan2f(y, x):
    """0x08A0B834 (atan2f du jeu, VFPU) : a = asin(y / |(y, x)|) (vrsq, vsat1, vasin x pi/2 ; norme
    nulle ou infinie -> asin(1)), puis si x est negatif (bit de signe) : (y negatif ? -pi : pi) - a."""
    d = add(mul(y, y), mul(x, x))
    r = div(ONE, sqrtf(d))
    sv = mul(y, r)
    sv = -1.0 if sv < -1.0 else (1.0 if sv > 1.0 else sv)
    if r != r or math.isinf(r): sv = ONE
    a = mul(vfpu_asin(sv), PI_2)
    if bits(x) >> 31:
        a = sub(fbits(0xC0490FDB) if bits(y) >> 31 else fbits(0x40490FDB), a)
    return a


def racine_lacet(quats):
    """0x0896C560 (si le coup n'a pas le bit 31 de son mot +0x3C) : remplace l'os 3 (racine) par le
    seul lacet de l'os 2 (0x0896AFF8 : atan2f(-m20, m00) de sa matrice, rotation autour de -y,
    0x0896D078) et reporte la difference dans les os 4 et 5 : M_k <- (R3')^-1 . R3 . M_k (k = 4, 5),
    reconvertis en quaternions (0x0896D298). Rien si |m11| de l'os 3 < 0,7071. Modifie quats."""
    R3 = quat_matrix(quats[3], IDENT)
    if abs(R3[1][1]) < LACET_SEUIL: return quats
    M4 = mmul(R3, quat_matrix(quats[4], IDENT)); M5 = mmul(R3, quat_matrix(quats[5], IDENT))
    Ry = quat_matrix(quats[2])
    yaw = atan2f(-Ry[0][2], Ry[0][0])
    k = mul(yaw, INV_PI); s, c = vfpu_sin(k), vfpu_cos(k)
    quats[3] = [mul(LACET_AXE[0], s), mul(LACET_AXE[1], s), mul(LACET_AXE[2], s), mul(ONE, c)]
    inv = inverse(quat_matrix(quats[3], R3))
    for b, M in ((4, M4), (5, M5)):
        t = M[3]; M = mmul(inv, M); M[3] = t
        quats[b] = matrix_quat(M)
    return quats


def anim_pose(anim, frame, lacet=True, echelle=(1.0, 1.0, 0.0)):
    """Tampon de quaternions que lit 0x089AE50C (joueur : 0x09B78630), image entiere `frame` :
    0x0896B1F4 (rotations : anim_quat ; positions des os 0, 1, 6 : base + canal x echelle, w = 0),
    z des os 0 et 1 nie (0x0896C464), puis racine_lacet (0x0896C560, sauf drapeau du coup).
    Les canaux et la pose de base viennent de dr_anim (decodage entier, deja exact).
    echelle = (joueur + 0x6D4, + 0x6D8, + 0x11C) : 0x089AE4DC multiplie les positions des os 0 et 1
    par (a + c, b, c + a) (Jin : 1, 1, 0 -> sans effet ; Paul : 1,04, 1,04, 0)."""
    import dr_anim as A
    rot, pos = A.scales(anim)
    ch = A.channels(anim, frame) if frame > 0 else [[0, 0, 0]] * A.BONES
    out, p = [], A.BASE
    for b in range(A.BONES):
        if b in A.POS_BONES:
            bs = struct.unpack_from('<3f', anim, p); p += 12
            out.append([add(bs[k], mul(float(ch[b][k]), pos[b])) for k in range(3)] + [0.0])
        else:
            bs = struct.unpack_from('<3h', anim, p); p += 6
            out.append(anim_quat(bs, ch[b], rot))
    for b in (0, 1): out[b][2] = -out[b][2]
    if lacet: racine_lacet(out)
    a, b_, c = echelle
    k = [add(a, c), add(b_, 0.0), add(c, a)]
    for b in (0, 1): out[b] = [mul(out[b][i], k[i]) for i in range(3)] + [out[b][3]]
    return out


# ---------------------------------------------------------------- mains : 0x0896DAB8 / 0x0896D7AC
H_OFF = (0, -84, -20, -4, 1, 5, 21, 4)    # 0x08B30600 (s8) : decalage de chaque code
H_BITS = (0, 6, 4, 2, 2, 4, 6, 12)        # 0x08B30608 (s8) : bits de chaque code (7 = valeur absolue)
H_W = 1.0                                 # 0x08B30610
H_EPS = fbits(0x3727C5AC)                 # 0x08B30614, 0x08B305E4, 0x08B3072C, 0x08B30738 : 1e-5
H_ANGLE = fbits(0x38C90FDB)               # 0x08B30618 : pi / 32768
INV_PI = f32(1 / math.pi)                 # vcst 1/PI


def _s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def hand_channels(anim, types, frame, nb):
    """0x0896D7AC(sortie, anim, types, image, os) : 3 x nb valeurs entieres (s16) d'une image.
    anim : octets de l'animation (u16 nombre d'images, puis deux poses de base de 3 nb s16, puis la
    table des blocs de 16 images en demi-mots, puis les canaux) ; types : type de chaque os (5..8 =
    rotation, decalage 4 ; sinon decalage 2)."""
    U = lambda o: struct.unpack_from('<H', anim, o)[0]
    n = U(0)
    base = 2
    if not frame + 1 < n:
        frame = 0; base = (6 * nb + 2) & ~1
    out = [U(base + 2 * i) for i in range(3 * nb)]
    if frame <= 0: return [_s16(v) for v in out]
    f = frame - 1
    hw = (f >> 4) + ((12 * nb + 2) >> 1)
    t1 = 2 * U(2 * hw)
    shift = 0
    for ch in range(3 * nb):
        if ch % 3 == 0: shift = 4 if 5 <= types[ch // 3] <= 8 else 2
        a1 = U(t1); nxt = t1 + 2 * (a1 & 0x1FF); a1 >>= 9; t1 += 2
        t2, t8, t3, t5 = 7, 0, 0, 0
        for _ in range((f & 15) + 1):
            if t2 < 16:
                a1 = _s32(a1 + (U(t1) << t2)); t1 += 2; t2 += 16
            if t5: t5 -= 1
            else:
                t3 = a1 & 15; a1 >>= 4; t2 -= 4
                if t3 >= 8:
                    t5 = (a1 & 15) + 1; a1 >>= 4; t2 -= 4; t3 -= 8
            if t3 == 0: continue
            if t3 == 7:
                if t2 < 12:
                    a1 = _s32(a1 + (U(t1) << t2)); t1 += 2; t2 += 16
                out[ch] = 0
                t8 = _s32(a1 << 20) >> 20
            else:
                t8 = _s16(t8 + H_OFF[t3] + (a1 & ((1 << H_BITS[t3]) - 1)))
            t2 -= H_BITS[t3]; a1 >>= H_BITS[t3]
        out[ch] = (out[ch] + (t8 << shift)) & 0xFFFF
        t1 = nxt
    return [_s16(v) for v in out]


def hand_quat(a):
    """Angles entiers (x, y, z) -> quaternion, comme 0x0896DAB8 : axe = Ry . Rx . ez, angle z."""
    ang = [mul(float(v), H_ANGLE) for v in a]
    R = euler_matrix((ang[0], ang[1]), axes=2)
    d = R[2]
    sz = mul(ang[2], INV_PI)
    s, c = vfpu_sin(sz), vfpu_cos(sz)
    return [mul(d[0], s), mul(d[1], s), mul(d[2], s), mul(ONE, c)]


def hand_pose_frame(pack, index, frame):
    """Pose entiere (image) d'une animation de main : 15 quaternions (ou positions)."""
    U = lambda o: struct.unpack_from('<H', pack, o)[0]
    nanim, nb = U(2), U(4)
    if index >= nanim or index < 0: index = 0
    off = struct.unpack_from('<I', pack, 8 + 4 * index)[0] & ~1
    types = [U(8 + 4 * nanim + 2 * i) for i in range(nb)]
    vals = hand_channels(pack[off:], types, frame, nb)
    out = []
    for b in range(nb):
        v = vals[3 * b:3 * b + 3]
        if 5 <= types[b] <= 8: out.append(hand_quat(v))
        else: out.append([f32(float(v[0])), f32(float(v[1])), f32(float(v[2])), H_W])
    return out


def nlerp(q0, q1, t):
    """0x0896D0FC : q0 (+-) (1 - t) + q1 t, signe choisi par q0 . q1 >= 0, puis x rendu positif ;
    pas de renormalisation. t <= 1e-5 : q0."""
    if not t > H_EPS: return list(q0)
    d = add(add(mul(q0[0], q1[0]), mul(q0[1], q1[1])), add(mul(q0[2], q1[2]), mul(q0[3], q1[3])))
    sg = 1.0 if d >= 0 else -1.0
    k = mul(sg, sub(ONE, t))
    r = [add(mul(q0[i], k), mul(q1[i], t)) for i in range(4)]
    sg = 1.0 if r[0] >= 0 else -1.0
    return [mul(v, sg) for v in r]


def hand_pose(pack, index, time):
    """0x0896DAB8(sortie, paquet, index, temps) : pose d'une animation de main au temps flottant
    `time` (image entiere + fraction) ; fraction >= 1e-5 : rotations interpolees (nlerp) et
    positions lineaires entre les images n et n + 1."""
    n = math.trunc(time); frac = sub(time, float(n))
    if frac < H_EPS: return hand_pose_frame(pack, index, n)
    U = lambda o: struct.unpack_from('<H', pack, o)[0]
    nanim, nb = U(2), U(4)
    types = [U(8 + 4 * nanim + 2 * i) for i in range(nb)]
    q0 = hand_pose_frame(pack, index, n); q1 = hand_pose_frame(pack, index, n + 1)
    g = sub(ONE, frac); out = []
    for b in range(nb):
        if 5 <= types[b] <= 8: out.append(nlerp(q0[b], q1[b], frac))
        else: out.append([add(mul(q0[b][i], g), mul(q1[b][i], frac)) for i in range(3)] + [H_W])
    return out


HAND_TABLE = 0x30        # 48 poses au plus dans la table par defaut (*(*(joueur + 0x8A4) + 0x38))


def hand_table(pack, count=None):
    """0x0896ECBC : table des poses de main par defaut, construite au chargement du personnage :
    pose k = image k de l'animation 0 du paquet de mains du moveset (moveset + 0x248), k < nombre
    d'images (0x0880BCCC) et k < 48."""
    off = struct.unpack_from('<I', pack, 8)[0] & ~1
    count = struct.unpack_from('<H', pack, off)[0] if count is None else count
    return [hand_pose(pack, 0, float(k)) for k in range(min(count, HAND_TABLE))]


def hand_select(table, pack, anims, time, ident=0, flags=0):
    """0x0896EF88 (une main), hors cache et hors fondu : pose de 15 quaternions.
    time : flottant joueur + 0x844 (main 0) / + 0x858 (main 1) ; ident : demi-mot + 0x848 / + 0x85C
    (bits 0..13 numero d'animation, bit 14 : paquet `anims` (anims_1 du personnage, joueur + 0x840)
    au lieu du paquet du moveset). ident = 0 et time < 48 : table par defaut (0x0896EDB8)."""
    if ident == 0 and math.trunc(time) < HAND_TABLE:
        n = math.trunc(time); frac = sub(time, float(n))
        if frac < H_EPS: return [list(q) for q in table[n]]
        return [nlerp(table[n][j], table[n + 1][j], frac) for j in range(15)]
    src = anims if ident & 0x4000 else pack
    return hand_pose(src, ident & 0x3FFF, time)


HAND_OS = (51, 66)       # premiers os des doigts (main 0 : 51..65, main 1 : 66..80), 0x1CB0 / 0x2520


def doigts(os_, gauche, droite):
    """0x0896F24C : ecrit les 2 x 15 os des doigts depuis les poses (quaternions) des deux mains.
    os 51 + 3 f + j (doigt f, phalange j) <- quaternion 3 f + j de la main 0 ; main 1 (os 66..80) :
    meme chose puis symetrie : phalange 0 -> D M D, D = diag(1, -1, 1) ; phalanges 1, 2 -> D = diag(1, -1, -1)
    (vpfxs sur C610 / R601, C600 / R600). Translations gardees. Rend os_ modifie."""
    for j, q in enumerate(gauche):
        o = HAND_OS[0] + j; os_[o] = quat_matrix(q, os_[o])
    for j, q in enumerate(droite):
        o = HAND_OS[1] + j; M = quat_matrix(q, os_[o])
        if j % 3 == 0:
            M[1] = [-M[1][0], M[1][1], -M[1][2], M[1][3]]
            M[0][1], M[2][1] = -M[0][1], -M[2][1]
        else:
            M[0] = [M[0][0], -M[0][1], -M[0][2], M[0][3]]
            M[1][0], M[2][0] = -M[1][0], -M[2][0]
        os_[o] = M
    return os_


# ---------------------------------------------------------------- apres 0x089AE50C (entre P1 et A)
# Transcriptions verifiees au bit contre l'interpreteur et les instantanes (POSE.md, section 2).
# Elles travaillent sur la memoire du jeu (classe Mem) : les entrees sont lues a leurs adresses.
class Mem:
    """Memoire utilisateur du jeu (24 Mo a 0x08800000), lecture / ecriture."""
    def __init__(s, ram): s.b = bytearray(ram)
    def o(s, a): return (a & 0x3FFFFFFF) - RAM0
    def u32(s, a): return int.from_bytes(s.b[s.o(a):s.o(a) + 4], 'little')
    def s32(s, a): v = s.u32(a); return v - (1 << 32) if v >> 31 else v
    def u16(s, a): return int.from_bytes(s.b[s.o(a):s.o(a) + 2], 'little')
    def s16(s, a): v = s.u16(a); return v - 0x10000 if v >> 15 else v
    def u8(s, a): return s.b[s.o(a)]
    def s8(s, a): v = s.b[s.o(a)]; return v - 0x100 if v >> 7 else v
    def f(s, a): return _up(bytes(s.b[s.o(a):s.o(a) + 4]))[0]
    def setf(s, a, x): s.b[s.o(a):s.o(a) + 4] = struct.pack('<I', bits(x))
    def set32(s, a, v): s.b[s.o(a):s.o(a) + 4] = struct.pack('<I', v & 0xFFFFFFFF)
    def v4(s, a): return [s.f(a + 4 * i) for i in range(4)]
    def setv4(s, a, v):
        for i in range(4): s.setf(a + 4 * i, v[i])
    def mat(s, a): return [s.v4(a + 16 * c) for c in range(4)]
    def setmat(s, a, m):
        for c in range(4): s.setv4(a + 16 * c, m[c])


ST = 0x08C8AFE4                # etat du regard, 0x54 o par joueur
GEL = 0x08C8AFE0               # drapeau global (remet le regard a l'etat 6)


def neg(x): return fbits(bits(x) ^ 0x80000000)
def fabs(x): return fbits(bits(x) & 0x7FFFFFFF)
def sign_bit(x): return bits(x) >> 31


def vmin(a, b):
    """vmin.s (JIT : MINSS sans SIMD : a < b ? a : b, NaN -> b)."""
    return a if a < b else b


def vmax(a, b): return a if a > b else b


def vsat1(x): return -1.0 if x < -1.0 else (1.0 if x > 1.0 else x)


def fmodf(x, y):
    """0x08A2F174 (fmodf de newlib, enveloppe) : reste exact."""
    if y == 0 or x != x or y != y or math.isinf(x): return math.nan
    return f32(math.fmod(x, y))


def wrap(x, two_pi, pi, mpi):
    """Motif du jeu : r = fmodf(x, 2 pi) ; r > pi -> r - 2 pi ; r < -pi -> r + 2 pi."""
    r = fmodf(x, two_pi)
    if pi < r: return sub(r, two_pi)
    if r < mpi: return add(r, two_pi)
    return r


def qmul(a, b):
    """0x0896D1FC : produit de quaternions (xyz = (a ^ b + b aw) + a bw ; w = aw bw - a.b)."""
    c = cross(a, b, a[3])
    c = [add(c[i], mul(b[i], a[3])) for i in range(4)]
    w = sub(mul(a[3], b[3]), dot3(a, b))
    c = [add(c[i], mul(a[i], b[3])) for i in range(4)]
    c[3] = w
    return c


def ry_cols(a):
    """vrot [C,0,-S] / [S,0,C] sur a x 2/PI : colonnes de Ry."""
    k = mul(a, TWO_PI_INV); s, c = vfpu_sin(k), vfpu_cos(k)
    return [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]]


def rz_cols(a):
    k = mul(a, TWO_PI_INV); s, c = vfpu_sin(k), vfpu_cos(k)
    return [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]


def rx_cols(a):
    k = mul(a, TWO_PI_INV); s, c = vfpu_sin(k), vfpu_cos(k)
    return [[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]]


def left(R, M):
    """vtfm3 de chaque colonne (y compris la translation, R003) : R . M, voies w gardees."""
    return [tfm(R, M[j][:3], 3) + [M[j][3]] for j in range(4)]


def transpose4(M): return [[M[r][c] for r in range(4)] for c in range(4)]


def world(m, osj):
    """monde(os) = monde(parent) . locale(os) ; parent = *(os + 0x80)."""
    par = m.u32(osj + 0x80)
    m.setmat(osj + 0x40, mmul(m.mat(par + 0x40), m.mat(osj)))


def stage_bit(m, b):
    """0x0882E1B4 (bit 5) / 0x0882E14C (bit 3) : drapeau du decor *(0x08AD87DC)[*(0x08B786D4)]."""
    return (m.u32(m.u32(0x08AD87DC + 4 * m.u32(0x08B786D4))) >> b) & 1


def flag_da18(m):
    """0x0880DA18 : *(0x08B78348) != 0 ou *(0x08B7833C) != 0 (pause / relecture ?)."""
    return 1 if (m.u32(0x08B78348) or m.u32(0x08B7833C)) else 0


def opponent(m, p):
    """0x089ADF38 : l'autre joueur (table 0x08B75730)."""
    return m.u32(0x08B75730 + (0 if m.s16(p + 0x12) else 4))


# ---------------------------------------------------------------- regard : 0x08926EF0
REGARD_LISTE = 0x08AEE230     # os recalcules en tete (octets, 0xFF = fin) : 0,1,2,3,4,13..16,18..20


def C(m, off): return m.f(0x08AF0000 - off)


def regard(m, p):
    os_ = m.u32(m.u32(p + 0x8A4) + 0x10)
    e1 = stage_bit(m, 5)
    pid = m.s16(p + 0x12)
    s2 = ST + 0x54 * pid
    s5 = flag_da18(m)
    opp = opponent(m, p)
    sp20 = m.v4(m.u32(m.u32(opp + 0x8A4) + 0x10) + 0x220)       # monde de l'os 3 adverse : translation
    s6 = os_ + 0x1B0
    M40 = m.mat(s6)
    f = add(m.f(os_ + 0x270), m.f(os_ + 0x3638))
    M40[3][0] = add(M40[3][0], f)
    M40 = mmul(m.mat(m.u32(os_ + 0x230) + 0x40), M40)
    sp30 = list(M40[3])                                         # point des yeux (monde)
    a = REGARD_LISTE
    while True:
        b = m.s8(a)
        if b < 0: break
        world(m, os_ + 0x90 * b); a += 1
    s7 = 0
    if s5 == 0:
        ang = atan2f(m.f(os_ + 0x170), m.f(os_ + 0x178))
        two_pi, pi, mpi = C(m, 0x1E80), C(m, 0x1E7C), C(m, 0x1E78)
        f20 = wrap(sub(ang, f32(float(m.s16(p + 0x7A)))), two_pi, pi, mpi)
        d = wrap(sub(f20, m.f(s2 + 0x48)), two_pi, pi, mpi)
        m.setf(s2 + 0x44, d); m.setf(s2 + 0x48, f20)
        f21 = mul(vfpu_asin(vsat1(neg(m.f(os_ + 0x174)))), PI_2)
        d = wrap(sub(f21, m.f(s2 + 0x50)), two_pi, pi, mpi)
        m.setf(s2 + 0x4C, d); m.setf(s2 + 0x50, f21)
    t0 = 0
    if e1 and m.s32(p + 0x6AC) > 0:
        a0 = m.u32(p + 0xC4)
        if m.u32(a0 + 0x3C) & 0x20000000:
            a1 = 1 if C(m, 0x1E74) <= m.f(os_ + 0xD4) else 0
            if m.u16(a0 + 0x44) == 0:
                t0 = a1; s7 = 1
            else:
                raise NotImplementedError('regard : chemin 0x089270E8 (coup avec +0x44 non nul)')
    if m.u32(GEL): s7 = 1
    m.setf(p + 0x74, m.f(p + 0x20))
    fp = None
    sp80 = None
    if s7:
        sp10 = list(sp20); fp = 'sp10'
        a0 = m.s32(s2 + 0xC)
        if a0 < 6 and s5 == 0: m.set32(s2 + 0xC, a0 + 1)
    else:
        if s5 == 0: m.set32(s2 + 0xC, m.s32(s2 + 0xC) - 2)
        if m.s32(s2 + 0xC) < 0: m.set32(s2 + 0xC, 0)
        sp80 = m.v4(0x08AEE240)
        M40 = m.mat(os_ + 0x1F0); M40[3] = list(sp30)
        sp10 = tfm(M40, sp80); fp = 'sp10'
        sp80 = [C(m, 0x1E70), 0.0, sp80[2], sp80[3]]
        M40 = m.mat(os_ + 0x280); M40[3] = list(sp30)
        sp20 = tfm(M40, sp80)
    # 0x0892724C
    f1 = None
    if m.s16(p + 0x148) == 0 and e1 and not (m.f(os_ + 0xD4) < C(m, 0x1E74)) and m.s32(p + 0x6AC) > 0:
        v1 = m.u32(p + 0xC4)
        if m.u32(v1 + 0x3C) & 0x20 or m.u32(p + 0xCC) & 0x18:
            f1 = m.f(p + 0x74)
        elif t0:
            sp0 = list(sp20); sp0[1] = m.f(os_ + 0x7C4); m.set32(s2 + 0x2C, 2)
        else:
            a0 = m.s32(s2 + 0x2C)
            if a0 > 0 and s5 == 0: m.set32(s2 + 0x2C, a0 - 1)
            f1 = mul(f32(float(m.s16(p + 0x7A))), C(m, 0x1E6C))
    else:
        a0 = m.s32(s2 + 0x2C)
        if a0 > 0 and s5 == 0: m.set32(s2 + 0x2C, a0 - 1)
        f1 = m.f(p + 0x20)
    if f1 is not None:
        R = ry_cols(f1)
        M = [R[0] + [0.0], R[1] + [0.0], R[2] + [0.0], [0.0, 0.0, 0.0, 1.0]]
        v = tfm(M, m.v4(0x08AEE250))
        sp0 = [add(v[i], m.f(os_ + 0x7C0 + 4 * i)) for i in range(4)]
        sp0[3] = C(m, 0x1E68)
    # 0x08927334
    regard_tronc(m, os_, p, t0, s5, sp0, m.f(p + 0x20))
    two_pi, pi, mpi = C(m, 0x1E80), C(m, 0x1E7C), C(m, 0x1E78)
    m.setf(p + 0x74, wrap(add(m.f(s2 + 0x30), m.f(p + 0x20)), two_pi, pi, mpi))
    M40 = m.mat(os_ + 0x160); M40[3] = list(sp30)
    regard_cou(m, os_, p, s7, s5, sp10, M40, 0)
    m.setmat(os_ + 0x1F0, mmul(m.mat(m.u32(os_ + 0x230) + 0x40), m.mat(s6)))
    M40 = m.mat(os_ + 0x1F0); M40[3] = list(sp30)
    regard_tete(m, os_, p, s7, s5, sp20, M40, 0)
    m.setmat(os_ + 0x280, mmul(m.mat(m.u32(os_ + 0x2C0) + 0x40), m.mat(os_ + 0x240)))
    m.set32(GEL, 0)


# ---------------------------------------------------------------- tronc : 0x0892773C
def lissage(m, p, flag, a, b, k):
    """0x08928844 : b + (a - b) min(k, 1) (les deux chemins donnent la meme valeur)."""
    k = vmin(k, m.f(0x08AEE218))
    return add(b, mul(sub(a, b), k))


def regard_tronc(m, os_, p, a2, a3, target, f21):
    pid = m.s16(p + 0x12)
    s0 = ST + 0x54 * pid
    two_pi, pi, mpi = C(m, 0x1E60), C(m, 0x1E5C), C(m, 0x1E58)
    sp0 = [0.0, C(m, 0x1E64), 0.0, 0.0]
    a = atan2f(neg(m.f(p + 0x7A0)), neg(m.f(p + 0x7A8)))
    f20 = wrap(sub(a, f21), two_pi, pi, mpi)
    if C(m, 0x1E54) < fabs(f20): f20 = 0.0
    if a3:
        f12 = m.f(s0 + 0x30)
    else:
        if a2 or m.u16(m.u32(p + 0xC4) + 0x44): f23 = C(m, 0x1E50)
        else: f23 = C(m, 0x1E4C)
        d = [sub(target[i], m.f(os_ + 0x7C0 + 4 * i)) for i in range(4)]
        a = atan2f(d[0], d[2])
        r = wrap(sub(a, f21), two_pi, pi, mpi)
        f13 = wrap(sub(r, f20), two_pi, pi, mpi)
        f12 = f13
        s2 = 1 if 0.0 < f13 else 2
        if f13 < C(m, 0x1E48): s2 = 4
        elif C(m, 0x1E44) < f13: s2 = 3
        prev = m.s32(s0 + 0x38)
        if (s2 == 3 and prev == 4) or (s2 == 4 and prev == 3):
            f12 = wrap(sub(m.f(s0 + 0x30), f20), two_pi, pi, mpi)
        f12 = vmax(f12, sub(m.f(s0 + 0x40), f20))
        f12 = vmin(f12, sub(m.f(s0 + 0x3C), f20))
        f22 = f12
        m.setf(s0 + 0x34, wrap(add(f12, f20), two_pi, pi, mpi))
        r2 = wrap(sub(m.f(s0 + 0x30), f20), two_pi, pi, mpi)
        f0 = lissage(m, p, a2, f22, r2, f23)
        m.setf(s0 + 0x30, wrap(add(f0, f20), two_pi, pi, mpi))
        if s2 < 3 or m.s32(s0 + 0x38) < 3: m.set32(s0 + 0x38, s2)
        f12 = m.f(s0 + 0x30)
    k = mul(f12, INV_PI); s, c = vfpu_sin(k), vfpu_cos(k)
    qr = [mul(sp0[0], s), mul(sp0[1], s), mul(sp0[2], s), mul(ONE, c)]
    q0 = matrix_quat(m.mat(os_))
    q = qmul(q0, qr)
    m.setmat(os_, quat_matrix(q, m.mat(os_)))
    for j in (0, 1, 2, 13): world(m, os_ + 0x90 * j)


# ---------------------------------------------------------------- cou (0x08927D08) et tete (0x089282C4)
def vers_local(target, M):
    """d = cible - M.c3 (w = 0), exprime dans M : tfm4(transposee(M), d)."""
    d = [sub(target[i], M[3][i]) for i in range(4)]; d[3] = 0.0
    return tfm(transpose4(M), d)


def amorti(v, ref, vel, f22, one):
    """Motif : si vel (v - ref) < 0 et |v - ref| f22 < |vel| : ref + (v - ref) min(2 f22, 1),
    sinon ref + (v - ref) min(f22, 1)."""
    dlt = sub(v, ref)
    if mul(vel, dlt) < 0.0 and mul(fabs(dlt), f22) < fabs(vel):
        return add(ref, mul(dlt, vmin(add(f22, f22), one)))
    return add(ref, mul(dlt, vmin(f22, one)))


def regard_cou(m, os_, p, s4, a3, target, M, s3):
    pid = m.s16(p + 0x12)
    s0 = ST + 0x54 * pid
    if m.u32(GEL):
        m.set32(s0 + 0xC, 6); a3 = 0; s4 = 1; f22 = C(m, 0x1E3C)
    else: f22 = C(m, 0x1E40)
    one = C(m, 0x1E3C)
    if a3:
        if m.s32(s0 + 0xC) > 0:
            cou_pose(m, os_ + 0x1B0, pid, m.f(s0 + 0x1C), m.f(s0 + 0x20))
        return
    v = vers_local(target, M)
    if m.s32(s0 + 0xC) <= 0:
        raise NotImplementedError('regard_cou : chemin 0x089281F8 (compteur nul)')
    f20 = atan2f(v[2], v[1])
    if 0.0 < f20:
        if C(m, 0x1E34) < f20:
            s1 = 3; f21 = div(sub(f20, C(m, 0x1E30)), C(m, 0x1E2C))
            if f21 < 0.0: f21 = 0.0
        else: f21 = one; s1 = 1
    else:
        if f20 < C(m, 0x1E38):
            s1 = 4; f21 = div(sub(f20, C(m, 0x1E28)), C(m, 0x1E24))
            if f21 < 0.0: f21 = 0.0
        else: f21 = one; s1 = 2
    if s3:
        f2 = m.f(s0 + 0x34)
        if mul(f2, f20) < 0.0: f20 = add(f20, sub(f2, m.f(s0 + 0x30)))
    prev = m.s32(s0 + 0x24)
    if (s1 == 3 and prev == 4) or (s1 == 4 and prev == 3):
        f20 = m.f(s0 + 0x1C); f21 = m.f(s0 + 0x20); f4, f5 = f20, f21
    else:
        w = sqrtf(add(add(mul(v[1], v[1]), mul(v[2], v[2])), mul(0.0, 0.0)))
        f21 = mul(f21, atan2f(neg(v[0]), w))
        f4 = m.f(s0 + 0x1C); f5 = m.f(s0 + 0x20)
    if s1 == 3 and prev == 3: f20 = C(m, 0x1E20)
    if s1 == 4 and prev == 4: f20 = C(m, 0x1E1C)
    f20 = vmin(vmax(f20, C(m, 0x1E1C)), C(m, 0x1E20))
    f20 = amorti(f20, f4, m.f(s0 + 0x44), f22, one)
    skip = False
    if s4 == 1 and not m.u32(GEL):
        lim = C(m, 0x1E18)
        if lim < fabs(sub(f20, f4)) or fabs(sub(f21, f5)) < lim:
            f21 = f5; skip = True
    if not skip:
        f21 = vmin(vmax(f21, C(m, 0x1E14)), C(m, 0x1E10))
        f21 = amorti(f21, f5, m.f(s0 + 0x4C), f22, one)
    cou_pose(m, os_ + 0x1B0, pid, f20, f21)
    m.setf(s0 + 0x1C, f20); m.setf(s0 + 0x20, f21)
    if s1 < 3 or m.s32(s0 + 0x24) < 3: m.set32(s0 + 0x24, s1)


def cou_pose(m, os3, pid, yaw, pitch):
    """0x089269FC : cible R = Rx(yaw) . Rz(pitch), puis nlerp(quaternion de l'os, cible, n / 6)."""
    s1 = ST + 0x54 * pid
    Rz = rz_cols(pitch)
    M = [Rz[0] + [0.0], Rz[1] + [0.0], Rz[2] + [0.0], [0.0, 0.0, 0.0, 0.0]]
    M = left(rx_cols(yaw), M)
    q1 = matrix_quat(M)
    q2 = matrix_quat(m.mat(os3))
    t = mul(f32(float(m.s32(s1 + 0xC))), m.f(0x08AEE150))
    m.setmat(os3, quat_matrix(nlerp(q2, q1, t), m.mat(os3)))


def regard_tete(m, os_, p, s4, a3, target, M, s3):
    pid = m.s16(p + 0x12)
    s0 = ST + 0x54 * pid
    if m.u32(GEL):
        m.set32(s0 + 0xC, 6); a3 = 0; s4 = 1; f22 = C(m, 0x1E08)
    else: f22 = C(m, 0x1E0C)
    one = C(m, 0x1E08)
    if a3:
        if m.s32(s0 + 0xC) > 0:
            tete_pose(m, os_ + 0x240, p, m.f(s0 + 0x10), m.f(s0 + 0x14))
        return
    v = vers_local(target, M)
    if m.s32(s0 + 0xC) <= 0:
        raise NotImplementedError('regard_tete : chemin 0x08928778 (compteur nul)')
    f21 = atan2f(v[2], v[1])
    s1 = 1 if 0.0 < f21 else 2
    if f21 < C(m, 0x1E04): s1 = 4
    elif C(m, 0x1E00) < f21: s1 = 3
    if s3:
        f2 = m.f(s0 + 0x34)
        if mul(f2, f21) < 0.0: f21 = add(f21, sub(f2, m.f(s0 + 0x30)))
    prev = m.s32(s0 + 0x18)
    if (s1 == 3 and prev == 4) or (s1 == 4 and prev == 3):
        f21 = m.f(s0 + 0x10); f20 = m.f(s0 + 0x14); f4, f5 = f21, f20
    else:
        w = sqrtf(add(add(mul(v[1], v[1]), mul(v[2], v[2])), mul(0.0, 0.0)))
        f20 = atan2f(neg(v[0]), w)
        f4 = m.f(s0 + 0x10); f5 = m.f(s0 + 0x14)
    if s1 in (3, 4): f20 = 0.0
    if s1 == 3 and prev == 3: f21 = C(m, 0x1DFC)
    if s1 == 4 and prev == 4: f21 = C(m, 0x1DF8)
    f21 = vmin(vmax(f21, C(m, 0x1DF8)), C(m, 0x1DFC))
    f21 = amorti(f21, f4, m.f(s0 + 0x44), f22, one)
    skip = False
    if s4 == 1 and not m.u32(GEL):
        lim = C(m, 0x1DF4)
        if lim < fabs(sub(f21, f4)) or fabs(sub(f20, f5)) < lim:
            f20 = f5; skip = True
    if not skip:
        f20 = vmin(vmax(f20, C(m, 0x1DF0)), C(m, 0x1DEC))
        f20 = amorti(f20, f5, m.f(s0 + 0x4C), f22, one)
    tete_pose(m, os_ + 0x240, p, f21, f20)
    m.setf(s0 + 0x10, f21); m.setf(s0 + 0x14, f20)
    if s1 < 3 or m.s32(s0 + 0x18) < 3: m.set32(s0 + 0x18, s1)


def tete_pose(m, os4, p, yaw, pitch):
    """0x08926AC4 : cible Ry(b) . Rz(pi/2) . Rz(yaw) . Ry(pitch) (b = 0,1745 si p+0x3E = 0x1E, sinon pi/2),
    puis nlerp(quaternion de l'os, cible, n / 6)."""
    s2 = ST + 0x54 * m.s16(p + 0x12)
    R = ry_cols(pitch)
    M = [R[0] + [0.0], R[1] + [0.0], R[2] + [0.0], [0.0, 0.0, 0.0, 1.0]]
    M = left(rz_cols(yaw), M)
    M = left(rz_cols(m.f(0x08AEE154)), M)
    b = m.f(0x08AEE158) if m.s16(p + 0x3E) == 0x1E else m.f(0x08AEE154)
    M = left(ry_cols(b), M)
    q1 = matrix_quat(M)
    q2 = matrix_quat(m.mat(os4))
    t = mul(f32(float(m.s32(s2 + 0xC))), m.f(0x08AEE15C))
    m.setmat(os4, quat_matrix(nlerp(q2, q1, t), m.mat(os4)))


SCR = 0x09B78850              # etat par joueur (0x460 o) : 7 ressorts de 0x70 o, longueurs (+0x444), sol (+0x310)


def scr(m, idx, pid): return SCR + idx * 0x8C0 + pid * 0x460


def tfm_t3(M, v):
    """vtfm3.t avec une matrice non transposee : (colonne i . v) = R^T v (3 termes dans l'ordre)."""
    return [dot3(M[i], v) for i in range(3)]


def world_c3(m, osj):
    """monde(os).c3 = monde(parent) . locale(os).c3 (vtfm4 : position seule)."""
    par = m.u32(osj + 0x80)
    m.setv4(osj + 0x70, tfm(m.mat(par + 0x40), m.v4(osj + 0x30)))


def ressorts(m, p, idx, flag):
    """0x089B19FC (chemin du coup sans +0x44) : les 7 vecteurs d'impulsion (+0x50 de chaque ressort)
    sont amortis (x 0,9, 0x08B36608), puis les octets +0x394 / +0x395 remis a 0."""
    if flag: return
    s0 = scr(m, idx, m.s16(p + 0x12))
    k = m.f(0x08B36608)
    for i in range(6, -1, -1):
        a = s0 + 0x70 * i + 0x50
        m.setv4(a, [mul(x, k) for x in m.v4(a)])
    if m.u16(m.u32(p + 0xC4) + 0x44):
        raise NotImplementedError('ressorts : chemin 0x089B1AC4 (coup avec +0x44 non nul)')
    s4 = s0 + 0x330
    m.b[m.o(s4 + 0x64)] = 0; m.b[m.o(s4 + 0x65)] = 0


def sol(m, p, os_, idx, pid, t0, t1):
    """0x089B2AF4 (chemin de la garde) : decalage vertical lisse (+0x310 du bloc), reporte dans
    joueur + 0x764 et + 0x7A4."""
    s3 = scr(m, idx, pid); s2 = s3 + 0x310
    f20 = 0.0; f21 = 0.0
    if m.u32(0x08B78308): raise NotImplementedError('sol : chemin 0x089B2EF0')
    if m.u32(m.u32(p + 0xC4) + 0x3C) & 0x10000000: raise NotImplementedError('sol : chemin 0x089B2B98')
    if t0: raise NotImplementedError('sol : chemin 0x089B2DBC')
    if m.u8(p + 0x1A9): raise NotImplementedError('sol : chemin 0x089B2ED0')
    if t1: f20 = add(f20, f21)
    if f20 < f21: f20 = f21
    f3 = add(m.f(s3 + 0x310), m.f(p + 4))
    m.setf(s3 + 0x310, f3)
    if m.u32(0x08B640A8): raise NotImplementedError('sol : chemin 0x089B2C68')
    if f20 < f3: raise NotImplementedError('sol : chemin 0x089B2E6C')
    m.setf(s2 + 4, f21)
    m.setf(s3 + 0x310, add(mul(f3, m.f(0x08B36634)), mul(f20, m.f(0x08B36638))))
    f20 = m.f(0x08B3663C)
    if m.u32(0x09B799D0): raise NotImplementedError('sol : chemin 0x089B2C84')
    f1 = sub(m.f(0x08B36640), m.f(p + 0x764))
    if f20 < f1 and m.f(s2) < f1: f20 = f1
    if fabs(m.f(os_ + 0x794)) < m.f(0x08B36644): raise NotImplementedError('sol : chemin 0x089B2CF4')
    if 0.0 < f20: raise NotImplementedError('sol : chemin 0x089B2D8C')
    k = m.f(0x08B36638)
    m.setf(s2 + 8, mul(m.f(s2 + 8), k)); m.setf(s2 + 0xC, mul(m.f(s2 + 0xC), k))
    m.setf(s2, sub(m.f(s2), m.f(p + 4)))
    f2 = m.f(s2)
    m.setf(p + 0x764, add(m.f(p + 0x764), f2))
    m.setf(p + 0x7A4, add(m.f(p + 0x7A4), m.f(s2)))
    if m.u32(s3 + 0x3D0 + 0x48) & 0x0F000000 == 0x09000000:
        raise NotImplementedError('sol : chemin 0x089B2DF4')


def pied(m, a0, a1, a2, pid, leg, t1, idx, f12):
    """0x089B0840 : position de l'extremite (a0) corrigee par le ressort (+0, +0x10) et l'impulsion
    (+0x50) du membre ; contact au sol. Rend 1 si la position change (ecrite en a0)."""
    t2 = scr(m, idx, pid); a3 = t2 + leg * 0x70; t5 = t2 + leg * 12 + 0x3D0
    sp10 = m.v4(a0)
    imp = m.v4(a3 + 0x50)
    sp10 = [add(sp10[i], imp[i]) for i in range(3)] + [sp10[3]]
    sp0 = list(sp10)
    ofs = m.v4(a3)
    sp10 = [add(sp10[i], ofs[i]) for i in range(4)]
    v = m.v4(a1); sp20 = [add(v[i], ofs[i]) for i in range(4)]
    sp30 = None
    if a2:
        v = m.v4(a2); sp30 = [add(v[i], ofs[i]) for i in range(4)]
    if t1 == 0:
        vel = [mul(x, m.f(0x08B365E8)) for x in m.v4(a3)]
        m.setv4(a3 + 0x10, vel)
        m.setv4(a3, [add(m.f(a3 + 4 * i), vel[i]) for i in range(4)])
    m.set32(t5, m.u32(t2 + 0x418))
    f3 = f12
    ref = m.v4(a3 + 0x40)
    d = [sub(sp10[i], ref[i]) for i in range(4)]
    q = add(add(mul(d[2], d[2]), mul(d[0], d[0])), mul(0.0, 0.0))
    if q < m.f(0x08B365EC):
        a1f = 1
        f2 = m.f(a3 + 0x44)
        if m.f(0x08B365F0) < fabs(sub(f12, f2)): f3 = f2
        else:
            m.setf(a3 + 0x44, f12)
            m.setf(a3 + 0x40, sp10[0]); m.setf(a3 + 0x48, sp10[2])
    else:
        m.setf(a3 + 0x44, f12); a1f = 0
        m.setf(a3 + 0x40, sp10[0]); m.setf(a3 + 0x48, sp10[2])
    f1 = sp20[1]
    if f1 < add(f3, m.f(0x08B365F4)):
        m.set32(t2 + 0x3B0, m.u32(t2 + 0x3B0) | (1 << leg))
        if f1 < f3:
            f2 = sub(f3, f1)
            sp10[1] = add(sp10[1], f2)
            if a2: sp30[1] = add(sp30[1], f2)
            sp20[1] = add(f1, f2)
            m.set32(a3 + 0x14, 0)
            nv = [sub(sp10[i], sp0[i]) for i in range(4)]
            m.setv4(a3, [mul(x, m.f(0x08B365F8)) for x in nv])
    if a2:
        f3 = add(f12, 0.0)
        if a1f and m.f(0x08B365F0) < fabs(sub(f3, m.f(a3 + 0x44))):
            raise NotImplementedError('pied : chemin 0x089B0A78')
        m.setf(a3 + 0x4C, f3)
        f2 = sp30[1]
        if f2 < add(f3, m.f(0x08B365F4)):
            m.set32(t2 + 0x3B0, m.u32(t2 + 0x3B0) | (1 << leg))
            if f2 < f3: raise NotImplementedError('pied : chemin 0x089B0AB0')
        if m.u32(t5) & 0x0F000000 == 0x09000000: raise NotImplementedError('pied : chemin 0x089B0B18')
    cur = m.v4(a0)
    d = [sub(cur[i], sp10[i]) for i in range(4)]
    if dot3(d, d) < m.f(0x08B365FC): return 0
    m.setv4(a0, sp10)
    return 1


def ik2(m, osa, target, osb, flag, L1, L2, ang):
    """0x089B2590 : IK a deux os. osa (hanche / epaule) et osb (genou / coude), locales modifiees.
    target : extremite voulue (vecteur, repere du parent de osa) ; L1, L2 : longueurs ; ang : angle
    courant de osb (radians)."""
    s6 = add(mul(L1, L1), mul(L2, neg(L2)))
    f20 = mul(ang, m.f(0x08B36620))
    iv = math.trunc(f20) if f20 == f20 and abs(f20) < 2 ** 31 else 0x7FFFFFFF
    iv = ((iv & 0xFFFF) ^ 0x8000) - 0x8000
    a = f32(float(iv) * 2.0 ** -14)
    sn, cs = vfpu_sin(a), vfpu_cos(a)
    A = m.mat(osa)
    f0 = add(mul(L2, cs), L1)
    v110 = [mul(x, f0) for x in A[0]]
    f0 = mul(L2, sn)
    v100 = [mul(x, f0) for x in A[1]]
    v110 = [sub(v110[i], v100[i]) for i in range(4)]
    d = dot3(v110, v110)
    eps = m.f(0x08B36624)
    if not d < eps:
        r = div(ONE, sqrtf(d))
        c010 = [mul(v110[i], r) for i in range(3)] + [0.0]
        c020 = list(A[2])
        c000 = cross(c020, c010, 0.0)
    else:
        c000, c010, c020 = list(A[0]), list(A[1]), list(A[2])
        if flag: c000 = [neg(x) for x in c000[:3]] + [c000[3]]
        else: c010 = [neg(x) for x in c010[:3]] + [c010[3]]
    F = [c010, c000, c020]
    c3 = A[3]
    v110 = [sub(target[i], c3[i]) for i in range(4)]
    f20 = dot3(v110, v110)
    if f20 < eps: raise NotImplementedError('ik2 : chemin 0x089B275C (cible confondue)')
    rs = div(ONE, sqrtf(f20)); f22 = fabs(sqrtf(f20))
    c010 = [mul(v110[i], rs) for i in range(3)] + [v110[3]]
    c030 = cross(F[0], c010, 0.0)
    if not dot3(c030, c030) < eps:
        raise NotImplementedError('ik2 : chemin 0x089B2A20 (rotation vers la cible)')
    for j in range(3): m.setv4(osa + 16 * j, F[j])
    for j, row in enumerate(([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])):
        m.setv4(osb + 16 * j, row + [0.0])
    if add(L1, L2) <= f22: return
    if f22 <= fabs(sub(L1, L2)): raise NotImplementedError('ik2 : chemin 0x089B27BC (cible trop proche)')
    f25 = add(f22, f22)
    one = m.f(0x08B3662C); mone = m.f(0x08B36628)
    c = div(add(f20, s6), mul(f25, L1))
    if one < c: raise NotImplementedError('ik2 : chemin 0x089B2868')
    if c < mone: raise NotImplementedError('ik2 : chemin 0x089B2984')
    s = sqrtf(sub(one, mul(c, c)))
    if flag: s = neg(s)
    Rz1 = [[c, s, 0.0, 0.0], [neg(s), c, 0.0, 0.0], [0.0, 0.0, one, 0.0], [0.0, 0.0, 0.0, 1.0]]
    m.setmat(osa, mmul(m.mat(osa), Rz1))
    f12 = div(sub(f20, s6), mul(f25, L2))
    if one < f12: raise NotImplementedError('ik2 : chemin 0x089B28CC')
    # le jeu compare ici un mot de pile (sp+0x124 : y du produit vectoriel c030) a -1
    if c030[1] < mone: raise NotImplementedError('ik2 : chemin 0x089B2958')
    f3 = sqrtf(sub(one, mul(f12, f12)))
    if flag: f3 = neg(f3)
    f2 = mul(c, f3); f1 = mul(s, f12); f0 = mul(c, f12); f3b = mul(s, f3)
    f1 = add(f1, f2); f0 = sub(f0, f3b)
    Rz2 = [[f0, neg(f1), 0.0, 0.0], [f1, f0, 0.0, 0.0], [0.0, 0.0, one, 0.0], [0.0, 0.0, 0.0, 1.0]]
    m.setmat(osb, mmul(m.mat(osb), Rz2))


def ik_membre(m, pid, i1, i2, ref, osa, osb, target, flag, idx):
    """0x089B0754 : cible exprimee dans le repere de ref (monde de l'os 13), longueurs du bloc."""
    s0 = scr(m, idx, pid)
    t = m.v4(target); M = m.mat(ref)
    d = [sub(t[i], M[3][i]) for i in range(3)]
    loc = tfm_t3(M, d) + [1.0]
    ang = atan2f(neg(m.f(osb + 4)), m.f(osb))
    L1 = m.f(s0 + 0x444 + 4 * i1); L2 = m.f(s0 + 0x444 + 4 * i2)
    ik2(m, osa, loc, osb, flag, L1, L2, ang)


def membre_fin(m, os_, a, b, c):
    """Mondes de a, b ; locale de c = R(monde b)^T . R(monde c) (3 x 3, voies w de monde c)."""
    world(m, os_ + 0x90 * a); world(m, os_ + 0x90 * b)
    Wb = m.mat(os_ + 0x90 * b + 0x40); Wc = m.mat(os_ + 0x90 * c + 0x40)
    for i in range(3):
        col = [dot3(Wb[r], Wc[i]) for r in range(3)] + [Wc[i][3]]
        m.setv4(os_ + 0x90 * c + 16 * i, col)


def jambe(m, leg, out, os_, pid, flag, idx):
    """0x089B0C18 : pied 16 (20), genou 15 (19), hanche 14 (18), points 23, 24 (25, 26)."""
    s3, t0, a3, a0, s5, s4 = (16, 0, 24, 23, 14, 15) if leg == 0 else (20, 1, 26, 25, 18, 19)
    out.append(m.v4(os_ + 0x90 * s3 + 0x70))
    s1 = os_ + 0x90 * s3 + 0x70
    pied(m, s1, os_ + 0x90 * a3 + 0x70, os_ + 0x90 * a0 + 0x70, pid, t0, flag, idx, 0.0)
    ik_membre(m, pid, 0, 1, os_ + 0x790, os_ + 0x90 * s5, os_ + 0x90 * s4, s1, 1, idx)
    membre_fin(m, os_, s5, s4, s3)


def bras(m, side, os_, pid, flag, idx):
    """0x089B0E6C : main 8 (12) ; si elle bouge (ressort), IK epaule 5 (9) / coude 7 (11)."""
    s7, t0, s0, s4, s3 = (8, 2, 5, 6, 7) if side == 0 else (12, 3, 9, 10, 11)
    v0 = os_ + 0x90 * s7
    f12 = add(mul(fabs(m.f(v0 + 0x44)), m.f(0x08B36600)), m.f(0x08B36604))
    s1 = v0 + 0x70
    if pied(m, s1, s1, 0, pid, t0, flag, idx, f12) == 0: return
    raise NotImplementedError('bras : chemin 0x089B0F44 (IK du bras)')


def monde(m, p, idx, os_):
    """0x089B10B4(joueur, idx, os)."""
    mode = m.u32(0x08B7519C)
    if mode in (9, 0x28) or m.u8(p + 0x1AB): return
    s1 = (stage_bit(m, 3) ^ 1) & 0xFF
    pid = m.s16(p + 0x12)
    s5 = scr(m, idx, pid)
    m.set32(s5 + 0x3B0, 0); m.set32(s5 + 0x3C0, 0)
    s6 = flag_da18(m)
    ressorts(m, p, idx, s6)
    sol(m, p, os_, idx, pid, s6, s1)
    m.setf(os_ + 0x74, add(m.f(os_ + 0x74), m.f(s5 + 0x310)))
    m.setf(os_ + 0x7C4, add(m.f(os_ + 0x7C4), m.f(s5 + 0x310)))
    s1 = 1 if m.u16(p + 0x870) else 0
    m.setf(os_ + 0x974, add(m.f(os_ + 0x974), m.f(s5 + 0x310)))
    world(m, os_ + 0x90 * 17)
    world_c3(m, os_ + 0x90 * 23); world_c3(m, os_ + 0x90 * 24)
    out = []
    jambe(m, 0, out, os_, pid, s6, idx)
    m.setf(os_ + 0xBB4, add(m.f(os_ + 0xBB4), m.f(s5 + 0x310)))
    world(m, os_ + 0x90 * 21)
    world_c3(m, os_ + 0x90 * 25); world_c3(m, os_ + 0x90 * 26)
    jambe(m, 1, out, os_, pid, s6, idx)
    if s1: raise NotImplementedError('monde : chemin 0x089B1688 (joueur + 0x870)')
    for j in (1, 2, 9, 10, 11, 12): world(m, os_ + 0x90 * j)
    bras(m, 1, os_, pid, s6, idx)
    for j in (5, 6, 7, 8): world(m, os_ + 0x90 * j)
    bras(m, 0, os_, pid, s6, idx)
    for base in (s5 + 0x3B0, s5 + 0x3C0):
        a2 = m.u32(base); a1 = m.u32(base + 4)
        x = a2 ^ a1
        m.set32(base + 0xC, x & a1); m.set32(base + 8, x & a2); m.set32(base + 4, a2)


MONDE_EXTRA = (72, 57, 81, 86, 95, 104)


def monde_final(m, p):
    """0x089AE260 : matrice du joueur (+0x730) recopiee en +0x770 (monde du parent de l'os 0), mondes
    des os 0..26 puis 72, 57, 81, 86, 95, 104 ; historique des extremites (0x089B16A4).
    (0x08A0B908 empile en plus le registre VFPU M700 sur une pile de matrices : sans rapport.)"""
    os_ = m.u32(m.u32(p + 0x8A4) + 0x10)
    m.setmat(p + 0x770, m.mat(p + 0x730))
    for j in range(27): world(m, os_ + 0x90 * j)
    for j in MONDE_EXTRA: world(m, os_ + 0x90 * j)
    a1 = scr(m, 0, m.s16(p + 0x12))
    for o in (0x20, 0x90, 0x100, 0x170, 0x1E0, 0x250, 0x2C0):
        m.setv4(a1 + o + 0x10, m.v4(a1 + o))
    for o, src in ((0x20, 0x970), (0x90, 0xBB0), (0x100, 0x4F0), (0x170, 0x730), (0x1E0, 0x220), (0x250, 0x2B0), (0x2C0, 0x70)):
        m.setv4(a1 + o, m.v4(os_ + src))
    m.setf(a1 + 0x320, m.f(a1 + 0x310))
    # 0x08A0B908 : M700 (registre VFPU, sans rapport avec la pose) empile en *(0x09BA5484) ; seuls le
    # pointeur et le compteur sont reproduits (les 64 octets empiles ne sont pas connus ici)
    m.set32(0x09BA5484, m.u32(0x09BA5484) + 0x40)
    m.set32(0x09BA548C, m.u32(0x09BA548C) - 1)


def _poignee(m, a):
    """Couple (pointeur, generation) valide : *(a) si *(*(a) + 0xC) == *(a + 4), sinon remis a zero."""
    ptr = m.u32(a)
    if ptr and m.u32(ptr + 0xC) == m.u32(a + 4): return ptr
    m.set32(a + 4, 0); m.set32(a, 0)
    return 0


def visage_actif(m, p):
    """Garde de 0x0896E898 : objet de reglages 0x08974E6C(0x09B2A500, 1) -> 0x08804740(., joueur),
    octet +0xB8 non nul. Dans les instantanes il est nul : le visage n'est pas anime."""
    obj = _poignee(m, 0x09B2A500 + 8 + 0xE8)
    if not obj: return False
    a2 = _poignee(m, obj + 0x78)
    o2 = _poignee(m, a2 + 8 * m.s16(p + 0x12) + 0x50)
    return bool(o2 and m.u8(o2 + 0xB8))


def apres_pose(m, p):
    """Suite de 0x089AF40C apres 0x089AE50C et les doigts : copie des 22 locales (*(+0x8A4) + 0x20),
    regard (0x08926EF0, sauf modes 9 et 0x28), mondes / sol / jambes / bras (0x089B10B4)."""
    if visage_actif(m, p): raise NotImplementedError('visage (0x0896E898) non transcrit')
    os_ = m.u32(m.u32(p + 0x8A4) + 0x10)
    if flag_da18(m) == 0:
        dst = m.u32(m.u32(p + 0x8A4) + 0x20)
        for j in range(22): m.setmat(dst + 0x40 * j, m.mat(os_ + 0x90 * j))
    if m.u32(0x08B7519C) not in (9, 0x28): regard(m, p)
    if m.u32(0x08B7CBD4) & 1: raise NotImplementedError('0x089BAEE4 non transcrit')
    monde(m, p, 0, os_)


# ---------------------------------------------------------------- depuis l'ISO
# Os du jeu (0x90 o, *(*(joueur + 0x8A4) + 0x10)) -> articulation du squelette (sous-fichier 12 du
# modele, dr_model.skeleton). Tables du jeu : angles d'Euler *(+0x18) et translations *(+0x1C) de l'os
# k = rotations / translations de l'articulation OS_JOINT[k] du squelette (verifie au bit : 102 os sur 107).
# Os 22..26 : pas d'articulation du fichier (os 22 : translation (0, 0, 263,1)) ; os k >= 27 : k + 4,
# sauf 45 / 46 et 49 / 50 croises. Os 15, 19 (genoux) : articulations 29, 30 (memes angles que 16, 19
# mais translation (440, 0, 0) au lieu de (440, -1, 0)).
OS_JOINT = [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 4, 15, 29, 17, 21, 18, 30, 20, 22,
            None, None, None, None, None] + [k + 4 for k in range(27, 107)]
OS_JOINT[45], OS_JOINT[46], OS_JOINT[49], OS_JOINT[50] = 50, 49, 54, 53


def squelette(sk):
    """Sous-fichier 12 (squelette) -> (translations, angles) par articulation, float32 du fichier."""
    n = struct.unpack_from('<H', sk, 2)[0]
    o_t, o_r = struct.unpack_from('<2I', sk, 12)
    T = [list(struct.unpack_from('<3f', sk, o_t + 12 * i)) for i in range(n)]
    E = [list(struct.unpack_from('<3f', sk, o_r + 12 * i)) for i in range(n)]
    return T, E


def os_repos(sk, n=107):
    """Os du jeu en pose de repos : matrices (rotation d'Euler, translation de l'articulation) et
    angles, comme les tables +0x18 / +0x1C. Os sans articulation : identite."""
    T, E = squelette(sk)
    os_, eu = [], []
    for k in range(n):
        j = OS_JOINT[k] if k < len(OS_JOINT) else None
        t, e = (T[j], E[j]) if j is not None and j < len(T) else ([0.0] * 3, [0.0] * 3)
        os_.append(euler_matrix(e, [None, None, None, t + [1.0]])); eu.append(e)
    return os_, eu


def fichiers_iso(name, costume=0, iso=None):
    """Animation de la garde (coup de l'alias 1), moveset decompresse, squelette, depuis l'ISO."""
    import dr_iso as DI
    disc = DI.Disc(iso or DI.ISO)
    g = DI.group_of(name, costume); mot = disc.lz(g + DI.GROUP['moveset'])
    i = DI.u32(mot, 0xAC + 4); mv = DI.HDR + DI.u32(mot, 0x1E0) + 76 * i
    v = DI.u32(mot, mv + 8)
    if v & 0x8000: pack = disc.raw(DI.COMMON_ANIM)
    else:
        c = disc.raw(g + DI.GROUP['anims']); o, size = struct.unpack_from('<II', c, 4); pack = c[o:o + size]
    import dr_anim as A
    anim = pack[A.pack_offsets(pack)[v & 0x3FFF]:]
    lacet = not DI.u32(mot, mv + 0x3C) >> 31 if mv + 0x40 <= len(mot) else True
    model = disc.raw(g + DI.GROUP['model'])
    n = struct.unpack_from('<I', model, 0)[0]
    subs = [model[o:o + sz] for o, sz in (struct.unpack_from('<II', model, 4 + 8 * k) for k in range(n))]
    hands = mot[DI.HDR + DI.u32(mot, 0x248):]
    return dict(anim=anim, lacet=lacet, moveset=mot, skeleton=subs[12], hands=hands)


GARDE_MAINS = (2.0, 1.0)     # joueur + 0x844 / + 0x858 dans la garde du Practice (Jin et Paul)


def garde(name, frame, mains=GARDE_MAINS, costume=0, iso=None, files=None):
    """Pose locale complete d'une image de la garde, sans emulateur : os 0..21 (0x089AE50C) et doigts
    (os 51..80). Rend (os, quaternions). Les os 22..50 (aides, poses par 0x089CA440) et le cou, la tete,
    les jambes (retouches apres, 0x089B10B4) ne sont pas calcules ici."""
    F = files or fichiers_iso(name, costume, iso)
    os_, eu = os_repos(F['skeleton'])
    q = anim_pose(F['anim'], frame, F['lacet'])
    pose_locales([list(x) for x in q], os_, eu)
    table = hand_table(F['hands'])
    doigts(os_, *(hand_select(table, F['hands'], None, t) for t in mains))
    return os_, q


# ---------------------------------------------------------------- instantanes
class Snap:
    def __init__(s, path):
        s.ram = Path(str(path) + '.bin').read_bytes()
        s.reg = json.loads(Path(str(path) + '.json').read_text())
    def u32(s, a): return struct.unpack_from('<I', s.ram, a - RAM0)[0]
    def f(s, a, n=1): return list(struct.unpack_from(f'<{n}f', s.ram, a - RAM0))
    def raw(s, a, n): return s.ram[a - RAM0:a - RAM0 + n]
    def mat(s, a): return [s.f(a + 16 * c, 4) for c in range(4)]
    def gpr(s, n): return s.reg['GPR'][n]


def pack_mat(M): return b''.join(struct.pack('<4f', *c) for c in M)


def entrees_p0(S):
    """Entrees de 0x089AE50C lues dans un instantane P0 (registres a0, a1, a2)."""
    pl, qa, oa = S.gpr('a0'), S.gpr('a1'), S.gpr('a2')
    quats = [S.f(qa + 16 * k, 4) for k in range(23)]
    os_ = [S.mat(oa + 0x90 * k) for k in range(23)]
    et = S.u32(S.u32(pl + 0x8A4) + 0x18)
    euler = [S.f(et + 12 * k, 3) for k in range(23)]
    return pl, oa, quats, os_, euler


def verifie(snaps=SNAPS):
    ok = True
    for k in range(3):
        P0, P1 = Snap(snaps / f'f{k}_P0'), Snap(snaps / f'f{k}_P1')
        pl, oa, quats, os_, euler = entrees_p0(P0)
        out = pose_locales(quats, [[list(c) for c in m] for m in os_], euler)
        bad = []
        for j in range(23):
            want = P1.raw(oa + 0x90 * j, 0x40); got = pack_mat(out[j])
            if want != got:
                w = struct.unpack('<16f', want); g = struct.unpack('<16f', got)
                n = sum(1 for i in range(16) if want[4 * i:4 * i + 4] != got[4 * i:4 * i + 4])
                ulp = max(abs(struct.unpack('<i', want[4 * i:4 * i + 4])[0] - struct.unpack('<i', got[4 * i:4 * i + 4])[0]) for i in range(16))
                err = max(abs(w[i] - g[i]) for i in range(16))
                bad.append(f'os {j} : {n} mots, ecart max {err:.3g} ({ulp} ulp)')
        print(f'image {k} : 0x089AE50C ' + ('exact au bit (23 os)' if not bad else 'ECARTS ' + '; '.join(bad)))
        ok &= not bad
        # doigts : paquet de mains du moveset (joueur + 0x83C), temps + 0x844 / + 0x858, etat final en A
        A = Snap(snaps / f'f{k}_A')
        hp = A.u32(pl + 0x83C)
        pack = A.raw(hp, 0x10000)
        table = hand_table(pack)
        want_t = A.raw(A.u32(A.u32(pl + 0x8A4) + 0x38), 0xF0 * len(table))
        got_t = b''.join(struct.pack('<4f', *q) for p in table for q in p)
        hands = []
        for h in range(2):
            b = pl + 0x83C + 20 * h
            t = A.f(b + 8)[0]; ident = struct.unpack('<H', A.raw(b + 0xC, 2))[0]
            hands.append(hand_select(table, pack, A.raw(A.u32(b + 4), 0x10000), t, ident))
        fos = [A.mat(oa + 0x90 * j) for j in range(81)]
        out = doigts([[list(c) for c in m] for m in fos], hands[0], hands[1])
        nb = 0
        for j in range(51, 81):
            want = A.raw(oa + 0x90 * j, 0x40); got = pack_mat(out[j])
            nb += sum(1 for i in list(range(0, 0x30, 4)) + [0x3C] if want[i:i + 4] != got[i:i + 4])
        print(f'image {k} : table des mains {"exacte" if want_t == got_t else "ECARTS"} ({len(table)} poses), '
              f'doigts (os 51..80, mains {A.f(pl + 0x844)[0]:g} / {A.f(pl + 0x858)[0]:g}) : '
              + ('exacts au bit' if not nb else f'{nb} mots differents'))
        ok &= not nb and want_t == got_t
    return ok


J1 = 0x08B75930


def zones_j1(S, p=J1):
    """Zones memoire de J1 ecrites par la chaine : os (107 x 0x90), copie des locales, etat du regard,
    bloc +0x460, champs du joueur."""
    os_ = S.u32(S.u32(p + 0x8A4) + 0x10); cp = S.u32(S.u32(p + 0x8A4) + 0x20)
    return {'os (locales et mondes)': (os_, os_ + 107 * 0x90), 'copie +0x20': (cp, cp + 22 * 0x40),
            'etat du regard': (ST, ST + 0x54), 'bloc 0x09B78850': (SCR, SCR + 0x460),
            'joueur +0x74': (p + 0x74, p + 0x78), 'joueur +0x764..0x7B0': (p + 0x764, p + 0x7B0)}


def compare(m, A, zones):
    out = []
    for name, (lo, hi) in zones.items():
        bad = [x for x in range(lo, hi, 4) if m.b[x - RAM0:x - RAM0 + 4] != A.raw(x, 4)]
        if bad: out.append(f'{name} : {len(bad)} mots')
    return out


def verifie_monde(snaps=SNAPS):
    """Etape P1 -> A (regard, mondes, jambes, mondes finaux) puis chaine complete P0 -> A."""
    ok = True
    for k in range(3):
        P0, P1, A = (Snap(snaps / f'f{k}_{t}') for t in ('P0', 'P1', 'A'))
        m = Mem(P1.ram)
        apres_pose(m, J1); monde_final(m, J1)
        bad = compare(m, A, zones_j1(A))
        print(f'image {k} : P1 -> A (regard, mondes, jambes) ' + ('exact au bit' if not bad else 'ECARTS ' + ', '.join(bad)))
        ok &= not bad
        # depuis P0 : 0x089AE50C, doigts, puis la suite
        m = Mem(P0.ram)
        pl, oa, quats, os0, euler = entrees_p0(P0)
        out = pose_locales(quats, [[list(c) for c in mm] for mm in os0], euler)
        for j in range(23): m.setmat(oa + 0x90 * j, out[j])
        pack = P0.raw(P0.u32(pl + 0x83C), 0x10000)
        table = hand_table(pack)
        hands = [hand_select(table, pack, None, P0.f(pl + 0x83C + 20 * h + 8)[0]) for h in range(2)]
        fos = doigts([m.mat(oa + 0x90 * j) for j in range(81)], *hands)
        for j in range(51, 81): m.setmat(oa + 0x90 * j, fos[j])
        apres_pose(m, J1); monde_final(m, J1)
        bad = compare(m, A, zones_j1(A))
        print(f'image {k} : P0 -> A (chaine complete) ' + ('exact au bit' if not bad else 'ECARTS ' + ', '.join(bad)))
        ok &= not bad
    return ok


def verifie_iso(snaps=SNAPS, iso=None):
    """Chaine complete depuis l'ISO (Jin) contre les instantanes : quaternions de P0 (image = joueur
    + 0xA8 - 1), tables du jeu (+0x18, +0x1C, paquet de mains), os de P1 et doigts de A."""
    try: F = fichiers_iso('Jin', 0, iso)
    except (OSError, SystemExit) as e:
        print(f'ISO indisponible ({e}) : verification depuis l ISO sautee'); return True
    ok = True
    for k in range(3):
        P0, P1, A_ = (Snap(snaps / f'f{k}_{t}') for t in ('P0', 'P1', 'A'))
        pl, oa, quats, os0, euler = entrees_p0(P0)
        frame = int(sub(P0.f(pl + 0xA8)[0], ONE))
        q = anim_pose(F['anim'], frame, F['lacet'])
        q_ok = b''.join(struct.pack('<4f', *x) for x in q) == P0.raw(P0.gpr('a1'), 23 * 16)
        o = P0.u32(pl + 0x8A4)
        rep, eu = os_repos(F['skeleton'])
        t_ok = all(struct.pack('<3f', *rep[j][3][:3]) == P0.raw(P0.u32(o + 0x1C) + 12 * j, 12)
                   and struct.pack('<3f', *eu[j]) == P0.raw(P0.u32(o + 0x18) + 12 * j, 12)
                   for j in range(107) if OS_JOINT[j] is not None)
        h_ok = F['hands'][:0x800] == P0.raw(P0.u32(pl + 0x83C), 0x800)
        os_, _ = garde('Jin', frame, files=F)
        n1 = sum(1 for j in range(22) if pack_mat(os_[j]) != P1.raw(oa + 0x90 * j, 0x40))
        n2 = 0
        for j in range(51, 81):
            want = A_.raw(oa + 0x90 * j, 0x40); got = pack_mat(os_[j])
            n2 += sum(1 for i in list(range(0, 0x30, 4)) + [0x3C] if want[i:i + 4] != got[i:i + 4])
        print(f'image {k} (animation {frame}) depuis l ISO : quaternions {"exacts" if q_ok else "ECARTS"}, '
              f'tables os {"exactes" if t_ok else "ECARTS"}, paquet de mains {"identique" if h_ok else "DIFFERENT"}, '
              f'os 0..21 {"exacts" if not n1 else f"{n1} os differents"}, doigts {"exacts" if not n2 else f"{n2} mots differents"}')
        ok &= q_ok and t_ok and h_ok and not n1 and not n2
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', nargs='?', default='verifie', choices=['verifie'])
    ap.add_argument('--snaps', type=Path, default=SNAPS)
    ap.add_argument('--iso', type=Path, help='image de Dark Resurrection (defaut : dr_iso.ISO)')
    a = ap.parse_args()
    ok = verifie(a.snaps)
    ok = verifie_monde(a.snaps) and ok
    ok = verifie_iso(a.snaps, a.iso) and ok
    print('TOUT EXACT' if ok else 'ECARTS')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
