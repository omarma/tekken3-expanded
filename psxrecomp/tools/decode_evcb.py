#!/usr/bin/env python3
"""Decode EvCB array dump."""
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'evcb_dump.json'
with open(path) as f:
    d = json.loads(f.read())
hex_str = d['hex']
data = bytes.fromhex(hex_str)
base = int(d['addr'], 16)

# EvCB stride hypotheses
for stride in (28, 32, 24, 16, 20):
    print(f"\n=== Stride {stride} ===")
    # head was 0xa000e004 = base + 0x04
    arr_start = base + 0x04
    found = False
    for i in range(40):
        off = (arr_start - base) + i * stride
        if off + stride > len(data):
            break
        e = data[off:off+stride]
        # Look at first 2 words
        cls = int.from_bytes(e[0:4], 'little')
        sta = int.from_bytes(e[4:8], 'little')
        sp = int.from_bytes(e[8:12], 'little') if stride >= 12 else 0
        mo = int.from_bytes(e[12:16], 'little') if stride >= 16 else 0
        # Print interesting (class != 0 or status != 0)
        if cls or sta:
            print(f"  slot {i:3d} @0x{base+off:05X}: class=0x{cls:08X} status=0x{sta:08X} spec=0x{sp:08X} mode=0x{mo:08X}")
            if cls == 0xF4000001:
                found = True
    if found:
        print("  ^^^ Found 0xF4000001 entries with this stride")
