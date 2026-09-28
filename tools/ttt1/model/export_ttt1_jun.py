"""Modele TTT1 pose avec la pose TTT1 de Jun (sonde du renderer arcade), texture."""
import sys,json,base64,io,math; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from pose_jun import *
from tex import vram_from_tims,page_image,PAL_Y
MODEL,TEX,OUT,NAME=sys.argv[1:5]; FI=int(sys.argv[5]) if len(sys.argv)>5 else 0
fr=jun_frame(FI)
# poses de main utilisees par Jun dans cette image (verite de la sonde)
HV={}
for ri,rec in fr:
    nv=SM.nvariants(V.J,ri,True)
    if nv>1:
        g0=gte(rec['ctrl']); best=None
        for vi in range(nv):
            a=SM.vlist(V.J,ri,True,vi); s_=len(a['g1'])+len(a['g2']); hit=0
            for i,v in enumerate(a['verts']):
                pp=project(g0,v[:3])
                if pp and s_+i<128:
                    q=(s16(rec['scr'][s_+i]),s16(rec['scr'][s_+i]>>16)); hit+=abs(pp[0]-q[0])<=2 and abs(pp[1]-q[1])<=2
            if best is None or hit>best[0]: best=(hit,vi)
        HV[ri]=best[1]
T1=load(MODEL); vram=vram_from_tims(open(TEX,'rb').read())
xf=pose_from_jun(fr,T1)
order=[(r,None) for r in range(1,nrows(T1)) if row(T1,r)[10] and row(T1,r-1)[12]>2]
HVm={r:min(v,SM.nvariants(T1,r,True)-1) for r,v in HV.items()}
# Une seule passe, cache vide : c'est ce que la sonde valide (une double passe
# recompte les soudures deja completees et produit des pointes).
geo=SM.assemble(order,T1,ttt1=True,xform=xf,variants=HVm)
texid={}; tris=[]
for r,_ in order:
    w=row(T1,r)
    if w[1]<=2 or w[2]<=2: continue
    cp=parse_c_ttt1(block(T1,w[2])); j=0
    for k,fl in enumerate(parse_b(block(T1,w[1]))):
        for rec in fl:
            _,mat,uv=cp[j]; j+=1; key=(mat>>16,mat&0xffff); texid.setdefault(key,len(texid))
            P=[geo[r][s] for s in prim_verts(k,rec)]
            for a,b,c in ([(0,1,2)] if k in (0,2) else [(0,1,2),(1,3,2)]):
                if None in (P[a],P[b],P[c]): continue
                tris.append([r,texid[key]]+P[a]+P[b]+P[c]+list(uv[a])+list(uv[b])+list(uv[c]))
texs=[]
for (pg,cl),i in sorted(texid.items(),key=lambda x:x[1]):
    bio=io.BytesIO(); page_image(vram,pg,cl,PAL_Y).save(bio,'PNG'); texs.append('data:image/png;base64,'+base64.b64encode(bio.getvalue()).decode())
open(OUT,'w').write('window.TEXTURED=window.TEXTURED||[];window.TEXTURED.push('+json.dumps(dict(name=NAME,tris=tris,textures=texs))+');')
print(NAME,'triangles',len(tris),'poses de main',HV)
