import sys; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__))); from probe_read import *; import simulate as SM
from fmt import *
from collections import Counter
ROWS27=[0,1,3,4,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,29]
recs=records('workspace/native/probe/probe-jun.bin',extended=True)
g=[r for r in recs if r['kind']=='guest']; m1=g[0]['m1']
J=load('workspace/native/jun-ttt1.3dm')
frames=[];cur=[]
for r in g:
    slot=(r['a0']-m1-16)//56; row_=ROWS27[slot]
    if slot==1 and cur: frames.append(cur); cur=[]
    cur.append((row_,r))
if cur: frames.append(cur)
def validate(fr,verbose=False):
    geo=SM.assemble(fr,J,ttt1=True); ok=tot=0; why=Counter(); ex=[]
    for ri,rec in fr:
        a=SM.vlist(J,ri,True); w=row(J,ri)
        if not a or w[1]<=2: continue
        G=gte(rec['ctrl']); R,T,ofx,ofy,H=G; L=geo[ri]
        n1,n2=len(a['g1']),len(a['g2']); s0=n1+n2
        grp={}; s=s0
        for gi,gl in enumerate(a['tails'][:5]):
            for fl in gl: grp[s]=(gi+1,fl); s+=1
        used=set(s for k,fl in enumerate(parse_b(block(J,w[1]))) for p in fl for s in prim_verts(k,p))
        for s in used:
            tot+=1; P=L[s]; q=(s16(rec['scr'][s]),s16(rec['scr'][s]>>16))
            cat='g1' if s<n1 else 'g2' if s<s0 else ('queue%d'%grp[s][0] if s in grp else 'propre')
            if P is None: why[cat+' vide']+=1; continue
            px=((ofx+int(H*P[0]*65536/P[2]))>>16,(ofy+int(H*P[1]*65536/P[2]))>>16)
            if abs(px[0]-q[0])<=2 and abs(px[1]-q[1])<=2: ok+=1
            else:
                why[cat]+=1
                if verbose and len(ex)<15: ex.append((ri,s,cat,hex(grp[s][1]) if s in grp else '',px,q))
    return ok,tot,why,ex
if __name__=='__main__':
    full=[f for f in frames if len(f)>=15]
    print('images',len(frames),'completes',len(full),'lignes',[r for r,_ in full[0]])
    ok,tot,why,ex=validate(full[0],True)
    print(f'{ok}/{tot}',why.most_common()); [print(e) for e in ex]
