"""Glyphes de la police des noms PS1 (bitmaps de noms du disque US), par lettre.

Les lettres d'un nom se touchent : on coupe sur les colonnes sans encre sombre
(indices 1..5), puis, si un nom donne moins de blocs que de lettres, on scinde
le bloc le plus large a sa colonne la plus claire. Chaque nom etant dessine a la
main, une meme lettre varie d'un nom a l'autre : on garde la premiere trouvee
dans l'ordre de NAMES.
"""
import struct
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
NAMES = {161: 'KUMA', 129: 'XIAOYU', 73: 'PAUL', 81: 'LAW', 89: 'LEI', 97: 'KING',
         105: 'YOSHIMITSU', 113: 'NINA', 121: 'HWOARANG', 137: 'EDDY', 145: 'JIN',
         153: 'JULIA', 165: 'PANDA', 169: 'BRYAN', 177: 'HEIHACHI', 185: 'OGRE',
         193: 'MOKUJIN', 217: 'ANNA', 221: 'TIGER'}
INK, SURROUND, FADE = 1, 10, 6

def name_bitmap(bundle):
    off, ln = struct.unpack_from('<II', bundle, 4); sec = bundle[off:off + ln]
    fs = struct.unpack_from('<I', sec, 8)[0] + 8
    m, f, size, x, y, words, h = struct.unpack_from('<III4H', sec, fs)
    px = sec[fs + 20:fs + 8 + size]
    return Image.frombytes('L', (words * 4, h), bytes(v for c in px for v in (c & 15, c >> 4)))

def ink_components(im):
    """Composantes 8-connexes d'encre sombre (indices 1..5), de gauche a droite."""
    W, H = im.size; px = im.load()
    ink = {(x, y) for x in range(W) for y in range(H) if 1 <= px[x, y] <= 5}
    comps = []
    while ink:
        stack = [ink.pop()]; c = set(stack)
        while stack:
            x, y = stack.pop()
            for q in ((x + i, y + j) for i in (-1, 0, 1) for j in (-1, 0, 1)):
                if q in ink: ink.discard(q); c.add(q); stack.append(q)
        comps.append(c)
    return sorted(comps, key=lambda c: min(x for x, _ in c))

def split_components(im, comps):
    """Lettres qui se chevauchent en colonne sans se toucher (le pied du A sous
    la panse du P dans PAUL) : une lettre par composante, cadree sur son encre
    comme une coupe par colonne ; chaque pixel non vide du cadre va a la
    composante la plus proche, ceux des voisines sont effaces."""
    W, H = im.size; px = im.load(); out = []
    for k, c in enumerate(comps):
        s = min(x for x, _ in c); e = max(x for x, _ in c) + 1
        g = Image.new('L', (e - s, H), SURROUND); gp = g.load()
        for x in range(s, e):
            for y in range(H):
                if px[x, y] != SURROUND and min(range(len(comps)), key=lambda j: min(
                        abs(x - a) + abs(y - b) for a, b in comps[j])) == k:
                    gp[x - s, y] = px[x, y]
        out.append((s, e, g))
    return out

def segment(im, n):
    W, H = im.size; px = im.load()
    dark = [sum(1 for y in range(H) if 1 <= px[x, y] <= 5) for x in range(W)]
    runs = []; x = 0
    while x < W:
        if not dark[x]: x += 1; continue
        s = x
        while x < W and dark[x]: x += 1
        runs.append((s, x))
    cuts = []
    while len(runs) < n:
        i = max(range(len(runs)), key=lambda k: runs[k][1] - runs[k][0])
        s, e = runs[i]
        if e - s < 6: return None
        c = min(range(s + 2, e - 2), key=lambda x: dark[x])
        runs[i:i + 1] = [(s, c), (c + 1, e)]; cuts.append(c)
    if len(runs) != n: return None
    # Une coupe forcee qui tranche une composante d'encre : legitime si deux
    # lettres se touchent (XIAOYU, HEIHACHI), fausse si chaque lettre est une
    # composante a part (P et A de PAUL, PANDA ; Y de BRYAN).
    if cuts:
        comps = ink_components(im)
        if len(comps) == n and any(min(x for x, _ in cc) < c < max(x for x, _ in cc)
                                   for c in cuts for cc in comps):
            return split_components(im, comps)
    return runs

def data_track():
    """The disc's first track, as named in the cue the setup writes into disc/
    (a Redump set keeps its own file names, a split single-file dump others)."""
    import re
    cue = ROOT / 'disc/Tekken 3 (USA).cue'
    if cue.is_file():
        found = re.search(r'FILE\s+"([^"]+)"', cue.read_text(errors='replace'))
        if found and (ROOT / 'disc' / found[1]).is_file(): return ROOT / 'disc' / found[1]
    return ROOT / 'disc/Tekken 3 (USA) (Track 1).bin'

