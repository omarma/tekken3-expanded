/* Source-derived solo combat adapter. See combat-report.json for coverage. */
#include "psx_runtime.h"
#include "mod_plugins.h"
#include "tekken3_ttt1_pack.h"
#include "tekken3_ttt1_assets.h"
#include "tekken3_fight_camera.h"
#include "gpu_render.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

extern unsigned tekken3_ttt1_motion_mode(void);
extern unsigned tekken3_ttt1_player_motion_mode(unsigned player);
extern int tekken3_devil_jin_player(unsigned player);
extern unsigned tekken3_native_moves_id(unsigned player);
extern int tekken3_ttt1_roster_enabled(void);
extern void tekken3_ttt1_face_tick(unsigned player,int advanced,int expression,unsigned duration,unsigned flag);
static uint32_t face_record[2];
static unsigned face_frame[2];
/* A player on TTT1 moves: a guest (mode 2) or a native fighter on its TTT1
 * moveset (mode 4, its own model and native key). */
static int ttt1_moves(unsigned player) {
    unsigned mode=tekken3_ttt1_player_motion_mode(player);
    return mode==2 || mode==4;
}
extern void __real_func_8002D178(CPUState *cpu);
extern void __real_func_80038B4C(CPUState *cpu);
extern void __real_func_800389C0(CPUState *cpu);
extern void __real_func_8002CC28(CPUState *cpu);
extern void __real_func_8002EE94(CPUState *cpu);
extern void __real_func_8002CD7C(CPUState *cpu);
extern void __real_func_80059890(CPUState *cpu);
extern void __real_func_8002C580(CPUState *cpu);
static unsigned char cpu_decided[2];
extern void __real_func_8006A3BC(CPUState *cpu);
extern void __real_func_8002D264(CPUState *cpu);
extern void __real_func_8002E8D0(CPUState *cpu);
extern void __real_func_8002E0BC(CPUState *cpu);
extern void __real_func_8002A914(CPUState *cpu);
extern void func_8002CA84(CPUState *cpu);
/* Each player's guest has its own slot: player 1's guest is slot 0, player
 * 2's slot 1, so the two can be different characters. Guest move IDs are
 * 8192+i for slot 0 and 8192+4096+i for slot 1: a move that animates the
 * other fighter (a throw's victim) still names its own graph. The reaction,
 * pushback and counter tables of both guests are merged into the one set the
 * engine reads (install_tables). */
enum { RECORDS_MAX=2048 };
/* T3's fire breath: True Ogre's ID, the effect limb of his breaths (records
 * 311, 366, 3962 of his own moves). */
enum { TRUE_OGRE=20, EFFECT_FIRE_LIMB=24 };
enum { SLOT_BASE=8192, SLOT_STRIDE=4096, ALIAS_ENTRIES=SLOT_BASE+2*SLOT_STRIDE,
       NATIVE_ROWS=633, NATIVE_PUSH=0xce8-0x75c, NATIVE_COUNTERS=(0x7c10-0x77dc)/4 };
typedef struct {uint16_t source,native;unsigned count;uint32_t clips[128];} ContactGroup;
typedef struct {
    unsigned generation;int attempted,loaded;
    unsigned char *data;uint32_t guest,size,count,records,neutral;
    /* Records of one pack: Unknown's King moveset has 1238 (Lei 1082,
     * Xiaoyu 1133); guest move IDs leave SLOT_STRIDE per slot. */
    uint32_t clip_addresses[RECORDS_MAX],clip_offsets[RECORDS_MAX];
    uint32_t patterns[1024];unsigned pattern_count;
    uint16_t native_aliases[4023];uint32_t source_aliases[5515];
    /* Guest record -> the first engine alias it stands for, plus one (0: a
     * move of the guest's own, such as a unique throw victim clip). */
    uint16_t recovery[SLOT_STRIDE];
    ContactGroup groups[64];unsigned group_count;
    struct {unsigned record,mask,alternate,normal;} dynamic_hits[64];unsigned dynamic_count;
    /* Fragment DYNC: cancel rules conditioned on the OPPONENT, written by
     * tools/ttt1/moves.py as (record u16, rule index u16, opponent u32). The
     * fragment is optional, emitted only when non-empty. The rules are read
     * and checked here, but their semantics is NOT applied yet. */
    struct {unsigned record,rule,opponent;} opponent_cancels[64];unsigned opponent_cancel_count;
    /* Fragment DEFR (optional): records the defender plays from this pack as
     * its own moves, the Jacks' haywire after a laser (SELF_MOVESET). */
    uint16_t defender_records[64];unsigned defender_count;
    /* The pack's tables, native parts included: nr rows of 42 bytes, np
     * pushback bytes, nc counters; and its event scripts (EVNT). */
    unsigned char *tables;unsigned nr,np,nc;
    unsigned char *events;unsigned event_bytes;
    unsigned char *hit_effect;unsigned hit_effect_frames;int hit_effect_attempted;
} GuestCombat;
static GuestCombat slots[2];
/* The pack a switch in the fight (Unknown) left: its guest memory is intact
 * in the player's other area until the next switch, and the fighter still
 * plays its stance, whose clips the engine keeps asking for (pose).
 * switching: SWITCH_TO retires the current pack into the other area;
 * SWITCH_UNDO (the new pack failed to load) drops the failed one and keeps
 * the retired pack the fighter still plays. */
enum { SWITCH_NONE, SWITCH_TO, SWITCH_UNDO };
static GuestCombat retired[2];static int switching[2];
static void free_combat(GuestCombat *c) {
    free(c->data);free(c->tables);free(c->events);free(c->hit_effect);
    memset(c,0,sizeof *c);
}
/* Unknown's hand bone that holds her blade (limb_position). */
enum { BLADE_BONE=10 };
typedef struct {
    uint32_t native_base,native_common,alias_table,original_alias,header,records,source,hit_bones;
    unsigned char *lasers;     /* beam type per record, 0 when not a laser */
    uint32_t *blades;          /* limbs of a record hitting with Unknown's blade, else 0 */
    /* What the records were built for: the slot's identity, its offsets in
     * the merged tables, and the other player's guest records. */
    unsigned generation,rx_shift,counter_shift,other_generation;uint32_t other_records;
} PlayerCombat;
static PlayerCombat players[2];
/* Where slot s's rows and counters start in the merged tables, beyond the
 * native ones: slot 1 follows slot 0's. */
