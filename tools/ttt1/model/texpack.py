"""Reagencement des textures TTT1 pour le repli costume PS1 (128 x 128 demi-mots).

Le moteur PS1 n'a qu'une page de texture par joueur : 128 x 128 demi-mots,
replies en 64 x 256 (x 0..63 -> y, x 64..127 -> y + 128). Une image ne peut donc
pas chevaucher x = 64. Les atlas TTT1 debordent souvent (jusqu'a x = 160) et
certains depassent le budget de 16 384 demi-mots. plan() range les images :

1. les images d'expressions du visage du costume (table TTT1 0x801945D8, voir
   faces() de tools/ttt1_import.py : l'image affichee et ses remplacantes) ne sont
   ni transposees ni reduites, et restent en place si le reste tient autour : le
   runtime recopie l'une sur l'autre (tekken3_ttt1_face_tick(), fichier .face) ;
2. les autres restent en place quand elles tiennent, sinon elles sont rangees dans
   les zones libres (au besoin transposees : UV echanges, sans perte) ;
3. si le budget ne suffit pas, des images 256 couleurs passent en 16 couleurs
   (palette propre, dans une case de 16 couleurs qu'aucune image gardee n'utilise),
   celles qui y perdent le moins d'abord. C'est la seule perte, et elle est
   consignee dans REPORT.
4. les palettes restent dans les lignes 0..3 du joueur : une palette de l'atlas
   au-dela (ligne 4 d'Unknown, qui tombait sur les palettes du joueur 2) est
   relogee dans une case libre.
5. dernier recours, si rien de cela ne tient (Unknown costume 2 : 18 112 demi-mots
   tout reduit) : les images qu'aucun polygone ne lit sont retirees (expressions du
   visage comprises : le costume garde son visage de base, sans .face) et les autres
   rognees aux UV lus, puis on reprend en 3. Les atlas qui tenaient ne changent pas.

Les images qu'un meme polygone chevauche forment un groupe, deplace d'un bloc.
"""
import struct
from PIL import Image

W, H, FOLD = 128, 128, 64
LAYOUT = None                                      # rempli par plan()
REPORT = {}

def read_tims(t):
    out = []; p = 0
    while p + 8 <= len(t):
        mg, fl = struct.unpack_from('<II', t, p)
        if mg != 16: break
        p += 8; pal = None
        for ispal in ((True, False) if fl & 8 else (False,)):
            sz, x, y, w, h = struct.unpack_from('<I4H', t, p)
            data = list(struct.unpack_from(f'<{w*h}H', t, p + 12))
            if ispal: pal = (x, y, w, h, data)
            else: out.append(dict(bpp=fl & 3, x=x, y=y, w=w, h=h, pix=data, pal=pal))
            p += sz
    return out

def write_tim(bpp, x, y, w, h, pix, pal):
    fl = bpp | (8 if pal else 0)
    b = struct.pack('<II', 16, fl)
    if pal:
        px, py, pw, ph, pd = pal
        b += struct.pack('<I4H', 12 + pw * ph * 2, px, py, pw, ph) + struct.pack(f'<{len(pd)}H', *pd)
    b += struct.pack('<I4H', 12 + w * h * 2, x, y, w, h) + struct.pack(f'<{len(pix)}H', *pix)
    return b

def ppw_of(bpp): return 4 if bpp == 0 else 2