def alphabet():
    import sys; sys.path.insert(0, str(ROOT / 'tools'))
    import bns_tool
    table, _, _ = bns_tool.load_us_table(ROOT / 'disc/SLUS_004.02')
    out = {}
    with bns_tool.open_bns_source(data_track()) as arc:
        for entry, text in NAMES.items():
            im = name_bitmap(arc.read_at(table[entry].offset, table[entry].size))
            runs = segment(im, len(text))
            if not runs: continue
            for ch, r in zip(text, runs):
                s, e = r[:2]
                out.setdefault(ch, (entry, s, e, r[2] if len(r) > 2 else im.crop((s, 0, e, 16))))
    return out

# Glyphes absents de la police, dessines sur la metrique du E (barres en 1-2 et
# 13-14, fut de deux pixels) : '#' encre, '.' fond.
DRAWN = {
    'Z': ["......", "######", "######", "....##", "....##", "...##.", "...##.", "..##..",
          "..##..", ".##...", ".##...", "##....", "##....", "######", "######", "......"],
    '-': ["....", "....", "....", "....", "....", "....", "....", "####",
          "####", "....", "....", "....", "....", "....", "....", "...."],
    '.': ["..", "..", "..", "..", "..", "..", "..", "..", "..", "..", "..", "..", "..", "##", "##", ".."],
    'V': ["......", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##",
          "##..##", ".####.", ".####.", ".####.", "..##..", "..##..", "..##..", "......"],
    '2': [".....", ".###.", "##.##", "...##", "...##", "...##", "..##.", "..##.",
          ".##..", ".##..", "##...", "##...", "##...", "#####", "#####", "....."],
}

def draw(ch):
    rows = DRAWN[ch]; g = Image.new('L', (len(rows[0]), 16), SURROUND); p = g.load()
    for y, r in enumerate(rows):
        for x, c in enumerate(r):
            if c == '#': p[x, y] = INK
            elif 0 < y < 15 and rows[y - 1][x] == '#' and rows[y + 1][x] != '#': p[x, y] = FADE
    return g

def name_image(text, max_width=76):
    """Bitmap 16 px de haut, largeur multiple de 4. Espace inter-lettres reduit
    si le nom depasse max_width (76 px, le plus long nom d origine : YOSHIMITSU)."""
    abc = alphabet(); glyphs = []; prov = {}
    for ch in text:
        if ch == ' ': glyphs.append(None); continue          # espace : largeur choisie plus bas
        if ch in abc:
            e, s, t, g = abc[ch]; glyphs.append(g); prov[ch] = dict(bns_entry=e, columns=[s, t])
        elif ch in DRAWN:
            glyphs.append(draw(ch)); prov[ch] = 'dessine'
        else:
            raise ValueError(f'lettre {ch!r} absente de la police et non dessinee')
    for gap, margin, space in ((1, 1, 3), (0, 1, 3), (0, 0, 2), (0, 0, 1)):
        # Espace transparent : un bloc de contour plein restait visible entre
        # les mots (plaque DEVIL JIN).
        glyphs = [g if g is not None else Image.new('L', (space, 16), 0) for g in
                  [None if (c == ' ') else g for c, g in zip(text, glyphs)]]
        width = margin * 2 + sum(g.width for g in glyphs) + gap * (len(glyphs) - 1)
        width = (width + 3) // 4 * 4
        if width <= max_width: break
    else:
        raise ValueError(f'{text} : {width} px, plus que {max_width}')
    # Hors des lettres (marge, espace inter-lettres, complement a 4) : le
    # contour seulement contre un pixel non transparent d'une lettre voisine,
    # transparent (0) ailleurs, comme les noms d'origine ; un fond plein
    # dessinait une barre contre les bords ouverts (haut du L, du J).
    img = Image.new('L', (width, 16), 0); x = margin; owner = [False] * width
    for c, g in zip(text, glyphs):
        img.paste(g, (x, 0)); owner[x:x + g.width] = [c != ' '] * g.width; x += g.width + gap
    px = img.load()
    for x in range(width):
        if owner[x]: continue
        for y in range(16):
            if any(0 <= n < width and owner[n] and px[n, y] for n in (x - 1, x + 1)): px[x, y] = SURROUND
    return img, prov

def sheet(path):
    abc = alphabet(); order = sorted(abc) + sorted(DRAWN)
    S = 8; W = sum(((abc[c][3] if c in abc else draw(c)).width) * S + 10 for c in order)
    out = Image.new('L', (W, 16 * S), 0); x = 0
    for c in order:
        g = abc[c][3] if c in abc else draw(c)
        out.paste(g.point(lambda p: min(255, p * 17)).resize((g.width * S, 16 * S), Image.Resampling.NEAREST), (x, 0))
        x += g.width * S + 10
    out.save(path); return ''.join(order)
