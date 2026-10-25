"""Unknown's wolf spirit: the glow pack of its light effects (F08, GH#42).

The effects stand on bones of the wolf's fighter block (world translation at
+0xA8C + 0x50 k): 1 the root, 13 and 16 the knees, where its legs end (12..14
and 15..17 are the legs, measured in MAME 2026-10-22). A Tekken 3 actor's
bones (+0x908 + 68 k) come in the same order (Unknown's measured in game):
the pack names them as they are.

TTT1's final stage (stage 14, 0x8015671C) creates the wolf's effects once:
type 18 (A, 0x8015BA1C / 0x8015A31C), two of type 19 (B, 0x8015BB80 /
0x8015A584), type 20 (C, 0x8015BC58 / 0x8015A8E8), two of type 22 (S,
0x8015BE4C / 0x8015AE94), and A sends a type 21 every 32 frames (W,
0x8015AAAC / 0x8015AC00). Each is a POLY_FT4 billboard, additive (texture
pages with ABR 1), whose image steps through a table of (u, v) and page
indices: A 0x800235DC / 0x80023624 (18 images of 64 x 64), B 0x80023688 /
0x800236E4 (23), C 0x80023734 / 0x8002377C (18 of 128 x 128), W and S
0x800237A0 (8 of 32 x 32, page 9). The images are archive 06's TIMs as they
lie in the fight's VRAM (files 0..9 in order; checked against MAME's uploads
on the final stage, 2026-10-22).

TTT1 builds its page and palette tables at boot (0x80347760, 0x80347710),
read here as MAME shows them: page indices 4..14 and the four palettes.

Here the images go to the upper VRAM half (y 512..1023, src/tekken3_ttt1_wolf.c),
in pages that neither stage pack uses (x 640..1023, y 512..767): the wolf's
own texture band at x 640 (the costume fold, 64 x 256), its palettes at
x 704.. y 512..515, then the frames on shelves of 64 rows from y 516, the
32 x 32 ones at y 708, the four effect palettes at x 960.. y 512. C's 128 x 128
images are halved (every other pixel): the six free pages hold 80 640
halfwords, the full set 117 760.

The pack, <Name>-TTT1-wolf.glow, little-endian:
  'GLOW', u16 version 1, u16 rectangles, u16 sequences, u16 0, u16 the bones
  of C's, A's and B's anchors (BONES: the root, the two knees),
  then each rectangle: u16 x, y, w, h (VRAM, y >= 512) and w x h halfwords,
  then each sequence (A, B, C, W): u16 images, and per image u8 u, v,
  width - 1, height - 1, u16 page (bit 11: upper half, ABR 1), u16 palette
  (bit 15: upper half).
"""
import struct

import numpy as np

# Pages of 0x80347760 (index -> GP0 texpage, System 12 bit 11 = y + 512).
PAGES = {4: 0x820, 5: 0x830, 6: 0x821, 7: 0x831, 8: 0x822, 9: 0x832,
         10: 0x823, 11: 0x833, 12: 0x824, 13: 0x834, 14: 0x825}
# Palettes of 0x80347710 the effects take (+0x1C A, +0x20 B, +0x24 W and S, +0x28 C).
PALETTES = dict(A=0x3ce0, B=0x3ce1, W=0x3ce2, C=0x3ce3)
# name: (uv table, page index table, images, image size in pixels)
SEQUENCES = dict(A=(0x800235dc, 0x80023624, 18, 64), B=(0x80023688, 0x800236e4, 23, 64),
                 C=(0x80023734, 0x8002377c, 18, 128), W=(0x800237a0, None, 8, 32))
W_PAGE = 9
BONES = (1, 13, 16)          # C on the root; A between the knees; B and S on each knee

BAND_X, CLUT_X, CLUT_Y = 640, 704, 512              # the wolf's textures and palettes
SHELF_X, SHELF_Y, SHELF_W, SHELVES = 704, 516, 320, 3
SMALL_Y = SHELF_Y + 64 * SHELVES                    # 708: the 32 x 32 images
GLOW_CLUT_X = 960


def vram(files):
    """Archive 06's TIMs, in file order, in a 1024 x 1024 VRAM."""
    v = np.zeros((1024, 1024), np.uint16)
    for d in files:
        p = 0
        while p + 8 <= len(d) and struct.unpack_from('<I', d, p)[0] == 0x10:
            flags = struct.unpack_from('<I', d, p + 4)[0]; p += 8
            for _ in range(2 if flags & 8 else 1):
                n, x, y, w, h = struct.unpack_from('<I4H', d, p)
                v[y:y + h, x:x + w] = np.frombuffer(d, np.uint16, w * h, p + 12).reshape(h, w)
                p += n
    return v


def page_origin(tp):
    return (tp & 0xf) * 64, (512 if tp & 0x800 else 0) + (tp >> 4 & 1) * 256


