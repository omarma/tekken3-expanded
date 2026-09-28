/* mdec_e2e.c — FULL-PATH MDEC pin. Drives the REAL runtime/src/mdec.c end-to-end
 * through its public DMA/MMIO API (SET_QUANT, SET_SCALE, DECODE, read output) on a
 * synthetic 6-block colour macroblock, and diffs the packed 16bpp output against a
 * Beetle-faithful full pipeline (dequant + IDCT + EncodeImage assembly) at every
 * spatial pixel. Localizes integration bugs the isolated mdec_pin.c misses.
 *
 * Build (from runtime root): gcc -O2 -I runtime/include -o mdec_e2e tools/mdec_pin/mdec_e2e.c runtime/src/mdec.c
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "mdec.h"

uint64_t s_frame_count = 0;   /* mdec.c extern */

/* ---------------- synthetic input ---------------- */
static uint8_t QY[64], QC[64];
static uint16_t SCALEW[64];
static uint16_t BLK[6][24]; static int BLKN[6];

static void make_input(void){
    for(int i=0;i<64;i++) SCALEW[i]=(uint16_t)(0x1000 + (i*53%777) - 388);
    for(int i=0;i<64;i++){ QY[i]=(uint8_t)(2+(i%17)); QC[i]=(uint8_t)(3+(i%13)); }
    /* 6 distinct blocks, AGGRESSIVE: many ACs, large/saturating levels, a qscale=0
     * block, runs that reach high zig indices, EOB at varied points. */
    for(int b=0;b<6;b++){
        int n=0;
        int qs = (b==3) ? 0 : (8+b);                 /* block 3: qscale=0 path */
        BLK[b][n++]=(uint16_t)((qs<<10)|((400-37*b)&0x3FF));    /* DC, larger level */
        BLK[b][n++]=(uint16_t)((0u<<10)|((uint16_t)(-300+11*b)&0x3FF)); /* big neg */
        BLK[b][n++]=(uint16_t)((1u<<10)|((250-9*b)&0x3FF));
        BLK[b][n++]=(uint16_t)((0u<<10)|((uint16_t)(-120)&0x3FF));
        BLK[b][n++]=(uint16_t)((4u<<10)|((333+b)&0x3FF));       /* level >0x100 (10-bit) */
        BLK[b][n++]=(uint16_t)((2u<<10)|((uint16_t)(-77)&0x3FF));
        BLK[b][n++]=(uint16_t)((7u<<10)|((90)&0x3FF));
        BLK[b][n++]=(uint16_t)((11u<<10)|((uint16_t)(-200)&0x3FF)); /* high zig index */
        BLK[b][n++]=(uint16_t)((1u<<10)|((45)&0x3FF));
        BLK[b][n++]=0xFE00u;                                     /* end of block */
        BLKN[b]=n;
    }
}

/* ---------------- drive the REAL mdec.c ---------------- */
static uint8_t OUT[1024]; static int OUTN;
static void run_real(void){
    mdec_init();
    /* control: enable nothing special; we feed via port 0 directly */
    /* SET_QUANT (both tables): cmd (2<<29)|1, 64 halfwords = 128 bytes = 32 words */
    mdec_write(0, (2u<<29)|1u);
    uint8_t qbytes[128]; memcpy(qbytes,QY,64); memcpy(qbytes+64,QC,64);
    for(int i=0;i<128;i+=4){ uint32_t w=qbytes[i]|(qbytes[i+1]<<8)|(qbytes[i+2]<<16)|(qbytes[i+3]<<24); mdec_write(0,w); }
    /* SET_SCALE: cmd (3<<29), 64 halfwords = 32 words */
    mdec_write(0, (3u<<29));
    for(int i=0;i<64;i+=2){ uint32_t w=SCALEW[i]|((uint32_t)SCALEW[i+1]<<16); mdec_write(0,w); }
    /* DECODE 16bpp (depth=3): assemble all 6 blocks' halfwords, pad to even, frame as words */
    uint16_t hw[256]; int hn=0;
    for(int b=0;b<6;b++) for(int i=0;i<BLKN[b];i++) hw[hn++]=BLK[b][i];
    if(hn&1) hw[hn++]=0xFE00u;                 /* pad to even halfwords */
    int words=hn/2;
    mdec_write(0, (1u<<29)|(3u<<27)|(uint32_t)(words&0xFFFF));
    for(int i=0;i<hn;i+=2){ uint32_t w=hw[i]|((uint32_t)hw[i+1]<<16); mdec_write(0,w); }
    /* read output */
    MDECDebugState st; mdec_debug_get_state(&st);
    OUTN=(int)st.output_size; if(OUTN>1024)OUTN=1024;
    for(int i=0;i<OUTN;i+=4){ uint32_t v=mdec_dma_read_word(); OUT[i]=v&0xFF; if(i+1<OUTN)OUT[i+1]=(v>>8)&0xFF; if(i+2<OUTN)OUT[i+2]=(v>>16)&0xFF; if(i+3<OUTN)OUT[i+3]=(v>>24)&0xFF; }
}

/* ---------------- BEETLE-faithful reference (verbatim from mdec.cpp) ---------------- */
static const uint8_t bz[64]={
 0x00,0x08,0x01,0x02,0x09,0x10,0x18,0x11,0x0a,0x03,0x04,0x0b,0x12,0x19,0x20,0x28,
 0x21,0x1a,0x13,0x0c,0x05,0x06,0x0d,0x14,0x1b,0x22,0x29,0x30,0x38,0x31,0x2a,0x23,
 0x1c,0x15,0x0e,0x07,0x0f,0x16,0x1d,0x24,0x2b,0x32,0x39,0x3a,0x33,0x2c,0x25,0x1e,
 0x17,0x1f,0x26,0x2d,0x34,0x3b,0x3c,0x35,0x2e,0x27,0x2f,0x36,0x3d,0x3e,0x37,0x3f};
