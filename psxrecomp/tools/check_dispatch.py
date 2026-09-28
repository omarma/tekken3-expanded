#!/usr/bin/env python3
"""Check which psx_dispatch targets are in the dispatch table."""
import re, sys

# Read dispatch table entries
dispatch_addrs = set()
with open('generated/SCPH1001_dispatch.c') as f:
    for line in f:
        m = re.search(r'\{ (0x[0-9A-Fa-f]+)u, func_', line)
        if m:
            dispatch_addrs.add(int(m.group(1), 16))

def normalize(addr):
    phys = addr & 0x1FFFFFFF
    if 0x1FC10000 <= phys <= 0x1FC17FFF:
        phys = phys - 0x1FC10000 + 0x500
    if 0x30000 <= phys <= 0x5AFFF:
        phys = phys - 0x30000 + 0x1FC18000
    return phys

# Shell entry dispatch calls
addrs = [
    0x8005A8D0, 0x8005A8E0, 0x80030798, 0x800403F0,
    0x8004EF90, 0x8003FDB0, 0x8003FE88, 0x8003F910,
    0x80040490, 0x80030788, 0x80059C80, 0x8004ED1C,
    0x80035BF4, 0x80030788, 0x80035DD8, 0x80035F50,
    0x80030788, 0x800359C4, 0x80056FF0, 0x800359C4,
    0x8003FB24, 0x80030684, 0x800360C4, 0x80030788,
    0x8003D558, 0x8003DE8C, 0x80059E30, 0x80059F10,
    0x8004B6F0, 0x80030254,
]

for i, a in enumerate(addrs):
    n = normalize(a)
    in_table = n in dispatch_addrs
    status = "OK" if in_table else "MISS"
    print(f"{i+1:2d}. 0x{a:08X} -> 0x{n:08X}  {status}")
