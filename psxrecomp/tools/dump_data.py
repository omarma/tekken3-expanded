import struct, sys
with open('bios/SCPH1001.BIN','rb') as f: rom=f.read()
BASE=0xBFC00000
for a in sys.argv[1:]:
    s,n = a.split(':') if ':' in a else (a, '16')
    start=int(s,16); count=int(n)
    off = start - BASE
    print(f'--- 0x{start:08X} ---')
    for i in range(count):
        o = off + i*4
        if o+4>len(rom): break
        w = struct.unpack('<I', rom[o:o+4])[0]
        print(f'  0x{start+i*4:08X}: 0x{w:08X}')
