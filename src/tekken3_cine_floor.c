/* The floor of a cinematic's close shots (src/tekken3_cine.c).
 *
 * The PS1 floor (0x80048240 calls *0x8009E728: 0x80048E58 -> 0x80048FF8 for
 * kind 0, 0x80049848 for kinds 1-4) is a grid of big tiles (1 800 units in
 * Gon's arena) around the fighters. A tile is dropped whole when one of its
 * corners is behind the camera (GTE SZ 0) or when its four corners are all
 * off the screen (0x80049338..0x80049490, 0x80049C84..0x80049DD8). A
 * fight's camera never looks at the floor near itself; a cinematic's low
 * close shots do, and the dropped tiles leave the black background
 * showing (Michelle's ending, its first two shots).
 *
 * After the game's floor, during a cinematic, every tile it dropped is
 * drawn again in pieces: split in four until each piece is in front of the
 * camera, small enough for the GPU and on the screen, with the tile's own
 * texture page, CLUT, UVs (interpolated), shading (kind 0: the depth fog,
 * kinds 1-4: the lights, computed for each piece's corners as the game does
 * for the grid's) and place in the display list. Pieces still too near the
 * camera are left out (a sliver under the camera, off the screen). Nothing
 * changes when the game drew every tile, nor outside cinematics, nor when
 * the PS1 floor routine did not draw (dark arena, a mod drawing its own
 * floor: the scratchpad sentinel is still there).
 *
 * The GTE state is the floor's own, still in the GTE after the call (only
 * 0x80048470, AddPrim, runs after it): rotation 0x800ADF70, translation
 * to the grid's origin (0x8004ADC4). RTPS as tools/arcade_stages/gte.py
 * (branch wip/arcade-stages); every grid corner is checked against the
 * game's results in the scratchpad (TEKKEN3_CINE_FLOOR_LOG). */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    SCRATCH=0x1F800000u, SENTINEL=0x7A5A1234u,
    FLOOR_FN=0x8009E728u, KIND0=0x80048E58u, KIND1=0x80049848u, DARK=0x800ADCA4u, MODE=0x800AFA88u,
    TILE=0x8009E780u, TEX_RANK=0x8009E790u, TEX_TABLE=0x8009E7F8u, UV_TABLE=0x8009E800u,
    LIGHT=0x8009E820u, NX=0x8009E824u, NZ=0x8009E828u, NVERT=0x8009E82Cu, GRID=0x800ADD14u,
    CAP=0x800ADD94u, BUFFER=0x800ADEFCu, WORLD=0x800ADF70u, CAMERA=0x800A85C0u, OTS=0x800A8C54u,
    FOG_DIV=0x800AE21Cu, FOG_TABLE=0x8001DF6Cu, FIGHTER=0x800AA190u, FIGHTER_SIZE=0x188C,
    PRIMS_MAX=600, PRIM=52, NEAR=64, DEPTH=6
};

typedef struct { int32_t r[3][3]; int32_t t[3]; int32_t ofx, ofy; uint32_t h; } Gte;
static uint8_t unr[0x101];

static uint32_t gte_divide(uint32_t h, uint32_t sz3) {
    if(h>=sz3*2u) return 0x1FFFF;
    int z=0;
    while(z<15 && !(sz3<<z&0x8000u)) z++;
    uint64_t n=(uint64_t)h<<z;
    int64_t d=(int64_t)(sz3<<z);
    int64_t u=unr[(d-0x7FC0)>>7]+0x101;
    d=(0x2000080-d*u)>>8;
    d=(0x0000080+d*u)>>8;
    uint64_t q=(n*(uint64_t)d+0x8000)>>16;
    return q>0x1FFFF?0x1FFFF:(uint32_t)q;
}

/* RTPS, sf 1: screen x, y (clamped as the GTE does) and SZ; raw: x, y
 * before the clamp (a corner far off the screen), then the depth before
 * its clamp (behind the camera: negative), then x, y in 16.16 before the
 * shift (sub-pixel precision, psxrecomp/ENHANCEMENTS.md G1.13). */
