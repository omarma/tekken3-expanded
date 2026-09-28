"""Add missing A0/B0/C0 trampolines to dispatch_miss_seeds.json.
The list of missing trampolines is what check_trampoline_seeds.py reports."""
import json, sys, re

MISSING = """
0xBFC0D8E0 0xBFC0D8F0 0xBFC0D900 0xBFC0D910 0xBFC0D920 0xBFC0D930 0xBFC0D940
0xBFC16550 0xBFC16560 0xBFC16570 0xBFC16580 0xBFC16590 0xBFC165A0 0xBFC165B0
0xBFC165C0 0xBFC165D0 0xBFC165E0 0xBFC165F0 0xBFC16600 0xBFC16610 0xBFC16620
0xBFC16630 0xBFC16640 0xBFC16650 0xBFC16660 0xBFC16670
0xBFC166B0 0xBFC166C0 0xBFC166D0 0xBFC166E0 0xBFC166F0 0xBFC16700 0xBFC16710
0xBFC16720 0xBFC16730 0xBFC16740 0xBFC16750
0xBFC428D0 0xBFC428E0 0xBFC428F0
0xBFC42A00 0xBFC42A20 0xBFC42A30 0xBFC42A40 0xBFC42A50 0xBFC42A60 0xBFC42A70
0xBFC42A80 0xBFC42AA0 0xBFC42AB0 0xBFC42AC0 0xBFC42AD0 0xBFC42AE0 0xBFC42AF0
0xBFC42B00 0xBFC42B10 0xBFC42B20 0xBFC42B30 0xBFC42B40 0xBFC42B50 0xBFC42B60
0xBFC42B70 0xBFC42B80 0xBFC42B90 0xBFC42BB0 0xBFC42BC0 0xBFC42BD0
""".split()

with open('recompiler/seeds/dispatch_miss_seeds.json') as f:
    seeds = json.load(f)

existing_addrs = {int(e['address'], 16) for e in seeds['seeds']}
added = 0
for addr_str in MISSING:
    addr = int(addr_str, 16)
    if addr in existing_addrs:
        continue
    # Region label
    if 0xBFC0D000 <= addr < 0xBFC0E000:
        rationale = (f"A0/B0/C0 trampoline (kernel install table region {addr_str}). "
                     "4-instruction MIPS trampoline `addiu $t2,0xA0/B0/C0; jr $t2; addiu $t1,idx`. "
                     "Recompiler missed via static discovery — required for indirect-jump dispatch.")
    elif 0xBFC16000 <= addr < 0xBFC17000:
        rationale = (f"A0/B0/C0 trampoline (kernel image post-copy lookup {addr_str}). "
                     "Indirect-call target, not statically discoverable.")
    elif 0xBFC42000 <= addr < 0xBFC43000:
        rationale = (f"Shell A0/B0/C0 trampoline {addr_str}. "
                     "Called by SHELL via JAL to pre-known addresses; without seed the dispatch falls "
                     "into dirty_ram_dispatch which may interpret incorrectly. "
                     "BFC42BB0=B0:0x15(_card_load), BFC42B00=B0:0x50(_card_write), etc.")
    else:
        rationale = f"A0/B0/C0 trampoline {addr_str}, indirect call target."

    seeds['seeds'].append({'address': addr_str, 'rationale': rationale})
    added += 1

with open('recompiler/seeds/dispatch_miss_seeds.json', 'w') as f:
    json.dump(seeds, f, indent=2)

print(f"added={added} total_seeds={len(seeds['seeds'])}")
