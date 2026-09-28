"""Jin PS1 costume 2 assemble et texture -> workspace/native/viewer/jin_ps1.js"""
import sys,struct,json,base64,io
sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from simulate import *; from packets import read_packets; from tex import vram_from_dump,page_image
CID=int(sys.argv[1]) if len(sys.argv)>1 else 147
PROBE=sys.argv[2] if len(sys.argv)>2 else 'workspace/native/probe/probe-2costumes.bin'
RAMF=sys.argv[3] if len(sys.argv)>3 else 'workspace/native/capture/00/ram.bin'
VRAMF=sys.argv[4] if len(sys.argv)>4 else 'workspace/native/capture/00/vram.bin'
OUTF=sys.argv[5] if len(sys.argv)>5 else 'workspace/native/viewer/jin_ps1.js'
recs=records(PROBE); m1=recs[0]['m1']; fr=frames(recs,m1)
models={143:load('workspace/native/rec143.bin'),147:load('workspace/native/rec147.bin')}
m=models[CID]
frame=[f for f in fr if len(f)==18 and f[0][0]==1 and costume_of(f,models)==CID][0]
geo=assemble(frame,m)
# paquets de la capture 00 (meme costume) pour UV / palette / page
ram=open(RAMF,'rb').read()
W=lambda a: struct.unpack_from('<I',ram,a&0x1fffff)[0]
actor=0x800a9228; base=0x801e9588; pk_of={}
for i in range(1,18):
    pt=actor+0x4f0+i*40
    for rowp,buf in ((W(pt+8),24),(W(pt+12),32)):
        if not rowp: continue
        r=((rowp&0x1fffff)-(base&0x1fffff)-16)//56
        fams=parse_b(block(m,row(m,r)[1]))
        pk_of[r]=read_packets(ram,W(pt+buf),[len(f) for f in fams])
vram=vram_from_dump(open(VRAMF,'rb').read())
texid={}; tris=[]
for ri,L in geo.items():
    w=row(m,ri)
    if w[1]<=2 or ri not in pk_of: continue
    j=0
    for k,fl in enumerate(parse_b(block(m,w[1]))):
        for rec in fl:
            pkt=pk_of[ri][j]; j+=1
            sl=prim_verts(k,rec); uv=pkt[2]; key=(pkt[4],pkt[3])
            if key not in texid: texid[key]=len(texid)
            P=[L[s] if s<len(L) else None for s in sl]
            order=[(0,1,2)] if k in (0,2) else [(0,1,2),(1,3,2)]
            for a,b,c in order:
                if None in (P[a],P[b],P[c]): continue
                tris.append(dict(r=ri,t=texid[key],p=[P[a],P[b],P[c]],uv=[uv[a],uv[b],uv[c]]))
texs=[]
for (tp,cl),i in sorted(texid.items(),key=lambda x:x[1]):
    im=page_image(vram,tp,cl); bio=io.BytesIO(); im.save(bio,'PNG')
    texs.append('data:image/png;base64,'+base64.b64encode(bio.getvalue()).decode())
out=dict(name=f'Jin — T3 PS1, costume {1 if CID==143 else 2} (assemble natif)',tris=[[t['r'],t['t']]+[c for p in t['p'] for c in p]+[c for u in t['uv'] for c in u] for t in tris],textures=texs)
open(OUTF,'w').write('window.TEXTURED=window.TEXTURED||[];window.TEXTURED.push('+json.dumps(out)+');')
print('triangles',len(tris),'textures',len(texs))
