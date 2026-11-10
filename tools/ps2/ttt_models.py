#!/usr/bin/env python3
"""The fighters' models of Tekken Tag Tournament PS2 (USA, SLUS-20001): which
TEKKEN.BIN file holds a costume, its triangle strips, skeleton nodes and
textures, and Unknown's two weapons (F29, GH#120).

    python tools/ps2/ttt_models.py DISC                       # Unknown's costumes and weapons
    python tools/ps2/ttt_models.py DISC --sheet OUT.png       # the weapons' textures, as the GS reads them

Costumes. Program table (s16[34 x 8]) found by its first row: key = character
x 8 + costume (the +0x26 of a fighter object, 0x879540 + 0xB8A0 i) -> model n
(+0x2E). The model is TEKKEN.BIN file 345 + 3n, its effect file 344 + 3n. The
character ids are TTT1's body numbers for the guests (Kunimitsu 28, Devil /
Angel 29, Unknown 33). The data of these files sits 18 464 sectors before the
sector their table entry gives: measured on the buffers of a PCSX2 save state
(Mokujin, file 540; Unknown, 693), and checked here on each read.

Meshes. GS triangle strips, each a GIF tag (PRIM 0x21C, or 0x25C blended;
REGS ST, RGBAQ, XYZ2) followed by NLOOP vertices for the VU1 skinning:
(s, t, 1.0, N), N bone slots (u32), then N x (normal x w, position x w | w),
N <= 3. A slot is 1-based in the palette of nodes that precedes the batch
(u32 n, 0, 0, 0, then n u64 node numbers). Bind frames are translations: a
vertex shared by two nodes gives the offset between them. Each strip's
texture is the TEX0 written just before it (twice, both contexts); TBP and
CBP are relative to where the game uploads the file (the GS uploads of the
file have the same relative DBP).

Unknown's weapons (fighter object +0x28 = the style, TTT1's moveset number):
the dagger of Kunimitsu's style (26) on nodes 116 / 117, child of the hand
node 38; the katana of Yoshimitsu's style (4) on 118 / 119, child of 63. The
node of the other style has a zero matrix. Every strip of a weapon is drawn
twice: opaque, then additive (ALPHA 0x48) from a 32 x 32 window, its purple
glow. The katana also gets a ribbon the game computes (not in the file).

Nothing read here goes into git.
"""
from __future__ import annotations

import argparse
import collections
import struct
import sys
from pathlib import Path

import ttt_disc as T

CHARACTER_ROW0 = struct.pack('<8h', 2, 3, 0, 1, -1, -1, -1, 122)
CHARACTERS, COSTUMES = 34, 8
SECTOR_SHIFT = 18464
UNKNOWN = 33
STYLE_DAGGER, STYLE_KATANA = 26, 4
# style: (root node, blade node, hand node, rotation of the root in the hand's
# frame, rows as the PS2 matrices: v_hand = v_root R). Save states 1, 2, 4 of F29.
WEAPONS = {
    STYLE_DAGGER: (116, 117, 38, ((0, 0, -1), (-1, 0, 0), (0, 1, 0))),
    STYLE_KATANA: (118, 119, 63, ((0, 0, 1), (-1, 0, 0), (0, -1, 0))),
}
ONE = 0x3F800000
PSMT8, PSMCT32 = 0x13, 0x00


class Models:
    """The costume table and the character files of a TTT PS2 disc."""

    def __init__(self, disc: T.Disc):
        self.tb = T.TekkenBin(disc)
        self.disc = disc
        program = disc.file(T.BOOT)
        at = program.find(CHARACTER_ROW0)
        if at < 0:
            raise T.DiscError(f'{disc.path}: no costume table in {T.BOOT}')
        self.table = struct.unpack_from(f'<{CHARACTERS * COSTUMES}h', program, at)
        toc = next(a for v, a, _ in T.TABLES if v == self.tb.version)
        count = 0
        while count < 1024 and struct.unpack_from('<I', program, toc + 16 * count + 12)[0] in (count, 0xFFFF):
            count += 1
        self.entries = [struct.unpack_from('<4I', program, toc + 16 * k) for k in range(count)]

    def model(self, character: int, costume: int) -> int:
        n = self.table[character * COSTUMES + costume]
        if n < 0:
            raise KeyError(f'character {character} has no costume {costume}')
        return n

    def read(self, k: int) -> bytes:
        sector, size = self.entries[k][0], max(self.entries[k][1] - T.SIZE_BIAS, 0)
        return self.disc.read(self.tb.lba + sector - SECTOR_SHIFT, size)

    def pack(self, n: int) -> bytes:
        """Model n's effect file then its model file, contiguous as on the disc;
        refuses data that has no strips (another layout, another disc)."""
        fx = self.read(344 + 3 * n)
        data = fx + bytes(-len(fx) % 2048) + self.read(345 + 3 * n)
        if len(strips(data, limit=4)) < 4:
            raise T.DiscError(f'{self.disc.path}: model {n} (file {345 + 3 * n}) has no strips at the expected place')
        return data


