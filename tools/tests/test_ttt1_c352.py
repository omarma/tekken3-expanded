import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ttt1'))
import c352


class Ttt1C352ReplayTests(unittest.TestCase):
    def test_key_on_ramps_the_volume_then_the_sample_ends(self):
        # Voice 1: 1024 bytes of linear 0x40 at half rate, full front volume.
        rom = bytes((0x40,) * 1024) + bytes(64)
        writes = [(10, 8 + 0, 0xffff, 0xffff), (10, 8 + 2, 0x8000, 0xffff), (10, 8 + 6, 1023, 0xffff),
                  (10, 8 + 3, c352.KEYON, 0xffff), (10, c352.KEY, 0, 0xffff)]
        left, right = c352.render(rom, [], writes, 0, 2400)
        self.assertEqual(left[:10], [0] * 10)
        self.assertEqual(left, right)
        # At half rate, one volume step per sample, up to 0xff.
        self.assertEqual(max(left), (0x40 << 8) * 0xff >> 8 >> 3)
        self.assertLess(left.index(max(left)), 10 + 0x110)
        self.assertEqual(left[-20:], [0] * 20)

    def test_output_keeps_a_level_four_samples_late(self):
        chip = [0] * 200 + [8000] * 800
        out = list(c352.output(chip, 0, 20, 500))
        step = 20 + next(i for i, v in enumerate(out) if v > 4000)   # cubic: a small undershoot first
        self.assertIn(step, range(100 + 3, 100 + 6))
        self.assertLessEqual(abs(out[300] - 8000), 1)


if __name__ == '__main__':
    unittest.main()
