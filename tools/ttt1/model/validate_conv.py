"""Valide le modele converti (kazuya-ps1.3dm) contre la sonde en jeu du chemin
natif : chaque sommet de chaque piece, ecran mesure contre ecran simule avec
les matrices GTE relevees. Usage : validate_conv.py <sonde> [modele]"""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from simulate import *
from collections import Counter,defaultdict
path=sys.argv[1]; m=load(sys.argv[2] if len(sys.argv)>2 else 'workspace/native/kazuya-ps1.3dm')
recs=[r for r in records(path,extended=True) if r['kind']=='native' and r['m1']==records(path,extended=True)[0]['m1']]
base=recs[0]['m1']-24-8+24   # a0 = m1+16+56*ligne
# garder les appels sur le modele de l'invite (m1), regroupes par image
fr=[];cur=[]
for r in recs:
    sl=(r['a0']-r['m1']-16)//56
    if not (0<=sl<27) or (r['a0']-r['m1']-16)%56: continue
    if sl==1 and cur: fr.append(cur); cur=[]
    cur.append((sl,r))
if cur: fr.append(cur)
f=fr[len(fr)//2]
print('images',len(fr),'ordre',[s for s,_ in f])
geo=assemble(f,m); tot=ok=0; why=Counter(); bad=defaultdict(list)
for ri,rec in f:
    a=vlist(m,ri); w=row(m,ri)
    if not a or w[1]<=2: continue
    R,T,ofx,ofy,H=gte(rec['ctrl']); L=geo[ri]
    n1,n2=len(a['g1']),len(a['g2']); s0=n1+n2; grp={}; s=s0
    for gi,gl in enumerate(a['tails'][:5]):
        for fl in gl: grp[s]=(gi+1,fl>>8,fl&0xff); s+=1
    used=set(x for k,fl in enumerate(parse_b(block(m,w[1]))) for p in fl for x in prim_verts(k,p))
    for s in sorted(used):
        tot+=1; q=(s16(rec['scr'][s]),s16(rec['scr'][s]>>16)); P=L[s]
        cat='g1' if s<n1 else 'g2' if s<s0 else ('queue%d/fl%d'%grp[s][:2] if s in grp else 'propre')
        if P is None: why[cat+' vide']+=1; bad[ri].append((s,cat,'vide',q)); continue
        px=((ofx+int(H*P[0]*65536/P[2]))>>16,(ofy+int(H*P[1]*65536/P[2]))>>16)
        if abs(px[0]-q[0])<=2 and abs(px[1]-q[1])<=2: ok+=1
        else: why[cat]+=1; bad[ri].append((s,cat,px,q,grp.get(s)))
print(f'{ok}/{tot} exacts ; faux :',why.most_common())
for ri in sorted(bad): print(' ligne',ri,len(bad[ri]),bad[ri][:5])
