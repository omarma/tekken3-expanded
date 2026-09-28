"""Scan for all addiu/ori instructions with a given 16-bit imm."""
import struct, sys
with open('bios/SCPH1001.BIN','rb') as f:
    rom = f.read()
BASE = 0xBFC00000
imm_want = int(sys.argv[1], 16)
for off in range(0, len(rom)-3, 4):
    w = struct.unpack('<I', rom[off:off+4])[0]
    op = (w >> 26) & 0x3f
    if op in (9, 13) and (w & 0xffff) == imm_want:
        pc = BASE + off
        rt = (w >> 16) & 0x1f
        rs = (w >> 21) & 0x1f
        name = 'addiu' if op == 9 else 'ori'
        print(f'0x{pc:08X}: {name} ${rt},${rs},0x{imm_want:X}')
