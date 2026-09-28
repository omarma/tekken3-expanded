#!/usr/bin/env python3
"""Find all JAL instructions in code regions that target GTE library addresses."""
import struct

ROM_PATH = "bios/SCPH1001.BIN"
ROM_BASE = 0xBFC00000

CODE_REGIONS = [
    (0xBFC00000, 0xBFC0DC60),
    (0xBFC10000, 0xBFC16760),
    (0xBFC18000, 0xBFC42800),
]

# GTE library is at BFC34E00-BFC36D00 (shell region)
# RAM addresses: 0x80030000 + (BFC34E00 - BFC18000) = 0x80030000 + 0x1CE00 = 0x8004CE00
# to 0x80030000 + (BFC36D00 - BFC18000) = 0x80030000 + 0x1ED00 = 0x8004ED00
GTE_LIB_RAM_LO = 0x8004CE00
GTE_LIB_RAM_HI = 0x8004F000

with open(ROM_PATH, "rb") as f:
    rom = f.read()

def in_code(addr):
    return any(lo <= addr < hi for lo, hi in CODE_REGIONS)

# Find all JAL instructions targeting GTE library
# JAL encoding: opcode=0x02 (bits 31-26), target in bits 25-0 (shifted left 2)
callers = []
for lo, hi in CODE_REGIONS:
    for off in range(lo - ROM_BASE, hi - ROM_BASE, 4):
        word = struct.unpack_from("<I", rom, off)[0]
        opcode = (word >> 26) & 0x3F
        if opcode == 0x03:  # JAL
            target26 = word & 0x03FFFFFF
            # JAL target: PC[31:28] | (target26 << 2)
            caller_addr = ROM_BASE + off
            # In KSEG1 (0xBFC...), top 4 bits = 0xB
            target = 0xB0000000 | (target26 << 2)
            # Convert to RAM: KSEG1 0xB00xxxxx -> KUSEG 0x000xxxxx -> KSEG0 0x800xxxxx
            target_ram = 0x80000000 | (target & 0x1FFFFFFF)
            if GTE_LIB_RAM_LO <= target_ram < GTE_LIB_RAM_HI:
                # Convert target to ROM address
                target_rom = 0xBFC18000 + (target_ram - 0x80030000)
                callers.append((caller_addr, target_ram, target_rom))

print(f"Found {len(callers)} JAL calls to GTE library ({GTE_LIB_RAM_LO:#x}-{GTE_LIB_RAM_HI:#x}):")
from collections import defaultdict
by_target = defaultdict(list)
for caller, target_ram, target_rom in callers:
    by_target[target_rom].append(caller)

for target in sorted(by_target):
    callers_list = by_target[target]
    print(f"\n  Target 0x{target:08X} (RAM 0x{target-0xBFC18000+0x80030000:08X}):")
    for c in callers_list:
        # Find which function the caller is in
        region = "kernel1" if c < 0xBFC10000 else ("kernel2" if c < 0xBFC18000 else "shell")
        print(f"    Called from 0x{c:08X} ({region})")