def pixels(tile):
    """indices de couleur, par ligne, en pixels."""
    ppw = ppw_of(tile['bpp']); rows = []
    for r in range(tile['h']):
        line = []
        for hw in tile['pix'][r * tile['w']:(r + 1) * tile['w']]:
            for k in range(ppw): line.append((hw >> (16 // ppw * k)) & ((1 << (16 // ppw)) - 1))
        rows.append(line)
    return rows

def pack_px(rows, bpp):
    ppw = ppw_of(bpp); bits = 16 // ppw; out = []
    for line in rows:
        line = line + [0] * (-len(line) % ppw)
        for i in range(0, len(line), ppw):
            out.append(sum(line[i + k] << (bits * k) for k in range(ppw)))
    return out

def clut_of(tile):
    px, py = tile['pal'][:2]
    return (py << 6) | (px >> 4)

# --- groupes -----------------------------------------------------------------

def _prims(T):
    from fmt import row, nrows, block, parse_c_ttt1
    out = []
    for r in range(nrows(T)):
        w = row(T, r)
        if w[2] > 2: out += parse_c_ttt1(block(T, w[2]))
    return out

def _hit(tile, X, v, strict):
    if strict: return tile['x'] <= X < tile['x'] + tile['w'] and tile['y'] <= v < tile['y'] + tile['h']
    return tile['x'] <= X <= tile['x'] + tile['w'] and tile['y'] <= v <= tile['y'] + tile['h']

def _corner(page, u):
    mode = (page >> 7) & 3; ppw = 4 >> mode
    return mode, (page & 15) * 64 + u // ppw

def groups(tiles, T):
    """Unions d'images qu'un meme polygone reference (meme palette, meme mode)."""
    parent = list(range(len(tiles)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for k, mat, uv in _prims(T):
        page, clut = mat >> 16, mat & 0xffff
        hit = set()
        for u, v in uv:
            mode, X = _corner(page, u)
            cands = [i for i, t in enumerate(tiles) if t['bpp'] == mode and clut_of(t) == clut and _hit(t, X, v, True)]
            # Palette du modele sans image : TTT1 dessine avec celle de la texture
            # (Devil costume 2 : memes UV que le costume 1, palettes decalees).
            cands = cands or [i for i, t in enumerate(tiles) if t['bpp'] == mode and _hit(t, X, v, True)]
            hit.update(cands[:1])
        hit = sorted(hit)
        for i in hit[1:]: parent[find(i)] = find(hit[0])
    out = {}
    for i in range(len(tiles)): out.setdefault(find(i), []).append(i)
    res = []
    for members in out.values():
        ts = [tiles[i] for i in members]
        x0, y0 = min(t['x'] for t in ts), min(t['y'] for t in ts)
        x1, y1 = max(t['x'] + t['w'] for t in ts), max(t['y'] + t['h'] for t in ts)
        if sum(t['w'] * t['h'] for t in ts) != (x1 - x0) * (y1 - y0):
            raise ValueError(f'images {[(t["x"], t["y"]) for t in ts]} liees par un polygone mais pas rectangulaires')
        res.append(dict(members=members, x=x0, y=y0, w=x1 - x0, h=y1 - y0, bpp=ts[0]['bpp']))
    return res

# --- rangement ---------------------------------------------------------------

class Grid:
    def __init__(self): self.rows = [0] * H
    def free(self, x, y, w, h):
        if x < 0 or y < 0 or x + w > W or y + h > H or (x < FOLD < x + w): return False
        m = ((1 << w) - 1) << x
        return all(not (self.rows[y + i] & m) for i in range(h))
    def take(self, x, y, w, h):
        m = ((1 << w) - 1) << x
        for i in range(h): self.rows[y + i] |= m

def _dims(g):
    """(largeur, hauteur) en demi-mots, droite puis transposee si possible."""
    ppw = ppw_of(g['bpp']); out = [(g['w'], g['h'], False)]
    if g.get('face'): return out                    # recopiee pixel a pixel sur une autre
    wpx = g['w'] * ppw
    if g['h'] % ppw == 0 and (g['h'] // ppw, wpx) != (g['w'], g['h']): out.append((g['h'] // ppw, wpx, True))
    return out

ORDERS = (lambda g: (-g['h'], -g['w']), lambda g: (-g['w'], -g['h']),
          lambda g: (-g['w'] * g['h'], -g['h']), lambda g: (-max(g['w'], g['h']), -g['w'] * g['h']))

def _place_once(gs, keep_in_place, key):
    grid = Grid(); where = {}; xs, ys = {0, FOLD}, {0}
    rest = []
    for i in sorted(range(len(gs)), key=lambda i: not gs[i].get('pinned')):
        g = gs[i]
        if (g.get('pinned') or keep_in_place) and grid.free(g['x'], g['y'], g['w'], g['h']):
            grid.take(g['x'], g['y'], g['w'], g['h']); where[i] = (g['x'], g['y'], False)
            xs.add(g['x'] + g['w']); ys.add(g['y'] + g['h'])
        elif g.get('pinned'):
            raise ValueError(f'image epinglee ({g["x"]}, {g["y"]}) hors de la zone')
        else: rest.append(i)
    for i in sorted(rest, key=lambda i: key(gs[i])):
        # coin inferieur gauche : positions candidates aux bords des images deja posees
        best = None
        for w, h, tr in _dims(gs[i]):
            for y in sorted(ys):
                for x in sorted(xs):
                    if grid.free(x, y, w, h) and (best is None or (y, x) < best[:2]):
                        best = (y, x, w, h, tr)
                        break
        if not best: return None
        y, x, w, h, tr = best
        grid.take(x, y, w, h); where[i] = (x, y, tr); xs.add(x + w); ys.add(y + h)
    return where

def _place_exact(gs, limit=300000):
    """Recherche avec retour arriere, pour les atlas serres : on remplit la
    premiere case libre (colonne par colonne) avec une image, ou on perd la
    colonne libre jusqu'au prochain obstacle, dans la limite des cases de jeu."""
    grid = Grid(); where = {}
    for i, g in enumerate(gs):
        if g.get('pinned'):
            if not grid.free(g['x'], g['y'], g['w'], g['h']): return None
            grid.take(g['x'], g['y'], g['w'], g['h']); where[i] = (g['x'], g['y'], False)
    left = [i for i in range(len(gs)) if i not in where]
    slack = W * H - sum(gs[i]['w'] * gs[i]['h'] for i in range(len(gs)))
    if slack < 0: return None
    nodes = [0]; full = (1 << W) - 1
    def first_free():
        # Premiere colonne ou une case est libre (bit a 0 dans le ET des
        # lignes), puis sa premiere case libre : le meme ordre que de balayer
        # colonne par colonne, sans tester les W x H cases une a une.
        busy = full
        for r in grid.rows: busy &= r
        cols = ~busy & full
        if not cols: return None
        x = (cols & -cols).bit_length() - 1; bit = 1 << x
        for y in range(H):
            if not grid.rows[y] & bit: return x, y
    def run_down(x, y):
        bit = 1 << x; n = 0
        while y + n < H and not grid.rows[y + n] & bit: n += 1
        return n
    def untake(x, y, w, h):
        m = ((1 << w) - 1) << x
        for k in range(h): grid.rows[y + k] &= ~m
    def dfs(slack):
        nodes[0] += 1
        if nodes[0] > limit: return False
        if not left: return True
        c = first_free()
        if c is None: return False
        x, y = c; seen = set()
        for i in sorted(left, key=lambda i: -gs[i]['w'] * gs[i]['h']):
            for w, h, tr in _dims(gs[i]):
                if (w, h) in seen or not grid.free(x, y, w, h): continue
                seen.add((w, h))
                grid.take(x, y, w, h); left.remove(i); where[i] = (x, y, tr)
                if dfs(slack): return True
                untake(x, y, w, h); left.append(i); del where[i]
        n = run_down(x, y)                               # case perdue : la colonne libre
        if n <= slack:
            grid.take(x, y, 1, n)
            if dfs(slack - n): return True
            untake(x, y, 1, n)
        return False
    return where if dfs(slack) else None

def _place(gs, keep_in_place):
    for key in ORDERS:
        where = _place_once(gs, keep_in_place, key)
        if where: return where
    return None if keep_in_place else _place_exact(gs)

def _quantize(g, tiles):
    """Groupe 8 bits -> 4 bits, 16 couleurs dont l'indice 0 transparent s'il sert.
    Rend (lignes de pixels 4 bits, palette 16, erreur quadratique moyenne)."""
    rows = [[] for _ in range(g['h'])]
    for i in g['members']:
        t = tiles[i]; px = pixels(t)
        for r in range(t['h']):
            rows[t['y'] - g['y'] + r].append((t['x'] - g['x'], px[r]))
    rows = [sum((seg for _, seg in sorted(line)), []) for line in rows]
    pal = tiles[g['members'][0]]['pal'][4]
    rgb = lambda c: ((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3)
    used = sorted(set(c for r in rows for c in r))
    clear = [c for c in used if pal[c] == 0]
    opaque = [c for c in used if pal[c] != 0]
    n = 15 if clear else 16
    im = Image.new('RGB', (max(1, len(opaque)), 1)); im.putdata([rgb(pal[c]) for c in opaque] or [(0, 0, 0)])
    q = im.quantize(colors=min(n, max(1, len(opaque))), method=Image.Quantize.MEDIANCUT)
    qp = q.getpalette(); qi = list(q.getdata())
    base = 1 if clear else 0
    newpal = [0] * 16
    for i in range(min(n, len(qp) // 3)):
        c = (qp[3*i] >> 3) | (qp[3*i+1] >> 3) << 5 | (qp[3*i+2] >> 3) << 10
        newpal[base + i] = c | 0x8000 if c == 0 else c
    m = {c: base + qi[j] for j, c in enumerate(opaque)}
    for c in clear: m[c] = 0
    err = 0
    for j, c in enumerate(opaque):
        a, b = rgb(pal[c]), qp[3*qi[j]:3*qi[j]+3]
        err += sum((x - y) ** 2 for x, y in zip(a, b)) * sum(r.count(c) for r in rows)
    npx = sum(len(r) for r in rows)
    return [[m[c] for c in r] for r in rows], newpal, err / max(1, npx)

# Palettes du joueur : x 0..255 des lignes 504 + 4 * joueur + 0..3, par cases de
# 16 couleurs. Au-dela de x = 256, la ligne 2 porte des palettes du jeu (celle du
# K.O. en (272, 506)) ; la ligne 4 est deja la premiere du joueur 2 (508 : le
# visage de Jin, noirci par les palettes de la ligne 4 de l'atlas d'Unknown).
AREA_ROWS, AREA_SLOTS = 4, 16

def _slots(pal):
    x, y, w = pal[:3]
    return [(y, k) for k in range(x // 16, (x + w + 15) // 16)]

def _palettes(tiles, gs, quant):
    """Cases de palette des images gardees (non reduites). Rend (cases libres,
    dans l'ordre d'attribution ; {(x, y, l) hors zone : (x, y) dans la zone}),
    ou None si une palette hors zone ne trouve pas de place. Une palette de
    l'atlas peut deja occuper les lignes 2 et 3 (Unknown, Baek) : une image
    reduite ne doit pas y ecrire la sienne."""
    kept = [tiles[k]['pal'] for i, g in enumerate(gs) if i not in quant for k in g['members'] if tiles[k]['pal']]
    inside = lambda s: s[0] < AREA_ROWS and s[1] < AREA_SLOTS
    taken = {s for p in kept for s in _slots(p) if all(map(inside, _slots(p)))}
    free = [(r, k) for r in (2, 3, 1, 0) for k in range(AREA_SLOTS) if (r, k) not in taken]
    moved = {}
    for p in kept:
        key = tuple(p[:3])
        if all(map(inside, _slots(p))) or key in moved: continue
        n = len(_slots(p))
        run = next(([(r, k + j) for j in range(n)] for r, k in free
                    if all((r, k + j) in free for j in range(n))), None)
        if not run: return None
        for s in run: free.remove(s)
        moved[key] = (run[0][1] * 16, run[0][0])
    return free, moved

def _pal_at(pal):
    """Palette d'une image gardee, a sa place finale."""
    if not pal: return pal
    x, y = LAYOUT['pal_moved'].get(tuple(pal[:3]), pal[:2])
    return (x, y) + tuple(pal[2:])

def _used(tiles, gs, T):
    """Rectangle (x0, y0, x1, y1) en demi-mots que les polygones lisent dans
    chaque groupe, None s'il n'est jamais lu ; meme recherche que _group_at."""
    box = [None] * len(gs)
    for k, mat, uv in _prims(T):
        page, clut = mat >> 16, mat & 0xffff
        for u, v in uv:
            mode, X = _corner(page, u); i = None
            for any_clut in (False, True):
                for strict in (True, False):
                    i = next((i for i, g in enumerate(gs) if g['bpp'] == mode and _hit(g, X, v, strict)
                              and (any_clut or clut_of(tiles[g['members'][0]]) == clut)), None)
                    if i is not None: break
                if i is not None: break
            if i is None: continue
            g = gs[i]; X, v = min(X, g['x'] + g['w'] - 1), min(v, g['y'] + g['h'] - 1)  # bord droit / bas exclu
            b = box[i] or (X, v, X + 1, v + 1)
            box[i] = (min(b[0], X), min(b[1], v), max(b[2], X + 1), max(b[3], v + 1))
    return box

def _trim(tiles, gs, T):
    """Etape 5 : retire les groupes jamais lus, rogne les autres (une image seule,
    non epinglee) a ce qu'ils lisent. Rend (images, groupes, retires, rognes)."""
    box = _used(tiles, gs, T)
    tiles = list(tiles); out = []; dropped = []; cropped = []
    for g, b in zip(gs, box):
        if b is None:
            dropped.append((g['x'], g['y'], g['w'], g['h'])); continue
        if g.get('pinned') or len(g['members']) > 1 or b == (g['x'], g['y'], g['x'] + g['w'], g['y'] + g['h']):
            out.append(g); continue
        k = g['members'][0]; t = tiles[k]
        x0, y0, x1, y1 = b
        pix = [hw for r in range(y0 - t['y'], y1 - t['y'])
               for hw in t['pix'][r * t['w'] + x0 - t['x']:r * t['w'] + x1 - t['x']]]
        tiles[k] = dict(t, x=x0, y=y0, w=x1 - x0, h=y1 - y0, pix=pix)
        cropped.append(dict(at=(g['x'], g['y']), size=(g['w'], g['h']), kept=(x0, y0, x1 - x0, y1 - y0)))
        out.append(dict(g, x=x0, y=y0, w=x1 - x0, h=y1 - y0))
    return tiles, out, dropped, cropped

def plan(tex, T, faces=()):
    """Calcule le rangement ; remap_uv() et repack() l'appliquent. faces :
    rectangles (x, y, l, h) des images d'expressions du visage, chacun une image
    entiere de l'atlas ; face_at() donne ensuite leur place."""
    tiles = read_tims(tex); gs = groups(tiles, T)
    for p in faces:
        if not any((g['x'], g['y'], g['w'], g['h']) == tuple(p) for g in gs):
            raise ValueError(f'visage : pas d image {tuple(p)} dans l atlas')
    for keep in (True, False):
        for g in gs:
            g['face'] = (g['x'], g['y'], g['w'], g['h']) in map(tuple, faces)
            # En place si le reste tient autour et sans chevaucher le repli (Alex,
            # 32 x 32 en (40, 96)), sinon rangee comme les autres.
            g['pinned'] = keep and g['face'] and g['x'] + g['w'] <= W and g['y'] + g['h'] <= H \
                and not g['x'] < FOLD < g['x'] + g['w']
        try:
            return _plan(tiles, gs)
        except ValueError as e:
            if 'ne tiennent pas' not in str(e): raise
        if not faces: break
    for g in gs: g['face'] = g['pinned'] = False    # etape 5 : sans expressions
    tiles, gs, dropped, cropped = _trim(tiles, gs, T)
    report = _plan(tiles, gs, halve=True)
    report.update(dropped=dropped, cropped=cropped)
    LAYOUT['dropped'] = dropped
    return report

def _halve(g, tiles, axis):
    """Image 16 couleurs (seule dans son groupe) a moitie de resolution sur un
    axe ('h' : lignes, 'w' : colonnes) : moyenne des paires de pixels, ramenee a
    la couleur la plus proche de sa propre palette. Rend (lignes, erreur), erreur
    comme _quantize (ecart quadratique par pixel d'origine)."""
    t = tiles[g['members'][0]]; pal = t['pal'][4]; px = pixels(t)
    if axis == 'w': px = [list(c) for c in zip(*px)]
    rgb = lambda c: ((c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3)
    opaque = [k for k in range(len(pal)) if pal[k] != 0]
    out = []; err = 0
    for r in range(0, len(px), 2):
        pair = px[r:r + 2]; line = []
        for cs in zip(*pair):
            solid = [c for c in cs if pal[c] != 0]
            if not solid: line.append(cs[0]); continue
            m = [sum(rgb(pal[c])[j] for c in solid) / len(solid) for j in range(3)]
            k = min(opaque, key=lambda k: sum((a - b) ** 2 for a, b in zip(rgb(pal[k]), m)))
            err += sum(sum((a - b) ** 2 for a, b in zip(rgb(pal[c]), rgb(pal[k]))) for c in solid)
            line.append(k)
        out.append(line)
    if axis == 'w': out = [list(c) for c in zip(*out)]
    return out, err / max(1, sum(len(r) for r in px))

def _plan(tiles, gs, halve=False):
    """Etapes 1 a 4 ; avec halve (etape 5), une image 16 couleurs peut aussi
    passer a moitie de resolution sur un axe : reductions et moities dans un
    seul ordre, celles qui perdent le moins d'abord (un visage 256 couleurs
    perd plus en 16 couleurs qu'une meche de cheveux a moitie de hauteur). Tant
    que les palettes ne tiennent pas, seule une reduction aide."""
    global LAYOUT
    quant = {}                                       # indice de groupe -> (lignes 4 bits, palette, erreur)
    half = {}                                        # indice de groupe -> (axe, lignes 4 bits, erreur)
    cands = [i for i, g in enumerate(gs) if g['bpp'] == 1 and not g.get('face')]
    errs = {i: _quantize(gs[i], tiles)[2] for i in cands}
    scored = sorted(cands, key=errs.get)
    halves = []
    if halve:
        for i, g in enumerate(gs):
            if g['bpp'] != 0 or g.get('face') or len(g['members']) > 1: continue
            halves.append(min(((a,) + _halve(g, tiles, a) for a in 'hw'), key=lambda h: h[2]) + (i,))
        halves.sort(key=lambda h: h[2])
    while True:
        # Les palettes aussi doivent tenir : Unknown remplit les lignes 0..3 de
        # quatre palettes 256 couleurs et en a quatre de plus en ligne 4. Reduire
        # toutes les images d'une palette 256 couleurs libere sa ligne.
        pals = _palettes(tiles, gs, quant)
        view = []
        for i, g in enumerate(gs):
            if i in quant: view.append(dict(g, bpp=0, w=g['w'] // 2 + g['w'] % 2))
            elif i in half:
                rows = half[i][1]
                view.append(dict(g, w=(len(rows[0]) + 3) // 4, h=len(rows)))
            else: view.append(g)
        where = pals and len(pals[0]) >= len(quant) and (_place(view, True) or _place(view, False))
        if where: break
        pal_ok = pals and len(pals[0]) >= len(quant)
        if halves and pal_ok and (not scored or halves[0][2] < errs[scored[0]]):
            a, rows, err, i = halves.pop(0); half[i] = (a, rows, err); continue
        if scored: i = scored.pop(0); quant[i] = _quantize(gs[i], tiles); continue
        raise ValueError('textures : ne tiennent pas, meme reduites en 16 couleurs' if pal_ok
                         else 'textures : plus de palette libre dans les lignes du joueur')
    free, pal_moved = pals
    for i, (r, k) in zip(list(quant), free): quant[i] = quant[i][:3] + ((r << 6) | k,)
    LAYOUT = dict(tiles=tiles, groups=view, src=gs, where=where, quant=quant, half=half, pal_moved=pal_moved)
    moved = [(g['x'], g['y']) for i, g in enumerate(gs) if where[i][:2] != (g['x'], g['y']) or where[i][2]]
    REPORT.clear(); REPORT.update(
        total=sum(t['w'] * t['h'] for t in tiles), moved=moved,
        transposed=[(gs[i]['x'], gs[i]['y']) for i in where if where[i][2]],
        palettes_moved={f'{k[0]},{k[1]}': v for k, v in pal_moved.items()},
        reduced=[dict(at=(gs[i]['x'], gs[i]['y']), size=(gs[i]['w'], gs[i]['h']), rms=round(q[2] ** 0.5, 1))
                 for i, q in quant.items()])
    if half:
        REPORT['halved'] = [dict(at=(gs[i]['x'], gs[i]['y']), size=(gs[i]['w'], gs[i]['h']), axis=a, rms=round(e ** 0.5, 1))
                            for i, (a, _, e) in half.items()]
    return REPORT

def face_at(x, y, w, h):
    """Place finale (x, y) de l'image de visage (x, y, l, h) (plan() doit avoir tourne),
    None si l'etape 5 a retire les expressions."""
    if 'dropped' in LAYOUT: return None
    i = next(i for i, g in enumerate(LAYOUT['src']) if (g['x'], g['y'], g['w'], g['h']) == (x, y, w, h))
    dx, dy, tr = LAYOUT['where'][i]
    # Une seule image, telle quelle : le runtime la cherche entiere dans le .tim.
    assert LAYOUT['src'][i]['face'] and not tr and len(LAYOUT['src'][i]['members']) == 1
    return dx, dy

def _group_at(page, clut, u, v):
    mode, X = _corner(page, u)
    gs = LAYOUT['src']
    for any_clut in (False, True):                  # voir groups() : palette de la texture
        for strict in (True, False):
            for i, g in enumerate(gs):
                if g['bpp'] != mode: continue
                if not any_clut and clut_of(LAYOUT['tiles'][g['members'][0]]) != clut: continue
                if _hit(g, X, v, strict): return i, mode, X
    raise ValueError(f'UV ({u}, {v}) page {page:#x} palette {clut:#x} hors de toute image')

def remap_uv(page, clut, u, v):
    """(page TTT1, palette, u, v) -> (mode, palette, X demi-mot absolu, sous-pixel, Y) apres reagencement."""
    mode = (page >> 7) & 3; ppw = 4 >> mode
    if LAYOUT is None: return mode, clut, (page & 15) * 64 + u // ppw, u % ppw, v
    i, mode, X = _group_at(page, clut, u, v); g = LAYOUT['src'][i]
    clut = clut_of(dict(pal=_pal_at(LAYOUT['tiles'][g['members'][0]]['pal'])))   # celle de l'image, que TTT1 utilise
    px, py = (X - g['x']) * ppw + u % ppw, v - g['y']            # pixel dans le groupe
    dx, dy, tr = LAYOUT['where'][i]
    if i in LAYOUT['quant']: mode, ppw, clut = 0, 4, LAYOUT['quant'][i][3]
    if i in LAYOUT.get('half', {}):
        if LAYOUT['half'][i][0] == 'h': py //= 2
        else: px //= 2
    if tr: px, py = py, px
    return mode, clut, dx + px // ppw, px % ppw, dy + py

def _tim(bpp, x, y, w, h, pix, pal):
    """write_tim, sauf une image 16 x 64 en (0, 0) apres l'etape 5 : l'ancienne
    tekken3_ttt1_face() y prenait l'expression du visage de Jun et la recopiait
    en (16, 64). Ecrite en deux moities, elle n'est pas reconnue par un runtime
    d'avant les fichiers .face (le runtime actuel ne lit que ceux-ci)."""
    if LAYOUT.get('dropped') and (x, y, w, h) == (0, 0, 16, 64):
        return write_tim(bpp, x, y, w, 32, pix[:w * 32], pal) + write_tim(bpp, x, y + 32, w, 32, pix[w * 32:], pal)
    return write_tim(bpp, x, y, w, h, pix, pal)

def repack(tex):
    """Ecrit les images a leur nouvelle place (plan() doit avoir tourne)."""
    L = LAYOUT; out = b''
    for i, g in enumerate(L['src']):
        dx, dy, tr = L['where'][i]
        if i in L.get('half', {}):
            rows = L['half'][i][1]; t = L['tiles'][g['members'][0]]
            if tr: rows = [list(c) for c in zip(*rows)]
            out += _tim(0, dx, dy, (len(rows[0]) + 3) // 4, len(rows), pack_px(rows, 0), _pal_at(t['pal']))
            continue
        if i in L['quant']:
            rows, pal, _, clut = L['quant'][i]
            if tr: rows = [list(c) for c in zip(*rows)]
            wpx = len(rows[0]); w = (wpx + 3) // 4
            out += _tim(0, dx, dy, w, len(rows), pack_px(rows, 0), ((clut & 63) * 16, clut >> 6, 16, 1, pal))
            continue
        for k in g['members']:
            t = L['tiles'][k]
            if not tr:
                out += _tim(t['bpp'], dx + t['x'] - g['x'], dy + t['y'] - g['y'], t['w'], t['h'], t['pix'], _pal_at(t['pal']))
                continue
            ppw = ppw_of(t['bpp']); rows = pixels(t)
            trows = [list(c) for c in zip(*rows)]                  # (x, y) -> (y, x)
            ox, oy = (t['y'] - g['y']), (t['x'] - g['x']) * ppw    # pixel d'origine dans le groupe transpose
            out += _tim(t['bpp'], dx + ox // ppw, dy + oy, t['h'] // ppw, len(trows), pack_px(trows, t['bpp']), _pal_at(t['pal']))
    return out
