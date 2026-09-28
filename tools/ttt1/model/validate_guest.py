"""Valide les regles TTT1 contre la sonde du renderer arcade, sur le modele tel
que le chargeur de Jun le presente (27 emplacements, lignes 2/5/28 retirees)."""
import sys,struct; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from probe_read import *; import simulate as SM
from fmt import *
from collections import Counter
ROWS27=[0,1,3,4,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,29]
def virtual(m):
    b=bytearray(m); hdr=bytearray(m[:24]); struct.pack_into('<I',hdr,0,27)
    rows=b''.join(m[24+r*56:24+r*56+56] for r in ROWS27)
    return bytes(hdr)+rows+bytes(m[24+27*56:])     # blocs inchanges (decalages absolus)
def frames_of(path,model):
    recs=records(path,extended=True); g=[r for r in recs if r['kind']=='guest']; m1=g[0]['m1']
    fr=[];cur=[]
    for r in g:
        slot=(r['a0']-m1-16)//56
        if slot==1 and cur: fr.append(cur); cur=[]
        cur.append((slot,r))
    if cur: fr.append(cur)
    return fr
def validate(fr,V):
    geo=SM.assemble(fr,V,ttt1=True); ok=tot=0; why=Counter()
    for si,rec in fr:
        a=SM.vlist(V,si,True); w=row(V,si)
        if not a or w[1]<=2: continue
        R,T,ofx,ofy,H=gte(rec['ctrl']); L=geo[si]
        n1,n2=len(a['g1']),len(a['g2']); s0=n1+n2
        grp={}; s=s0
        for gi,gl in enumerate(a['tails'][:5]):
            for fl in gl: grp[s]=gi+1; s+=1
        used=set(s for k,fl in enumerate(parse_b(block(V,w[1]))) for p in fl for s in prim_verts(k,p))
        for s in used:
            tot+=1; P=L[s]; q=(s16(rec['scr'][s]),s16(rec['scr'][s]>>16))
            cat='g1' if s<n1 else 'g2' if s<s0 else ('queue%d'%grp[s] if s in grp else 'propre')
            if P is None or abs(P[2])<1e-9: why[cat+' vide']+=1; continue
            px=((ofx+int(H*P[0]*65536/P[2]))>>16,(ofy+int(H*P[1]*65536/P[2]))>>16)
            if abs(px[0]-q[0])<=2 and abs(px[1]-q[1])<=2: ok+=1
            else: why[(ROWS27[si],cat)]+=1
    return ok,tot,why
if __name__=='__main__':
    K=load('workspace/native/kazuya-ttt1.3dm'); V=virtual(K)
    frs=[f for f in frames_of('workspace/native/probe/probe-kazuya.bin',K) if len(f)>=15]
    print('images',len(frs),'emplacements',[s for s,_ in frs[0]])
    for exact in (False,True):
        SM.TTT1_EXACT=exact; T=[0,0]; W=Counter()
        for fr in frs[:4]:
            ok,tot,why=validate(fr,V); T[0]+=ok; T[1]+=tot; W.update(why)
        print('regle exacte' if exact else 'regle approchee',T,W.most_common(8))
