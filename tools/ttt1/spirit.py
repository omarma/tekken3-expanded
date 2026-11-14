"""Unknown's wolf spirit: the glow pack of its light effects (F08, GH#42; B157, GH#199).

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
indices (ttt-ps1/src/decor/8015A584.c, 80156CB8.c): A 0x800235DC / 0x80023624,
36 images of 64 x 64, 2 frames each; B 0x80023688 / 0x800236E4, 45 images,
1 frame each (counter 0..0x2C); C 0x80023734 / 0x8002377C, 36 images of
128 x 128, 2 frames each; W and S 0x800237A0 (8 of 32 x 32, page 9). Before
B157 the pack took 18, 23 and 18 of them, C at half size. The images are
archive 06's TIMs as they lie in the fight's VRAM (files 0..9 in order;
checked against MAME's uploads on the final stage, 2026-10-22).

TTT1 builds its page and palette tables at boot (0x80347760, 0x80347710),
read here as MAME shows them: page index 4 + 2 k is 0x820 + k, 5 + 2 k is
0x830 + k (indices 4..19, a 64-wide column of the upper half each, A to C's
images covering x 0..511 of y 512..1023), and the four palettes.

All of A, B and C is 232 448 halfwords, for 80 640 free in the wolf's pages
(x 640..1023, y 512..767): they are not uploaded once. The pack carries every
image, and src/tekken3_ttt1_wolf.c uploads at each drawn frame the ones it
draws (C, A and the two B) into a 64 x 128 set of its own, one per wolf and
frame buffer, at x 704 + 64 k, y 516. What stays in VRAM: the wolf's own
texture band at x 640 (the costume fold, 64 x 256), its palettes at x 704..
y 512..515, W's eight 32 x 32 images at y 708, the four effect palettes at
x 960.. y 512.

The pack, <Name>-TTT1-wolf.glow, little-endian:
  'GLOW', u16 version 2, u16 rectangles, u16 sequences (4), u16 0, u16 the
  bones of C's, A's and B's anchors (BONES: the root, the two knees),
  then each rectangle: u16 x, y, w, h (VRAM, y >= 512) and w x h halfwords,
  then A, B and C, streamed: u16 images, u16 size in pixels, and each image's
  size / 4 x size halfwords (4 bits, its sequence's palette),
  then W: u16 images, and per image u8 u, v, width - 1, height - 1, u16 page
  (bit 11: upper half, ABR 1), u16 palette (bit 15: upper half).
"""
import struct

import numpy as np

# Pages of 0x80347760 (index -> GP0 texpage, System 12 bit 11 = y + 512).
PAGES = {k: 0x820 + (k - 4) // 2 + (0x10 if k & 1 else 0) for k in range(4, 20)}
# Palettes of 0x80347710 the effects take (+0x1C A, +0x20 B, +0x24 W and S, +0x28 C).
PALETTES = dict(A=0x3ce0, B=0x3ce1, W=0x3ce2, C=0x3ce3)
# name: (uv table, page index table, images, image size in pixels)
SEQUENCES = dict(A=(0x800235dc, 0x80023624, 36, 64), B=(0x80023688, 0x800236e4, 45, 64),
                 C=(0x80023734, 0x8002377c, 36, 128), W=(0x800237a0, None, 8, 32))
STREAMED = 'ABC'
W_PAGE = 9
BONES = (1, 13, 16)          # C on the root; A between the knees; B and S on each knee

BAND_X, CLUT_X, CLUT_Y = 640, 704, 512              # the wolf's textures and palettes
SETS_X, SETS_Y = 704, 516                           # src/tekken3_ttt1_wolf.c's four 64 x 128 sets
SMALL_X, SMALL_Y = 704, 708                         # W's 32 x 32 images
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
    rects = []
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
    # The effects' palettes after the wolf's; A, B and C's images whole, for
    # the runtime to upload; W's in VRAM.
    streams, w_seq = [], []
    for k, name in enumerate('ABCW'):
        cx, cy = clut_origin(PALETTES[name])
        clut = GLOW_CLUT_X + 16 * k
        rects.append((clut, 512, 16, 1, v[cy, cx:cx + 16].tobytes()))
        places, size = frames(game, name)
        if name in STREAMED:
            images = [np.ascontiguousarray(v[y:y + size, x:x + size // 4]).tobytes() for x, y in places]
            streams.append(struct.pack('<2H', len(images), size) + b''.join(images))
            continue
        seen = {}
        for x, y in places:
            if (x, y) not in seen:
                dx = SMALL_X + 8 * len(seen)
                rects.append((dx, SMALL_Y, 8, size, np.ascontiguousarray(v[y:y + size, x:x + 8]).tobytes()))
                seen[x, y] = dx
            dx = seen[x, y]
            page = dx // 64 | 0x800 | 0x20                    # upper half, ABR 1 (additive), 4 bits
            w_seq.append(struct.pack('<4B2H', (dx % 64) * 4, SMALL_Y - 512, size - 1, size - 1, page, 0x8000 | clut // 16))
    out = b'GLOW' + struct.pack('<2H2H3H', 2, len(rects), 4, 0, *bones)
    for x, y, w, h, pixels in rects:
        out += struct.pack('<4H', x, y, w, h) + bytes(pixels)
    out += b''.join(streams) + struct.pack('<H', len(w_seq)) + b''.join(w_seq)
    return out, dict(rectangles=len(rects), images={n: SEQUENCES[n][2] for n in 'ABCW'}, bones=bones)