static void rtps(const Gte *g, int x, int y, int z, int *sx, int *sy, int *sz, int64_t raw[5]) {
    int64_t mac[3];
    for(int i=0;i<3;i++)
        mac[i]=(((int64_t)g->t[i]<<12)+(int64_t)g->r[i][0]*x+(int64_t)g->r[i][1]*y+(int64_t)g->r[i][2]*z)>>12;
    int64_t ir0=mac[0]<-0x8000?-0x8000:mac[0]>0x7FFF?0x7FFF:mac[0];
    int64_t ir1=mac[1]<-0x8000?-0x8000:mac[1]>0x7FFF?0x7FFF:mac[1];
    uint32_t sz3=(uint32_t)(mac[2]<0?0:mac[2]>0xFFFF?0xFFFF:mac[2]);
    int64_t q=gte_divide(g->h,sz3);
    int64_t vx=(q*ir0+g->ofx)>>16, vy=(q*ir1+g->ofy)>>16;
    if(raw) { raw[0]=vx; raw[1]=vy; raw[2]=mac[2]; raw[3]=q*ir0+g->ofx; raw[4]=q*ir1+g->ofy; }
    *sx=(int)(vx<-0x400?-0x400:vx>0x3FF?0x3FF:vx);
    *sy=(int)(vy<-0x400?-0x400:vy>0x3FF?0x3FF:vy);
    *sz=(int)sz3;
}

/* ---- The frame's floor ----------------------------------------------- */

static struct {
    Gte g;
    int x0, z0, kind, margin;               /* kind: 0 (fog), 1-4 (lights) */
    int light[2][2], centre[2], cam_x;      /* kinds 1, 2, 4 */
    int fog_from, fog_step, fog_k;          /* kind 0 (fog_k 0: the prims' own colours) */
    uint32_t ot, cursor, end;
    unsigned prims, tiles, off, deep, full, bent;
} f;
static uint32_t memory;

static int log_on(void) { static int l=-1; if(l<0) l=getenv("TEKKEN3_CINE_FLOOR_LOG")!=NULL; return l; }

static int32_t square(int32_t a, int32_t b) {             /* mult, low 32 bits */
    int32_t d=(int32_t)((uint32_t)a*(uint32_t)a+(uint32_t)b*(uint32_t)b);
    return d?d:1;
}

/* The shade of a floor point (grid units from the grid's origin, its SZ),
 * as the game computes it: kind 0 0x8004954C..0x80049604, kinds 1-4
 * 0x80049EF4..0x8004A120. -1: the tile's own colours. */
static int shade(int vx, int vz, int sz) {
    switch(f.kind) {
    case 0: {
        if(!f.fog_k) return -1;
        int a=sz-f.fog_from; if(a<0) a=0;
        int i=(int)((int32_t)((uint32_t)a*(uint32_t)f.fog_step)>>16); if(i>=0x400) i=0x3FF;
        int s=((int)psx_mod_read_byte(FOG_TABLE+(uint32_t)i)*f.fog_k>>7)+0x80;
        return s<0?0:s<0xFF?s:0xFE; }
    case 1: {
        int32_t s=0x0F200000/square(f.light[0][0]-vx,f.light[0][1]-vz)+0x0F200000/square(f.light[1][0]-vx,f.light[1][1]-vz);
        return s<0xFF?s:0xFE; }
    case 2: {
        int32_t s=0x2FAF0800/square(f.centre[0]-(f.x0+vx),f.centre[1]-(f.z0+vz)), cap=(int32_t)psx_mod_read_word(CAP);
        return (uint8_t)(cap<s?cap:s); }
    case 4: {
        int32_t s=0x18B82000/square(f.cam_x-(f.x0+vx),-0x7D0-(f.z0+vz));
        return s<0xFF?s:0xFE; }
    }
    return -1;
}

typedef struct { int x, z, u, v, c; } Corner;   /* grid units, texel, the tile's own grey */
typedef struct { int sx, sy, sz; int64_t raw[5]; } Shot;

/* A piece's corner moved by `grow` pixels, in 16.16 and inside the pixel of
 * the word written (G1.13: the integer part must be the word's). */
