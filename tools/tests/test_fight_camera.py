"""Guard the native camera adapter against source drift and unrelated changes."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from build_fight_camera import generate, SITES


class FightCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'generated/SLUS_004.02_full_26.c').read_text(encoding='utf-8')
        cls.exe = (ROOT / 'disc/SLUS_004.02').read_bytes()

    def test_only_horizontal_arithmetic_changes(self):
        result = generate(self.source, self.exe)
        self.assertEqual(result.count('tekken3_fight_camera_focal(cpu)'), 8)
        # Removing the operand substitutions must recover the original function
        # byte-for-byte, including all continuations and cycle instrumentation.
        result = result[result.index('void __wrap_func_80064E10('):]
        result = result.replace('__wrap_func_80064E10', 'func_80064E10', 1)
        result = result.replace('    { const uint32_t wide_focal = tekken3_fight_camera_focal(cpu);\n', '')
        result = result.replace('wide_focal', 'cpu->gpr[18]')
        result = result.replace('\n    tekken3_fight_camera_capture_yaw(cpu);', '')
        # Each injected block closes immediately before the MULT/DIV latency.
        result = result.replace('\n    }\n#ifdef PSX_ENABLE_BLOCK_CYCLES\n    psx_muldiv_set',
                                '\n#ifdef PSX_ENABLE_BLOCK_CYCLES\n    psx_muldiv_set')
        start = self.source.index('void func_80064E10(CPUState* cpu)\n{')
        end = self.source.index('\n}\n', start) + 3
        self.assertEqual(result, self.source[start:end])

    def test_mismatched_disc_is_rejected(self):
        bad = bytearray(self.exe)
        bad[0x80065448 - 0x80010000 + 0x800] ^= 1
        with self.assertRaisesRegex(ValueError, 'instruction mismatch'):
            generate(self.source, bytes(bad))

    def test_each_changed_generated_instruction_is_rejected(self):
        for address, word in SITES.items():
            with self.subTest(address=hex(address)):
                bad = self.source.replace(f'0x{address:08X}: 0x{word:08X}',
                                          f'0x{address:08X}: 0x00000000')
                with self.assertRaisesRegex(ValueError, 'marker mismatch'):
                    generate(bad, self.exe)


if __name__ == '__main__':
    unittest.main()
