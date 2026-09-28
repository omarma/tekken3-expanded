#!/usr/bin/env python3
"""Check emitted function sizes vs expected ROM span."""
import re, sys

with open('generated/SCPH1001_full.c') as f:
    lines = f.readlines()

funcs = []
for i, line in enumerate(lines, 1):
    m = re.match(r'^void func_1FC([0-9A-Fa-f]+)\(CPUState\* cpu\) \{', line)
    if m:
        addr = int(m.group(1), 16) + 0xBFC00000
        funcs.append((addr, i))

targets = [0xBFC34EC4, 0xBFC35FD0, 0xBFC36068, 0xBFC362D0, 0xBFC36740, 0xBFC36CF0]
for t in targets:
    for i, (addr, lineno) in enumerate(funcs):
        if addr == t:
            next_line = funcs[i + 1][1] if i + 1 < len(funcs) else len(lines)
            code_lines = next_line - lineno
            rom_addrs = set()
            for li in range(lineno - 1, min(next_line - 1, len(lines))):
                m2 = re.search(r'0x(BFC[0-9A-Fa-f]{5}):', lines[li])
                if m2:
                    rom_addrs.add(int(m2.group(1), 16))
            if rom_addrs:
                lo = min(rom_addrs)
                hi = max(rom_addrs)
                rom_bytes = hi - lo + 4
            else:
                lo = hi = rom_bytes = 0
            print(f'func_1FC{t - 0xBFC00000:05X}: {code_lines:4d} C lines, '
                  f'ROM 0x{lo:08X}-0x{hi:08X} ({rom_bytes:5d} bytes = {rom_bytes // 4:4d} insns)')
            break
