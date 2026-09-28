import struct, sys
with open('bios/SCPH1001.BIN','rb') as f: rom=f.read()
BASE=0xBFC00000
for a in sys.argv[1:]:
    t=int(a,16)
    b=struct.pack('<I', t)
    pos=0; hits=[]
    while True:
        i=rom.find(b,pos)
        if i<0: break
        hits.append(i); pos=i+1
    print(f'0x{t:08X}: {len(hits)} literal occurrences')
    for h in hits[:10]:
        print(f'  ROM+0x{h:X} (addr=0x{BASE+h:08X})')