static unsigned rx_shift[2],push_shift[2],counter_shift[2];
static uint32_t push_table=0x8001075c;
uint32_t tekken3_ttt1_push_base(void) {return push_table;}
static uint32_t word(const unsigned char *p) {
    return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static void put_half(unsigned char *p,unsigned v) {p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static unsigned slot_base(unsigned s) {return SLOT_BASE+s*SLOT_STRIDE;}
/* The player whose guest record this is, or -1. */
static int record_owner(uint32_t record) {
    for(unsigned p=0;p<2;p++)if(slots[p].loaded && players[p].records && record>=players[p].records &&
       record<players[p].records+slots[p].count*56 && (record-players[p].records)%56==0)return (int)p;
    return -1;
}
static int source_record(uint32_t record) {return record_owner(record)>=0;}
/* A player's moves changed: a new guest at the selector, or a moveset drawn at
 * round start (Tetsujin). Everything read from the files goes and reloads.
 * Mid-fight the engine's slot still names our header, in guest memory about
 * to be reused: hand it back its native header first. */
static void follow_identity(unsigned s) {
    unsigned generation=tekken3_guest_moves_generation(s);
    if(slots[s].generation==generation)return;
    GuestCombat *c=&slots[s];
    uint32_t engine_slot=0x800adc20+s*4;
    if(players[s].header && psx_mod_read_word(engine_slot)==players[s].header)
        psx_mod_write_word(engine_slot,players[s].native_base);
    free(players[s].lasers);free(players[s].blades);
    if(switching[s]==SWITCH_TO) {
        free_combat(&retired[s]);
        retired[s]=*c;memset(c,0,sizeof *c);
        tekken3_guest_pool_flip(s);
    } else {
        if(switching[s]!=SWITCH_UNDO)free_combat(&retired[s]);
        free_combat(c);
        tekken3_guest_pool_reset(s);
    }
    c->generation=generation;
    memset(&players[s],0,sizeof players[s]);
}
/* Condition 83 (tools/ttt1/moves.py SELF_MOVESET): the fighter playing the
 * record has TTT1 moveset param. Kept on the reaction to Devil and Angel's
 * lasers (TTT1 alias E23), which the defender plays from the shooter's pack:
 * the Jacks (Gun Jack 0x10, Jack-2 0x13, P.Jack 0x14) go haywire into the
 * Windmill Punch, the others take the plain stun. Keys as the hit rules
 * read them: a guest by its TTT1 moveset (key 23, Tetsujin / Unknown by
 * the one they drew), the natives' shared keys 0..18 are TTT1's (Gun Jack
 * 16 on either moveset). */
enum { SELF_MOVESET=83 };
static unsigned fighter_moveset(uint32_t actor) {
    int p=actor==0x800a9228?0:actor==0x800aaab4?1:-1;
    if(p<0)return 32;
    unsigned key=psx_mod_read_half(actor+0x16);
    return key==23?tekken3_guest_moveset((unsigned)p):key<=18?key:32;
}
int tekken3_ttt1_source_condition(uint32_t actor,unsigned kind) {
    /* Contact conditions 69..75 remain in the separate contact pass. */
    return kind>=76 && kind<=SELF_MOVESET && source_record(psx_mod_read_word(actor+0x54));
}
int tekken3_ttt1_source_transition(CPUState *cpu) {
    uint32_t actor=cpu->gpr[17];unsigned kind=cpu->gpr[3];
    if(kind<45 || kind>47 || !source_record(psx_mod_read_word(actor+0x1a4)))return 0;
    /* TTT 80100E24..80100EF4, called only after the native transition's
     * frame gate has committed. s2 retains the native root-refresh decision. */
    psx_mod_write_half(actor+0x58,1);psx_mod_write_half(actor+0x50,1);
    psx_mod_write_half(actor+0x74,0);
    psx_mod_write_word(actor+0x4c,psx_mod_read_word(actor+0x1a4));
    psx_mod_write_byte(actor+0xb9,kind==45?8:kind-34);
    if(kind==45)psx_mod_write_half(actor+0x2c,psx_mod_read_half(actor+0x2a));
    psx_mod_write_half(actor+0xe,psx_mod_read_half(actor+(kind==45?0x2a:0x34)));
    if(kind==45 || cpu->gpr[18]) {
        psx_mod_write_word(actor,psx_mod_read_word(actor+0xf68));
        psx_mod_write_word(actor+8,psx_mod_read_word(actor+0xf70));
    }
    return 1;
}
/* TTT's camera-plane axis (80113620: 0x400 - camera yaw, in 4096 units) as a
 * 16-bit facing. The PS1 camera yaw is an 18-bit angle, 0x40000 a turn
 * (80064810: atan << 6, masked 0x3FFFF; 80064E10 reads its sine at yaw >> 6);
 * taken as 16-bit, the axis drifted by three times the camera's turn and the
 * guest swung to the side on these moves as soon as the fight had rotated. */
static int camera_axis(void) {
    return (0x4000-((tekken3_fight_camera_yaw()&0x3ffff)>>2))&0xffff;
}
int tekken3_ttt1_source_rotation(uint32_t actor) {
    unsigned mode=psx_mod_read_byte(actor+0xb9);
    if((mode!=12 && mode!=13) || !source_record(psx_mod_read_word(actor+0x54)))return 0;
    /* TTT 80112E70 / 80112EA0: the camera-plane axis (+0x3C) or its
     * perpendicular (+0x3E), closest half-turn, eight-frame blend. */
    int axis=camera_axis();
    if(psx_mod_read_half(actor+0x12))axis+=0x8000;
    if(mode==13)axis=(int16_t)axis-0x4000;
    int facing=psx_mod_read_half(actor+0x2c);
    int delta=(int16_t)(facing-axis);
    unsigned distance=(uint16_t)(delta<0?65535-delta:delta);
    if(distance>=0x4000)axis+=0x8000;
    int frame=(int16_t)psx_mod_read_half(actor+0x5c);if(frame>8)frame=8;
    int step=(int16_t)(((int16_t)(axis-facing)*frame)/8);
    if(step>0x71c)step=0x71c;if(step< -0x71c)step= -0x71c;
    psx_mod_write_half(actor+0x2c,(uint16_t)(facing+step));
    psx_mod_write_half(actor+0xe,(uint16_t)(facing+step));
    return 1;
}
void __wrap_func_8002E0BC(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x8002e0bc) {
        unsigned kind=psx_mod_read_byte(cpu->gpr[4]+3),actor=cpu->gpr[5],match=0;
        if(kind>=76 && kind<=SELF_MOVESET && source_record(psx_mod_read_word(actor+0x54))) {
            int relative=(int16_t)psx_mod_read_half(actor+0x2e);
            if(kind==SELF_MOVESET)match=fighter_moveset(actor)==psx_mod_read_half(cpu->gpr[4]+4);
            else if(kind==76)match=(int16_t)psx_mod_read_half(actor+0x30)<=0x4000;
            else if(kind==77)match=relative<0;
            else if(kind==78)match=relative>=0;
            else {
                int axis=camera_axis();
                unsigned quarter=(uint16_t)(psx_mod_read_half(actor+0x2c)-axis+0x2000)/0x4000;
                static const unsigned wanted[4]={1,2,0,3};
                match=quarter==wanted[kind-79];
            }
            cpu->gpr[2]=match;cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_8002E0BC(cpu);
}
static void patch_base(uint32_t high_at,uint32_t low_at,unsigned reg,uint32_t target) {
    psx_mod_write_code_word(high_at,0x3c000000u|(reg<<16)|((target+0x8000)>>16));
    psx_mod_write_code_word(low_at,0x24000000u|(reg<<21)|(reg<<16)|(target&65535));
}
static int load_tables(unsigned s,const char *root) {
    GuestCombat *c=&slots[s];
    char path[4096];snprintf(path,sizeof path,"%s/%s-tables.jst",root,tekken3_guest_moves_prefix_for(s));
    FILE *f=fopen(path,"rb");if(!f)return 0;
    unsigned char h[32];if(fread(h,1,32,f)!=32){fclose(f);return 0;}
    uint32_t bytes=word(h+8),nr=word(h+12),np=word(h+16),nc=word(h+20);
    uint32_t fixed=nr*42+np+nc*4;
    if(word(h)!=0x3154534a || word(h+4)!=2 || nr<633 || nr>4096 ||
       np<1420 || np>65534 || (np&1) || nc<269 || nc>4096 ||
       bytes<32+fixed || bytes>1024*1024 || word(h+24) || word(h+28)){fclose(f);return 0;}
    unsigned char *p=malloc(bytes-32);if(!p){fclose(f);return 0;}
    int ok=fread(p,1,bytes-32,f)==bytes-32 && fgetc(f)==EOF;fclose(f);
    if(!ok){free(p);return 0;}
    unsigned chunks=0,event_offset=0,event_bytes=0;
    for(unsigned at=fixed;ok && at<bytes-32;) {
        if(bytes-32-at<8){ok=0;break;}
        unsigned type=word(p+at),n=word(p+at+4);at+=8;
        if(n>bytes-32-at){ok=0;break;}
        if(type==0x41494c41 && !(chunks&1) && n%4==0) {
            chunks|=1;
            for(unsigned i=0;i<n;i+=4) {
                unsigned a=ttt1_pack_half(p+at+i),b=ttt1_pack_half(p+at+i+2);
                if(a>=4023 || c->native_aliases[a] || !ttt1_pack_target(b,c->count)){ok=0;break;}
                c->native_aliases[a]=b;
                if(b>=SLOT_BASE && b-SLOT_BASE<SLOT_STRIDE && !c->recovery[b-SLOT_BASE])
                    c->recovery[b-SLOT_BASE]=(uint16_t)(a+1);
            }
        } else if(type==0x41435253 && !(chunks&2) && n==sizeof c->source_aliases) {
            chunks|=2;for(unsigned i=0;i<5515;i++)c->source_aliases[i]=word(p+at+i*4);
        } else if(type==0x50555247 && !(chunks&4)) {
            chunks|=4;
            for(unsigned i=0;i<n;) {
                if(n-i<8 || c->group_count>=64){ok=0;break;}
                ContactGroup *g=&c->groups[c->group_count++];
                g->source=ttt1_pack_half(p+at+i);g->native=ttt1_pack_half(p+at+i+2);
                g->count=word(p+at+i+4);i+=8;
                /* native 0xFFFF: TTT-only group, no stock counterpart. */
                if(g->count>128 || g->count*4>n-i || (g->native>=52 && g->native!=0xffff)){ok=0;break;}
                for(unsigned k=0;k<g->count;k++)g->clips[k]=word(p+at+i+k*4);
                i+=g->count*4;
            }
        } else if(type==0x544e5645 && !(chunks&8)) {
            chunks|=8;event_offset=at;event_bytes=n;
            for(unsigned i=0;i<n;) {
                if(n-i<8){ok=0;break;}
                unsigned id=word(p+at+i),ne=word(p+at+i+4);i+=8;
                if(id<1024 || id>=4096 || !ne || ne>256 || ne*4>n-i || word(p+at+i+(ne-1)*4)){ok=0;break;}
                unsigned prev=0;
                for(unsigned k=0;k+1<ne;k++) {
                    unsigned v=word(p+at+i+k*4),frame=v&4095;
                    if(!frame || frame<prev || ((v>>12)&15)>3)ok=0;prev=frame;
                }
                i+=ne*4;
            }
        } else if(type==0x484e5944 && !(chunks&16) && n%16==0 && n/16<=64) {
            chunks|=16;c->dynamic_count=n/16;
            for(unsigned i=0;i<c->dynamic_count;i++) {
                c->dynamic_hits[i].record=word(p+at+i*16);
                c->dynamic_hits[i].mask=word(p+at+i*16+4);
                c->dynamic_hits[i].alternate=word(p+at+i*16+8);
                c->dynamic_hits[i].normal=word(p+at+i*16+12);
                if(c->dynamic_hits[i].record>=c->count || (c->dynamic_hits[i].alternate&65535)>=nr || (c->dynamic_hits[i].normal&65535)>=nr)ok=0;
            }
        } else if(type==0x434e5944 && !(chunks&32) && n%8==0 && n/8<=64) {
            chunks|=32;c->opponent_cancel_count=n/8;
            for(unsigned i=0;i<c->opponent_cancel_count;i++) {
                c->opponent_cancels[i].record=ttt1_pack_half(p+at+i*8);
                c->opponent_cancels[i].rule=ttt1_pack_half(p+at+i*8+2);
                c->opponent_cancels[i].opponent=word(p+at+i*8+4);
                if(c->opponent_cancels[i].record>=c->count)ok=0;
            }
        } else if(type==0x52464544 && !(chunks&64) && n%2==0 && n/2<=64) {
            chunks|=64;c->defender_count=n/2;
            for(unsigned i=0;i<c->defender_count;i++) {
                c->defender_records[i]=(uint16_t)ttt1_pack_half(p+at+i*2);
                if(c->defender_records[i]>=c->count)ok=0;
            }
        } else ok=0;
        at+=n;
    }
    /* DYNC (bit 32) est facultatif : on n'exige que les cinq fragments
     * obligatoires, sinon les packs sans regle conditionnee seraient rejetes. */
    if((chunks&31)!=31)ok=0;
    for(unsigned i=633;ok && i<nr;i++) {
        for(unsigned k=0;k<14;k++)if(!ttt1_pack_target(ttt1_pack_half(p+i*42+k*2),c->count))ok=0;
        for(unsigned k=15;k<21;k+=2)if(ttt1_pack_half(p+i*42+k*2)*2+20>np)ok=0;
        if(ttt1_pack_half(p+i*42+40)*2+20>np)ok=0;
    }
    if(!ok){fprintf(stderr,"%s combat: tables rejected (fragments 0x%X)\n",tekken3_guest_name_for(s),chunks);free(p);return 0;}
    /* Slot 1's graph lives at 8192+4096: move its reaction rows' targets. */
    if(s)for(unsigned i=NATIVE_ROWS;i<nr;i++)for(unsigned k=0;k<14;k++) {
        unsigned t=ttt1_pack_half(p+i*42+k*2);
        if(t>=SLOT_BASE)put_half(p+i*42+k*2,t+s*SLOT_STRIDE);
    }
    c->events=event_bytes?malloc(event_bytes):NULL;
    if(event_bytes && !c->events){free(p);return 0;}
    if(event_bytes)memcpy(c->events,p+event_offset,event_bytes);
    c->event_bytes=event_bytes;
    c->tables=p;c->nr=nr;c->np=np;c->nc=nc;
    return 1;
}
static int load_combat(unsigned s) {
    follow_identity(s);
    GuestCombat *c=&slots[s];
    if(c->attempted)return c->loaded;c->attempted=1;
    const char *root=tekken3_ttt1_asset_root();if(!root)return 0;
    /* TEKKEN3_ENDING_PACKS (the TTT Cinematics feature): a folder of packs that
     * add an ending's clips to a guest's own, used in its place. */
    const char *packs=getenv("TEKKEN3_ENDING_PACKS");
    char path[4096];FILE *f=NULL;
    if(packs && *packs && snprintf(path,sizeof path,"%s/%s-combat.jmv",packs,tekken3_guest_moves_prefix_for(s))<(int)sizeof path &&
       (f=fopen(path,"rb")))fprintf(stderr,"%s combat: ending pack %s\n",tekken3_guest_name_for(s),path);
    if(!f)snprintf(path,sizeof path,"%s/%s-combat.jmv",root,tekken3_guest_moves_prefix_for(s));
    if(!f && !(f=fopen(path,"rb")))return 0;
    unsigned char header[32];
    if(fread(header,1,32,f)!=32 || word(header)!=0x314d554a || word(header+4)!=4){fclose(f);return 0;}
    c->size=word(header+8);c->count=word(header+12);c->neutral=word(header+16);c->records=word(header+28);
    uint32_t ro=word(header+20),rn=word(header+24);
    if(c->size>16*1024*1024 || c->count>RECORDS_MAX || !c->count || c->neutral>=c->count || c->records!=32+c->count*16 || c->records+c->count*56>c->size || ro>c->size || rn>(c->size-ro)/4){fclose(f);return 0;}
    c->data=(unsigned char*)malloc(c->size);if(!c->data){fclose(f);return 0;}
    memcpy(c->data,header,32);
    int ok=fread(c->data+32,1,c->size-32,f)==c->size-32 && fgetc(f)==EOF;fclose(f);
    for(unsigned i=0;ok && i<rn;i++) {
        uint32_t r=word(c->data+ro+i*4);
        if(r>c->size-4 || (r&3) || word(c->data+r)>=c->size)ok=0;
    }
    if(!ok || !ttt1_pack_validate(c->data,c->size)){
        fprintf(stderr,"%s combat: rejected invalid combat pack\n",tekken3_guest_name_for(s));
        free(c->data);c->data=NULL;return 0;
    }
    /* Slot 1's graph lives at 8192+4096: move each record's next move and
     * its cancel destinations, now that the pack has been checked. */
    if(s)for(unsigned i=0;i<c->count;i++) {
        uint32_t rp=c->records+i*56,cp=word(c->data+rp+12),n=word(c->data+32+i*16+12);
        if(ttt1_pack_half(c->data+rp+16)>=SLOT_BASE)put_half(c->data+rp+16,ttt1_pack_half(c->data+rp+16)+s*SLOT_STRIDE);
        for(unsigned j=0;j<n;j++) {
            unsigned char *e=c->data+cp+j*12+6;
            if(ttt1_pack_half(e)>=SLOT_BASE)put_half(e,ttt1_pack_half(e)+s*SLOT_STRIDE);
        }
    }
    /* Keep decoded motion in host memory; guest records point at compact
     * clip headers consumed by the decoder bridge. */
    uint32_t compact=c->records+c->count*56;
    for(unsigned i=0;i<c->count;i++) {
        uint32_t n=word(c->data+32+i*16+12);
        if(n>4096){free(c->data);c->data=NULL;return 0;}
        uint32_t rp=c->records+i*56;
        compact+=8+n*12+8;
        unsigned props=word(c->data+rp+32),j=0;
        do {compact+=4;} while(ttt1_pack_half(c->data+props+j++*4));
    }
    c->guest=tekken3_guest_pool_alloc(s,compact,16);
    if(!c->guest){fprintf(stderr,"%s combat: cannot allocate %u guest bytes\n",tekken3_guest_name_for(s),compact);return 0;}
    uint32_t cursor=c->records+c->count*56;
    for(unsigned i=0;i<cursor;i++)psx_mod_write_byte(c->guest+i,c->data[i]);
    for(unsigned i=0;i<c->count;i++) {
        uint32_t rp=c->records+i*56,cp=word(c->data+rp+12),n=word(c->data+32+i*16+12)*12;
        uint32_t clip=word(c->data+rp);
        if(cp>c->size || n>c->size-cp || clip>c->size-8)return 0;
        c->clip_addresses[i]=c->guest+cursor;c->clip_offsets[i]=clip;
        for(unsigned j=0;j<8;j++)psx_mod_write_byte(c->guest+cursor+j,c->data[clip+j]);
        psx_mod_write_word(c->guest+rp,c->guest+cursor);cursor+=8;
        psx_mod_write_word(c->guest+rp+12,c->guest+cursor);
        for(unsigned j=0;j<n;j++)psx_mod_write_byte(c->guest+cursor+j,c->data[cp+j]);
        cursor+=n;
        uint32_t sounds=word(c->data+rp+28),props=word(c->data+rp+32);
        psx_mod_write_word(c->guest+rp+28,c->guest+cursor);
        for(unsigned j=0;j<8;j++)psx_mod_write_byte(c->guest+cursor+j,j<6?c->data[sounds+j]:255);
        cursor+=8;
        psx_mod_write_word(c->guest+rp+32,c->guest+cursor);
        unsigned j=0;
        do {for(unsigned k=0;k<4;k++)psx_mod_write_byte(c->guest+cursor+k,c->data[props+j*4+k]);cursor+=4;}
        while(ttt1_pack_half(c->data+props+j++*4));
    }
    uint32_t po=ro+rn*4;
    if(po>c->size-4)return 0;
    c->pattern_count=word(c->data+po);po+=4;if(c->pattern_count>1024)return 0;
    for(unsigned i=0;i<c->pattern_count;i++) {
        if(po>c->size-4)return 0;
        unsigned command=c->data[po]|(unsigned)c->data[po+1]<<8,n=c->data[po+2]|(unsigned)c->data[po+3]<<8;po+=4;
        if(command!=0xe000+i || n<3 || n>65 || n*2>c->size-po)return 0;
        c->patterns[i]=tekken3_guest_pool_alloc(s,n*2,4);if(!c->patterns[i])return 0;
        for(unsigned j=0;j<n*2;j++)psx_mod_write_byte(c->patterns[i]+j,c->data[po+j]);po+=n*2;
    }
    if(!load_tables(s,root))return 0;
    fprintf(stderr,"%s combat: loaded %u source records and %u input sequences at %08X\n",tekken3_guest_name_for(s),c->count,c->pattern_count,c->guest);
    c->loaded=1;
    return 1;
}
/* The engine reads one reaction table, one pushback table, one counter table
 * and one event-script table. They hold the native entries followed by slot
 * 0's then slot 1's own, so slot 1's row, pushback and counter indices move
 * past slot 0's (rx_shift, push_shift, counter_shift); ready() applies them
 * to its records. Rebuilt whenever a slot is loaded or released. */
static uint32_t merged,merged_events;
enum { MERGED_BYTES=0x40000, EVENT_BYTES=0x20000 };
static void install_tables(void) {
    static unsigned installed[2]={~0u,~0u};
    unsigned key[2];
    for(unsigned s=0;s<2;s++)key[s]=slots[s].loaded && slots[s].tables?slots[s].generation:0;
    if(key[0]==installed[0] && key[1]==installed[1])return;
    const GuestCombat *first=key[0]?&slots[0]:key[1]?&slots[1]:NULL;
    if(!first)return;
    if(!merged && !(merged=psx_mod_alloc_guest_memory(MERGED_BYTES,16)))return;
    if(!merged_events && !(merged_events=psx_mod_alloc_guest_memory(EVENT_BYTES,16)))return;
    unsigned rows=NATIVE_ROWS,push=NATIVE_PUSH,counters=NATIVE_COUNTERS;
    for(unsigned s=0;s<2;s++) {
        rx_shift[s]=rows-NATIVE_ROWS;push_shift[s]=push-NATIVE_PUSH;counter_shift[s]=counters-NATIVE_COUNTERS;
        if(!key[s])continue;
        rows+=slots[s].nr-NATIVE_ROWS;push+=slots[s].np-NATIVE_PUSH;counters+=slots[s].nc-NATIVE_COUNTERS;
    }
    if(rows*42+push+counters*4>MERGED_BYTES){fprintf(stderr,"TTT1 characters: merged reaction tables too large\n");return;}
    uint32_t row_at=merged,push_base=merged+rows*42,counter_base=push_base+push;
    uint32_t push_at=push_base,counter_at=counter_base;
    const unsigned char *native=first->tables;
    for(unsigned i=0;i<NATIVE_ROWS*42;i++)psx_mod_write_byte(row_at++,native[i]);
    for(unsigned i=0;i<NATIVE_PUSH;i++)psx_mod_write_byte(push_at++,native[first->nr*42+i]);
    for(unsigned i=0;i<NATIVE_COUNTERS*4;i++)psx_mod_write_byte(counter_at++,native[first->nr*42+first->np+i]);
    for(unsigned s=0;s<2;s++) {
        if(!key[s])continue;
        const GuestCombat *c=&slots[s];
        const unsigned char *t=c->tables;
        for(unsigned i=NATIVE_ROWS;i<c->nr;i++)for(unsigned k=0;k<21;k++) {
            unsigned v=ttt1_pack_half(t+i*42+k*2);
            /* Halfwords 15, 17, 19, 20: pushback offsets, in halfwords. */
            if((k==15 || k==17 || k==19 || k==20) && v*2>=NATIVE_PUSH)v+=push_shift[s]/2;
            psx_mod_write_half(row_at,(uint16_t)v);row_at+=2;
        }
        for(unsigned i=NATIVE_PUSH;i<c->np;i++)psx_mod_write_byte(push_at++,t[c->nr*42+i]);
        for(unsigned i=NATIVE_COUNTERS;i<c->nc;i++) {
            unsigned rx=ttt1_pack_half(t+c->nr*42+c->np+i*4),threshold=ttt1_pack_half(t+c->nr*42+c->np+i*4+2);
            if(rx>=NATIVE_ROWS)rx+=rx_shift[s];
            psx_mod_write_half(counter_at,(uint16_t)rx);psx_mod_write_half(counter_at+2,(uint16_t)threshold);counter_at+=4;
        }
    }
    /* Event scripts: native IDs below 470, then each guest's by TTT1 script
     * ID (a shared ID names the same script, the first slot's is kept). */
    uint32_t cursor=merged_events+4096*4;
    psx_mod_write_word(cursor,0);
    for(unsigned i=0;i<4096;i++)psx_mod_write_word(merged_events+i*4,i<470?psx_mod_read_word(0x800971f8+i*4):cursor);
    cursor+=4;
    for(unsigned s=0;s<2;s++) {
        if(!key[s])continue;
        const unsigned char *e=slots[s].events;
        for(unsigned i=0;i<slots[s].event_bytes;) {
            unsigned id=word(e+i),ne=word(e+i+4);i+=8;
            if(psx_mod_read_word(merged_events+id*4)==merged_events+4096*4 &&
               cursor+ne*4<=merged_events+EVENT_BYTES) {
                psx_mod_write_word(merged_events+id*4,cursor);
                for(unsigned k=0;k<ne;k++)psx_mod_write_word(cursor+k*4,word(e+i+k*4));
                cursor+=ne*4;
            }
            i+=ne*4;
        }
    }
    patch_base(0x80041400,0x80041404,2,merged_events);
    patch_base(0x8002d7ac,0x8002d7b4,2,merged);
    patch_base(0x80044590,0x80044598,2,merged);
    patch_base(0x80044608,0x80044610,3,merged);
    patch_base(0x80044664,0x8004466c,2,merged);
    patch_base(0x800445c4,0x800445cc,2,counter_base);
    patch_base(0x80044ac0,0x80044ac4,3,counter_base);
    push_table=push_base;
    installed[0]=key[0];installed[1]=key[1];
    fprintf(stderr,"TTT1 characters: reaction tables merged: %u rows, %u pushback bytes, %u counters (%s%s%s)\n",
            rows,push,counters,key[0]?tekken3_guest_name_for(0):"",key[0]&&key[1]?" + ":"",key[1]?tekken3_guest_name_for(1):"");
}
/* Reaction destinations are engine entries even when the record sits in the
 * character's bank: being thrown by Paul plays a victim clip stored with Jin.
 * Keep the aliases named by the 633 native reaction rows (0x80010CE8) and by
 * the paired-reaction list (0x800174C4), and what they lead to (+16, and a
 * terminal cancel 0xC000), but never follow into an entry the guest already
 * plays itself: that would reach the donor's attacks. */
static void keep_native_reactions(const GuestCombat *c,uint32_t aliases,uint32_t missing,unsigned char keep[4023]) {
    static uint16_t pending[4023];unsigned head=0,tail=0;
    memset(keep,0,4023);
    for(unsigned i=0;i<NATIVE_ROWS;i++)for(unsigned k=0;k<14;k++) {
        unsigned alias=psx_mod_read_half(0x80010ce8+i*42+k*2);
        if(alias<4023 && !keep[alias]){keep[alias]=1;pending[tail++]=(uint16_t)alias;}
    }
    for(uint32_t at=0x800174c4;at<0x800177dc;at+=2) {
        unsigned alias=psx_mod_read_half(at);
        if(alias<4023 && !keep[alias]){keep[alias]=1;pending[tail++]=(uint16_t)alias;}
    }
    while(head<tail) {
        unsigned alias=pending[head++];
        if(c->native_aliases[alias])continue;
        uint32_t record=psx_mod_read_word(aliases+alias*4);
        if(record==missing || record<0x80010000 || record>0x801fffc8)continue;
        unsigned next=psx_mod_read_half(record+16);
        if(next<4023 && !keep[next]){keep[next]=1;pending[tail++]=(uint16_t)next;}
        uint32_t cancel=psx_mod_read_word(record+12);
        for(unsigned i=0;i<1024 && cancel>=0x80010000 && cancel<=0x801ffff4;i++,cancel+=12) {
            unsigned command=psx_mod_read_half(cancel);
            if(command==0xc00d)break;          /* end of a shared cancel subroutine */
            if(command!=0xc000)continue;
            next=psx_mod_read_half(cancel+6);
            if(next<4023 && !keep[next]){keep[next]=1;pending[tail++]=(uint16_t)next;}
            break;
        }
    }
}
static int ready(unsigned player) {
    /* Diagnostic ponctuel sous TEKKEN3_GUEST_WHY=1 : dire QUELLE garde bloque.
     * load_combat() a plusieurs sorties muettes. */
    if(getenv("TEKKEN3_GUEST_WHY")) {
        static int said[2];
        if(!said[player]) {
            unsigned mode=tekken3_ttt1_player_motion_mode(player);
            int lc=load_combat(player);
            uint32_t slot=0x800adc20+player*4,base=psx_mod_read_word(slot);
            said[player]=1;
            fprintf(stderr,"%s combat WHY P%u: motion_mode=%u load_combat=%d "
                    "slot=%08X base=%08X mot0=%08X\n",
                    tekken3_guest_name_for(player),player+1,mode,lc,slot,base,base?psx_mod_read_word(base):0);
        }
    }
    if(player>1 || !ttt1_moves(player) || !load_combat(player))return 0;
    install_tables();
    GuestCombat *c=&slots[player];
    PlayerCombat *p=&players[player];
    const unsigned other=1-player;
    uint32_t other_records=slots[other].loaded?players[other].records:0;
    uint32_t slot=0x800adc20+player*4,base=psx_mod_read_word(slot);
    if(base==p->header)base=p->native_base;
    /* A move header: 1, then its key - Jin's 9 under a guest, the native's
     * own (0..18) under a native on its TTT1 moves. */
    unsigned header=base>=0x80010000 && base<=0x801f0000?psx_mod_read_word(base)&0xffff:0;
    if((header&255)!=1 || (tekken3_ttt1_player_motion_mode(player)==4?header>>8>18:header>>8!=9))return 0;
    uint32_t common=psx_mod_read_word(0x800adc28);
    if(base!=p->native_base || psx_mod_read_word(slot)!=p->header || common!=p->native_common ||
       psx_mod_read_word(base+8)!=p->source || psx_mod_read_word(base+12)!=p->original_alias ||
       p->generation!=c->generation || p->rx_shift!=rx_shift[player] ||
       p->counter_shift!=counter_shift[player] || p->other_records!=other_records ||
       p->other_generation!=slots[other].generation) {
        uint32_t source=psx_mod_read_word(base+8);
        p->original_alias=psx_mod_read_word(base+12);
        if(!p->alias_table)p->alias_table=tekken3_guest_pool_alloc(player,ALIAS_ENTRIES*4,16);
        if(!p->header)p->header=tekken3_guest_pool_alloc(player,64,16);
        if(!p->records)p->records=tekken3_guest_pool_alloc(player,c->count*56,16);
        if(!p->hit_bones)p->hit_bones=tekken3_guest_pool_alloc(player,c->count*8,16);
        if(!p->alias_table || !p->header || !p->records || !p->hit_bones)return 0;
        for(unsigned i=0;i<64;i+=4)psx_mod_write_word(p->header+i,psx_mod_read_word(base+i));
        uint32_t idle=p->records+c->neutral*56;
        unsigned native_count=psx_mod_read_word(base)>>16;
        static unsigned char keep[4023];
        keep_native_reactions(c,p->original_alias,source-56,keep);
        for(unsigned i=0;i<ALIAS_ENTRIES;i++)psx_mod_write_word(p->alias_table+i*4,idle);
        for(unsigned i=0;i<4023;i++) {
            uint32_t original=psx_mod_read_word(p->original_alias+i*4);
            /* Shared engine reactions remain available, and so do the
             * reactions stored in the Jin cache. Its other moves (attacks)
             * must never animate the guest. */
            if(original>=source && original<source+native_count*56 && !keep[i])continue;
            if(original==source-56)continue; /* native missing-alias record */
            psx_mod_write_word(p->alias_table+i*4,original);
        }
        for(unsigned i=0;i<c->count;i++) {
            uint32_t dst=p->records+i*56;
            for(unsigned j=0;j<56;j+=4)psx_mod_write_word(dst+j,psx_mod_read_word(c->guest+c->records+i*56+j));
            /* Reaction row (high half of +48) and counter index (+52) in the
             * merged tables. */
            uint32_t reaction=psx_mod_read_word(dst+48);
            if((reaction>>16)>=NATIVE_ROWS)reaction+=rx_shift[player]<<16;
            psx_mod_write_word(dst+48,reaction);
            uint32_t counter=psx_mod_read_word(dst+52);
            if(counter>=NATIVE_COUNTERS)psx_mod_write_word(dst+52,counter+counter_shift[player]);
            uint32_t limbs=word(c->data+c->records+i*56+40);
            if(!p->lasers)p->lasers=calloc(c->count,1);
            /* A first limb of 24 or more sends T3's hit test (80047BBC) to
             * the effect-object capsules used by True Ogre's fire breath,
             * so the laser's actor capsule would never be tested. Keep the
             * beam type aside and give the engine an ordinary limb: the
             * sweep wrapper replaces its capsule with the beam anyway. */
            /* True Ogre on his TTT1 moves: TTT1 breathes his fire through
             * the laser's virtual limb 24, T3 through its own effect limb 24
             * (0x8006F0F4 each active frame, then the effect-object capsules):
             * the engine's flames, their hit and sound, on his T3 model. */
            int fire=(limbs&255)==TTT1_PACK_LASER_LIMB && tekken3_native_moves_id(player)==TRUE_OGRE;
            if(p->lasers)p->lasers[i]=(limbs&255)==TTT1_PACK_LASER_LIMB && !fire?(limbs>>8&255)|0x80:0;
            if(fire)limbs=(limbs&~0xffffu)|EFFECT_FIRE_LIMB;
            else if((limbs&255)==TTT1_PACK_LASER_LIMB)limbs=(limbs&~255u)|17;
            /* Blade points: kept aside for the capsules, the hand for the
             * engine (the same reason as the laser). */
            if(!p->blades)p->blades=calloc(c->count,4);
            int blade=0;
            for(unsigned k=0;k<4;k++) {
                unsigned b=limbs>>(8*k)&255;
                if(b==TTT1_PACK_BLADE_MID || b==TTT1_PACK_BLADE_TIP){blade=1;limbs=(limbs&~(255u<<(8*k)))|BLADE_BONE<<(8*k);}
            }
            if(p->blades)p->blades[i]=blade?word(c->data+c->records+i*56+40):0;
            psx_mod_write_word(p->hit_bones+i*8,limbs);
            psx_mod_write_word(p->hit_bones+i*8+4,0);
            psx_mod_write_word(dst+40,p->hit_bones+i*8);
            psx_mod_write_word(p->alias_table+(slot_base(player)+i)*4,dst);
        }
        /* The other player's guest moves too, for the reactions it plays on
         * this fighter (a throw's victim). */
        if(other_records)for(unsigned i=0;i<slots[other].count;i++)
            psx_mod_write_word(p->alias_table+(slot_base(other)+i)*4,other_records+i*56);
        psx_mod_write_word(p->alias_table+3*4,p->records+c->neutral*56);
        for(unsigned i=0;i<4023;i++)if(c->native_aliases[i]) {
            unsigned index=c->native_aliases[i]==3?c->neutral:c->native_aliases[i]-SLOT_BASE;
            psx_mod_write_word(p->alias_table+i*4,p->records+index*56);
        }
        psx_mod_write_word(p->header+12,p->alias_table);
        /* A guest's moves go by key 23; a native on its TTT1 moves and Devil
         * Jin keep their own key, which the other fighter's rules test. */
        if(tekken3_ttt1_roster_enabled() && tekken3_ttt1_player_motion_mode(player)==2 &&
           !tekken3_devil_jin_player(player))psx_mod_write_byte(p->header+1,23);
        /* Native cache headers may be shared by two actors. Keep them intact. */
        psx_mod_write_word(slot,p->header);
        p->native_base=base;p->native_common=common;p->source=source;
        p->generation=c->generation;p->rx_shift=rx_shift[player];p->counter_shift=counter_shift[player];
        p->other_records=other_records;p->other_generation=slots[other].generation;
        fprintf(stderr,"%s combat: installed P%u alias table, original=%08X custom=%08X records=%08X\n",
                tekken3_guest_name_for(player),player+1,p->original_alias,p->alias_table,p->records);
    }
    unsigned opponent=psx_mod_read_half(0x800a9228+other*0x188c+0x16);
    /* The shared T3 move keys are 0..18; a guest opponent (native key 23)
     * has its own TTT1 key. Console-only fighters have no arcade key.
     * Panda/Tiger use their existing shared move headers, just as the native
     * hit resolver does. */
    unsigned source_key=opponent==23?tekken3_guest_moveset(other):opponent<=18?opponent:32;
    for(unsigned i=0;i<c->dynamic_count;i++) {
        uint32_t address=p->records+c->dynamic_hits[i].record*56+48;
        unsigned row=source_key<32 && (c->dynamic_hits[i].mask&(1u<<source_key))?
                    c->dynamic_hits[i].alternate:c->dynamic_hits[i].normal;
        /* Low half: reaction row. High half: damage + 1 when it depends on
         * the opponent too (0 in older packs: the record keeps its own). */
        unsigned rx=row&65535,damage=row>>16;
        if(rx>=NATIVE_ROWS)rx+=rx_shift[player];
        psx_mod_write_word(address,(psx_mod_read_word(address)&65535)|(rx<<16));
        if(damage)psx_mod_write_half(address-48+20,damage-1);
    }
    return 1;
}
/* Round start (0x8002A914), where T3 draws Mokujin's moveset (0x8002AA54).
 * A guest with donors (Tetsujin) draws one here, and its moves are rebuilt
 * before the routine puts the fighters back in their stance. Only on entry:
 * a sliced call resumes through this wrapper with pc at the resume point. */
void __wrap_func_8002A914(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8002a914) && tekken3_ttt1_roster_enabled())
        for(unsigned p=0;p<2;p++)if(tekken3_guest_draw_moveset(p))ready(p);
    __real_func_8002A914(cpu);
}
void __wrap_func_8002D264(CPUState *cpu) {
    unsigned param=(uint16_t)cpu->gpr[5];
    if((cpu->pc==0 || cpu->pc==0x8002d264) && (slots[0].loaded || slots[1].loaded) && (param&0x4000)) {
        /* Contact groups are TTT1's global motion lists: the same source ID
         * names the same group in every guest's pack. */
        const ContactGroup *g=NULL;
        for(unsigned s=0;s<2 && !g;s++)if(slots[s].loaded)
            for(unsigned i=0;i<slots[s].group_count;i++)if(slots[s].groups[i].source==(param&0x3fff))g=&slots[s].groups[i];
        if(g) {
            for(unsigned s=0;s<2;s++)if(slots[s].loaded)for(unsigned i=0;i<slots[s].count;i++)
                if(slots[s].clip_addresses[i]==cpu->gpr[4]) {
                    unsigned clip=word(slots[s].data+32+i*16),match=0;
                    for(unsigned k=0;k<g->count;k++)if(g->clips[k]==clip)match=1;
                    cpu->gpr[2]=match;cpu->pc=cpu->gpr[31];return;
                }
            if(g->native==0xffff){cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;}
            cpu->gpr[5]=g->native;
        } else {cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;}
    }
    __real_func_8002D264(cpu);
}
void __wrap_func_8002E8D0(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8002e8d0) && (slots[0].loaded || slots[1].loaded) &&
       psx_mod_read_byte(cpu->gpr[4]+3)==74 && (psx_mod_read_half(cpu->gpr[4]+4)&0x8000)) {
        unsigned alias=psx_mod_read_half(cpu->gpr[4]+4)&0x7fff,match=0;
        uint32_t defender=cpu->gpr[5],attacker=cpu->gpr[6],record=psx_mod_read_word(attacker+0x54);
        int owner=record_owner(record);
        if(owner>=0) {
            unsigned i=(record-players[owner].records)/56;
            match=alias<5515 && slots[owner].source_aliases[alias]==word(slots[owner].data+36+i*16);
        }
        unsigned native=alias==0x125?0xf7:alias==0x45a?0x351:alias==0x47f?0x36f:alias==0xb56?0x85d:0xffff;
        if(native!=0xffff && psx_mod_read_half(attacker+0xa0)==native)match=1;
        match=match && (int16_t)psx_mod_read_half(defender+0x30)<0x2aaa &&
                       (int16_t)psx_mod_read_half(attacker+0x30)<0x2aaa;
        cpu->gpr[2]=match;cpu->pc=cpu->gpr[31];return;
    }
    __real_func_8002E8D0(cpu);
}
/* TTT1 lasers (Devil / Angel). Their hit ends on a virtual limb 24 that the
 * arcade's laser routine (80116F8C / 8011707C) places at the tip of a beam:
 * it starts at the head plus an offset and grows every frame from the third
 * frame of the move's active window, then slides along the floor (the tip
 * stops at y = 0, 801171A8). The arcade picks the beam by move ID
 * (80116C1C) and builds it in the fighter's yaw alone (+0x28, recomputed
 * every frame), with no bone matrix: T3's facing +0x2C is the same angle
 * (forward = sin, cos, as 8002A224 measures the angle to the opponent).
 * Offsets and steps measured in MAME (tools/data/ttt1_lasers.json), and
 * found again in the arcade routines. */
