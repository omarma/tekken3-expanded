#include "tekken3_force_background.h"
#include "tekken3_selector_layout.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static const Tekken3SelectorPacket force[] = {
#include "fixtures/tekken3_force_loading_packets.inc"
};
static const Tekken3SelectorPacket team[] = {
#include "fixtures/tekken3_team_loading_packets.inc"
};
static void loading(const Tekken3SelectorPacket *input, size_t n, int kind, int delta) {
    Tekken3SelectorPacket p[160];
    Tekken3LoadingFrame frame;
    assert(n <= 160);
    memcpy(p,input,n*sizeof(*p));
    for (size_t i=0;i<n;i++) p[i].source_addr += delta;
    assert(tekken3_loading_analyze_frame(p,n,368,480,&frame));
    assert(frame.layout_kind==kind);
    int backgrounds=0,left=0,right=0;
    for (size_t i=0;i<n;i++) {
        Tekken3SelectorPlacement a=tekken3_loading_place(&frame,&p[i],61);
        Tekken3SelectorPlacement b=tekken3_loading_place(&frame,&p[i],0);
        assert(!b.sidecar_dx && !b.expand_backdrop);
        if (p[i].opcode==0x2d && p[i].width==126) {
            assert(a.sidecar_dx==(p[i].source_addr>=frame.right_source && kind==1?61:-61));
            if(a.sidecar_dx<0)left++;else right++;
        }
        if (p[i].opcode==0x2d && p[i].width<70) {
            assert(a.expand_backdrop);backgrounds++;
        }
        if(kind==1 && p[i].opcode==0x65 && p[i].width==32)
            assert(a.sidecar_dx==(p[i].y<200?-61:61));
        if(kind==2 && p[i].opcode==0x65 && p[i].y==120)assert(a.sidecar_dx==61);
    }
    assert(backgrounds==42 && left==4 && right==(kind==1?4:0));
    for(size_t i=0;i<n;i++)if(p[i].source_addr==frame.left_source)p[i].width--;
    assert(!tekken3_loading_analyze_frame(p,n,368,480,&frame));
    assert(!tekken3_loading_analyze_frame(input,n,320,240,&frame));
}

static void reveal(void) {
    Tekken3ForceCell map[32];
    Tekken3ForceSprite sprites[14];
    Tekken3ForceReveal out[12];
    for(int i=0;i<32;i++)map[i]=(Tekken3ForceCell){(uint16_t)(((i/16)<<8)|(i%16)),(uint16_t)(100+i)};
    /* Every camera phase, including both map wrap boundaries. */
    for(int scroll=-1024;scroll<=2048;scroll++) {
        int offset=(scroll%1024+1024)%1024, first=offset/64, x0=-(offset%64);
        for(int row=0;row<2;row++)for(int col=0;col<7;col++) {
            int i=row*7+col;
            sprites[i]=(Tekken3ForceSprite){0x100004u+(unsigned)i*20,x0+col*64,row*64,map[row*16+(first+col)%16]};
        }
        size_t n=tekken3_force_reveal(map,16,2,scroll,0,61,sprites,14,out,12);
        int lo[2]={x0,x0},hi[2]={x0+448,x0+448};
        for(size_t i=0;i<n;i++) {
            int row=out[i].y/64;
            assert(out[i].x+64<=0 || out[i].x>=368);
            int col=(out[i].x-x0)/64;
            int index=(first+col+16)%16;
            assert(out[i].cell.tile==map[row*16+index].tile);
            assert(out[i].cell.clut==map[row*16+index].clut);
            if(out[i].x<lo[row])lo[row]=out[i].x;
            if(out[i].x+64>hi[row])hi[row]=out[i].x+64;
        }
        for(int row=0;row<2;row++)assert(lo[row]<=-61 && hi[row]>=429);
        assert(!tekken3_force_reveal(map,16,2,scroll,0,0,sprites,14,out,12));
    }
    sprites[0].cell.clut^=1;sprites[7].cell.clut^=1;
    assert(!tekken3_force_reveal(map,16,2,2048,0,61,sprites,14,out,12));
    assert(!tekken3_force_reveal(map,16,2,2048,0,61,sprites,6,out,12));
    /* The original background tilt changes height at each third column. */
    for(int slope=-12288;slope<=12288;slope+=24576)for(int first=0;first<16;first++) {
        for(int row=0;row<2;row++)for(int col=0;col<7;col++) {
            int i=row*7+col;
            sprites[i]=(Tekken3ForceSprite){0x100004u+(unsigned)i*20,-31+col*64,
                row*64-((first+col)/3-first/3)*slope/4096,map[row*16+(first+col)%16]};
        }
        size_t n=tekken3_force_reveal(map,16,2,first*64+31,slope,61,sprites,14,out,12);
        assert(n==4);
        for(size_t i=0;i<n;i++) {
            int index=(int)(out[i].edge_source-0x100004u)/20;
            int anchor=index%7, col=(out[i].x+31)/64;
            int thirds=(first+col<0?(first+col-2)/3:(first+col)/3);
            assert(out[i].y==sprites[index].y-(thirds-(first+anchor)/3)*slope/4096);
        }
    }
}
int main(void) {
    loading(force,sizeof(force)/sizeof(*force),2,0);
    loading(force,sizeof(force)/sizeof(*force),2,0x3c00);
    loading(team,sizeof(team)/sizeof(*team),1,0);
    loading(team,sizeof(team)/sizeof(*team),1,-0x3c00);
    reveal();
    puts("PASS: Force original-map reveal, Force and Team Battle loading A/B");
    return 0;
}
