/* Bounds checks for source-derived v4 combat records, before guest writes. */
#ifndef TEKKEN3_JUN_PACK_H
#define TEKKEN3_JUN_PACK_H
#include <stddef.h>
#include <stdint.h>
static uint32_t ttt1_pack_word(const unsigned char *p) {
    return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static unsigned ttt1_pack_half(const unsigned char *p) {return p[0]|(unsigned)p[1]<<8;}
static int ttt1_pack_target(unsigned id,unsigned count) {
    return id==3 || (id>=8192 && id-8192<count);
}
/* Hit limb marking a TTT1 laser (virtual limb 24): see __wrap_func_8006A3BC.
 * Unknown's glowing blade: TTT1 limbs 23 (mid-blade) and 22 (near its tip),
 * points of her hand bone 10 (blade_point in tekken3_ttt1_combat.c). */
enum { TTT1_PACK_BLADE_MID=0x3d, TTT1_PACK_BLADE_TIP=0x3e, TTT1_PACK_LASER_LIMB=0x3f };
static int ttt1_pack_validate(const unsigned char *p,size_t size) {
    if(size<32 || size>16*1024*1024 || ttt1_pack_word(p)!=0x314d554a ||
       ttt1_pack_word(p+4)!=4 || ttt1_pack_word(p+8)!=size)return 0;
    unsigned n=ttt1_pack_word(p+12),r=ttt1_pack_word(p+28),ro=ttt1_pack_word(p+20);
    /* Up to 2048 records: Unknown's King moveset has 1238. */
    if(!n || n>2048 || ttt1_pack_word(p+16)>=n || r!=32+n*16 ||
       r+n*56>size || ro<r+n*56 || ro>size ||
       ttt1_pack_word(p+24)!=4*n || 16*n+4>size-ro)return 0;
    unsigned po=ro+16*n,patterns=ttt1_pack_word(p+po);po+=4;
    if(patterns>1024)return 0;
    for(unsigned i=0;i<patterns;i++) {
        if(po>size-4)return 0;
        unsigned cmd=ttt1_pack_half(p+po),words=ttt1_pack_half(p+po+2);po+=4;
        if(cmd!=0xe000+i || words<3 || words>65 || words*2>size-po ||
           ttt1_pack_half(p+po)<1 || ttt1_pack_half(p+po)>60 ||
           ttt1_pack_half(p+po+(words-1)*2))return 0;
        po+=words*2;
    }
    if(po!=size)return 0;
    for(unsigned i=0;i<n;i++) {
        unsigned rp=r+i*56,cp=ttt1_pack_word(p+rp+12),clip=ttt1_pack_word(p+rp);
        unsigned nc=ttt1_pack_word(p+32+i*16+12);
        unsigned provenance=ttt1_pack_word(p+32+i*16+4);
        if(provenance<0x80010000 || provenance>=0x80400000 || ttt1_pack_word(p+32+i*16+8)!=rp ||
           ttt1_pack_word(p+ro+i*16)!=rp || ttt1_pack_word(p+ro+i*16+4)!=rp+12 ||
           ttt1_pack_word(p+ro+i*16+8)!=rp+28 || ttt1_pack_word(p+ro+i*16+12)!=rp+32 ||
           clip<r+n*56 || clip>ro-8 || (clip&3) ||
           (ttt1_pack_word(p+clip)&0xffffff00)!=0x4a554e00 ||
           ttt1_pack_word(p+clip+4)!=57 || !p[clip] || p[clip]*114u>ro-clip-8 ||
           cp<r+n*56 || cp>ro || (cp&3) || !nc || nc>4096 || nc*12>ro-cp ||
           !ttt1_pack_target(ttt1_pack_half(p+rp+16),n))return 0;
        unsigned sounds=ttt1_pack_word(p+rp+28),props=ttt1_pack_word(p+rp+32),j;
        if(sounds<r+n*56 || sounds>=ro || (sounds&3) || props<r+n*56 || props>=ro || (props&3))return 0;
        for(j=0;j<4;j++) {if(sounds+j*2>ro-2)return 0;if(ttt1_pack_half(p+sounds+j*2)==0xffff)break;}
        if(j==4)return 0;
        for(j=0;j<256;j++) {if(props+j*4>ro-4)return 0;if(!ttt1_pack_half(p+props+j*4))break;}
        if(j==256)return 0;
        /* Hit limbs are bone indices: 0..17 core, 18..23 guest accessory
         * bones; above, the laser and blade markers only. */
        for(unsigned j=0;j<4;j++)if(p[rp+40+j]>=24 && (p[rp+40+j]<TTT1_PACK_BLADE_MID || p[rp+40+j]>TTT1_PACK_LASER_LIMB))return 0;
        for(unsigned j=0;j<nc;j++) {
            const unsigned char *c=p+cp+j*12;
            unsigned cmd=ttt1_pack_half(c);
            if(!ttt1_pack_target(ttt1_pack_half(c+6),n) || c[2] || c[3]>=83 ||
               (cmd>=0x8000 && cmd!=0xc000 && cmd!=0xc001 && cmd!=0xc002 &&
                !(cmd>=0xe000 && cmd-0xe000<patterns)))return 0;
        }
        if(ttt1_pack_half(p+cp+(nc-1)*12)!=0xc000)return 0;
    }
    return 1;
}
#endif
