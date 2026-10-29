/* Unknown's wolf spirit (F08, GH#42): the TTT1 model 114 drawn behind her in
 * every fight, as the arcade draws it on its final stage, with the light
 * effects around it.
 *
 * What the arcade does (TTT1, MAME 0.289 and its code, 2026-10-22):
 * - the wolf is a fifth fighter block (0x802A5878), set up by 0x801694A8
 *   (0x801294D8(block, 0x21, 7): Unknown's variant 7, model 114) when her
 *   team is Unknown alone (0x80169FF8, flag +0x3DD), at her root plus
 *   (0, -150, -500) turned by her angle;
 * - each frame (0x80169968 from 0x8010A970) it takes her 18 local bone
 *   rotations as they are (same pose, same frame) and her root rotation;
 *   its root trails hers (0x8016968C): target = her root + (0, -150, -800)
 *   turned by the wolf's own angle, x += d / 6, y and z += d / 8 (toward
 *   zero), angle += d / 32 (16-bit angles, sign-extended: no wrap), then a
 *   wobble of about 21 units from the sine table and the random generator;
 *   paused with the game (0x802435CC / 0x802435C0);
 * - it is drawn by the fighter renderer after her (0x8010D6D8), additive
 *   (all its pixels lighter than the floor under it, same frame with and
 *   without the flag);
 * - the effects (tools/ttt1/spirit.py), on the wolf's bones: A between its
 *   knees, bones 13 and 16, where its legs end (fading with the flag, a wisp
 *   W every 32 frames), B on each knee, C on bone 1 (the root), S on each
 *   knee. A Tekken 3 actor's bones come in the same order as the arcade
 *   block's (legs 12..14, 15..17). Here they are drawn whenever the
 *   wolf is; the arcade creates them on its stage 14 only, where the wolf
 *   always is.
 *
 * Here: a copy of Unknown's actor (src/tekken3_cine.c's 0x8003B4F8 wrapper
 * calls us once her draw is over), its parts wired to the wolf's rows
 * (Unknown-TTT1-wolf.3dm, read once) and its own packets, which read the
 * wolf's textures and the effects' images in the upper VRAM half
 * (Unknown-TTT1-wolf.glow, uploaded at each fight). The game solves its
 * skeleton (0x8003AFCC, pause flag set: our local matrices kept) and draws
 * its body (0x80037924, no shadow), outside emulated time; the engine writes
 * each packet's command, so the semi-transparent bit goes on afterwards.
 * Not in our cinematics (engine scenes, Ogre lifting the sub-boss, the
 * Embu). The upper half is made by the activation (before the renderer
 * starts) only when the pack is staged; a renderer without it (Vulkan)
 * draws no wolf. TEKKEN3_UNKNOWN_WOLF=0 turns it off; TEKKEN3_WOLF_TRACE=1
 * logs it. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "tekken3_host_clock.h"
#include "tekken3_ttt1_assets.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    ACTOR0=0x800a9228, ACTOR_SIZE=0x188c,
    SLOTS=0x4f0, SLOT_SIZE=40, PARTS=24,
    BONE_WORLD=0x908, BONE_SIZE=68,     /* a bone's world translation; its view one is +32 */
    ROOT=0xf54, LOCALS=0xf74, SHADOW=0x1274, FACING=0x2c, YAW=0x0e,
    MODELS=0x8009bd28,                  /* each player's model header */
    PART_ROW=0x8001a05c, PART_BONE=0x8001a074,
    PAUSE=0x80095468,                   /* the solver keeps the local matrices it is given */
    PAUSED=0x80095494,                  /* the pause menu */
    SKIP_DRAW=0x800adca4, SCREEN=0x800ae204, PHASE=0x800ae224,
    OT=0x800a8c54, BUFFER=0x800adefc,   /* 0 / 1, flipped once a drawn frame, in every arena */
    WORLD_VIEW=0x800adf70,              /* camera = R . world + T (src/tekken3_cine.c, sprites) */
    SOLVE=0x8003afcc, BODY=0x80037924,
    FRAME_CYCLES=564480,                /* a VBlank of emulated time (interrupts.h) */
    RETURN=0x80010000,                  /* never reached: the nested call stops there */
    ROWS=27, HEADER=24+ROWS*56,
    PACKETS=0x12000,                    /* a wolf's packets, both buffers (about 2 x 32 KB) */
    SPRITES=16, SPRITE=40,
    BAND_PAGE=10, CLUT_X=704,           /* tools/ttt1/spirit.py */
};
enum { SEQ_A, SEQ_B, SEQ_C, SEQ_W, SEQS };

static struct {
    int tried, ok, upper;
    unsigned char *model; uint32_t model_size, relocs[256]; unsigned reloc_count;
    unsigned char *pack; uint32_t pack_size;
    uint32_t memory;                    /* the model in guest memory */
    uint32_t gpu;                       /* both wolves' packets and sprites */
    uint16_t bones[3];                  /* the root and the two knees: 1, 13, 16 */
    struct { unsigned count; const unsigned char *frames; } seq[SEQS];
    int uploaded; uint64_t uploaded_at; /* the emulated clock at the last upload */
} pack;

