import struct
def load(p): return open(p,'rb').read()
def nrows(m): return struct.unpack_from('<I',m,0)[0]
def row(m,r): return struct.unpack_from('<14i',m,24+r*56)
def offsets(m):
    s=set()
    for r in range(nrows(m)):
        w=row(m,r)
        for k in (0,1,2,12,13):
            if w[k]>2: s.add(w[k])
    return sorted(s)+[len(m)]
def block(m,o):
    so=offsets(m); return m[o:so[so.index(o)+1]]
def parse_a(b):
    p=0; head=struct.unpack_from('<I',b,0)[0]; p=4; groups=[]
    for g in range(2):
        n=struct.unpack_from('<I',b,p)[0]; p+=4
        groups.append(list(b[p:p+n])); p+=(n+3)&~3
    n=struct.unpack_from('<I',b,p)[0]; p+=4
    v=[struct.unpack_from('<4h',b,p+i*8) for i in range(n)]; p+=8*n
    return dict(head=head,g1=groups[0],g2=groups[1],verts=v,used=p,size=len(b))
def parse_b(b):
    p=0;fams=[]
    for k in range(4):
        n=struct.unpack_from('<I',b,p)[0];p+=4;st=12 if k==3 else 8
        fams.append([b[p+i*st:p+(i+1)*st] for i in range(n)]);p+=n*st
    return fams
def prim_verts(k,rec):
    w=struct.unpack_from('<I',rec,0)[0]
    f=lambda s:(w>>s)&0x1fc
    return [f(0)//4,f(7)//4,f(14)//4] if k in (0,2) else [f(0)//4,f(7)//4,f(14)//4,f(23)//4]  # ordre des coins du paquet GPU
def parse_d(b):
    """Bloc de positions : en-tete, emprunts (8 bits), sommets, puis 3 groupes a
    champs de 9 bits (indice & 0xff, drapeau 0x100) et 1 groupe a champs de 2 bits."""
    a=parse_a(b); p=a['used']; tails=[]
    for bits in (9,9,9,2):
        if p+4>len(b): tails.append([]); continue
        n=struct.unpack_from('<I',b,p)[0]; p+=4
        per=32//bits if bits==2 else 3
        words=(n+per-1)//per; vals=[]
        for wi in range(words):
            w=struct.unpack_from('<I',b,p+4*wi)[0]
            for k in range(per):
                if len(vals)<n: vals.append((w>>(bits*k))&((1<<bits)-1))
        p+=4*words; tails.append(vals)
    a['tails']=tails; a['end']=p; return a
def parse_c_ps1(c):
    """Bloc c PS1 : u16 decalage table UV, materiaux u16, table UV (u16 = u | v<<8),
    puis par famille : compte (octet), et par polygone : materiau (octet), indices UV."""
    uvoff=struct.unpack_from('<H',c,0)[0]
    mats=[struct.unpack_from('<H',c,o)[0] for o in range(2,uvoff,2)]
    uvt=c[uvoff:]; srcoff=struct.unpack_from('<H',uvt,0)[0]
    uvs=[struct.unpack_from('<H',uvt,2+2*i)[0] for i in range((srcoff-2)//2)]
    p=uvoff+srcoff; prims=[]
    for k in range(4):
        n=c[p]; p+=1; nv=4 if k&1 else 3
        for i in range(n):
            mat=c[p]; idx=list(c[p+1:p+1+nv]); p+=1+nv
            prims.append((k,mats[mat] if mat<len(mats) else None,[(uvs[j]&255,uvs[j]>>8) if j<len(uvs) else None for j in idx]))
    return prims
def parse_c_ttt1(c):
    """Bloc c TTT1 : u32 decalage table UV, materiaux u32 (page<<16 | palette),
    table UV (u16 decalage puis u16 = u | v<<8), puis comme PS1."""
    uvoff=struct.unpack_from('<I',c,0)[0]
    mats=[struct.unpack_from('<I',c,o)[0] for o in range(4,uvoff,4)]
    uvt=c[uvoff:]; srcoff=struct.unpack_from('<H',uvt,0)[0]
    uvs=[struct.unpack_from('<H',uvt,2+2*i)[0] for i in range((srcoff-2)//2)]
    p=uvoff+srcoff; prims=[]
    for k in range(4):
        n=c[p]; p+=1; nv=4 if k&1 else 3
        for i in range(n):
            mat=c[p]; idx=list(c[p+1:p+1+nv]); p+=1+nv
            prims.append((k,mats[mat] if mat<len(mats) else None,[(uvs[j]&255,uvs[j]>>8) if j<len(uvs) else None for j in idx]))
    return prims
