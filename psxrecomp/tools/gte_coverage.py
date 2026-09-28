#!/usr/bin/env python3
"""Check which ROM functions in the GTE-heavy region are emitted."""
import struct, re

ROM_PATH = "bios/SCPH1001.BIN"
GEN_PATH = "generated/SCPH1001_full.c"
ROM_BASE = 0xBFC00000

# Code regions from CLAUDE.md
CODE_REGIONS = [
    (0xBFC00000, 0xBFC0DC60),  # kernel 1
    (0xBFC10000, 0xBFC16760),  # kernel 2
    (0xBFC18000, 0xBFC42800),  # shell
]

def in_code_region(addr):
    return any(lo <= addr < hi for lo, hi in CODE_REGIONS)

# Scan ROM for GTE in code regions only
with open(ROM_PATH, "rb") as f:
    rom = f.read()

gte_in_code = []
for off in range(0, len(rom), 4):
    word = struct.unpack_from("<I", rom, off)[0]
    opcode = (word >> 26) & 0x3F
    addr = ROM_BASE + off
    if not in_code_region(addr):
        continue
    if opcode == 0x12 and (word >> 25) & 1:  # COP2 command
        gte_in_code.append((addr, word))
    elif opcode in (0x32, 0x3A):  # LWC2/SWC2
        gte_in_code.append((addr, word))

# Find all emitted function ranges
emitted = []  # (start_addr, end_addr_or_None)
with open(GEN_PATH, "r") as f:
    for line in f:
        m = re.match(r'^void func_1FC([0-9A-Fa-f]+)\(CPUState\* cpu\) \{', line)
        if m:
            addr = 0xBFC00000 + int(m.group(1), 16)
            emitted.append(addr)

emitted.sort()
emitted_set = set(emitted)

# Find all generated ROM addresses that emit GTE behavior. Data-register
# transfers may route through helpers so register side effects stay centralized.
gen_gte = set()
with open(GEN_PATH, "r") as f:
    prev_addr = None
    for line in f:
        m = re.search(r'/\* 0x(BFC[0-9A-Fa-f]{5}):', line)
        if m:
            prev_addr = int(m.group(1), 16)
        if (
            'gte_execute' in line
            or 'gte_read_data' in line
            or 'gte_write_data' in line
            or 'gte_data' in line
            or 'gte_ctrl' in line
        ) and prev_addr:
            gen_gte.add(prev_addr)

# Focus on BFC34F00-BFC36D00 region
print("=== GTE instructions in BFC34F00-BFC36D00 ===")
region_gte = [(a, w) for a, w in gte_in_code if 0xBFC34F00 <= a < 0xBFC36D00]
print(f"Total in region: {len(region_gte)}")

missing = [(a, w) for a, w in region_gte if a not in gen_gte]
present = [(a, w) for a, w in region_gte if a in gen_gte]
print(f"Present in generated: {len(present)}")
print(f"Missing: {len(missing)}")

# Check which emitted functions are in this range
funcs_in_range = [a for a in emitted if 0xBFC34F00 <= a < 0xBFC36D00]
print(f"\nEmitted functions in range: {len(funcs_in_range)}")
for a in funcs_in_range:
    print(f"  func_1FC{a-0xBFC00000:05X} (0x{a:08X})")

# For each missing GTE, find nearest emitted function
print(f"\nMissing GTE instructions by function:")
from collections import defaultdict
by_func = defaultdict(list)
for addr, word in missing:
    # Find the function this address belongs to
    best = None
    for fa in emitted:
        if fa <= addr:
            best = fa
        else:
            break
    by_func[best].append((addr, word))

for func_addr in sorted(by_func):
    entries = by_func[func_addr]
    if func_addr:
        name = f"func_1FC{func_addr-0xBFC00000:05X}"
        in_dispatch = func_addr in emitted_set
    else:
        name = "(no function found)"
        in_dispatch = False
    print(f"  {name}: {len(entries)} missing GTE instructions")
    for a, w in entries:
        op = w & 0x3F
        opcode = (w >> 26) & 0x3F
        kind = "COP2cmd" if opcode == 0x12 else ("LWC2" if opcode == 0x32 else "SWC2")
        print(f"    0x{a:08X}: 0x{w:08X} ({kind} op=0x{op:02x})")
