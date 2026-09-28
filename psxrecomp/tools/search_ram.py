#!/usr/bin/env python3
"""Search PSX runtime RAM for a 4-byte value via TCP debug server."""
import subprocess
import json
import sys

NC = '/c/Program Files (x86)/Nmap/ncat'
TARGET = '9c600000'  # 0x0000609C in little-endian hex

RANGES = [
    (0x0000, 0x8000),    # kernel
    (0x30000, 0x90000),  # shell data
]

found = []

for (start, end) in RANGES:
    print(f"Scanning 0x{start:05X}-0x{end:05X}...")
    for base in range(start, end, 0x1000):
        addr_hex = format(base, 'x')
        cmd = f"""(printf '{{"cmd":"read_ram","addr":"{addr_hex}","len":4096}}\\n'; sleep 0.5) | "{NC}" localhost 4370"""
        try:
            proc = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True, text=True, timeout=10
            )
            d = json.loads(proc.stdout.strip())
            hexdata = d.get('hex', '').lower()
            pos = 0
            while True:
                idx = hexdata.find(TARGET, pos)
                if idx == -1:
                    break
                # Check alignment: idx must be even (byte-aligned)
                if idx % 2 != 0:
                    pos = idx + 1
                    continue
                byte_offset = idx // 2
                ram_addr = base + byte_offset
                found.append(ram_addr)
                print(f"  FOUND at 0x{ram_addr:08X} (chunk 0x{base:05X}, byte offset 0x{byte_offset:03X})")
                pos = idx + len(TARGET)
        except Exception as e:
            print(f"  Error at 0x{base:05X}: {e}", file=sys.stderr)

print()
if found:
    print(f"=== {len(found)} match(es) found ===")
    for addr in found:
        print(f"  0x{addr:08X}")
else:
    print("=== No matches found ===")
