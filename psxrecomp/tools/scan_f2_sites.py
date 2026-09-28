#!/usr/bin/env python3
import sys
rom = open('../bios/SCPH1001.BIN','rb').read()

matches = []
for rt in range(32):
    word = (0x0F << 26) | (rt << 16) | 0xF200
    b = word.to_bytes(4, 'little')
    off = 0
    while True:
        o = rom.find(b, off)
        if o == -1: break
        bios_addr = 0xBFC00000 + o
        next_word = int.from_bytes(rom[o+4:o+8], 'little')
        op = (next_word >> 26) & 0x3F
        rs = (next_word >> 21) & 0x1F
        rt_out = (next_word >> 16) & 0x1F
        imm = next_word & 0xFFFF
        matches.append((bios_addr, rt, op, rs, rt_out, imm, next_word, o))
        off = o + 4

print("--- ROM sites forming 0xF200xxxx (class values) ---")
for addr, rt, op, rs, rt_out, imm, nw, offset in matches:
    if rs == rt and rt_out == rt:
        if op == 0x0D:
            marker = "OPENEVENT-TARGET" if imm in (1,2,3,9) else ""
            print(f"  0x{addr:08X}: lui r{rt}, 0xF200; ori r{rt}, 0x{imm:04X}  class=0xF200{imm:04X}  {marker}")

print("\n--- 0xF2000003 (VBlank) sites, JAL-adjacency check ---")
for addr, rt, op, rs, rt_out, imm, nw, offset in matches:
    if rs == rt and rt_out == rt and op == 0x0D and imm == 0x0003:
        o = offset
        # JAL preceding? (i.e. at offset-4)
        if o >= 4:
            prev = int.from_bytes(rom[o-4:o], 'little')
            op_prev = (prev >> 26) & 0x3F
            if op_prev == 0x03:
                jal_addr = 0xBFC00000 + o - 4
                target = (jal_addr & 0xF0000000) | ((prev & 0x3FFFFFF) << 2)
                print(f"  0x{addr:08X}: VBlank class; PREV_JAL at 0x{jal_addr:08X} -> 0x{target:08X}")
            else:
                print(f"  0x{addr:08X}: VBlank class; prev op=0x{op_prev:02x} at 0x{0xBFC00000+o-4:08X}")

# Now: find which functions contain these addresses
# A function "contains" addr if it's the closest-entry <= addr
# Read dispatch.c:
print("\n--- Functions containing 0xF2000003 sites ---")
import re
dispatch = open('../generated/SCPH1001_dispatch.c').read()
entries = re.findall(r'\{\s*0x([0-9A-F]+)u,\s*func_([0-9A-F]+)\s*\}', dispatch)
# Only keep those in code range (phys 0x1FC00000+)
fn_list = sorted([(int(a,16), name) for a,name in entries])
def containing_fn(addr):
    phys = addr & 0x1FFFFFFF
    prev = None
    for faddr, name in fn_list:
        if faddr <= phys:
            prev = (faddr, name)
        else:
            break
    return prev

for addr, rt, op, rs, rt_out, imm, nw, offset in matches:
    if rs == rt and rt_out == rt and op == 0x0D and imm == 0x0003:
        cf = containing_fn(addr)
        if cf:
            print(f"  0x{addr:08X} (lui+ori F2000003) is inside func_{cf[1]} (entry 0x{cf[0]:08X})")
        else:
            print(f"  0x{addr:08X}: NO CONTAINING FUNCTION (orphan code region!)")