static const struct { int16_t fwd,up,step_fwd,step_down; } laser_beams[]={
    {0,0,0,0},
    {-49,170,199,0},      /* 1 Inferno (1+2): 0x1448, 80117544, 200 a frame */
    {99,160,101,110},     /* 2 Devil Blaster (3+4): 0x1449, 801177F8, 102 / 110 */
    /* 3 Reverse Devil Blaster (3+4, 3+4): 0x144B, the Blaster's routine. The
     * arcade's yaw is still the one before the flight over the opponent:
     * the beam goes back towards him while the model faces away. */
    {99,160,101,110},
    {40,170,290,-78},     /* 4 Air Inferno (u+1+2): 80117DD0, 300 a frame at 15 degrees up */
    /* 5 Sky sweep (clip 0xAE0088, 0x1292 / 0x1294): 80117AC0. Straight up
     * by 200 a frame for 8 frames, then the tip swings round the yaw by
     * 0x200 a frame between about +-0x3000, at a random length (0..1023)
     * on each horizontal axis. */
    {-140,160,0,-200},
};
/* Per player: the move the beam belongs to, its facing when it started
 * (the Reverse Blaster's), and the sky sweep's state, stepped once a frame. */
#define LASER_TURN (6.283185307179586/65536)  /* radians per unit of a 16-bit angle */
static struct { uint32_t record; int frame; uint16_t facing; int sweep,turning; uint32_t seed; int32_t dx,dz; } beams[2];
/* Beam ends in world space, v[0..2] start and v[3..5] tip; returns the
 * number of frames the beam has grown (0 before it appears). */
