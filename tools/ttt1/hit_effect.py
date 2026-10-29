"""Effet de coup fort d'un personnage TTT1 -> paquet d'effet au format Tekken 3.

TTT1 (releve en VRAM, tools/ttt1_hit_effect_capture.lua) : deux pages 256 x 256
en 4 bits cote a cote, 16 images 64 x 64 chacune rangees 4 par ligne, pages
(512, 256) puis (576, 256) du joueur 1, palette 16 couleurs en (512, 64).
L'effet joue les images de la premiere page puis celles de la seconde, une par
trame : 30 en tout pour la plupart (Lee, Jack-2), les 10 dernieres eteintes par
la couleur de sommet (0x80 -> 0x21) ; images vides comprises (0 pour l'eclair
des Mishima, 3 pour les etincelles de Roger / Alex). Releve par
tools/ttt1_hit_effect_order.lua (issue #14 : seule la premiere page etait lue,
l'effet perdait sa fin, l'explosion centrale des Jacks par exemple).

Tekken 3 : dans le fichier de chaque personnage, une suite de TIM 4 bits, un
par image : palette 16 x 1 puis image 32 x 32 (8 x 32 demi-mots), coordonnees
a zero (le chargeur les place : colonnes 368/376 pour le joueur 1, 496/504
pour le joueur 2, image k en colonne k % 2 et ligne k // 2 ; palette en
(16 * joueur, 503)). Seule la palette de la premiere image garde le bit de
semi-transparence, comme dans les paquets d'origine. T3 joue tout le paquet,
une image par trame, et eteint lui-meme les 10 dernieres comme TTT1 ; sa
longueur vient d'une table par personnage (22 ou 30, src/tekken3_ttt1_roster.c,
effect_headers) : le paquet a la longueur de l'effet TTT1, image pour image.
"""
import struct
import numpy as np
from PIL import Image

T3_FRAMES = 30                                   # longueur par defaut ; les Mishima 22 (hit_frames)
SHEET_X, SHEET_Y, CLUT_X, CLUT_Y = 512, 256, 512, 64
SHEET_X2, CLUT_X2 = 640, 528                     # joueur 2 : planche et palette plus a droite


def sheet(vram_bytes, player=0):
    """(indices 256 x 512 : les deux pages, palette 16) de l'effet du joueur 1
    (player 0) ou du joueur 2 (player 1, le CPU : Unknown au combat final) dans
    la VRAM TTT1."""
    V = np.frombuffer(vram_bytes, np.uint16).reshape(1024, 1024)
    sx, cx = (SHEET_X2, CLUT_X2) if player else (SHEET_X, CLUT_X)
    blk = V[SHEET_Y:SHEET_Y + 256, sx:sx + 128]
    idx = np.stack([(blk >> (4 * k)) & 15 for k in range(4)], -1).reshape(256, 512)
    pal = V[CLUT_Y, cx:cx + 16].copy()
    if not idx.any() or not pal.any(): raise ValueError('planche d effet vide')
    return idx.astype(np.uint8), pal


def rgb(pal):
    p = pal.astype(np.int32)
    return np.stack([(p & 31) << 3, ((p >> 5) & 31) << 3, ((p >> 10) & 31) << 3], -1).astype(np.float32)


def shrink(idx64, pal):
    """Image 64 x 64 indexee -> 32 x 32 dans la meme palette : moyenne des
    couleurs par blocs 2 x 2, puis couleur la plus proche. Les pixels vides
    (couleur 0x0000, non dessinee) restent vides si le bloc l'est en majorite."""
    col = rgb(pal)
    empty = pal == 0
    c = col[idx64].reshape(32, 2, 32, 2, 3)
    e = empty[idx64].reshape(32, 2, 32, 2)
    n = (~e).sum((1, 3))
    avg = (c * (~e)[..., None]).sum((1, 3)) / np.maximum(n, 1)[..., None]
    usable = np.nonzero(~empty)[0]
    d = ((avg[:, :, None, :] - col[usable][None, None]) ** 2).sum(-1)
    out = usable[d.argmin(-1)].astype(np.uint8)
    if empty.any(): out[n < 2] = np.nonzero(empty)[0][0]
    return out


