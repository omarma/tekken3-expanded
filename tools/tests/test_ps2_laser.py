"""Devil's and Angel's PS2 laser (tools/ps2/ttt_laser_install.py) and the Mishima's PS2
strong-hit effects (tools/ps2/ttt_hitspark_ps2.py).

    python -m unittest tools.tests.test_ps2_laser

The tests that read the disc run only where it is, by default
C:\\TekkenProject\\discs or ~/TekkenProject/discs (TEKKEN3_TTT_DISC: another
path); the comparison with the study's sheet only where the study is
(TEKKEN3_LASER_STUDY_SHEET).
"""
from __future__ import annotations

import hashlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ps2'))
import laser_version  # noqa: E402
import ttt_disc  # noqa: E402
import ttt_laser_install as laser  # noqa: E402

NAME = 'Tekken Tag Tournament (USA) (v1.00).cue'
DISC = next((p for p in [Path(os.environ.get('TEKKEN3_TTT_DISC', '')), Path(r'C:\TekkenProject\discs') / NAME,
                          Path.home() / 'TekkenProject/discs' / NAME] if str(p) != '.' and p.is_file()), None)
STUDY = Path(os.environ.get('TEKKEN3_LASER_STUDY_SHEET',
                            r'C:\TekkenProject\etude-hitspark-ps2\planches\ps2-devil-laser-set.png'))
STUDY_RAM = 0xC700B0        # where the study's save state had the set (its sheet's labels)
# ps2-laser.tim (Devil) and ps2-laser-angel.tim made from the USA disc: if
# the conversion changes, so do these, and laser_version.LASER_VERSION goes up
# with them.
PACK_SHA256 = 'd87add19fe6c0cd4fe9e7a762d09066a1f19b9ea6664abac55b69871179b0c19'
ANGEL_SHA256 = '8a5666efad630d1f938762db776b84e13c53a620999e5bf432fe6095215a8adf'


def iso(files: dict[str, bytes]) -> bytes:
    """A minimal ISO 9660 image (2 048-byte sectors), its files in the root."""
    def record(name: bytes, extent: int, size: int, directory=False) -> bytes:
        length = 33 + len(name) + (len(name) + 1) % 2
        out = bytearray(length)
        out[0] = length
        struct.pack_into('<I', out, 2, extent)
        struct.pack_into('<I', out, 10, size)
        out[25] = 2 if directory else 0
        out[32] = len(name)
        out[33:33 + len(name)] = name
        return bytes(out)
    sectors, extent, body = {}, 19, []
    for name, data in files.items():
        body.append(record(name.encode() + b';1', extent, len(data)))
        sectors[extent] = data
        extent += (len(data) + 2047) // 2048
    root = record(b'\0', 18, 2048, True) + record(b'\1', 18, 2048, True) + b''.join(body)
    pvd = bytearray(2048)
    pvd[0:6] = b'\1CD001'
    pvd[156:190] = record(b'\0', 18, 2048, True)
    image = bytearray(2048 * extent)
    image[16 * 2048:17 * 2048] = pvd
    image[18 * 2048:18 * 2048 + len(root)] = root
    for at, data in sectors.items():
        image[at * 2048:at * 2048 + len(data)] = data
    return bytes(image)


