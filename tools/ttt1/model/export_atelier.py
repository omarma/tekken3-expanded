"""Donnees de la page Atelier (squelettes, pieces en 3D, octets) : Jin arcade,
Jin PS1, Jin TTT1, Kazuya TTT1, Kazuya converti PS1. Sortie locale sous
workspace/native/viewer/ (donnees du jeu : ne jamais publier)."""
import json,struct,sys,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from fmt import *
import simulate as SM, convert as C
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D=os.path.join(ROOT,'workspace/native/')
EXE=open(os.path.join(ROOT,'disc/SLUS_004.02'),'rb').read()
f=lambda a:a-0x80010000+0x800
P2R=list(EXE[f(0x8001a05c):f(0x8001a05c)+24])
def arcade_a(b):
    n=struct.unpack_from('<I',b,0)[0]
    return dict(g1=[],g2=[],verts=[struct.unpack_from('<4h',b,4+i*8) for i in range(n)])
def model(name,path,kind,ttt1=False,cut=None,s2t=None):
    m=load(path); m=m[:cut] if cut else m
    so=offsets(m); rows=[]
    for r in range(nrows(m)):
        w=row(m,r); active=bool(w[10]) and w[0]>2
        sizes={k:(so[so.index(w[i])+1]-w[i] if w[i]>2 else 0) for k,i in zip('abcde',(0,1,2,12,13))}
        a=dict(g1=[],g2=[],verts=[]); nn=0; nprim=0
        if active:
            if kind=='arcade': a=arcade_a(block(m,w[0]))
            else:
                nn=len(parse_a(block(m,w[0]))['verts'])
                if r>0 and row(m,r-1)[12]>2: a=SM.vlist(m,r,ttt1)
            if w[1]>2 and kind!='arcade': nprim=sum(len(x) for x in parse_b(block(m,w[1])))
        rows.append(dict(row=r,active=active,bone=w[3:6],parent=w[6],rot=w[7:10],flag=w[10],
            sizes=sizes,g1=list(a['g1']),g2=list(a['g2']),verts=[v[:3] for v in a['verts']],
            normals=nn,prims=nprim,src=(s2t[r] if s2t else None)))
    return dict(name=name,kind=kind,bytes=len(m),scale=struct.unpack_from('<I',m,4)[0],rows=rows)
out=dict(ps1_part_to_row=P2R,models=[
    model('Jin — T3 arcade',D+'jin-t3arcade-raw.bin','arcade',cut=0x11af8),
    model('Jin — T3 PS1 (BNS 143)',D+'rec143.bin','packed'),
    model('Jin — TTT1',D+'jin-ttt1.3dm','packed',ttt1=True),
    model('Kazuya — TTT1',D+'kazuya-ttt1.3dm','packed',ttt1=True),
    model('Kazuya — converti PS1',D+'kazuya-ps1.3dm','packed',s2t=C.S2T)])
open(D+'viewer/data.js','w').write('window.MODELS='+json.dumps(out)+';')
print('ok',[(x['name'],x['bytes']) for x in out['models']])