static int32_t grown16(int64_t v16, int grow, int word) {
    int64_t v = v16 + ((int64_t)grow << 16), lo = (int64_t)word << 16;
    return (int32_t)(v < lo ? lo : v > lo + 0xFFFF ? lo + 0xFFFF : v);
}

static Corner mix(const Corner *c, int s, int t, int n) {   /* bilinear at (s, t) / n */
    int64_t w[4]={(int64_t)(n-s)*(n-t),(int64_t)s*(n-t),(int64_t)(n-s)*t,(int64_t)s*t},nn=(int64_t)n*n;
    int64_t x=0,z=0,u=0,v=0,g=0;
    for(int k=0;k<4;k++) { x+=w[k]*c[k].x; z+=w[k]*c[k].z; u+=w[k]*c[k].u; v+=w[k]*c[k].v; g+=w[k]*c[k].c; }
    Corner o={(int)((x+nn/2)/nn),(int)((z+nn/2)/nn),(int)((u+nn/2)/nn),(int)((v+nn/2)/nn),(int)((g+nn/2)/nn)};
    return o;
}

static void emit(const Corner q[4], const Shot p[4], uint8_t code, uint32_t clut, uint32_t tpage, uint32_t at) {
    if(f.cursor+PRIM>f.end) { f.full++; return; }
    uint32_t a=f.cursor; f.cursor+=PRIM;
    /* One pixel bigger on every side: the pieces meet the game's tiles and
     * each other at T-junctions, which leave hairline cracks otherwise. */
    int cx=(p[0].sx+p[1].sx+p[2].sx+p[3].sx)/4, cy=(p[0].sy+p[1].sy+p[2].sy+p[3].sy)/4;
    /* TEKKEN3_CINE_FLOOR_INTEGER: the pieces without precision (the
     * before of tools/pgxp_cine.py). */
    static int integer=-1;
    if(integer<0) integer=getenv("TEKKEN3_CINE_FLOOR_INTEGER")!=NULL;
    int precise=!integer && psx_mod_precision_wanted();
    for(int k=0;k<4;k++) {
        int gx=(p[k].sx>cx)-(p[k].sx<cx), gy=(p[k].sy>cy)-(p[k].sy<cy);
        int x=p[k].sx+gx, y=p[k].sy+gy;
        int u=q[k].u<0?0:q[k].u>255?255:q[k].u, v=q[k].v<0?0:q[k].v>255?255:q[k].v;
        int s=shade(q[k].x,q[k].z,p[k].sz); if(s<0) s=q[k].c;
        uint32_t g=(uint32_t)s&0xFF;
        psx_mod_write_word(a+4+12*k,g|g<<8|g<<16|(k?0:(uint32_t)code<<24));
        uint32_t w=(uint32_t)(y&0xFFFF)<<16|(uint32_t)(x&0xFFFF);
        psx_mod_write_word(a+8+12*k,w);
        /* Sub-pixel precision: the corner's own 16.16 point, grown by the
         * same pixel (emitted pieces are never clamped). */
        if(precise)
            psx_mod_precise_word(a+8+12*k,w,grown16(p[k].raw[3],gx,x),grown16(p[k].raw[4],gy,y),
                                 (uint32_t)(p[k].sz<1?1:p[k].sz));
        psx_mod_write_word(a+12+12*k,(uint32_t)(v<<8|u)|(k==0?clut:k==1?tpage:0));
    }
    uint32_t o=psx_mod_read_word(at);
    psx_mod_write_word(a,(o&0x00FFFFFFu)|0x0C000000u);
    psx_mod_write_word(at,(o&0xFF000000u)|(a&0x00FFFFFFu));
    f.prims++;
}

/* A piece of a tile (corners in GT4 order: 0 1 on one edge, 2 3 on the
 * other), split in four until drawable. */
