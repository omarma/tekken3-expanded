"""Pose un modele TTT1 avec les matrices TTT1 relevees sur Jun (renderer arcade) :
rotations de Jun, positions recalculees avec les longueurs d'os du modele."""
import sys,math; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import simulate as SM
from probe_read import *
from fmt import *
from pose_ttt1 import mul, rot_rest, part_row
import validate_ttt1 as V
def jun_frame(i=0):
    full=[f for f in V.frames if len(f)>=15]; return full[i]
def pose_from_jun(frame,model,jun=V.J):
    G={ri:gte(rec['ctrl']) for ri,rec in frame}
    SAME={2:1,3:1,5:4,6:4,23:22}          # pieces absentes chez Jun : meme os que leur voisine
    cache={}
    def xform(ri):
        if ri in cache: return cache[ri]
        w=row(model,ri); par=part_row(w[6]) if w[6]!=0xffffffff and w[6]>=0 else None
        if ri in G or ri in SAME:
            src=ri if ri in G else SAME[ri]
            R,T,ofx,ofy,H=G[src]
            off=w[3:6]
            if par and par in G and any(off):
                Rp,Tp,_,_,_=xform(par)
                T=[Tp[k]+sum(Rp[k][c]*off[c] for c in range(3))/4096 for k in range(3)]
            cache[ri]=(R,T,ofx,ofy,H); return cache[ri]
        # os absent chez Jun (accessoires) : parent + rotation de repos
        Rp,Tp,ofx,ofy,H=xform(par); off=w[3:6]; ang=[x&0xffff for x in w[7:10]]
        cache[ri]=(mul(Rp,rot_rest(ang)),[Tp[k]+sum(Rp[k][c]*off[c] for c in range(3))/4096 for k in range(3)],ofx,ofy,H)
        return cache[ri]
    return xform
if __name__=='__main__':
    fr=jun_frame(0)
    # controle : Jun posee ainsi doit retomber exactement sur la sonde
    xf=pose_from_jun(fr,V.J)
    order=[(r,None) for r,_ in fr]
    geo=SM.assemble(order,V.J,ttt1=True,xform=xf)
    ok=tot=0
    for ri,rec in fr:
        w=row(V.J,ri)
        if w[1]<=2: continue
        R,T,ofx,ofy,H=gte(rec['ctrl'])
        used=set(s for k,fl in enumerate(parse_b(block(V.J,w[1]))) for p in fl for s in prim_verts(k,p))
        for s in used:
            P=geo[ri][s]; q=(s16(rec['scr'][s]),s16(rec['scr'][s]>>16)); tot+=1
            px=((ofx+int(H*P[0]*65536/P[2]))>>16,(ofy+int(H*P[1]*65536/P[2]))>>16)
            ok+=abs(px[0]-q[0])<=2 and abs(px[1]-q[1])<=2
    print('controle Jun posee par pose_from_jun :',ok,'/',tot)
