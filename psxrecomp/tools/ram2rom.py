#!/usr/bin/env python3
"""Convert shell RAM addresses to ROM addresses."""
import sys
ram_base = 0x80030000
rom_base = 0xBFC18000
for arg in sys.argv[1:]:
    ram_addr = int(arg, 16)
    rom_addr = ram_addr - ram_base + rom_base
    print(f"  RAM 0x{ram_addr:08X} -> ROM 0x{rom_addr:08X}")