class Conversion(unittest.TestCase):
    def test_colours(self):
        self.assertEqual(laser.colour15(0, 0, 0), 0)            # transparent
        self.assertEqual(laser.colour15(2, 1, 3), 0)            # rounds to black: adds nothing either way
        self.assertEqual(laser.colour15(255, 255, 255), 0xFFFF)
        self.assertEqual(laser.colour15(0x80, 0x40, 0xF8), 0x8000 | 16 | 8 << 5 | 31 << 10)

    def test_angel_gold(self):
        self.assertEqual(laser.gold(0, 0, 0), (0, 0, 0))                  # transparent stays so
        self.assertEqual(laser.gold(255, 255, 255), (255, 255, 255))      # the white hearts stay white
        r, g, b = laser.gold(0x60, 0x40, 0xE0)                            # a purple of the beam: gold
        self.assertTrue(r > g > b, (r, g, b))

    def test_tim_round_trip(self):
        pixels = bytes(range(256)) * 4                          # 64 x 32 in 4 bits
        clut = [0x8000 | k for k in range(16)]
        pack = laser.tim(64, 32, pixels, clut) * 2
        self.assertEqual(laser.read_pack(pack), [(64, 32, pixels, tuple(clut))] * 2)
        # The header the game's strong-hit packs have (src/tekken3_ttt1_combat.c, load_hit_effect).
        self.assertEqual(struct.unpack_from('<5I', pack, 0), (0x10, 8, 44, 0, 0x10010))

    def test_another_program_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            disc = Path(temp) / 'ttt-pal.iso'
            disc.write_bytes(iso({'SYSTEM.CNF': b'BOOT2 = cdrom0:\\SLES_500.78;1\r\nVER = 1.00\r\n', 'SLES_500.78': b'\0' * 4096}))
            with self.assertRaises(ttt_disc.DiscError) as error:
                laser.laser_set(disc)
            self.assertIn('SLES_500.78, not SLUS_200.01', str(error.exception))
            self.assertIn("keep the arcade's yellow beam", str(error.exception))
            self.assertFalse(laser.found(disc))
            self.assertEqual(laser.main(['--ttt-disc', str(disc), '--out', str(Path(temp) / 'pack')]), 1)
            self.assertFalse((Path(temp) / 'pack').exists())

    def test_an_unknown_version_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            disc = Path(temp) / 'ttt-v3.iso'
            disc.write_bytes(iso({'SYSTEM.CNF': b'BOOT2 = cdrom0:\\SLUS_200.01;1\r\nVER = 3.00\r\n',
                                  'SLUS_200.01': b'\0' * 0x1D0000, 'TEKKEN.BIN': b'\0' * 2048}))
            with self.assertRaises(ttt_disc.DiscError) as error:
                laser.laser_set(disc)
            self.assertIn('SLUS_200.01 of an unknown version (SYSTEM.CNF: VER = 3.00), not 1.00 or 2.00', str(error.exception))
            self.assertFalse(laser.found(disc))

    def test_not_a_disc(self):
        with tempfile.TemporaryDirectory() as temp:
            disc = Path(temp) / 'zeros.iso'
            disc.write_bytes(bytes(40 * 2048))
            self.assertFalse(laser.found(disc))
            self.assertFalse(laser.found(Path(temp) / 'missing.iso'))


@unittest.skipUnless(DISC, 'no Tekken Tag Tournament USA PS2 disc here')
class FromTheDisc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entry, cls.images = laser.laser_set(DISC)

    def test_the_same_set_in_each_file(self):
        self.assertEqual(self.entry, 585)
        with ttt_disc.Disc(DISC) as d:
            tekken = ttt_disc.TekkenBin(d)
            for k in laser.ENTRIES:
                self.assertEqual(laser.digest(laser.find_set(tekken.read(k))), laser.SHA256, k)
            self.assertIsNone(laser.find_set(tekken.read(582)))

    def test_install(self):
        with tempfile.TemporaryDirectory() as temp:
            out = laser.install(DISC, Path(temp) / 'laser-pack', say=lambda line: None)
            self.assertTrue(laser_version.current(out))
            pack = (out / laser_version.FILE).read_bytes()
            angel = (out / laser_version.ANGEL_FILE).read_bytes()
        images = laser.read_pack(pack)
        self.assertEqual([(w, h) for w, h, _, _ in images], laser.SHAPE)
        for (w, h, pixels, clut), (u, p) in zip(images, self.images):
            self.assertEqual(pixels, u.data)                    # indices kept
            for i, v in enumerate(clut):
                self.assertEqual(bool(v & 0x8000), v != 0)      # STP on every colour drawn
                self.assertEqual(v, laser.colour15(*p.data[4 * i:4 * i + 3]))
            self.assertEqual({p.data[4 * i + 3] for i in range(16)}, {0x80})
        # Angel's: the same images, her palettes gold.
        for (w, h, pixels, clut), (u, p) in zip(laser.read_pack(angel), self.images):
            self.assertEqual(pixels, u.data)
            self.assertEqual(list(clut), [laser.colour15(*laser.gold(*p.data[4 * i:4 * i + 3])) for i in range(16)])
        self.assertEqual(hashlib.sha256(pack).hexdigest(), PACK_SHA256,
                         'ps2-laser.tim changed: increase laser_version.LASER_VERSION, then this')
        self.assertEqual(hashlib.sha256(angel).hexdigest(), ANGEL_SHA256,
                         'ps2-laser-angel.tim changed: increase laser_version.LASER_VERSION, then this')

    @unittest.skipUnless(STUDY.is_file(), "no study sheet here")
    def test_sheet_as_the_study(self):
        from PIL import Image, ImageChops
        first = self.images[0][0].at
        labels = [f'{STUDY_RAM + u.at - first:#x} {u.width}x{u.height}' for u, _ in self.images]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'sheet.png'
            laser.sheet(laser.ps2_images(self.images), out, labels)
            with Image.open(out) as mine, Image.open(STUDY) as study:
                self.assertIsNone(ImageChops.difference(mine.convert('RGB'), study.convert('RGB')).getbbox())


