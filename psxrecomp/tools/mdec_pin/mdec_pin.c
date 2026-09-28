/* mdec_pin.c — byte-exact MDEC numeric pin: OUR pipeline (verbatim from
 * runtime/src/mdec.c on wt/tomba2-mdec-faithful-wip) vs BEETLE's verbatim
 * pipeline (mednafen/psx/mdec.cpp), on identical synthetic input. Diffs each
 * stage (post-dequant Coeff -> post-IDCT block -> YUV->RGB) to localize the bug.
 *
 * Build: gcc -O2 -o mdec_pin mdec_pin.c && ./mdec_pin
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>

/* ===================== shared synthetic input ===================== */
/* A varied (asymmetric) scale matrix so the transpose is exercised, and a
 * varied quant. The exact values don't matter — both decoders get the same. */
static uint16_t SCALE_WORDS[64];
static uint8_t  QUANT[64];
/* One luma block of RLE: DC then a few (run,level) ACs. word = (run<<10)|level10 */
static uint16_t RLE[8];
static int RLE_N;

static void make_input(void) {
    for (int i = 0; i < 64; i++) SCALE_WORDS[i] = (uint16_t)(0x1000 + (i * 53 % 777) - 388); /* signed-ish */
    for (int i = 0; i < 64; i++) QUANT[i] = (uint8_t)(2 + (i % 17));
    int n = 0;
    /* DC word: qscale=8 (bits15..10), level = 100 */
    RLE[n++] = (uint16_t)((8u << 10) | (100u & 0x3FF));
    /* ACs: (run,level) */
    RLE[n++] = (uint16_t)((0u << 10) | ((uint16_t)(-50) & 0x3FF)); /* run0, neg level */
    RLE[n++] = (uint16_t)((3u << 10) | (40u & 0x3FF));             /* run3 */
    RLE[n++] = (uint16_t)((1u << 10) | ((uint16_t)(-7) & 0x3FF));
    RLE[n++] = (uint16_t)((10u << 10) | (5u & 0x3FF));
    RLE_N = n;
}

/* ===================== OURS (verbatim from mdec.c) ===================== */
static const uint8_t my_zig[64] = {
    0x00,0x08,0x01,0x02,0x09,0x10,0x18,0x11, 0x0a,0x03,0x04,0x0b,0x12,0x19,0x20,0x28,
    0x21,0x1a,0x13,0x0c,0x05,0x06,0x0d,0x14, 0x1b,0x22,0x29,0x30,0x38,0x31,0x2a,0x23,
    0x1c,0x15,0x0e,0x07,0x0f,0x16,0x1d,0x24, 0x2b,0x32,0x39,0x3a,0x33,0x2c,0x25,0x1e,
    0x17,0x1f,0x26,0x2d,0x34,0x3b,0x3c,0x35, 0x2e,0x27,0x2f,0x36,0x3d,0x3e,0x37,0x3f
};
static int16_t my_scale[64];
static int16_t my_sign_extend_10(uint16_t v){ return (int16_t)((int16_t)(v<<6)>>6); }
static int my_clamp(int v,int lo,int hi){ return v<lo?lo:(v>hi?hi:v); }
static int my_sign_x_to_s32(int bits,int v){ int s=32-bits; return (int)(((int32_t)((uint32_t)v<<s))>>s); }
static int my_mask9(int v){ v=my_sign_x_to_s32(9,v); if(v<-128)v=-128; if(v>127)v=127; return v; }
static void my_set_scale(void){ for(uint32_t i=0;i<64;i++){ uint32_t t=((i&7u)<<3)|((i>>3)&7u); my_scale[t]=(int16_t)((int16_t)SCALE_WORDS[i]>>3);} }
static void my_idct(int16_t *block){
    int16_t tmp[64];
    for(int col=0;col<8;col++) for(int x=0;x<8;x++){ int s=0; for(int u=0;u<8;u++) s+=(int)block[col*8+u]*(int)my_scale[x*8+u]; tmp[x*8+col]=(int16_t)((s+0x4000)>>15);}
    for(int col=0;col<8;col++) for(int x=0;x<8;x++){ int s=0; for(int u=0;u<8;u++) s+=(int)tmp[col*8+u]*(int)my_scale[x*8+u]; block[col*8+x]=(int16_t)my_mask9((s+0x4000)>>15);}
}
static void my_dequant(int16_t *block, const uint8_t *quant){
    memset(block,0,64*sizeof(int16_t));
    int p=0; uint16_t word=RLE[p++];
    uint32_t qscale=(word>>10)&0x3Fu; uint32_t k=0;
    int ci=my_sign_extend_10(word&0x3FFu); int q=(int)quant[0];
    int tmp=(q!=0)?(((ci*q)<<4)+(ci?(ci<0?8:-8):0)):((ci*2)<<4);
    block[0]=(int16_t)my_clamp(tmp,-0x4000,0x3FFF);
    while(p<RLE_N && k<63u){ word=RLE[p++]; if(word==0xFE00u)break; k+=((word>>10)&0x3Fu)+1u; if(k>=64u)break;
        ci=my_sign_extend_10(word&0x3FFu); q=(int)qscale*(int)quant[k];
        tmp=(q!=0)?((((ci*q)>>3)<<4)+(ci?(ci<0?8:-8):0)):((ci*2)<<4);
        block[my_zig[k]]=(int16_t)my_clamp(tmp,-0x4000,0x3FFF);
    }
}
static void my_yuv(int y,int cr,int cb,int*r,int*g,int*b){
    *r=my_mask9(y+(((359*cr)+0x80)>>8));
    *g=my_mask9(y+((((-88*cb)&~0x1F)+((-183*cr)&~0x07)+0x80)>>8));
    *b=my_mask9(y+(((454*cb)+0x80)>>8));
    *r^=0x80; *g^=0x80; *b^=0x80;
}

