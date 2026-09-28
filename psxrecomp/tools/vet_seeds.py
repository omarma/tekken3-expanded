#!/usr/bin/env python3
"""
vet_seeds.py — Vet dirty_ram miss addresses as function-seed candidates.

For each candidate address applies two checks directly against the game EXE:

  1. BOUNDARY: the 8 bytes immediately before the address must be
     `jr $ra` (0x03E00008) followed by `nop` (0x00000000).
     Fail → REJECT (mid-function address, never safe to seed).

  2. PROLOGUE: at least one of the first 4 instructions must be
     `addiu $sp, $sp, -N` (N > 0).
     Fail → WARN (frameless: leaf function or frame-borrower like DF00).
     Frame-borrowers crash when called from a context that hasn't set up
     the expected caller frame. Requires manual confirmation before seeding.

Verdict summary:
  ACCEPT  — boundary + prologue: safe to seed.
  WARN    — boundary, no prologue: manual review required.
  REJECT  — no boundary: mid-function, never seed.

Usage:
  python3 tools/vet_seeds.py --game <game.toml> <miss_file>

  <miss_file>  path to seeds/dirty_ram_misses.txt or similar; lines starting
               with a hex address (0x...) are parsed, rest are ignored.

Example:
  python3 psxrecomp/tools/vet_seeds.py --game game.toml seeds/dirty_ram_misses.txt
"""

import sys
import os
import re
import struct
import argparse

# ---------------------------------------------------------------------------
# Minimal TOML reader — only parses [game] section fields we need.
# ---------------------------------------------------------------------------

def _parse_toml_str(path, section, key):
    """Return the string value of section.key from a TOML file, or None."""
    in_section = False
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^\[(\w+)\]', line)
            if m:
                in_section = (m.group(1) == section)
                continue
            if in_section:
                m = re.match(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', line)
                if m:
                    return m.group(1)
    return None

# ---------------------------------------------------------------------------
# MIPS decode helpers
# ---------------------------------------------------------------------------

def _word(data, off):
    return struct.unpack_from('<I', data, off)[0]

def _is_jr_ra(w):
    return w == 0x03E00008          # jr $ra

def _is_nop(w):
    return w == 0x00000000

def _is_addiu_sp_neg(w):
    """addiu $sp, $sp, -N  (N > 0) — stack frame setup."""
    return ((w >> 26) & 0x3F) == 9 \
        and ((w >> 21) & 0x1F) == 29 \
        and ((w >> 16) & 0x1F) == 29 \
        and (w & 0x8000) != 0

# ---------------------------------------------------------------------------
# Vetting logic
# ---------------------------------------------------------------------------

def vet(exe_bytes, base_phys, text_size, vaddr):
    """
    Returns (verdict, reason).
    verdict: 'ACCEPT' | 'WARN' | 'REJECT'
    """
    EXE_HEADER = 0x800
    phys = vaddr & 0x1FFFFFFF

    if phys < base_phys or phys >= base_phys + text_size:
        return 'REJECT', 'outside game text range'

    off = EXE_HEADER + (phys - base_phys)

    if off < 8 or off + 16 > len(exe_bytes):
        return 'REJECT', 'EXE offset out of range'

    # Check 1: boundary — jr $ra followed by any delay slot (nop is common
    # but some compilers emit a useful instruction in the delay slot).
    prev_jr   = _word(exe_bytes, off - 8)
    prev_ds   = _word(exe_bytes, off - 4)
    has_boundary = _is_jr_ra(prev_jr)
    if not has_boundary:
        return 'REJECT', (
            f'no jr $ra/nop boundary '
            f'(saw 0x{prev_jr:08X} / 0x{prev_ds:08X})'
        )
    # Note non-nop delay slot — still a valid boundary but worth flagging.
    delay_note = '' if _is_nop(prev_ds) else f' (non-nop delay slot 0x{prev_ds:08X})'

    # Check 2: prologue
    for i in range(4):
        if _is_addiu_sp_neg(_word(exe_bytes, off + i * 4)):
            return 'ACCEPT', f'boundary + prologue at instr {i}{delay_note}'

    return 'WARN', (
        f'boundary + no addiu $sp,$sp,-N{delay_note}'
        ' -- frameless (leaf or frame-borrower); manual Ghidra check required'
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', required=True, metavar='TOML',
                    help='Path to game.toml')
    ap.add_argument('miss_file',
                    help='File containing candidate addresses (dirty_ram_misses.txt etc.)')
    args = ap.parse_args()

    # Resolve paths relative to game.toml directory
    game_dir = os.path.dirname(os.path.abspath(args.game))

    exe_rel    = _parse_toml_str(args.game, 'game', 'exe')
    load_str   = _parse_toml_str(args.game, 'game', 'load_address')
    tsize_str  = _parse_toml_str(args.game, 'game', 'text_size')

    if not all([exe_rel, load_str, tsize_str]):
        sys.exit('ERROR: game.toml missing exe / load_address / text_size under [game]')

    exe_path  = os.path.join(game_dir, exe_rel)
    load_addr = int(load_str, 16)
    text_size = int(tsize_str, 16)
    base_phys = load_addr & 0x1FFFFFFF

    if not os.path.exists(exe_path):
        sys.exit(f'ERROR: game EXE not found: {exe_path}')

    with open(exe_path, 'rb') as f:
        exe_bytes = f.read()

    # Parse candidate addresses
    candidates = []
    with open(args.miss_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^(0x[0-9A-Fa-f]+)', line)
            if m:
                candidates.append((int(m.group(1), 16), line))

    if not candidates:
        sys.exit('No candidate addresses found in input file.')

    print(f'Game EXE : {exe_path}')
    print(f'Load addr: 0x{load_addr:08X}  text_size: 0x{text_size:X}')
    print(f'Checking {len(candidates)} candidate(s)...')
    print()

    accepted = []
    warned   = []
    rejected = []

    for vaddr, raw_line in candidates:
        verdict, reason = vet(exe_bytes, base_phys, text_size, vaddr)
        tag = {'ACCEPT': '[ACCEPT]', 'WARN': '[ WARN ]', 'REJECT': '[REJECT]'}[verdict]
        print(f'  {tag}  0x{vaddr:08X}  {reason}')
        if verdict == 'ACCEPT':
            accepted.append(vaddr)
        elif verdict == 'WARN':
            warned.append(vaddr)
        else:  # REJECT
            rejected.append((vaddr, reason))

    print()
    print(f'Results: {len(accepted)} ACCEPT  {len(warned)} WARN  {len(rejected)} REJECT')

    if accepted:
        print()
        print('Safe to add to ghidra_funcs.txt:')
        for a in accepted:
            print(f'  0x{a:08X}')

    if warned:
        print()
        print('WARN — verify in Ghidra before seeding (check callers set up a frame):')
        for a in warned:
            print(f'  0x{a:08X}')

    if rejected:
        print()
        print('REJECT — mid-function or out-of-range (high confidence); rare false-rejects')
        print('  possible when the preceding function ends with jr $t0 / jalr instead of jr $ra.')
        print('  Investigate in Ghidra if you suspect a false-reject:')
        for addr, reason in rejected:
            print(f'  0x{addr:08X}  # {reason}')

if __name__ == '__main__':
    main()
