"""Compare A0/B0/C0 trampoline addresses (from Ghidra search) against the
recomp dispatch_table. Print which trampolines are MISSING from dispatch."""
import re

trampolines = """bfc0d880 bfc0d890 bfc0d8a0 bfc0d8b0
bfc0d970 bfc0d980 bfc0d990 bfc0d9a0 bfc0d9b0 bfc0d9c0 bfc0d9d0
bfc0d9e0 bfc0d9f0 bfc0da00 bfc0da10 bfc0da20 bfc0da30 bfc0da40
bfc0da50 bfc0da60 bfc0da70 bfc0da80 bfc0da90 bfc0daa0 bfc0dab0
bfc0dac0 bfc0dad0 bfc0dae0
bfc16550 bfc16560 bfc166b0 bfc166c0 bfc166d0 bfc166e0 bfc166f0
bfc16700 bfc16710 bfc16720 bfc16730 bfc16740 bfc16750
bfc42960 bfc42970 bfc42980 bfc429d0 bfc429e0
bfc42a00 bfc42a30 bfc42a40 bfc42a80 bfc42aa0 bfc42ab0 bfc42ac0
bfc42ad0 bfc42ae0 bfc42af0
bfc42b00 bfc42b20 bfc42b30 bfc42b40 bfc42b50 bfc42b90 bfc42ba0
bfc42bb0 bfc42bc0 bfc42bd0 bfc42bf0
bfc0d8d0 bfc0d8e0 bfc0d8f0 bfc0d900 bfc0d910 bfc0d920 bfc0d930
bfc0d940 bfc0d950
bfc0dbf0 bfc0dc00 bfc0dc10 bfc0dc20 bfc0dc30 bfc0dc40 bfc0dc50
bfc16570 bfc16580 bfc16590 bfc165a0 bfc165b0 bfc165c0 bfc165d0
bfc165e0 bfc165f0 bfc16600 bfc16610 bfc16620 bfc16630 bfc16640
bfc16650 bfc16660 bfc16670
bfc428d0 bfc428e0 bfc428f0
bfc42900 bfc42910 bfc42920 bfc42930 bfc42940 bfc42950 bfc42990
bfc429a0 bfc429b0
bfc42a20 bfc42a50 bfc42a60 bfc42a70
bfc42b10 bfc42b60 bfc42b70 bfc42b80 bfc42be0
""".split()

with open('generated/SCPH1001_dispatch.c', 'r') as f:
    dispatch = f.read()

in_table = set()
for m in re.finditer(r'\{ 0x([0-9A-Fa-f]{8})u', dispatch):
    in_table.add(int(m.group(1), 16))

print(f"dispatch_table entries: {len(in_table)}")
print(f"trampolines found: {len(set(trampolines))}")
print()

missing = []
for t in sorted(set(trampolines)):
    addr = int(t, 16)
    phys = addr & 0x1FFFFFFF
    if phys not in in_table and addr not in in_table:
        missing.append(t)

print(f"MISSING from dispatch_table ({len(missing)}):")
for m in missing:
    print(f"  0xBFC{m[3:].upper()}")
