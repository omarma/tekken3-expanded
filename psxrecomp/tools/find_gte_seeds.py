#!/usr/bin/env python3
"""Find all function entry points in the GTE library region by scanning for jr $ra patterns."""
import struct, json

ROM_PATH = "bios/SCPH1001.BIN"
ROM_BASE = 0xBFC00000

# GTE library region (from the audit: BFC34F00 to BFC36D00)
# Actually scan a wider range to catch everything
SCAN_LO = 0xBFC34E00
SCAN_HI = 0xBFC37000

with open(ROM_PATH, "rb") as f:
    rom = f.read()

# Find all jr $ra instructions in the scan range
JR_RA = 0x03E00008
NOP = 0x00000000

entries = []
off_lo = SCAN_LO - ROM_BASE
off_hi = SCAN_HI - ROM_BASE

# Strategy: after every "jr $ra; nop" pair, the next non-NOP word starts a new function
i = off_lo
while i < off_hi - 8:
    word = struct.unpack_from("<I", rom, i)[0]
    if word == JR_RA:
        # Found jr $ra at offset i. Delay slot is at i+4.
        delay = struct.unpack_from("<I", rom, i + 4)[0]
        # Next instruction after delay slot
        next_off = i + 8
        if next_off < off_hi:
            next_word = struct.unpack_from("<I", rom, next_off)[0]
            if next_word != NOP and next_word != JR_RA:
                entry_addr = ROM_BASE + next_off
                entries.append(entry_addr)
    i += 4

# Also check the very first instruction in the range as a potential entry
first_word = struct.unpack_from("<I", rom, off_lo)[0]
first_addr = ROM_BASE + off_lo
if first_addr not in entries:
    entries.insert(0, first_addr)

# Deduplicate and sort
entries = sorted(set(entries))

# Load existing seeds to check which are new
existing_seeds = set()
seed_file = "recompiler/seeds/phase2_ghidra_seeds.json"
try:
    with open(seed_file) as f:
        data = json.load(f)
    for s in data.get("seeds", []):
        existing_seeds.add(int(s["address"], 16))
except:
    pass

print(f"Found {len(entries)} potential function entries in {SCAN_LO:#010x}-{SCAN_HI:#010x}")
new_count = 0
for addr in entries:
    # Show the first few bytes for verification
    off = addr - ROM_BASE
    words = [struct.unpack_from("<I", rom, off + j*4)[0] for j in range(3)]
    mnemonics = []
    for w in words:
        op = (w >> 26) & 0x3F
        if op == 0x32:
            mnemonics.append("lwc2")
        elif op == 0x3A:
            mnemonics.append("swc2")
        elif op == 0x12:
            mnemonics.append("cop2")
        elif op == 0x09:
            mnemonics.append("addiu")
        elif op == 0x0F:
            mnemonics.append("lui")
        elif op == 0x00:
            func = w & 0x3F
            if func == 0x08:
                mnemonics.append("jr")
            elif func == 0x21:
                mnemonics.append("addu")
            elif func == 0x00 and w == 0:
                mnemonics.append("nop")
            else:
                mnemonics.append(f"r{func:#04x}")
        else:
            mnemonics.append(f"op{op:#04x}")

    is_new = addr not in existing_seeds
    marker = "NEW" if is_new else "exists"
    if is_new:
        new_count += 1
    print(f"  {addr:#010x}: {' '.join(mnemonics):30s} [{marker}]")

print(f"\n{new_count} new seeds to add")

# Output as seed entries
if new_count > 0:
    print("\nSeed JSON entries:")
    for addr in entries:
        if addr not in existing_seeds:
            print(f'    {{"address": "0x{addr:08X}", "name": "gte_lib_{addr:08X}"}}')