static int16_t bmat[64];
static int bsx(int bits,int v){int s=32-bits;return (int)(((int32_t)((uint32_t)v<<s))>>s);}
static int b10(int v){return (int16_t)bsx(10,v);}
static int bm9(int v){v=bsx(9,v);if(v<-128)v=-128;if(v>127)v=127;return v;}
static int bmin(int a,int b){return a<b?a:b;} static int bmax(int a,int b){return a>b?a:b;}
static void bset(void){for(int i=0;i<64;i++)bmat[((i&7)<<3)|((i>>3)&7)]=(int16_t)((int16_t)SCALEW[i]>>3);}
static void bdq(int16_t*C,const uint16_t*w,int n,const uint8_t*QM){
    memset(C,0,64*sizeof(int16_t)); int p=0,ci=0,qs=0;
    while(p<n){ uint16_t V=w[p++];
        if(ci==0){ if(V==0xFE00)continue; qs=V>>10; int q=QM[0],c=b10(V&0x3FF),t;
            if(q)t=(int32_t)((uint32_t)(c*q)<<4)+(c?((c<0)?8:-8):0); else t=(uint32_t)(c*2)<<4;
            C[bz[0]]=bmin(0x3FFF,bmax(-0x4000,t)); ci++;
        } else { if(V==0xFE00){ while(ci<64)C[bz[ci++]]=0; }
            else { uint32_t rl=V>>10; for(uint32_t i=0;i<rl&&ci<64;i++)C[bz[ci++]]=0;
                if(ci<64){ int q=qs*QM[ci],c=b10(V&0x3FF),t;
                    if(q)t=(int32_t)((uint32_t)((c*q)>>3)<<4)+(c?((c<0)?8:-8):0); else t=(uint32_t)(c*2)<<4;
                    C[bz[ci]]=bmin(0x3FFF,bmax(-0x4000,t)); ci++; } } } }
}
static void bidct(int16_t*in,int16_t*out){ int16_t t[64];
    for(int c=0;c<8;c++)for(int x=0;x<8;x++){int s=0;for(int u=0;u<8;u++)s+=in[c*8+u]*bmat[x*8+u];t[x*8+c]=(int16_t)((s+0x4000)>>15);}
    for(int c=0;c<8;c++)for(int x=0;x<8;x++){int s=0;for(int u=0;u<8;u++)s+=t[c*8+u]*bmat[x*8+u];out[c*8+x]=(int16_t)bm9((s+0x4000)>>15);} }
static void byuv(int8_t y,int8_t cb,int8_t cr,int*r,int*g,int*b){
    *r=bm9(y+(((359*cr)+0x80)>>8)); *g=bm9(y+((((-88*cb)&~0x1F)+((-183*cr)&~0x07)+0x80)>>8)); *b=bm9(y+(((454*cb)+0x80)>>8));
    *r^=0x80;*g^=0x80;*b^=0x80; }
/* Beetle RGB_to_RGB555 takes uint8 params -> the ^0x80 result truncates to 0..255
 * before the round/shift. (The earlier int-param version replicated mdec.c's bug,
 * so the pin falsely passed; uint8 makes it a true oracle.) */
static int b555(uint8_t c){int v=(c+4)>>3;if(v>0x1F)v=0x1F;return v;}

static uint16_t ref_px[256];
static void run_ref(void){
    bset();
    int16_t Cr[64],Cb[64],Y[4][64], cr8[64],cb8[64],y8[4][64];
    bdq(Cr,BLK[0],BLKN[0],QC); bidct(Cr,cr8);
    bdq(Cb,BLK[1],BLKN[1],QC); bidct(Cb,cb8);
    for(int k=0;k<4;k++){ bdq(Y[k],BLK[2+k],BLKN[2+k],QY); bidct(Y[k],y8[k]); }
    for(int py=0;py<16;py++)for(int px=0;px<16;px++){
        int ybn=(px>=8?1:0)+(py>=8?2:0); int x=px&7,y=py&7;
        int chroma=(py>>1)*8+(px>>1);
        int r,g,b; byuv((int8_t)y8[ybn][y*8+x],(int8_t)cb8[chroma],(int8_t)cr8[chroma],&r,&g,&b);
        ref_px[py*16+px]=(uint16_t)(b555(r)|(b555(g)<<5)|(b555(b)<<10)); /* signed=0,bit15=0 -> xor 0 */
    }
}

int main(void){
    make_input(); run_real(); run_ref();
    printf("real output bytes: %d (expect 512 for one 16x16 16bpp macroblock)\n", OUTN);
    int diffs=0, shown=0;
    for(int py=0;py<16;py++)for(int px=0;px<16;px++){
        int n=py*16+px; if(2*n+1>=OUTN) continue;
        uint16_t got = OUT[2*n] | (OUT[2*n+1]<<8);
        uint16_t exp = ref_px[n];
        if(got!=exp){ diffs++; if(shown<12){ printf("  px(%2d,%2d) real=0x%04X beetle=0x%04X\n",px,py,got,exp); shown++; } }
    }
    printf("[full-path 16bpp] pixel diffs: %d / 256\n", diffs);
    printf("\n%s\n", diffs?"*** INTEGRATION DIVERGENCE ***":"FULL PATH BYTE-EXACT vs BEETLE");
    return 0;
}
