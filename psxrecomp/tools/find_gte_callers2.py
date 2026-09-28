#!/usr/bin/env python3
"""Find all JAL instructions targeting GTE library, with correct address decoding."""
import struct
from collections import defaultdict

ROM_PATH = "bios/SCPH1001.BIN"
ROM_BASE = 0xBFC00000

CODE_REGIONS = [
    (0xBFC00000, 0xBFC0DC60),
    (0xBFC10000, 0xBFC16760),
    (0xBFC18000, 0xBFC42800),
]

# GTE library ROM range
GTE_ROM_LO = 0xBFC34E00
GTE_ROM_HI = 0xBFC37000

# Corresponding RAM range (shell: ROM BFC18000 -> RAM 0x80030000)
SHELL_ROM_BASE = 0xBFC18000
SHELL_RAM_BASE = 0x80030000

def rom_to_ram(rom_addr):
    return SHELL_RAM_BASE + (rom_addr - SHELL_ROM_BASE)

GTE_RAM_LO = rom_to_ram(GTE_ROM_LO)
GTE_RAM_HI = rom_to_ram(GTE_ROM_HI)

with open(ROM_PATH, "rb") as f:
    rom = f.read()

callers = []
for lo, hi in CODE_REGIONS:
    for off in range(lo - ROM_BASE, hi - ROM_BASE, 4):
        word = struct.unpack_from("<I", rom, off)[0]
        opcode = (word >> 26) & 0x3F
        if opcode == 0x03:  # JAL
            target26 = word & 0x03FFFFFF
            # Shell code runs from RAM, so PC[31:28] = 0x8
            # For kernel code running from ROM, PC[31:28] = 0xB
            # But kernel would call through RAM addresses too after shell copy
            # The recompiler uses 0x8 prefix for RAM targets
            target_ram = 0x80000000 | (target26 << 2)
            caller_rom = ROM_BASE + off

            if GTE_RAM_LO <= target_ram < GTE_RAM_HI:
                target_rom = SHELL_ROM_BASE + (target_ram - SHELL_RAM_BASE)
                callers.append((caller_rom, target_ram, target_rom))

print(f"JAL calls to GTE library (RAM {GTE_RAM_LO:#x}-{GTE_RAM_HI:#x}):")
print(f"Found: {len(callers)}")

by_target = defaultdict(list)
for caller_rom, target_ram, target_rom in callers:
    by_target[target_rom].append(caller_rom)

for target in sorted(by_target):
    callers_list = by_target[target]
    ram = rom_to_ram(target)
    print(f"\n  Target ROM 0x{target:08X} (RAM 0x{ram:08X}):")
    for c in callers_list:
        region = "kernel1" if c < 0xBFC10000 else ("kernel2" if c < 0xBFC18000 else "shell")
        # Find approximate function
        func_rom = (c & ~0xFFF)  # rough 4KB alignment
        print(f"    Called from 0x{c:08X} ({region})")
