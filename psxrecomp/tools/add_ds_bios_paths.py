"""Ensure DuckStation settings.ini has BIOS paths wired up for BIOS shell boot."""
import sys
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    s = f.read()
inject = (
    "[BIOS]\n"
    "PathNTSC-U = SCPH1001.BIN\n"
    "PathNTSC-J = SCPH1001.BIN\n"
    "PathPAL = SCPH1001.BIN\n"
    "FastForwardBoot"
)
s = s.replace("[BIOS]\nFastForwardBoot", inject)
with open(p, 'w', encoding='utf-8') as f:
    f.write(s)
print('OK')
