import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ttt1'))
from voices import decode_sample, mulaw_table


class Ttt1VoiceDecodeTests(unittest.TestCase):
    def test_namco_mulaw_segments_and_negative_values(self):
        table = mulaw_table()
        self.assertEqual([table[i] for i in (0, 16, 24, 48, 100, 127)],
                         [0, 512, 1024, 4096, 17408, 31232])
        self.assertEqual(table[128], -32)
        self.assertEqual(table[255], -31264)

    def test_damage_sample_can_cross_rom_bank_boundary(self):
        rom = bytearray(0x20000)
        rom[0xfffe:0x10003] = bytes((10, 20, 30, 40, 50))
        crossed = decode_sample(rom, 0, 0xfffe, 2, 8)
        flat = decode_sample(bytes((10, 20, 30, 40, 50)), 0, 0, 4, 8)
        self.assertEqual(crossed, flat)
        self.assertGreater(max(struct.unpack('<'+'h'*(len(flat)//2), flat)), 0)

    def test_linear_pcm_is_signed_eight_bit(self):
        # Flags 0: signed 8-bit linear PCM (Roger), next to mu-law (flags 8).
        pcm = decode_sample(bytes((0x40,) * 64), 0, 0, 63, 0)
        values = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
        self.assertEqual(max(values), 0x40 << 8)

    def test_refuses_unsupported_flags_and_out_of_range_data(self):
        for flags in (10, 9, 0x18):
            with self.assertRaises(ValueError):
                decode_sample(bytes(20), 0, 0, 10, flags)
        with self.assertRaises(ValueError):
            decode_sample(bytes(20), 0, 10, 25, 8)

    def test_output_duration_uses_original_arcade_pitch(self):
        pcm = decode_sample(bytes([40])*8505, 0, 0, 8504, 8)
        # Original 88200 Hz chip clock, 0x18af/65536 playback increment.
        self.assertAlmostEqual(len(pcm)/2/44100, 1.0, delta=.002)


if __name__ == '__main__':
    unittest.main()