typedef struct { int32_t x,y,z,vx,vy,vz,life; unsigned counter; int alive; } Wisp;
static struct {
    uint32_t actor;                     /* our copy of Unknown's actor, guest memory */
    uint32_t built_from;                /* her model header when wired */
    uint32_t start,next;                /* its packets */
    int32_t x,y,z; uint16_t angle;      /* the root, as the arcade's +0x53C and +2 */
    uint64_t last_drawn; unsigned last_buffer; uint32_t wobble;
    int live;                           /* drawn on the frame before */
    unsigned a_counter,a_spawn,b_counter[2],c_counter,s_counter[2]; int a_alpha;
    Wisp wisps[4];
} wolves[2];

static int tracing(void) {
    static int on=-1;
    if(on<0) on=getenv("TEKKEN3_WOLF_TRACE")!=NULL;
    return on;
}
static int wanted(void) {
    static int on=-1;
    if(on<0) { const char *e=getenv("TEKKEN3_UNKNOWN_WOLF"); on=!e || strcmp(e,"0"); }
    return on;
}
/* TEKKEN3_WOLF_GLOW=0: the wolf without its glow (the performance bench's breakdown). */
static int glowing(void) {
    static int on=-1;
    if(on<0) { const char *e=getenv("TEKKEN3_WOLF_GLOW"); on=!e || strcmp(e,"0"); }
    return on;
}

static unsigned char *read_file(const char *suffix,uint32_t *size) {
    const char *root=tekken3_ttt1_asset_root();
    char path[4096];
    if(!root || snprintf(path,sizeof path,"%s/Unknown-TTT1-%s",root,suffix)>=(int)sizeof path) return NULL;
    FILE *f=fopen(path,"rb");
    if(!f) return NULL;
    fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET);
    unsigned char *b=n>0 && n<4*1024*1024?malloc((size_t)n):NULL;
    if(b && fread(b,1,(size_t)n,f)!=(size_t)n) { free(b); b=NULL; }
    fclose(f);
    if(b) *size=(uint32_t)n;
    return b;
}
static uint32_t word(const unsigned char *p) { return p[0]|p[1]<<8|p[2]<<16|(uint32_t)p[3]<<24; }
static uint16_t half(const unsigned char *p) { return (uint16_t)(p[0]|p[1]<<8); }

/* The pack: 'GLOW', version, rectangles, sequences, 0, the three bones, the
 * rectangles, the sequences (tools/ttt1/spirit.py). Checked whole once. */
static int parse_pack(void) {
    const unsigned char *b=pack.pack,*end=b+pack.pack_size;
    if(pack.pack_size<18 || memcmp(b,"GLOW",4) || half(b+4)!=1 || half(b+8)!=SEQS) return 0;
    for(unsigned i=0;i<3;i++) pack.bones[i]=half(b+12+2*i);
    const unsigned char *p=b+18;
    for(unsigned r=0,n=half(b+6);r<n;r++) {
        if(p+8>end) return 0;
        unsigned x=half(p),y=half(p+2),w=half(p+4),h=half(p+6);
        if(y<512 || y+h>1024 || x+w>1024 || p+8+2u*w*h>end) return 0;
        p+=8+2u*w*h;
    }
    for(unsigned s=0;s<SEQS;s++) {
        if(p+2>end) return 0;
        pack.seq[s].count=half(p); pack.seq[s].frames=p+2;
        p+=2+8u*pack.seq[s].count;
        if(p>end || !pack.seq[s].count) return 0;
    }
    return 1;
}
static void upload_pack(void) {
    const unsigned char *p=pack.pack+18;
    for(unsigned r=0,n=half(pack.pack+6);r<n;r++) {
        unsigned x=half(p),y=half(p+2),w=half(p+4),h=half(p+6);
        uint16_t *pixels=malloc(2u*w*h);
        if(pixels) {
            memcpy(pixels,p+8,2u*w*h);
            psx_mod_gpu_high_vram_upload((int)x,(int)y,(int)w,(int)h,pixels);
            free(pixels);
        }
        p+=8+2u*w*h;
    }
}

/* The activation: the upper half, only for a staged pack (the renderer
 * compiles its upper-half shader only if the half exists when it starts). */
static void wolf_activate(void) {
    if(!wanted()) return;
    pack.pack=read_file("wolf.glow",&pack.pack_size);
    if(!pack.pack || !parse_pack()) {
        if(pack.pack) fprintf(stderr,"Unknown's wolf: Unknown-TTT1-wolf.glow unreadable, no wolf\n");
        free(pack.pack); pack.pack=NULL;
        return;
    }
    pack.upper=psx_mod_gpu_high_vram_enable();
    fprintf(stderr,"Unknown's wolf: %s\n",pack.upper?"pack read, upper VRAM half on":"no upper VRAM half, no wolf");
}

