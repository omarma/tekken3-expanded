import struct
SIZE=[32,40,40,52]
# offsets (octets) des mots xy / uv dans chaque paquet GPU, par famille
XY=[[8,16,24],[8,16,24,32],[8,20,32],[8,20,32,44]]
UV=[[12,20,28],[12,20,28,36],[12,24,36],[12,24,36,48]]
def read_packets(ram,addr,counts):
    """Paquets d'une partie : liste (famille, [(x,y)], [(u,v)], clut, tpage, cmd)."""
    o=addr&0x1fffff; out=[]
    for k,n in enumerate(counts):
        for i in range(n):
            w=lambda off: struct.unpack_from('<I',ram,o+off)[0]
            xy=[]; uv=[]
            for a in XY[k]:
                v=w(a); x=v&0xffff; y=v>>16
                xy.append((x-65536 if x>32767 else x, y-65536 if y>32767 else y))
            for a in UV[k]:
                v=w(a); uv.append((v&255,(v>>8)&255))
            clut=w(UV[k][0])>>16; tpage=w(UV[k][1])>>16
            out.append((k,xy,uv,clut,tpage,w(4)>>24)); o+=SIZE[k]
    return out
