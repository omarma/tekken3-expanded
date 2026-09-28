#!/usr/bin/env python3
"""Decode a MIPS jump table from hex."""
import struct, sys

hex_data = sys.argv[1]
base_state = int(sys.argv[2]) if len(sys.argv) > 2 else 2

data = bytes.fromhex(hex_data)
n = len(data) // 4
print(f"Jump table entries (state {base_state}-{base_state+n-1}):")
for i in range(n):
    addr = struct.unpack_from('<I', data, i * 4)[0]
    state = i + base_state
    print(f"  state 0x{state:02X} ({state:2d}): target = 0x{addr:08X}")