static int laser_ends(uint32_t actor,uint32_t record,unsigned type,int32_t v[6]) {
    if(!type || type>=sizeof laser_beams/sizeof *laser_beams)type=1;
    uint32_t head=actor+0x908+2*68;
    int32_t hx=(int32_t)psx_mod_read_word(head),hy=(int32_t)psx_mod_read_word(head+4),hz=(int32_t)psx_mod_read_word(head+8);
    int frame=(int)psx_mod_read_half(actor+0x58),first=psx_mod_read_byte(record+45)+3;
    int n=frame-first;if(n<0)n=0;
    unsigned p=actor!=0x800a9228;
    uint16_t facing=psx_mod_read_half(actor+0x2c);
    if(beams[p].record!=record || frame<beams[p].frame) {
        beams[p].record=record;beams[p].facing=facing;beams[p].sweep=0;beams[p].turning=0;
        beams[p].dx=beams[p].dz=0;beams[p].seed=0x5eed+p;beams[p].frame=-1;
    }
    /* The arcade's yaw does not move during the move; T3 keeps turning the
     * fighter to the opponent, and a beam on that facing followed whoever
     * side-stepped it. The direction is held from the beam's first frame
     * (the Reverse Blaster's from the start of the move). */
    if(type!=3 && n<=1)beams[p].facing=facing;
    facing=beams[p].facing;
    double yaw=facing*LASER_TURN;
    double fx=sin(yaw),fz=cos(yaw);
    double sx=hx+fx*laser_beams[type].fwd,sz=hz+fz*laser_beams[type].fwd,sy=hy-laser_beams[type].up;
    double ex=sx+fx*laser_beams[type].step_fwd*n,ez=sz+fz*laser_beams[type].step_fwd*n;
    double ey=sy+(double)laser_beams[type].step_down*n;
    if(type==5) {
        if(frame!=beams[p].frame) {
            beams[p].frame=frame;
            if(n>8) {
                /* 80117BD0: swing, turning back past +-0x3000; lengths
                 * from the random generator, one per axis. */
                beams[p].sweep+=beams[p].turning?-0x200:0x200;
                if((uint16_t)(beams[p].sweep+0x2fff)>=0x5fff)beams[p].turning^=1;
                double a=(uint16_t)(facing+beams[p].sweep)*LASER_TURN;
                beams[p].seed=beams[p].seed*1103515245u+12345u;
                beams[p].dx=(int32_t)(((beams[p].seed>>16)&0x3ff)*sin(a));
                beams[p].seed=beams[p].seed*1103515245u+12345u;
                beams[p].dz=(int32_t)(((beams[p].seed>>16)&0x3ff)*cos(a));
            }
        }
        if(n>8)n=8;
        ex=sx+beams[p].dx;ez=sz+beams[p].dz;ey=sy-200.0*n;
    } else beams[p].frame=frame;
    if(ey>0)ey=0;                                   /* floor: the beam slides along it */
    v[0]=(int32_t)sx;v[1]=(int32_t)sy;v[2]=(int32_t)sz;v[3]=(int32_t)ex;v[4]=(int32_t)ey;v[5]=(int32_t)ez;
    return n;
}
static void laser_capsule(uint32_t actor,uint32_t record,unsigned type,uint32_t capsule) {
    int32_t v[6];laser_ends(actor,record,type,v);
    for(unsigned i=0;i<6;i++)psx_mod_write_word(capsule+i*4,(uint32_t)v[i]);
}
/* For the renderer: the visible beam of player p this frame, if its current
 * move is a laser and the beam has appeared (up to a few frames after the
 * active window). */
