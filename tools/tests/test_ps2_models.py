"""TTT PS2 fighters' models (tools/ps2/ttt_models.py): costume table, file
layout, strips, and Unknown's weapons (F29, GH#120).

    python -m unittest tools.tests.test_ps2_models

The tests that read the disc run only where it is, by default
C:\\TekkenProject\\discs or ~/TekkenProject/discs (TEKKEN3_TTT_DISC: another
path).
"""
from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ps2'))
import ttt_disc  # noqa: E402
import ttt_models as M  # noqa: E402

NAME = 'Tekken Tag Tournament (USA) (v1.00).cue'
DISC = next((p for p in [Path(os.environ.get('TEKKEN3_TTT_DISC', '')), Path(r'C:\TekkenProject\discs') / NAME,
                          Path.home() / 'TekkenProject/discs' / NAME] if str(p) != '.' and p.is_file()), None)
# The first vertex of the katana's first strip as the GS drew it (F29's GS
# dump of Unknown in Yoshimitsu's style, draw 1420): its S / Q, T / Q.
KATANA_UV = (0.2505859434604645, 0.03046874701976776)


def strip(prim=0x21C, verts=()):
    """A GIF tag and its vertices in the file's form: ((s, t), [(slot, w, (x, y, z))])."""
    hi = 3 << 28 | prim << 15 | 1 << 14
    out = struct.pack('<4I', len(verts), hi, 0x412, 0)
    for (s, t), inf in verts:
        out += struct.pack('<2f2I', s, t, M.ONE, len(inf))
        out += struct.pack('<4I', *([slot for slot, _, _ in inf] + [0] * (4 - len(inf))))
        for _, w, (x, y, z) in inf:
            out += struct.pack('<4f', 0, 0, 0, 0) + struct.pack('<4f', x * w, y * w, z * w, w)
    return out


class Synthetic(unittest.TestCase):
    def test_palette_and_bind_offsets(self):
        palette = struct.pack('<4I', 2, 0, 0, 0) + struct.pack('<4I', 116, 0, 117, 0)
        verts = [((0, 0), [(1, 1.0, (0, 0, 0))]), ((0, 1), [(1, 1.0, (10, 0, 0))]),
                 ((1, 0), [(1, .5, (20, 0, 0)), (2, .5, (5, 0, 0))]),     # node 117 is 15 further along x
                 ((1, 1), [(2, 1.0, (30, 0, 0))])]
        data = bytes(16) + palette + strip(verts=verts) + bytes(32)
        parsed = M.strips(data)
        self.assertEqual(len(parsed), 1)
        self.assertEqual([M.dominant(inf) for _, inf in parsed[0]['verts']], [116, 116, 116, 117])
        self.assertEqual(M.offsets(parsed)[117][0] - M.offsets(parsed)[116][0], 15)

    def test_rejects_a_wrong_header(self):
        bad = bytearray(strip(verts=[((0, 0), [(1, 1.0, (0, 0, 0))])] * 3))
        struct.pack_into('<I', bad, 16 + 8, 0)        # not 1.0
        self.assertEqual(M.strips(bytes(bad)), [])


@unittest.skipUnless(DISC, 'no TTT PS2 disc')
class Disc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.disc = ttt_disc.Disc(DISC)
        cls.m = M.Models(cls.disc)

    @classmethod
    def tearDownClass(cls):
        cls.disc.close()

    def test_costume_table(self):
        self.assertEqual(len(self.m.entries), 748)
        self.assertEqual([self.m.model(M.UNKNOWN, c) for c in (0, 1)], [116, 117])
        self.assertEqual(self.m.model(29, 0), 106)            # Devil
        self.assertEqual(self.m.model(29, 4), 107)            # Angel
        self.assertEqual([self.m.model(28, c) for c in (0, 1, 4)], [103, 104, 105])   # Kunimitsu
        with self.assertRaises(KeyError):
            self.m.model(M.UNKNOWN, 2)

    def test_unknown_models(self):
        for n, count in ((116, 6546), (117, 5876)):
            parsed = M.strips(self.m.pack(n))
            self.assertEqual(sum(len(s['verts']) - 2 for s in parsed), count)

    def test_unknown_weapons(self):
        for n in (116, 117):
            data = self.m.pack(n)
            parsed = M.strips(data)
            dagger = M.weapon(data, M.STYLE_DAGGER, parsed)
            katana = M.weapon(data, M.STYLE_KATANA, parsed)
            self.assertEqual((dagger['hand'], katana['hand']), (38, 63))
            for w, opaque in ((dagger, 122), (katana, 88)):
                self.assertEqual(sum(not t['additive'] for t in w['triangles']), opaque)
                self.assertEqual(sum(t['additive'] for t in w['triangles']), opaque)
                self.assertTrue(all(t['tex0'] for t in w['triangles']))
            length = lambda w: max(p[0] for t in w['triangles'] for p in t['points']) - min(
                p[0] for t in w['triangles'] for p in t['points'])
            self.assertAlmostEqual(length(katana), 986, delta=2)
            self.assertAlmostEqual(length(dagger), 625, delta=2)
            if n == 116:          # the dump's costume; the GS's vertex opens a strip (degenerate first triangle)
                opening = {s['verts'][0][0] for s in parsed if all(M.dominant(inf) in (118, 119) for _, inf in s['verts'])}
                self.assertIn(KATANA_UV, opening)

    def test_weapon_texels(self):
        data = self.m.pack(116)
        sheets, palettes = M.textures(data)
        katana = M.weapon(data, M.STYLE_KATANA)
        found = [M.texel(sheets, palettes, t['tex0'], *t['uv'][0]) for t in katana['triangles']]
        self.assertTrue(all(c is not None for c in found))


