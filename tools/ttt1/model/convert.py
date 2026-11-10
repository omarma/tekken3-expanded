#!/usr/bin/env python3
"""Convertit un modele 3DMK TTT1 (30 lignes) au format natif Tekken 3 PS1 (27 lignes).

Placement : emplacement PS1 s <- ligne TTT1 S2T[s]. Les lignes PS1 2 et 4 sont
les seconds maillages du haut du corps et du bassin (comme la 20 pour la tete),
ce qui accueille les lignes TTT1 2 et 5/6 ; les os d'accessoires 18..23 (lignes
PS1 21..26) accueillent les lignes TTT1 24..29. Rien n'est supprime.

Blocs :
- normales (mot 0), polygones (mot 1) : format identique, recopies ;
- textures (mot 2) : materiaux u32 -> u16 (palette | 0x8000 si 8 bits), UV
  replies dans la bande costume PS1 (page 6 : x 0..63 -> y, x 64..127 -> y+128) ;
- positions (mot 12, et ses variantes de main) : indices de cache doubles,
  champs de fin 16 bits -> 9 bits (drapeau = demi-poids), groupe final 2 bits vide ;
- table des poses de main (mot 13) : pointeurs recalcules.
Chaque ligne PS1 pointe (mot 12) vers le bloc de positions de la ligne TTT1
precedant la ligne de l'emplacement suivant : c'est la que le moteur les lit.

Usage : convert.py <entree TTT1 .3dm> <sortie PS1 .3dm> [<sortie .relocs> [<textures TTT1> <sortie textures>]]
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulate as SM
from fmt import *
import texpack

# Le moteur PS1 ne dessine que les parties 0..21 (boucle 0x80037A5C : slti 22),
# soit les lignes 1..24 : les tibias (TTT1 28 / 29, lecteurs du cache seulement)
# prennent les lignes 23 / 24. Les biceps (TTT1 26 / 27) vont en 25 / 26 et se
# dessinent comme SECONDS MAILLAGES de leur bras (parties 10 / 14), juste apres
# lui : leur os rigide est integre aux sommets (BAKE), leurs emprunts au tampon
# deviennent des emprunts au cache (rewire).
P2R = [0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 24]   # 0x8001a05c
BASE_S2T = {0: 0, 1: 1, 2: 2, 3: 4, 4: 6, **{s: s + 2 for s in range(5, 21)}}
BASE_SECOND = {1: 2, 2: 4, 17: 20}                      # partie -> ligne dessinee avec elle
ACC_ROWS, BAKE_ROWS = (21, 22, 23, 24), (25, 26)        # parties 18..21 ; seconds maillages
NROWS = 27
HDR = 24 + NROWS * 56

HOSTROW = {}        # ligne PS1 integree -> ligne TTT1 de l'accessoire frere hote (sinon absent)
KEEP = frozenset()  # lignes TTT1 a garder sur leur propre partie d'accessoire (convert(keep=...))

def set_layout(s2t, second, hosts=None):
    global S2T, SECOND, DRAW, TORDER, BAKED, HOSTROW
    S2T, SECOND, HOSTROW = dict(s2t), dict(second), dict(hosts or {})
    DRAW = [r for p_ in range(1, 22) for r in ([P2R[p_]] + ([SECOND[p_]] if p_ in SECOND else []))]
    TORDER = [S2T[r] for r in DRAW]                     # ordre de dessin, en lignes TTT1
    BAKED = [r for r in SECOND.values() if r in BAKE_ROWS]   # lignes PS1 a os integre

def ttt1_part_row(p):
    """Partie TTT1 -> ligne TTT1 : 1 poitrine, 2 bassin, 3..17 -> ligne p + 4,
    puis les os d'accessoires 18.. -> ligne p + 6. Les lignes 22 et 23 ne sont
    pas des parties : ce sont des maillages de tete supplementaires. Preuve :
    chez Armor King, la ligne 22 n'existe pas et la cape (24 -> 25 -> 26) a
    pour parents les parties 18 et 19."""
    return {0: 0, 1: 1, 2: 4}.get(p, p + 4 if p <= 17 else p + 6)

def ps1_part(T, p, s2t, second):
    """Partie TTT1 p -> partie PS1 qui porte sa ligne (hote si second maillage)."""
    t = ttt1_part_row(p)
    s = next((s for s, tt in s2t.items() if tt == t), None)
    if s is None: raise ValueError(f'partie TTT1 {p} (ligne {t}) non placee')
    if s in P2R: return P2R.index(s)
    return next(q for q, r in second.items() if r == s)

PART_BONE = [0, 1, 11, 12, 13, 14, 15, 16, 17, 3, 4, 5, 6, 7, 8, 9, 10, 2, 18, 19, 20, 21, 22, 23]   # 0x8001a074

def limb_map(T):
    """Os TTT1 d'accessoire (>= 18, numerote comme sa partie) -> os PS1 de la
    partie qui porte sa ligne, pour le placement courant (S2T, SECOND)."""
    out = {}
    for b in range(18, nrows(T) - 6):
        try: out[b] = PART_BONE[ps1_part(T, b, S2T, SECOND)]
        except (ValueError, StopIteration): pass
    return out

PART_OF_ROW = {r: r - 6 for r in range(24, 30)}   # lignes d'accessoires -> parties TTT1 18..

def head_extra_rows(T):
    """Maillages de tete au-dela du second (ligne 23 de Michelle, Devil, Angel) :
    meme parent et meme decalage que la tete (ligne 21). Le PS1 n'a qu'un second
    maillage par partie ; ceux-ci prennent une partie d'accessoire rattachee a la
    tete sans decalage ni rotation, dessinee juste apres elle."""
    h = row(T, 21)
    return [t for t in (23,) if t < nrows(T) and row(T, t)[10] and row(T, t)[1] > 2
            and row(T, t)[3:7] == h[3:7] and not any(row(T, t)[7:10])]

def accessory_rows(T):
    """Lignes TTT1 d'os d'accessoires qui dessinent (24.. ; 21..23 sont la tete)."""
    return [t for t in range(24, nrows(T)) if row(T, t)[10] and row(T, t)[1] > 2]

def layouts(T):
    """Placements candidats, du plus simple au plus contraint. Les accessoires
    prennent les parties 18..21 dans l'ordre ; au-dela de quatre, certains
    deviennent seconds maillages (os integre) d'une partie qui n'en a pas."""
    from itertools import combinations
    heads = head_extra_rows(T)
    # Passes, chacune essayee seulement si les precedentes ne donnent rien (les
    # placements deja valides, Kazuya, ne changent pas) :
    #  1. hote de meme parent qui suit le meme os (jamais un maillage de tete
    #     supplementaire pour une piece d'un autre parent : Baek costume 2) ;
    #  2. hote de la meme chaine rigide (os d'accessoires sans animation jusqu'au
    #     meme os anime), de preference la ligne dessinee juste avant la piece
    #     (Michelle costume 2 : la meche 28 dans la partie de la meche 27, ce qui
    #     libere une partie d'accessoire pour la piece du dos 26) ;
    #  3. dernier recours : maillage de tete supplementaire pour tout parent.
    # Pieces a garder (KEEP, convert(keep=...)) : d'abord les placements ou aucune n'est integree
    # ni n'accueille de piece integree (elle balance seule, comme la borne), puis tous.
    keep = KEEP & set(accessory_rows(T))
    for avoid in ((keep, frozenset()) if keep else (frozenset(),)):
        for mode in ('same', 'rigid', 'head'):
            yield from _layouts(T, heads, mode, avoid)

def rigid_root(T, t):
    """Os anime qui porte la ligne t et la pose de repos de t dans son repere :
    (partie TTT1, M 12 bits, p). Les os d'accessoires (parties >= 18) n'ont pas
    de canal d'animation : leur chaine est rigide jusqu'a une partie < 18. Un
    maillage de tete supplementaire suit la tete (partie 17) sans decalage."""
    if t in head_extra_rows(T): return 17, [[4096, 0, 0], [0, 4096, 0], [0, 0, 4096]], [0, 0, 0]
    ident = [[4096, 0, 0], [0, 4096, 0], [0, 0, 4096]]
    w = row(T, t); M = bake_matrix(w) if any(w[7:10]) else ident; p = list(w[3:6]); par = w[6]
    while par >= 18:
        r = ttt1_part_row(par); wr = row(T, r)
        Mr = bake_matrix(wr) if any(wr[7:10]) else ident
        M = [[sum(Mr[i][k] * M[k][j] for k in range(3)) >> 12 for j in range(3)] for i in range(3)]
        p = [(sum(Mr[i][k] * p[k] for k in range(3)) >> 12) + wr[3 + i] for i in range(3)]
        par = wr[6]
    return par, M, p

def _layouts(T, heads, mode, avoid=frozenset()):
    from itertools import combinations
    acc = heads + accessory_rows(T)
    if len(acc) > len(ACC_ROWS) + len(BAKE_ROWS):
        raise ValueError(f'{len(acc)} os d accessoires, {len(ACC_ROWS) + len(BAKE_ROWS)} places')
    for k in range(max(0, len(acc) - len(ACC_ROWS)), len(BAKE_ROWS) + 1):
        for baked in combinations([t for t in acc if t not in heads], k):
            if avoid & set(baked): continue
            parts = [t for t in acc if t not in baked]
            s2t = dict(BASE_S2T)
            mesh = lambda t: row(T, t)[10] and row(T, t)[1] > 2
            if mesh(5) and not mesh(6): s2t[4] = 5      # second maillage du bassin en ligne 5 (Baek, Ganryu)
            s2t.update(zip(ACC_ROWS, parts)); s2t.update(zip(BAKE_ROWS, baked))
            # emplacements sans accessoire : lignes TTT1 vides (rien a dessiner,
            # et la ligne qui les precede n'a pas de positions a transmettre).
            # Leur propre mot 12 (positions de la ligne suivante) n'y entre pas :
            # le mot 12 PS1 vient de la ligne de l'emplacement suivant (Michelle
            # costume 3 : lignes 25 et 28, sans maillage, portent les positions
            # de 26 et 29). A defaut de ligne entierement vide seulement.
            empty = [t for t in range(23, nrows(T)) if not row(T, t)[10]
                     and all(row(T, t)[k] <= 2 for k in (0, 1, 2, 12, 13)) and row(T, t - 1)[12] <= 2]
            empty = empty or [t for t in range(23, nrows(T)) if not row(T, t)[10]
                              and all(row(T, t)[k] <= 2 for k in (0, 1, 2, 13)) and row(T, t - 1)[12] <= 2]
            for s in ACC_ROWS + BAKE_ROWS:
                if s not in s2t:
                    if not empty: raise ValueError('aucune ligne TTT1 vide pour combler')
                    s2t[s] = empty.pop(0) if len(empty) > 1 else empty[0]
            second = dict(BASE_SECOND); hosts = {}
            placed = [t for s_, t in s2t.items() if s_ in ACC_ROWS]
            try:
                for s, t in zip(BAKE_ROWS, baked):
                    par = row(T, t)[6]
                    if any(row(T, u)[6] == PART_OF_ROW.get(t) for u in acc if u != t):
                        raise ValueError('parent d un autre accessoire')      # sa transformation se perdrait
                    q = ps1_part(T, par, s2t, second)
                    if 1 <= q <= 21 and q not in second:
                        second[q] = s; continue
                    # accessoire frere (meme parent, ou maillage de tete si le parent est la tete).
                    # Un maillage de tete supplementaire suit l'os de la tete, pas son parent
                    # TTT1 : pour une piece d'un autre parent, seulement en dernier recours
                    # (Baek costume 2 : le panneau du milieu du dos, parent poitrine, suivait
                    # la tete : dos troue, embleme coupe).
                    head_parent = ps1_part(T, par, s2t, second) == 17
                    if mode == 'rigid':
                        root = rigid_root(T, t)[0]
                        sib = [u for u in placed if u not in baked and rigid_root(T, u)[0] == root]
                        sib.sort(key=lambda u: (u > t, -u))        # la ligne dessinee juste avant d'abord
                    else:
                        sib = [u for u in placed if u not in baked and
                               ((row(T, u)[6] == par and (u not in heads or mode == 'head')) or
                                (u in heads and head_parent))]
                    if mode == 'head' and not any(u in heads and not head_parent for u in sib):
                        raise ValueError('deja essaye sans hote de tete')
                    sib = [u for u in sib if P2R.index(next(k for k, v in s2t.items() if v == u)) not in second
                           and u not in avoid]
                    if not sib: raise ValueError('aucun hote')
                    h = sib[0]; hq = P2R.index(next(k for k, v in s2t.items() if v == h))
                    second[hq] = s; hosts[s] = h
            except (ValueError, StopIteration):
                continue
            yield s2t, second, hosts

set_layout({**BASE_S2T, 21: 24, 22: 25, 23: 28, 24: 29, 25: 26, 26: 27},
           {**BASE_SECOND, 10: 25, 14: 26})             # Kazuya, pour les outils qui importent ce module

def pack_fields(vals, bits):
    per = {9: 3, 2: 16}[bits]; out = struct.pack('<I', len(vals))
    for i in range(0, len(vals), per):
        w = 0
        for k, v in enumerate(vals[i:i + per]): w |= (v & ((1 << bits) - 1)) << (bits * k)
        out += struct.pack('<I', w)
    return out

def pad4(b): return b + b'\0' * (-len(b) % 4)

# Allocation des entrees de cache PS1 (0..127) par intervalle de vie, comme des
# registres : une entree TTT1 est vivante de son depot a sa derniere lecture dans
# l'ordre de dessin. Les depots jamais relus vont dans l'entree 0 (poubelle).
ALLOC = {}          # (temps, entree TTT1, 'r'|'w') -> entree PS1
G2_READS = {}       # evenement de lecture G2 -> (ligne TTT1 lectrice, rang dans G2)
DROPPED = set()     # soudures G2 retirees : (ligne TTT1 lectrice, rang dans G2)
SLOTMAP = {}        # ligne TTT1 lectrice -> {ancien emplacement: nouveau} apres retrait
CUR_T = [0]         # temps de la ligne en cours de conversion
LEG_ROWS = range(3, 11)   # lignes PS1 du bassin et des deux jambes (parties 2..8) : faces doubles, voir double_sided
WELDS = {}          # ligne TTT1 lectrice -> anciens emplacements dont la soudure (poids 12/4, ...) devient 8/8
COPIED = []         # soudures devenues copies : (ligne TTT1 lectrice, groupe, rang dans le groupe, poids)
def natural_prev(t):
    """Ligne TTT1 dont la liste occupait le tampon avant t dans l'ordre TTT1."""
    return max((x for x in TORDER if x < t), default=None)

def list_len(a):
    return len(a['g1']) + len(a['g2']) + len(a['verts'])