int tekken3_laser_beam(unsigned p,int32_t v[6],int *fade) {
    if(p>1 || !ttt1_moves(p) || !players[p].records)return 0;
    uint32_t actor=0x800a9228+p*0x188c,record=psx_mod_read_word(actor+0x54),base=players[p].records;
    if(record<base || record>=base+slots[p].count*56 || (record-base)%56)return 0;
    unsigned laser=players[p].lasers?players[p].lasers[(record-base)/56]:0;
    if(!laser)return 0;
    int frame=(int)psx_mod_read_half(actor+0x58);
    if(frame>psx_mod_read_byte(record+46)+4)return 0;
    /* The arcade's fade (80117280): 4096 at the start of the active window, 0 thirty frames
     * after its end; it scales the beam's colour and its width (80117354: 50 + 100 f units). */
    int start=psx_mod_read_byte(record+45),span=psx_mod_read_byte(record+46)-start+30;
    if(span<1)span=1;
    *fade=(span-(frame-start))*4096/span;
    if(*fade<0)*fade=0;
    return laser_ends(actor,record,laser&0x7f,v)>0;
}
/* For the sounds: nonzero when player p's current record is one of its
 * guest's lasers. */
int tekken3_ttt1_laser_record(unsigned p,uint32_t record) {
    if(p>1 || !players[p].records || !players[p].lasers)return 0;
    uint32_t base=players[p].records;
    if(record<base || record>=base+slots[p].count*56 || (record-base)%56)return 0;
    return players[p].lasers[(record-base)/56]!=0;
}
/* Swept limbs. A limb pair with no start bone sweeps the limb from where it
 * was the frame before. TTT1 primes that start on every frame of the move
 * (8010A9A8, from the main loop), but T3 only calls 8006A3BC inside the
 * active window (80041FB4): taking the start from the capsule itself left
 * it where the last attack that swept ended - another move, another place
 * in the arena - and the first active frame (the only one, for many moves)
 * hit or missed depending on what was played before. The runtime keeps the
 * limb's position of the previous frame itself. */
/* Unknown's blade (TTT1 limbs 22 and 23, pack markers TTT1_PACK_BLADE_*):
 * fixed points of her hand bone 10, along the glowing blade the renderer
 * draws there, read in TTT1 (fighter + 0xA8C + limb * 0x50, the positions
 * 0x8010A9A8 takes) in the frame of that bone on Yoshimitsu's moveset. */
static void limb_position(uint32_t actor,unsigned limb,uint32_t out[3]) {
    if(limb!=TTT1_PACK_BLADE_MID && limb!=TTT1_PACK_BLADE_TIP) {
        for(unsigned axis=0;axis<3;axis++)out[axis]=psx_mod_read_word(actor+0x908+limb*68+axis*4);
        return;
    }
    uint32_t m=actor+0x8f4+BLADE_BONE*68;
    const int32_t l[3]={100,0,limb==TTT1_PACK_BLADE_TIP?727:364};
    for(unsigned i=0;i<3;i++) {
        int32_t v=(int32_t)psx_mod_read_word(m+0x14+i*4);
        for(unsigned j=0;j<3;j++)v+=((int16_t)psx_mod_read_half(m+(i*3+j)*2)*l[j])>>12;
        out[i]=(uint32_t)v;
    }
}
/* The limbs of player p's record: kept aside for a blade, else the engine's. */
/* A record of player p's pack that the defender plays as its own (DEFR):
 * the Jacks' haywire after Devil or Angel's laser. */
static int defender_record(unsigned p,uint32_t record) {
    uint32_t base=players[p].records;
    if(!base || record<base || (record-base)%56 || (record-base)/56>=slots[p].count)return 0;
    for(unsigned i=0;i<slots[p].defender_count;i++)if(slots[p].defender_records[i]==(record-base)/56)return 1;
    return 0;
}
static uint32_t record_limbs(unsigned p,uint32_t record) {
    uint32_t base=players[p].records;
    if(players[p].blades && record>=base && (record-base)%56==0 && (record-base)/56<slots[p].count &&
       players[p].blades[(record-base)/56])return players[p].blades[(record-base)/56];
    return psx_mod_read_word(psx_mod_read_word(record+40));
}
typedef struct { uint32_t record; unsigned frame; int valid; uint32_t pos[3]; } SweepSample;
/* Two samples per limb pair (the latest, the one before): the per-frame tick
 * may run before or after the capsules within a frame. */
static SweepSample sweep[2][2][2];
/* A sample of another record still counts when it is from the frame just
 * before: a string may switch records mid-clip - Kazuya's Spinning Demon,
 * d/f+4 then 4 late, leaves 276 for 277 on frame 16, its only active frame.
 * Forgetting the samples there left the foot without a sweep, a point: the
 * first kick hit only when the foot ended inside the opponent, where TTT1,
 * priming the start on every frame, sweeps it. */
static int follows(const SweepSample *h,uint32_t record,unsigned frame) {
    return h->valid && h->frame<frame && (h->record==record || frame-h->frame<=2);
}
static void keep_sweep(unsigned player,unsigned k,uint32_t record,unsigned frame,const uint32_t pos[3]) {
    SweepSample *h=sweep[player][k];
    /* Another move, or the same one started again (its frame went back,
     * or its pack was reloaded at the same address): forget the old ones. */
    if(!h[0].valid || (h[0].frame!=frame && !follows(&h[0],record,frame)) ||
       (h[0].frame==frame && h[0].record!=record))h[0].valid=h[1].valid=0;
    else if(h[0].frame!=frame)h[1]=h[0];
    h[0].record=record;h[0].frame=frame;h[0].valid=1;
    for(unsigned axis=0;axis<3;axis++)h[0].pos[axis]=pos[axis];
}
static const SweepSample *earlier_sweep(unsigned player,unsigned k,uint32_t record,unsigned frame) {
    for(unsigned i=0;i<2;i++) {
        const SweepSample *h=&sweep[player][k][i];
        if(follows(h,record,frame))return h;
    }
    return NULL;
}
static void sample_sweeps(unsigned player) {
    uint32_t actor=0x800a9228+player*0x188c,record=psx_mod_read_word(actor+0x54);
    unsigned frame=psx_mod_read_half(actor+0x58);
    if(!source_record(record))return;
    uint32_t limbs=record_limbs(player,record);
    for(unsigned k=0;k<2;k++) {
        unsigned end=limbs>>(16*k)&255,start=limbs>>(16*k+8)&255;
        if(!end || start || (end>=24 && end!=TTT1_PACK_BLADE_MID && end!=TTT1_PACK_BLADE_TIP))continue;
        uint32_t pos[3];
        limb_position(actor,end,pos);
        keep_sweep(player,k,record,frame,pos);
    }
}
/* 0x8003C8F0: the frames of pose blend when a fighter changes move - up to
 * the new move's first active frame (record +45), so that the blend is over
 * when the move hits. A switch on the active frame itself leaves none and
 * T3 falls back on 4 or 16 frames: Kazuya's Spinning Demon, second kick
 * pressed late, leaves 276 for 277 on frame 16, the kick's only active frame,
 * and the foot was blended with the previous pose - a quarter of its path,
 * short of the opponent. TTT1 goes on with the clip there (MAME: the foot
 * covers 4839 units from frame 15 to 16 against 4927 in 276 alone). A
 * guest's move entered inside its active window takes no blend. */
extern void __real_func_8003C8F0(CPUState *cpu);
void __wrap_func_8003C8F0(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x8003c8f0) {
        uint32_t actor=cpu->gpr[4],record=psx_mod_read_word(actor+0x54);
        if((actor==0x800a9228 || actor==0x800aaab4) && source_record(record) &&
           psx_mod_read_word(actor+0x1824)!=record) {
            unsigned first=psx_mod_read_byte(record+45),last=psx_mod_read_byte(record+46);
            int frame=(int16_t)psx_mod_read_half(actor+0x58);
            if(first && frame>=(int)first && frame<=(int)last) {
                cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;
            }
        }
    }
    __real_func_8003C8F0(cpu);
}
void __wrap_func_8006A3BC(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x8006a3bc) {
        uint32_t actor=cpu->gpr[4];
        for(unsigned p=0;p<2;p++) if(actor==0x800a9228+p*0x188c) {
            /* The pack the record is from: the fighter's own guest moves, or
             * the other's haywire moves it plays as its own (any fighter). */
            uint32_t record=psx_mod_read_word(actor+0x54);
            unsigned q=defender_record(p^1,record)?p^1:p;
            if(q==p && !(ttt1_moves(p) && players[p].records))break;
            uint32_t base=players[q].records;
            if(record<base || record>=base+slots[q].count*56 || (record-base)%56)break;
            uint32_t limbs=record_limbs(q,record);
            unsigned laser=players[q].lasers?players[q].lasers[(record-base)/56]:0;
            if(laser){laser_capsule(actor,record,laser&0x7f,actor+0x1ac);cpu->pc=cpu->gpr[31];return;}
            if((limbs&255)==EFFECT_FIRE_LIMB)break;         /* True Ogre's fire: the engine's own */
            /* Arcade 8010AEFC..8010B178 uses two pairs of limb IDs. A
             * zero second ID sweeps the first limb from its previous
             * position. Otherwise the capsule joins two current joints.
             * Core limb numbering 0..17 is unchanged in the PS1 skeleton. */
            for(unsigned k=0;k<2;k++) {
                unsigned end=limbs>>(16*k)&255,start=limbs>>(16*k+8)&255;
                if(!end)continue;
                uint32_t capsule=actor+0x1ac+k*24;
                unsigned frame=psx_mod_read_half(actor+0x58);
                /* Sweep: from the limb's position of an earlier frame of
                 * this move; none yet (the move's first frame): no sweep. */
                const SweepSample *earlier=start?NULL:earlier_sweep(p,k,record,frame);
                uint32_t now[3],first[3];
                limb_position(actor,end,now);
                if(start)limb_position(actor,start,first);
                for(unsigned axis=0;axis<3;axis++) {
                    uint32_t from=start?first[axis]:earlier?earlier->pos[axis]:now[axis];
                    psx_mod_write_word(capsule+axis*4,from);
                    psx_mod_write_word(capsule+12+axis*4,now[axis]);
                }
                if(!start)keep_sweep(p,k,record,frame,now);
            }
            cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_8006A3BC(cpu);
}
/* 0x8002CC28 tests a cancel entry's command for the actor in a0 (0: no).
 * A fighter that a guest's move animates (a throw's victim, a reaction of
 * the guest's own, __wrap_func_8002D178) stands on that guest's record and
 * reads its cancel list: its own inputs then started the guest's moves - a
 * CPU Kuma or Jack-2 played Kazuya's. On another player's guest record, only
 * the automatic links (0xC000..0xDFFF: end of the clip, transitions) count,
 * which bring the fighter back to its own moves. Command 0x0010 (no button,
 * no direction: the clip's own automatic follow-up, e.g. the face-down
 * juggle fall 0xD6E -> 0xD6F at frame 32) reads no input either: it passes.
 * Among those is the guard window of a stun: a reaction (the stagger kicks'
 * 0x229A, for one) has at its 9th frame an entry of command 0x0010 whose
 * destination is the record itself, transition kind 26: it does not change the
 * clip, it raises the actor's +0xB6, which lets the pad pick the guard flags
 * (0x1052 stand guard back, 0x2829 crouch guard down-back, at 0x8004043C) for
 * the rest of the stun. Refused, the victim's pad was never read and the next
 * hit of the series always landed. */
/* The defender's own rules on a laser reaction (condition SELF_MOVESET), and
 * every rule of the moves they lead to (DEFR): the Jacks' haywire, whose
 * links are automatic (command 0x0010). */
static int defender_rule(uint32_t actor,unsigned owner,uint32_t entry) {
    return psx_mod_read_byte(entry+3)==SELF_MOVESET || defender_record(owner,psx_mod_read_word(actor+0x54));
}
void __wrap_func_8002CC28(CPUState *cpu) {
    unsigned player=cpu->gpr[4]==0x800aaab4?1:0;
    if((cpu->pc==0 || cpu->pc==0x8002cc28) && cpu->gpr[4]==0x800a9228+player*0x188c) {
        int owner=record_owner(psx_mod_read_word(cpu->gpr[4]+0x54));
        unsigned command=psx_mod_read_half(cpu->gpr[5]);
        if(owner>=0 && (unsigned)owner!=player && command!=0x10 && (command<0xc000 || command>=0xe000) &&
           !defender_rule(cpu->gpr[4],(unsigned)owner,cpu->gpr[5])) {
            cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;
        }
    }
    if((cpu->pc==0 || cpu->pc==0x8002cc28) && cpu->gpr[4]==0x800a9228+player*0x188c && players[player].native_base) {
        unsigned command=psx_mod_read_half(cpu->gpr[5]);
        if(command>=0xe000 && command<0xe000+slots[player].pattern_count) {
            cpu->gpr[5]=slots[player].patterns[command-0xe000];cpu->pc=0;
            func_8002CA84(cpu);return;
        }
    }
    __real_func_8002CC28(cpu);
}
/* Reaction category of a fighter hit while airborne. 0x8002EE94 (a0 the victim,
 * a1 the attacker) picks a row of the table at 0x8001A630 - the engine alias in
 * +2, a modifier in +0 - and stores the category at +0x90, the alias at +0x1A0
 * and the modifier at +0x96. TTT1's chooser (0x8011643C) has a branch Tekken 3
 * lacks: a victim in the face-down stage of a juggle (flags bit 0x200, or
 * already on 0x128B..0x128D) falls on 0x128B once its counter (+0x3E0 here,
 * +0x3BC there) reaches 110, else on 0x128D (Tekken 3's 0xD62) while its pelvis
 * is lower than 736 (|+0xF6C|; -1042 standing), else on 0x128C (the arcade's
 * delay slot sets 5 before the branch that keeps it, 6 follows it).
 * Tekken 3 knows neither bit 0x200 nor 0x128B / 0x128C, so a juggle hit on a
 * fighter lying face-down always came out as category 0, the face-up fall.
 * For an attacker on TTT1 moves that branch is taken here, with the attacker's
 * own records of the two aliases (the importer keeps them in the pack).
 * Everything else, and every attacker on Tekken 3 moves, goes to the original
 * function untouched. */
static unsigned guest_alias(unsigned slot,unsigned source_alias) {
    const GuestCombat *c=&slots[slot];
    if(!c->loaded || !c->data || source_alias>=5515)return 0;
    uint32_t record=c->source_aliases[source_alias];
    if(!record)return 0;
    for(unsigned i=0;i<c->count;i++)if(word(c->data+36+i*16)==record)return slot_base(slot)+i;
    return 0;
}
void __wrap_func_8002EE94(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8002ee94) && (cpu->gpr[5]==0x800a9228 || cpu->gpr[5]==0x800aaab4) &&
       cpu->gpr[4]!=cpu->gpr[5]) {
        unsigned attacker=cpu->gpr[5]==0x800aaab4;
        uint32_t victim=cpu->gpr[4];
        unsigned face_down=0,low=0;
        if(ttt1_moves(attacker) && ready(attacker) && (face_down=guest_alias(attacker,0x128b)) &&
           (low=guest_alias(attacker,0x128c))) {
            uint32_t flags=psx_mod_read_word(victim+0x60);
            int number=(int16_t)psx_mod_read_half(victim+0xa0),frame=(int16_t)psx_mod_read_half(victim+0x58);
            if((flags&0x200) || number==(int)face_down || number==(int)low || number==0xd62 ||
               ((number==0xd63 || number==0xd64) && frame>=19)) {
                int32_t counter=(int32_t)psx_mod_read_word(victim+0x3e0),height=(int32_t)psx_mod_read_word(victim+0xf6c);
                unsigned alias,modifier;
                if(height<0)height=-height;
                if(counter>=110){alias=face_down;modifier=0x226;}
                else if((int16_t)height>=736){alias=low;modifier=0;}
                else {modifier=psx_mod_read_half(0x8001a630+4*2);alias=psx_mod_read_half(0x8001a630+4*2+2);}
                if(getenv("TEKKEN3_TTT1_JUGGLE_LOG"))
                    fprintf(stderr,"TTT1 juggle P%u: flags %04X number %04X frame %d counter %d height %d -> alias %04X\n",
                            attacker+1,flags,number&0xffff,frame,counter,height,alias);
                psx_mod_write_half(victim+0x90,2);
                psx_mod_write_half(victim+0x1a0,alias);
                psx_mod_write_half(victim+0x96,modifier);
                cpu->gpr[2]=modifier;cpu->gpr[3]=alias;cpu->pc=cpu->gpr[31];return;
            }
        }
    }
    __real_func_8002EE94(cpu);
}
/* Strong-hit effect. Each fighter's file carries a pack of 4-bit TIMs
 * (16-colour palette, 32 x 32 image) that the fight loader places in VRAM:
 * frame k in column 368/376 (player 1) or 496/504 (player 2), row 32*(k/2),
 * palette at (16*player, 503). A guest is loaded through Jin, so it would
 * show Jin's lightning; its own pack, converted from TTT1 by the importer,
 * is written over it whenever the loader has put Jin's back. */
