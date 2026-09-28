import struct,sys
sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__))); from fmt import *
REC=4*(8+32+32+256*3)
REC2=REC+4*256*4          # sonde etendue : + zone 8009D000..8009E000
def records(path='workspace/native/probe/probe-2costumes.bin',extended=False):
    b=open(path,'rb').read(); out=[]; R=REC2 if extended else REC
    for i in range(len(b)//R):
        o=i*R; h=struct.unpack_from('<8I',b,o); o+=32
        ctrl=struct.unpack_from('<32I',b,o); o+=128
        data=struct.unpack_from('<32I',b,o); o+=128
        scr=struct.unpack_from('<256I',b,o); o+=1024
        p1=struct.unpack_from('<256I',b,o); o+=1024
        p2=struct.unpack_from('<256I',b,o); o+=1024
        arc=struct.unpack_from('<1024I',b,o) if extended else None
        out.append(dict(kind='guest' if h[0]==0x474F5250 else 'native',seen=h[1],m1=h[2],m2=h[3],a0=h[4],ctrl=ctrl,data=data,scr=scr,p1=p1,p2=p2,arc=arc))
    return out
def s16(x): x&=0xffff; return x-65536 if x>32767 else x
def gte(ctrl):
    c=ctrl; R=[[s16(c[0]),s16(c[0]>>16),s16(c[1])],[s16(c[1]>>16),s16(c[2]),s16(c[2]>>16)],[s16(c[3]),s16(c[3]>>16),s16(c[4])]]
    T=[struct.unpack('<i',struct.pack('<I',c[k]))[0] for k in (5,6,7)]
    ofx=struct.unpack('<i',struct.pack('<I',c[24]))[0]; ofy=struct.unpack('<i',struct.pack('<I',c[25]))[0]; H=c[26]&0xffff
    return R,T,ofx,ofy,H
def project(g,v):
    R,T,ofx,ofy,H=g
    x,y,z=[T[k]+ (R[k][0]*v[0]+R[k][1]*v[1]+R[k][2]*v[2])//4096 for k in range(3)]
    if z<=0: return None
    return ((ofx + H*x*65536//z)>>16, (ofy + H*y*65536//z)>>16)
