"""Inspect a PSX memcard image — show sector 0, sector 1 (first dir entry),
and check whether sectors 1..15 are formatted-empty (proper) vs zero-padded
(invalid)."""
import sys

def show_sector(name, data, n=16):
    print(f"  {name}: " + ' '.join(f'{b:02X}' for b in data[:n]))

for path in ('dummy.0.mcr', 'dummy.1.mcr', 'card1.mcd', 'card2.mcd'):
    try:
        d = open(path, 'rb').read()
    except FileNotFoundError:
        continue
    print(f"=== {path}  ({len(d)} bytes) ===")
    if len(d) != 131072:
        print("  WRONG SIZE — expected 131072")
        continue
    # Sector 0 (header)
    show_sector("sec 0 (header)", d[0:128])
    # Directory frames: sectors 1..15
    for s in range(1, 16):
        off = s * 128
        sec = d[off:off+128]
        # PSX free directory entry: byte0=0xA0, byte8..11=0xFFFFFFFF, byte127=checksum
        print(f"  sec {s:>2}: " + ' '.join(f'{b:02X}' for b in sec[:16])
              + f"  ck=0x{sec[127]:02X}")
    # Count non-zero bytes in directory frames (sectors 1..15)
    nz = sum(1 for b in d[128:128*16] if b != 0)
    print(f"  non-zero bytes in dir frames 1..15: {nz}/{128*15}")
    print()
