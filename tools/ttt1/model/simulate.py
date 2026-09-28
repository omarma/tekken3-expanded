"""Rejoue l'assemblage natif d'une image, valide contre la sonde."""
import sys,struct
sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from fmt import *; from probe_read import *
def tails_of(b,start,ttt1):
    layout=(16,16,16,16,16,8) if ttt1 else (9,9,9,9,9,2)
    p=start; out=[]
    for bits in layout:
        n=struct.unpack_from('<I',b,p)[0]; p+=4
        per={9:3,2:16,16:2,8:4}[bits]; words=(n+per-1)//per; vals=[]
        for wi in range(words):
            w=struct.unpack_from('<I',b,p+4*wi)[0]
            for k in range(per):
                if len(vals)<n: vals.append((w>>(bits*k))&((1<<bits)-1))
        p+=4*words; out.append(vals)
    return out
def variants(b,ttt1=False):
    """Un bloc de positions peut enchainer plusieurs listes completes (poses de main)."""
    out=[]; p=0
    while p+16<=len(b):
        a=parse_a(b[p:]); t=tails_of(b[p:],a['used'],ttt1)
        layout=(16,16,16,16,16,8) if ttt1 else (9,9,9,9,9,2)
        q=a['used']
        for bits,vals in zip(layout,t):
            per={9:3,2:16,16:2,8:4}[bits]; q+=4+4*((len(vals)+per-1)//per)
        a['tails']=t; out.append(a); p+=q
        if q<=0: break
    return out
def vlist(m,r,ttt1=False,variant=0):
    wp=row(m,r-1)
    if wp[12]<=2: return None
    b=block(m,wp[12])
    try: vs=variants(b,ttt1)
    except Exception:
        a=parse_a(b); a['tails']=[[]]*6; return a
    return vs[min(variant,len(vs)-1)]
def nvariants(m,r,ttt1=False):
    wp=row(m,r-1)
    if wp[12]<=2: return 0
    try: return len(variants(block(m,wp[12]),ttt1))
    except Exception: return 1
def frames(recs,m1):
    """Decoupe les appels du modele m1 en images (ligne 1 = debut)."""
    fr=[];cur=[]
    for r in recs:
        if not (m1<=r['a0']<m1+30000): continue
        ri=(r['a0']-m1-16)//56
        if ri==1 and cur: fr.append(cur); cur=[]
        cur.append((ri,r))
    if cur: fr.append(cur)
    return fr
def costume_of(frame,models):
    best=None
    for cid,m in models.items():
        hit=0
        for ri,rec in frame[:6]:
            a=vlist(m,ri)
            if not a: continue
            g=gte(rec['ctrl']); s=len(a['g1'])+len(a['g2'])
            for i,v in enumerate(a['verts']):
                p=project(g,v[:3]); q=(s16(rec['scr'][s+i]),s16(rec['scr'][s+i]>>16)) if s+i<128 else None
                hit+= bool(p and q and abs(p[0]-q[0])<=1 and abs(p[1]-q[1])<=1)
        if not best or hit>best[0]: best=(hit,cid)
    return best[1]
def camspace(g,v):
    R,T,_,_,_=g
    return [T[k]+(R[k][0]*v[0]+R[k][1]*v[1]+R[k][2]*v[2])/4096 for k in range(3)]
SEAMS=[]
WMODE='propre'    # TTT1 : poids/16 (octet haut du champ) sur le sommet propre ; PS1 : moitie
WMODE_G={}        # surcharge par groupe (0,1,2) si besoin
EXPORT_PRE=True   # TTT1 : groupe 1 depose la valeur brute (avant ponderation)
TTT1_IDX={'g1':'demi','g2':'direct','cache':'direct','case':'demi'}   # valide sur Jun (renderer arcade) : 100 %
TTT1_EXACT=True   # TTT1 : regle exacte du renderer arcade (parts ponderees)
G1_EXPORT=True    # TTT1 : le groupe 1 depose-t-il dans le cache ?
G4_EXPORT_PRE=False  # TTT1 : groupe 4 depose la valeur brute
G4_BLEND=True     # TTT1 : groupe 4 pondere (poids/16 sur le propre) ; valide sur Jun
LAST_CACHE={}
WRITERS={'cache':{},'tampon':{}}   # derniere piece ayant ecrit chaque entree
def assemble(frame,m,ttt1=False,xform=None,variants=None,cache_init=None):
    """Rejoue l'assemblage : renvoie {ligne: liste de points 3D par emplacement}."""
    cache=dict(cache_init or {}); scratch=[None]*128; out={}; cachew={}; scratchw=[16]*128
    for ri,rec in frame:
        a=vlist(m,ri,ttt1,(variants or {}).get(ri,0))
        nv=nvariants(m,ri,ttt1)
        if nv>1 and rec is not None and xform is None:
            g0=gte(rec['ctrl']); best=None
            for vi in range(nv):
                av=vlist(m,ri,ttt1,vi); s_=len(av['g1'])+len(av['g2']); hit=0
                for i,v in enumerate(av['verts']):
                    pp=project(g0,v[:3])
                    if pp and s_+i<128:
                        q=(s16(rec['scr'][s_+i]),s16(rec['scr'][s_+i]>>16)); hit+=abs(pp[0]-q[0])<=2 and abs(pp[1]-q[1])<=2
                if best is None or hit>best[0]: best=(hit,vi)
            a=vlist(m,ri,ttt1,best[1])
        if not a: out[ri]=list(scratch); continue
        g=gte(rec['ctrl']) if xform is None else xform(ri)
        cv=lambda b,kind: (b if (ttt1 and TTT1_IDX[kind]=='direct') else b//2)
        L=[scratch[cv(b,'g1')-1] if 0<=cv(b,'g1')-1<128 else None for b in a['g1']]
        L+=[cache.get(cv(b,'g2')) for b in a['g2']]
        s0=len(L)
        L+=[camspace(g,v[:3]) for v in a['verts']]
        s=s0; copies=[]; before=list(scratch); cache0=dict(cache); beforew=list(scratchw); cachew0=dict(cachew)
        avg=lambda A,B:[(A[k]+B[k])/2 for k in range(3)]
        if ttt1 and TTT1_EXACT:
            # Regle du renderer arcade (func_8010DC94, GPF 0x3D) : poids/16.
            # Le moteur somme des coordonnees ECRAN ; en 3D on ramene chaque
            # somme au total de ses poids (x 16/total) : meme point a l'ecran,
            # profondeur correcte (sinon pointes dans l'axe de la camera).
            sc=lambda A,w:[A[k]*w/16 for k in range(3)]
            def comb(part,pw,v,w):
                tot=pw+w; S=[part[k]+v[k]*w/16 for k in range(3)]
                return [S[k]*16/tot for k in range(3)] if tot else v
            for gi,grp in enumerate(a['tails'][:5]):
                for f in grp:
                    if s>=len(L): break
                    idx=cv(f&0xff,'cache'); t=cv(f&0xff,'case')-1
                    w=(f>>8)&0x1f          # 16 = plein (mesure sur la sonde Kazuya)
                    v=L[s]
                    if v is not None:
                        if gi==0:
                            if cache.get(idx) is not None: L[s]=comb(cache[idx],cachew.get(idx,16),v,w)
                            cache[idx]=L[s]; cachew[idx]=16; WRITERS['cache'][idx]=(ri,1)
                        elif gi==1:
                            if cache0.get(idx) is not None: L[s]=comb(cache0[idx],cachew0.get(idx,16),v,w)
                        elif gi==2:
                            if 0<=t<128 and before[t] is not None: L[s]=comb(before[t],beforew[t],v,w)
                        elif gi==3:
                            cache[idx]=sc(v,w); cachew[idx]=w; WRITERS['cache'][idx]=(ri,4)
                        elif gi==4:
                            copies.append((t,s,w))
                    s+=1
        else:
            def avg(A,B,fl=None,gi=None):
                mode=WMODE_G.get(gi,WMODE)
                if not ttt1 or mode=='moitie' or fl is None: return [(A[k]+B[k])/2 for k in range(3)]
                w=min(16,fl>>8)/16
                if mode=='propre': return [A[k]*w+B[k]*(1-w) for k in range(3)]
                return [A[k]*(1-w)+B[k]*w for k in range(3)]
            for gi,grp in enumerate(a['tails'][:5]):
                for f in grp:
                    if s>=len(L): break
                    idx=cv(f&0xff,'cache'); flag=f>>8; t=cv(f&0xff,'case')-1
                    if gi in (0,1):
                        raw=L[s]
                        if flag and cache0.get(idx) is not None and L[s] is not None:
                            SEAMS.append((ri,sum((L[s][k]-cache0[idx][k])**2 for k in range(3))**.5)); L[s]=avg(L[s],cache0[idx],f,gi)
                        if gi==0 and (G1_EXPORT or not ttt1): cache[idx]=raw if (ttt1 and EXPORT_PRE) else L[s]
                    elif gi==2:
                        if flag and 0<=t<128 and before[t] is not None and L[s] is not None:
                            SEAMS.append((ri,sum((L[s][k]-before[t][k])**2 for k in range(3))**.5)); L[s]=avg(L[s],before[t],f,gi)
                    elif gi==3:
                        # Mesure (sonde Jin) : depot de la moitie (drapeau) ou du sommet entier ;
                        # l'emplacement ne reprend JAMAIS la valeur du cache. En 3D : depot du sommet.
                        raw4=L[s]
                        if ttt1 and flag and idx in cache and G4_BLEND and L[s] is not None:
                            L[s]=avg(L[s],cache[idx],f)
                        cache[idx]=raw4 if (ttt1 and G4_EXPORT_PRE) else L[s]
                    elif gi==4:
                        copies.append((t,s,flag))
                    s+=1
        prev_high=list(scratch)
        scratch[:len(L)]=L; scratchw[:len(L)]=[16]*len(L)
        for k in range(len(L)): WRITERS['tampon'][k]=(ri,'liste')
        for t,sl,flag in copies:
            if 0<=t<128 and L[sl] is not None:
                scratch[t]=[L[sl][k]*flag/16 for k in range(3)] if (ttt1 and TTT1_EXACT) else L[sl]; WRITERS['tampon'][t]=(ri,5)
                if ttt1 and TTT1_EXACT: scratchw[t]=flag
        out[ri]=list(scratch)
    LAST_CACHE.clear(); LAST_CACHE.update(cache)
    return out
