import json, sys, struct

target = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0xBFC0C720

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    if not d.get('ok'):
        continue
    base = int(d['addr'], 16)
    raw = bytes.fromhex(d['hex'])
    for i in range(0, len(raw) - 3, 4):
        val = struct.unpack_from('<I', raw, i)[0]
        if val == target:
            print(f'Found 0x{target:08X} at RAM 0x{base+i:05X}')