/* ===================== BEETLE (verbatim from mdec.cpp) ===================== */
static const uint8_t be_zig[64] = {
    0x00,0x08,0x01,0x02,0x09,0x10,0x18,0x11, 0x0a,0x03,0x04,0x0b,0x12,0x19,0x20,0x28,
    0x21,0x1a,0x13,0x0c,0x05,0x06,0x0d,0x14, 0x1b,0x22,0x29,0x30,0x38,0x31,0x2a,0x23,
    0x1c,0x15,0x0e,0x07,0x0f,0x16,0x1d,0x24, 0x2b,0x32,0x39,0x3a,0x33,0x2c,0x25,0x1e,
    0x17,0x1f,0x26,0x2d,0x34,0x3b,0x3c,0x35, 0x2e,0x27,0x2f,0x36,0x3d,0x3e,0x37,0x3f
};
static int16_t be_idctmat[64];
static int be_sign_x(int bits,int v){ int s=32-bits; return (int)(((int32_t)((uint32_t)v<<s))>>s); }
static int16_t be_sign_10_to_s16(int v){ return (int16_t)be_sign_x(10,v); }
static int be_mask9(int v){ v=be_sign_x(9,v); if(v<-128)v=-128; if(v>127)v=127; return v; }
static int be_min(int a,int b){return a<b?a:b;} static int be_max(int a,int b){return a>b?a:b;}
static void be_set_scale(void){ /* mdec.cpp:647, transposed >>3 */
    for(int i=0;i<64;i++){ be_idctmat[((i&7)<<3)|((i>>3)&7)]=(int16_t)((int16_t)SCALE_WORDS[i]>>3);} }
static void be_idct_1d_int16(int16_t *in,int16_t *out){
    for(int col=0;col<8;col++) for(int x=0;x<8;x++){ int s=0; for(int u=0;u<8;u++) s+=in[col*8+u]*be_idctmat[x*8+u]; out[x*8+col]=(int16_t)((s+0x4000)>>15);} }
static void be_idct_1d_int8(int16_t *in,int16_t *out){
    for(int col=0;col<8;col++) for(int x=0;x<8;x++){ int s=0; for(int u=0;u<8;u++) s+=in[col*8+u]*be_idctmat[x*8+u]; out[col*8+x]=(int16_t)be_mask9((s+0x4000)>>15);} }
