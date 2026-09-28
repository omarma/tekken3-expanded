import struct
with open('bios/SCPH1001.BIN','rb') as f: rom=f.read()
BASE=0xBFC00000
ranges = [(0xBFC61CFC, 0xBFC61D20), (0x80061D00, 0x80061D20)]
for lo,hi in ranges:
    print(f'--- literals in [0x{lo:X}..0x{hi:X}] ---')
    for off in range(0, len(rom)-3, 4):
        w = struct.unpack('<I', rom[off:off+4])[0]
        if lo <= w < hi:
            print(f'  ROM+0x{off:X} (0x{BASE+off:08X}) = 0x{w:08X}')
# Also scan for half-alignment
print('--- unaligned too ---')
for off in range(0, len(rom)-3):
    w = struct.unpack('<I', rom[off:off+4])[0]
    if 0xBFC61D00 <= w < 0xBFC61D20:
        print(f'  ROM+0x{off:X} = 0x{w:08X}')
