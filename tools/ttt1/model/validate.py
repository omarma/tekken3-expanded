import sys; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__))); from simulate import *
from collections import Counter
recs=records(); m1=recs[0]['m1']; fr=frames(recs,m1)
models={143:load('workspace/native/rec143.bin'),147:load('workspace/native/rec147.bin')}
for cid in (143,147):
  f=[f for f in fr if costume_of(f,models)==cid][0]; m=models[cid]
  geo=assemble(f,m); why=Counter(); ok=tot=0
  for ri,rec in f:
    a=vlist(m,ri); w=row(m,ri)
    if not a or w[1]<=2: continue
    g=gte(rec['ctrl']); R,T,ofx,ofy,H=g; L=geo[ri]
    n1,n2=len(a['g1']),len(a['g2']); s0=n1+n2
    grp={}; s=s0
    for gi,gl in enumerate(a['tails'][:5]):
        for fl in gl: grp[s]=(gi+1,fl>>8); s+=1
    used=set(s for k,fl in enumerate(parse_b(block(m,w[1]))) for p in fl for s in prim_verts(k,p))
    for s in used:
        tot+=1
        q=(s16(rec['scr'][s]),s16(rec['scr'][s]>>16)); P=L[s]
        cat='g1' if s<n1 else 'g2' if s<s0 else ('queue%d/fl%d'%grp[s] if s in grp else 'propre')
        if P is None: why[cat+' vide']+=1; continue
        px=((ofx+int(H*P[0]*65536/P[2]))>>16,(ofy+int(H*P[1]*65536/P[2]))>>16)
        if abs(px[0]-q[0])<=2 and abs(px[1]-q[1])<=2: ok+=1
        else: why[cat]+=1
  print(f'BNS {cid}: {ok}/{tot} exacts ; faux :',why.most_common())