import ttt_hitspark_ps2 as hitspark  # noqa: E402

# The Mishima's strong-hit packs made from the USA disc (ttt_hitspark_ps2.py):
# if the conversion changes, so do these, and laser_version.LASER_VERSION.
HITSPARK_SHA256 = {
    'Jin': 'dd6777bbd8c998da9c16d7b45133e63223040f00756685b2db5e2f9f6c599d41',
    'Heihachi': 'a4043a2de35b3e9af7ed4ec95eb5be49a57b43db7d40182e9b238dac070928c5',
    'Kazuya': '11fa764109b560ba373e19f868477740327d056aac8fc01e856710d01d173514',
    'Devil': 'a0197ef832e7a338ac3deb932b1fc76b02bdc03d023f4f7ae047c01eb6a2acf8',
    'Angel': '8841aef775088799254ee27c8bfb49d225053f6329b466580982b274fe767aea',
}


def read_hfx(data: bytes):
    """(images, palettes, flags, [16 colours] per palette, [64 x 64 indices] per image) of a .hfx."""
    magic, version, images, side, palettes, flags, _ = struct.unpack_from('<4s6H', data)
    assert (magic, version, side) == (b'HFX6', 1, 64) and len(data) == 16 + 32 * palettes + 2048 * images
    cluts = [struct.unpack_from('<16H', data, 16 + 32 * k) for k in range(palettes)]
    at = 16 + 32 * palettes
    pixels = [[v for b in data[at + 2048 * k:at + 2048 * (k + 1)] for v in (b & 15, b >> 4)] for k in range(images)]
    return images, palettes, flags, cluts, pixels


class HitsparkConversion(unittest.TestCase):
    def test_shrink_keeps_the_brightest_texel(self):
        palette = [(i * 16, i * 16, i * 16) for i in range(16)]
        image = bytearray(128 * 64)
        image[0] = 0x3 | 0x9 << 4          # top left block: 3, 9 on its first line
        image[64] = 0x5                     # and 5 under the 3
        out = hitspark.shrink(bytes(image), palette)
        self.assertEqual(len(out), 64 * 32)
        self.assertEqual(out[0] & 15, 9)
        self.assertEqual(sum(out[1:]), 0)

    def test_hfx_layout(self):
        pal = bytes(4 * 16)
        images = [(bytes(8192), pal)] * 40
        data = hitspark.hfx(images)
        n, palettes, flags, _, _ = read_hfx(data)
        self.assertEqual((n, palettes, flags), (hitspark.MOST, hitspark.MOST, 1))


@unittest.skipUnless(DISC, 'no Tekken Tag Tournament USA PS2 disc here')
class HitsparksFromTheDisc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = hitspark.sets(DISC)
        cls.files = hitspark.files(DISC)

    def test_sets_as_the_study_ram(self):
        for name, images in self.sets.items():
            self.assertEqual(len(images), hitspark.SETS[name][2], name)
            self.assertEqual(hitspark.digest(images), hitspark.SETS[name][3], name)

    def test_packs(self):
        self.assertEqual(sorted(self.files), sorted(laser_version.HITSPARK_FILES))
        for name, want in HITSPARK_SHA256.items():
            data = self.files[f'{name}-PS2-hiteffect64.hfx']
            n, palettes, flags, cluts, _ = read_hfx(data)
            self.assertEqual(n, min(hitspark.MOST, len(self.sets['Devil' if name == 'Angel' else name])), name)
            self.assertEqual((palettes, flags), (n, 1), name)
            for clut in cluts:
                for v in clut: self.assertEqual(bool(v & 0x8000), v != 0, name)
            self.assertEqual(hashlib.sha256(data).hexdigest(), want,
                             f'{name}: the pack changed: increase laser_version.LASER_VERSION, then this')

    def test_angel_is_devil_in_gold(self):
        devil = read_hfx(self.files['Devil-PS2-hiteffect64.hfx'])
        angel = read_hfx(self.files['Angel-PS2-hiteffect64.hfx'])
        self.assertEqual(devil[4], angel[4])
        for k, (_, palette) in enumerate(self.sets['Devil'][:hitspark.MOST]):
            self.assertEqual(list(angel[3][k]), [laser.colour15(*laser.gold(*c)) for c in hitspark.colours(palette)])

    def test_install_writes_them(self):
        with tempfile.TemporaryDirectory() as temp:
            out = laser.install(DISC, Path(temp) / 'laser-pack', say=lambda line: None)
            self.assertTrue(laser_version.current(out))
            for name in laser_version.HITSPARK_FILES:
                self.assertEqual((out / name).read_bytes(), self.files[name], name)


if __name__ == '__main__':
    unittest.main()
