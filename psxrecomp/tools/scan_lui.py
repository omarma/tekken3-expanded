import struct, sys
with open('bios/SCPH1001.BIN','rb') as f: rom=f.read()
BASE=0xBFC00000
hi = int(sys.argv[1],16) if len(sys.argv)>1 else 0xBFC6
for off in range(0, len(rom)-3, 4):
    w = struct.unpack('<I', rom[off:off+4])[0]
    op=(w>>26)&0x3f
    if op==15 and (w&0xffff)==hi:
        rt=(w>>16)&0x1f
        print(f'0x{BASE+off:08X}: lui ${rt},0x{hi:04X}')