import hashlib  # noqa: E402
import ttt_weapons as W  # noqa: E402
import laser_version  # noqa: E402

# unknown-weapons.bin made from the USA disc: if the conversion changes, so
# does this, and laser_version.LASER_VERSION goes up with it.
WEAPONS_SHA256 = '29d4a4470f7128f8ae3d57aaf8a4dddc1f3c65c05f89690e5778ba3451f87116'


@unittest.skipUnless(DISC, 'no TTT PS2 disc')
class Pack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = W.build(DISC)
        cls.costumes = W.read(cls.pack)

    def test_digest(self):
        self.assertEqual(hashlib.sha256(self.pack).hexdigest(), WEAPONS_SHA256,
                         'unknown-weapons.bin changed: increase laser_version.LASER_VERSION, then this')
        self.assertGreaterEqual(laser_version.LASER_VERSION, 4)

    def test_styles_bones_polygons(self):
        self.assertEqual(len(self.costumes), 2)
        for costume in self.costumes:
            self.assertEqual(sorted(costume['styles']), [M.STYLE_KATANA, M.STYLE_DAGGER])
            for style, w in costume['styles'].items():
                self.assertEqual(w['bone'], W.BONES[style])
                polys = w['polygons']
                # the glow on the same polygons as the opaque pass, mostly quads (the arcade's construction)
                opaque = [t['corners'] for t in polys if not t['additive']]
                self.assertEqual(opaque, [t['corners'] for t in polys if t['additive']])
                self.assertGreater(sum(len(c) == 4 for c in opaque), 0.8 * len(opaque))
                self.assertLessEqual(len(opaque), 60)                  # about the arcade sword's part (70 with its hand)

    def test_guards_kept(self):
        # the katana's tsuba: wider than its handle and its blade, as on the PS2 (45.9 against 31 and 29)
        for costume in self.costumes:
            rings = {}
            for p in costume['styles'][M.STYLE_KATANA]['points']:
                rings.setdefault(p[2], []).append(p[0])
            width = lambda z0, z1: max(max(xs) - min(xs) for z, xs in rings.items() if z0 <= z <= z1)
            self.assertGreater(width(90, 96), width(-130, 66) + 8)
            self.assertGreater(width(90, 96), width(150, 700) + 8)

    def test_frame_and_length(self):
        # where TTT1 ends Unknown's energy blades: Kunimitsu's style at z -400,
        # Yoshimitsu's going on past 687 (the PS2 katana's tip): both lengths are the PS2's
        for costume in self.costumes:
            dagger = costume['styles'][M.STYLE_DAGGER]['points']
            katana = costume['styles'][M.STYLE_KATANA]['points']
            self.assertAlmostEqual(min(p[2] for p in dagger), -400, delta=5)
            self.assertAlmostEqual(max(p[2] for p in katana), 687, delta=2)
            self.assertAlmostEqual(min(p[2] for p in katana), -135, delta=2)
            self.assertAlmostEqual(max(p[2] for p in dagger), 120, delta=2)

    def test_uvs_in_images(self):
        for costume in self.costumes:
            for w in costume['styles'].values():
                for t in w['polygons']:
                    iw, ih, pixels, clut = costume['images'][t['image']]
                    self.assertEqual(iw % 4, 0)
                    self.assertTrue(all(0 <= u < iw and 0 <= v < ih for u, v in t['uv']))
                    self.assertEqual(clut[0], 0)                       # index 0: transparent
                    if t['additive']:
                        self.assertTrue(all(c == 0 or c & 0x8000 for c in clut))   # STP for the PS1's blend


if __name__ == '__main__':
    unittest.main()
