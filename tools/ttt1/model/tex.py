"""Textures : espace VRAM virtuel (TTT1 : TIM concatenes ; PS1 : capture VRAM),
et rendu d'une page 256x256 pour un materiau (page<<16 | clut)."""
import struct
from PIL import Image
W,H=1024,512
PAL_Y=448   # TTT1 : palettes rangees a part, sinon les pixels poses en (0,0) les ecrasent
def vram_from_tims(t,pal_y=PAL_Y):
    v=[[0]*W for _ in range(H)]; p=0
    while p+8<=len(t):
        mg,fl=struct.unpack_from('<II',t,p)
        if mg!=16: break
        p+=8
        for pal in ((True,False) if fl&8 else (False,)):
            sz,x,y,w,h=struct.unpack_from('<I4H',t,p)
            px=struct.unpack_from(f'<{w*h}H',t,p+12)
            yy=y+(pal_y if pal else 0)
            for r in range(h):
                v[yy+r][x:x+w]=px[r*w:(r+1)*w]
            p+=sz
    return v
def vram_from_dump(b):
    px=struct.unpack(f'<{W*H}H',b); return [list(px[r*W:(r+1)*W]) for r in range(H)]
def rgba(c):
    if c==0: return (0,0,0,0)
    return ((c&31)*255//31,((c>>5)&31)*255//31,((c>>10)&31)*255//31,255)
def page_image(v,page,clut,pal_y=0):
    mode=(page>>7)&3; xb=(page&15)*64; yb=256 if page&16 else 0
    cx=(clut&63)*16; cy=((clut>>6)&0x1ff)+pal_y
    im=Image.new('RGBA',(256,256)); pix=im.load()
    for y in range(256):
        row=v[(yb+y)%H]
        for u in range(256):
            if mode==0: hw=row[(xb+u//4)%W]; i=(hw>>(4*(u%4)))&15
            elif mode==1: hw=row[(xb+u//2)%W]; i=(hw>>(8*(u%2)))&255
            else: pix[u,y]=rgba(row[(xb+u)%W]); continue
            pix[u,y]=rgba(v[cy][(cx+i)%W])
    return im
def vram_from_costume_record(b, start=48):
    """TIM d'un enregistrement costume PS1 (141, 145...) poses comme le jeu :
    pixels repliés dans la bande x=384.., palettes a y=504+."""
    v=[[0]*W for _ in range(H)]; p=start; n=0
    while p+8<=len(b):
        mg,fl=struct.unpack_from('<II',b,p)
        if mg!=16 or fl not in (0,1,8,9): break
        p+=8
        for pal in ((True,False) if fl&8 else (False,)):
            sz,x,y,w,h=struct.unpack_from('<I4H',b,p)
            px=struct.unpack_from(f'<{w*h}H',b,p+12)
            for r in range(h):
                if pal: X,Y=x,504+y+r
                else:   X,Y=384+x%64,y+r+(128 if x>=64 else 0)
                v[Y%H][X:X+w]=px[r*w:(r+1)*w]
            p+=sz
        n+=1
    return v,n,p
