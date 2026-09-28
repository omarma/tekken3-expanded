import json, sys, struct

d = json.loads(sys.stdin.read())
raw = bytes.fromhex(d['hex'])
base = int(d['addr'], 16)

for i in range(0, min(len(raw), 512), 4):
    word = struct.unpack_from('<I', raw, i)[0]
    if word != 0:
        print(f'  0x{base+i:05X} (+{i:3d}): 0x{word:08X}')