/* The model, in guest memory with its pointers moved; then the packet
 * memory, declared as a source of the upper half. Once. */
static int load(void) {
    if(pack.tried) return pack.ok;
    pack.tried=1;
    if(!pack.pack || !pack.upper || !psx_mod_gpu_high_vram_ready()) return 0;
    uint32_t n=0;
    unsigned char *relocs=read_file("wolf.relocs",&n);
    pack.model=read_file("wolf.3dm",&pack.model_size);
    if(!pack.model || !relocs || n%4 || n/4>sizeof pack.relocs/4 || pack.model_size<HEADER ||
       word(pack.model)!=ROWS || word(pack.model+8)!=0x4b4d4433 || word(pack.model+16)!=0x5f8) {
        fprintf(stderr,"Unknown's wolf: Unknown-TTT1-wolf.3dm / .relocs missing or not a converted model\n");
        free(relocs); return 0;
    }
    pack.reloc_count=n/4;
    for(unsigned i=0;i<pack.reloc_count;i++) {
        pack.relocs[i]=word(relocs+4*i);
        if(pack.relocs[i]%4 || pack.relocs[i]>pack.model_size-4 || word(pack.model+pack.relocs[i])>=pack.model_size) {
            free(relocs); return 0;
        }
    }
    free(relocs);
    pack.memory=psx_mod_alloc_guest_memory(pack.model_size,16);
    pack.gpu=psx_mod_alloc_gpu_dma_memory(2*PACKETS+2*2*SPRITES*SPRITE,16);
    for(unsigned p=0;p<2;p++) wolves[p].actor=psx_mod_alloc_guest_memory(ACTOR_SIZE,16);
    if(!pack.memory || !pack.gpu || !wolves[0].actor || !wolves[1].actor ||
       !psx_mod_gpu_high_vram_source(pack.gpu,2*PACKETS+2*2*SPRITES*SPRITE)) {
        fprintf(stderr,"Unknown's wolf: no memory left\n"); return 0;
    }
    for(uint32_t i=0;i<pack.model_size;i+=4) psx_mod_write_word(pack.memory+i,word(pack.model+i));
    for(unsigned i=0;i<pack.reloc_count;i++)
        psx_mod_write_word(pack.memory+pack.relocs[i],word(pack.model+pack.relocs[i])+pack.memory);
    psx_mod_write_word(pack.memory+16,pack.memory+0x5f8);     /* as the guests' header (player_tick) */
    fprintf(stderr,"Unknown's wolf: model %u B at %08X, packets at %08X, actors at %08X %08X\n",pack.model_size,
            pack.memory,pack.gpu,wolves[0].actor,wolves[1].actor);
    return pack.ok=1;
}

/* A mesh's packets, as tekken3_ttt1_mod.c's make_packets_native, reading the
 * wolf's band (page 10 of the upper half) through its palettes (x 704..,
 * y 512..), additive: texpage ABR 1 and the command's semi-transparent bit. */
static uint32_t make_packets(uint32_t bundle,uint32_t out,uint32_t end) {
    uint32_t m=psx_mod_read_word(bundle+16);
    uint32_t uv=m+psx_mod_read_half(m);
    uint32_t src=uv+psx_mod_read_half(uv);
    static const unsigned size[4]={32,40,40,52};
    static const unsigned opcode[4]={0x26,0x2e,0x36,0x3e};
    static const unsigned voff[4][4]={{12,20,28,0},{12,20,28,36},{12,24,36,0},{12,24,36,48}};
    for(unsigned kind=0;kind<4;kind++) {
        unsigned count=psx_mod_read_byte(src++),nv=(kind&1)?4:3;
        for(unsigned i=0;i<count;i++) {
            unsigned mat=psx_mod_read_half(m+2+psx_mod_read_byte(src++)*2);
            if(out+size[kind]>end) { src+=nv; continue; }
            for(unsigned j=0;j<size[kind];j+=4) psx_mod_write_word(out+j,0);
            psx_mod_write_word(out+4,(opcode[kind]<<24)|0x808080);
            if(kind>=2) {
                psx_mod_write_word(out+16,0x808080); psx_mod_write_word(out+28,0x808080);
                if(nv==4) psx_mod_write_word(out+40,0x808080);
            }
            unsigned tpage=BAND_PAGE|0x800|0x20|(mat&0x8000?0x80u:0u);
            unsigned clut=0x8000|((mat&0x7fff)+CLUT_X/16);
            for(unsigned j=0;j<nv;j++) {
                uint32_t v=psx_mod_read_half(uv+2+psx_mod_read_byte(src++)*2);
                if(j==0) v|=clut<<16;
                if(j==1) v|=tpage<<16;
                psx_mod_write_word(out+voff[kind][j],v);
            }
            out+=size[kind];
        }
    }
    return out;
}