def image(idx, k):
    """Image k de l'effet (0..31) : page k // 16, rang (k % 16) // 4, colonne k % 4."""
    x, y = (k // 16) * 256 + (k % 4) * 64, (k % 16) // 4 * 64
    return idx[y:y + 64, x:x + 64]


def frames(idx, pal, count=T3_FRAMES):
    return [shrink(image(idx, k), pal) for k in range(count)]


def tim(img32, pal):
    data = bytearray()
    for row in img32:
        for x in range(0, 32, 2): data.append(int(row[x]) | int(row[x + 1]) << 4)
    clut = struct.pack('<I4H', 12 + 32, 0, 0, 16, 1) + struct.pack('<16H', *(int(v) for v in pal))
    image = struct.pack('<I4H', 12 + len(data), 0, 0, 8, 32) + bytes(data)
    return struct.pack('<2I', 0x10, 8) + clut + image


def t3_pack(vram_bytes, player=0, count=T3_FRAMES):
    """Paquet d'effet T3 (TIM a la suite, count images) depuis la VRAM TTT1 du
    joueur 1 ou 2."""
    idx, pal = sheet(vram_bytes, player)
    first = pal.copy()
    rest = pal & 0x7fff
    return b''.join(tim(f, first if k == 0 else rest) for k, f in enumerate(frames(idx, pal, count)))


HFX_MAGIC, HFX_VERSION, HFX_SIZE = b'HFX6', 1, 64
HFX_PALETTE_FADE = 1                             # drapeau : fondu par les palettes, pas par la couleur de sommet


def hfx_pack(vram_bytes, player=0, count=T3_FRAMES, order=None, palette=None):
    """Paquet 64 x 64 (F12) : les images TTT1 telles quelles, que le runtime
    met en VRAM haute (src/tekken3_ttt1_combat.c, hit_effect_64) au lieu du
    32 x 32 du paquet T3, qui reste le repli. Little-endian :

      char[4] 'HFX6', u16 version 1, u16 images n, u16 cote (64),
      u16 palettes p (1 : commune ; n : une par image), u16 drapeaux
      (bit 0 : fondu par les palettes, la couleur de sommet reste a 0x80),
      u16 0 ; puis p palettes de 16 couleurs ; puis n images 4 bits, 32 octets
      par ligne (pixel de gauche dans le quartet bas), 64 lignes.

    TTT1 : une palette, le fondu des 10 dernieres par la couleur de sommet
    comme T3. Les etincelles de TTT PS2 (F13) ont une palette par image.
    order : les images de la planche dans cet ordre (le brouillard de TTT1,
    pris dans la planche de la fumee) ; palette : 16 couleurs a la place de
    celle de la planche."""
    idx, pal = sheet(vram_bytes, player)
    if palette is not None: pal = np.frombuffer(palette, '<u2')
    order = list(range(count)) if order is None else order
    head = struct.pack('<4s6H', HFX_MAGIC, HFX_VERSION, len(order), HFX_SIZE, 1, 0, 0)
    images = b''.join((im[:, 0::2] | im[:, 1::2] << 4).astype(np.uint8).tobytes()
                      for im in (image(idx, k) for k in order))
    return head + pal.astype('<u2').tobytes() + images


def hfx_preview(pack, scale=2):
    """Planche de controle d'un paquet 64 x 64 (fond noir)."""
    magic, _, n, size, p, _, _ = struct.unpack_from('<4s6H', pack)
    pals = np.frombuffer(pack, '<u2', 16 * p, 16).reshape(p, 16)
    o = 16 + 32 * p
    out = Image.new('RGB', (n * (size + 2), size))
    for k in range(n):
        raw = np.frombuffer(pack, np.uint8, size * size // 2, o + k * size * size // 2)
        ix = np.stack([raw & 15, raw >> 4], -1).reshape(size, size)
        out.paste(Image.fromarray(rgb(pals[k if p > 1 else 0])[ix].astype(np.uint8)), (k * (size + 2), 0))
    return out.resize((out.width * scale, size * scale), Image.NEAREST)


def preview(pack, scale=4):
    """Planche de controle des images du paquet (fond noir, melange additif)."""
    out, o = [], 0
    while o < len(pack):
        pal = np.array(struct.unpack_from('<16H', pack, o + 20), np.uint16)
        raw = np.frombuffer(pack[o + 64:o + 64 + 512], np.uint8)
        ix = np.stack([raw & 15, raw >> 4], -1).reshape(32, 32)
        out.append(Image.fromarray(rgb(pal | 0)[ix].astype(np.uint8)))
        o += 64 + 512
    sheet_im = Image.new('RGB', (len(out) * 34, 32))
    for k, im in enumerate(out): sheet_im.paste(im, (k * 34, 0))
    return sheet_im.resize((sheet_im.width * scale, 32 * scale), Image.NEAREST)