static void piece(const Corner q[4], int depth, uint8_t code, uint32_t clut, uint32_t tpage, uint32_t at) {
    Shot p[4]; int near=0, behind=0; int64_t minx=INT64_MAX, maxx=INT64_MIN, miny=INT64_MAX, maxy=INT64_MIN;
    for(int k=0;k<4;k++) {
        rtps(&f.g,q[k].x,0,q[k].z,&p[k].sx,&p[k].sy,&p[k].sz,p[k].raw);
        if(p[k].sz<NEAR) near=1;
        if(p[k].raw[2]<NEAR) behind++;
        if(p[k].raw[0]<minx) minx=p[k].raw[0];
        if(p[k].raw[0]>maxx) maxx=p[k].raw[0];
        if(p[k].raw[1]<miny) miny=p[k].raw[1];
        if(p[k].raw[1]>maxy) maxy=p[k].raw[1];
    }
    if(behind==4) { f.off++; return; }                      /* a flat piece: wholly behind too */
    /* Wholly off the screen (only when every corner is in front: a corner
     * behind the camera projects anywhere). */
    if(!near && (maxx<-f.margin || minx>=0x170+f.margin || maxy<0 || miny>=0x1E0)) { f.off++; return; }
    int clamped=0;
    for(int k=0;k<4;k++) if(p[k].raw[0]!=p[k].sx || p[k].raw[1]!=p[k].sy) clamped=1;
    if(!near && !clamped && maxx-minx<1000 && maxy-miny<500) { emit(q,p,code,clut,tpage,at); return; }
    if(depth>=DEPTH) { f.deep++; return; }
    Corner m[9];                                            /* 3 x 3: corners, edge middles, centre */
    for(int t=0;t<3;t++) for(int s=0;s<3;s++) m[3*t+s]=mix(q,s,t,2);
    static const int quads[4][4]={{0,1,3,4},{1,2,4,5},{3,4,6,7},{4,5,7,8}};
    for(int i=0;i<4;i++) {
        Corner c[4]={m[quads[i][0]],m[quads[i][1]],m[quads[i][2]],m[quads[i][3]]};
        piece(c,depth+1,code,clut,tpage,at);
    }
}

/* Before 0x80048240: the sentinel the PS1 floor overwrites (its first
 * corner's screen x, y; never this value, clamped to +-0x400). */
void tekken3_cine_floor_before(void) { psx_mod_write_word(SCRATCH,SENTINEL); }