static void copy_words(uint32_t to,uint32_t from,uint32_t bytes) {
    for(uint32_t i=0;i<bytes;i+=4) psx_mod_write_word(to+i,psx_mod_read_word(from+i));
}

/* Our copy of her actor, its parts on the wolf's rows: her pointers into
 * her actor and her model header moved to ours, the second meshes of parts
 * 1, 2 and 17 (rows 2, 4, 20) as the guests', no accessory (the wolf has
 * none), each bone's length from its row, and each mesh's packets twice
 * (both frame buffers). A part without primitives keeps an empty block, as
 * the guests' (rebuild_packets). */
static void build(unsigned p) {
    uint32_t src=ACTOR0+p*ACTOR_SIZE,a=wolves[p].actor,her=psx_mod_read_word(MODELS+p*4),base=pack.memory;
    copy_words(a,src,ACTOR_SIZE);
    for(uint32_t off=0;off<ACTOR_SIZE;off+=4) {
        uint32_t v=psx_mod_read_word(a+off);
        if(v>=src && v<src+ACTOR_SIZE) psx_mod_write_word(a+off,v-src+a);
        else if(v>=her && v<her+HEADER) psx_mod_write_word(a+off,v-her+base);
    }
    psx_mod_write_word(a+SHADOW,0);
    static const unsigned second[3][2]={{1,2},{2,4},{17,20}};
    for(unsigned k=0;k<3;k++) {
        uint32_t part=a+SLOTS+second[k][0]*SLOT_SIZE,r=base+24+second[k][1]*56;
        psx_mod_write_word(part+12,psx_mod_read_word(r+40) && psx_mod_read_word(r+4)?base+16+second[k][1]*56:0);
    }
    for(unsigned i=18;i<PARTS;i++) psx_mod_write_word(a+SLOTS+i*SLOT_SIZE,0);
    uint32_t start=pack.gpu+p*PACKETS,end=start+PACKETS,next=start;
    for(unsigned i=1;i<18;i++) {
        uint32_t part=a+SLOTS+i*SLOT_SIZE;
        unsigned row=psx_mod_read_byte(PART_ROW+i),bone=psx_mod_read_byte(PART_BONE+i);
        uint32_t pos=a+0xf88+bone*32;
        for(unsigned k=0;k<3;k++) psx_mod_write_word(pos+k*4,psx_mod_read_word(base+24+row*56+12+k*4));
        if(!psx_mod_read_word(part)) continue;
        psx_mod_write_word(part+8,base+16+row*56);
        unsigned produced=0;
        for(unsigned mesh=0;mesh<2;mesh++) {
            uint32_t bundle=psx_mod_read_word(part+8+mesh*4);
            for(unsigned frame=0;frame<2;frame++) {
                uint32_t before=next;
                if(bundle) next=make_packets(bundle,next,end);
                if(next!=before) produced++;
                psx_mod_write_word(part+24+mesh*8+frame*4,next==before?0:before);
            }
        }
        if(!produced) {
            for(unsigned frame=0;frame<2 && next+32<=end;frame++) {
                for(unsigned j=0;j<32;j+=4) psx_mod_write_word(next+j,0);
                psx_mod_write_word(part+24+frame*4,next);
                next+=32;
            }
        }
    }
    wolves[p].start=start; wolves[p].next=next; wolves[p].built_from=her;
    if(tracing()) fprintf(stderr,"Unknown's wolf: P%u wired, %u packet bytes, part 0 %08X\n",p+1,next-start,
                          psx_mod_read_word(a+SLOTS));
}

/* TTT1's sine table (0x8001B194): 4096 steps a turn, 4096 = 1. */
static int32_t tsin(unsigned i) { return (int32_t)lround(4096.0*sin(i*(6.283185307179586/4096.0))); }
static uint32_t seed=0x2545f491u;
static unsigned rnd(void) { seed=seed*1103515245u+12345u; return seed>>16&0x7fff; }
static int32_t div_trunc(int32_t a,int32_t b) { return a/b; }       /* toward zero, as the arcade */

static void root_of(uint32_t actor,int32_t r[3]) {
    for(unsigned k=0;k<3;k++) r[k]=(int32_t)psx_mod_read_word(actor+ROOT+0x14+k*4);
}
/* The trailing offset (0, -150, back) turned by a 16-bit angle: T3's facing
 * +0x2C points along (sin, cos) in x, z (tekken3_ttt1_combat.c, lasers). */
