"""Rendu d'un modele converti au format PS1 : assemblage avec les regles PS1
(simulate.assemble, ttt1=False), pose TTT1 de Jun appliquee a chaque
emplacement PS1 (S2T), textures TTT1 posees comme la bande costume PS1."""
import sys,os,json,base64,io,struct; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from pose_jun import *
import convert as C
from tex import W,H,page_image
PS1,TTT1,TEX,OUT,NAME=sys.argv[1:6]
P=load(PS1); T=load(TTT1)
fr=jun_frame(0); xf=pose_from_jun(fr,T)
order=[s for s in range(1,C.NROWS) if row(P,s)[10] and row(P,s-1)[12]>2]
geo=SM.assemble([(s,None) for s in order],P,ttt1=False,xform=lambda s: xf(C.S2T[s]))
# VRAM virtuelle facon PS1 : pixels replies en x=384.., palettes en y=504+
v=[[0]*W for _ in range(H)]; t=open(TEX,'rb').read(); p=0
while p+8<=len(t):
    mg,fl=struct.unpack_from('<II',t,p)
    if mg!=16: break
    p+=8
    for pal in ((True,False) if fl&8 else (False,)):
        sz,x,y,w,h=struct.unpack_from('<I4H',t,p); px=struct.unpack_from(f'<{w*h}H',t,p+12)
        for r in range(h):
            if pal: X,Y=x,504+y+r
            else:
                if x>=128: break                       # tuile hors repli : non geree pour l'instant
                X,Y=384+x%64,y+r+(128 if x>=64 else 0)
            v[Y][X:X+w]=px[r*w:(r+1)*w]
        p+=sz
texid={}; tris=[]
for s in order:
    w=row(P,s)
    if w[1]<=2 or w[2]<=2: continue
    cp=parse_c_ps1(block(P,w[2])); j=0
    for k,fl in enumerate(parse_b(block(P,w[1]))):
        for rec in fl:
            _,mat,uv=cp[j]; j+=1
            key=(0x86 if mat&0x8000 else 0x06, 0x7e00+(mat&0x7fff)); texid.setdefault(key,len(texid))
            Pt=[geo[s][x] for x in prim_verts(k,rec)]
            for a,b,c in ([(0,1,2)] if k in (0,2) else [(0,1,2),(1,3,2)]):
                if None in (Pt[a],Pt[b],Pt[c]): continue
                tris.append([s,texid[key]]+Pt[a]+Pt[b]+Pt[c]+list(uv[a])+list(uv[b])+list(uv[c]))
texs=[]
for (pg,cl),i in sorted(texid.items(),key=lambda x:x[1]):
    bio=io.BytesIO(); page_image(v,pg,cl).save(bio,'PNG'); texs.append('data:image/png;base64,'+base64.b64encode(bio.getvalue()).decode())
open(OUT,'w').write('window.TEXTURED=window.TEXTURED||[];window.TEXTURED.push('+json.dumps(dict(name=NAME,tris=tris,textures=texs))+');')
zs=[x for t_ in tris for x in (t_[4],t_[7],t_[10])]
print(NAME,'triangles',len(tris),'profondeur',round(min(zs)),'..',round(max(zs)))