/* After 0x80048240 with the fighters p1, p2. */
void tekken3_cine_floor_after(CPUState *cpu, uint32_t p1, uint32_t p2) {
    if(psx_mod_read_word(SCRATCH)==SENTINEL) return;                 /* the PS1 floor did not draw */
    uint32_t fn=psx_mod_read_word(FLOOR_FN);
    if((fn!=KIND0 && fn!=KIND1) || psx_mod_read_word(DARK) || psx_mod_read_word(MODE)==8) return;
    if(!unr[0]) for(int i=0;i<0x101;i++) { int v=(0x40000/(i+0x100)+1)/2-0x101; unr[i]=(uint8_t)(v<0?0:v); }
    if(!memory && !(memory=psx_mod_alloc_gpu_dma_memory(2*PRIMS_MAX*PRIM,16))) {
        static int told;                                             /* never silent (the 1.3.0 black floor) */
        if(!told++) fprintf(stderr,"Cine floor: no GPU-DMA memory left for %u bytes, the close shots' floor stays as the game draws it\n",2*PRIMS_MAX*PRIM);
        return;
    }
    if(log_on()) {
        static int told;
        if(!told++) fprintf(stderr,"Cine floor: pieces at 0x%08X, %u bytes\n",memory,2*PRIMS_MAX*PRIM);
    }
    const int size=(int)psx_mod_read_word(TILE), nx=(int)psx_mod_read_word(NX), nz=(int)psx_mod_read_word(NZ);
    const int nv=(int)psx_mod_read_word(NVERT);
    const uint32_t grid=psx_mod_read_word(GRID);
    if(size<=0 || nx<=0 || nz<=0 || nx>10 || !grid || nv<=0) return;
    /* The floor's GTE, as the game left it. */
    const uint32_t *c=cpu->gte_ctrl;
    f.g.r[0][0]=(int16_t)c[0]; f.g.r[0][1]=(int16_t)(c[0]>>16); f.g.r[0][2]=(int16_t)c[1];
    f.g.r[1][0]=(int16_t)(c[1]>>16); f.g.r[1][1]=(int16_t)c[2]; f.g.r[1][2]=(int16_t)(c[2]>>16);
    f.g.r[2][0]=(int16_t)c[3]; f.g.r[2][1]=(int16_t)(c[3]>>16); f.g.r[2][2]=(int16_t)c[4];
    f.g.t[0]=(int32_t)c[5]; f.g.t[1]=(int32_t)c[6]; f.g.t[2]=(int32_t)c[7];
    f.g.ofx=(int32_t)c[24]; f.g.ofy=(int32_t)c[25]; f.g.h=c[26]&0xFFFF;
    /* The grid's origin (a tile corner): the translation less the world's,
     * back through the rotation, to the nearest tile. */
    double v[3]={0,0,0};
    for(int i=0;i<3;i++) {
        double d=(double)f.g.t[i]-(double)(int32_t)psx_mod_read_word(WORLD+0x14+4*(uint32_t)i);
        for(int k=0;k<3;k++) v[k]+=f.g.r[i][k]*d/4096.0;
    }
    int gx=(int)floor(v[0]/size+0.5), gz=(int)floor(v[2]/size+0.5);
    f.x0=gx*size; f.z0=gz*size;
    f.margin=psx_mod_widescreen_x_margin(); if(f.margin<0) f.margin=0;
    const uint32_t tex=psx_mod_read_word(TEX_TABLE);
    if(fn==KIND0) {
        f.kind=0;
        f.fog_k=(int16_t)psx_mod_read_half(tex+0x326);
        int mx=((int)psx_mod_read_word(FIGHTER)+(int)psx_mod_read_word(FIGHTER+FIGHTER_SIZE))/2;
        int mz=((int)psx_mod_read_word(FIGHTER+8)+(int)psx_mod_read_word(FIGHTER+FIGHTER_SIZE+8))/2;
        double dx=(int)psx_mod_read_word(CAMERA+0x14)-mx, dz=(int)psx_mod_read_word(CAMERA+0x1C)-mz;
        f.fog_from=(int)sqrt(dx*dx+dz*dz);
        int32_t div=(int32_t)psx_mod_read_word(FOG_DIV);
        f.fog_step=div?0x4000000/div:0;
    } else {
        f.kind=(int16_t)psx_mod_read_half(LIGHT);
        f.light[0][0]=(int)psx_mod_read_word(p1+0xF68)-f.x0; f.light[0][1]=(int)psx_mod_read_word(p1+0xF70)-f.z0;
        f.light[1][0]=(int)psx_mod_read_word(p2+0xF68)-f.x0; f.light[1][1]=(int)psx_mod_read_word(p2+0xF70)-f.z0;
        f.centre[0]=((int)psx_mod_read_word(p1+0xF68)+(int)psx_mod_read_word(p2+0xF68))/2;
        f.centre[1]=((int)psx_mod_read_word(p1+0xF70)+(int)psx_mod_read_word(p2+0xF70))/2;
        f.cam_x=(int)psx_mod_read_word(CAMERA+0x14);
    }
    f.ot=psx_mod_read_word(psx_mod_read_word(OTS)+4)+0xFF4;
    unsigned buffer=psx_mod_read_word(BUFFER)&1;
    f.cursor=memory+buffer*PRIMS_MAX*PRIM; f.end=f.cursor+PRIMS_MAX*PRIM; f.prims=f.tiles=f.off=f.deep=f.full=f.bent=0;
    const uint32_t verts=psx_mod_read_word(grid+0xC), table=psx_mod_read_word(grid+0x1C);
    const uint32_t slots=grid+0x5E4+buffer*0x1450;
    /* The game's own results (scratchpad, 0x8004A364): screen x, y a corner, then SZ. */
    const uint32_t sz_at=SCRATCH+(uint32_t)(nv+2)*4+0x20+(uint32_t)((nv+3)/2)*2;
    int col0=gx%nx; if(col0<0) col0+=nx;
    int row=gz%nz; if(row<0) row+=nz; row=nz-(row+1);
    unsigned mismatch=0, checked=0;
    for(int r=0;r<nz;r++) {
        int col=col0;
        for(int cc=0;cc<nx;cc++,col=col+1<nx?col+1:0) {
            uint32_t w=psx_mod_read_word(table+(uint32_t)(cc*4+r*40));
            uint32_t slot=slots+(uint32_t)(PRIM*(r*nx+cc));
            Corner q[4];
            int drawn=1, sy_in=0, sx_in=0, bent=0;
            int64_t raw[5], lo[2]={INT64_MAX,INT64_MAX}, hi[2]={INT64_MIN,INT64_MIN};
            for(int k=0;k<4;k++) {
                uint32_t idx=w>>(8*k)&0xFF, vw=psx_mod_read_word(verts+4*idx);
                q[k].x=(int16_t)(vw>>16); q[k].z=(int16_t)(vw&0xFFFF);
                q[k].c=psx_mod_read_byte(slot+4+12*(uint32_t)k);
                int sx,sy,sz;
                rtps(&f.g,q[k].x,0,q[k].z,&sx,&sy,&sz,raw);
                if(raw[0]!=sx || raw[1]!=sy) bent=1;
                for(int a=0;a<2;a++) { if(raw[a]<lo[a]) lo[a]=raw[a]; if(raw[a]>hi[a]) hi[a]=raw[a]; }
                uint16_t gsz=psx_mod_read_half(sz_at+2*idx);
                uint32_t gxy=psx_mod_read_word(SCRATCH+4*idx);
                checked++;
                if(gsz!=(uint16_t)sz || gxy!=((uint32_t)(sy&0xFFFF)<<16|(uint32_t)(sx&0xFFFF))) mismatch++;
                if(!gsz) drawn=0;
                if((int16_t)(gxy>>16)>=0 && (int16_t)(gxy>>16)<0x1E0) sy_in=1;
                if((gxy&0xFFFF)<0x170) sx_in=1;
            }
            if(drawn && sy_in && sx_in) {
                /* The game drew it: right, unless a corner was clamped
                 * (the tile shrunk and bent, the background showing where
                 * it should be) or it is too big for the GPU (dropped). */
                if(!bent && hi[0]-lo[0]<1024 && hi[1]-lo[1]<512) continue;
                psx_mod_write_word(slot,psx_mod_read_word(slot)&0x00FFFFFFu);  /* sent empty: still linked */
                f.bent++;
            }
            /* The tile's texture (0x800494DC..0x8004976C, 0x80049E3C..0x8004A288). */
            uint32_t at=f.ot-4*psx_mod_read_byte(TEX_RANK+(uint32_t)(row*10+col));
            uint32_t entry=tex+(uint32_t)(row*80+4+col*8);
            uint32_t t6=psx_mod_read_word(entry), t9=psx_mod_read_word(entry+4);
            uint32_t uvs=UV_TABLE+(t6>>30)*8, base=t6&0xFFFF, order=(t6>>16)&0x600;
            static const int orders[4][4]={{0,1,2,3},{1,0,3,2},{2,3,0,1},{3,2,1,0}};
            for(int k=0;k<4;k++) {
                uint32_t uv=(base+psx_mod_read_half(uvs+2*(uint32_t)orders[order>>9][k]))&0xFFFF;
                q[k].u=(int)(uv&0xFF); q[k].v=(int)(uv>>8);
            }
            uint8_t code=psx_mod_read_byte(slot+7);
            if((code&0xFC)!=0x3C) code=0x3C;
            f.tiles++;
            piece(q,0,code,t9&0xFFFF0000u,t6&0x39FF0000u,at);
        }
        row=row-1<0?nz-1:row-1;
    }
    if(log_on()) {
        static unsigned frames;
        if(f.tiles || mismatch || !(frames++%120))
            fprintf(stderr,"Cine floor: kind %d, origin %d %d, %u dropped or bent (%u) tiles drawn again in %u pieces (%u off the screen, %u too near, %u past the buffer); corners %u/%u as the game's\n",
                    f.kind,f.x0,f.z0,f.tiles,f.bent,f.prims,f.off,f.deep,f.full,checked-mismatch,checked);
    }
}