static void offset(uint16_t angle,int back,int32_t out[3]) {
    double a=angle*(6.283185307179586/65536.0);
    out[0]=(int32_t)lround(-sin(a)*back); out[1]=-150; out[2]=(int32_t)lround(-cos(a)*back);
}
/* 0x801694A8: the wolf comes out of her, 500 behind. */
static void place(unsigned p) {
    uint32_t her=ACTOR0+p*ACTOR_SIZE;
    int32_t r[3],o[3];
    root_of(her,r);
    wolves[p].angle=psx_mod_read_half(her+FACING);
    offset(wolves[p].angle,500,o);
    wolves[p].x=r[0]+o[0]; wolves[p].y=r[1]+o[1]; wolves[p].z=r[2]+o[2];
    wolves[p].wobble=0; wolves[p].a_counter=wolves[p].a_spawn=wolves[p].c_counter=0;
    wolves[p].b_counter[0]=0; wolves[p].b_counter[1]=0x16;      /* 0x8015BC38 */
    wolves[p].s_counter[0]=0; wolves[p].s_counter[1]=4;         /* 0x8015BF24 */
    wolves[p].a_alpha=0x80;
    memset(wolves[p].wisps,0,sizeof wolves[p].wisps);
}
/* One frame of 0x8016968C, and of the effects' counters. */
static void step(unsigned p) {
    uint32_t her=ACTOR0+p*ACTOR_SIZE;
    int32_t r[3],o[3];
    root_of(her,r);
    int32_t d=(int32_t)(int16_t)psx_mod_read_half(her+FACING)-(int32_t)(int16_t)wolves[p].angle;
    wolves[p].angle=(uint16_t)(wolves[p].angle+div_trunc(d,32));
    offset(wolves[p].angle,800,o);
    wolves[p].x+=div_trunc(r[0]+o[0]-wolves[p].x,6);
    wolves[p].y+=div_trunc(r[1]+o[1]-wolves[p].y,8);
    wolves[p].z+=div_trunc(r[2]+o[2]-wolves[p].z,8);
    wolves[p].wobble+=0x40;
    uint32_t v=wolves[p].wobble+(rnd()&0x3f);
    wolves[p].x+=div_trunc(div_trunc(tsin(((v>>1)&0xfff)+0x400),6),32);
    v=wolves[p].wobble+(rnd()&0x3f);
    wolves[p].y+=div_trunc(div_trunc(tsin(v&0xfff),6),32);
    v=wolves[p].wobble+(rnd()&0x3f);
    wolves[p].z+=div_trunc(div_trunc(tsin((v>>1)&0xfff),6),32);
    /* The effects: A 18 images of 2 frames (0x8015A31C), B 23 (0x8015A584),
     * C 18 (0x8015A8E8), S one a frame (0x8015AE94), a wisp from A every
     * 32 frames (0x8015A524). */
    if(++wolves[p].a_counter>=0x24) wolves[p].a_counter=0;
    for(unsigned i=0;i<2;i++) if(++wolves[p].b_counter[i]>=0x2e) wolves[p].b_counter[i]=0;
    if(++wolves[p].c_counter>=0x24) wolves[p].c_counter=0;
    for(unsigned i=0;i<2;i++) wolves[p].s_counter[i]++;
    uint32_t a=wolves[p].actor;
    int32_t ax=0,ay=0,az=0;
    for(unsigned k=0;k<2;k++) {
        uint32_t b=a+BONE_WORLD+pack.bones[1+k]*BONE_SIZE;
        ax+=(int32_t)psx_mod_read_word(b); ay+=(int32_t)psx_mod_read_word(b+4); az+=(int32_t)psx_mod_read_word(b+8);
    }
    ax>>=1; ay>>=1; az>>=1;
    for(unsigned i=0;i<4;i++) {
        Wisp *w=&wolves[p].wisps[i];
        if(!w->alive) continue;
        if(--w->life<0) { w->alive=0; continue; }
        /* 0x8015AC00: pulled back toward A, rising faster and faster. */
        w->vx+=w->x<ax?0x18000:-0x18000;
        w->vz+=w->z<az?0x18000:-0x18000;
        w->vy+=0x9000;
        w->x+=w->vx>>16; w->z+=w->vz>>16; w->y-=w->vy>>16;
        w->counter++;
    }
    if((++wolves[p].a_spawn&0x1f)==0) {
        for(unsigned i=0;i<4;i++) if(!wolves[p].wisps[i].alive) {
            Wisp *w=&wolves[p].wisps[i];
            /* 0x8015AAAC: around A, 0xF1 lower, a random sideways speed. */
            w->x=ax-0xff+(int32_t)(rnd()&0x1ff); w->y=ay+0xf1; w->z=az-0xff+(int32_t)(rnd()&0x1ff);
            w->vx=((int32_t)(rnd()&0x7fff)-0x3fff)<<7; w->vy=0; w->vz=((int32_t)(rnd()&0x7fff)-0x3fff)<<7;
            w->life=0x80; w->counter=0; w->alive=1;
            break;
        }
    }
}

/* A routine of the game, called from here; it returns into us. */
static void call(CPUState *cpu,uint32_t fn,uint32_t a0) {
    cpu->gpr[4]=a0; cpu->gpr[31]=RETURN; cpu->pc=0;
    psx_dispatch_call(cpu,fn,RETURN);
}

