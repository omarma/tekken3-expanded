import sys,io,base64; sys.path.insert(0,__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import numpy as np
from PIL import Image
def holes(m,reg,cull=True,size=(700,1600)):
    T=np.array([t[2:11] for t in m['tris']],float).reshape(-1,3,3)
    P=T-T.reshape(-1,3).mean(0); W,H=size; sc=0.9*min(W/np.ptp(P[:,:,0]),H/np.ptp(P[:,:,1]))
    X=P[:,:,0]*sc+W/2; Y=P[:,:,1]*sc+H/2
    cov=np.zeros((H,W),bool)
    for i in range(len(T)):
        x,y=X[i],Y[i]; area=(x[1]-x[0])*(y[2]-y[0])-(x[2]-x[0])*(y[1]-y[0])
        if (cull and area<=0) or area==0: continue
        x0,x1=int(max(0,x.min())),int(min(W-1,x.max()+1)); y0,y1=int(max(0,y.min())),int(min(H-1,y.max()+1))
        if x1<=x0 or y1<=y0: continue
        gx,gy=np.meshgrid(np.arange(x0,x1)+.5,np.arange(y0,y1)+.5)
        w0=((x[1]-gx)*(y[2]-gy)-(x[2]-gx)*(y[1]-gy))/area; w1=((x[2]-gx)*(y[0]-gy)-(x[0]-gx)*(y[2]-gy))/area; w2=1-w0-w1
        cov[y0:y1,x0:x1]|=(w0>=0)&(w1>=0)&(w2>=0)
    return (~cov[reg]).sum()
