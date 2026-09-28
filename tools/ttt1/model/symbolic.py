"""Assemblage TTT1 symbolique : chaque emplacement porte ses sommets sources
{(ligne, indice propre): poids} au lieu d'une position. Memes regles que
simulate.assemble (TTT1_EXACT), normalisation par le total des poids comprise."""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import simulate as SM
from fmt import *
def scale(A,k): return {s:c*k for s,c in A.items()}
def add(A,B):
    C=dict(A)
    for s,c in B.items(): C[s]=C.get(s,0)+c
    return C
def comb(part,pw,v,w):
    tot=pw+w; S=add(part,scale(v,w/16))
    return scale(S,16/tot) if tot else v
def assemble_symbolic(m,order,variants=None):
    cache={}; cachew={}; scratch=[None]*128; scratchw=[16]*128; out={}; lists={}
    for ri in order:
        a=SM.vlist(m,ri,True,(variants or {}).get(ri,0))
        cv=lambda b,kind:(b if SM.TTT1_IDX[kind]=='direct' else b//2)
        L=[scratch[cv(b,'g1')-1] if 0<=cv(b,'g1')-1<128 else None for b in a['g1']]
        L+=[cache.get(cv(b,'g2')) for b in a['g2']]
        s0=len(L)
        L+=[{(ri,i):1.0} for i in range(len(a['verts']))]
        before=list(scratch); beforew=list(scratchw); cache0=dict(cache); cachew0=dict(cachew); copies=[]; s=s0
        for gi,grp in enumerate(a['tails'][:5]):
            for f in grp:
                if s>=len(L): break
                idx=cv(f&0xff,'cache'); t=cv(f&0xff,'case')-1; w=(f>>8)&0x1f; v=L[s]
                if v is not None:
                    if gi==0:
                        if cache.get(idx) is not None: L[s]=comb(cache[idx],cachew.get(idx,16),v,w)
                        cache[idx]=L[s]; cachew[idx]=16
                    elif gi==1:
                        if cache0.get(idx) is not None: L[s]=comb(cache0[idx],cachew0.get(idx,16),v,w)
                    elif gi==2:
                        if 0<=t<128 and before[t] is not None: L[s]=comb(before[t],beforew[t],v,w)
                    elif gi==3: cache[idx]=scale(v,w/16); cachew[idx]=w
                    elif gi==4: copies.append((t,s,w))
                s+=1
        scratch[:len(L)]=L; scratchw[:len(L)]=[16]*len(L)
        for t,sl,w in copies:
            if 0<=t<128 and L[sl] is not None: scratch[t]=scale(L[sl],w/16); scratchw[t]=w
        out[ri]=L; lists[ri]=a
    return out,lists
if __name__=='__main__':
    from collections import Counter
    K=load('workspace/native/kazuya-ttt1.3dm')
    order=[r for r in range(1,nrows(K)) if row(K,r)[10] and row(K,r-1)[12]>2]
    geo,lists=assemble_symbolic(K,order)
    st=Counter(); cross=Counter()
    for r in order:
        w=row(K,r)
        if w[1]<=2: continue
        for k,fl in enumerate(parse_b(block(K,w[1]))):
            for p in fl:
                for s in prim_verts(k,p):
                    c=geo[r][s]
                    if c is None: st['vide']+=1; continue
                    src=sorted(c.items(),key=lambda x:-x[1])
                    rows_=set(x[0][0] for x in src)
                    if len(src)==1: st['1 source' + (' (propre)' if src[0][0][0]==r else ' (autre piece)')]+=1
                    else:
                        dom=src[0][1]
                        st['2+ sources, dominante %.2f'%round(dom*4/4,2) if False else ('melange dominant>=0.75' if dom>=0.75 else 'melange equilibre')]+=1
                    for (rr,_),_ in src:
                        if rr!=r: cross[(r,rr)]+=1
    print(st.most_common())
    print('liens entre pieces (piece qui dessine, piece source):',sorted(cross.items())[:40])