/* The view: camera = R . world + T, then the GTE's projection. */
typedef struct { int32_t r[9],t[3],ofx,ofy,h; } View;
static int project(const View *v,int32_t x,int32_t y,int32_t z,int32_t out[3]) {
    for(unsigned i=0;i<3;i++)
        out[i]=(int32_t)(((int64_t)v->r[i*3]*x+(int64_t)v->r[i*3+1]*y+(int64_t)v->r[i*3+2]*z)>>12)+v->t[i];
    return out[2]>64;
}
/* One billboard: corners (x0, y0)..(x1, y1) around a view point, image k of
 * sequence s, colour c, linked in the ordering table at its depth plus bias
 * (the arcade's effects: +0xE). */
static void sprite(const View *v,uint32_t ot,uint32_t *at,uint32_t end,const int32_t c[3],
                   int x0,int y0,int x1,int y1,unsigned s,unsigned k,unsigned colour,int bias) {
    if(*at+SPRITE>end || colour==0) return;
    const unsigned char *f=pack.seq[s].frames+8*(k%pack.seq[s].count);
    int32_t sx[2],sy[2];
    sx[0]=v->ofx+(int32_t)((int64_t)v->h*(c[0]+x0)/c[2]); sx[1]=v->ofx+(int32_t)((int64_t)v->h*(c[0]+x1)/c[2]);
    sy[0]=v->ofy+(int32_t)((int64_t)v->h*(c[1]+y0)/c[2]); sy[1]=v->ofy+(int32_t)((int64_t)v->h*(c[1]+y1)/c[2]);
    if(sx[1]<-1024 || sx[0]>1023 || sy[1]<-1024 || sy[0]>1023) return;
    int index=(c[2]>>5)+bias;
    if(index<1) index=1;
    if(index>1023) index=1023;
    uint32_t q=*at,u=f[0],w=f[1],du=f[2],dv=f[3];
    uint32_t xy[4]={(uint32_t)(sx[0]&0xffff)|(uint32_t)sy[0]<<16,(uint32_t)(sx[1]&0xffff)|(uint32_t)sy[0]<<16,
                    (uint32_t)(sx[0]&0xffff)|(uint32_t)sy[1]<<16,(uint32_t)(sx[1]&0xffff)|(uint32_t)sy[1]<<16};
    psx_mod_write_word(q+4,0x2e000000u|colour<<16|colour<<8|colour);
    psx_mod_write_word(q+8,xy[0]);  psx_mod_write_word(q+12,(uint32_t)half(f+6)<<16|w<<8|u);
    psx_mod_write_word(q+16,xy[1]); psx_mod_write_word(q+20,(uint32_t)half(f+4)<<16|w<<8|(u+du));
    psx_mod_write_word(q+24,xy[2]); psx_mod_write_word(q+28,(w+dv)<<8|u);
    psx_mod_write_word(q+32,xy[3]); psx_mod_write_word(q+36,(w+dv)<<8|(u+du));
    uint32_t slot=ot+(uint32_t)index*4,link=psx_mod_read_word(slot);
    psx_mod_write_word(q,9u<<24|(link&0xffffff));
    psx_mod_write_word(slot,(link&0xff000000u)|(q&0xffffff));
    *at+=SPRITE;
}
static void bone_view(const View *v,unsigned p,unsigned bone,int32_t c[3]) {
    uint32_t b=wolves[p].actor+BONE_WORLD+bone*BONE_SIZE;
    project(v,(int32_t)psx_mod_read_word(b),(int32_t)psx_mod_read_word(b+4),(int32_t)psx_mod_read_word(b+8),c);
}
static void effects(const CPUState *cpu,unsigned p) {
    View v;
    for(unsigned i=0;i<9;i++) v.r[i]=(int16_t)psx_mod_read_half(WORLD_VIEW+i*2);
    for(unsigned i=0;i<3;i++) v.t[i]=(int32_t)psx_mod_read_word(WORLD_VIEW+0x14+i*4);
    v.ofx=(int32_t)cpu->gte_ctrl[24]>>16; v.ofy=(int32_t)cpu->gte_ctrl[25]>>16; v.h=(int32_t)(cpu->gte_ctrl[26]&0xffff);
    uint32_t ot=psx_mod_read_word(psx_mod_read_word(OT)+4),buffer=psx_mod_read_word(BUFFER)&1;
    uint32_t at=pack.gpu+2*PACKETS+(p*2+buffer)*SPRITES*SPRITE,end=at+SPRITES*SPRITE;
    int32_t c[3];
    /* A: between the knees (0x8015A31C), 1034 x 896, bias -0x14. */
    int32_t m[3]={0,0,0};
    for(unsigned k=0;k<2;k++) {
        uint32_t b=wolves[p].actor+BONE_WORLD+pack.bones[1+k]*BONE_SIZE;
        for(unsigned i=0;i<3;i++) m[i]+=(int32_t)psx_mod_read_word(b+i*4);
    }
    if(project(&v,m[0]>>1,m[1]>>1,m[2]>>1,c))
        sprite(&v,ot,&at,end,c,-517,-448,517,448,SEQ_A,wolves[p].a_counter>>1,(unsigned)wolves[p].a_alpha,-0x14);
    /* B on each knee (0x8015A584), 930 x 930 from 724 above, bias -0xF. */
    for(unsigned k=0;k<2;k++) {
        bone_view(&v,p,pack.bones[1+k],c);
        if(c[2]>64) sprite(&v,ot,&at,end,c,-465,-724,465,206,SEQ_B,wolves[p].b_counter[k]>>1,0x80,-0xf);
    }
    /* C on the root, bone 1 (0x8015A8E8), 1724 x 1724, bias -0x1E. */
    bone_view(&v,p,pack.bones[0],c);
    if(c[2]>64) sprite(&v,ot,&at,end,c,-862,-862,862,862,SEQ_C,wolves[p].c_counter>>1,0x80,-0x1e);
    /* S on each knee (0x8015AE94): the wisps' images, one a frame, 758 x 688, bias -7. */
    for(unsigned k=0;k<2;k++) {
        bone_view(&v,p,pack.bones[1+k],c);
        if(c[2]>64) sprite(&v,ot,&at,end,c,-379,-344,379,344,SEQ_W,wolves[p].s_counter[k]&7,0x80,-7);
    }
    /* The wisps (0x8015AC00): an image every 4 frames, 412 x 412, fading, bias -0xA. */
    for(unsigned i=0;i<4;i++) {
        const Wisp *w=&wolves[p].wisps[i];
        if(w->alive && project(&v,w->x,w->y,w->z,c))
            sprite(&v,ot,&at,end,c,-206,-206,206,206,SEQ_W,(w->counter>>2)&7,(unsigned)w->life,-0xa);
    }
}