def strips(data: bytes, limit: int | None = None) -> list[dict]:
    """The model's strips: {at, prim, tex0 (or None), verts: [((s, t), [(node, w, (x, y, z)), ...])]}."""
    palettes = []
    for o in range(0, len(data) - 16, 16):
        n, z1, z2, z3 = struct.unpack_from('<4I', data, o)
        if 1 <= n <= 20 and not (z1 or z2 or z3) and o + 16 + 16 * ((n + 1) // 2) <= len(data):
            ids = []
            for q in range((n + 1) // 2):
                a, za, c, zc = struct.unpack_from('<4I', data, o + 16 + 16 * q)
                if za or zc or a >= 256 or c >= 256:
                    break
                ids += [a, c]
            else:
                if len(set(ids[:n])) == n:
                    palettes.append((o, ids[:n]))
    out, o, p = [], 0, -1
    while o < len(data) - 16 and (limit is None or len(out) < limit):
        lo, hi, r0, r1 = struct.unpack_from('<4I', data, o)
        nloop, prim = lo & 0x7FFF, (hi >> 15) & 0x7FF
        if r0 == 0x412 and r1 == 0 and hi >> 28 == 3 and (hi >> 14) & 1 and 3 <= nloop <= 200 and prim & 7 in (3, 4):
            while p + 1 < len(palettes) and palettes[p + 1][0] < o:
                p += 1
            pal = palettes[p][1] if p >= 0 else []
            verts, v = [], o + 16
            for _ in range(nloop):
                if v + 32 > len(data):
                    break
                s, t = struct.unpack_from('<2f', data, v)
                one, count = struct.unpack_from('<2I', data, v + 8)
                count &= 0xFF
                if one != ONE or not 1 <= count <= 4 or v + 32 + 32 * count > len(data):
                    break
                slots = struct.unpack_from('<4I', data, v + 16)[:count]
                inf = []
                for k, slot in enumerate(slots):
                    x, y, z, w = struct.unpack_from('<4f', data, v + 48 + 32 * k)
                    node = pal[slot - 1] if 1 <= slot <= len(pal) else -1
                    inf.append((node, w, (x / w, y / w, z / w) if w else (0.0, 0.0, 0.0)))
                verts.append(((s, t), inf))
                v += 32 + 32 * count
            if len(verts) == nloop:
                out.append(dict(at=o, prim=prim, tex0=tex0_before(data, o), verts=verts))
                o = v
                continue
        o += 16
    return out


def tex0_before(data: bytes, at: int) -> dict | None:
    """The TEX0 written (twice) just before a strip: window and palette, relative."""
    for back in range(16, min(0x200, at + 16), 16):
        lo, hi = struct.unpack_from('<2I', data, at - back)
        if (lo >> 20) & 63 == PSMT8 and struct.unpack_from('<2I', data, at - back + 8) == (lo, hi):
            v = lo | hi << 32
            return dict(tbp=v & 0x3FFF, tbw=(v >> 14) & 63, tw=1 << ((v >> 26) & 15), th=1 << ((v >> 30) & 15),
                        cbp=(v >> 37) & 0x3FFF)
    return None


def dominant(inf) -> int:
    return max(inf, key=lambda x: x[1])[0]


def offsets(strip_list) -> dict:
    """node -> bind translation (relative to the first node reached), from the
    vertices two nodes share."""
    pairs = collections.defaultdict(list)
    for s in strip_list:
        for _, inf in s['verts']:
            for i in range(len(inf)):
                for j in range(i + 1, len(inf)):
                    (a, wa, pa), (b, wb, pb) = inf[i], inf[j]
                    if a != b and wa > 0.1 and wb > 0.1:
                        pairs[a, b].append([pa[k] - pb[k] for k in range(3)])
    adj = collections.defaultdict(list)
    for (a, b), d in pairs.items():
        m = [sorted(x[k] for x in d)[len(d) // 2] for k in range(3)]
        adj[a].append((b, m))
        adj[b].append((a, [-x for x in m]))
    nodes = {dominant(inf) for s in strip_list for _, inf in s['verts']} | set(adj)
    out = {}
    for root in sorted(nodes, key=lambda n: (-len(adj[n]), n)):
        if root in out:
            continue
        out[root], todo = (0.0, 0.0, 0.0), [root]
        while todo:
            a = todo.pop()
            for b, d in adj[a]:
                if b not in out:
                    out[b] = tuple(out[a][k] + d[k] for k in range(3))
                    todo.append(b)
    return out


def textures(data: bytes) -> tuple[dict, dict]:
    """The model's 8-bit sheets {dbp: (width, rows of indices)} and 256-colour
    palettes {dbp: [(r, g, b, a)] * 256, CSM1 order undone}."""
    sheets, palettes = {}, {}
    for u in T.uploads(data):
        dbp = (struct.unpack_from('<Q', data, u.at + 16)[0] >> 32) & 0x3FFF
        if u.psm == PSMT8 and len(u.data) >= u.width * u.height:
            sheets[dbp] = (u.width, [u.data[r * u.width:(r + 1) * u.width] for r in range(u.height)])
        elif u.psm == PSMCT32 and (u.width, u.height) == (16, 16):
            raw = [tuple(u.data[4 * i:4 * i + 4]) for i in range(256)]
            palettes[dbp] = [raw[(i & ~0x18) | ((i & 8) << 1) | ((i & 16) >> 1)] for i in range(256)]
    return sheets, palettes


def texel(sheets, palettes, tex0, s, t):
    """The colour the GS reads at (s, t) of a strip's window: the sheet whose
    pages hold TBP (PSMT8 pages are 128 x 64, TBW / 2 across)."""
    for dbp, (width, rows) in sheets.items():
        page = tex0['tbp'] - dbp
        across = max(width // 128, 1)
        if page < 0 or page % 32 or (page // 32 // across) * 64 >= len(rows):
            continue
        page //= 32
        x = (page % across) * 128 + int(s * tex0['tw']) % tex0['tw']
        y = (page // across) * 64 + int(t * tex0['th']) % tex0['th']
        if y < len(rows) and x < width:
            pal = palettes.get(tex0['cbp'])
            return pal[rows[y][x]] if pal else None
    return None


def weapon(data: bytes, style: int, parsed: list[dict] | None = None) -> dict:
    """Unknown's weapon of a style: triangles in the root node's frame, with UVs,
    window and additive flag; the hand node and the root's rotation in it."""
    root, blade, hand, rotation = WEAPONS[style]
    parsed = parsed if parsed is not None else strips(data)
    mine = [s for s in parsed if all(dominant(inf) in (root, blade) for _, inf in s['verts'])]
    if not mine:
        raise ValueError(f'no strip on nodes {root} / {blade}')
    off = offsets(mine)
    base = off.get(root, (0.0, 0.0, 0.0))
    tris = []
    for s in mine:
        pos = []
        for _, inf in s['verts']:
            w = sum(x[1] for x in inf)
            pos.append(tuple(sum(x[1] * (x[2][k] + off.get(x[0], base)[k] - base[k]) for x in inf) / w for k in range(3)))
        for i in range(len(s['verts']) - 2):
            p = pos[i:i + 3]
            ux, uy, uz = (p[1][k] - p[0][k] for k in range(3))
            vx, vy, vz = (p[2][k] - p[0][k] for k in range(3))
            if abs(uy * vz - uz * vy) + abs(uz * vx - ux * vz) + abs(ux * vy - uy * vx) < 1e-6:
                continue
            # a strip alternates its winding: keep the GS order, flip odd ones
            order = (0, 1, 2) if i % 2 == 0 else (1, 0, 2)
            tris.append(dict(points=[p[k] for k in order], uv=[s['verts'][i + k][0] for k in order],
                             additive=bool(s['prim'] & 0x40), tex0=s['tex0']))
    return dict(style=style, root=root, blade=blade, hand=hand, rotation=rotation, triangles=tris)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('disc', type=Path)
    ap.add_argument('--sheet', type=Path, help="PNG: Unknown's weapons' texture windows (Pillow)")
    args = ap.parse_args(argv)
    with T.Disc(args.disc) as disc:
        m = Models(disc)
        for costume in (0, 1):
            n = m.model(UNKNOWN, costume)
            data = m.pack(n)
            parsed = strips(data)
            print(f'Unknown costume {costume + 1}: model {n}, file {345 + 3 * n}, {len(parsed)} strips, '
                  f'{sum(len(s["verts"]) - 2 for s in parsed)} triangles')
            for style in (STYLE_DAGGER, STYLE_KATANA):
                w = weapon(data, style, parsed)
                opaque = sum(not t['additive'] for t in w['triangles'])
                print(f'  style {style}: nodes {w["root"]}/{w["blade"]} on hand {w["hand"]}, '
                      f'{opaque} triangles + {len(w["triangles"]) - opaque} additive')
            if args.sheet and costume == 0:
                from PIL import Image
                sheets, palettes = textures(data)
                windows = sorted({(t['tex0']['tbp'], t['tex0']['tw'], t['tex0']['th'], t['tex0']['cbp'])
                                  for style in (STYLE_DAGGER, STYLE_KATANA) for t in weapon(data, style, parsed)['triangles']})
                img = Image.new('RGBA', (len(windows) * 136, 136))
                for i, (tbp, tw, th, cbp) in enumerate(windows):
                    w0 = dict(tbp=tbp, tw=tw, th=min(th, 128), cbp=cbp)
                    for y in range(min(th, 128)):
                        for x in range(min(tw, 128)):
                            c = texel(sheets, palettes, w0, (x + .5) / tw, (y + .5) / w0['th'])
                            if c:
                                img.putpixel((i * 136 + x, y), (c[0], c[1], c[2], 255))
                img.save(args.sheet)
                print('windows', [tuple(hex(v) for v in w) for w in windows], '->', args.sheet)
    return 0


if __name__ == '__main__':
    sys.exit(main())
