"""Pose un modele TTT1 avec les rotations d'os de Jin PS1 (sonde), positions
recalculees depuis les longueurs d'os du modele TTT1."""
import sys; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from simulate import *
# ligne TTT1 -> (ligne PS1 dont on prend la rotation, correction d'axes (perm, signes))
ID=((0,1,2),(1,1,1))
MAP={1:(1,ID),2:(1,ID),3:(1,ID),4:(3,ID),5:(3,ID),6:(3,ID),
     7:(5,ID),8:(6,ID),9:(7,((0,1,2),(-1,-1,1))),
     10:(8,ID),11:(9,ID),12:(10,((0,1,2),(-1,-1,1))),
     13:(11,((0,1,2),(1,-1,-1))),14:(12,ID),15:(13,ID),16:(14,ID),
     17:(15,((0,1,2),(1,-1,-1))),18:(16,ID),19:(17,ID),20:(18,ID),
     21:(19,ID),22:(19,ID),23:(19,ID)}
# Correction apprise sur Jin (tete TTT1 recalee sur la tete PS1, meme forme,
# rotation negligeable) : decalage dans le repere du torse PS1.
HEAD_CORR=(-6.2,21.2,-2.0)
PS1_PARENT={1:0,3:0,5:3,6:5,7:6,8:3,9:8,10:9,11:1,12:11,13:12,14:13,15:1,16:15,17:16,18:17,19:1}
def fixmat(fx):
    p,s=fx; F=[[0]*3 for _ in range(3)]
    for i in range(3): F[i][p[i]]=s[i]
    return F   # v_ps = F v_ttt1
def mul(A,B): return [[sum(A[i][k]*B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def pose(frame_ps1, T1model, extra_parent=None):
    """Renvoie xform(ri) pour assemble(), et l'ordre de dessin TTT1."""
    ps={ri:gte(rec['ctrl']) for ri,rec in frame_ps1}
    # rotations PS1 ; positions recalculees
    Tpos={}
    def tpos(psrow):
        if psrow in Tpos: return Tpos[psrow]
        R,T,_,_,_=ps[psrow]; Tpos[psrow]=T; return T
    cache={}
    def xform(ri):
        if ri in cache: return cache[ri]
        psrow,fx=MAP.get(ri,(None,None)) if ri in MAP else extra_parent(ri)
        R,T,ofx,ofy,H=ps[psrow]
        par=PS1_PARENT.get(psrow)
        off=row(T1model,ri)[3:6]
        if par in ps and any(off):
            Rp,Tp,_,_,_=ps[par]
            Tn=[Tp[k]+sum(Rp[k][c]*off[c] for c in range(3))/4096 for k in range(3)]
        else: Tn=T
        if ri in (21,22,23) and 1 in ps:
            R1=ps[1][0]; Tn=[Tn[k]+sum(R1[k][c]*HEAD_CORR[c] for c in range(3))/4096 for k in range(3)]
        g=(mul(R,fixmat(fx)),Tn,ofx,ofy,H); cache[ri]=g; return g
    return xform
import math
# partie TTT1 -> ligne (releve sur les parents de Jin TTT1 : 1 poitrine, 2 bassin, p>=3 -> p+4)
def part_row(p): return {1:1,2:4}.get(p,p+4)
def rot_rest(ang):
    a,b,c=[x/65536*2*math.pi for x in ang]
    ca,sa,cb,sb,cc,sc=math.cos(a),math.sin(a),math.cos(b),math.sin(b),math.cos(c),math.sin(c)
    Rx=[[1,0,0],[0,ca,-sa],[0,sa,ca]]; Ry=[[cb,0,sb],[0,1,0],[-sb,0,cb]]; Rz=[[cc,-sc,0],[sc,cc,0],[0,0,1]]
    return mul(mul(Rz,Ry),Rx)
def pose_with_extras(frame_ps1,T1):
    base=pose(frame_ps1,T1)
    cache={}
    def xform(ri):
        if ri in MAP: return base(ri)
        if ri in cache: return cache[ri]
        w=row(T1,ri); par=part_row(w[6])
        Rp,Tp,ofx,ofy,H=xform(par)
        off=w[3:6]; ang=[x & 0xffff for x in w[7:10]]
        R=mul(Rp,rot_rest(ang))
        T=[Tp[k]+sum(Rp[k][c]*off[c] for c in range(3))/4096 for k in range(3)]
        cache[ri]=(R,T,ofx,ofy,H); return cache[ri]
    return xform