extern int tekken3_ttt1_guest_grafted(unsigned player);
extern int tekken3_cine_pending(void);
static int unknown(unsigned p) {
    const char *prefix=tekken3_guest_data_prefix_for(p);
    return prefix && !strncmp(prefix,"Unknown-",8) && tekken3_ttt1_guest_grafted(p);
}
/* For the other users of the upper half (Devil's and Angel's PS2 lasers):
 * whether rectangle x, y, w, h overlaps the wolf's pages (x 640..1023, y
 * 512..767, tools/ttt1/spirit.py) while Unknown is in the fight. */
int tekken3_ttt1_wolf_high_vram_used(int x,int y,int w,int h) {
    if(!wanted() || !pack.pack || !pack.upper || (!unknown(0) && !unknown(1))) return 0;
    return x<1024 && 640<x+w && y<768 && 512<y+h;
}
/* The fight's states: not the Embu (6) nor Ogre's cutscene (phases 16, 17:
 * Unknown lifted alone, the user's choice), nor any of our cinematics. */
static int fighting(void) {
    unsigned phase=psx_mod_read_half(PHASE);
    return psx_mod_read_word(SCREEN)==8 && phase!=16 && phase!=17 && !tekken3_cine_pending();
}

/* src/tekken3_cine.c's 0x8003B4F8 wrapper, once an actor is drawn. */
void tekken3_ttt1_wolf_after_actor(CPUState *cpu,uint32_t actor) {
    if(actor!=ACTOR0 && actor!=ACTOR0+ACTOR_SIZE) return;
    unsigned p=actor!=ACTOR0;
    if(!wanted() || !pack.pack || psx_mod_read_word(SKIP_DRAW) || !fighting() || !unknown(p) || !load()) {
        wolves[p].live=0; return;
    }
    /* Phases 2..4 set a round up (the fighters back on their marks): no
     * wolf; it comes out of her again when the round starts, as 0x801694A8
     * at each round, or after 8 frames she was not drawn. A step a game
     * frame, told by the OT buffer flipping: the frame counter 0x800A08F0
     * advances in the stage tiles' routine 0x8006D014 only, which the dark
     * arena (True Ogre's, 0x800AFAA0) never runs, and the wolf stayed where
     * it came out (B111). Gaps and uploads go by the emulated clock. */
    uint64_t now=psx_cycle_count;
    unsigned buffer=psx_mod_read_word(BUFFER)&1;
    if(psx_mod_read_half(PHASE)<6 || now-wolves[p].last_drawn>8*FRAME_CYCLES) wolves[p].live=0;
    if(psx_mod_read_half(PHASE)<6) return;
    if(!pack.uploaded || now-pack.uploaded_at>600*FRAME_CYCLES || !wolves[p].live) {
        upload_pack(); pack.uploaded=1; pack.uploaded_at=now;
    }
    if(wolves[p].built_from!=psx_mod_read_word(MODELS+p*4) || !wolves[p].live) build(p);
    int32_t r[3];
    root_of(actor,r);
    if(!wolves[p].live) { place(p); wolves[p].last_buffer=buffer; }
    unsigned steps=buffer!=wolves[p].last_buffer;
    wolves[p].last_buffer=buffer; wolves[p].last_drawn=now;
    if(psx_mod_read_word(PAUSED)) steps=0;
    wolves[p].live=1;

    uint64_t t0=tekken3_host_ns();
    /* Outside emulated time, as the cinematics' extra actors (TIPS): the
     * game's own routines on our actor, registers, GTE and scratchpad put
     * back, the clock where it was, no device serviced meanwhile. */
    psx_cyc_batch_flush();
    uint64_t cycles=psx_cycle_count;
    int service=psx_in_device_service;
    psx_in_device_service=1;
    CPUState saved=*cpu;
    uint32_t scratch[256];
    for(unsigned i=0;i<256;i++) scratch[i]=psx_mod_read_word(0x1f800000+i*4);
    uint32_t a=wolves[p].actor,pause=psx_mod_read_word(PAUSE);
    for(unsigned b=0;b<18;b++) for(unsigned k=0;k<9;k++)
        psx_mod_write_half(a+LOCALS+b*32+k*2,psx_mod_read_half(actor+LOCALS+b*32+k*2));
    for(unsigned k=0;k<9;k++) psx_mod_write_half(a+ROOT+k*2,psx_mod_read_half(actor+ROOT+k*2));
    psx_mod_write_word(a+ROOT+0x14,(uint32_t)wolves[p].x);
    psx_mod_write_word(a+ROOT+0x18,(uint32_t)wolves[p].y);
    psx_mod_write_word(a+ROOT+0x1c,(uint32_t)wolves[p].z);
    for(unsigned k=0;k<3;k++)
        psx_mod_write_word(a+k*4,psx_mod_read_word(actor+k*4)+(uint32_t)((k==0?wolves[p].x:k==1?wolves[p].y:wolves[p].z)-r[k]));
    psx_mod_write_half(a+FACING,wolves[p].angle);
    psx_mod_write_half(a+YAW,psx_mod_read_half(actor+YAW));
    psx_mod_write_word(PAUSE,1);
    call(cpu,SOLVE,a);
    if(tracing()) {
        static unsigned n;
        int worst=0; unsigned at=0;
        for(unsigned b=0;b<18;b++) for(unsigned k=0;k<9;k++) {
            int d=abs((int16_t)psx_mod_read_half(a+LOCALS+b*32+k*2)-(int16_t)psx_mod_read_half(actor+LOCALS+b*32+k*2));
            if(d>worst) { worst=d; at=b; }
        }
        if(!(n++%120)) fprintf(stderr,"Unknown's wolf: P%u pose after the solver, worst bone %u off by %d\n",p+1,at,worst);
    }
    call(cpu,BODY,a);
    psx_mod_write_word(PAUSE,pause);
    /* The engine wrote each drawn packet's command over ours: semi-transparent again. */
    static const unsigned size[4]={32,40,40,52};
    for(uint32_t q=wolves[p].start;q<wolves[p].next;) {
        uint32_t w=psx_mod_read_word(q+4);
        unsigned op=w>>24;
        if(op<0x24 || op>0x3f) { q+=32; continue; }                 /* an empty block */
        psx_mod_write_word(q+4,w|0x02000000u);
        q+=size[(op>>3)-4];
    }
    while(steps--) step(p);
    if(glowing()) effects(&saved,p);
    for(unsigned i=0;i<256;i++) psx_mod_write_word(0x1f800000+i*4,scratch[i]);
    *cpu=saved;
    psx_cyc_batch_flush();
    psx_cycle_count=cycles; psx_in_device_service=service;
    if(tracing()) {
        static unsigned n;
        static uint64_t spent;
        spent+=(tekken3_host_ns()-t0)/1000u;
        if(!(n++%120)) {
            fprintf(stderr,"Unknown's wolf: %.0f us a wolf a frame (host), phase %u\n",spent/120.0,psx_mod_read_half(PHASE));
            spent=0;
            uint32_t other=ACTOR0+(1-p)*ACTOR_SIZE;
            int32_t o[3]; root_of(other,o);
            double fx=(o[0]-r[0]),fz=(o[2]-r[2]),wx=wolves[p].x-r[0],wz=wolves[p].z-r[2];
            fprintf(stderr,"Unknown's wolf: P%u root %d %d %d, wolf %d %d %d, angle %04X / %04X, behind %.2f\n",p+1,
                    r[0],r[1],r[2],wolves[p].x,wolves[p].y,wolves[p].z,psx_mod_read_half(actor+FACING),wolves[p].angle,
                    (fx*wx+fz*wz)/(sqrt(fx*fx+fz*fz)*sqrt(wx*wx+wz*wz)+1e-9));
        }
    }
}

PSX_MOD_CONSTRUCTOR(register_ttt1_wolf) {
    (void)psx_mod_register_activation_plugin("tekken3.ttt1-characters",wolf_activate);
}