static void load_hit_effect(unsigned s) {
    follow_identity(s);
    GuestCombat *c=&slots[s];
    if(c->hit_effect_attempted)return;
    c->hit_effect_attempted=1;
    const char *root=tekken3_ttt1_asset_root();
    if(!root)return;
    char path[4096];
    if(snprintf(path,sizeof path,"%s/%s-hiteffect.tim",root,tekken3_guest_data_prefix_for(s))>=(int)sizeof path)return;
    FILE *f=fopen(path,"rb");if(!f)return;
    unsigned char *p=malloc(32*576);
    size_t n=p?fread(p,1,32*576,f):0;fclose(f);
    if(!p || !n || n%576){free(p);return;}
    for(size_t o=0;o<n;o+=576)
        if(word(p+o)!=0x10 || word(p+o+4)!=8 || word(p+o+8)!=44 || word(p+o+16)!=0x10010 ||
           word(p+o+52)!=524 || word(p+o+60)!=0x200008){free(p);return;}
    c->hit_effect=p;c->hit_effect_frames=(unsigned)(n/576);
    fprintf(stderr,"%s combat: strong-hit effect, %u frames\n",tekken3_guest_name_for(s),c->hit_effect_frames);
}
/* Player s's pack for the effect header (tekken3_ttt1_roster.c): its number
 * of images, 0 without one, and its palette's mean colour, 8 bits a channel. */
unsigned tekken3_ttt1_hit_effect_frames(unsigned s,unsigned rgb[3]) {
    if(s>1)return 0;
    load_hit_effect(s);
    const GuestCombat *c=&slots[s];
    if(!c->hit_effect)return 0;
    unsigned n=0;
    rgb[0]=rgb[1]=rgb[2]=0;
    for(unsigned i=1;i<16;i++) {
        unsigned v=(c->hit_effect[20+2*i]|c->hit_effect[21+2*i]<<8)&0x7fff;
        if(!v)continue;
        rgb[0]+=(v&31)<<3;rgb[1]+=(v>>5&31)<<3;rgb[2]+=(v>>10&31)<<3;n++;
    }
    for(unsigned k=0;n && k<3;k++)rgb[k]/=n;
    return c->hit_effect_frames;
}
/* No VRAM readback: on the OpenGL renderer each one waits for the GPU to
 * finish the frame (a second of 20-27 ms frames at every round start with
 * 3x supersampling when this checked for 60 frames). The runtime flags any
 * write over the pack or its palette row (gr_vram_watch): the pack goes up
 * on entering the fight and again after anything wrote there (the loader
 * putting Jin's back), never otherwise. The palette watch leaves out colours
 * 0..1 of the row: the game copies a 2-pixel column (x 0..1, the whole VRAM
 * height, GP0 0x80) every frame in Tekken Force as in the selectors, which
 * flagged player 1's palette every frame and sent the whole pack (23 rects)
 * to the GPU on each one. */
static int hit_effect_in_fight[2];
static int hit_effect_watch[2][2]={{-1,-1},{-1,-1}};
extern int tekken3_cine_frame(void);
extern int tekken3_ttt1_tiles_up(void);
static void place_hit_effect(unsigned player) {
    /* A cinematic's own pack (TEKKEN3_EMBU_EFFECT_P1 / _P2) holds the slot
     * while it plays: Jin's red lightning, not the guest's own. */
    const char *own=getenv(player?"TEKKEN3_EMBU_EFFECT_P2":"TEKKEN3_EMBU_EFFECT_P1");
    if(own && *own && tekken3_cine_frame()>=0)return;
    load_hit_effect(player);
    const GuestCombat *c=&slots[player];
    if(!c->hit_effect)return;
    /* Team Battle's FIGHT screen: the fighter still loaded keeps placing its
     * pack, but player 2's (x 496..511) lies under the end of Panda's and
     * Tiger's 128-colour palettes (384..511, rows 136..139). Each frame the
     * tiles went back, the pack over them, and the pack won: speckled tile.
     * The tiles' backup keeps the pack and returns it when they go. */
    if(tekken3_ttt1_tiles_up())return;
    unsigned x=player?496:368,frames=c->hit_effect_frames<32?c->hit_effect_frames:32;
    int *w=hit_effect_watch[player];
    if(w[0]<0) {
        w[0]=gr_vram_watch(x,0,16,32*((frames+1)/2));
        w[1]=gr_vram_watch(16*player+2,503,14,1);   /* not colours 0..1: see below */
    }
    int written=gr_vram_watch_take(w[0]) | gr_vram_watch_take(w[1]);
    if(hit_effect_in_fight[player] && !written)return;
    hit_effect_in_fight[player]=1;
    for(unsigned k=0;k<frames;k++)
        gr_vram_transfer_in(x+8*(k&1),32*(k>>1),8,32,(const uint16_t*)(c->hit_effect+k*576+64));
    gr_vram_transfer_in(16*player,503,16,1,(const uint16_t*)(c->hit_effect+20));
    gr_vram_watch_take(w[0]);gr_vram_watch_take(w[1]);   /* our own upload */
}
/* The attract-mode Embu does not run the fight's effect placing: its players
 * show whatever effect pack the Embu loaded for its own cast. A pack of the
 * same format can be written there instead (TEKKEN3_EMBU_EFFECT_P1 / _P2: a
 * file, absolute or under the TTT1 asset root): Jin's red TTT1 lightning
 * for his transformation in Kazuya's TTT ending, which the lightning aura
 * (timed property 6) draws with. */
void tekken3_ttt1_embu_effects(void) {
    static unsigned char *pack[2];static unsigned frames[2];static int tried[2];
    for(unsigned p=0;p<2;p++) {
        if(!tried[p]) {
            tried[p]=1;
            const char *e=getenv(p?"TEKKEN3_EMBU_EFFECT_P2":"TEKKEN3_EMBU_EFFECT_P1"),*root=tekken3_ttt1_asset_root();
            char path[4096];
            if(!e || !*e)continue;
            /* Absolute on Windows too (C:\..., the TTT Cinematics' $DIR). */
            if(e[0]=='/' || e[0]=='\\' || (e[0] && e[1]==':'))snprintf(path,sizeof path,"%s",e);
            else if(!root || snprintf(path,sizeof path,"%s/%s",root,e)>=(int)sizeof path)continue;
            FILE *f=fopen(path,"rb");if(!f){fprintf(stderr,"TTT1 Embu: no effect pack %s\n",path);continue;}
            unsigned char *b=malloc(32*576);size_t n=b?fread(b,1,32*576,f):0;fclose(f);
            if(!b || !n || n%576){free(b);continue;}
            pack[p]=b;frames[p]=(unsigned)(n/576);
            fprintf(stderr,"TTT1 Embu: P%u effect pack %s, %u frames\n",p+1,path,frames[p]);
        }
        if(!pack[p])continue;
        unsigned x=p?496:368;
        uint16_t row[16],pal[16];
        gr_vram_transfer_out(x,0,8,1,row);
        gr_vram_transfer_out(16*p,503,16,1,pal);
        if(!memcmp(row,pack[p]+64,16) && !memcmp(pal,pack[p]+20,32))continue;
        for(unsigned k=0;k<frames[p] && k<32;k++)
            gr_vram_transfer_in(x+8*(k&1),32*(k>>1),8,32,(const uint16_t*)(pack[p]+k*576+64));
        gr_vram_transfer_in(16*p,503,16,1,(const uint16_t*)(pack[p]+20));
    }
}
/* The strong-hit light's colour (header of 6 bytes per character at
 * 0x80027950: frames, then RGB): the Embu keeps its natives' IDs, so its
 * guests light up in their colours (Hwoarang's cyan on skin reads green).
 * TEKKEN3_EMBU_EFFECT_LIGHT="RRGGBB" gives every character that colour while
 * the Embu runs, the stock colours back as soon as it ends. */
void tekken3_ttt1_embu_light(int embu) {
    enum { HEADERS=0x80027950, HEADER=6, IDS=22 };
    static int want=-2;static unsigned char saved[IDS][3];static int lit;
    if(want==-2){const char *e=getenv("TEKKEN3_EMBU_EFFECT_LIGHT");want=e&&*e?(int)strtol(e,NULL,16):-1;}
    if(want<0)return;
    if(embu && !lit) {
        for(unsigned id=0;id<IDS;id++)for(unsigned k=0;k<3;k++) {
            saved[id][k]=psx_mod_read_byte(HEADERS+id*HEADER+2+k);
            psx_mod_write_byte(HEADERS+id*HEADER+2+k,(unsigned char)(want>>(16-8*k)));
        }
        lit=1;fprintf(stderr,"TTT1 Embu: strong-hit light %06X\n",want);
    } else if(!embu && lit) {
        for(unsigned id=0;id<IDS;id++)for(unsigned k=0;k<3;k++)psx_mod_write_byte(HEADERS+id*HEADER+2+k,saved[id][k]);
        lit=0;fprintf(stderr,"TTT1 Embu: strong-hit light back to stock\n");
    }
}
/* A guest standing in for the native whose effect the Embu plays
 * (tekken3_ttt1_roster.c, embu_effect_headers). */