def rewired(T, t):
    """Variantes de positions du lecteur TTT1 t. Si d'autres lignes sont
    dessinees entre sa ligne TTT1 precedente et lui (ou si celle-ci passe apres
    lui), les emprunts au tampon (g1) aux cases qu'elles ecrasent sont reroutes
    vers l'entree de cache que la ligne precedente y avait copiee (g2). Les
    autres cases du tampon (permanent) restent lisibles."""
    vs = SM.variants(block(T, row(T, t - 1)[12]), True)
    nat = natural_prev(t)
    if nat is None or not vs[0]['g1']: return vs
    i_t = TORDER.index(t)
    if nat in TORDER[:i_t]:
        between = TORDER[TORDER.index(nat) + 1:i_t]
        if not between: return vs
        # Cases ecrasees : la liste de chaque ligne intercalee, et les cases ou
        # elle copie des sommets (groupe 4, Michelle costume 2, Kunimitsu
        # costume 3) ; les autres restent lisibles. Lues sur la liste brute : le
        # reroutage ne change ni sa longueur ni le groupe 4, et rewired(x) pourrait
        # redemander t (accessoires dessines a l'envers de TTT1, 25 avant 24 :
        # recursion sans fin chez Hwoarang Poing et Julia Pied).
        over = set()
        for x in between:
            for rx in SM.variants(block(T, row(T, x - 1)[12]), True) if row(T, x - 1)[12] > 2 else []:
                over |= set(range(list_len(rx)))
                over |= {(f & 0xff) // 2 - 1 for f in rx['tails'][4]}
    else:
        over = set(range(128))                           # la ligne precedente n'est pas encore dessinee
    pa = rewired(T, nat)[0]; n1p = len(pa['g1']); pp = pa.get('perm', {})
    out = []
    for a in vs:
        ents, keep, moved = [], [], []
        for j, b in enumerate(a['g1']):
            k = b // 2 - 1
            if k not in over: keep.append(j); continue
            k = pp.get(k, k)                             # case de la liste precedente apres sa propre permutation
            if not (n1p <= k < n1p + len(pa['g2'])): raise ValueError(f'ligne {t} : emprunt {b // 2 - 1} ecrase et hors cache')
            ents.append(pa['g2'][k - n1p]); moved.append(j)
        if not ents: out.append(a); continue
        g1 = list(a['g1'])
        a = dict(a); a['g2'] = ents + list(a['g2']); a['g1'] = [g1[j] for j in keep]
        # Emprunts mixtes : ceux qui restent au tampon gardent la tete de la
        # liste, les autres passent au cache juste apres ; convert_positions
        # compose cette permutation dans SLOTMAP (polygones, liste suivante).
        perm = {j: i for i, j in enumerate(keep + moved) if i != j}
        if perm: a['perm'] = perm
        out.append(a)
    return out

_SIN = None
def bake_matrix(w):
    """Rotation de repos (mots 7..9) comme accessory_rotation() : table de
    sinus du jeu a 0x8001e8c4, calcul 12 bits."""
    global _SIN
    if _SIN is None:
        E = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../disc/SLUS_004.02'), 'rb').read()
        _SIN = lambda off: struct.unpack_from('<h', E, 0x8001e8c4 + off - 0x80010000 + 0x800)[0]
    m12 = lambda a, b: (a * b) >> 12
    sn, cs = [], []
    for ang in w[7:10]:
        o = ((ang & 0xffffffff) >> 3) & 0x1ffe; sn.append(_SIN(o)); cs.append(_SIN(o + 0x800))
    a, b = m12(cs[0], cs[2]), m12(cs[0], sn[2]); d, e = m12(sn[0], cs[2]), m12(sn[0], sn[2])
    return [[m12(cs[1], cs[2]), m12(d, sn[1]) - b, e + m12(a, sn[1])],
            [m12(cs[1], sn[2]), a + m12(e, sn[1]), m12(b, sn[1]) - d],
            [-sn[1], m12(sn[0], cs[1]), m12(cs[0], cs[1])]]

def bake(T, t, a, host=None):
    """Sommets propres du lecteur t exprimes dans le repere de sa partie parente,
    ou de l'accessoire frere `host` (meme parent) : v' = Mh^T (Mt v + pt - ph)."""
    w = row(T, t); M = bake_matrix(w); a = dict(a)
    vs = [[(sum(M[i][k] * v[k] for k in range(3)) >> 12) + w[3 + i] for i in range(3)] for v in a['verts']]
    if host is not None:
        # Repere de l'hote, par la chaine rigide commune (meme parent : Mh, ph de
        # sa ligne ; maillage de tete supplementaire : identite).
        _, Mt, pt = rigid_root(T, t); _, Mh, ph = rigid_root(T, host)
        vs = [[(sum(Mt[i][k] * v[k] for k in range(3)) >> 12) + pt[i] for i in range(3)] for v in a['verts']]
        vs = [[sum(Mh[k][i] * (v[k] - ph[k]) for k in range(3)) >> 12 for i in range(3)] for v in vs]
    a['verts'] = [tuple(v) + (0,) for v in vs]
    return a

def plan_cache(T, order):
    from collections import defaultdict
    ev = []; times = {}; tm = 0
    for t in order:
        if row(T, t - 1)[12] <= 2: continue
        vs = rewired(T, t)
        times[t] = tm
        for a in vs:
            for e in a['g2']: ev.append((tm, e, 'r'))
            for gi, grp in enumerate(a['tails'][:5]):
                for j, f in enumerate(grp):
                    e = f & 0xff
                    if gi == 0: ev += [(tm + 1, e, 'r'), (tm + 1.5, e, 'x')]   # G1 : lit puis reecrit la MEME entree
                    elif gi == 1:
                        ev.append((tm + 1, e, 'r'))
                        if len(vs) == 1: G2_READS[(tm + 1, e, 'r')] = (t, j)
                    elif gi == 3: ev.append((tm + 1.5, e, 'w'))
        tm += 2
    byE = defaultdict(list)
    for x in sorted(set(ev)): byE[x[1]].append(x)
    ranges = []                                   # (debut, fin, entree, [evenements])
    for e, L in byE.items():
        cur = None
        for t_, _, k in L:
            if k == 'w':
                if cur: ranges.append(cur)
                cur = [t_, t_, e, [(t_, e, 'w')]]
            elif k == 'x':                              # reecriture G1 : prolonge l'intervalle courant
                if cur is None: cur = [t_, t_, e, []]
                cur[1] = t_; cur[3].append((t_, e, 'x'))
            else:
                if cur is None: cur = [-1, t_, e, []]
                cur[1] = t_; cur[3].append((t_, e, 'r'))
        if cur: ranges.append(cur)
    # Trop d'entrees vivantes au meme instant : on retire des soudures de lissage
    # (lecture G2 unique, piece hors mains) couvrant le pic, sommet garde propre.
    def peak_of(rs):
        pts = sorted(set(x for r in rs for x in r[:2]))
        return max(((sum(1 for r in rs if r[0] <= p_ <= r[1]), p_) for p_ in pts), default=(0, 0))
    live = [rg for rg in ranges if any(x[2] == 'r' for x in rg[3])]
    # L'entree 0 est interdite : le moteur recharge un mot des qu'il ne reste que
    # des zeros, un champ nul en fin de mot desynchronise tout le bloc (gel en jeu).
    while peak_of(live)[0] > 127:
        p_ = peak_of(live)[1]
        cands = [rg for rg in live if rg[0] <= p_ <= rg[1] and len([x for x in rg[3] if x[2] == 'r']) == 1
                 and G2_READS.get([x for x in rg[3] if x[2] == 'r'][0])]
        if not cands: raise ValueError('plus de 128 entrees de cache vivantes, rien a retirer')
        rg = max(cands, key=lambda r: r[1] - r[0])
        rd = [x for x in rg[3] if x[2] == 'r'][0]
        DROPPED.add(G2_READS[rd]); live.remove(rg)
        for x in rg[3]:
            if x[2] == 'w': ranges.append([x[0], x[0], rg[2], [x]])     # depot devenu mort
        ranges.remove(rg)
    free_at = {}                                  # registre -> fin d'occupation
    dead = [rg for rg in ranges if not any(x[2] == 'r' for x in rg[3])]
    for rg in sorted(live, key=lambda r: r[0]):
        reg = next((r for r in range(1, 128) if free_at.get(r, -2) < rg[0]), None)
        if reg is None: raise ValueError('plus de 128 entrees de cache vivantes')
        free_at[reg] = rg[1]
        for x in rg[3]: ALLOC[x] = reg
    # depots jamais relus : n'importe quel registre libre a cet instant
    occ = {}
    for rg in live:
        occ.setdefault(ALLOC[rg[3][-1]], []).append((rg[0], rg[1]))
    for rg in dead:
        t_ = rg[0]
        reg = next((r for r in range(1, 128) if all(not (a <= t_ <= b) for a, b in occ.get(r, []))), None)
        if reg is None: continue          # cache plein : depot jamais relu, retire (convert_positions)
        for x in rg[3]: ALLOC[x] = reg
    return times

def ps1_entry(e, kind='r', dt=0):
    return ALLOC[(CUR_T[0] + dt, e, kind)]

def remap_slot_byte(b, mp):
    """octet d'emprunt au tampon (emplacement = b/2 - 1) renumerote."""
    sl = b // 2 - 1
    return 2 * (mp[sl] + 1) if sl in mp else b

HALF = dict(c={}, s={}, moved=0)   # contenu moitie (depot marque) ou entier, par entree TTT1

def convert_positions(a, reader=None, prev_reader=None, half=None, track=False):
    """Une liste de positions TTT1 (dict parse_a + tails) -> octets PS1.

    Regle PS1 (0x80036F2C..0x800370E0) : lecture marquee = propre/2 + stocke,
    depot marque = propre/2. Une soudure marquee n'est donc juste que si la
    valeur stockee est une MOITIE. Quand la valeur lue est entiere (sommet de la
    liste precedente, depot plein, reecriture G1), le sommet devient une simple
    copie : emprunt au tampon (g1) ou au cache (g2), sans calcul de soudure."""
    a = dict(a); tails = [list(g) for g in a['tails']]; verts = list(a['verts'])
    hc, hs = half if half else (HALF['c'], HALF['s'])
    pm = SLOTMAP.get(prev_reader, {})
    n1, n2 = len(a['g1']), len(a['g2']); s0 = n1 + n2
    g1 = [remap_slot_byte(b, pm) for b in a['g1']]
    g2 = [2 * ps1_entry(e) for e in a['g2']]
    drops = set(j for (r_, j) in DROPPED if r_ == reader)
    fate = {}; v = 0; new_c = dict(hc); copies = {}; halved = []
    for gi, grp in enumerate(tails[:5]):
        for j, f in enumerate(grp):
            low = f & 0xff; w = (f >> 8) & 0x1f
            if track and w not in (0, 8, 16): WELDS.setdefault(reader, set()).add(s0 + v)
            dead = gi == 3 and (CUR_T[0] + 1.5, low, 'w') not in ALLOC   # depot jamais relu, cache plein
            if dead: fate[v] = ('drop',)
            elif gi == 1 and j in drops: fate[v] = ('drop',)
            elif gi in (0, 1) and not hc.get(low, False): fate[v] = ('g2', 2 * ps1_entry(low, 'r', 1))
            elif gi == 2 and not hs.get(low, False): fate[v] = ('g1', remap_slot_byte(low, pm))
            if track and v in fate and fate[v][0] != 'drop': COPIED.append((reader, gi, j, w))
            if gi == 0: new_c[low] = False                 # reecriture G1 (ou copie) : valeur entiere
            elif gi == 3 and not dead: new_c[low] = w < 16
            elif gi == 4: copies[low] = w < 16
            if (gi == 4 or (gi == 3 and not dead)) and w < 16: halved.append(2 * (s0 + v + 1))   # depot marque : la case propre devient moitie
            v += 1
    if track:
        # tampon permanent de 128 cases : la liste n'ecrase que ses propres cases,
        # le reste garde son etat (copies moitie deposees par des lignes anterieures)
        n_list = s0 + len(verts)
        for k in [k for k in hs if k // 2 - 1 < n_list]: del hs[k]
        hc.clear(); hc.update(new_c)
        for k in halved: hs[k] = True
        hs.update(copies)
        HALF['moved'] += sum(1 for x in fate.values() if x[0] != 'drop')
    add1 = [fate[k][1] for k in sorted(fate) if fate[k][0] == 'g1']
    add2 = [fate[k][1] for k in sorted(fate) if fate[k][0] == 'g2']
    n1n, n2n = n1 + len(add1), n2 + len(add2); s0n = n1n + n2n
    mp = {}
    for j in range(n2): mp[n1 + j] = n1n + j
    k1 = k2 = 0
    for k in sorted(fate):
        if fate[k][0] == 'g1': mp[s0 + k] = n1 + k1; k1 += 1
        elif fate[k][0] == 'g2': mp[s0 + k] = n1n + n2 + k2; k2 += 1
    keep = [k for k in range(len(verts)) if k not in fate]
    tail_end = [k for k in sorted(fate) if fate[k][0] == 'drop']
    for i, k in enumerate(keep + tail_end): mp[s0 + k] = s0n + i
    mp = {o: n for o, n in mp.items() if o != n}
    if mp: SLOTMAP[reader] = mp
    verts = [verts[k] for k in keep + tail_end]
    g1 += add1; g2 += add2
    # Le moteur remplit la liste SUR PLACE : l'emprunt j ecrit la case j. Un
    # emprunt qui lit une case k < j lit donc une case deja reecrite. TTT1 evite
    # ce cas ; la renumerotation de la liste precedente peut le recreer : on
    # reordonne alors les emprunts (cases lues croissantes) et on renumerote.
    if any(b // 2 - 1 < j for j, b in enumerate(g1)):
        order = sorted(range(len(g1)), key=lambda j: g1[j] // 2 - 1)
        g1 = [g1[j] for j in order]
        if any(b // 2 - 1 < j for j, b in enumerate(g1)):
            raise ValueError(f'ligne {reader} : emprunts au tampon croises, aucun ordre sur place')
        pos = {old: new for new, old in enumerate(order)}
        full = {o: mp.get(o, o) for o in range(s0 + len(a['verts']))}
        full = {o: (pos[n] if n < len(g1) else n) for o, n in full.items()}
        mp = {o: n for o, n in full.items() if o != n}
        if mp: SLOTMAP[reader] = mp
        else: SLOTMAP.pop(reader, None)
    perm = a.get('perm')                              # emprunts mixtes reroutes (rewired)
    if perm:
        full = {o: mp.get(perm.get(o, o), perm.get(o, o)) for o in range(s0 + len(a['verts']))}
        mp = {o: n for o, n in full.items() if o != n}
        if mp: SLOTMAP[reader] = mp
        else: SLOTMAP.pop(reader, None)
    if any(b > 255 for b in g1 + g2): raise ValueError('entree de cache > 127')
    head = 2 * (1 + len(g1) + len(g2))
    out = struct.pack('<I', head)
    out += struct.pack('<I', len(g1)) + pad4(bytes(g1))
    out += struct.pack('<I', len(g2)) + pad4(bytes(g2))
    out += struct.pack('<I', len(verts)) + b''.join(struct.pack('<4h', *v_[:3], 0) for v_ in verts)
    v = 0
    for gi, grp in enumerate(tails[:5]):
        vals = []
        for f in grp:
            low = f & 0xff; w = (f >> 8) & 0x1f
            if v in fate: v += 1; continue
            v += 1
            if gi in (0, 1): byte = 2 * ps1_entry(low, 'r', 1)   # G1 : lecture puis depot, meme entree
            elif gi == 3: byte = 2 * ps1_entry(low, 'w', 1.5)
            elif gi == 2: byte = remap_slot_byte(low, pm)          # reprise au tampon
            else: byte = remap_slot_byte(low, mp)                  # copie vers le tampon
            if byte > 255: raise ValueError('indice de cache > 127')
            flag = 1 if gi in (0, 1, 2) else (1 if w < 16 else 0)  # lecture : moitie ; depot partiel : moitie
            vals.append((flag << 8) | byte)
        out += pack_fields(vals, 9)
    out += pack_fields([], 2)
    return out

def ps1_uv(page, clut, u, v):
    """UV TTT1 -> (materiau PS1, UV u | v << 8 dans la bande costume), apres rangement."""
    mode, cl, X, sub, Y = texpack.remap_uv(page, clut, u, v)   # images hors repli deplacees
    ppw = 4 >> mode
    pm = (cl & 0x7fff) | (0x8000 if mode == 1 else 0)
    Yf = Y + (128 if X >= 64 else 0); Xf = X % 64                # repli de la bande costume
    return pm, ((Xf * ppw + sub) & 255) | ((Yf & 255) << 8)

def convert_texture(c):
    prims = parse_c_ttt1(c)
    mats = []; uvs = []; stream = []
    fam_counts = [0, 0, 0, 0]
    for k, mat, uv in prims:
        page, clut = mat >> 16, mat & 0xffff
        idx = []; pm = None
        for u, v in uv:
            pm, e = ps1_uv(page, clut, u, v)
            if e not in uvs: uvs.append(e)
            idx.append(uvs.index(e))
        if pm not in mats: mats.append(pm)
        stream.append((k, mats.index(pm), idx)); fam_counts[k] += 1
    if len(uvs) > 255 or len(mats) > 255: raise ValueError('trop d UV ou de materiaux')
    uvoff = 2 + 2 * len(mats)
    body = struct.pack('<H', uvoff) + b''.join(struct.pack('<H', m) for m in mats)
    body += struct.pack('<H', 2 + 2 * len(uvs)) + b''.join(struct.pack('<H', e) for e in uvs)
    for k in range(4):
        body += bytes([fam_counts[k]])
        for kk, mi, idx in stream:
            if kk == k: body += bytes([mi] + idx)
    return pad4(body)

DOUBLE_SIDED = 0x01000000   # bit 24 du mot 0 (triangles, 0x8003739C) ou du mot 1 (quadrilateres, 0x8003749C) : dessine meme de dos

def double_sided(b, welds):
    """Marque double face les polygones dont un sommet est une soudure approximee. Le PS1 ne sait
    melanger qu'a parts egales : une soudure 12/4 devenue 8/8 deplace le sommet, et sur une jambe
    pliee elle retourne la face ; le moteur ecarte les faces de dos (NCLIP <= 0), d'ou un trou derriere
    le genou de Lee. Aucun polygone n'utilise ce bit dans les modeles importes."""
    b = bytearray(b); p = 0
    for k in range(4):
        n = struct.unpack_from('<I', b, p)[0]; p += 4; st = 12 if k == 3 else 8
        for i in range(n):
            w = struct.unpack_from('<I', b, p + i * st)[0]
            sh = (0, 7, 14) if k in (0, 2) else (0, 7, 14, 23)
            if any(((w >> s) & 0x1fc) // 4 in welds for s in sh):
                at = p + i * st + (4 if k in (1, 3) else 0)      # le mot 0 d'un quadrilatere porte le 4e sommet jusqu'au bit 31
                struct.pack_into('<I', b, at, struct.unpack_from('<I', b, at)[0] | DOUBLE_SIDED)
        p += n * st
    return bytes(b)

def remap_prims(b, mp):
    if not mp: return b
    b = bytearray(b); p = 0
    for k in range(4):
        n = struct.unpack_from('<I', b, p)[0]; p += 4; st = 12 if k == 3 else 8
        for i in range(n):
            w = struct.unpack_from('<I', b, p + i * st)[0]
            for sh in ((0, 7, 14) if k in (0, 2) else (0, 7, 14, 23)):
                sl = ((w >> sh) & 0x1fc) // 4
                if sl in mp: w = (w & ~(0x1fc << sh)) | ((mp[sl] * 4) << sh)
            struct.pack_into('<I', b, p + i * st, w & 0xffffffff)
        p += n * st
    return bytes(b)

def unplaced(T):
    """Lignes TTT1 qui portent un maillage mais n'ont aucune place PS1 (ex. le
    troisieme maillage de tete de Michelle, ligne 23) : perdues, a signaler."""
    return [t for t in range(nrows(T)) if row(T, t)[10] and row(T, t)[1] > 2 and t not in S2T.values()
            and t not in FOLDED and t not in MERGED and t not in MOVED]

# Soudures sur un sommet entier. TTT1 soude un sommet propre V a la valeur lue (case du tampon,
# groupe 3, ou entree du cache, groupe 2) avec les poids 16 (valeur entiere) et w :
# (16 P + w V) / (16 + w). Le PS1 ne sait que propre/2 + valeur stockee, juste si la valeur est une
# moitie : convert_positions en fait une copie de P, le sommet suit l'autre os en entier (haut des
# cuisses de Michelle costume 3 : l'ourlet du short reste sur le bassin). Ici, avant la conversion,
# la ligne qui a ecrit P recoit un sommet auxiliaire (memes coordonnees) qui en depose la moitie
# (groupe 4, poids 8) dans une entree libre du cache, et le lecteur lit cette moitie (groupe 2 ; un
# lecteur du tampon y passe) : soudure 8/8. Par le cache seulement : le tampon n'a que 110 cases
# (0x80036CAC : SXY en 0x1F800000 + 4 k, SZ en 0x1F8001B8 + 2 k ; au-dela, la case 110 ecrase les
# profondeurs, d'ou des pointes en jeu) et les hanches les occupent deja. Seulement si
# w >= HALF_WELD_MIN : la part de P est 16/(16+w), 76 % pour w = 5, a mi-chemin de la copie (100 %)
# et de la moitie ; la moitie seule fait plier le short (entrejambe et ourlet : poids 5). En dessous,
# la copie est plus juste.
HALF_WELDS = True
BUFFER_TOP = 109    # derniere case du tampon (110 cases), aussi la plus haute des modeles TTT1
HALF_WELD_MIN = 5
HALF_DONE = []      # soudures rendues : (ligne ecrivain, ligne lectrice, groupe, poids)
HALF_SKIPPED = []   # soudures w >= HALF_WELD_MIN restees copies : (raison, ligne lectrice, poids)

def list_bytes(a):
    """Liste de positions TTT1 (parse_a + tails) -> octets, l'inverse de SM.variants."""
    out = struct.pack('<I', 2 * (1 + len(a['g1']) + len(a['g2'])))
    for g in (a['g1'], a['g2']):
        out += struct.pack('<I', len(g)) + pad4(bytes(g))
    out += struct.pack('<I', len(a['verts'])) + b''.join(struct.pack('<4h', *v) for v in a['verts'])
    for gi, g in enumerate(a['tails']):
        bits, per = (16, 2) if gi < 5 else (8, 4)
        out += struct.pack('<I', len(g))
        for i in range(0, len(g), per):
            w = 0
            for k, v in enumerate(g[i:i + per]): w |= v << (bits * k)
            out += struct.pack('<I', w)
    return out

def rebuild(T, new, added=None, words=None):
    """Modele TTT1 avec des blocs remplaces ({decalage: octets}) ou ajoutes ({(ligne, mot): octets}),
    et des mots de ligne poses ({(ligne, mot): valeur, ou ('bloc', ancien decalage)}), decalages des
    lignes recalcules. Les blocs a variantes (tables de poses, mot 13) ne sont jamais remplaces par un
    bloc d'une autre taille : leurs pointeurs internes restent justes avec le decalage du bloc."""
    so = offsets(T); out = bytearray(T[:so[0]]); at = {}
    for o in so[:-1]:
        at[o] = len(out); out += pad4(new.get(o, block(T, o)))
    extra = {}
    for key, b in (added or {}).items():
        extra[key] = len(out); out += pad4(b)
    for r in range(nrows(T)):
        w = list(row(T, r))
        for k in (0, 1, 2, 12, 13):
            if w[k] > 2: w[k] = at[w[k]]
        for (rr, k), v in (words or {}).items():
            if rr == r: w[k] = at[v[1]] if isinstance(v, tuple) else v
        for (rr, k), o in extra.items():
            if rr == r: w[k] = o
        struct.pack_into('<14i', out, 24 + r * 56, *w)
        if w[13] > 2:
            p = w[13]; old = row(T, r)[13]; n = len(block(T, old)) // 4
            for i in range(n):
                e = struct.unpack_from('<I', out, p + 4 * i)[0]
                o = max(x for x in so[:-1] if x <= e); struct.pack_into('<I', out, p + 4 * i, at[o] + e - o)
    return bytes(out)

# Soudures a poids libres. TTT1 soude au genou (et aux autres articulations) un sommet propre V du
# lecteur a la case du tampon ou l'ecrivain a depose son sommet U avec les poids w et 16 - w :
# (pw U + w V) / 16 a l'ecran. Le PS1 ne sait que V/2 + U/2 : 14/2 devenu 8/8 tirait le mollet de
# Devil de 6/16 vers la cuisse (B145, 45 a 78 unites), 12/4 le poussait de 4/16 vers le tibia. Si
# le lecteur est l'enfant de l'ecrivain (ou son parent), l'articulation est l'origine de l'enfant :
# le point o (decalage de l'enfant) dans le repere du parent, 0 dans le sien. Mettre chaque sommet a
# l'echelle autour d'elle, enfant v -> v w / 8, parent u -> o + (u - o) pw / 8, rend la soudure 8/8
# exacte dans toute pose (les deux os passent par o). Seulement pour un depot lu par ce seul lecteur,
# dans l'ordre TTT1 comme dans l'ordre PS1, et qu'aucun polygone de l'ecrivain ne dessine.
EXACT_WELDS = True
EXACT_DONE = []     # soudures rendues exactes : (ligne lectrice, ligne ecrivain, poids lecteur, poids ecrivain)

def exact_welds(T, order):
    """Modele TTT1 ou les soudures du groupe 3 a poids complementaires autres que 8/8 sont mises a
    l'echelle autour de l'articulation et passent a 8/8. `order` : ordre de dessin PS1 (TORDER)."""
    lists = {r: SM.variants(block(T, row(T, r - 1)[12]), True) for r in range(1, nrows(T)) if row(T, r - 1)[12] > 2}
    one = {r: dict(vs[0], tails=[list(g) for g in vs[0]['tails']], verts=[list(v) for v in vs[0]['verts']])
           for r, vs in lists.items() if len(vs) == 1}
    def bounds(a):
        b = [0]
        for g in a['tails'][:5]: b.append(b[-1] + len(g))
        return b
    def reads(order):
        """Lectures du tampon : (lecteur, groupe 3 ou 'g1', rang) -> ecrivain (ligne, sommet propre,
        poids, rang dans le groupe 5) ou None (case de liste, ligne a poses)."""
        cur, out = {}, {}
        for r in order:
            if r not in one:
                for p in range(max(len(a['g1']) + len(a['g2']) + len(a['verts']) for a in lists[r])): cur[p] = None
                continue
            a = one[r]; b = bounds(a)
            for j, f in enumerate(a['tails'][2]): out[(r, 2, j)] = cur.get((f & 0xff) // 2 - 1)
            for j, x in enumerate(a['g1']): out[(r, 'g1', j)] = cur.get(x // 2 - 1)
            for p in range(len(a['g1']) + len(a['g2']) + len(a['verts'])): cur[p] = None
            for j, f in enumerate(a['tails'][4]): cur[(f & 0xff) // 2 - 1] = (r, b[4] + j, (f >> 8) & 0x1f, j)
        return out
    rt, rp = reads(sorted(lists)), reads([r for r in order if r in lists])
    readers = {}
    for k, wr in rt.items():
        if wr: readers.setdefault(wr[:2], []).append(k)
    def drawn(r, i):                            # sommet propre i de la ligne r dessine par un de ses polygones
        a = one[r]; s = len(a['g1']) + len(a['g2']) + i
        return any(s in prim_verts(k, p) for k, fl in enumerate(parse_b(block(T, row(T, r)[1]))) for p in fl) if row(T, r)[1] > 2 else False
    part = lambda r: next((p for p in range(nrows(T)) if ttt1_part_row(p) == r), None)
    changed = set()
    for (r, g, j), wr in rt.items():
        if g != 2 or not wr or rp.get((r, g, j)) != wr: continue
        a = one[r]; i = bounds(a)[2] + j; w = (a['tails'][2][j] >> 8) & 0x1f
        x, u, pw, j5 = wr
        if w in (0, 8, 16) or pw + w != 16 or readers[wr[:2]] != [(r, g, j)] or drawn(x, u): continue
        R, W = row(T, r), row(T, x)
        if R[6] == part(x): o, (cs, ps), (cw, pp) = R[3:6], (w, False), (pw, True)        # lecteur enfant
        elif W[6] == part(r): o, (cs, ps), (cw, pp) = W[3:6], (w, True), (pw, False)      # ecrivain enfant
        else: continue
        scale = lambda v, c, parent: [round(o[k] + (v[k] - o[k]) * c / 8) if parent else round(v[k] * c / 8) for k in range(3)]
        V, U = scale(a['verts'][i], cs, ps), scale(one[x]['verts'][u], cw, pp)
        if any(abs(c) > 32767 for c in V + U): continue
        a['verts'][i][:3], one[x]['verts'][u][:3] = V, U
        a['tails'][2][j] = (a['tails'][2][j] & ~0x1f00) | 8 << 8
        one[x]['tails'][4][j5] = (one[x]['tails'][4][j5] & ~0x1f00) | 8 << 8
        changed |= {r, x}; EXACT_DONE.append((r, x, w, pw))
    new = {}
    for r in changed:
        o = row(T, r - 1)[12]; bts = list_bytes(dict(one[r], verts=[tuple(v) for v in one[r]['verts']]))
        new[o] = bts + block(T, o)[len(bts):]
    return rebuild(T, new) if new else T

def half_welds(T, order):
    """Modele TTT1 ou les soudures que convert_positions vient de changer en copies (COPIED, passe
    a blanc sur T) lisent une moitie deposee dans le cache par un sommet auxiliaire. `order` : ordre
    de dessin PS1 (TORDER) ; une case deplacee doit survivre dans cet ordre et dans l'ordre TTT1."""
    lists = {r: SM.variants(block(T, row(T, r - 1)[12]), True) for r in range(1, nrows(T)) if row(T, r - 1)[12] > 2}
    lists = {r: [dict(a, tails=[list(g) for g in a['tails']], g1=list(a['g1'])) for a in vs] for r, vs in lists.items()}
    def bounds(a):                              # debuts des groupes 1..5 puis des sommets sans groupe
        b = [0]
        for g in a['tails'][:5]: b.append(b[-1] + len(g))
        return b
    def group_of(a, i):
        b = bounds(a); g = next((k for k in range(5) if b[k] <= i < b[k + 1]), 5)
        return g, (a['tails'][g][i - b[g]] if g < 5 else None)
    def simulate(order):
        """Lectures (temps, lecteur, variante, 'g1'|groupe, rang, case, ecrivain) et vies des valeurs du
        tampon. Ecrivain : (ligne, sommet propre) pour une case de sa liste, (ligne, sommet, poids) pour
        un depot (groupe 5 au tampon, groupe 4 au cache), None pour un emprunt ou une reecriture."""
        cur, ccur, reads, life = {}, {}, [], {}
        for tm, r in enumerate(order):
            for vi, a in enumerate(lists[r]):
                for j, b in enumerate(a['g1']):
                    reads.append((tm, r, vi, 'g1', j, b // 2 - 1, cur.get(b // 2 - 1)))
                for j, f in enumerate(a['tails'][2]):
                    reads.append((tm, r, vi, 2, j, (f & 0xff) // 2 - 1, cur.get((f & 0xff) // 2 - 1)))
                for j, f in enumerate(a['tails'][1]):
                    reads.append((tm, r, vi, 1, j, f & 0xff, ccur.get(f & 0xff)))
            for s in {x[5] for x in reads if x[0] == tm and x[3] != 1}:
                if s in life: life[s][-1][1] = tm
            a = lists[r][0]; s0 = len(a['g1']) + len(a['g2']); b = bounds(a)
            for p in range(max(len(v['g1']) + len(v['g2']) + len(v['verts']) for v in lists[r])):
                cur[p] = (r, p - s0) if p >= s0 else None; life.setdefault(p, []).append([tm, tm])
            for j, f in enumerate(a['tails'][3]): ccur[f & 0xff] = (r, b[3] + j, (f >> 8) & 0x1f)
            for f in a['tails'][0]: ccur[f & 0xff] = None
            for j, f in enumerate(a['tails'][4]):
                t = (f & 0xff) // 2 - 1; cur[t] = (r, b[4] + j, (f >> 8) & 0x1f); life.setdefault(t, []).append([tm, tm])
        return reads, life
    orders = [sorted(lists), [r for r in order if r in lists]]
    sims = [simulate(o) for o in orders]
    times = [{r: i for i, r in enumerate(o)} for o in orders]
    used = {f & 0xff for vs in lists.values() for a in vs for gi in (0, 1, 3) for f in a['tails'][gi]}
    used |= {b for vs in lists.values() for a in vs for b in a['g2']}
    free_entries = [e for e in range(255, 0, -1) if e not in used]
    want = {}                                   # (ecrivain, sommet propre) -> [(lecteur, groupe, rang, poids)]
    for r, gi, j, w in COPIED:
        if w < HALF_WELD_MIN: continue
        skip = lambda why: HALF_SKIPPED.append((why, r, w))
        if gi not in (1, 2) or r not in lists or len(lists[r]) > 1: skip('groupe 1 ou poses'); continue
        wr = next(x for x in sims[0][0] if x[1] == r and x[3] == gi and x[4] == j)[6]
        if not wr or wr[0] == r or len(lists[wr[0]]) > 1: skip('valeur empruntee'); continue
        x, i = wr[0], wr[1]
        g, f = group_of(lists[x][0], i)
        if gi == 1 and (len(wr) < 3 or wr[2] != 16): skip('valeur reecrite'); continue   # depot entier du groupe 4 seulement
        if gi == 2 and (g in (0, 1, 2) or (g in (3, 4) and (f >> 8) & 0x1f != 16)): skip('valeur soudee'); continue
        if any(t.get(x, 1e9) >= t.get(r, -1) for t in times): skip('ordre'); continue
        want.setdefault((x, i), []).append((r, gi, j, w))
    for key in list(want)[len(free_entries):]:
        HALF_SKIPPED.extend(('cache plein', r, w) for r, gi, j, w in want.pop(key))
    ents = {key: free_entries[n] for n, key in enumerate(want)}

    def live_across(s, t0, t1, k):              # une valeur du tampon ecrite avant t1 et lue apres t0
        return any(b0 < t1 and b1 > t0 for b0, b1 in sims[k][1].get(s, []) + taken[k].get(s, []))
    def plan(q, helpers, conv):
        """Places des sommets de la ligne q : auxiliaires (sommets propres `helpers`) en fin de groupe 4,
        sommets du groupe 3 de rangs `conv` en fin de groupe 2 ; les autres restent ou ils sont autant que
        possible (un decalage d'ensemble enverrait des sommets lus plus tard dans des cases deja ecrasees).
        Rend (blocs dans le nouvel ordre, {case: nouvelle case}, {rang du groupe 5: nouvelle case}) ou la
        raison de l'echec."""
        a = lists[q][0]; s0 = len(a['g1']) + len(a['g2']); b = bounds(a); V = len(a['verts'])
        n3 = b[3] - b[2]
        blocks = [[('v', i) for i in range(b[0], b[1])],
                  [('v', i) for i in range(b[1], b[2])] + [('v', b[2] + j) for j in sorted(conv)],
                  [('v', b[2] + j) for j in range(n3) if j not in conv],
                  [('v', i) for i in range(b[3], b[4])] + [('h', i) for i in helpers],
                  [('v', i) for i in range(b[4], b[5])],
                  [('v', i) for i in range(b[5], V)]]
        place, start, ordered = {}, 0, []
        for blk in blocks:
            rng = range(start, start + len(blk)); kept = set(); rest = []
            for it in blk:
                if it[0] == 'v' and it[1] in rng: place[it] = it[1]; kept.add(it[1])
                else: rest.append(it)
            for it, p in zip(rest, [p for p in rng if p not in kept]): place[it] = p
            ordered.append(sorted(blk, key=lambda it: place[it])); start += len(blk)
        L0, L1 = s0 + V, s0 + start
        if L1 > BUFFER_TOP + 1: return 'liste trop longue'   # 110 cases (Eddy Poing, ligne 23 : 108 + 5)
        mp = {s0 + it[1]: s0 + p for it, p in place.items() if it[0] == 'v' and it[1] != p}
        if any(live_across(s, times[k][q], times[k][q], k) for s in range(L0, L1) for k in (0, 1)):
            return 'liste agrandie'             # la liste agrandie ecraserait une valeur encore lue
        # Le moteur range tous les sommets de la liste avant les soudures : une lecture du groupe 3 de q
        # dans la partie ajoutee relirait un sommet de q (sonde, Bruce costume 1 : bassin 62 -> 70,
        # lectures 63..69, pointes). TTT1 les tient toujours au-dela de la liste.
        if any(L0 <= (f & 0xff) // 2 - 1 < L1 for v in lists[q] for f in v['tails'][2]):
            return 'liste agrandie'
        moved, keep = {}, {(f & 0xff) // 2 - 1 for f in a['tails'][4]}
        for j5, f in enumerate(a['tails'][4]):  # depots du groupe 5 que la liste agrandie recouvrirait
            t = (f & 0xff) // 2 - 1
            if t >= L1: continue
            wrt = (q, b[4] + j5, (f >> 8) & 0x1f)
            last = [max([x[0] for x in sims[k][0] if x[6] == wrt and x[5] == t], default=times[k][q]) for k in (0, 1)]
            s = next((s for s in range(BUFFER_TOP, L1 - 1, -1) if s not in keep and s not in moved.values()
                      and not any(live_across(s, times[k][q], last[k], k) for k in (0, 1))), None)
            if s is None: return 'pas de case libre'
            moved[j5] = s
            for k in (0, 1): taken[k].setdefault(s, []).append((times[k][q], last[k]))
        def overwritten(s, r, k):               # case s ecrite entre q et le lecteur r ?
            if r not in times[k]: return False
            tq, tr = times[k][q], times[k][r]
            return any(tq < b0 < tr for b0, _ in sims[k][1].get(s, [])) or any(b0 < tr and b1 > tq for b0, b1 in taken[k].get(s, []))
        if any(overwritten(mp[x[5]], x[1], k) for x in sims[0][0] if x[6] and len(x[6]) == 2 and x[6][0] == q
               and x[5] in mp and x[3] != 1 for k in (0, 1)):
            return 'sommet deplace ecrase'
        return ordered, mp, moved

    def spare_row(q):
        """Ligne TTT1 du second maillage de la partie dont q est le maillage principal, si elle est
        vide et dessinee juste apres q (bassin : ligne 6, poitrine : ligne 2) : elle peut porter les
        auxiliaires de q dans une liste a elle, sans toucher a celle de q."""
        s = next((s for s, t in S2T.items() if t == q and s in P2R), None)
        s2 = SECOND.get(P2R.index(s)) if s is not None else None
        if s2 is None: return None
        t2 = S2T[s2]
        if (row(T, t2)[10] and row(T, t2)[1] > 2) or row(T, t2 - 1)[12] > 2 or t2 in lists: return None
        if template(q) is None: return None
        return t2 if t2 in order and order.index(t2) == order.index(q) + 1 else None
    def template(q):
        """Un triangle de q et sa texture : (famille, enregistrement, materiau, UV), ou None."""
        w = row(T, q)
        if w[1] <= 2 or w[2] <= 2: return None
        fams, prims = parse_b(block(T, w[1])), parse_c_ttt1(block(T, w[2]))
        for k in (0, 2):
            tex = [x for x in prims if x[0] == k]
            if fams[k] and tex and len(tex) == len(fams[k]): return k, fams[k][0], tex[0][1], tex[0][2]
        return None
    while True:                                 # retire les soudures d'une ligne qui ne se replace pas
        helpers, conv = {}, {}
        for (x, i), rds in want.items():
            helpers.setdefault(x, []).append(i)
            for r, gi, j, w in rds:
                if gi == 2: conv.setdefault(r, set()).add(j)
        taken = ({}, {}); plans = {}; spares = {}; bad = None
        for q, hs in helpers.items():           # liste du second maillage : cases 0..h-1 ecrasees
            t2 = spare_row(q)
            if t2 and not any(live_across(s, times[k][q] + .5, times[k][q] + .5, k) for s in range(len(hs)) for k in (0, 1)):
                spares[q] = t2
        for q in sorted(set(helpers) | set(conv)):
            p = plan(q, [] if q in spares else helpers.get(q, []), conv.get(q, set()))
            if isinstance(p, str): bad = (q, p); break
            plans[q] = p
        if not bad: break
        q, why = bad
        for key in [k for k, rds in want.items() if k[0] == q or any(r == q for r, *_ in rds)]:
            HALF_SKIPPED.extend((why, r, w) for r, gi, j, w in want.pop(key))
        if not want: return T
    # 1. lectures des sommets et depots deplaces, puis soudures dirigees vers le cache, sur les listes
    #    d'origine (rangs des champs inchanges a ce stade)
    for q, (ordered, mp, moved) in plans.items():
        b4 = bounds(lists[q][0])[4]
        for tm, r, vi, grp, j, s, wr in sims[0][0]:
            if not wr or wr[0] != q or grp == 1: continue
            if len(wr) == 2 and s in mp: ns = mp[s]
            elif len(wr) == 3 and wr[1] - b4 in moved and s == (lists[q][0]['tails'][4][wr[1] - b4] & 0xff) // 2 - 1:
                ns = moved[wr[1] - b4]
            else: continue
            if grp == 'g1': lists[r][vi]['g1'][j] = 2 * (ns + 1)
            else: f = lists[r][vi]['tails'][2][j]; lists[r][vi]['tails'][2][j] = (f & ~0xff) | 2 * (ns + 1)
    for (x, i), rds in want.items():
        for r, gi, j, w in rds:
            f = lists[r][0]['tails'][gi][j]; lists[r][0]['tails'][gi][j] = (f & ~0xff) | ents[(x, i)]
            HALF_DONE.append((x, r, gi, w))
    # 2. listes des seconds maillages (auxiliaires seuls : sommets du maillage principal, depots
    #    moitie dans le cache), puis chaque ligne replacee : sommets et champs (deja recables) dans
    #    le nouvel ordre
    added, words = {}, {}
    for q, t2 in spares.items():
        hs = helpers[q]
        added[(t2 - 1, 12)] = list_bytes(dict(g1=[], g2=[], verts=[lists[q][0]['verts'][i] for i in hs],
                                              tails=[[], [], [], [ents[(q, i)] | 8 << 8 for i in hs], [], []]))
        # Le runtime n'arme un second maillage d'invite qu'avec des polygones et le drapeau de maillage
        # (mot 10) : un triangle de surface nulle (trois fois le sommet 0, ecarte par NCLIP), materiau,
        # UV et normales repris d'un triangle de q.
        w = row(T, q); k, rec, mat, uv = template(q)
        polys = b''.join(struct.pack('<I', n) for n in ([1] if k == 0 else [0, 0, 1]))
        polys = polys + struct.pack('<II', 0, struct.unpack_from('<I', rec, 4)[0])
        polys += b''.join(struct.pack('<I', 0) for _ in range(3 - k))
        tex = struct.pack('<II', 8, mat) + struct.pack('<4H', 8, *[u | v << 8 for u, v in uv])
        tex += bytes([0] * k + [1, 0, 0, 1, 2] + [0] * (3 - k))
        added[(t2, 1)] = polys; added[(t2, 2)] = tex
        words[(t2, 10)] = 1
        if w[0] > 2: words[(t2, 0)] = ('bloc', w[0])
    new = {}
    for q, (ordered, mp, moved) in plans.items():
        a = lists[q][0]; b = bounds(a)
        for j5, s in moved.items(): a['tails'][4][j5] = (a['tails'][4][j5] & ~0xff) | 2 * (s + 1)
        def field(it):
            if it[0] == 'h': return ents[(q, it[1])] | 8 << 8   # depot moitie dans le cache
            return group_of(a, it[1])[1]
        verts = [a['verts'][it[1]] for blk in ordered for it in blk]
        tails = [[field(it) for it in blk] for blk in ordered[:5]] + [list(a['tails'][5])]
        lists[q] = [dict(a, verts=verts, tails=tails)]
        if mp and row(T, q)[1] > 2: new[row(T, q)[1]] = remap_prims(block(T, row(T, q)[1]), mp)
    for r in lists:
        o = row(T, r - 1)[12]; bts = b''.join(list_bytes(a) for a in lists[r])
        if bts != block(T, o)[:len(bts)]: new[o] = bts
    return rebuild(T, new, added, words) if new or added else T

# Pieces repliees (F32). Le PS1 a six places pour les accessoires et les maillages de tete en plus
# (parties 18..21, lignes 25 / 26 a os integre) ; les anciens costumes de Hwoarang et de Julia
# (emplacements TTT1 12 et 21) en ont sept : un troisieme maillage de tete (ligne 23) et six os
# d'accessoires. Comme F26 (to_ps1 : les pieces en trop repliees dans leur parent au repos), une piece
# B passe dans une piece A de la meme chaine rigide : sommets et normales dans le repere de A (bake,
# hote A), liste, normales, polygones et textures a la suite de ceux de A ; la ligne B devient vide.
# Seulement pour une feuille sans effet sur le reste : B ne lit ni n'ecrit le tampon, n'ecrit pas le
# cache, ne porte aucune piece ; A n'ecrit rien ; aucune ligne apres A ne lit les cases (positions,
# couleurs) que la liste agrandie recouvre. B suit A rigidement : si A balance (ressort), B balance
# avec elle, au repos par rapport a elle.
FOLDED = {}         # ligne TTT1 repliee -> ligne TTT1 qui l'accueille (dernier convert)
COLOUR_LIMIT = 90   # couleurs d'une piece : 0x1F800290 + 4 (k + 1), sous le tampon des profondeurs

def colour_fields(fam, ws):
    """Octets des couleurs d'un polygone (800361A8 : couleur k a SCR_COL + 4 (k + 1))."""
    if fam == 0: return [ws[1]]
    if fam == 1: return [ws[1] & 0x1fc]
    if fam == 2: return [ws[1] & 0x1fc, (ws[1] >> 7) & 0x1fc, ws[1] >> 16]
    return [ws[1] & 0x1fc, ws[2] & 0x1fc, (ws[2] >> 7) & 0x1fc, ws[2] >> 16]

def remap_polygon(fam, rec, slots, colours):
    """Enregistrement de polygone aux cases (positions) et couleurs renumerotees."""
    ws = list(struct.unpack_from(f'<{len(rec) // 4}I', rec))
    w = ws[0]
    for sh in ((0, 7, 14) if fam in (0, 2) else (0, 7, 14, 23)):
        sl = ((w >> sh) & 0x1fc) // 4
        w = (w & ~(0x1fc << sh)) | ((slots[sl] * 4) << sh)
    ws[0] = w & 0xffffffff
    c = [4 * (colours[f // 4 - 1] + 1) for f in colour_fields(fam, ws)]
    gour = lambda x, c3: (x & ~(0x1fc | 0x1fc << 7 | 0xffff0000)) | c3[0] | c3[1] << 7 | c3[2] << 16
    if fam == 0: ws[1] = c[0]
    elif fam == 1: ws[1] = (ws[1] & ~0x1fc) | c[0]
    elif fam == 2: ws[1] = gour(ws[1], c)
    else: ws[1] = (ws[1] & ~0x1fc) | c[0]; ws[2] = gour(ws[2], c[1:])
    return struct.pack(f'<{len(ws)}I', *[x & 0xffffffff for x in ws])

def texture_bytes(prims):
    """Bloc c TTT1 (l'inverse de parse_c_ttt1) : [(famille, materiau, [(u, v)...])] par famille."""
    mats, uvs, fam = [], [], [[] for _ in range(4)]
    for k, mat, uv in prims:
        if mat not in mats: mats.append(mat)
        idx = []
        for u, v in uv:
            if u | v << 8 not in uvs: uvs.append(u | v << 8)
            idx.append(uvs.index(u | v << 8))
        fam[k].append(bytes([mats.index(mat)] + idx))
    if len(mats) > 255 or len(uvs) > 255 or any(len(f) > 255 for f in fam): raise ValueError('textures trop grandes')
    out = struct.pack('<I', 4 + 4 * len(mats)) + b''.join(struct.pack('<I', m) for m in mats)
    out += struct.pack('<H', 2 + 2 * len(uvs)) + b''.join(struct.pack('<H', e) for e in uvs)
    for f in fam: out += bytes([len(f)]) + b''.join(f)
    return pad4(out)

def normal_bytes(a):
    """Bloc de normales sans depot de couleurs (deux groupes vides), comme parse_a le lit."""
    out = struct.pack('<I', 4 * (1 + len(a['g1']) + len(a['g2'])))
    for g in (a['g1'], a['g2']): out += struct.pack('<I', len(g)) + pad4(bytes(g))
    out += struct.pack('<I', len(a['verts'])) + b''.join(struct.pack('<4h', *v) for v in a['verts'])
    return out + b'\0' * 8

def fold_rows(T, A, B):
    """Modele TTT1 ou la piece B est repliee dans la piece A (voir FOLDED), ou ValueError."""
    if not (A < B and {A, B} <= set(accessory_rows(T))): raise ValueError('pas deux accessoires')
    if row(T, A - 1)[13] > 2 or row(T, B - 1)[13] > 2 or row(T, A - 1)[12] <= 2 or row(T, B - 1)[12] <= 2:
        raise ValueError('table de poses ou liste absente')
    if any(row(T, u)[6] == PART_OF_ROW[B] for u in range(nrows(T)) if u != B): raise ValueError('B porte une piece')
    if rigid_root(T, A)[0] != rigid_root(T, B)[0]: raise ValueError('chaines rigides differentes')
    vA, vB = (SM.variants(block(T, row(T, r - 1)[12]), True) for r in (A, B))
    if len(vA) > 1 or len(vB) > 1: raise ValueError('variantes')
    LA, LB = vA[0], vB[0]
    if any(LA['tails'][g] for g in (0, 3, 4)): raise ValueError('A ecrit')
    if LB['g1'] or any(LB['tails'][g] for g in (0, 2, 3, 4)): raise ValueError('B lit le tampon ou ecrit')
    between = [u for u in range(A + 1, B) if row(T, u - 1)[12] > 2]
    written = {f & 0xff for u in between for a in SM.variants(block(T, row(T, u - 1)[12]), True)
               for g in (0, 3) for f in a['tails'][g]}
    if written & (set(LB['g2']) | {f & 0xff for f in LB['tails'][1]}): raise ValueError('cache de B reecrit avant B')
    NA, NB = (parse_a(block(T, row(T, r)[0])) for r in (A, B))
    for r, N in ((A, NA), (B, NB)):
        if block(T, row(T, r)[0])[N['used']:] != b'\0' * 8: raise ValueError('depots de couleurs')
    if NB['g2'] and any(block(T, row(T, u)[0])[parse_a(block(T, row(T, u)[0]))['used']:].strip(b'\0')
                        for u in between if row(T, u)[0] > 2):
        raise ValueError('couleurs de B reecrites avant B')
    nA, nB = list_len(LA), list_len(LB)
    cA = len(NA['g1']) + len(NA['g2']) + len(NA['verts'])
    cB = len(NB['g1']) + len(NB['g2']) + len(NB['verts'])
    nM, cM = nA + nB, cA + cB - len(NB['g1'])
    if nM > BUFFER_TOP + 1 or cM > COLOUR_LIMIT: raise ValueError('liste trop longue')
    if NB['g1'] and B != A + 1: raise ValueError('couleurs empruntees par B')
    if any(not (0 <= b // 2 - 1 < cA) for b in NB['g1']): raise ValueError('couleurs empruntees hors de A')
    for u in range(A + 1, nrows(T)):                 # lecteurs apres A : tampon et couleurs
        if u == B: continue
        if row(T, u - 1)[12] > 2:
            for a in SM.variants(block(T, row(T, u - 1)[12]), True):
                if any(b // 2 - 1 < nM for b in a['g1']) or any((f & 0xff) // 2 - 1 < nM for f in a['tails'][2]):
                    raise ValueError(f'ligne {u} lit les cases de la liste agrandie')
        if row(T, u)[0] > 2 and any(b // 2 - 1 < cM for b in parse_a(block(T, row(T, u)[0]))['g1']):
            raise ValueError(f'ligne {u} lit les couleurs de la piece agrandie')
    # Liste agrandie : emprunts de A, cache de A puis de B, sommets groupe par groupe (A puis B)
    LBb = bake(T, B, LB, host=A)
    def starts(a):                                   # premiere case de chaque groupe, puis fin de liste
        b = [len(a['g1']) + len(a['g2'])]
        for g in a['tails'][:5]: b.append(b[-1] + len(g))
        return b + [b[0] + len(a['verts'])]
    sA, sB = starts(LA), starts(LB)
    mA = {j: j for j in range(len(LA['g1']) + len(LA['g2']))}
    mB = {len(LB['g1']) + j: len(LA['g1']) + len(LA['g2']) + j for j in range(len(LB['g2']))}
    verts, at = [], len(LA['g1']) + len(LA['g2']) + len(LB['g2'])
    for g in range(6):
        for L, s, m in ((LA, sA, mA), (LBb, sB, mB)):
            for i in range(s[g], s[g + 1]):
                m[i] = at; at += 1; verts.append(L['verts'][i - s[0]])
    M = dict(g1=list(LA['g1']), g2=list(LA['g2']) + list(LB['g2']), verts=verts,
             tails=[list(LA['tails'][g]) + list(LB['tails'][g]) for g in range(6)])
    for r, L, n, m in ((A, LA, nA, mA), (B, LB, nB, mB)):  # cases hors liste : seulement au-dela de la liste agrandie
        for k, fl in enumerate(parse_b(block(T, row(T, r)[1]))):
            for p in fl:
                for sl in prim_verts(k, p):
                    if sl >= n and (r == B or sl < nM): raise ValueError(f'ligne {r} dessine une case hors liste')
                    if sl >= n: m[sl] = sl
    # Normales : emprunts de A, cache de A puis de B, normales de A puis de B (tournees vers A)
    _, Mt, _ = rigid_root(T, B); _, Mh, _ = rigid_root(T, A)
    turn = lambda v: tuple(sum(Mh[k][i] * (sum(Mt[k][j] * v[j] for j in range(3)) >> 12) for k in range(3)) >> 12
                           for i in range(3)) + (0,)
    n1, n2 = len(NA['g1']), len(NA['g2'])
    cmA = {k: (k if k < n1 + n2 else k + len(NB['g2'])) for k in range(cA)}
    cmB = {k: cmA[NB['g1'][k] // 2 - 1] for k in range(len(NB['g1']))}
    cmB.update({len(NB['g1']) + j: n1 + n2 + j for j in range(len(NB['g2']))})
    cmB.update({len(NB['g1']) + len(NB['g2']) + j: cA + len(NB['g2']) + j for j in range(len(NB['verts']))})
    N = dict(g1=list(NA['g1']), g2=list(NA['g2']) + list(NB['g2']),
             verts=list(NA['verts']) + [turn(v) for v in NB['verts']])
    fams = [[], [], [], []]
    for r, m, cm in ((A, mA, cmA), (B, mB, cmB)):
        for k, fl in enumerate(parse_b(block(T, row(T, r)[1]))):
            fams[k] += [remap_polygon(k, p, m, cm) for p in fl]
    polys = b''.join(struct.pack('<I', len(f)) + b''.join(f) for f in fams)
    tex = parse_c_ttt1(block(T, row(T, A)[2])) + parse_c_ttt1(block(T, row(T, B)[2]))
    tex = texture_bytes(sorted(tex, key=lambda x: x[0]))          # stable : A puis B dans chaque famille
    # Lignes : A recoit les nouveaux blocs, B devient une ligne vide (sans maillage ni liste)
    mine = {(A - 1, 12), (A, 0), (A, 1), (A, 2), (B - 1, 12), (B, 0), (B, 1), (B, 2)}
    old = {row(T, r)[k] for r, k in mine}
    others = {row(T, r)[k] for r in range(nrows(T)) for k in (0, 1, 2, 12, 13) if (r, k) not in mine}
    new = {o: b'' for o in old - others if o > 2}
    added = {(A - 1, 12): list_bytes(M), (A, 0): normal_bytes(N), (A, 1): polys, (A, 2): tex}
    words = {(B - 1, 12): 0, (B, 0): 0, (B, 1): 0, (B, 2): 0, (B, 10): 0, (B, 11): 0,
             **{(B, k): v for k, v in zip(range(3, 10), (0, 0, 0, -1, 0, 0, 0))}}
    return rebuild(T, new, added, words)

def fold_accessories(T):
    """Replie des pieces (fold_rows) tant qu'il y en a plus que de places PS1. Preference : B enfant
    de A, puis meme parent, puis meme chaine rigide ; a egalite, la plus petite liste agrandie."""
    FOLDED.clear()
    while len(head_extra_rows(T) + accessory_rows(T)) > len(ACC_ROWS) + len(BAKE_ROWS):
        acc = accessory_rows(T); best = None
        for A in acc:
            for B in acc:
                if B <= A: continue
                try: T2 = fold_rows(T, A, B)
                except (ValueError, StopIteration): continue
                rank = (row(T, B)[6] != PART_OF_ROW[A], row(T, B)[6] != row(T, A)[6],
                        list_len(SM.variants(block(T, row(T, A - 1)[12]), True)[0]) +
                        list_len(SM.variants(block(T, row(T, B - 1)[12]), True)[0]))
                if best is None or rank < best[0]: best = (rank, A, B, T2)
        if best is None: break                       # _layouts dira combien de pieces pour combien de places
        _, A, B, T = best; FOLDED[B] = A
    return T

# Troisiemes maillages de la poitrine et du bassin (F32). TTT1 dessine jusqu'a trois maillages par
# partie : poitrine 1 / 2 / 3, bassin 4 / 5 / 6 (meme os, sans decalage). Le PS1 n'en a que deux
# (lignes 1 / 2 et 3 / 4) : les lignes 3 et 5 etaient perdues, et la ligne suivante empruntait au
# tampon des sommets qu'elles n'avaient pas ranges (17 natifs : Yoshimitsu, Xiaoyu, Eddy, Tiger, Jin,
# Hwoarang, Gun Jack, Lei). Les parties 18..21 se dessinent apres la tete, loin des lignes 4..7 qui
# lisent ce que 3 et 5 laissent dans le tampon et le cache. Deux voies, essayees dans l'ordre :
# - fusion (merge_rows) : B est fondue dans la piece A dessinee juste avant elle sur le meme os
#   (2 + 3, 5 + 6 ou 4 + 5), une seule liste : emprunts de A, cache de A puis de B, sommets groupe
#   par groupe (A puis B), polygones a la suite. Les emprunts de B disparaissent : ses polygones
#   lisent les valeurs la ou elles sont ;
# - place d'accessoire (move_row), si la liste fondue depasse 110 cases (Gun Jack, Lei) : B se
#   dessine apres la tete, rattachee a la poitrine sans decalage ; ses sommets lus par d'autres lignes
#   restent calcules a leur rang, dans la liste de A (ou de la ligne 1).
# Le modele est repris par provenance (ir_build) : chaque emprunt, soudure au tampon et coin de
# polygone designe la valeur qu'il lit, pas une case ; emit repasse les lignes dans l'ordre TTT1 et
# place chaque lecture la ou sa valeur se trouve. Le tampon est plein (Yoshimitsu Poing : cases 39 a
# 109 occupees apres la ligne 3) : une valeur que la liste plus longue ecraserait passe par le cache
# (_to_cache : son depot ecrit une entree neuve, ses lecteurs l'y lisent ; _reroute si l'entree est
# reprise avant la lecture). Meme chose pour les couleurs (tampon SCR_COL, table globale).
# Verifie hors jeu : memes coins (simulateur TTT1, 6 poses), memes couleurs, memes textures.
MERGED = {}         # ligne TTT1 fondue -> ligne TTT1 qui l'accueille (dernier convert)
EXTRA_MESHES = ((2, 3), (5, 6), (4, 5))   # fusions (A, B) candidates, dans l'ordre (voir merge_extra_meshes)

def _own(r, j): return ('L', r, j)          # sommet propre j (case j de la liste) de la ligne r

def pos_flow(T, rename=None):
    """Provenance du tampon (128 cases) et du cache des positions, lignes dans l'ordre TTT1.
    Etiquettes : ('L', r, j) valeur de la case j de la liste de r (un emprunt porte l'etiquette de ce
    qu'il recopie), ('D', e, w) depot partiel, ('C3', e, w) depot partiel au cache, ('V', r) ligne a
    poses, ('P', k) / ('PC', e) etat initial. Rend (etats du tampon avant / apres chaque ligne, cache
    avant / apres, lectures). Lecture : (ligne, variante, sorte, rang, case ou entree, etiquette) ;
    sortes 'g1', 'g2' (emprunts), 0 / 1 / 2 (soudures), ('poly', famille, rang, coin) hors liste."""
    rename = rename or {}
    sc = [('P', k) for k in range(128)]; ca = {}; reads = []; pre, post, cpre, cpost = {}, {}, {}, {}
    cg = lambda c, e: c.get(e, ('PC', e))
    for r in range(1, nrows(T)):
        pre[r], cpre[r] = list(sc), dict(ca); n = 0
        if row(T, r - 1)[12] > 2:
            vs = SM.variants(block(T, row(T, r - 1)[12]), True)
            for vi, a in enumerate(vs):
                for j, b in enumerate(a['g1']): reads.append((r, vi, 'g1', j, b // 2 - 1, pre[r][b // 2 - 1]))
                for j, e in enumerate(a['g2']): reads.append((r, vi, 'g2', j, e, cg(cpre[r], e)))
                for gi in (0, 1):
                    for j, f in enumerate(a['tails'][gi]): reads.append((r, vi, gi, j, f & 0xff, cg(cpre[r], f & 0xff)))
                for j, f in enumerate(a['tails'][2]):
                    reads.append((r, vi, 2, j, (f & 0xff) // 2 - 1, pre[r][(f & 0xff) // 2 - 1]))
            if len(vs) == 1:
                a = vs[0]; s0 = len(a['g1']) + len(a['g2']); n = s0 + len(a['verts'])
                own = lambda j: rename.get(r, {}).get(j, _own(r, j))
                lst = [pre[r][b // 2 - 1] for b in a['g1']] + [cg(cpre[r], e) for e in a['g2']] + [own(j) for j in range(s0, n)]
                sc[:n] = lst; b0 = s0
                for gi, g in enumerate(a['tails'][:5]):
                    for j, f in enumerate(g):
                        s, w, e = b0 + j, (f >> 8) & 0x1f, f & 0xff
                        if gi == 0: ca[e] = lst[s]
                        elif gi == 3: ca[e] = lst[s] if w == 16 else ('D', lst[s], w)
                        elif gi == 4: sc[e // 2 - 1] = lst[s] if w == 16 else ('D', lst[s], w)
                    b0 += len(g)
            else:
                n = max(list_len(a) for a in vs)
                for k in range(n): sc[k] = ('V', r)
                for a in vs:
                    for f in a['tails'][4]: sc[(f & 0xff) // 2 - 1] = ('V', r)
                    for gi in (0, 3):
                        for f in a['tails'][gi]: ca[f & 0xff] = ('V', r)
                n = min(list_len(a) for a in vs)
        post[r], cpost[r] = list(sc), dict(ca)
        if row(T, r)[1] > 2:
            for k, fl in enumerate(parse_b(block(T, row(T, r)[1]))):
                for i, p in enumerate(fl):
                    for c, sl in enumerate(prim_verts(k, p)):
                        if sl >= n: reads.append((r, 0, ('poly', k, i, c), 0, sl, sc[sl]))
    return pre, post, cpre, cpost, reads

def colour_list(T, r):
    """Bloc de normales de la ligne r : parse_a et les deux groupes de renvois (cache global, tampon)."""
    b = block(T, row(T, r)[0]); N = parse_a(b); p = N['used']; dep = []
    for _ in range(2):
        n = struct.unpack_from('<I', b, p)[0] if p + 4 <= len(b) else 0; p += 4
        dep.append(list(b[p:p + n])); p += (n + 3) & ~3
    return N, dep

def colour_bytes(N, dep):
    out = normal_bytes(N)[:-8]
    for g in dep: out += struct.pack('<I', len(g)) + pad4(bytes(g))
    return out

def colour_flow(T, rename=None):
    """Provenance des couleurs (char_render_model, etape 2) : tampon SCR_COL (case k = octet 2k + 2
    des emprunts et des renvois, 4k + 4 des polygones), table globale. Etiquettes ('K', r, j) ou
    ('PK', k) / ('PG', e). Rend comme pos_flow ; lectures 'g1', 'g2', ('poly', famille, rang, champ)."""
    rename = rename or {}
    sc = [('PK', k) for k in range(128)]; gt = {}; reads = []; pre, post, gpre, gpost = {}, {}, {}, {}
    gg = lambda g, e: g.get(e, ('PG', e))
    for r in range(1, nrows(T)):
        pre[r], gpre[r] = list(sc), dict(gt); n = 0
        if row(T, r)[0] > 2:
            N, dep = colour_list(T, r)
            for j, b in enumerate(N['g1']): reads.append((r, 0, 'g1', j, b // 2 - 1, pre[r][b // 2 - 1]))
            for j, e in enumerate(N['g2']): reads.append((r, 0, 'g2', j, e, gg(gpre[r], e)))
            s0 = len(N['g1']) + len(N['g2']); n = s0 + len(N['verts'])
            own = lambda j: rename.get(r, {}).get(j, ('K', r, j))
            lst = [pre[r][b // 2 - 1] for b in N['g1']] + [gg(gpre[r], e) for e in N['g2']] + [own(j) for j in range(s0, n)]
            sc[:n] = lst
            for j, e in enumerate(dep[0]): gt[e] = lst[s0 + j]
            for j, e in enumerate(dep[1]): sc[e // 2 - 1] = lst[s0 + len(dep[0]) + j]
        post[r], gpost[r] = list(sc), dict(gt)
        if row(T, r)[1] > 2:
            for k, fl in enumerate(parse_b(block(T, row(T, r)[1]))):
                for i, p in enumerate(fl):
                    ws = struct.unpack_from(f'<{len(p) // 4}I', p)
                    for c, f in enumerate(colour_fields(k, ws)):
                        if f // 4 - 1 >= n: reads.append((r, 0, ('poly', k, i, c), 0, f // 4 - 1, sc[f // 4 - 1]))
    return pre, post, gpre, gpost, reads

KINDS = ('pos', 'col')
DEP_GROUP = {'pos': 4, 'col': 1}               # groupe des depots au tampon
LIST_TOP = {'pos': BUFFER_TOP + 1, 'col': COLOUR_LIMIT}

def _items(T, r, kind):
    """Liste de la ligne r : (g1, g2, sommets propres [(sommet, groupe, champ)]), groupes dans l'ordre
    du flux. Positions : groupes 0..4 des soudures, 5 (champ 8 bits), 6 (sans champ) ; couleurs :
    0 (renvoi au cache global), 1 (renvoi au tampon), 2 (rien)."""
    if kind == 'pos':
        a = SM.variants(block(T, row(T, r - 1)[12]), True)[0]; it = []; i = 0
        for g in range(6):
            for f in a['tails'][g]: it.append((a['verts'][i], g, f)); i += 1
        it += [(v, 6, None) for v in a['verts'][i:]]
        return list(a['g1']), list(a['g2']), it
    N, dep = colour_list(T, r); it = []; i = 0
    for g in range(2):
        for f in dep[g]: it.append((N['verts'][i], g, f)); i += 1
    it += [(v, 2, None) for v in N['verts'][i:]]
    return list(N['g1']), list(N['g2']), it

def _set_slot(f, s): return (f & ~0xff) | 2 * (s + 1)

class Lost(Exception):
    """Valeur introuvable pendant l'emission (flux, etiquette, ligne, sorte, etats)."""
    def __init__(self, kind, tag, r, how, pre, cache, post=None, lst=None):
        super().__init__(f'{kind} : ligne {r} ({how}) : valeur {tag} perdue')
        self.kind, self.tag, self.r, self.how, self.pre, self.cache, self.post, self.lst = kind, tag, r, how, pre, cache, post, lst

def _find(state, t, k):
    if 0 <= k < 128 and state[k] == t: return k
    return next((i for i in range(128) if state[i] == t), None)

def ir_build(T):
    """Lignes de T par provenance : chaque emprunt, soudure au tampon et coin de polygone designe la
    valeur qu'il lit (etiquette de pos_flow / colour_flow) et la case d'origine, preferee a l'emission.
    ir[r] = dict(pos, col, raw, polys) ; pos / col : dict(g1 [(etiquette, case)], g2 [(entree,
    etiquette attendue)], own [dict(v, g, f, id, ...)]) ; raw : lectures d'une ligne a poses ;
    polys : par famille [(enregistrement, [(etiquette, case)] positions, [(etiquette, case)] couleurs)]."""
    pre, post, cpre, cpost, reads = pos_flow(T)
    kpre, kpost, gpre, gpost, _ = colour_flow(T)
    ir = {}
    for r in range(1, nrows(T)):
        R = ir[r] = dict(pos=None, col=None, raw=None, polys=None)
        if row(T, r - 1)[12] > 2:
            vs = SM.variants(block(T, row(T, r - 1)[12]), True)
            if len(vs) > 1:
                R['raw'] = [x[1:] for x in reads if x[0] == r and not isinstance(x[2], tuple)]
            else:
                g1, g2, it = _items(T, r, 'pos'); s0 = len(g1) + len(g2); c = dict(cpre[r]); own = []
                for i, (v, g, f) in enumerate(it):
                    d = dict(v=v, g=g, f=f, id=_own(r, s0 + i))
                    if g == 0: d['exp'] = c.get(f & 0xff, ('PC', f & 0xff)); c[f & 0xff] = d['id']
                    elif g == 1: d['exp'] = cpre[r].get(f & 0xff, ('PC', f & 0xff))
                    elif g == 2: d['src'] = (pre[r][(f & 0xff) // 2 - 1], (f & 0xff) // 2 - 1)
                    elif g == 4: d['slot'] = (f & 0xff) // 2 - 1
                    own.append(d)
                R['pos'] = dict(g1=[(pre[r][b // 2 - 1], b // 2 - 1) for b in g1],
                                g2=[(e, cpre[r].get(e, ('PC', e))) for e in g2], own=own)
        if row(T, r)[0] > 2:
            g1, g2, it = _items(T, r, 'col'); s0 = len(g1) + len(g2)
            own = [dict(v=v, g=g, f=f, id=('K', r, s0 + i), slot=(f & 0xff) // 2 - 1 if g == 1 else None)
                   for i, (v, g, f) in enumerate(it)]
            R['col'] = dict(g1=[(kpre[r][b // 2 - 1], b // 2 - 1) for b in g1],
                            g2=[(e, gpre[r].get(e, ('PG', e))) for e in g2], own=own)
        if row(T, r)[1] > 2:
            R['polys'] = []
            for fam, fl in enumerate(parse_b(block(T, row(T, r)[1]))):
                out = []
                for p in fl:
                    ws = struct.unpack_from(f'<{len(p) // 4}I', p)
                    out.append((p, [(post[r][s], s) for s in prim_verts(fam, p)],
                                [(kpost[r][f // 4 - 1], f // 4 - 1) for f in colour_fields(fam, ws)]))
                R['polys'].append(out)
    return ir

def _value(kind, d):
    """Etiquette de la valeur que le sommet propre d depose (tampon ou cache), ou None."""
    if kind == 'pos':
        if d['g'] in (3, 4): w = (d['f'] >> 8) & 0x1f; return d['id'] if w == 16 else ('D', d['id'], w)
        return d['id'] if d['g'] == 0 else None
    return d['id'] if d['g'] in (0, 1) else None

def emit(T, ir, rows_new=None):
    """Repasse les lignes dans l'ordre TTT1 en placant chaque lecture la ou sa valeur se trouve ;
    rend {(ligne, mot): octets} des blocs changes, ou leve Lost. Verifie les lectures du cache."""
    sc = [('P', k) for k in range(128)]; ca = {}; ks = [('PK', k) for k in range(128)]; kg = {}
    out = {}
    for r in range(1, nrows(T)):
        R = ir[r]; pre, c0 = list(sc), dict(ca); n = 0; lst = []
        if R['raw'] is not None:
            o = row(T, r - 1)[12]
            vs = [dict(a, g1=list(a['g1']), tails=[list(g) for g in a['tails']]) for a in SM.variants(block(T, o), True)]
            for vi, kind, j, s, t in R['raw']:
                if kind in ('g1', 2):
                    ns = _find(pre, t, s)
                    if ns is None: raise Lost('pos', t, r, 'raw', pre, c0)
                    if kind == 'g1': vs[vi]['g1'][j] = 2 * (ns + 1)
                    else: vs[vi]['tails'][2][j] = _set_slot(vs[vi]['tails'][2][j], ns)
                elif c0.get(s, ('PC', s)) != t: raise Lost('pos', t, r, 'cache', pre, c0)
            out[(r - 1, 12)] = b''.join(list_bytes(a) for a in vs)
            n = max(list_len(a) for a in vs)
            for k in range(n): sc[k] = ('V', r)
            for a in vs:
                for f in a['tails'][4]: sc[(f & 0xff) // 2 - 1] = ('V', r)
                for gi in (0, 3):
                    for f in a['tails'][gi]: ca[f & 0xff] = ('V', r)
            n = min(list_len(a) for a in vs)
        elif R['pos']:
            P = R['pos']; g1 = []
            for t, s in P['g1']:
                ns = _find(pre, t, s)
                if ns is None: raise Lost('pos', t, r, 'g1', pre, c0)
                g1.append(2 * (ns + 1))
            for e, t in P['g2']:
                if c0.get(e, ('PC', e)) != t: raise Lost('pos', t, r, 'cache', pre, c0)
            own = sorted(P['own'], key=lambda d: d['g']); c = dict(c0); fields = []
            for d in own:
                g, f = d['g'], d['f']
                if g == 0:
                    if c.get(f & 0xff, ('PC', f & 0xff)) != d['exp']: raise Lost('pos', d['exp'], r, 'cache', pre, c0)
                    c[f & 0xff] = d['id']
                elif g == 1:
                    if c0.get(f & 0xff, ('PC', f & 0xff)) != d['exp']: raise Lost('pos', d['exp'], r, 'cache', pre, c0)
                elif g == 2:                     # le PS1 range toute la liste avant les soudures : la
                    t_, s_ = d['src']            # valeur lue doit etre au-dela (engine_rules)
                    nl = len(g1) + len(P['g2']) + len(own)
                    # la case d'un depot marque garde sa moitie (voir plus bas) : une soudure la lit
                    # comme avant (convert_positions la sait moitie : soudure 8/8)
                    ok = lambda x: x[0] == 'Hd' and x[1] == t_
                    ns = next((i for i in [s_] * (s_ >= nl) + list(range(nl, 128)) if pre[i] == t_), None)
                    if ns is None: ns = s_ if s_ >= nl and ok(pre[s_]) else next((i for i in range(nl, 128) if ok(pre[i])), None)
                    if ns is None: raise Lost('pos', t_, r, 't2', pre, c0)
                    f = _set_slot(f, ns)
                elif g == 3: c[f & 0xff] = _value('pos', d)
                elif g == 4: f = _set_slot(f, d['slot'])
                fields.append(f)
            lst = [pre[b // 2 - 1] for b in g1] + [c0.get(e, ('PC', e)) for e, _ in P['g2']] + [d['id'] for d in own]
            n = len(lst)
            if n > LIST_TOP['pos']: raise ValueError(f'ligne {r} : liste de {n} sommets')
            sc[:n] = lst
            # Regle PS1 (0x80036CAC), pas TTT1 : apres la liste, les groupes passent dans l'ordre et sur
            # place ; un depot marque (poids < 16, groupes 3 et 4) ne laisse que la moitie dans sa propre
            # case, et une copie (groupe 4) recopie la case telle qu'elle est a ce moment (une copie
            # precedente a pu la recouvrir). Lue comme entiere, cette moitie tirait des pointes vers le
            # coin haut gauche de l'ecran (Eddy 87 / 17, lignes 3 / 5 fondues).
            s0 = len(g1) + len(P['g2'])
            for i, d in enumerate(own):
                if d['g'] not in (3, 4): continue
                s = s0 + i
                w = (d['f'] >> 8) & 0x1f
                if w < 16: sc[s] = ('Hd', d['id'], w) if sc[s] == d['id'] else ('H', r, s)
                if d['g'] == 4: sc[d['slot']] = _value('pos', d) if sc[s][0] == 'Hd' else sc[s]
            ca = c
            out[(r - 1, 12)] = list_bytes(dict(g1=g1, g2=[e for e, _ in P['g2']], verts=[d['v'] for d in own],
                                              tails=[[f for d, f in zip(own, fields) if d['g'] == k] for k in range(6)]))
        kpre_, g0 = list(ks), dict(kg); klst = []
        if R['col']:
            K = R['col']; g1 = []
            for t, s in K['g1']:
                ns = _find(kpre_, t, s)
                if ns is None: raise Lost('col', t, r, 'g1', kpre_, g0)
                g1.append(2 * (ns + 1))
            for e, t in K['g2']:
                if g0.get(e, ('PG', e)) != t: raise Lost('col', t, r, 'cache', kpre_, g0)
            own = sorted(K['own'], key=lambda d: d['g'])
            klst = [kpre_[b // 2 - 1] for b in g1] + [g0.get(e, ('PG', e)) for e, _ in K['g2']] + [d['id'] for d in own]
            if len(klst) > LIST_TOP['col']: raise ValueError(f'ligne {r} : {len(klst)} couleurs')
            ks[:len(klst)] = klst
            for d in own:
                if d['g'] == 0: kg[d['f'] & 0xff] = d['id']
                elif d['g'] == 1: ks[d['slot']] = d['id']
            dep = [[d['f'] for d in own if d['g'] == 0], [2 * (d['slot'] + 1) for d in own if d['g'] == 1]]
            out[(r, 0)] = colour_bytes(dict(g1=g1, g2=[e for e, _ in K['g2']], verts=[d['v'] for d in own]), dep)
        if R['polys'] is not None:
            b = b''
            for fam, fl in enumerate(R['polys']):
                b += struct.pack('<I', len(fl))
                for p, cs, cc in fl:
                    sl = {}
                    for (t, s), s_old in zip(cs, prim_verts(fam, p)):
                        ns = _find(sc, t, s)
                        if ns is None: raise Lost('pos', t, r, 'poly', pre, c0, sc, lst)
                        sl[s_old] = ns
                    co = {}
                    ws = struct.unpack_from(f'<{len(p) // 4}I', p)
                    for (t, s), f in zip(cc, colour_fields(fam, ws)):
                        ns = _find(ks, t, s)
                        if ns is None: raise Lost('col', t, r, 'poly', kpre_, g0, ks, klst)
                        co[f // 4 - 1] = ns
                    b += remap_polygon(fam, p, sl, co)
            out[(r, 1)] = b
    return out

def _fresh(ir, kind):
    used = set()
    for R in ir.values():
        X = R[kind]
        if X:
            used |= {e for e, _ in X['g2']} | {d['f'] & 0xff for d in X['own'] if d['f'] is not None and d['g'] in ((0, 1, 3) if kind == 'pos' else (0,))}
    if kind == 'pos':
        for R in ir.values():
            for vi, k, j, s, t in R['raw'] or []:
                if k in ('g2', 0, 1): used.add(s)
    return next(e for e in range(254, 1, -2) if e not in used and e not in (0,))

def _to_cache(ir, kind, t, T=None):
    """La valeur t ne passe plus par le tampon : son depot (ou le sommet qui la porte) l'ecrit dans le
    cache, et ses lecteurs l'y lisent (emprunt au cache, soudure au cache). ValueError si impossible."""
    base = t[1] if t[0] == 'D' else t
    hit = [(r, d) for r, R in ir.items() if R[kind] for d in R[kind]['own'] if d['id'] == base]
    if not hit: raise ValueError(f'{kind} : valeur {t} sans sommet')
    r0, d = hit[0]
    if _value(kind, d) == t and (kind == 'pos' and d['g'] in (0, 3) or kind == 'col' and d['g'] == 0):
        e = d['f'] & 0xff
    elif kind == 'pos' and ((d['g'] == 4 and _value(kind, d) == t) or (d['g'] in (5, 6) and t == base)):
        e = _fresh(ir, 'pos'); w = (d['f'] >> 8) & 0x1f if d['g'] == 4 else 16
        d['g'], d['f'] = 3, (w << 8) | e; d.pop('slot', None)
    elif kind == 'col' and d['g'] in (1, 2) and t == base:
        e = _fresh(ir, 'col'); d['g'], d['f'], d['slot'] = 0, e, None
    else: raise ValueError(f'{kind} : valeur {t} soudee, ni deposee')
    for r, R in ir.items():
        X = R[kind]
        if R['raw'] and kind == 'pos' and any(tt == t for _, k, _, _, tt in R['raw'] if k in ('g1', 2)):
            raise ValueError(f'ligne a poses {r} lit {t}')
        if not X: continue
        if any(tt == t for tt, _ in X['g1']):
            X['g1'] = [(tt, s) for tt, s in X['g1'] if tt != t]; X['g2'].append((e, t))
        if kind == 'pos':
            for o in X['own']:
                if o['g'] == 2 and o['src'][0] == t:
                    o['g'], o['f'], o['exp'] = 1, (o['f'] & ~0xff) | e, t; o.pop('src')
    return e

def _reroute(ir, kind, t):
    """La valeur t, ecrasee dans son entree du cache avant d'etre lue, passe par une entree neuve :
    son depot (groupe 4 des positions, renvoi global des couleurs) et ses lecteurs changent d'entree."""
    hit = [d for R in ir.values() if R[kind] for d in R[kind]['own']
           if _value(kind, d) == t and d['g'] == (3 if kind == 'pos' else 0)]
    if not hit: raise ValueError(f'{kind} : entree du cache de {t} ecrasee, sans depot a deplacer')
    d = hit[0]; old = d['f'] & 0xff; e = _fresh(ir, kind); d['f'] = (d['f'] & ~0xff) | e
    for R in ir.values():
        X = R[kind]
        if R['raw'] and kind == 'pos' and any(tt == t for _, k, _, _, tt in R['raw'] if k in ('g2', 0, 1)):
            raise ValueError(f'ligne a poses : lit {t} au cache')
        if not X: continue
        X['g2'] = [(e if (ee, tt) == (old, t) else ee, tt) for ee, tt in X['g2']]
        for o in X['own']:
            if kind == 'pos' and o['g'] in (0, 1) and o.get('exp') == t and o['f'] & 0xff == old:
                if o['g'] == 0: raise ValueError(f'{kind} : {t} relu et reecrit au cache (groupe 1)')
                o['f'] = (o['f'] & ~0xff) | e

def _split(ir, t):
    """La valeur entiere t est celle d'un depot marque : au PS1 sa case n'en garde que la moitie (emit).
    Un sommet simple aux memes coordonnees, ajoute a la fin de sa ligne, porte la valeur entiere ; les
    lecteurs de t le lisent. Rend False si t n'est pas un tel depot (ou deja dedouble)."""
    hit = [R['pos'] for R in ir.values() if R['pos'] for d in R['pos']['own']
           if d['id'] == t and d['g'] in (3, 4) and (d['f'] >> 8) & 0x1f < 16]
    new = ('S', t)
    if not hit or any(o['id'] == new for o in hit[0]['own']): return False
    X = hit[0]; d = next(o for o in X['own'] if o['id'] == t)
    X['own'].append(dict(v=d['v'], g=6, f=None, id=new))
    rn = lambda x: new if x == t else x
    for R in ir.values():
        if R['raw'] and any(tt == t for *_, tt in R['raw']): raise ValueError(f'ligne a poses lit {t}')
        if R['pos']:
            R['pos']['g1'] = [(rn(tt), s) for tt, s in R['pos']['g1']]
            for o in R['pos']['own']:
                if 'src' in o: o['src'] = (rn(o['src'][0]), o['src'][1])
        if R['polys']:
            R['polys'] = [[(p, [(rn(tt), s) for tt, s in cs], cc) for p, cs, cc in fl] for fl in R['polys']]
    return True

def _fix(ir, L):
    """Une correction pour la perte L, ou ValueError."""
    if L.kind == 'pos' and L.how != 'cache' and _split(ir, L.tag): return
    if L.how == 'cache': return _reroute(ir, L.kind, L.tag)
    X = ir[L.r][L.kind]
    cache_has = next((e for e, v in L.cache.items() if v == L.tag), None)
    if L.how == 'poly' and X:
        if L.tag in L.pre: X['g1'].append((L.tag, L.pre.index(L.tag))); return
        if cache_has is not None: X['g2'].append((cache_has, L.tag)); return
        if L.tag in L.lst:                       # valeur de la liste ecrasee par un depot de la ligne
            p = L.lst.index(L.tag)
            d = next((d for d in X['own'] if d.get('slot') == p and d['g'] == DEP_GROUP[L.kind]), None)
            if d is not None: _to_cache(ir, L.kind, _value(L.kind, d)); return
    if L.how in ('g1', 't2') and cache_has is not None and X:
        if L.how == 'g1':
            X['g1'] = [(tt, s) for tt, s in X['g1'] if tt != L.tag]; X['g2'].append((cache_has, L.tag)); return
        for o in X['own']:
            if o['g'] == 2 and o['src'][0] == L.tag:
                o['g'], o['f'], o['exp'] = 1, (o['f'] & ~0xff) | cache_has, L.tag; o.pop('src')
        return
    _to_cache(ir, L.kind, L.tag)

def ir_merge(T, ir, A, B):
    """Ligne A de ir = A puis B (meme os) : emprunts de A, cache de A puis de B (sauf valeurs de A),
    sommets groupe par groupe, polygones a la suite ; les emprunts de B au tampon disparaissent (ses
    polygones lisent les valeurs la ou elles sont). Ligne B vide."""
    _, _, cpre, _, _ = pos_flow(T); _, _, gpre, _, _ = colour_flow(T)
    RA, RB = ir[A], ir[B]
    for kind, cp, P in (('pos', cpre, 'PC'), ('col', gpre, 'PG')):
        XA, XB = RA[kind], RB[kind]
        mine = {_value(kind, d) for d in XA['own']} - {None}
        g2 = list(XA['g2'])
        for e, t in XB['g2']:
            if t == cp[A].get(e, (P, e)): g2.append((e, t))
            elif t not in mine: raise ValueError(f'{kind} : ligne {B} : cache {e} : depot partiel de A')
        RA[kind] = dict(g1=list(XA['g1']), g2=g2, own=[dict(d) for d in XA['own']] + [dict(d) for d in XB['own']])
    RA['polys'] = [a + b for a, b in zip(RA['polys'], RB['polys'])]
    ir[B] = dict(pos=None, col=None, raw=None, polys=None)

def merge_rows(T, A, B):
    """Modele TTT1 ou la piece B est fondue dans la piece A (voir MERGED), ou ValueError."""
    wa, wb = row(T, A), row(T, B)
    if wa[3:10] != wb[3:10] or any(wa[3:6]) or any(wa[7:10]): raise ValueError('pas le meme os')
    for r in (A, B):
        if not (row(T, r)[10] and row(T, r)[1] > 2 and row(T, r)[2] > 2 and row(T, r)[0] > 2):
            raise ValueError(f'ligne {r} sans maillage')
        if row(T, r - 1)[12] <= 2 or row(T, r - 1)[13] > 2: raise ValueError(f'ligne {r} : liste absente ou a poses')
        if len(SM.variants(block(T, row(T, r - 1)[12]), True)) > 1: raise ValueError('variantes')
    pre, post, cpre, cpost, _ = pos_flow(T)
    LA, LB = (SM.variants(block(T, row(T, r - 1)[12]), True)[0] for r in (A, B))
    # Lectures de B qui verraient l'etat d'avant A une fois fondues : refusees si A a change la valeur
    wA0 = {f & 0xff for f in LA['tails'][0]}; wA3 = {f & 0xff for f in LA['tails'][3]}
    if {f & 0xff for f in LB['tails'][0]} & wA3: raise ValueError('cache : depot de A relu ou recouvert par B (groupe 1)')
    if {f & 0xff for f in LB['tails'][1]} & (wA0 | wA3): raise ValueError('cache : soudure de B sur une valeur de A')
    if any(post[A][(f & 0xff) // 2 - 1] != pre[A][(f & 0xff) // 2 - 1] for f in LB['tails'][2]):
        raise ValueError('tampon : soudure de B sur une valeur de A')
    ir = ir_build(T); ir_merge(T, ir, A, B)
    tex = parse_c_ttt1(block(T, row(T, A)[2])) + parse_c_ttt1(block(T, row(T, B)[2]))
    return _assemble(T, ir, B, [A], {(A, 2): texture_bytes(sorted(tex, key=lambda x: x[0]))}, {})

def _solve(T, ir):
    seen = {}
    while True:
        try: return emit(T, ir)
        except Lost as L:
            key = (L.kind, L.tag, L.r, L.how); seen[key] = seen.get(key, 0) + 1
            if seen[key] > 30 or sum(seen.values()) > 3000: raise ValueError(str(L))
            _fix(ir, L)

def _assemble(T, ir, B, rebuilt, added, words):
    """Modele final : blocs emis (ceux des lignes `rebuilt`, et des lignes sans bloc, ajoutes),
    ligne B vide."""
    out = _solve(T, ir)
    mine = {(r - 1, 12) for r in rebuilt + [B]} | {(r, k) for r in rebuilt + [B] for k in (0, 1, 2)}
    old = {row(T, r)[k] for r, k in mine}
    keep = {row(T, r)[k] for r in range(nrows(T)) for k in (0, 1, 2, 12, 13) if (r, k) not in mine}
    keep |= {v[1] for v in words.values() if isinstance(v, tuple)}
    new = {o: b'' for o in old - keep if o > 2}
    for (r, k), b in out.items():
        o = row(T, r)[k]
        if (r, k) in mine or o <= 2: added[(r, k)] = b; continue
        ob = block(T, o)
        if ob[:len(b)] == b and not ob[len(b):].strip(b'\0'): continue
        new[o] = b + ob[len(b):] if k == 12 and ir[r + 1]['raw'] is not None else b
    words = {(B - 1, 12): 0, (B, 0): 0, (B, 1): 0, (B, 2): 0, (B, 10): 0, (B, 11): 0,
             **{(B, k): v for k, v in zip(range(3, 10), (0, 0, 0, -1, 0, 0, 0))}, **words}
    return rebuild(T, new, added, words)

# Si la liste fondue depasse le tampon (Gun Jack, Lei : 111 a 121 cases), B garde sa liste mais se
# dessine dans une place d'accessoire libre D (24..29), rattachee a la partie de A sans decalage ni
# rotation (meme os), apres la tete. Ses sommets que d'autres lignes lisent (sorties) restent calcules
# a leur place d'origine dans l'ordre : ils passent dans la liste d'une ligne hote du meme os dessinee
# avant B (A, sinon la ligne 1). Ces sommets doivent etre bruts (aucune soudure). Ses emprunts et ses
# polygones retrouvent leurs valeurs comme pour la fusion (cache au besoin).
MOVED = {}          # ligne TTT1 deplacee -> place d'accessoire (dernier convert)

def move_row(T, B, host):
    """Modele TTT1 ou la piece B se dessine en place d'accessoire (voir MOVED), ou ValueError."""
    if row(T, host)[3:10] != row(T, B)[3:10] or any(row(T, B)[3:6]) or any(row(T, B)[7:10]):
        raise ValueError('pas le meme os')
    for r in {host, B}:
        if row(T, r - 1)[12] <= 2 or row(T, r - 1)[13] > 2 or len(SM.variants(block(T, row(T, r - 1)[12]), True)) > 1:
            raise ValueError(f'ligne {r} : liste absente ou a poses')
    if not (row(T, B)[10] and row(T, B)[1] > 2 and row(T, B)[2] > 2 and row(T, B)[0] > 2): raise ValueError(f'ligne {B} sans maillage')
    D = next((d for d in range(24, nrows(T)) if not row(T, d)[10] and all(row(T, d)[k] <= 2 for k in (0, 1, 2))
              and row(T, d - 1)[12] <= 2 and row(T, d - 1)[13] <= 2), None)
    if D is None: raise ValueError('aucune place d accessoire libre')
    read = {k: {x[5] for x in f(T)[4] if x[0] != B} for k, f in (('pos', pos_flow), ('col', colour_flow))}
    ir = ir_build(T); RB = ir[B]; RH = ir[host]; moved = 0
    for kind in KINDS:
        outs = [d for d in RB[kind]['own'] if d['id'] in read[kind] or _value(kind, d) in read[kind]]
        if kind == 'pos' and any(d['g'] in (0, 1, 2) for d in outs): raise ValueError('sortie de B soudee')
        RB[kind]['own'] = [d for d in RB[kind]['own'] if d not in outs]
        RH[kind]['own'] = RH[kind]['own'] + [dict(d) for d in outs]; moved += len(outs)
    ir[D] = dict(RB); ir[B] = dict(pos=None, col=None, raw=None, polys=None)
    part = 1 if B <= 3 else 2                         # poitrine (lignes 1..3) ou bassin (4..6)
    words = {(D, 2): ('bloc', row(T, B)[2]), (D, 10): row(T, B)[10], (D, 11): row(T, B)[11],
             **{(D, k): v for k, v in zip(range(3, 10), (0, 0, 0, part, 0, 0, 0))}}
    out = _assemble(T, ir, B, [], {}, words)
    MOVED[B] = D
    return out

def merge_extra_meshes(T):
    """Fond les troisiemes maillages de la poitrine et du bassin (merge_rows) tant qu'une ligne 3 ou 5
    porte un maillage sans place PS1. Les modeles sans ces lignes ne changent pas."""
    MERGED.clear(); MOVED.clear()
    mesh = lambda t: row(T, t)[10] and row(T, t)[1] > 2
    # (ligne perdue, second maillage qui garde sa place, essais : fusion (A, B) ou deplacement (B, hote))
    for lost, second, tries in ((3, 2, (('fond', 2, 3), ('place', 3, 2), ('place', 3, 1))),
                                (5, 6, (('fond', 5, 6), ('fond', 4, 5), ('place', 5, 4)))):
        if not (mesh(lost) and mesh(second)): continue      # sans second maillage, 5 en prend la place
        why = []
        for how, x, y in tries:
            try:
                if how == 'fond': T2 = merge_rows(T, x, y); MERGED[y] = x
                else: T2 = move_row(T, x, y)
            except (ValueError, StopIteration, KeyError) as e:
                why.append(f'{how} {x} {y} : {e}'); continue
            T = T2; break
        else: print(f'ligne {lost} sans place : ' + ' ; '.join(why))
    return T

def convert(src, keep=()):
    """Essaie les placements candidats dans l'ordre ; le premier qui se convertit gagne. keep :
    lignes TTT1 d'accessoires que la borne balance avec une borne (mode 1 de son solveur,
    tools/ttt1/accessories.py keep_rows) ; quand il faut integrer une piece (plus de pieces que de
    parties 18..21), une autre qu'elles l'est, et pas sur elles, si un placement se convertit (Heihachi
    LK / RK : son pan droit, borne par la cuisse droite, suivait le pan gauche et entrait dans la
    cuisse ; F32). Sans keep, les placements de toujours. Avec
    EXACT_WELDS, les soudures a poids libres sont d'abord rendues exactes (exact_welds). Avec
    HALF_WELDS, le placement est converti deux fois : a blanc (soudures perdues, COPIED), puis sur
    le modele aux soudures moitie (half_welds) ; la conversion a blanc reste si la seconde echoue.
    Plus de pieces que de places PS1 : certaines sont d'abord repliees (fold_accessories)."""
    global KEEP
    errors = []; HALF_DONE.clear(); HALF_SKIPPED.clear(); KEEP = frozenset(keep)
    src = fold_accessories(merge_extra_meshes(src))
    for s2t, second, hosts in layouts(src):
        set_layout(s2t, second, hosts)
        EXACT_DONE.clear(); T = exact_welds(src, TORDER) if EXACT_WELDS else src
        try:
            out = convert_layout(T)
        except ValueError as e:
            errors.append(f'{sorted(s2t.items())[21:]} : {e}'); continue
        if HALF_WELDS:
            dropped = len(DROPPED); T2 = half_welds(T, TORDER)
            if T2 is not T:
                try:
                    out2 = convert_layout(T2)
                    if len(DROPPED) <= dropped: return out2
                    e = 'cache plein, soudures de lissage retirees'
                except ValueError as err: e = err
                print(f'soudures moitie abandonnees ({e})')
                HALF_SKIPPED.extend(('conversion', r, w) for _, r, _, w in HALF_DONE)
                HALF_DONE.clear(); out = convert_layout(T)
        return out
    raise ValueError('aucun placement ne se convertit :\n' + '\n'.join(errors))

HAND_ROWS = (13, 17)      # PS1 rows of the two hands (the engine's 0x80034844 callers)
REGULAR_POSES = 17        # TTT1's open -> fist progression; some characters have more poses after it


def hand_steps(ents, n):
    """Table des poses de main. Le moteur PS1 n'utilise que les indices 0..3 (ouverte,
    deux demi-poses, poing ferme ; 4 et plus = poses speciales, la pose 0 chez Jin). TTT1
    range 17 poses en progression reguliere ouvert -> poing : recopiees telles quelles,
    l'indice 3 n'etait qu'a un quart de la fermeture et les mains restaient ouvertes.
    Les quatre premiers indices prennent donc les poses 0, 1/3, 2/3 et 16 (0, 5, 11, 16) ;
    les suivants la pose 0, comme les natifs. Les listes de sommets ne changent pas.
    Baek, Lee et Ganryu ont une 18e pose, Armor King une 18e et une 19e : des poses a part
    apres la progression, la derniere plus ouverte que la pose 0 (main a plat). Le poing
    est donc la pose 16, pas la derniere."""
    if n < 8: return ents
    steps = [round(i * (min(n, REGULAR_POSES) - 1) / 3) for i in range(4)]
    return [ents[s] for s in steps] + [ents[0]] * (len(ents) - 4)


def convert_layout(src):
    T = src; ALLOC.clear(); G2_READS.clear(); DROPPED.clear(); SLOTMAP.clear()
    HALF['c'].clear(); HALF['s'].clear(); HALF['moved'] = 0; WELDS.clear(); COPIED.clear()
    times = plan_cache(T, TORDER)
    blocks = bytearray(); rows = {}; relocs = [16]
    def put(b):
        off = HDR + len(blocks); blocks.extend(pad4(b)); return off
    # blocs de positions : une entree par ligne TTT1 porteuse (avec ses variantes)
    pos_off = {}
    for t in [rd - 1 for rd in TORDER]:                  # ordre de DESSIN : etat moitie / entier
        w = row(T, t)
        if w[12] <= 2: continue
        if t + 1 not in times: continue
        vs = rewired(T, t + 1)
        if t + 1 in [S2T[r] for r in BAKED]:
            sb = next(r for r in BAKED if S2T[r] == t + 1)
            vs = [bake(T, t + 1, a, HOSTROW.get(sb)) for a in vs]
        CUR_T[0] = times[t + 1]
        rd = t + 1; od = TORDER
        prev_rd = natural_prev(rd)                          # la liste que ses emprunts designent
        snap = (dict(HALF['c']), dict(HALF['s']))
        pos_off[t] = [put(convert_positions(a, rd, prev_rd, half=(dict(snap[0]), dict(snap[1])))) for a in vs]
        convert_positions(vs[0], rd, prev_rd, track=True)       # etat moitie / entier apres la ligne
    for s in range(NROWS):
        t = S2T[s]; w = list(row(T, t)); new = [0] * 14
        new[3:12] = w[3:12]
        if s >= 21 and w[6] >= 0: new[6] = ps1_part(T, w[6], S2T, SECOND)   # parent en parties PS1
        if s >= 21 and t in head_extra_rows(T): new[3:10] = [0, 0, 0, 17, 0, 0, 0]  # os = la tete
        if s in BAKED:
            new[3:6] = [0, 0, 0]; new[7:10] = [0, 0, 0]   # os integre aux sommets
            new[6] = next(q for q, r in SECOND.items() if r == s)   # partie hote (mot 6, lu par le runtime)
        if w[0] > 2: new[0] = put(block(T, w[0]))          # normales : recopiees
        prims = double_sided(block(T, w[1]), WELDS.get(t, set())) if s in LEG_ROWS and w[1] > 2 else block(T, w[1]) if w[1] > 2 else b''
        if w[1] > 2: new[1] = put(remap_prims(prims, SLOTMAP.get(t, {})))
        if w[2] > 2: new[2] = put(convert_texture(block(T, w[2])))
        nxt = S2T.get(s + 1)
        src_t = (nxt - 1) if nxt is not None else t
        if src_t in pos_off: new[12] = pos_off[src_t][0]
        elif row(T, src_t)[12] == 2: new[12] = 2
        tab = row(T, src_t)[13]                              # la table va avec les positions qu'elle choisit
        if tab > 2 and src_t in pos_off:                     # table des poses (mains, ailes)
            e = struct.unpack_from(f'<{len(block(T, tab)) // 4}I', block(T, tab))
            olds = [x for x in SM.variants(block(T, row(T, src_t)[12]), True)]
            # decalages TTT1 des variantes -> decalages convertis
            p = row(T, src_t)[12]; starts = []
            for a in olds:
                starts.append(p)
                q = a['used']
                for bits, vals in zip((16, 16, 16, 16, 16, 8), a['tails']):
                    per = {16: 2, 8: 4}[bits]; q += 4 + 4 * ((len(vals) + per - 1) // per)
                p += q
            remap = dict(zip(starts, pos_off[src_t]))
            ents = [remap.get(x, pos_off[src_t][0]) for x in e]
            if s in HAND_ROWS: ents = hand_steps(ents, len(olds))     # not the wings
            new[13] = put(b''.join(struct.pack('<I', x) for x in ents))
            relocs += [new[13] + 4 * i for i in range(len(e))]
        rows[s] = new
        relocs += [24 + s * 56 + 4 * k for k in (0, 1, 2, 12, 13) if new[k] > 2]
    hdr = struct.pack('<6I', NROWS, struct.unpack_from('<I', T, 4)[0], 0x4B4D4433, 0, HDR - 8, 0)
    body = b''.join(struct.pack('<14I', *[x & 0xffffffff for x in rows[s]]) for s in range(NROWS))
    return hdr + body + bytes(blocks), sorted(relocs)

if __name__ == '__main__':
    src = load(sys.argv[1])
    if len(sys.argv) > 5:                                    # textures : rangement avant les UV
        tex = open(sys.argv[4], 'rb').read()
        print('textures :', texpack.plan(tex, src))
    out, rel = convert(src)
    open(sys.argv[2], 'wb').write(out)
    if len(sys.argv) > 3: open(sys.argv[3], 'wb').write(struct.pack(f'<{len(rel)}I', *rel))
    if len(sys.argv) > 5:
        open(sys.argv[5], 'wb').write(texpack.repack(tex))
        print('textures reagencees ->', sys.argv[5])
    print(f'{sys.argv[1]} -> {sys.argv[2]} : {len(out)} o, {len(rel)} relocalisations, {HALF["moved"]} soudures devenues copies')
