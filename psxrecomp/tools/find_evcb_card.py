#!/usr/bin/env python3
"""Find EvCB entries for class 0xF4000001 (card events)."""
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'evcb_dump.json'
with open(path) as f:
    d = json.loads(f.read())
data = bytes.fromhex(d['hex'])
base = int(d['addr'], 16)

# Find all positions where 0xF4000001 LE bytes appear
target = (0xF4000001).to_bytes(4, 'little')
positions = []
i = 0
while i < len(data):
    p = data.find(target, i)
    if p < 0: break
    positions.append(p)
    i = p + 1

print(f"Positions of 0xF4000001 in dump (base=0x{base:X}):")
for p in positions:
    addr = base + p
    # Show context: 28 bytes before and after
    start = max(0, p - 4)
    end = min(len(data), p + 28)
    ctx = data[start:end]
    # Print as 4-byte words
    print(f"  addr=0x{addr:X} (offset {p}):")
    for j in range(0, len(ctx), 4):
        w = int.from_bytes(ctx[j:j+4], 'little') if j+4 <= len(ctx) else 0
        print(f"    +{j-4 if start==max(0,p-4) and start>0 else j:+3d}: 0x{w:08X}")
    print()