void tekken3_ttt1_embu_hit_effect(unsigned player) {
    if(player<2)place_hit_effect(player);
}
/* The CPU's spacing table (0x80098260, 12 bytes per character: five distance
 * thresholds) is read at round start (0x800616CC) with the actor's ID (+0x18)
 * of the CPU and of its opponent. It stops at ID 21, so against a guest
 * (23+) the CPU read the next table: thresholds of 0. Copy it with a row
 * for every guest ID. TTT1 gives all the guests its default row, which is
 * Jin's (row 9). */
enum { CPU_TABLE=0x80098260, CPU_NATIVE_ROWS=22, CPU_ROWS=64, CPU_ROW=12, CPU_DEFAULT_ROW=9 };
static void install_cpu_table(void) {
    static uint32_t table;
    if(table || psx_mod_read_word(CPU_TABLE+CPU_DEFAULT_ROW*CPU_ROW)!=0x06c00580 ||
       psx_mod_read_word(0x800616cc)!=0x3c04800a || psx_mod_read_word(0x800616d4)!=0x24848260)return;
    if(!(table=psx_mod_alloc_guest_memory(CPU_ROWS*CPU_ROW,16)))return;
    for(unsigned id=0;id<CPU_ROWS;id++) {
        uint32_t from=CPU_TABLE+(id<CPU_NATIVE_ROWS?id:CPU_DEFAULT_ROW)*CPU_ROW;
        for(unsigned i=0;i<CPU_ROW;i+=4)psx_mod_write_word(table+id*CPU_ROW+i,psx_mod_read_word(from+i));
    }
    patch_base(0x800616cc,0x800616d4,4,table);
}
/* Tekken Force's overlay (0x800B2658) picks each stage's boss from a route:
 * 0x800B6378[selection], selection = character * 4 + costume (actor +0x14),
 * points to {fighter, outfit} per stage. The table stops at character 22:
 * a guest read 0 (Kazuya) or the actor state that follows (higher IDs),
 * then dereferenced it at 0x800B26D4. Copy it with a route per guest ID,
 * Jin's (the guests fight in his envelope), whenever the overlay is loaded. */
enum { FORCE_TABLE=0x800b6378, FORCE_NATIVE=92, FORCE_ENTRIES=64*4, FORCE_DEFAULT=9 };
static void install_force_bosses(void) {
    static uint32_t table;
    if(psx_mod_read_word(0x800b2658)!=0x27bdffb8 || psx_mod_read_word(0x800b26d4)!=0x84720002 ||
       psx_mod_read_word(0x800b2694)!=0x3c05800b || psx_mod_read_word(0x800b2698)!=0x24a56378)return;
    if(!table && !(table=psx_mod_alloc_guest_memory(FORCE_ENTRIES*4,16)))return;
    for(unsigned i=0;i<FORCE_ENTRIES;i++)
        psx_mod_write_word(table+i*4,psx_mod_read_word(FORCE_TABLE+(i<FORCE_NATIVE?i:FORCE_DEFAULT*4+i%4)*4));
    patch_base(0x800b2694,0x800b2698,5,table);
    fprintf(stderr,"TTT1 characters: Tekken Force boss routes extended, guests take Jin's\n");
}
/* The engine entries whose TTT1 records carry Unknown's switch rule (cancel
 * 0x800B, condition 0xA6), the same in her 23 movesets (TTT1 RAM, read
 * through combat_semantics.native_aliases): stance, walks, crouch, dashes,
 * sidesteps - not only the stance at rest. */
static int switch_entry(unsigned alias) {
    static const unsigned char entries[]={0x03,0x15,0x16,0x18,0x1a,0x1b,0x1c,0x1d,0x1e,0x1f,0x20,0x21,
        0x24,0x25,0x26,0x27,0x28,0x2c,0x2d,0x2e,0x2f,0x30,0x31,0x33,0x34,0x35,0x36,0x38,0x39,0x3a,
        0x3b,0x3c,0x3d,0x3e,0x3f,0x40,0x41,0x42,0x43,0x44,0x45,0x46,0x7f};
    if(alias>=0x11b && alias<=0x11e)return 1;
    for(unsigned i=0;i<sizeof entries;i++)if(entries[i]==alias)return 1;
    return 0;
}
static int may_switch(unsigned player,uint32_t record) {
    if(record==players[player].records+slots[player].neutral*56)return 1;
    for(unsigned alias=0;alias<=0x11e;alias++)
        if(switch_entry(alias) && psx_mod_read_word(players[player].alias_table+alias*4)==record)return 1;
    return 0;
}
/* Unknown's L1 (tekken3_guest_switch_request): once she is in one of the
 * moves TTT1 allows it from (switch_entry), her moves are rebuilt from the
 * drawn donor and she takes its stance record, as TTT1's rule leads to the
 * stance. */
static void switch_moveset(unsigned player) {
    if(!tekken3_guest_switch_request(player))return;
    uint32_t actor=0x800a9228+player*0x188c;
    if(!slots[player].loaded || !may_switch(player,psx_mod_read_word(actor+0x54)))return;
    tekken3_guest_switch_done(player);
    /* The new pack goes to the player's other area. The engine's saved
     * poses still name clips of the old pack, which pose() finds there
     * intact: loaded over the old one, they read the new pack's data and
     * the fighter jumped elsewhere in the arena. The fighter then takes the
     * new stance as the engine starts a move (0x8002D5F0): move ID +0x1A0,
     * record +0x54, +0x4C and +0x1A4, frame +0x58 = 1. The old records'
     * own links would not do: they name moves by their index in the old
     * pack. */
    switching[player]=SWITCH_TO;
    int drawn=tekken3_guest_switch_moveset(player),switched=drawn && ready(player);
    if(drawn && !switched) {
        /* A pack that does not load must not strand her on the old one,
         * which no switch could leave: take the previous moveset back. */
        fprintf(stderr,"%s combat: P%u moveset did not load, back to the previous one\n",
                tekken3_guest_name_for(player),player+1);
        switching[player]=SWITCH_UNDO;
        switched=tekken3_guest_switch_undo(player) && ready(player);
    }
    switching[player]=SWITCH_NONE;
    if(!switched)return;
    uint32_t stance=players[player].records+slots[player].neutral*56;
    psx_mod_write_half(actor+0x1a0,3);
    psx_mod_write_word(actor+0x54,stance);psx_mod_write_word(actor+0x4c,stance);psx_mod_write_word(actor+0x1a4,stance);
    psx_mod_write_half(actor+0x58,1);
}
/* The CPU keeps its own copy of a fighter's alias table (0x8009F2E8 +
 * 4 * index and 0x8009F318 + 0x330 * index + 12, index = actor +0x1886),
 * set when its initialization ran: before a guest's table was installed,
 * or while the slot still named the previous guest's. The CPU then drew its
 * moves from another table: a CPU Kuma or Jack-2 played Kazuya's (UAT,
 * 2026-09-26). Upstream fixed it for Jun in v0.1.3 (d073392, "opponents no
 * longer copy her moves"); here, before each CPU decision, a guest's copy
 * is its own table (a native on its TTT1 moves too), and a stock fighter's
 * copy that still names a guest's table goes back to its own header's. */
enum { CPU_ALIASES=0x8009f2e8, CPU_STATE=0x8009f318, CPU_STATE_SIZE=0x330 };
/* The CPU and the lasers. T3's CPU has a defence for the native breaths
 * (0x80059A4C marks Ogre's and Gon's, +0x200 / +0x201), but it is a guard
 * and turns the CPU passive: tried on the lasers, which cannot be blocked,
 * it stood in every beam. Measured with the same protocol in both games
 * (tools/test_cpu_lasers.py, tools/ttt1_cpu_lasers.lua: the two put 2500
 * apart, a shot after a varying delay): TTT1's CPU at SUPER HARD keeps its
 * distance and side-steps, hit by 1 Inferno in 11 and 1 Blaster in 10;
 * T3's at HARD (the same strength, DIFFICULTY.md) runs in and takes 6 in
 * 8 (17 in 19 from 3500). Here, when a guest's Inferno or Blaster starts,
 * a dice by difficulty (EASY 30 %, MEDIUM 55 %, HARD 80 %, the arcade levels
 * of the Options menu 85 to 95 %) has
 * the CPU side-step until the beam is over, with the side step's inputs
 * (__wrap_func_8002C580): a tap of up or down whenever it is free (not
 * attacking, standing), again every 24 frames, nothing held in between.
 * Starting its side-step move directly (aliases 59 / 127) let its own
 * held inputs turn it into a jump (seen in the user's game, 2026-10-02),
 * and a list of free moves taken from the bench missed most of a real
 * fight. T3's defence against Ogre's fire is no help here: it holds back
 * (input 0x8000, 40 frames), a guard, against a beam no guard stops.
 * Air Inferno and the win pose are left out. TEKKEN3_CPU_LASER_DODGE=0
 * turns it off (measurements). */
enum { CPU_DIFFICULTY=0x800ae208, CPU_MENU_DIFFICULTY=0x80097f06, DODGE_GAP=24 };
static struct { uint32_t record; int start,dodge,stepped; unsigned dir,seed; } dodges[2];
/* Returns 1 with the CPU's inputs of the frame in *input when it is
 * answering a laser. */
static int cpu_laser_dodge(uint32_t self,uint32_t *input) {
    static int off=-1;
    if(off<0){const char *e=getenv("TEKKEN3_CPU_LASER_DODGE");off=e && *e=='0';}
    if(off || (self!=0x800a9228 && self!=0x800aaab4))return 0;
    unsigned me=self!=0x800a9228,q=!me;
    uint32_t opponent=0x800a9228+q*0x188c;
    if(!ttt1_moves(q) || !players[q].records || !players[q].lasers){dodges[me].record=0;return 0;}
    uint32_t record=psx_mod_read_word(opponent+0x54),base=players[q].records;
    unsigned type=0;
    if(record>=base && record<base+slots[q].count*56 && !((record-base)%56))
        type=players[q].lasers[(record-base)/56]&0x7f;
    if(type<1 || type>3){dodges[me].record=0;return 0;}
    int frame=(int16_t)psx_mod_read_half(opponent+0x58);
    int last=psx_mod_read_byte(record+46);
    if(dodges[me].record!=record || frame<dodges[me].start) {
        dodges[me].record=record;dodges[me].start=frame;dodges[me].dodge=-1;
    }
    if(frame>last+4)return 0;
    if(dodges[me].dodge<0) {
        /* The arcade levels of the Options menu (src/tekken3_difficulty_mod.c)
         * leave the game's value at HARD; the menu's says which: past HARD,
         * ULTRA HARD (T3 arcade), SUPER HARD (TTT1, measured about 9 in 10),
         * ULTRA HARD1, EX SUPER HARD, easiest first. */
        static const unsigned char arcade[]={85,90,93,95};
        unsigned level=psx_mod_read_half(CPU_DIFFICULTY),menu=psx_mod_read_byte(CPU_MENU_DIFFICULTY);
        unsigned chance=level==0?30:level==1?55:80;
        if(level>=2 && menu>=3)chance=arcade[menu-3<sizeof arcade?menu-3:sizeof arcade-1];
        dodges[me].seed=dodges[me].seed*1103515245u+12345u+psx_mod_read_word(0x800adca0);
        dodges[me].dodge=(dodges[me].seed>>16)%100<chance;
        dodges[me].dir=(dodges[me].seed>>8)&1?0x1000:0x4000;
        dodges[me].start=frame;dodges[me].stepped=-DODGE_GAP;
    }
    if(!dodges[me].dodge)return 0;
    /* Free: its move has no hit window (not an attack) and it stands (head
     * bone above 1100: not down, not crouched, not thrown about). */
    uint32_t own=psx_mod_read_word(self+0x54);
    int attacking=own>=0x80010000 && own<0xa0000000 && psx_mod_read_byte(own+45);
    int free=!attacking && (int32_t)psx_mod_read_word(self+0x908+2*68+4)< -1100;
    *input=0;
    if(free && frame-dodges[me].stepped>=DODGE_GAP){*input=dodges[me].dir;dodges[me].stepped=frame;}
    return 1;
}
static int guest_alias_table(uint32_t table) {
    for(unsigned p=0;p<2;p++)if(table && table==players[p].alias_table)return 1;
    return 0;
}
/* Tekken Force loads each enemy and each boss at the same address, and the
 * engine does not refresh the CPU's copy of the table when one replaces the
 * other: the boss's AI kept the previous enemy's table address, now inside
 * the boss's own file. Entry 3 (the stance) of such a table names data that
 * is no record, and the candidate scan of 0x80056764, which follows a
 * record's list of 12-byte entries until its 0xC000 terminator, ran off
 * through memory: a stall of most of a second every few seconds, and the
 * widescreen view dropping to 4:3 each time. A table is sound when its
 * stance record and that record's list are pointers into memory. */
