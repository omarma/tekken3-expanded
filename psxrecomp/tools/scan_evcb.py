import json, sys, struct

base_addr = 0xE028
entry_size = 28

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    if not d.get('ok'):
        continue
    chunk_base = int(d['addr'], 16)
    raw = bytes.fromhex(d['hex'])
    for i in range(0, len(raw) - (entry_size - 1), entry_size):
        cls = struct.unpack_from('<I', raw, i)[0]
        status = struct.unpack_from('<I', raw, i+4)[0]
        spec = struct.unpack_from('<I', raw, i+8)[0]
        mode = struct.unpack_from('<I', raw, i+12)[0]
        func = struct.unpack_from('<I', raw, i+16)[0]
        if cls != 0:
            entry_idx = ((chunk_base + i) - base_addr) // entry_size
            addr_hex = chunk_base + i
            print(f'EvCB[{entry_idx:3d}] @ 0x{addr_hex:05X}: class=0x{cls:08X} status=0x{status:08X} spec=0x{spec:08X} mode=0x{mode:08X} func=0x{func:08X}')
