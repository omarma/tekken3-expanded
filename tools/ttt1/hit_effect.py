"""Effet de coup fort d'un personnage TTT1 -> paquet d'effet au format Tekken 3.

TTT1 (releve en VRAM, tools/ttt1_hit_effect_capture.lua) : planche 256 x 256
en 4 bits, 16 images 64 x 64 rangees 4 par ligne, page (512, 256) du joueur 1,
palette 16 couleurs en (512, 64).

Tekken 3 : dans le fichier de chaque personnage, une suite de TIM 4 bits, un
par image : palette 16 x 1 puis image 32 x 32 (8 x 32 demi-mots), coordonnees
a zero (le chargeur les place : colonnes 368/376 pour le joueur 1, 496/504
pour le joueur 2, image k en colonne k % 2 et ligne k // 2 ; palette en
(16 * joueur, 503)). Seule la palette de la premiere image garde le bit de
semi-transparence, comme dans les paquets d'origine. Un invite joue le paquet
de Jin, 22 images : on en produit autant, la planche TTT1 etiree dans le temps,
dans son ordre de lecture : TTT1 affiche les images 0 a 15 dans l'ordre de la
planche, une par trame (releve par tools/ttt1_hit_effect_order.lua pour
Kazuya, Kunimitsu, Lee et Roger), images vides comprises (0 pour l'eclair des
Mishima, 3 pour les etincelles de Roger / Alex).
"""
import struct
import numpy as np
from PIL import Image

T3_FRAMES = 22
SHEET_X, SHEET_Y, CLUT_X, CLUT_Y = 512, 256, 512, 64


def sheet(vram_bytes):
    """(indices 256 x 256, palette 16) de l'effet du joueur 1 dans la VRAM TTT1."""
    V = np.frombuffer(vram_bytes, np.uint16).reshape(1024, 1024)
    blk = V[SHEET_Y:SHEET_Y + 256, SHEET_X:SHEET_X + 64]
    idx = np.stack([(blk >> (4 * k)) & 15 for k in range(4)], -1).reshape(256, 256)
    pal = V[CLUT_Y, CLUT_X:CLUT_X + 16].copy()
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


def frames(idx, pal, count=T3_FRAMES):
    src = [idx[(k // 4) * 64:(k // 4) * 64 + 64, (k % 4) * 64:(k % 4) * 64 + 64] for k in range(16)]
    return [shrink(src[min(15, k * 16 // count)], pal) for k in range(count)]


def tim(img32, pal):
    data = bytearray()
    for row in img32:
        for x in range(0, 32, 2): data.append(int(row[x]) | int(row[x + 1]) << 4)
    clut = struct.pack('<I4H', 12 + 32, 0, 0, 16, 1) + struct.pack('<16H', *(int(v) for v in pal))
    image = struct.pack('<I4H', 12 + len(data), 0, 0, 8, 32) + bytes(data)
    return struct.pack('<2I', 0x10, 8) + clut + image


def t3_pack(vram_bytes):
    """Paquet d'effet T3 (TIM a la suite) depuis la VRAM TTT1 du joueur 1."""
    idx, pal = sheet(vram_bytes)
    first = pal.copy()
    rest = pal & 0x7fff
    return b''.join(tim(f, first if k == 0 else rest) for k, f in enumerate(frames(idx, pal)))


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