static int memory_pointer(uint32_t a) {return (a>=0x80010000 && a<0x80200000) || (a>=0x9f000000 && a<0x9f400000);}
static int alias_table_sound(uint32_t table) {
    if(!memory_pointer(table))return 0;
    uint32_t record=psx_mod_read_word(table+3*4);
    return memory_pointer(record) && memory_pointer(psx_mod_read_word(record+12));
}
void __wrap_func_80059890(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x80059890) {
        uint32_t actor=cpu->gpr[4];
        if(actor==0x800a9228 || actor==0x800aaab4)cpu_decided[actor!=0x800a9228]=1;
        for(unsigned p=0;p<2;p++) {
            if(actor!=0x800a9228+p*0x188c)continue;
            unsigned index=psx_mod_read_byte(actor+0x1886);
            if(index>=2)break;
            uint32_t cached=psx_mod_read_word(CPU_ALIASES+index*4),table=0;
            if(ttt1_moves(p) && ready(p))table=players[p].alias_table;
            else {
                uint32_t header=psx_mod_read_word(0x800adc20+p*4),own=0;
                if(header>=0x80010000 && header<0x80200000 && !guest_alias_table(psx_mod_read_word(header+12)))
                    own=psx_mod_read_word(header+12);
                if(guest_alias_table(cached))table=own;
                else if(own && own!=cached && !alias_table_sound(cached) && alias_table_sound(own))table=own;
            }
            if(table && table!=cached) {
                fprintf(stderr,"TTT1 characters: P%u CPU alias cache %08X -> %08X (%s)\n",p+1,cached,table,
                        ttt1_moves(p)?"its guest table":alias_table_sound(cached)?"back to its own":"stale, back to its own");
                psx_mod_write_word(CPU_ALIASES+index*4,table);
                psx_mod_write_word(CPU_STATE+index*CPU_STATE_SIZE+12,table);
            }
            break;
        }
    }
    __real_func_80059890(cpu);
}
/* 0x8002C580 takes a fighter's inputs of the frame, pressed (a2) and held
 * (a3): the pad's for a player, the CPU's from its decision (0x8002C4C4,
 * which calls 0x80059890 just before). While the CPU answers a laser, its
 * inputs are the side step's: a single frame of up or down pressed, then
 * nothing held (held, it would jump), as its own side steps go. */
void __wrap_func_8002C580(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x8002c580) {
        uint32_t actor=cpu->gpr[4],input;
        if(actor==0x800a9228 || actor==0x800aaab4) {
            unsigned me=actor!=0x800a9228;
            if(cpu_decided[me] && cpu_laser_dodge(actor,&input)){cpu->gpr[6]=input;cpu->gpr[7]=input;}
            cpu_decided[me]=0;
        }
    }
    __real_func_8002C580(cpu);
}
/* The CPU's command synthesis (0x800618C0) looks its inputs up here; the
 * stock lookup knows nothing of a guest's input sequences (0xE000 +, as
 * 0x8002CC28 above): the CPU's guest lost those moves. Only for the guest
 * (or native on its TTT1 moves) that the CPU is playing (0x800AFA5C), from
 * its own pack. Also upstream's
 * v0.1.3 fix for Jun. */
void __wrap_func_8002CD7C(CPUState *cpu) {
    unsigned command=cpu->gpr[4]&0xffff;
    if((cpu->pc==0 || cpu->pc==0x8002cd7c) && command>=0xe000) {
        uint32_t actor=psx_mod_read_word(0x800afa5c);
        for(unsigned p=0;p<2;p++)
            if(actor==0x800a9228+p*0x188c && ttt1_moves(p) && players[p].native_base &&
               command<0xe000+slots[p].pattern_count) {
                cpu->gpr[2]=slots[p].patterns[command-0xe000];cpu->pc=cpu->gpr[31];return;
            }
    }
    __real_func_8002CD7C(cpu);
}
void tekken3_ttt1_combat_tick(void) {
    install_cpu_table();
    install_force_bosses();
    for(unsigned player=0;player<2;player++) {
        if(ttt1_moves(player)) {
            if(ready(player))switch_moveset(player);
            if(ready(player)) {
                /* A native on its TTT1 moves and Devil Jin keep their own
                 * strong-hit effect (and Devil Jin his Devil face). */
                if(tekken3_ttt1_player_motion_mode(player)==2 && !tekken3_devil_jin_player(player))place_hit_effect(player);
                sample_sweeps(player);
                uint32_t actor=0x800a9228+player*0x188c,record=psx_mod_read_word(actor+0x54);
                unsigned frame=psx_mod_read_half(actor+0x58),duration=0;
                /* A face expression property (0x40..0x45, combat_semantics.py) fires once,
                 * when the move's frame reaches it, as TTT1's dispatch (800FBF0C: previous
                 * frame < its frame <= frame). The game advanced if the move or its frame
                 * changed since the last tick: not in a pause. */
                int expression=-1,advanced=record!=face_record[player] || frame!=face_frame[player];
                unsigned previous=record==face_record[player] && face_frame[player]<=frame?face_frame[player]:0;
                face_record[player]=record;face_frame[player]=frame;
                unsigned flag=0;
                /* TTT1 record +0x24 bits 11 and 22 are bits 18 and 30 of the
                 * T3 record (combat_semantics.flags), +4 the same: so also on
                 * the engine's own records a guest plays when it is hit
                 * (0x801B...: knocked down, Jin's throws). */
                if(advanced && ((record>=0x80000000u && record<0x80200000u) || source_record(record))) {
                    uint32_t bits=psx_mod_read_word(record+0x24);
                    flag=bits&0x40000?1:(psx_mod_read_word(record+4)&4) && !(bits&0x40000000)?2:0;
                }
                if(advanced && source_record(record)) {
                    uint32_t prop=psx_mod_read_word(record+32);
                    for(unsigned i=0;i<256;i++,prop+=4) {
                        unsigned at=psx_mod_read_half(prop),op=psx_mod_read_half(prop+2);
                        if(!at)break;
                        if(op>>8>=0x40 && op>>8<=0x45 && previous<at && at<=frame) {
                            expression=op>>8==0x40?1:op>>8==0x41?0:(int)(op>>8)-0x40;
                            duration=op&255;
                        }
                    }
                }
                if(tekken3_ttt1_player_motion_mode(player)==2 && !tekken3_devil_jin_player(player))
                    tekken3_ttt1_face_tick(player,advanced,expression,duration,flag);
            }
            else hit_effect_in_fight[player]=0;
            continue;
        }
        hit_effect_in_fight[player]=0;
        PlayerCombat *p=&players[player];
        if(p->native_base && psx_mod_read_word(0x800adc20+player*4)==p->header)
            psx_mod_write_word(0x800adc20+player*4,p->native_base);
        p->native_base=0;
    }
}
void __wrap_func_8002D178(CPUState *cpu) {
    unsigned player=cpu->gpr[4]==0x800aaab4?1:0;
    unsigned id=(uint16_t)cpu->gpr[5];
    if((cpu->pc==0 || cpu->pc==0x8002d178) && id>=SLOT_BASE && id<SLOT_BASE+2*SLOT_STRIDE) {
        /* A guest move ID names its graph: a reaction row can animate the
         * other fighter, whose own graph may be another guest's or native. */
        unsigned s=(id-SLOT_BASE)/SLOT_STRIDE,index=(id-SLOT_BASE)%SLOT_STRIDE;
        unsigned native=slots[s].loaded && index<slots[s].count?slots[s].recovery[index]:0;
        /* Not while the victim still plays one of the guest's unique clips:
         * the throw goes on as a pair. Jack-2's victim clip 809 ends on
         * record 78, the ground state that is also engine alias 0x9C; sent to
         * its own 0x9C, the victim stopped at frame 1 and the thrower (810)
         * at frame 62 of 194, before the laughs. Leaving 78 (get-up), it
         * takes its own moves as before. */
        if(slots[s].loaded && index<slots[s].count && players[s].records) {
            uint32_t base=players[s].records,end=base+slots[s].count*56;
            uint32_t current=psx_mod_read_word(cpu->gpr[4]+0x54);
            uint32_t thrower=psx_mod_read_word(0x800a9228+s*0x188c+0x54);
            /* Nor while the guest still plays its own side of the throw (a
             * unique clip of its own: Jack-2's 810 lasts 194 frames, past the
             * victim's 78 - leaving it early froze both at frame 122). The
             * throw is known by the guest's throw flag (+0x74 > 0, 1 through
             * all of 810): a record without an engine alias alone also means
             * the guest's stance, and a victim waiting for that - Kuma thrown
             * by Kazuya - got up with the guest's clips and the CPU then
             * played the guest's moves through them. */
            int throwing=(int16_t)psx_mod_read_half(0x800a9228+s*0x188c+0x74)>0;
            int unique_throw=s!=player && throwing && thrower>=base && thrower<end && (thrower-base)%56==0 &&
                             !slots[s].recovery[(thrower-base)/56];
            int on_guest=current>=base && current<end && (current-base)%56==0;
            /* A victim's unique clip only holds it while the throw goes on: a
             * plain hit's reaction (Paul's 422, crouched) would have kept the
             * CPU in the attacker's crouch 15 for its 70 frames. */
            if((on_guest && !slots[s].recovery[(current-base)/56] && (throwing || s==player)) || unique_throw)
                native=0;
            /* The other way round: out of the unique clips, on a record with
             * an engine alias, towards one without. Paul's TTT1 moves (native
             * pack, 284 aliases) end a crouched reaction (422) on his crouch
             * 15 (alias 40), which loops with 16 (none): a CPU hit there
             * crouched in Paul's clips until the next hit. It takes its own
             * entry for the record it stands on. */
            else if(!native && s!=player && on_guest)
                native=slots[s].recovery[(current-base)/56];
        }
        if(native && cpu->gpr[4]==0x800a9228+player*0x188c &&
           !(player==s && ttt1_moves(player))) {
            /* Another fighter (a throw's victim) left the guest's unique
             * clip for an engine entry - get-up, crouch, stance: it takes
             * its own, from its own table, not the guest's graph. */
            cpu->gpr[5]=native-1;
            if(psx_mod_read_half(cpu->gpr[4]+0x1a0)==id)psx_mod_write_half(cpu->gpr[4]+0x1a0,native-1);
            __real_func_8002D178(cpu);return;
        }
        if(slots[s].loaded && index<slots[s].count && ready(s)) {
            cpu->gpr[2]=players[s].records+index*56;cpu->pc=cpu->gpr[31];return;
        }
    }
    if((cpu->pc==0 || cpu->pc==0x8002d178) && cpu->gpr[4]==0x800a9228+player*0x188c && ready(player)) {
        const GuestCombat *c=&slots[player];
        static unsigned char reported[2][4023];
        if(id<4023 && id!=3 && !c->native_aliases[id] && !reported[player][id] &&
            psx_mod_read_word(players[player].alias_table+id*4)==players[player].records+c->neutral*56) {
            reported[player][id]=1;fprintf(stderr,"%s combat: unmapped native entry %04X requested by P%u\n",tekken3_guest_name_for(player),id,player+1);
        }
        if(id==3) {
            cpu->gpr[2]=players[player].records+c->neutral*56;cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_8002D178(cpu);
}
static const uint16_t *pose(uint32_t clip,int frame) {
    for(unsigned k=0;k<4;k++) {
        const GuestCombat *c=k<2?&slots[k]:&retired[k-2];
        if(!c->loaded || clip<c->guest)continue;
        unsigned index=0;
        while(index<c->count && c->clip_addresses[index]!=clip)index++;
        if(index==c->count)continue;
        unsigned offset=c->clip_offsets[index],n=word(c->data+offset)&255;
        if((word(c->data+offset)&0xffffff00)!=0x4a554e00 || word(c->data+offset+4)!=57 || !n || offset+8+n*114>c->size)return NULL;
        if(frame<0)frame=0;if((unsigned)frame>=n)frame=n-1;
        return (const uint16_t*)(c->data+offset+8+frame*114);
    }
    return NULL;
}
const uint16_t *tekken3_ttt1_decoded_pose(uint32_t input) {
    if(psx_mod_read_word(input+8)!=0x504e554a)return NULL;
    uint32_t clip=psx_mod_read_word(input+12);
    return pose(clip,psx_mod_read_half(input+16));
}
static int decode_pose(CPUState *cpu,int full) {
    const uint16_t *p=pose(cpu->gpr[4],(int)cpu->gpr[6]);if(!p)return 0;
    uint32_t out=cpu->gpr[5],angle=p[0],table=0x8001e8c4+((angle>>3)&0x1ffe);
    int32_t s=(int16_t)psx_mod_read_half(table),c=(int16_t)psx_mod_read_half(table+0x800),distance=(int16_t)p[2];
    if(full)for(unsigned i=0;i<49;i++)psx_mod_write_half(out+i*2,0);
    psx_mod_write_half(out,(uint16_t)((s*distance)>>12));
    psx_mod_write_half(out+2,(uint16_t)-(int16_t)p[1]);
    psx_mod_write_half(out+4,(uint16_t)((c*distance)>>12));
    if(full) {
        psx_mod_write_word(out+8,0x504e554a);
        psx_mod_write_word(out+12,cpu->gpr[4]);
        psx_mod_write_half(out+16,(uint16_t)((int)cpu->gpr[6]<0?0:cpu->gpr[6]));
    }
    cpu->pc=cpu->gpr[31];return 1;
}
void __wrap_func_80038B4C(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x80038b4c) && decode_pose(cpu,1))return;
    __real_func_80038B4C(cpu);
}
void __wrap_func_800389C0(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x800389c0) && decode_pose(cpu,0))return;
    __real_func_800389C0(cpu);
}