def clut_origin(c):
    return (c & 0x3f) * 16, (c >> 6 & 0x1ff) + (512 if c & 0x8000 else 0)


def frames(game, name):
    """(x, y) in VRAM halfwords of a sequence's images, and their size in pixels."""
    uv, pages, count, size = SEQUENCES[name]
    at = lambda a, n: game[a - 0x80010000:a - 0x80010000 + n]
    uvs = at(uv, 2 * count)
    idx = at(pages, count) if pages else bytes([W_PAGE]) * count
    out = []
    for i in range(count):
        px, py = page_origin(PAGES[idx[i]])
        out.append((px + uvs[2 * i] // 4, py + uvs[2 * i + 1]))
    return out, size


def build(game, files, wolf_tim, bones):
    """The pack's bytes. wolf_tim: the converted wolf's .tim (costume fold),
    whose images go to BAND_X and palettes to CLUT_X."""
    v = vram(files)
    rects, seqs = [], []
    # The wolf's textures and palettes, as the guests' (tekken3_ttt1_mod.c,
    # upload_textures_now): x 0..63 -> y, x 64..127 -> y + 128.
    p = 0
    while p + 8 <= len(wolf_tim) and struct.unpack_from('<I', wolf_tim, p)[0] == 0x10:
        flags = struct.unpack_from('<I', wolf_tim, p + 4)[0]; p += 8
        clut = None
        if flags & 8:
            n, x, y, w, h = struct.unpack_from('<I4H', wolf_tim, p)
            clut = (x, y, w, h, wolf_tim[p + 12:p + 12 + 2 * w * h]); p += n
        n, x, y, w, h = struct.unpack_from('<I4H', wolf_tim, p)
        pixels = wolf_tim[p + 12:p + 12 + 2 * w * h]; p += n
        if x + w > 128 or y + h > 128 or x // 64 != (x + w - 1) // 64:
            raise ValueError(f'loup : image ({x},{y}) {w}x{h} hors du pli 128 x 128')
        if clut:
            cx, cy, cw, ch, cpix = clut
            if CLUT_X + cx + cw > GLOW_CLUT_X or cy + ch > 4: raise ValueError(f'loup : palette ({cx},{cy}) hors de sa bande')
            rects.append((CLUT_X + cx, CLUT_Y + cy, cw, ch, cpix))
        rects.append((BAND_X + x % 64, 512 + y + (128 if x >= 64 else 0), w, h, pixels))
    # The effects' images on shelves, their palettes after the wolf's.
    slot, small = 0, 0
    for k, name in enumerate('ABCW'):
        cx, cy = clut_origin(PALETTES[name])
        clut = GLOW_CLUT_X + 16 * k
        rects.append((clut, 512, 16, 1, v[cy, cx:cx + 16].tobytes()))
        places, size = frames(game, name)
        seq, seen = [], {}
        for x, y in places:
            if (x, y) not in seen:
                img = v[y:y + size, x:x + size // 4]
                if size == 128: img = halve(img)
                if size == 32:
                    dx, dy, hw = SHELF_X + 8 * small, SMALL_Y, 8; small += 1
                else:
                    if slot >= SHELVES * SHELF_W // 16: raise ValueError('lueur : plus de place sur les etageres')
                    dx, dy, hw = SHELF_X + 16 * (slot % (SHELF_W // 16)), SHELF_Y + 64 * (slot // (SHELF_W // 16)), 16
                    slot += 1
                rects.append((dx, dy, hw, img.shape[0], np.ascontiguousarray(img).tobytes()))
                seen[x, y] = (dx, dy, img.shape[0])
            dx, dy, h = seen[x, y]
            page = dx // 64 | 0x800 | 0x20                    # upper half, ABR 1 (additive), 4 bits
            seq.append(struct.pack('<4B2H', (dx % 64) * 4, dy - 512, h - 1, h - 1, page, 0x8000 | clut // 16))
        seqs.append(seq)
    out = b'GLOW' + struct.pack('<2H2H3H', 1, len(rects), len(seqs), 0, *bones)
    for x, y, w, h, pixels in rects:
        out += struct.pack('<4H', x, y, w, h) + bytes(pixels)
    for seq in seqs:
        out += struct.pack('<H', len(seq)) + b''.join(seq)
    return out, dict(rectangles=len(rects), images={n: len(s) for n, s in zip('ABCW', seqs)},
                     shelf_images=slot, small_images=small, bones=bones)


def halve(img):
    """A 4-bit image (halfwords of four pixels) at half size: every other pixel
    of every other row."""
    px = np.zeros((img.shape[0], img.shape[1] * 4), np.uint8)
    for k in range(4): px[:, k::4] = img >> (4 * k) & 15
    px = px[::2, ::2]
    out = np.zeros((px.shape[0], px.shape[1] // 4), np.uint16)
    for k in range(4): out |= px[:, k::4].astype(np.uint16) << (4 * k)
    return out
