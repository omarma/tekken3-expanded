"""Pose d'un modele invite PS1 (converti) avec une image d'animation TTT1 (57 canaux).

- rotations locales des 18 os : formule du pont du runtime (src/tekken3_jun_motion.c,
  rotation() puis inversion des lignes 2 et 3 de l'os 0) ;
- hierarchie : parties PS1 (0x8001A05C partie -> ligne, 0x8001A074 partie -> os),
  parents des lignes principales, accessoires rattaches a leur partie (mot 6) avec
  leur rotation de repos ;
- sommets : provenance de chaque case de liste selon les regles PS1 (emprunts au
  tampon et au cache, depots G1 / G4, recopies G5), chaque sommet suit l'os de la
  ligne qui l'a produit ; les soudures moyennees gardent le sommet propre.
"""
import struct, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kazuya', 'native'))
from simulate import vlist, nvariants
from fmt import load, row, nrows, block, parse_b, prim_verts
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
P2R = [0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 24]
PART_BONE = [0, 1, 11, 12, 13, 14, 15, 16, 17, 3, 4, 5, 6, 7, 8, 9, 10, 2, 18, 19, 20, 21]
ROW_PARENT = {1: 0, 3: 0, 5: 3, 6: 5, 7: 6, 8: 3, 9: 8, 10: 9, 11: 1, 12: 11, 13: 12, 14: 13,
              15: 1, 16: 15, 17: 16, 18: 17, 19: 1}
SECONDS = (2, 4, 20, 25, 26)
_E = None

def _sin(off):
    global _E
    if _E is None: _E = open(os.path.join(ROOT, 'disc/SLUS_004.02'), 'rb').read()
    return struct.unpack_from('<h', _E, 0xe8c4 + off + 0x800)[0]   # 0x8001E8C4 dans SLUS_004.02

def rotation(angle, neg=True):
    s, c = [], []
    for i in range(3):
        a = int(angle[i]) & 0xffff
        if neg and i < 2: a = (-a) & 0xffff
        o = (a >> 3) & 0x1ffe; s.append(_sin(o)); c.append(_sin(o + 0x800))
    m12 = lambda a, b: (a * b) >> 12
    a, b = m12(c[0], c[2]), m12(c[0], s[2]); d, e = m12(s[0], c[2]), m12(s[0], s[2])
    return np.array([[m12(c[1], c[2]), m12(d, s[1]) - b, e + m12(a, s[1])],
                     [m12(c[1], s[2]), a + m12(e, s[1]), m12(b, s[1]) - d],
                     [-s[1], m12(s[0], c[1]), m12(c[0], c[1])]], dtype=float) / 4096

def bind(m):
    """Liste des lignes dessinees et, pour chacune, provenance (ligne, sommet local) de ses cases,
    plus ses triangles (indices de case)."""
    scratch = [None] * 128; cache = {}; out = {}
    order = []
    for p in range(1, 22):
        order.append(P2R[p])
        for r in SECONDS:
            if r < nrows(m) and row(m, r)[10] and row(m, r)[1] > 2 and (row(m, r)[6] & 0xff) == p and r not in order \
                    and (r in (25, 26) or {2: 1, 4: 2, 20: 17}[r] == p):
                order.append(r)
    for r in order:
        w = row(m, r)
        if not w[10] or w[1] <= 2: continue
        a = vlist(m, r)
        if not a: continue
        L = [scratch[b // 2 - 1] if 0 < b // 2 <= 128 else None for b in a['g1']]
        L += [cache.get(b // 2) for b in a['g2']]
        s0 = len(L); L += [(r, tuple(v[:3])) for v in a['verts']]
        s = s0; copies = []
        for gi, grp in enumerate(a['tails'][:5]):
            for f in grp:
                if s >= len(L): break
                idx = (f & 0xff) // 2
                if gi in (0, 3): cache[idx] = L[s]
                elif gi == 4: copies.append(((f & 0xff) // 2 - 1, s))
                s += 1
        scratch[:len(L)] = L
        for t, sl in copies:
            if 0 <= t < 128: scratch[t] = L[sl]
        tris = []
        for k, fam in enumerate(parse_b(block(m, w[1]))):
            for p_ in fam:
                vs = prim_verts(k, p_)
                tris.append(vs[:3])
                if len(vs) == 4: tris.append([vs[1], vs[3], vs[2]])
        out[r] = (list(L), tris)
    return out

def world(m, pose):
    """Transformations monde (R, T) par ligne pour une image de 57 canaux."""
    loc = {}
    for b in range(18):
        R = rotation(pose[3 + b * 3:6 + b * 3])
        if b == 0: R[1:, :] *= -1
        loc[b] = R
    W = {0: (loc[0], np.array([0., 0., 0.]))}
    def get(r):
        if r in W: return W[r]
        w = row(m, r)
        if r in ROW_PARENT:
            Rp, Tp = get(ROW_PARENT[r]); b = PART_BONE[P2R.index(r)]
            W[r] = (Rp @ loc[b], Tp + Rp @ np.array(w[3:6], dtype=float))
        elif r in (2, 4, 20):
            W[r] = get({2: 1, 4: 3, 20: 19}[r])
        elif r in (21, 22, 23, 24):
            pp = w[6] & 0xff; Rp, Tp = get(P2R[pp])
            W[r] = (Rp @ rotation(w[7:10], neg=False), Tp + Rp @ np.array(w[3:6], dtype=float))
        elif r in (25, 26):
            W[r] = get(P2R[w[6] & 0xff])
        else:
            W[r] = W[0]
        return W[r]
    for r in range(nrows(m)): get(r)
    return W
