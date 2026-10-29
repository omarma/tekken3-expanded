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
    return [t for t in range(nrows(T)) if row(T, t)[10] and row(T, t)[1] > 2 and t not in S2T.values()]

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

def convert(src):
    """Essaie les placements candidats dans l'ordre ; le premier qui se convertit gagne. Avec
    HALF_WELDS, le placement est converti deux fois : a blanc (soudures perdues, COPIED), puis sur
    le modele aux soudures moitie (half_welds) ; la conversion a blanc reste si la seconde echoue."""
    errors = []; HALF_DONE.clear(); HALF_SKIPPED.clear()
    for s2t, second, hosts in layouts(src):
        set_layout(s2t, second, hosts)
        try:
            out = convert_layout(src)
        except ValueError as e:
            errors.append(f'{sorted(s2t.items())[21:]} : {e}'); continue
        if HALF_WELDS:
            dropped = len(DROPPED); T2 = half_welds(src, TORDER)
            if T2 is not src:
                try:
                    out2 = convert_layout(T2)
                    if len(DROPPED) <= dropped: return out2
                    e = 'cache plein, soudures de lissage retirees'
                except ValueError as err: e = err
                print(f'soudures moitie abandonnees ({e})')
                HALF_SKIPPED.extend(('conversion', r, w) for _, r, _, w in HALF_DONE)
                HALF_DONE.clear(); out = convert_layout(src)
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
