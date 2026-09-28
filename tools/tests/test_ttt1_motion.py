import struct
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ttt1"))
from motion import decode


class MotionDecoderTests(unittest.TestCase):
    def clip(self, count=18):
        b = bytearray(512)
        b[0] = count
        struct.pack_into("<57H", b, 2, *range(57))
        struct.pack_into("<57H", b, 0x74, *range(100, 157))
        struct.pack_into("<H", b, 0xE6, 0x98)
        return b

    def test_first_last_and_clamped_frames(self):
        b = self.clip()
        self.assertEqual(decode(b, 0, 0), list(range(57)))
        self.assertEqual(decode(b, 0, 17), list(range(100, 157)))
        self.assertEqual(decode(b, 0, 999, 3), [100, 101, 102])

    def test_absolute_and_repeated_deltas(self):
        b = self.clip()
        # Span=2 words; opcode=repeat(+1..+4); repeat nibble=1 gives
        # three applications. Payloads 0, 1, 2 give deltas 16, 32, 48.
        bits = 2 | (12 << 4) | (1 << 8) | (0 << 12) | (1 << 14) | (2 << 16)
        struct.pack_into("<I", b, 0x130, bits)
        self.assertEqual(decode(b, 0, 1, 1), [16])
        self.assertEqual(decode(b, 0, 2, 1), [48])
        self.assertEqual(decode(b, 0, 3, 1), [96])
        struct.pack_into("<I", b, 0x130, 2 | (7 << 4) | (0xABC << 8))
        self.assertEqual(decode(b, 0, 1, 1), [0xABC0])

    def test_height_and_distance_use_quarter_angle_quantum(self):
        b = self.clip()
        for i in range(3):
            struct.pack_into("<H", b, 0x130 + i * 2, 1 | (4 << 4))
        self.assertEqual(decode(b, 0, 1, 3), [16, 5, 6])

    def test_next_block_and_wrapping(self):
        b = self.clip(20)
        struct.pack_into("<H", b, 2, 0xFFF8)
        struct.pack_into("<H", b, 0xE8, 0xA0)
        struct.pack_into("<H", b, 0x140, 1 | (4 << 4))
        self.assertEqual(decode(b, 0, 17, 1), [8])

    def test_rejects_invalid_and_truncated_input(self):
        b = self.clip()
        for args in [(b, -1, 0), (b[:30], 0, 0), (b, 0, -1), (b, 0, 0, 58)]:
            with self.assertRaises(ValueError):
                decode(*args)
        b[0] = 0
        with self.assertRaises(ValueError):
            decode(b, 0, 0)

    def test_rejects_bad_span_and_payload_overrun(self):
        b = self.clip()
        with self.assertRaises(ValueError):
            decode(b, 0, 1, 1)
        struct.pack_into("<I", b, 0x130, 1 | (7 << 4) | (0xABC << 8))
        with self.assertRaises(ValueError):
            decode(b, 0, 1, 1)


if __name__ == "__main__":
    unittest.main()
