import struct, sys
with open('bios/SCPH1001.BIN','rb') as f: rom=f.read()
BASE=0xBFC00000
# Print addresses that JAL/J to any target in argv
targets = [int(a,16) for a in sys.argv[1:]]
hits = {t: [] for t in targets}
for off in range(0, len(rom), 4):
    w = struct.unpack('<I', rom[off:off+4])[0]
    op=(w>>26)&0x3f
    if op not in (2,3): continue
    pc = BASE+off
    real = (pc & 0xF0000000) | ((w & 0x3ffffff) << 2)
    for t in targets:
        if (real & 0x1FFFFFFF) == (t & 0x1FFFFFFF):
            hits[t].append((pc, op, real))
for t in targets:
    print(f'--- {t:08X} ({len(hits[t])} callers) ---')
    for pc, op, real in hits[t]:
        n = 'jal' if op==3 else 'j'
        print(f'  PC=0x{pc:08X} {n} 0x{real:08X}')
