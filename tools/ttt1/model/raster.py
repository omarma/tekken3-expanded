"""Rendu logiciel (z-buffer, textures) d'un export jin_ps1*.js, pour inspection."""
import sys,json,base64,io
import numpy as np
from PIL import Image
def load(path):
    s=open(path).read(); s=s[s.index('push(')+5:s.rindex(')')]
    return json.loads(s)
def render(m,view='face',size=(520,760),cull=True,only=None):
    texs=[np.array(Image.open(io.BytesIO(base64.b64decode(t.split(',')[1]))).convert('RGBA')) for t in m['textures']]
    T=np.array([t[2:11] for t in m['tris']],float).reshape(-1,3,3)
    UV=np.array([t[11:17] for t in m['tris']],float).reshape(-1,3,2)
    TI=[t[1] for t in m['tris']]; RI=[t[0] for t in m['tris']]
    P=T.copy()
    Q=P.reshape(-1,3); c=(Q.min(0)+Q.max(0))/2
    P-=c
    if view=='dos': P[:,:,0]*=-1; P[:,:,2]*=-1
    if view=='profil': P=P[:,:,[2,1,0]]; P[:,:,2]*=-1
    W,H=size; sc=0.9*min(W/np.ptp(P[:,:,0]),H/np.ptp(P[:,:,1]))
    X=P[:,:,0]*sc+W/2; Y=P[:,:,1]*sc+H/2; Z=P[:,:,2]
    img=np.full((H,W,3),40,np.uint8); zb=np.full((H,W),1e18)
    for i in range(len(T)):
        if only is not None and RI[i] not in only: continue
        x,y,z=X[i],Y[i],Z[i]
        area=(x[1]-x[0])*(y[2]-y[0])-(x[2]-x[0])*(y[1]-y[0])
        if cull and area<=0: continue
        if area==0: continue
        x0,x1=int(max(0,np.floor(x.min()))),int(min(W-1,np.ceil(x.max())))
        y0,y1=int(max(0,np.floor(y.min()))),int(min(H-1,np.ceil(y.max())))
        if x1<x0 or y1<y0: continue
        gx,gy=np.meshgrid(np.arange(x0,x1+1)+.5,np.arange(y0,y1+1)+.5)
        w0=((x[1]-gx)*(y[2]-gy)-(x[2]-gx)*(y[1]-gy))/area
        w1=((x[2]-gx)*(y[0]-gy)-(x[0]-gx)*(y[2]-gy))/area
        w2=1-w0-w1
        inside=(w0>=-1e-6)&(w1>=-1e-6)&(w2>=-1e-6)
        if not inside.any(): continue
        zz=w0*z[0]+w1*z[1]+w2*z[2]
        u=np.clip((w0*UV[i,0,0]+w1*UV[i,1,0]+w2*UV[i,2,0]).astype(int),0,255)
        v=np.clip((w0*UV[i,0,1]+w1*UV[i,1,1]+w2*UV[i,2,1]).astype(int),0,255)
        tex=texs[TI[i]][v,u]
        ok=inside&(tex[...,3]>0)&(zz<zb[y0:y1+1,x0:x1+1])
        zb[y0:y1+1,x0:x1+1][ok]=zz[ok]
        img[y0:y1+1,x0:x1+1][ok]=tex[...,:3][ok]
    return Image.fromarray(img)
if __name__=='__main__':
    m=load(sys.argv[1]); out=sys.argv[2]
    ims=[render(m,v,cull=c) for v,c in (('face',False),('face',True),('dos',True))]
    sheet=Image.new('RGB',(sum(i.width for i in ims),ims[0].height))
    x=0
    for im in ims: sheet.paste(im,(x,0)); x+=im.width
    sheet.save(out)
