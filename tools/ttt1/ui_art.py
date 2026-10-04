"""Images d'interface d'un personnage, reprises de TTT1.

- grand portrait de l'ecran de chargement : 152 x 256 px, 256 couleurs ;
- vignette de la grille de selection : 64 x 32 px, 256 couleurs.

Les deux viennent de la ROM (tools/ttt1/rom_ram.py, thumbnail de
tools/data/ttt1_characters.json).
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps



def rgba(data, w, h, pal, clear_zero=True):
    """Pixels 8 bits (w demi-mots de large) -> image RGBA ; couleur 0 transparente."""
    P = np.array(pal, dtype=np.uint16)[np.frombuffer(data[:w * h * 2], dtype=np.uint8)].reshape(h, w * 2)
    r, g, b = ((P & 31) << 3), (((P >> 5) & 31) << 3), (((P >> 10) & 31) << 3)
    a = np.where((P == 0) & clear_zero, 0, 255)
    return Image.fromarray(np.stack([r, g, b, a], 2).astype(np.uint8), 'RGBA')


BACKGROUND = (54, 24, 90)       # fond des vignettes, celui des invites precedents


def head_crop(portrait, w, h, frac=0.85):
    """Case de grille : la tete du grand portrait, cadre w x h, 85 % de sa largeur."""
    A = np.asarray(portrait)[:, :, 3] > 0; ys, xs = np.nonzero(A); top = ys.min()
    cw = round(portrait.width * frac); ch = round(cw * h / w)
    cols = np.nonzero(A[top:top + ch // 2].any(0))[0]; cx = (cols.min() + cols.max()) // 2
    x0 = max(0, min(portrait.width - cw, cx - cw // 2)); y0 = max(0, top - 6)
    im = portrait.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), BACKGROUND + (255,)); out.alpha_composite(im)
    return out


def thumb_tile(thumb, w, h):
    """Case de grille depuis la vignette TTT1 (42 x 27) : les cases T3 ont des
    pixels deux fois moins hauts (44 x 58 s'affiche comme 44 x 29), donc la
    vignette est remise a l'echelle sur w x h/2, recadree au centre si la case
    est plus haute qu'elle, puis doublee en hauteur."""
    t = thumb.convert('RGBA').crop(thumb.getbbox() or (0, 0, 42, 27))
    vh = h / 2
    k = max(w / t.width, vh / t.height)
    sw, sh = max(w, round(t.width * k)), max(round(vh), round(t.height * k))
    t = t.resize((sw, sh), Image.LANCZOS)
    x0, y0 = (sw - w) // 2, (sh - round(vh)) // 2
    return t.crop((x0, y0, x0 + w, y0 + round(vh))).resize((w, h), Image.LANCZOS)


# Cadrages deja trouves par thumb_search, par empreinte des deux images : la
# ROM est verifiee puce par puce, donc les captures -- et le cadrage -- sont les
# memes chez tout le monde. Des nombres seulement, aucune donnee du jeu.
KNOWN_BOXES = Path(__file__).resolve().parents[1] / 'data/ttt1_thumb_boxes.json'


def image_key(*images):
    import hashlib
    h = hashlib.sha256()
    for im in images: h.update(repr((im.mode, im.size)).encode()); h.update(im.tobytes())
    return h.hexdigest()


def thumb_box(portrait, thumb):
    """thumb_search, sans refaire la recherche pour des images deja vues."""
    import json
    known = json.loads(KNOWN_BOXES.read_text()) if KNOWN_BOXES.is_file() else {}
    hit = known.get(image_key(portrait, thumb))
    if hit: return hit[0], hit[1], tuple(hit[2])
    return thumb_search(portrait, thumb)


def thumb_search(portrait, thumb):
    """Cadrage de la vignette de grille TTT1 dans le grand portrait de chargement.

    Meme rendu, mais en miroir et a demi-resolution verticale : on cherche le
    rectangle du portrait (retourne ou non) qui, reduit a 42 x 27, ressemble le
    plus a la vignette (correlation par canal, bords gris de la vignette
    ignores). Renvoie (score, miroir, (x0, y0, x1, y1)) en pixels du portrait."""
    PAD = 100
    bg = Image.new('RGBA', (portrait.width + 2 * PAD, portrait.height + 2 * PAD), (0, 0, 0, 255))
    bg.alpha_composite(portrait, (PAD, PAD)); B = bg.convert('RGB')
    T = thumb.convert('RGB').crop(thumb.getbbox() or (0, 0, 42, 27)).resize((42, 27))
    best = (-1.0, False, None)
    for mirror in (True, False):
        t = np.asarray(ImageOps.mirror(T) if mirror else T, dtype=np.float32)[:, 4:38]
        t = (t - t.mean((0, 1))) / (t.std((0, 1)) + 1e-6)

        def score(cx, cy, bw, bh):
            box = (PAD + cx - bw / 2, PAD + cy - bh / 2, PAD + cx + bw / 2, PAD + cy + bh / 2)
            if bw < 8 or bh < 8 or box[0] < 0 or box[1] < 0 or box[2] > B.width or box[3] > B.height: return -1.0
            q = np.asarray(B.resize((42, 27), Image.BILINEAR, box=box), dtype=np.float32)[:, 4:38]
            sd = q.std((0, 1))
            if (sd < 1).any(): return -1.0
            return float(np.mean(t * (q - q.mean((0, 1))) / sd))
        c, s = None, -1.0
        for bw in range(portrait.width * 2 // 5, portrait.width + 1, 5):
            for asp in np.arange(1.0, 1.8, 0.1):
                for cx in range(0, portrait.width, 6):
                    for cy in range(0, portrait.height, 6):
                        v = score(cx, cy, bw, bw * asp)
                        if v > s: s, c = v, [cx, cy, bw, bw * asp]
        for step in (2, 1, .5):                          # affinage local
            improved = True
            while improved:
                improved = False
                for k in range(4):
                    for d in (step, -step):
                        n = list(c); n[k] += d; v = score(*n)
                        if v > s: s, c, improved = v, n, True
        if s > best[0]:
            cx, cy, bw, bh = c
            best = (s, mirror, (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))
    return best


def portrait_tile(portrait, box, w, h):
    """Case w x h prise dans le grand portrait autour du cadrage de la vignette :
    meme centre et meme largeur, hauteur ajustee a la case (les cases T3 ont la
    densite de pixels du portrait)."""
    x0, y0, x1, y1 = box; cx, cy, bw = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0
    bh = bw * h / w
    PAD = 100
    big = Image.new('RGBA', (portrait.width + 2 * PAD, portrait.height + 2 * PAD), (0, 0, 0, 0))
    big.alpha_composite(portrait, (PAD, PAD))
    face = big.resize((w, h), Image.LANCZOS, box=(PAD + cx - bw / 2, PAD + cy - bh / 2, PAD + cx + bw / 2, PAD + cy + bh / 2))
    out = tile_background(h, character_color(portrait)).convert('RGBA'); out.alpha_composite(face)
    return out


def character_color(portrait):
    """Couleur d'aplat de la case, propre a chaque personnage comme dans T3 :
    teinte moyenne du portrait, saturation et luminosite de celle de Jun."""
    import colorsys
    a = np.asarray(portrait.convert('RGBA'), dtype=np.float32); m = a[:, :, 3] > 0
    r, g, b = (a[:, :, :3][m].mean(0) / 255).tolist()
    hue = colorsys.rgb_to_hsv(r, g, b)[0]
    return tuple(round(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.64, 0.81))


def tile_background(rows, top):
    """Fond des cases : la couleur du personnage sur toute la hauteur, assombrie
    vers le bas, comme sur les cases de T3 (Jin, King, Paul : couleur visible
    sur les cotes jusqu'en bas ; les cheveux couvrent souvent le haut)."""
    bg = Image.new('RGB', (44, rows)); px = bg.load()
    for y in range(rows):
        k = 1 - 0.55 * y / max(1, rows - 1)
        for x in range(44): px[x, y] = tuple(round(c * k) for c in top)
    return bg


THUMB_MATCH = 0.6     # en dessous, le portrait n'est pas le rendu de la vignette


def t3_images(portrait, thumb=None, box=None):
    """Les cinq images du pack d'interface Tekken 3 (tailles de ui.SPECS).
    Cases de grille : la vignette TTT1 si elle est connue ; sinon le cadrage
    declare (tile_box de ttt1_characters.json, en pixels du portrait) pour les
    personnages sans vignette a eux (case partagee : Angel, Alex ; case cachee :
    Tetsujin) ; a defaut, la tete recadree sur le grand portrait."""
    big = Image.new('RGBA', (168, 252), (0, 0, 0, 0))
    scaled = portrait.resize((round(portrait.width * 252 / portrait.height), 252), Image.LANCZOS)
    big.alpha_composite(scaled, ((168 - scaled.width) // 2, 0))
    tile, how = (lambda w, h: head_crop(portrait, w, h)), 'tete recadree sur le portrait'
    if box is not None:
        tile, how = (lambda w, h: portrait_tile(portrait, box, w, h)), f'cadrage declare {tuple(box)}'
    elif thumb is not None:
        score, _, box = thumb_box(portrait, thumb)
        if score >= THUMB_MATCH:
            tile, how = (lambda w, h: portrait_tile(portrait, box, w, h)), f'cadrage de la vignette TTT1 dans le portrait (correlation {score:.2f})'
        else:
            tile, how = (lambda w, h: thumb_tile(thumb, w, h)), f'vignette TTT1 agrandie (portrait different, correlation {score:.2f})'
    images = {'portrait': big, 'selector-tall': tile(44, 68), 'selector': tile(44, 58)}
    # chargement : memes cases, pixels deux fois moins hauts (comme le jeu d'origine)
    images['loading-tall'] = images['selector-tall'].resize((44, 34), Image.LANCZOS)
    images['loading'] = images['selector'].resize((44, 29), Image.LANCZOS)
    return images, how