static void be_idct(int16_t *in,int16_t *out){ int16_t t[64]; be_idct_1d_int16(in,t); be_idct_1d_int8(t,out); }
static void be_dequant(int16_t *Coeff,const uint8_t *QM){ /* WriteImageData, mdec.cpp:425 */
    memset(Coeff,0,64*sizeof(int16_t));
    int p=0; int CoeffIndex=0; int QScale=0;
    while(p<RLE_N){
        uint16_t V=RLE[p++];
        if(CoeffIndex==0){
            if(V==0xFE00) continue;
            QScale=V>>10;
            int q=QM[0]; int ci=be_sign_10_to_s16(V&0x3FF); int tmp;
            if(q!=0) tmp=(int32_t)((uint32_t)(ci*q)<<4)+(ci?((ci<0)?8:-8):0);
            else     tmp=(uint32_t)(ci*2)<<4;
            Coeff[be_zig[0]]=be_min(0x3FFF,be_max(-0x4000,tmp)); CoeffIndex++;
        } else {
            if(V==0xFE00){ while(CoeffIndex<64) Coeff[be_zig[CoeffIndex++]]=0; }
            else {
                uint32_t rl=V>>10;
                for(uint32_t i=0;i<rl && CoeffIndex<64;i++){ Coeff[be_zig[CoeffIndex]]=0; CoeffIndex++; }
                if(CoeffIndex<64){
                    int q=QScale*QM[CoeffIndex]; int ci=be_sign_10_to_s16(V&0x3FF); int tmp;
                    if(q!=0) tmp=(int32_t)((uint32_t)((ci*q)>>3)<<4)+(ci?((ci<0)?8:-8):0);
                    else     tmp=(uint32_t)(ci*2)<<4;
                    Coeff[be_zig[CoeffIndex]]=be_min(0x3FFF,be_max(-0x4000,tmp)); CoeffIndex++;
                }
            }
        }
    }
}
static void be_yuv(int8_t y,int8_t cb,int8_t cr,int*r,int*g,int*b){
    *r=be_mask9(y+(((359*cr)+0x80)>>8));
    *g=be_mask9(y+((((-88*cb)&~0x1F)+((-183*cr)&~0x07)+0x80)>>8));
    *b=be_mask9(y+(((454*cb)+0x80)>>8));
    *r^=0x80; *g^=0x80; *b^=0x80;
}

/* ===================== diff ===================== */
int main(void){
    make_input();
    my_set_scale(); be_set_scale();

    /* scale matrix store */
    int sdiff=0; for(int i=0;i<64;i++) if(my_scale[i]!=be_idctmat[i]) sdiff++;
    printf("[scale matrix]   diffs: %d\n", sdiff);

    /* dequant */
    int16_t cmine[64], cbe[64];
    my_dequant(cmine, QUANT); be_dequant(cbe, QUANT);
    int ddiff=0; for(int i=0;i<64;i++) if(cmine[i]!=cbe[i]){ if(ddiff<8) printf("  Coeff[%2d] mine=%6d beetle=%6d\n",i,cmine[i],cbe[i]); ddiff++; }
    printf("[dequant Coeff]  diffs: %d\n", ddiff);

    /* idct */
    int16_t bmine[64], bbe[64];
    memcpy(bmine,cmine,sizeof(bmine)); my_idct(bmine);
    be_idct(cbe,bbe);
    int idiff=0; for(int i=0;i<64;i++) if(bmine[i]!=bbe[i]){ if(idiff<8) printf("  block[%2d] mine=%5d beetle=%5d\n",i,bmine[i],bbe[i]); idiff++; }
    printf("[idct block]     diffs: %d\n", idiff);

    /* yuv: sweep a few (y,cr,cb) */
    int ydiff=0;
    for(int y=-100;y<=100;y+=37) for(int cr=-100;cr<=100;cr+=37) for(int cb=-100;cb<=100;cb+=37){
        int r1,g1,b1,r2,g2,b2;
        my_yuv(y,cr,cb,&r1,&g1,&b1);
        be_yuv((int8_t)y,(int8_t)cb,(int8_t)cr,&r2,&g2,&b2);
        if(r1!=r2||g1!=g2||b1!=b2){ if(ydiff<8) printf("  yuv(y=%d cr=%d cb=%d) mine=(%d,%d,%d) beetle=(%d,%d,%d)\n",y,cr,cb,r1,g1,b1,r2,g2,b2); ydiff++; }
    }
    printf("[yuv->rgb]       diffs: %d\n", ydiff);

    printf("\n%s\n", (sdiff||ddiff||idiff||ydiff)?"*** DIVERGENCE FOUND ***":"ALL STAGES BYTE-EXACT");
    return 0;
}
