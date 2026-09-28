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
    for mode in ('same', 'rigid', 'head'):
        yield from _layouts(T, heads, mode)

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

def _layouts(T, heads, mode):
    from itertools import combinations
    acc = heads + accessory_rows(T)
    if len(acc) > len(ACC_ROWS) + len(BAKE_ROWS):
        raise ValueError(f'{len(acc)} os d accessoires, {len(ACC_ROWS) + len(BAKE_ROWS)} places')
    for k in range(max(0, len(acc) - len(ACC_ROWS)), len(BAKE_ROWS) + 1):
        for baked in combinations([t for t in acc if t not in heads], k):
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
                    sib = [u for u in sib if P2R.index(next(k for k, v in s2t.items() if v == u)) not in second]
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
        # costume 3) ; les autres restent lisibles.
        over = set()
        for x in between:
            for rx in rewired(T, x):
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
            dead = gi == 3 and (CUR_T[0] + 1.5, low, 'w') not in ALLOC   # depot jamais relu, cache plein
            if dead: fate[v] = ('drop',)
            elif gi == 1 and j in drops: fate[v] = ('drop',)
            elif gi in (0, 1) and not hc.get(low, False): fate[v] = ('g2', 2 * ps1_entry(low, 'r', 1))
            elif gi == 2 and not hs.get(low, False): fate[v] = ('g1', remap_slot_byte(low, pm))
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

def convert_texture(c):
    prims = parse_c_ttt1(c)
    mats = []; uvs = []; stream = []
    fam_counts = [0, 0, 0, 0]
    for k, mat, uv in prims:
        page, clut = mat >> 16, mat & 0xffff
        idx = []; pm = None
        for u, v in uv:
            mode, cl, X, sub, Y = texpack.remap_uv(page, clut, u, v)   # images hors repli deplacees
            ppw = 4 >> mode
            pm = (cl & 0x7fff) | (0x8000 if mode == 1 else 0)
            Yf = Y + (128 if X >= 64 else 0); Xf = X % 64                # repli de la bande costume
            e = ((Xf * ppw + sub) & 255) | ((Yf & 255) << 8)
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
    return [t for t in range(nrows(T)) if row(T, t)[10] and row(T, t)[1] > 2 and t not in S2T.values()]

def convert(src):
    """Essaie les placements candidats dans l'ordre ; le premier qui se convertit gagne."""
    errors = []
    for s2t, second, hosts in layouts(src):
        set_layout(s2t, second, hosts)
        try:
            return convert_layout(src)
        except ValueError as e:
            errors.append(f'{sorted(s2t.items())[21:]} : {e}')
    raise ValueError('aucun placement ne se convertit :\n' + '\n'.join(errors))

def convert_layout(src):
    T = src; ALLOC.clear(); G2_READS.clear(); DROPPED.clear(); SLOTMAP.clear()
    HALF['c'].clear(); HALF['s'].clear(); HALF['moved'] = 0
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
        if w[1] > 2: new[1] = put(remap_prims(block(T, w[1]), SLOTMAP.get(t, {})))
        if w[2] > 2: new[2] = put(convert_texture(block(T, w[2])))
        nxt = S2T.get(s + 1)
        src_t = (nxt - 1) if nxt is not None else t
        if src_t in pos_off: new[12] = pos_off[src_t][0]
        elif row(T, src_t)[12] == 2: new[12] = 2
        if w[13] > 2 and src_t in pos_off:                   # table des poses de main
            e = struct.unpack_from(f'<{len(block(T, w[13])) // 4}I', block(T, w[13]))
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
            new[13] = put(b''.join(struct.pack('<I', remap.get(x, pos_off[src_t][0])) for x in e))
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
