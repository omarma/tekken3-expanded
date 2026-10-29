/* Source-derived solo combat adapter. See combat-report.json for coverage. */
#include "psx_runtime.h"
#include "mod_plugins.h"
#include "tekken3_ttt1_pack.h"
#include "tekken3_ttt1_assets.h"
#include "tekken3_fight_camera.h"
#include "gpu_render.h"
#include "gpu.h"
#if defined(PSX_DEBUG_SERVER_LITE) || !defined(PSX_NO_DEBUG_TOOLS)
#include "host_osd.h"
#endif
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
extern void tekken3_jin_omen_face(unsigned player,unsigned character,int advanced,int expression,unsigned duration);
extern int tekken3_cine_engine_frame(void);
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
extern void __real_func_80056764(CPUState *cpu);
extern void __real_func_8002C580(CPUState *cpu);
static unsigned char cpu_decided[2];
extern void __real_func_8006A3BC(CPUState *cpu);
extern void __real_func_8002D264(CPUState *cpu);
extern void __real_func_8002E8D0(CPUState *cpu);
extern void __real_func_8002D8B4(CPUState *cpu);
extern void __real_func_8002E0BC(CPUState *cpu);
extern void __real_func_8002A914(CPUState *cpu);
extern void __real_func_8002D07C(CPUState *cpu);
extern void func_8002CA84(CPUState *cpu);
/* Each player's guest has its own slot: player 1's guest is slot 0, player
 * 2's slot 1, so the two can be different characters. Guest move IDs are
 * 8192+i for slot 0 and 8192+4096+i for slot 1: a move that animates the
 * other fighter (a throw's victim) still names its own graph. The reaction,
 * pushback and counter tables of both guests are merged into the one set the
 * engine reads (install_tables). */
enum { RECORDS_MAX=2048 };
/* T3's fire breath: True Ogre's ID, the effect limb of his breaths (records
 * 311, 366, 3962 of his own moves). T3's mist: effect limb 25, Nina's Evil
 * Mist and Yoshimitsu's Poison Breath on their own moves, the same as TTT1's
 * virtual limb 25 (0x8006F0F4 -> 0x8006ECA4: a cloud of effect objects from
 * the head, whose capsules hit). */
enum { TRUE_OGRE=20, EFFECT_FIRE_LIMB=24, EFFECT_MIST_LIMB=25 };
/* TTT1 numbers the points of Yoshimitsu's sword 22 (tip) and 23 (middle of
 * the blade); his T3 model has them as bones 18 and 19, which his own win
 * poses light on. Timed properties 6..10 (0x800458C8) light an effect at the
 * world position of the bone in their argument: on the native, the slots of
 * bones 20..23 stay at (0, 0, 0), the arena's centre (B48, GH#73). */
enum { YOSHIMITSU=4, TTT1_SWORD_TIP=22, TTT1_SWORD_MID=23, T3_SWORD_TIP=18, T3_SWORD_MID=19 };
static void native_effect_bones(unsigned s,unsigned char *prop) {
    if(tekken3_native_moves_id(s)!=YOSHIMITSU)return;
    unsigned kind=prop[3],bone=prop[2];
    if(kind<6 || kind>10)return;
    if(bone==TTT1_SWORD_TIP)prop[2]=T3_SWORD_TIP;
    else if(bone==TTT1_SWORD_MID)prop[2]=T3_SWORD_MID;
}
enum { SLOT_BASE=8192, SLOT_STRIDE=4096, ALIAS_ENTRIES=SLOT_BASE+2*SLOT_STRIDE,
       NATIVE_ROWS=633, NATIVE_PUSH=0xce8-0x75c, NATIVE_COUNTERS=(0x7c10-0x77dc)/4 };
typedef struct {uint16_t source,native;unsigned count;uint32_t clips[128];} ContactGroup;
/* A 64 x 64 strong-hit effect pack (TTT Hitspark, below). */
typedef struct { unsigned char *data; unsigned images,palettes,flags; } Hfx;
typedef struct {
    unsigned generation;int attempted,loaded;
    unsigned char *data;uint32_t guest,size,count,records,neutral;
    /* Bytes at guest: header, records, then each record's clip header and
     * cancel list (load_combat). */
    uint32_t guest_size;
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
     * fragment is optional, emitted only when non-empty. Only rows flagged
     * OPPONENT_APPLIED are applied (opponent_rule_holds); the others keep
     * their rule for everyone. */
    struct {unsigned record,rule,opponent;} opponent_cancels[64];unsigned opponent_cancel_count;
    /* Fragment DEFR (optional): records the defender plays from this pack as
     * its own moves, the Jacks' haywire after a laser (SELF_MOVESET). */
    uint16_t defender_records[64];unsigned defender_count;
    /* The pack's tables, native parts included: nr rows of 42 bytes, np
     * pushback bytes, nc counters; and its event scripts (EVNT). */
    unsigned char *tables;unsigned nr,np,nc;
    /* Records the pack's own reaction rows put a hit fighter on (B73). */
    unsigned char reaction_records[SLOT_STRIDE];
    unsigned char *events;unsigned event_bytes;
    unsigned char *hit_effect;unsigned hit_effect_frames;int hit_effect_attempted;
    /* The same effect in 64 x 64 (TTT Hitspark): <Name>-TTT1-hiteffect64.hfx. */
    Hfx hfx;
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
    free(c->data);free(c->tables);free(c->events);free(c->hit_effect);free(c->hfx.data);
    memset(c,0,sizeof *c);
}
/* Unknown's hand bone that holds her blade (limb_position). */
enum { BLADE_BONE=10 };
typedef struct {
    uint32_t native_base,native_common,alias_table,original_alias,header,records,source,hit_bones;
    unsigned char *lasers;     /* beam type per record, 0 when not a laser */
    uint32_t *blades;          /* limbs of a record hitting with Unknown's blade, else 0 */
    /* True Ogre's breath on Gon (gon_breath_rule): the scratch copy of the
     * breath record, and the breath's list with T3's rule first. */
    uint32_t gon_breath,gon_rules;unsigned gon_rule_room;
    /* What the records were built for: the slot's identity, its offsets in
     * the merged tables, the other player's guest records, and the engine's
     * last link of the two alias tables (__wrap_func_8002D07C). */
    unsigned generation,rx_shift,counter_shift,other_generation,links;uint32_t other_records;
} PlayerCombat;
static PlayerCombat players[2];
/* How many times the engine has finished linking the two alias tables. */
static unsigned alias_links;
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
/* Tekken Ball's walk and dash boost (B41, GH#94). Every frame the Ball
 * overlay (0x800B068C) rewrites each player's 6-byte entry at 0x800B6678
 * from the T3 move number at actor +0xA0: 24 and 26 (back walk, back step)
 * get 30 units a frame, frames 3..9; 30 and 32 (the backdash's start) 150 a
 * frame, frames 5..12, and an early exit at frame 18 (byte 5, read at
 * 0x8002DB9C), which 31 and 33 also get. 0x8003F5C4 pushes the fighter
 * backwards (+0 angle 0x8000) by that much. A fighter on TTT1 moves plays
 * pack numbers (8192 + i), so the entry stayed empty: a plain backdash
 * (about 745) where the T3 one goes about 1935. Its own records with one of
 * those engine aliases (recovery) get the same entry, just before each of
 * the two readers (tools/build_ttt1_combat_hooks.py). */
void tekken3_ttt1_ball_boost(uint32_t actor) {
    unsigned player=psx_mod_read_half(actor+0x12);
    uint32_t record=psx_mod_read_word(actor+0x54);
    if(player>1 || record_owner(record)!=(int)player)return;
    unsigned alias=slots[player].recovery[(record-players[player].records)/56];
    if(!alias)return;
    uint32_t entry=0x800b6678+player*6;
    switch(alias-1) {
    case 24: case 26:
        psx_mod_write_half(entry,0x8000);psx_mod_write_byte(entry+2,30);
        psx_mod_write_byte(entry+3,3);psx_mod_write_byte(entry+4,9);break;
    case 30: case 32:
        psx_mod_write_half(entry,0x8000);psx_mod_write_byte(entry+2,150);
        psx_mod_write_byte(entry+3,5);psx_mod_write_byte(entry+4,12);psx_mod_write_byte(entry+5,18);break;
    case 31: case 33:
        psx_mod_write_byte(entry+5,18);break;
    }
}
/* Yoshimitsu's sword breaks the ball in Tekken Ball (B92, GH#146). The Ball
 * overlay (ball_move, 0x800B1734) breaks it on an unblockable hit (move id
 * +0x64 0x607 or 0x706) by moves key 4, Yoshimitsu's, unless the move is the
 * throw 0x181 or strikes with an effect capsule; any other unblockable sends
 * it homing. Every guest fights with key 23: Unknown on Yoshimitsu's moves
 * sent it. The overlay is interpreted, so its test is rewritten in place (the
 * same 17 words, load delays filled instead of nops) to take the key from a
 * mask in the immediate at 0x800B1738, a bit per player whose moves are
 * Yoshimitsu's as the hit rules read them (fighter_moveset): the native on
 * either moveset, Mokujin drawing his, a guest on his TTT1 moves. Only while
 * such a guest fights, checked every frame (the fight's guest ticks stop
 * without one); otherwise the overlay's own words are put back. */
enum { BALL_SWORD_SITE=0x800b1734u, BALL_SWORD_WORDS=17, BALL_SWORD_MASK=1, BALL_SWORD_KEY=4 };
static const uint32_t ball_sword_stock[BALL_SWORD_WORDS]={
    0x86430016,0x00000000,0x14620023,0x24020607,0x96430064,0x00000000,0x10620003,0x24020706,0x1462001d,
    0x00000000,0x32e20008,0x1440001a,0x24020181,0x864300a0,0x00000000,0x10620016,0x00000000};
static const uint32_t ball_sword_bits[BALL_SWORD_WORDS]={
    0x86410012,   /* lh   at, 0x12(s2)      player */
    0x24030000,   /* li   v1, mask          bit 0/1: that player's moves are Yoshimitsu's */
    0x00231806,   /* srlv v1, v1, at */
    0x30630001,   /* andi v1, v1, 1 */
    0x96410064,   /* lhu  at, 0x64(s2)      move id */
    0x10600020,   /* beqz v1, 0x800B17CC    no sword: the other hits */
    0x864300a0,   /*  lh  v1, 0xA0(s2)      move number */
    0x24020607,   /* li   v0, 0x607 */
    0x10220003,   /* beq  at, v0, unblockable */
    0x24020706,   /*  li  v0, 0x706 */
    0x1422001b,   /* bne  at, v0, 0x800B17CC */
    0x00000000,
    0x32e20008,   /* unblockable: andi v0, s7, 8   effect capsule */
    0x14400018,   /* bnez v0, 0x800B17CC */
    0x24020181,   /*  li  v0, 0x181         the throw */
    0x10620016,   /* beq  v1, v0, 0x800B17CC */
    0x00000000};  /* then 0x800B1778: the ball breaks */
void tekken3_ttt1_ball_sword_tick(void) {
    if(psx_mod_read_word(0x800ae204)!=8 || psx_mod_read_byte(0x800afa88)!=7)return;
    unsigned mask=0,guest=0,stock=1,patched=1;
    for(unsigned p=0;p<2;p++) {
        uint32_t actor=0x800a9228+p*0x188c;
        if(fighter_moveset(actor)!=BALL_SWORD_KEY)continue;
        mask|=1u<<p;guest|=psx_mod_read_half(actor+0x16)==23;
    }
    for(unsigned i=0;i<BALL_SWORD_WORDS;i++) {
        uint32_t w=psx_mod_read_word(BALL_SWORD_SITE+i*4);
        stock&=w==ball_sword_stock[i];
        patched&=i==BALL_SWORD_MASK?(w&0xffff0000u)==ball_sword_bits[i]:w==ball_sword_bits[i];
    }
    if(!stock && !patched)return;     /* another overlay there */
    for(unsigned i=0;i<BALL_SWORD_WORDS;i++) {
        uint32_t w=guest?ball_sword_bits[i]|(i==BALL_SWORD_MASK?mask:0):ball_sword_stock[i];
        if(psx_mod_read_word(BALL_SWORD_SITE+i*4)!=w)psx_mod_write_code_word(BALL_SWORD_SITE+i*4,w);
    }
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
    for(unsigned i=NATIVE_ROWS;i<nr;i++)for(unsigned k=0;k<14;k++) {
        unsigned t=ttt1_pack_half(p+i*42+k*2);
        if(t>=slot_base(s) && t<slot_base(s)+c->count)c->reaction_records[t-slot_base(s)]=1;
    }
    c->events=event_bytes?malloc(event_bytes):NULL;
    if(event_bytes && !c->events){free(p);return 0;}
    if(event_bytes)memcpy(c->events,p+event_offset,event_bytes);
    c->event_bytes=event_bytes;
    c->tables=p;c->nr=nr;c->np=np;c->nc=nc;
    return 1;
}
/* Yoshimitsu's sitting win pose (T3 alias 0xD68, TTT1 0x1293) lights his
 * effect at frame 205, but the arcade starts the next round at frame 201
 * (MAME): the spark is never seen there. T3 lets the pose run on: at 205
 * the sword is at the end of its forward cut and whips back three frames
 * later, leaving the spark in the air (B48). Whoever plays his TTT1 moves
 * (the native, Unknown) lights it at frame 191 instead, as the cut arrives:
 * the blade then stays out over the spark until 206 (B60, GH#73). */
enum { WIN_SITTING=0xd68, WIN_SITTING_CUT=191, YOSHIMITSU_MOVES=4 };
static void sitting_pose_effect(unsigned s,const GuestCombat *c) {
    unsigned target=c->native_aliases[WIN_SITTING];
    if(tekken3_guest_moveset(s)!=YOSHIMITSU_MOVES || target<SLOT_BASE || target-SLOT_BASE>=c->count)return;
    uint32_t props=psx_mod_read_word(c->guest+c->records+(target-SLOT_BASE)*56+32);
    for(uint32_t at=props;;at+=4) {
        uint32_t prop=psx_mod_read_word(at);
        unsigned kind=prop>>24&255;
        if(!(prop&0xffff))break;
        if(kind>=6 && kind<=10)psx_mod_write_word(at,(prop&~0xffffu)|WIN_SITTING_CUT);
    }
}
static int load_combat(unsigned s) {
    follow_identity(s);
    GuestCombat *c=&slots[s];
    if(c->attempted)return c->loaded;c->attempted=1;
    const char *root=tekken3_ttt1_asset_root();if(!root)return 0;
    char path[4096];FILE *f;
    snprintf(path,sizeof path,"%s/%s-combat.jmv",root,tekken3_guest_moves_prefix_for(s));
    if(!(f=fopen(path,"rb")))return 0;
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
     * its cancel destinations, now that the pack has been checked. Records
     * may share a cancel list (records copied from the stance by
     * tools/ttt1/pack_edit.py, as the old way's ending packs were): each
     * entry moves once. Moved once per record, the stance's destinations
     * went past 0x8000 for the CPU's Kazuya and Devil, read as negative
     * aliases: stray records (B30). */
    unsigned char *moved=s?calloc(c->size/8+1,1):NULL;
    if(s && !moved){free(c->data);c->data=NULL;return 0;}
    if(s)for(unsigned i=0;i<c->count;i++) {
        uint32_t rp=c->records+i*56,cp=word(c->data+rp+12),n=word(c->data+32+i*16+12);
        if(ttt1_pack_half(c->data+rp+16)>=SLOT_BASE)put_half(c->data+rp+16,ttt1_pack_half(c->data+rp+16)+s*SLOT_STRIDE);
        for(unsigned j=0;j<n;j++) {
            uint32_t at=cp+j*12+6;
            if(moved[at>>3]&1u<<(at&7))continue;
            moved[at>>3]|=(unsigned char)(1u<<(at&7));
            unsigned char *e=c->data+at;
            if(ttt1_pack_half(e)>=SLOT_BASE)put_half(e,ttt1_pack_half(e)+s*SLOT_STRIDE);
        }
    }
    free(moved);
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
    c->guest_size=compact;
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
        do {native_effect_bones(s,c->data+props+j*4);
            for(unsigned k=0;k<4;k++)psx_mod_write_byte(c->guest+cursor+k,c->data[props+j*4+k]);cursor+=4;}
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
    if(!load_tables(s,root)) {
        /* The fighter falls back to its T3 moves. Test builds (debug server
         * or debug tools) say so on screen too, an old or damaged pack being
         * otherwise only in the log (B50); the public build keeps the log. */
        char msg[128];
        snprintf(msg,sizeof msg,"%s: TTT1 moves not loaded (tables rejected), see the log",tekken3_guest_name_for(s));
        fprintf(stderr,"%s\n",msg);
#if defined(PSX_DEBUG_SERVER_LITE) || !defined(PSX_NO_DEBUG_TOOLS)
        host_osd_push(msg,6000);
#endif
        return 0;
    }
    sitting_pose_effect(s,c);
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
    /* A slot left by its player (a native back on Tekken 3 moves: its
     * identity moved on, its moves are not played) is no part of them. */
    for(unsigned s=0;s<2;s++)key[s]=slots[s].loaded && slots[s].tables &&
        (ttt1_moves(s) || slots[s].generation==tekken3_guest_moves_generation(s))?slots[s].generation:0;
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
/* True Ogre's 1+2 breath on Gon (B120, GH#170). Gon breathes fire himself:
 * in T3 he takes a scratch. The breath 0x137 opens on an automatic rule
 * (command 0x0010, frames 1..10) towards 0xF7A when the opponent's move key
 * is Gon's (key test 0x42 = 0x2F + 19, cancel_next 0x8002DE24): the same
 * breath, for 1 damage and reaction row 0x220 (Gon's 0xA57, then his
 * stance). TTT1 has no Gon: its breath (Hell's Flame, active on 0x137's
 * frames 58..126) burnt him for 39 and floored him. The pack's breath takes
 * T3's rule first, towards a copy of itself with 0xF7A's damage and
 * reaction, which alias 0xF7A names. T3 always enters 0x137 at frame 1;
 * the pack enters its breath at frame 12 from the rising states (records
 * 492..517), so the rule holds up to the frame before the flames. The
 * other breath (0x16E, d/f+1+2) has no such rule: it passes over Gon in
 * both games. */
enum { T3_BREATH=0x137 };
static void gon_breath_rule(unsigned player) {
    const GuestCombat *c=&slots[player];
    PlayerCombat *p=&players[player];
    if(tekken3_native_moves_id(player)!=TRUE_OGRE)return;
    uint32_t breath=psx_mod_read_word(p->original_alias+T3_BREATH*4),rule=0;
    if(breath<0x80010000 || breath>0x801fffc8)return;
    uint32_t list=psx_mod_read_word(breath+12);
    for(unsigned k=0;k<64 && list>=0x80010000 && list<=0x801ffff4;k++,list+=12) {
        unsigned command=psx_mod_read_half(list),key=psx_mod_read_byte(list+2);
        if(command==0xc000)break;
        if(command==0x10 && key>=0x2f && key<0x46){rule=list;break;}  /* the opponent's key */
    }
    unsigned target=rule?psx_mod_read_half(rule+6):4023;
    uint32_t scratch=target<4023?psx_mod_read_word(p->original_alias+target*4):0;
    if(scratch<0x80010000 || scratch>0x801fffc8)return;
    for(unsigned i=0;i<c->count;i++) {
        uint32_t dst=p->records+i*56,own=psx_mod_read_word(dst+12);
        if(psx_mod_read_byte(psx_mod_read_word(dst+40))!=EFFECT_FIRE_LIMB ||
           psx_mod_read_byte(dst+45)!=psx_mod_read_byte(breath+45) || psx_mod_read_byte(dst+46)!=psx_mod_read_byte(breath+46))continue;
        unsigned n=1;
        while(n<1024 && psx_mod_read_half(own+(n-1)*12)!=0xc000)n++;
        if(!p->gon_breath)p->gon_breath=tekken3_guest_pool_alloc(player,56,16);
        if(p->gon_rule_room<n+1){p->gon_rules=tekken3_guest_pool_alloc(player,(n+1)*12,4);p->gon_rule_room=p->gon_rules?n+1:0;}
        if(!p->gon_breath || !p->gon_rules)return;
        for(unsigned j=0;j<56;j+=4)psx_mod_write_word(p->gon_breath+j,psx_mod_read_word(dst+j));
        psx_mod_write_half(p->gon_breath+0x14,psx_mod_read_half(scratch+0x14));    /* damage */
        psx_mod_write_byte(p->gon_breath+0x2c,psx_mod_read_byte(scratch+0x2c));    /* hitstun */
        psx_mod_write_half(p->gon_breath+0x32,psx_mod_read_half(scratch+0x32));    /* reaction row */
        psx_mod_write_half(p->gon_breath+0x34,psx_mod_read_half(scratch+0x34));    /* counter index */
        for(unsigned j=0;j<12;j+=4)psx_mod_write_word(p->gon_rules+j,psx_mod_read_word(rule+j));
        unsigned last=psx_mod_read_byte(dst+45)-1u;
        if(last>psx_mod_read_byte(rule+10) && last<255)psx_mod_write_byte(p->gon_rules+10,(unsigned char)last);
        for(unsigned j=0;j<n*12;j+=4)psx_mod_write_word(p->gon_rules+12+j,psx_mod_read_word(own+j));
        psx_mod_write_word(dst+12,p->gon_rules);
        psx_mod_write_word(p->alias_table+target*4,p->gon_breath);
        fprintf(stderr,"%s combat: P%u breath record %u takes T3's rule on Gon (0x%X -> 0x%X, %d damage)\n",
                tekken3_guest_name_for(player),player+1,i,T3_BREATH,target,(int16_t)psx_mod_read_half(scratch+0x14));
        return;
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
       p->other_generation!=slots[other].generation || p->links!=alias_links) {
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
            /* The mist: the engine's own cloud, its hit and its sound. */
            else if((limbs&255)==TTT1_PACK_MIST_LIMB)limbs=(limbs&~255u)|EFFECT_MIST_LIMB;
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
        gon_breath_rule(player);
        psx_mod_write_word(p->header+12,p->alias_table);
        /* A guest's moves go by key 23; a native on its TTT1 moves and Devil
         * Jin keep their own key, which the other fighter's rules test. */
        if(tekken3_ttt1_roster_enabled() && tekken3_ttt1_player_motion_mode(player)==2 &&
           !tekken3_devil_jin_player(player))psx_mod_write_byte(p->header+1,23);
        /* Native cache headers may be shared by two actors. Keep them intact. */
        psx_mod_write_word(slot,p->header);
        p->native_base=base;p->native_common=common;p->source=source;
        p->generation=c->generation;p->rx_shift=rx_shift[player];p->counter_shift=counter_shift[player];
        p->other_records=other_records;p->other_generation=slots[other].generation;p->links=alias_links;
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
 * A guest with donors (Tetsujin) draws one here, Unknown takes her own back
 * (tekken3_guest_draw_moveset), and their moves are rebuilt
 * before the routine puts the fighters back in their stance. Only on entry:
 * a sliced call resumes through this wrapper with pc at the resume point. */
void __wrap_func_8002A914(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8002a914) && tekken3_ttt1_roster_enabled())
        for(unsigned p=0;p<2;p++)if(tekken3_guest_draw_moveset(p))ready(p);
    __real_func_8002A914(cpu);
}
/* As a fight loads (0x8006A158), 0x8002D07C links the two players' alias
 * tables: an alias missing from one fighter's file takes the other's record
 * (reactions stored with the attacker: Paul hit by Bryan's d/f+4 plays
 * 0xAD6, a record of Bryan's file). Each player's table is the one its slot
 * header (0x800ADC20 + 4 * player) names. A custom table is a copy of that
 * table, made by ready(); the routine is sliced over frames, and a copy made
 * between two slices kept the links of the fighter before: in Team Battle,
 * Paul on his TTT1 moves facing Mokujin after Angel played Jin's file's
 * record there, cut to his stance at once (B81). The links go to the native
 * tables, the custom ones are copied again once the routine has returned. */
void __wrap_func_8002D07C(CPUState *cpu) {
    static uint32_t caller;
    uint32_t custom[2]={0,0};
    if(cpu->pc==0 || cpu->pc==0x8002d07c) {
        caller=cpu->gpr[31];
        for(unsigned p=0;p<2;p++) {
            uint32_t slot=0x800adc20+p*4;
            if(players[p].header && psx_mod_read_word(slot)==players[p].header) {
                custom[p]=players[p].header;psx_mod_write_word(slot,players[p].native_base);
            }
        }
    }
    __real_func_8002D07C(cpu);
    for(unsigned p=0;p<2;p++)if(custom[p])psx_mod_write_word(0x800adc20+p*4,custom[p]);
    if(caller && cpu->pc==caller){caller=0;alias_links++;}
}
/* Moves of a fighter on its Tekken 3 moves (actor +0xA0) and their TTT1
 * alias, for the on-hit rules that name an opponent's move (condition 74) or
 * a TTT1 group of clips (75). The standard throws, 1+3 and 2+4 (T3 0xAE8 /
 * 0xAEC, TTT1 0xEDC / 0xEE0), are in TTT1's group 0x19C, which Tekken 3
 * lacks: Anna's Chaos Judgement (records 303 / 304, aliases 0x539 / 0x53A,
 * Unknown's in her style alike) parries them there, the only such rule of
 * the 72 packs (B90). */
static const struct { uint16_t ttt1,t3; } t3_twins[]={
    {0x125,0xf7},{0x45a,0x351},{0x47f,0x36f},{0xb56,0x85d},{0xedc,0xae8},{0xee0,0xaec},
};
static unsigned t3_twin(unsigned ttt1) {
    for(unsigned i=0;i<sizeof t3_twins/sizeof *t3_twins;i++)if(t3_twins[i].ttt1==ttt1)return t3_twins[i].t3;
    return 0xffff;
}
/* Whether the fighter on Tekken 3 moves whose clip is anim plays the twin of
 * a move of group g: that move's TTT1 clip in slot s's pack. */
static int t3_move_in_group(unsigned s,const ContactGroup *g,uint32_t anim) {
    for(unsigned p=0;p<2;p++) {
        uint32_t actor=0x800a9228+p*0x188c,record=psx_mod_read_word(actor+0x54);
        if(!record || record_owner(record)>=0 || psx_mod_read_word(record)!=anim)continue;
        unsigned move=psx_mod_read_half(actor+0xa0);
        for(unsigned t=0;t<sizeof t3_twins/sizeof *t3_twins;t++) {
            uint32_t source=t3_twins[t].t3==move?slots[s].source_aliases[t3_twins[t].ttt1]:0;
            for(unsigned i=0;source && i<slots[s].count;i++)if(word(slots[s].data+36+i*16)==source) {
                unsigned clip=word(slots[s].data+32+i*16);
                for(unsigned k=0;k<g->count;k++)if(g->clips[k]==clip)return 1;
            }
        }
    }
    return 0;
}
void __wrap_func_8002D264(CPUState *cpu) {
    unsigned param=(uint16_t)cpu->gpr[5];
    if((cpu->pc==0 || cpu->pc==0x8002d264) && (slots[0].loaded || slots[1].loaded) && (param&0x4000)) {
        /* Contact groups are TTT1's global motion lists: the same source ID
         * names the same group in every guest's pack. */
        const ContactGroup *g=NULL;
        unsigned owner=0;
        for(unsigned s=0;s<2 && !g;s++)if(slots[s].loaded)
            for(unsigned i=0;i<slots[s].group_count;i++)if(slots[s].groups[i].source==(param&0x3fff)){g=&slots[s].groups[i];owner=s;}
        if(g) {
            for(unsigned s=0;s<2;s++)if(slots[s].loaded)for(unsigned i=0;i<slots[s].count;i++)
                if(slots[s].clip_addresses[i]==cpu->gpr[4]) {
                    unsigned clip=word(slots[s].data+32+i*16),match=0;
                    for(unsigned k=0;k<g->count;k++)if(g->clips[k]==clip)match=1;
                    cpu->gpr[2]=match;cpu->pc=cpu->gpr[31];return;
                }
            if(g->native==0xffff){cpu->gpr[2]=t3_move_in_group(owner,g,cpu->gpr[4]);cpu->pc=cpu->gpr[31];return;}
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
        unsigned native=t3_twin(alias);
        if(native!=0xffff && psx_mod_read_half(attacker+0xa0)==native)match=1;
        match=match && (int16_t)psx_mod_read_half(defender+0x30)<0x2aaa &&
                       (int16_t)psx_mod_read_half(attacker+0x30)<0x2aaa;
        cpu->gpr[2]=match;cpu->pc=cpu->gpr[31];return;
    }
    __real_func_8002E8D0(cpu);
}
/* 0x8002D8B4 (a0 a fighter hit this frame, +0xCE; a1 its opponent as
 * 0x80045C18 names it) reads the on-hit rules of the fighter's record
 * (0x8002E708, conditions 69..75: the opponent's move or clip). For a fighter
 * hit during its move that opponent is the slot in +0x22, which the engine
 * copies from the hit record only as the damage is applied, after this pass:
 * the attacker of the hit before, and player 1 itself until it is first hit.
 * Player 1's Chaos Judgement then looked for a throw in its own clip and
 * never parried (B90); player 2's slot 0 was right by chance. TTT1
 * (0x800FC654 -> 0x80101794) passes the other fighter. A fighter on a TTT1
 * pack gets the attacker of its hit record in use (+0x13C, two of 0x2C
 * bytes: attacker +0x20, in use +0x21); one on its Tekken 3 moves keeps the
 * engine's way. */
void __wrap_func_8002D8B4(CPUState *cpu) {
    uint32_t actor=cpu->gpr[4];
    unsigned player=actor==0x800aaab4;
    if((cpu->pc==0 || cpu->pc==0x8002d8b4) && actor==0x800a9228+player*0x188c &&
       psx_mod_read_byte(actor+0xce) && record_owner(psx_mod_read_word(actor+0x54))==(int)player)
        for(unsigned i=0;i<2;i++)if(psx_mod_read_byte(actor+0x13c+i*0x2c+0x21)) {
            unsigned slot=psx_mod_read_byte(actor+0x13c+i*0x2c+0x20);
            if(slot<3)cpu->gpr[5]=0x800a9228+slot*0x188c;
            break;
        }
    __real_func_8002D8B4(cpu);
}
/* TTT1 lasers (Devil / Angel). Their hit ends on a virtual limb 24 that the
 * arcade's laser routine (80116F8C / 8011707C) places at the tip of a beam:
 * it starts at the head plus an offset and grows every frame from the first
 * frame of the move's active window (length 0 on that frame: t of
 * func_80117544 and the others in the arcade's C, measured image by image
 * by tools/ttt1_laser_frames.lua), then slides along the floor (the tip
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
     * by 200 a frame for 9 frames (1 800), then the tip swings round the yaw
     * by 0x200 a frame between about +-0x3000, at a random length (0..1023)
     * on each horizontal axis (rand() twice: x = n1 sin, z = n2 cos). */
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
    int frame=(int)psx_mod_read_half(actor+0x58),first=psx_mod_read_byte(record+45);
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
            if(n>9) {
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
        if(n>9)n=9;
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
 * move is a laser, the beam has appeared and the active window has not
 * ended (func_80116B68 drops the beam on the first frame past it). */
int tekken3_laser_beam(unsigned p,int32_t v[6],int *fade) {
    if(p>1 || !ttt1_moves(p) || !players[p].records)return 0;
    uint32_t actor=0x800a9228+p*0x188c,record=psx_mod_read_word(actor+0x54),base=players[p].records;
    if(record<base || record>=base+slots[p].count*56 || (record-base)%56)return 0;
    unsigned laser=players[p].lasers?players[p].lasers[(record-base)/56]:0;
    if(!laser)return 0;
    int frame=(int)psx_mod_read_half(actor+0x58);
    if(frame>psx_mod_read_byte(record+46))return 0;
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
/* For the PS2 drawing (src/tekken3_ttt1_ps2_laser.c): the frames since player
 * p's laser move opened its active window (0 on its first frame, where the
 * PS2 draws its first orb), -1 outside a laser move or before the window;
 * s = where the beam starts. */
int tekken3_laser_age(unsigned p,int32_t s[3]) {
    if(p>1 || !ttt1_moves(p) || !players[p].records || !players[p].lasers)return -1;
    uint32_t actor=0x800a9228+p*0x188c,record=psx_mod_read_word(actor+0x54),base=players[p].records;
    if(record<base || record>=base+slots[p].count*56 || (record-base)%56)return -1;
    unsigned laser=players[p].lasers[(record-base)/56];
    int age=(int)psx_mod_read_half(actor+0x58)-psx_mod_read_byte(record+45);
    if(!laser || age<0)return -1;
    int32_t v[6];laser_ends(actor,record,laser&0x7f,v);
    for(unsigned i=0;i<3;i++)s[i]=v[i];
    return age;
}
/* Whether player p's moves hold a laser (Devil's and Angel's). */
int tekken3_ttt1_has_lasers(unsigned p) {
    if(p>1 || !ttt1_moves(p) || !players[p].lasers)return 0;
    for(unsigned i=0;i<slots[p].count;i++)if(players[p].lasers[i])return 1;
    return 0;
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
 * 0x8010A9A8 takes) in the frame of that bone on Yoshimitsu's moveset.
 * Native Yoshimitsu on his TTT1 moves shares the pack, but his T3 model's
 * hand bone is a quarter turn about x from hers: the same points put his
 * blade flat out to the side, where TTT1 holds it straight up in front of
 * him in the Flash (b+1 then 4), and the cut hit an opponent standing
 * against him that the arcade's misses. His sword bones 18 / 19 sit at
 * (103, -723, 0) / (102, -362, 0) in that hand's frame; they are not
 * refreshed every frame, so the hand's matrix with that offset gives the
 * points. */
/* True Ogre's horn tip, TTT1 limb 23 (Buffalo Horn, the end of Demon's
 * Feast): joint 2 moved by (800, 0, 600), the point TTT1 computes on every
 * frame (MAME: fighter + 0xA8C + 23 * 0x50, 1000 from joint 2) and T3 as
 * joint 23 (0x80041F4C, offset 0x8001DC40), but only outside the move's
 * active window: read from the joint, the hit took the horn where it was the
 * frame before the window, up to 1800 below the tip that tosses (B106). */
enum { TTT1_HORN_TIP=23, HORN_BONE=2 };
static void limb_position(uint32_t actor,unsigned limb,uint32_t out[3]) {
    int horn=limb==TTT1_HORN_TIP && tekken3_native_moves_id(actor==0x800a9228?0:1)==TRUE_OGRE;
    if(limb!=TTT1_PACK_BLADE_MID && limb!=TTT1_PACK_BLADE_TIP && !horn) {
        for(unsigned axis=0;axis<3;axis++)out[axis]=psx_mod_read_word(actor+0x908+limb*68+axis*4);
        return;
    }
    uint32_t m=actor+0x8f4+(horn?HORN_BONE:BLADE_BONE)*68;
    int32_t length=limb==TTT1_PACK_BLADE_TIP?727:364;
    int native=tekken3_native_moves_id(actor==0x800a9228?0:1)==YOSHIMITSU;
    const int32_t blade[3]={100,native?-length:0,native?0:length},tip[3]={800,0,600};
    const int32_t *l=horn?tip:blade;
    for(unsigned i=0;i<3;i++) {
        int32_t v=(int32_t)psx_mod_read_word(m+0x14+i*4);
        for(unsigned j=0;j<3;j++)v+=((int16_t)psx_mod_read_half(m+(i*3+j)*2)*l[j])>>12;
        out[i]=(uint32_t)v;
    }
}
/* Yoshimitsu's win poses light their effect on TTT1's points 22 and 23
 * (timed properties 6..10, 0x800458C8 reads actor + 0x908 + 68 * bone). On
 * Unknown they are her blade's, but her T3 model has no such bones: the
 * slots stayed at (0, 0, 0) and the spark lit at the arena's centre (B60,
 * GH#73). While T3 runs a fighter's timed properties, the slots hold the
 * blade's points, then get their own values back. On a continuation (a call
 * the function made) the actor is in s2, where it keeps it. */
extern void __real_func_800458C8(CPUState *cpu);
void __wrap_func_800458C8(CPUState *cpu) {
    uint32_t actor=cpu->pc==0 || cpu->pc==0x800458c8?cpu->gpr[4]:cpu->gpr[18];
    int p=actor==0x800a9228?0:actor==0x800aaab4?1:-1;
    if(p<0 || !tekken3_guest_switches_on_button((unsigned)p) || tekken3_guest_moveset((unsigned)p)!=YOSHIMITSU_MOVES) {
        __real_func_800458C8(cpu);
        return;
    }
    uint32_t saved[2][3];
    for(unsigned k=0;k<2;k++) {
        uint32_t at=actor+0x908+(TTT1_SWORD_TIP+k)*68,pos[3];
        limb_position(actor,k?TTT1_PACK_BLADE_MID:TTT1_PACK_BLADE_TIP,pos);
        for(unsigned i=0;i<3;i++){saved[k][i]=psx_mod_read_word(at+i*4);psx_mod_write_word(at+i*4,pos[i]);}
    }
    __real_func_800458C8(cpu);
    for(unsigned k=0;k<2;k++)for(unsigned i=0;i<3;i++)
        psx_mod_write_word(actor+0x908+(TTT1_SWORD_TIP+k)*68+i*4,saved[k][i]);
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
            if((limbs&255)==EFFECT_FIRE_LIMB || (limbs&255)==EFFECT_MIST_LIMB)break;   /* fire, mist: the engine's own */
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
/* The victim's way out of a reaction (B73). The stagger that Jin's u/f+4
 * leaves (record 707, TTT1 0x8007940C, a record every TTT1 character has)
 * lists, at its 40th frame, back held (0x0930, four facings) towards the
 * guards 804 / 809 / 783 / 787, forward (0x2490) towards 806, 1+2 and 3+4
 * towards 783 / 787. TTT1 (MAME): the victim holding down-back leaves on
 * 783 there and guards the next low hit; refused, it stayed on 707 and every
 * hit of the string landed (Nina's d+3, 2 alike). In all 72 packs, the
 * button and direction entries of the records the pack's reaction rows name
 * lead to clips that cannot hit (no limbs, no damage) - guards, rolls, side
 * rolls - except on some characters' own reactions (118 entries, Anna's
 * chain throws among them): those still need the attacker's say. Not during
 * the attacker's throw (+0x74): a throw's victim clip goes with the
 * thrower's (__wrap_func_8002D178). */
static int reaction_exit(unsigned owner,uint32_t actor,uint32_t entry) {
    const GuestCombat *c=&slots[owner];
    uint32_t base=players[owner].records,record=psx_mod_read_word(actor+0x54);
    if(!c->reaction_records[(record-base)/56])return 0;
    if((int16_t)psx_mod_read_half(0x800a9228+owner*0x188c+0x74)>0)return 0;
    unsigned id=psx_mod_read_half(entry+6);
    if(id<slot_base(owner) || id>=slot_base(owner)+c->count)return 0;
    uint32_t target=base+(id-slot_base(owner))*56;
    return !record_limbs(owner,target) && !psx_mod_read_half(target+0x14);
}
/* A cancel rule on the opponent (fragment DYNC) whose row carries
 * OPPONENT_APPLIED (tools/ttt1/moves.py: Jin's Omen, more damage against
 * Kazuya and Jun, deflected by Jin, Heihachi and Devil) holds only against
 * that TTT1 moveset, read as for SELF_MOVESET. Rows without the flag keep
 * the rule for everyone, as before. The rule is the entry's position in the
 * list of the player's current record (12 bytes an entry). */
enum { OPPONENT_APPLIED=0x100 };
static int opponent_rule_holds(unsigned player,uint32_t actor,uint32_t entry) {
    const GuestCombat *c=&slots[player];
    uint32_t record=psx_mod_read_word(actor+0x54);
    if(!c->opponent_cancel_count || record_owner(record)!=(int)player)return 1;
    uint32_t list=psx_mod_read_word(record+12);
    if(entry<list || (entry-list)%12)return 1;
    unsigned index=(record-players[player].records)/56,rule=(entry-list)/12;
    for(unsigned i=0;i<c->opponent_cancel_count;i++)
        if(c->opponent_cancels[i].record==index && c->opponent_cancels[i].rule==rule &&
           (c->opponent_cancels[i].opponent&OPPONENT_APPLIED))
            return fighter_moveset(0x800a9228+(1-player)*0x188c)==(c->opponent_cancels[i].opponent&255);
    return 1;
}
void __wrap_func_8002CC28(CPUState *cpu) {
    unsigned player=cpu->gpr[4]==0x800aaab4?1:0;
    if((cpu->pc==0 || cpu->pc==0x8002cc28) && cpu->gpr[4]==0x800a9228+player*0x188c &&
       !opponent_rule_holds(player,cpu->gpr[4],cpu->gpr[5])) {
        cpu->gpr[2]=0;cpu->pc=cpu->gpr[31];return;
    }
    if((cpu->pc==0 || cpu->pc==0x8002cc28) && cpu->gpr[4]==0x800a9228+player*0x188c) {
        int owner=record_owner(psx_mod_read_word(cpu->gpr[4]+0x54));
        unsigned command=psx_mod_read_half(cpu->gpr[5]);
        /* Only that guest's own lists: the engine's look-ahead at the end of
         * a clip reads the victim's own list (B42, __wrap_func_8002D178),
         * native or, on a TTT1 pack (a guest, a native on its TTT1 moves),
         * in guest memory too - refused, it fell back on the guest's dash
         * and was hit from behind whatever its pad (B68). */
        uint32_t lists=owner>=0?slots[owner].guest:0;
        if(owner>=0 && (unsigned)owner!=player && command!=0x10 && (command<0xc000 || command>=0xe000) &&
           cpu->gpr[5]>=lists && cpu->gpr[5]-lists<slots[owner].guest_size &&
           !defender_rule(cpu->gpr[4],(unsigned)owner,cpu->gpr[5]) &&
           !reaction_exit((unsigned)owner,cpu->gpr[4],cpu->gpr[5])) {
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
/* Tekken 3's combo counter (victim +0x80: the Practice's COMBO and DAMAGE,
 * the damage scaling of the next hit) moves at each of the victim's
 * transitions (0x8002F7E8). A victim just hit that does not go from one
 * reaction to another starts again at 0, except two aliases written in the
 * code (0x8002F8A0): 0xCC6 adds one, 0x9A6 keeps the count. Both belong to
 * the Machine Gun Cannon (1, 2, 1 on a counter hit), a third hit without a
 * hit box whose damage is a timed property (T3 11): its victim plays the
 * paired reaction 0xCC6, then waits on 0x9A6 before the hit lands. The
 * Changs on TTT1 moves send their victim to their own records of the two,
 * TTT1 aliases 0x11CA and 0xCFC (the same records in every TTT1 table), pack
 * numbers there: the third hit started a new combo (2 Combo, Damage 26
 * where Julia on T3 moves has 3 and 46; B67, GH#124). Called with the
 * victim's next alias, sign-extended. */
uint32_t tekken3_ttt1_paired_alias(uint32_t number) {
    for(unsigned s=0;s<2;s++) {
        if(number<slot_base(s) || number>=slot_base(s)+SLOT_STRIDE)continue;
        if(number==guest_alias(s,0x11ca))return 0xcc6;
        if(number==guest_alias(s,0xcfc))return 0x9a6;
    }
    return number;
}
/* A throw's damage. The attacker's timed property (TTT1 24, T3 11) sets +0xE4
 * to 1 on its frame; 0x800449B4 then takes +0xEC (or the record's damage,
 * +0x5E) from the opponent only while that one is still thrown (+0x74 < 0).
 * TTT1 (0x800FB534) takes it whatever the victim does. Ganryu's side throws
 * let their victim go (a 0x0010 entry of type 6 at frames 60 / 51, which
 * clears +0x74) before their damage at 66 / 58: they dealt nothing (B52).
 * For an attacker on TTT1 moves, the damage is taken as TTT1 does. */
extern void __real_func_800449B4(CPUState *cpu);
void __wrap_func_800449B4(CPUState *cpu) {
    uint32_t victim=cpu->gpr[4];
    int entry=(cpu->pc==0 || cpu->pc==0x800449b4) && (victim==0x800a9228 || victim==0x800aaab4);
    __real_func_800449B4(cpu);
    if(!entry || (int16_t)psx_mod_read_half(victim+0x74)<0)return;
    unsigned attacker=victim==0x800a9228;
    uint32_t a=0x800a9228+attacker*0x188c;
    if(!ttt1_moves(attacker) || psx_mod_read_byte(a+0xe4)!=1)return;
    int16_t damage=(int16_t)psx_mod_read_half(a+0xec);
    if(!damage)damage=(int16_t)psx_mod_read_half(a+0x5e);
    cpu->gpr[2]+=damage;
}
/* Strong-hit effect. Each fighter's file carries a pack of 4-bit TIMs
 * (16-colour palette, 32 x 32 image) that the fight loader places in VRAM:
 * frame k in column 368/376 (player 1) or 496/504 (player 2), row 32*(k/2),
 * palette at (16*player, 503). A guest is loaded through Jin, so it would
 * show Jin's lightning; its own pack, converted from TTT1 by the importer,
 * is written over it whenever the loader has put Jin's back. */
static void load_hit_effect_64(unsigned s,const char *root);
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
    load_hit_effect_64(s,root);
}
/* Player s's pack for the effect header (tekken3_ttt1_roster.c): its number
 * of images, 0 without one, and its palette's mean colour, 8 bits a channel. */
/* A cinematic's own pack (`effect`, src/tekken3_cine.c) is the one in VRAM
 * while it plays (place_hit_effect): the header follows it, not the guest's
 * pack (the Embu's Devil Jin, a `swap` to the guest Devil: Devil's purple
 * light on Jin's red lightning). */
static unsigned char *embu_effect_pack[2];static unsigned embu_effect_frames[2];
static const char *embu_effect_file(unsigned player);
extern int tekken3_cine_frame(void);
unsigned tekken3_ttt1_hit_effect_frames(unsigned s,unsigned rgb[3]) {
    if(s>1)return 0;
    load_hit_effect(s);
    const GuestCombat *c=&slots[s];
    const unsigned char *pack=c->hit_effect;unsigned frames=c->hit_effect_frames;
    const char *own=embu_effect_file(s);
    if(own && *own && tekken3_cine_frame()>=0 && embu_effect_pack[s]){pack=embu_effect_pack[s];frames=embu_effect_frames[s];}
    if(!pack)return 0;
    unsigned n=0;
    rgb[0]=rgb[1]=rgb[2]=0;
    for(unsigned i=1;i<16;i++) {
        unsigned v=(pack[20+2*i]|pack[21+2*i]<<8)&0x7fff;
        if(!v)continue;
        rgb[0]+=(v&31)<<3;rgb[1]+=(v>>5&31)<<3;rgb[2]+=(v>>10&31)<<3;n++;
    }
    for(unsigned k=0;n && k<3;k++)rgb[k]/=n;
    return frames;
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
/* A cinematic's lightning pack: the engine's (src/tekken3_cine.c, `effect`). */
extern const char *tekken3_cine_effect(unsigned player);
extern int tekken3_cine_light(void);
static const char *embu_effect_file(unsigned player) { return tekken3_cine_effect(player); }
extern int tekken3_cine_frame(void);
extern int tekken3_ttt1_tiles_up(void);
static void place_hit_effect(unsigned player) {
    /* A cinematic's own pack (`effect`) holds the slot while it plays:
     * Jin's red lightning, not the guest's own. */
    const char *own=embu_effect_file(player);
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
    /* A video (24-bit display) shows VRAM x 0..383: player 1's pack (x
     * 368..383) at its right edge, a grey column with noise (the intro after
     * the TTT Embu, its Devil Jin still loaded: the pack went back each time
     * the video wrote there). Not placed while one plays, its rectangle black
     * once as it starts (as the video's borders: the Embu's own pack lay
     * there too); placed again after. An upload of black, not a fill: OpenGL
     * shows a 24-bit display from the CPU copy of VRAM, which a fill misses. */
    static int in_video[2];
    static const uint16_t black[16*32*16];
    if(gpu_display_is_depth24()) {
        if(!in_video[player]) { gr_vram_transfer_in((int)x,0,16,32*(int)((frames+1)/2),black); in_video[player]=1; hit_effect_in_fight[player]=0; }
        return;
    }
    in_video[player]=0;
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
/* TTT Hitspark (F12, GH#112): every fighter's strong-hit effect at TTT1's
 * 64 x 64. The guests' come with their import (<Name>-TTT1-hiteffect64.hfx),
 * Tekken 3's own cast's are read from TTT1 too (tools/ttt1_hitspark.py; Gon
 * and Dr. B, who are not in it, take Heihachi's: the 22-image packs of the
 * disc are all the same, F22), all in the catalogue
 * (tools/ttt1/hit_effect.py, hfx_pack: 'HFX6', version, images, side 64,
 * palettes 1 or one per image, flags, then the palettes and the 4-bit
 * images). They lie in the upper VRAM half (System 12 bits, mod_plugins.h),
 * in cells of 16 x 64 halfwords that no stage pack and not Unknown's wolf
 * use: y 768..959, x 544..1023 (all 28 Arcade Stages and TTT Stages files
 * measured, 73 free cells; tools/arcade_stages/pack.py keeps them free).
 * Player 1 takes row 768 and (544, 896), player 2 row 832, both palettes
 * the cell (560, 896); up to 36 images a player (F13), the rest of row 896.
 * TTT1's common sparks too (a landed hit's spray, a throw, a guard, the
 * knockdown smoke) and the poison mist, below.
 *
 * The game still draws its 32 x 32 sprite: fx_sprites_update (0x80076E70,
 * from 0x8007745C and the replay's 0x80077524) links one POLY_FT4 a living
 * sprite into the ordering table. Once it has, a copy in our packet memory
 * takes its place in the list, at the same place, size and colour (the same
 * size on screen: the user's choice over twice the size, 2026-10-23),
 * reading the 64 x 64 image of the frame the game drew (read back from its
 * texture page and UV: frame k at 368/496 + 8 (k % 2), 32 (k / 2)). The
 * pack is the one whose 32 x 32 is in VRAM: the guest's once placed, a
 * cinematic's own `effect` (Jin's red lightning: Jin's), else the native's
 * of the fighter's ID, Devil Jin's being Jin's red lightning (the user's
 * choice). It replaces the former Jin red lightning mod. The game's memory
 * is not written, only the link to its quad; without the mod, a .hfx, or on
 * a renderer without the upper half (Vulkan), the 32 x 32 plays as before.
 * The half is made at activation (before the renderer starts) for a roster
 * at import version 10 or later only. */
enum { HFX_MAX=36, HFX_SIDE=64, HFX_IMAGE=HFX_SIDE*HFX_SIDE/2, HFX_PAL_X=560, HFX_PAL_Y=896,
       HFX_PALETTE_FADE=1, HFX_VERSION=10 /* TTT1_IMPORT_VERSION that brings the packs */ };
enum { FX_SPRITES=0x800a3408, FX_SPRITE=64, FX_PRIMS=0x800a34c8, FX_PRIM=40,
       FX_OT=0x800a8c54, FX_BUFFER=0x800adefc, FX_DRAW_SKIP=0x800adca4, FX_IDS=0x800a9240 };
static struct { int on,tried; uint32_t packets; const unsigned char *placed[2]; } hfx;
extern unsigned tekken3_stage_high_vram_generation(void);
extern int tekken3_stage_high_vram_used(int x,int y,int w,int h);
/* Tekken 3's cast by ID (tools/ttt1_hitspark.py NATIVES): Gon (17) and Dr. B
 * (19) have none of their own, Heihachi's is theirs (native_hfx). */
static const char *const hfx_native_names[]={"Paul","Law","Lei","King","Yoshimitsu","Nina","Hwoarang","Xiaoyu",
    "Eddy","Jin","Julia","Kuma","Bryan","Heihachi","Ogre","Mokujin","Gunjack",NULL,"Anna",NULL,"Trueogre"};
enum { HFX_NATIVES=sizeof hfx_native_names/sizeof *hfx_native_names };
static Hfx hfx_natives[HFX_NATIVES];static int hfx_native_tried[HFX_NATIVES];
static void hfx_cell(unsigned p,unsigned k,unsigned *x,unsigned *y) {
    if(k>=30) { *x=(p?672:576)+16*(k-30); *y=896; return; }
    if(p) { *x=544+16*k; *y=832; return; }
    if(k==29) { *x=544; *y=896; return; }
    *x=k<2?544+16*k:592+16*(k-2); *y=768;
}
static void hit_effect_64_activate(void) {
    const char *e=getenv("TEKKEN3_HIT_EFFECT_64"),*root=tekken3_ttt1_asset_root();
    if(e && !strcmp(e,"0")) { fprintf(stderr,"TTT Hitspark: off (TEKKEN3_HIT_EFFECT_64=0)\n"); return; }
    if(!root)return;
    char path[4096];int version=0;
    if(snprintf(path,sizeof path,"%s/import-version.txt",root)>=(int)sizeof path)return;
    FILE *f=fopen(path,"rb");
    if(f) { if(fscanf(f,"%d",&version)!=1)version=0; fclose(f); }
    if(version<HFX_VERSION) {
        fprintf(stderr,"TTT Hitspark: off (TTT1 catalogue at import version %d, needs %d)\n",version,HFX_VERSION);
        return;
    }
    hfx.on=psx_mod_gpu_high_vram_enable();
    fprintf(stderr,"TTT Hitspark: %s\n",hfx.on?"on, upper VRAM half made":"off: no upper VRAM half");
}
PSX_MOD_CONSTRUCTOR(register_ttt_hitspark) {
    (void)psx_mod_register_activation_plugin("tekken3.ttt-hitspark",hit_effect_64_activate);
}
/* <root>/<prefix>-hiteffect64.hfx, checked whole. */
static int read_hfx(const char *root,const char *prefix,const char *who,Hfx *out) {
    char path[4096];
    if(!root || snprintf(path,sizeof path,"%s/%s-hiteffect64.hfx",root,prefix)>=(int)sizeof path)return 0;
    FILE *f=fopen(path,"rb");
    if(!f) { fprintf(stderr,"TTT Hitspark: no %s, %s's strong-hit effect stays 32 x 32\n",path,who); return 0; }
    enum { MOST=16+32*HFX_MAX+HFX_MAX*HFX_IMAGE };
    unsigned char *p=malloc(MOST+1);
    size_t n=p?fread(p,1,MOST+1,f):0;fclose(f);
    unsigned images=n>=16?p[6]|p[7]<<8:0,palettes=n>=16?p[10]|p[11]<<8:0;
    if(!p || n<16 || memcmp(p,"HFX6",4) || (p[4]|p[5]<<8)!=1 || (p[8]|p[9]<<8)!=HFX_SIDE ||
       !images || images>HFX_MAX || (palettes!=1 && palettes!=images) ||
       n!=16+32u*palettes+(size_t)images*HFX_IMAGE) {
        fprintf(stderr,"TTT Hitspark: %s is not a 64 x 64 effect pack, %s's stays 32 x 32\n",path,who);
        free(p); return 0;
    }
    out->data=p;out->images=images;out->palettes=palettes;out->flags=p[12]|p[13]<<8;
    fprintf(stderr,"TTT Hitspark: %s, %u images, %u palette(s)\n",who,images,palettes);
    return 1;
}
static void load_hit_effect_64(unsigned s,const char *root) {
    char prefix[256];
    if(!hfx.on || snprintf(prefix,sizeof prefix,"%s",tekken3_guest_data_prefix_for(s))>=(int)sizeof prefix)return;
    read_hfx(root,prefix,tekken3_guest_name_for(s),&slots[s].hfx);
}
static const Hfx *native_hfx(unsigned id) {
    if(id==17 || id==19)id=13;            /* Gon and Dr. B: their T3 pack is Heihachi's, byte for byte */
    if(id>=HFX_NATIVES || !hfx_native_names[id])return NULL;
    if(!hfx_native_tried[id]) {
        char prefix[64];
        hfx_native_tried[id]=1;
        snprintf(prefix,sizeof prefix,"%s-TTT1",hfx_native_names[id]);
        read_hfx(tekken3_ttt1_asset_root(),prefix,hfx_native_names[id],&hfx_natives[id]);
    }
    return hfx_natives[id].data?&hfx_natives[id]:NULL;
}
/* A cinematic's own pack, <Name>-TTT1-hiteffect.tim: that native's. */
static const Hfx *cine_hfx(const char *file) {
    const char *base=file,*end;
    for(const char *c=file;*c;c++)if(*c=='/' || *c=='\\')base=c+1;
    if(!(end=strstr(base,"-TTT1-hiteffect")))return NULL;
    for(unsigned id=0;id<HFX_NATIVES;id++)
        if(hfx_native_names[id] && strlen(hfx_native_names[id])==(size_t)(end-base) &&
           !strncmp(base,hfx_native_names[id],(size_t)(end-base)))return native_hfx(id);
    return NULL;
}
/* PS2 EFFECTS (src/tekken3_ttt1_ps2_laser.c, TIPS section 164): the
 * Mishima's TTT PS2 strong-hit effects instead of TTT1's, read on the
 * player's PS2 disc (tools/ps2/ttt_hitspark_ps2.py): Jin and Heihachi (the
 * natives, IDs 9 and 13), Kazuya, Devil and Angel (the guests); not Devil
 * Jin (later, the user's choice). At most 32 images (the frame is read from
 * the game's UV, 2 x 16 cells); their length goes to the player's effect
 * entry (ps2_hfx_lengths). In a fight only (state 8): the Embu and the
 * cinematics keep TTT1's. */
extern int tekken3_ps2_effects_on(void);
extern const char *tekken3_ps2_effects_dir(void);
enum { PS2_HFX_MOST=32 };
static const char *const ps2_hfx_names[]={"Jin","Heihachi","Kazuya","Devil","Angel"};
enum { PS2_HFX=sizeof ps2_hfx_names/sizeof *ps2_hfx_names };
static Hfx ps2_hfx[PS2_HFX];static int ps2_hfx_tried[PS2_HFX];
static const Hfx *ps2_hfx_for(unsigned p) {
    if(!hfx.on || psx_mod_read_word(0x800ae204)!=8 || !tekken3_ps2_effects_on() || tekken3_devil_jin_player(p))return NULL;
    int which=-1;
    if(hit_effect_in_fight[p]) {
        const char *prefix=tekken3_guest_data_prefix_for(p);
        for(int k=2;prefix && k<PS2_HFX;k++)
            if(!strncmp(prefix,ps2_hfx_names[k],strlen(ps2_hfx_names[k])) && !strcmp(prefix+strlen(ps2_hfx_names[k]),"-TTT1"))which=k;
    } else {
        unsigned id=psx_mod_read_half(FX_IDS+p*0x188c);
        which=id==9?0:id==13?1:-1;
    }
    if(which<0)return NULL;
    if(!ps2_hfx_tried[which]) {
        char prefix[32];
        ps2_hfx_tried[which]=1;
        snprintf(prefix,sizeof prefix,"%s-PS2",ps2_hfx_names[which]);
        Hfx *h=&ps2_hfx[which];
        if(read_hfx(tekken3_ps2_effects_dir(),prefix,ps2_hfx_names[which],h) && (h->images>PS2_HFX_MOST || h->palettes!=h->images)) {
            fprintf(stderr,"PS2 effects: %s's pack has %u images (%u most), TTT1's stays\n",ps2_hfx_names[which],
                    h->images,PS2_HFX_MOST);
            free(h->data);memset(h,0,sizeof *h);
        }
    }
    return ps2_hfx[which].data?&ps2_hfx[which]:NULL;
}
/* The player's effect entry (0x800A35C8 + 16 * player, set at each round
 * from the 6-byte headers at 0x80027950: frames, then the light's RGB):
 * while a PS2 pack plays, our own header, its length and the light of the
 * header it replaces; the entry given back once the pack is no longer the
 * player's. Every frame before the effects are stepped. */
static void ps2_hfx_lengths(void) {
    enum { ROWS=0x800a35c8 };
    static uint32_t ours[2],replaced[2];
    for(unsigned p=0;p<2;p++) {
        uint32_t at=ROWS+p*16,now=psx_mod_read_word(at);
        const Hfx *h=ps2_hfx_for(p);
        if(!h) {
            if(ours[p] && now==ours[p])psx_mod_write_word(at,replaced[p]);
            continue;
        }
        if(!ours[p] && !(ours[p]=psx_mod_alloc_guest_memory(8,4))) {
            fprintf(stderr,"PS2 effects: no guest memory for P%u's effect header, TTT1's length stays\n",p+1);
            continue;
        }
        if(now!=ours[p]) {
            replaced[p]=now;
            for(unsigned k=2;k<6;k++)psx_mod_write_byte(ours[p]+k,psx_mod_read_byte(now+k));
            psx_mod_write_half(ours[p],(uint16_t)h->images);
            psx_mod_write_word(at,ours[p]);
        }
    }
}
/* The 64 x 64 of the 32 x 32 now in player p's VRAM rectangle. An Embu
 * guest in Jin's or Yoshimitsu's part has its own there, whatever
 * hit_effect_in_fight says: the fight tick clears that for a player off TTT1
 * moves, which an Embu guest is, once a fight with a guest has left the
 * TTT1 characters on (Kunimitsu drew Yoshimitsu's 64 x 64, Kazuya Jin's red
 * lightning: GH#29 again, B115). */
extern int tekken3_ttt1_embu_effect_guest(unsigned player);
static const Hfx *hit_effect_64_pack(unsigned p) {
    if(tekken3_ttt1_tiles_up())return NULL;
    const char *own=embu_effect_file(p);
    if(own && *own && tekken3_cine_frame()>=0)return cine_hfx(own);
    const Hfx *ps2=ps2_hfx_for(p);
    if(ps2)return ps2;
    if(hit_effect_in_fight[p] || tekken3_ttt1_embu_effect_guest(p))return slots[p].hfx.data?&slots[p].hfx:NULL;
    return native_hfx(psx_mod_read_half(FX_IDS+p*0x188c));
}
/* A pack in its cells (image k at cells[k], palette p at row pal_y + p of
 * column pal_x), unless the upper half already holds it (it is in save
 * states: one taken before F12, or with another fighter, is caught). */
typedef struct { uint16_t x,y; } HfxCell;
static void place_hfx(const Hfx *h,const HfxCell *cells,unsigned pal_x,unsigned pal_y,
                      const unsigned char **placed,const char *who) {
    const uint16_t *hi=gpu_high_vram_pixels();
    const unsigned char *pal=h->data+16,*img=pal+32*h->palettes;
    int same=hi!=NULL;
    for(unsigned k=0;same && k<h->palettes;k++)
        same=!memcmp(hi+(size_t)(pal_y-512+k)*1024+pal_x,pal+32*k,32);
    for(unsigned k=0;same && k<h->images;k++)
        for(unsigned row=0;same && row<HFX_SIDE;row++)
            same=!memcmp(hi+(size_t)(cells[k].y-512+row)*1024+cells[k].x,img+k*HFX_IMAGE+row*32,32);
    if(same)return;
    for(unsigned k=0;k<h->palettes;k++)
        psx_mod_gpu_high_vram_upload((int)pal_x,(int)(pal_y+k),16,1,(const uint16_t*)(pal+32*k));
    for(unsigned k=0;k<h->images;k++)
        psx_mod_gpu_high_vram_upload(cells[k].x,cells[k].y,16,HFX_SIDE,(const uint16_t*)(img+k*HFX_IMAGE));
    if(*placed!=h->data)
        fprintf(stderr,"TTT Hitspark: %s, %u images in the upper VRAM half\n",who,h->images);
    *placed=h->data;
}
static HfxCell hfx_player_cells[2][HFX_MAX];
static const HfxCell *player_cells(unsigned p) {
    if(!hfx_player_cells[0][0].x)
        for(unsigned q=0;q<2;q++)for(unsigned k=0;k<HFX_MAX;k++) {
            unsigned x,y;hfx_cell(q,k,&x,&y);
            hfx_player_cells[q][k]=(HfxCell){(uint16_t)x,(uint16_t)y};
        }
    return hfx_player_cells[p];
}
/* TTT1's common sparks (tools/ttt1_hitspark.py COMMON), in place of the
 * boxes of T3's set 2 (fighter_tim_vram_table 0x800279EC + 2 * 48: each its
 * palette x and first image), each at its TTT1 length (the user's choice):
 *   0 a landed hit's spray ((896, 256), every landed hit: 0x80076C28), row 28;
 *   1 a throw's pink spark ((920, 352), move property 9 and "no attack"
 *     hits, 0x800448E0), row 29 (F22);
 *   2 a guarded hit's sparks ((896, 448), 0x800448E0), row 30;
 *   3 the knockdown smoke ((968, 288), property 10, and the six puffs of
 *     fx_scatter at each fall, below), row 33 (F22).
 * The poison mist (decor effect type 10, below) takes TTT1's: the smoke's
 * images in a palette of its own (Mist-TTT1-hiteffect64.hfx).
 * Their cells in the upper half are placed with each stage pack, around it
 * (tekken3_stage_high_vram_used), outside the F12 cells and Unknown's wolf:
 * the smoke's 30 images stay in theirs (the puffs and the mist share them);
 * the spray, the throw and the guard are written image by image into a cell
 * a sprite and a frame buffer (6: what one buffer drew is not written while
 * the other is built; the renderers read the half at the next draw); one
 * cell of palettes. 37 cells, of the 75 free with the fullest stage (TTT 14;
 * F12 kept the spray's and the guard's 61 images in place). T3 plays 27, 21,
 * 25 and 27 images (box k's header 0x800279D4 + 6 k), but 0x8007641C points
 * the guard's entry (0x800A3600) at box 1's header: while ours can be drawn,
 * box 1's header is the throw's and the guard's entry goes to box 2's, read
 * by no one else. Their own lengths otherwise. */
enum { SPARK_BOXES=4, SPARK_SMOKE=3, SMOKE_FRAMES=30, MIST_FRAMES=21, MIST_ROW=SPARK_BOXES,
       SPARK_CELLS=2*3+SMOKE_FRAMES+1, SPARK_HEADER=0x800279d4, GUARD_ENTRY=0x800a3600 };
static const struct { const char *name; unsigned clut_x,vram_x,vram_y,stock; } hfx_sparks[SPARK_BOXES]={
    {"Spark",32,896,256,27},{"Throw",48,920,352,21},{"Guard",64,896,448,25},{"Smoke",80,968,288,27}};
static struct {
    Hfx pack[SPARK_BOXES],mist; int tried,ready; unsigned generation;
    HfxCell stream[2][3],smoke[SMOKE_FRAMES],pal; const unsigned char *placed;
    unsigned char mist_image[MIST_FRAMES];      /* the smoke's image of each of the mist's */
} sparks={.ready=-1};
static const uint16_t hfx_taken[][4]={{544,768,32,64},{592,768,432,64},{544,832,480,64},{544,896,224,64},
                                      {640,512,384,256} /* Unknown's wolf */};
static int spark_cell_free(int x,int y) {
    for(unsigned i=0;i<sizeof hfx_taken/sizeof *hfx_taken;i++) {
        const uint16_t *r=hfx_taken[i];
        if(x<r[0]+r[2] && r[0]<x+16 && y<r[1]+r[3] && r[1]<y+HFX_SIDE)return 0;
    }
    return !tekken3_stage_high_vram_used(x,y,16,HFX_SIDE);
}
static int sparks_ready(void) {
    unsigned g=tekken3_stage_high_vram_generation();
    if(sparks.ready>=0 && g==sparks.generation)return sparks.ready;
    sparks.generation=g;sparks.ready=0;sparks.placed=NULL;
    HfxCell got[SPARK_CELLS];unsigned n=0;
    for(int page=512;page<1024;page+=256)
        for(int x=0;x<1024;x+=16)
            for(int y=page;y<page+256;y+=HFX_SIDE)
                if(n<SPARK_CELLS && spark_cell_free(x,y))got[n++]=(HfxCell){(uint16_t)x,(uint16_t)y};
    if(n<SPARK_CELLS) {
        fprintf(stderr,"TTT Hitspark: %u free cells beside this stage, the common sparks stay 32 x 32\n",n);
        return 0;
    }
    memcpy(sparks.stream,got,sizeof sparks.stream);
    memcpy(sparks.smoke,got+6,sizeof sparks.smoke);
    sparks.pal=got[SPARK_CELLS-1];
    return sparks.ready=1;
}
static const HfxCell *spark_cell(unsigned k) {
    return k<6?&sparks.stream[k/3][k%3]:k<6+SMOKE_FRAMES?&sparks.smoke[k-6]:&sparks.pal;
}
/* For other users of the upper half (the PS2 lasers of Devil and Angel): whether
 * rectangle x, y, w, h overlaps what TTT Hitspark takes there while it is on,
 * its fixed cells and the common sparks' 37 cells around the loaded stage
 * (placed now for this stage if they were not yet). Unknown's wolf (x
 * 640..1023, y 512..767) is never ours. Call it again when
 * tekken3_stage_high_vram_generation() changes. */
int tekken3_hit_effect_high_vram_used(int x,int y,int w,int h) {
    if(!hfx.on)return 0;
    for(unsigned i=0;i<4;i++) {                         /* hfx_taken without the wolf */
        const uint16_t *r=hfx_taken[i];
        if(x<r[0]+r[2] && r[0]<x+w && y<r[1]+r[3] && r[1]<y+h)return 1;
    }
    if(sparks_ready()!=1)return 0;
    for(unsigned k=0;k<SPARK_CELLS;k++) {
        const HfxCell *c=spark_cell(k);
        if(x<c->x+16 && c->x<x+w && y<c->y+HFX_SIDE && c->y<y+h)return 1;
    }
    return 0;
}
/* Box s's pack, when ours can be drawn. */
static const Hfx *spark_pack(unsigned s) {
    return sparks.ready==1 && sparks.pack[s].data?&sparks.pack[s]:NULL;
}
/* Once a frame, before any spark is made: the packs, their cells, T3's lengths. */
static void sparks_tick(void) {
    if(!sparks.tried) {
        sparks.tried=1;
        static const unsigned frames[SPARK_BOXES]={30,28,30,SMOKE_FRAMES};
        for(unsigned s=0;s<SPARK_BOXES;s++) {
            char prefix[32];snprintf(prefix,sizeof prefix,"%s-TTT1",hfx_sparks[s].name);
            if(read_hfx(tekken3_ttt1_asset_root(),prefix,hfx_sparks[s].name,&sparks.pack[s]) &&
               (sparks.pack[s].images!=frames[s] || sparks.pack[s].palettes!=1)) {
                fprintf(stderr,"TTT Hitspark: %s has %u images (%u wanted), it stays 32 x 32\n",hfx_sparks[s].name,
                        sparks.pack[s].images,frames[s]);
                free(sparks.pack[s].data);memset(&sparks.pack[s],0,sizeof sparks.pack[s]);
            }
        }
        /* The mist's images are the smoke's: each found there, or no mist. */
        const Hfx *smoke=&sparks.pack[SPARK_SMOKE],*mist=&sparks.mist;
        if(smoke->data && read_hfx(tekken3_ttt1_asset_root(),"Mist-TTT1","Mist",&sparks.mist)) {
            unsigned found=0;
            if(mist->images==MIST_FRAMES && mist->palettes==1)
                for(unsigned k=0;k<MIST_FRAMES;k++)
                    for(unsigned j=0;j<SMOKE_FRAMES;j++)
                        if(!memcmp(mist->data+48+k*HFX_IMAGE,smoke->data+48+j*HFX_IMAGE,HFX_IMAGE)) {
                            sparks.mist_image[k]=(unsigned char)j;found++;break;
                        }
            if(found!=MIST_FRAMES) {
                fprintf(stderr,"TTT Hitspark: the mist's images are not the smoke's, it stays 32 x 32\n");
                free(sparks.mist.data);memset(&sparks.mist,0,sizeof sparks.mist);
            }
        }
    }
    int ready=psx_mod_gpu_high_vram_ready() && sparks_ready();
    int ours[SPARK_BOXES];
    for(unsigned s=0;s<SPARK_BOXES;s++)ours[s]=ready && sparks.pack[s].data;
    for(unsigned s=0;s<SPARK_BOXES;s++) {
        unsigned want=ours[s]?sparks.pack[s].images:hfx_sparks[s].stock;
        if(s==2 && !ours[2] && ours[1])want=21;         /* the guard's own length, off box 1's header */
        uint32_t header=SPARK_HEADER+6*s;
        if(psx_mod_read_half(header)!=want)psx_mod_write_half(header,(uint16_t)want);
    }
    uint32_t entry=ours[1] || ours[2]?SPARK_HEADER+12:SPARK_HEADER+6;
    if(psx_mod_read_word(GUARD_ENTRY)!=entry)psx_mod_write_word(GUARD_ENTRY,entry);
}
/* The smoke's images and every palette in their cells, unless already there. */
static void sparks_place(void) {
    const Hfx *smoke=spark_pack(SPARK_SMOKE);
    if(smoke)place_hfx(smoke,sparks.smoke,sparks.pal.x,sparks.pal.y+SPARK_SMOKE,&sparks.placed,"Smoke");
    const uint16_t *hi=gpu_high_vram_pixels();
    for(unsigned s=0;s<=SPARK_BOXES;s++) {
        const Hfx *h=s<SPARK_BOXES?spark_pack(s):sparks.ready==1 && sparks.mist.data?&sparks.mist:NULL;
        if(!h || !hi)continue;
        const uint16_t *row=hi+(size_t)(sparks.pal.y-512+s)*1024+sparks.pal.x;
        if(memcmp(row,h->data+16,32))psx_mod_gpu_high_vram_upload(sparks.pal.x,sparks.pal.y+s,16,1,(const uint16_t*)(h->data+16));
    }
}
/* Image k of pack h in cell c, unless it is there already. */
static void spark_stream(const HfxCell *c,const Hfx *h,unsigned k) {
    const uint16_t *hi=gpu_high_vram_pixels();
    const unsigned char *img=h->data+16+32*h->palettes+(size_t)k*HFX_IMAGE;
    if(!hi)return;
    for(unsigned row=0;row<HFX_SIDE;row++)
        if(memcmp(hi+(size_t)(c->y-512+row)*1024+c->x,img+row*32,32)) {
            psx_mod_gpu_high_vram_upload(c->x,c->y,16,HFX_SIDE,(const uint16_t*)img);
            return;
        }
}
/* Our packets, a frame buffer each: the three hit sprites, the 18 puffs, the mists. */
enum { SCATTER=0x8009e850, SCATTER_SLOT=0x370, SCATTER_PUFFS=18, MIST_MOST=16,
       HFX_QUADS=3+SCATTER_PUFFS+MIST_MOST };
static int hit_effect_64_packets(void) {
    if(hfx.tried)return hfx.packets!=0;
    hfx.tried=1;
    uint32_t a=psx_mod_alloc_gpu_dma_memory(2*HFX_QUADS*FX_PRIM,16);
    if(!a || !psx_mod_gpu_high_vram_source(a,2*HFX_QUADS*FX_PRIM)) {
        fprintf(stderr,"TTT Hitspark: no packet memory, the strong-hit effects stay 32 x 32\n");
        return 0;
    }
    hfx.packets=a;
    return 1;
}
/* A quad the game linked, and what ours reads instead: the cell, the palette
 * (column, row), our packet's slot, and whether the pack fades by palettes. */
typedef struct { uint32_t prim; const HfxCell *cell; unsigned pal_x,pal_y,slot,fade; } HfxSwap;
/* Each quad's place in the ordering table (one walk from its last tag), then
 * a copy in our packet memory takes it: same place, size and colour, the
 * game's blending, the upper half's cell and palette. A quad linked right
 * after another of the list hangs from that one's copy. */
static void hfx_swap(const HfxSwap *s,unsigned n,unsigned buffer,int trace) {
    uint32_t before[HFX_QUADS]={0},ours[HFX_QUADS]={0};
    unsigned left=n;
    uint32_t at=psx_mod_read_word(psx_mod_read_word(FX_OT)+0x10)&0xffffff;
    for(unsigned g=0;left && g<0x10000 && at!=0xffffff && at;g++) {
        uint32_t next=psx_mod_read_word(0x80000000u|at)&0xffffff;
        for(unsigned k=0;k<n;k++)
            if(!before[k] && next==(s[k].prim&0xffffff)) { before[k]=0x80000000u|at; left--; }
        at=next;
    }
    for(unsigned k=0;k<n;k++) {
        if(trace)fprintf(stderr,"TTT Hitspark trace: quad %08X slot %u, %s\n",s[k].prim,s[k].slot,
                         before[k]?"replaced":"not found in the ordering table");
        if(!before[k])continue;
        uint32_t prim=s[k].prim,o=ours[k]=hfx.packets+(buffer*HFX_QUADS+s[k].slot)*FX_PRIM;
        unsigned tpage=psx_mod_read_half(prim+22),u0=psx_mod_read_byte(prim+12),u1=psx_mod_read_byte(prim+20);
        for(unsigned w=1;w<10;w++)psx_mod_write_word(o+4*w,psx_mod_read_word(prim+4*w));
        psx_mod_write_word(o,9u<<24|(psx_mod_read_word(prim)&0xffffff));
        const HfxCell *cell=s[k].cell;
        unsigned u=(cell->x%64)*4,v=cell->y%256,flip=u0>u1;
        unsigned clut=0x8000u|(s[k].pal_y-512)<<6|s[k].pal_x>>4;
        unsigned page=0x800u|(cell->y>=768?0x10u:0)|(tpage&0x60)|cell->x/64;  /* upper half, the game's blending */
        unsigned ul=flip?u+63:u,ur=flip?u:u+63;
        psx_mod_write_word(o+12,clut<<16|v<<8|ul);
        psx_mod_write_word(o+20,page<<16|v<<8|ur);
        psx_mod_write_half(o+28,(uint16_t)((v+63)<<8|ul));
        psx_mod_write_half(o+36,(uint16_t)((v+63)<<8|ur));
        if(s[k].fade)psx_mod_write_word(o+4,(psx_mod_read_word(prim+4)&0xff000000u)|0x808080);
    }
    for(unsigned k=0;k<n;k++) {
        if(!before[k])continue;
        uint32_t link=before[k];
        for(unsigned j=0;j<n;j++)if(before[j] && s[j].prim==link)link=ours[j];
        psx_mod_write_word(link,(psx_mod_read_word(link)&0xff000000u)|(ours[k]&0xffffff));
    }
}
/* Each sprite's life as fx_sprites_update starts: it draws the living ones,
 * then steps them (the last image drawn, its life is already 0). */
static int16_t hfx_lives[3];
static void hit_effect_64_lives(void) {
    if(!hfx.on)return;
    for(unsigned i=0;i<3;i++)hfx_lives[i]=(int16_t)psx_mod_read_half(FX_SPRITES+i*FX_SPRITE+2);
    sparks_tick();
    ps2_hfx_lengths();
}
static int hfx_trace(void) {
    static int trace=-1;
    if(trace<0)trace=getenv("TEKKEN3_HIT_EFFECT_TRACE")!=NULL;
    return trace;
}
/* The mists (decor effects of type 10, made by fx_special_25 for Nina's and
 * Yoshimitsu's limb 25) that fx_update_draw linked this frame, before the hit
 * sprites in every loop of the game (0x8002AE58): image = the effect's
 * frame (+0x48, 0..20, 0x80072D5C), from the smoke's cells; the mist's
 * palette, the smoke's for limb 28's (+0x4C set: T3's grey). */
enum { FX_ACTIVE=0x800a0988 };
static unsigned mists_64(HfxSwap *s,unsigned buffer) {
    if(sparks.ready!=1 || !sparks.mist.data || !spark_pack(SPARK_SMOKE))return 0;
    unsigned n=0;
    uint32_t e=psx_mod_read_word(FX_ACTIVE+4);
    for(unsigned g=0;g<0x50 && e && e!=FX_ACTIVE && n<MIST_MOST;g++,e=psx_mod_read_word(e+4)) {
        int32_t frame=(int32_t)psx_mod_read_word(e+0x48);
        if(psx_mod_read_byte(e+0xc)!=10 || !(psx_mod_read_byte(e+0xd)&0x40) || frame<0 || frame>=MIST_FRAMES)continue;
        unsigned row=psx_mod_read_word(e+0x4c)?SPARK_SMOKE:MIST_ROW;
        s[n]=(HfxSwap){e+0x50+buffer*FX_PRIM,&sparks.smoke[sparks.mist_image[frame]],sparks.pal.x,sparks.pal.y+row,
                       3+SCATTER_PUFFS+n,0};
        n++;
    }
    return n;
}
static void hit_effect_64(void) {
    if(!hfx.on || psx_mod_read_word(FX_DRAW_SKIP) || !psx_mod_gpu_high_vram_ready())return;
    unsigned buffer=psx_mod_read_word(FX_BUFFER)&1,n=0;
    int trace=hfx_trace();
    HfxSwap s[3+MIST_MOST];
    for(unsigned i=0;i<3;i++) {
        uint32_t fx=FX_SPRITES+i*FX_SPRITE,prim=FX_PRIMS+(buffer*3+i)*FX_PRIM;
        if(trace && hfx_lives[i]>0)
            fprintf(stderr,"TTT Hitspark trace: sprite %u life %d clut row %u base %u tpage %04X uv %u,%u / %u\n",i,hfx_lives[i],
                    psx_mod_read_half(fx+0x22),psx_mod_read_half(fx+0x14),psx_mod_read_half(prim+22),psx_mod_read_byte(prim+12),
                    psx_mod_read_byte(prim+13),psx_mod_read_byte(prim+20));
        if(hfx_lives[i]<=0 || psx_mod_read_half(fx+0x22)!=503)continue;
        unsigned base=psx_mod_read_half(fx+0x14),tpage=psx_mod_read_half(prim+22);
        unsigned u0=psx_mod_read_byte(prim+12),u1=psx_mod_read_byte(prim+20);
        const Hfx *h=NULL;const HfxCell *cell=NULL;unsigned pal_x=0,pal_y=0,k;
        if(base==368 || base==496) {
            /* A fighter's effect: the frame the game drew, from its texture page and UV. */
            unsigned p=base==496;
            if(!(h=hit_effect_64_pack(p)))continue;
            unsigned x=(tpage&15)*64+(u0<u1?u0:u1)/4,y=(tpage>>4&1)*256+psx_mod_read_byte(prim+13);
            if(x<base || x-base>8 || (x-base)%8 || y%32)continue;
            k=2*(y/32)+(x-base)/8;
            if(k>=h->images)k=h->images-1;
            cell=player_cells(p)+k;pal_x=HFX_PAL_X;pal_y=HFX_PAL_Y+32*p+(h->palettes>1?k:0);
            place_hfx(h,player_cells(p),HFX_PAL_X,HFX_PAL_Y+32*p,&hfx.placed[p],p?"P2":"P1");
        } else {
            /* A common spark: its image is its age. */
            unsigned b=0,clut_x=psx_mod_read_half(fx+0x20),vram_y=psx_mod_read_half(fx+0x16);
            while(b<SPARK_BOXES && (hfx_sparks[b].clut_x!=clut_x || hfx_sparks[b].vram_x!=base || hfx_sparks[b].vram_y!=vram_y))b++;
            if(b==SPARK_BOXES || !(h=spark_pack(b)))continue;
            k=(unsigned)hfx_lives[i]-1;
            if(k>=h->images)k=h->images-1;
            sparks_place();
            if(b==SPARK_SMOKE)cell=&sparks.smoke[k];
            else spark_stream(cell=&sparks.stream[buffer][i],h,k);
            pal_x=sparks.pal.x;pal_y=sparks.pal.y+b;
        }
        s[n++]=(HfxSwap){prim,cell,pal_x,pal_y,i,(h->flags&HFX_PALETTE_FADE)!=0};
    }
    unsigned m=mists_64(s+n,buffer);
    if(m)sparks_place();
    if(n+m && hit_effect_64_packets())hfx_swap(s,n+m,buffer,trace);
}
/* hit_fx_update (0x8007745C: a pause, a replay's fx_replay_update) and
 * hit_fx_update_rec (0x80077524: a fight): entered (pc 0 or the entry, the
 * dispatch's), then back from fx_sprites_update, the quads linked
 * (continuation 0x800774A8 / 0x80077570). */
extern void __real_func_8007745C(CPUState *cpu);
extern void __real_func_80077524(CPUState *cpu);
void __wrap_func_8007745C(CPUState *cpu) {
    uint32_t at=cpu->pc;
    if(!at || at==0x8007745cu)hit_effect_64_lives();
    __real_func_8007745C(cpu);
    if(at==0x800774a8u)hit_effect_64();
}
void __wrap_func_80077524(CPUState *cpu) {
    uint32_t at=cpu->pc;
    if(!at || at==0x80077524u)hit_effect_64_lives();
    __real_func_80077524(cpu);
    if(at==0x80077570u)hit_effect_64();
}
/* The knockdown smoke (F22): fx_scatter, three slots of six puffs at
 * 0x8009E850 (0x370 bytes: the sprites at +0x10, 64 bytes each, a POLY_FT4
 * each per frame buffer at +0x190 + 0xF0 buffer), box 3's sprites, started
 * one every other frame and linked at slot 1 of the ordering table by
 * fx_scatter_update (0x8004AA90), from fx_scatter_tick (0x8004AC24: a pause,
 * a replay) and fx_scatter_advance (0x8004ACB4: a fight). Each puff from the
 * smoke's cells. The image drawn, from the lives before and after: a puff
 * started there is drawn at 1 and stepped. */
static int16_t scatter_lives[SCATTER_PUFFS];
static void scatter_64_lives(void) {
    if(!hfx.on)return;
    for(unsigned j=0;j<SCATTER_PUFFS;j++)
        scatter_lives[j]=(int16_t)psx_mod_read_half(SCATTER+j/6*SCATTER_SLOT+0x10+j%6*FX_SPRITE+2);
}
static void scatter_64(void) {
    const Hfx *h=hfx.on?spark_pack(SPARK_SMOKE):NULL;
    if(!h || psx_mod_read_word(FX_DRAW_SKIP) || !psx_mod_gpu_high_vram_ready())return;
    unsigned buffer=psx_mod_read_word(FX_BUFFER)&1,n=0;
    HfxSwap s[SCATTER_PUFFS];
    for(unsigned j=0;j<SCATTER_PUFFS;j++) {
        uint32_t slot=SCATTER+j/6*SCATTER_SLOT,fx=slot+0x10+j%6*FX_SPRITE;
        int life=(int16_t)psx_mod_read_half(fx+2),before=scatter_lives[j];
        int k=life>0?(life==before?life-1:life-2):before-1;
        if(k<0 || psx_mod_read_half(fx+0x20)!=hfx_sparks[SPARK_SMOKE].clut_x || psx_mod_read_half(fx+0x22)!=503 ||
           psx_mod_read_half(fx+0x14)!=hfx_sparks[SPARK_SMOKE].vram_x || psx_mod_read_half(fx+0x16)!=hfx_sparks[SPARK_SMOKE].vram_y)
            continue;
        if((unsigned)k>=h->images)k=(int)h->images-1;
        s[n++]=(HfxSwap){slot+0x190+buffer*0xf0+j%6*FX_PRIM,&sparks.smoke[k],sparks.pal.x,sparks.pal.y+SPARK_SMOKE,3+j,0};
    }
    if(!n || !hit_effect_64_packets())return;
    sparks_place();
    hfx_swap(s,n,buffer,hfx_trace());
}
extern void __real_func_8004AC24(CPUState *cpu);
extern void __real_func_8004ACB4(CPUState *cpu);
void __wrap_func_8004AC24(CPUState *cpu) {
    uint32_t at=cpu->pc;
    if(!at || at==0x8004ac24u)scatter_64_lives();
    __real_func_8004AC24(cpu);
    if(at==0x8004ac48u)scatter_64();
}
void __wrap_func_8004ACB4(CPUState *cpu) {
    uint32_t at=cpu->pc;
    if(!at || at==0x8004acb4u)scatter_64_lives();
    __real_func_8004ACB4(cpu);
    if(at==0x8004acd4u)scatter_64();
}
/* A cinematic does not run the fight's effect placing: a pack of the same
 * format is written there instead (its `effect`: a file, absolute or under
 * the TTT1 asset root): Jin's red TTT1 lightning for his transformation in
 * Kazuya's TTT ending, which the lightning aura (timed property 6) draws
 * with. */
static unsigned char *embu_effect_pack[2];static unsigned embu_effect_frames[2];static int embu_effect_tried[2];
/* Another cinematic (src/tekken3_cine.c, as one starts and ends): read again. */
void tekken3_ttt1_embu_effects_reset(void) {
    for(unsigned p=0;p<2;p++){free(embu_effect_pack[p]);embu_effect_pack[p]=NULL;embu_effect_tried[p]=0;}
}
void tekken3_ttt1_embu_effects(void) {
    unsigned char **pack=embu_effect_pack;unsigned *frames=embu_effect_frames;int *tried=embu_effect_tried;
    for(unsigned p=0;p<2;p++) {
        if(!tried[p]) {
            tried[p]=1;
            const char *e=embu_effect_file(p),*root=tekken3_ttt1_asset_root();
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
 * A cinematic's `light` RRGGBB gives every character that colour while it
 * plays, the stock colours back as soon as it ends. */
void tekken3_ttt1_embu_light(int embu) {
    enum { HEADERS=0x80027950, HEADER=6, IDS=22 };
    static unsigned char saved[IDS][3];static int lit;
    int want=tekken3_cine_light();                              /* -2: none */
    if(want<0)embu=0;
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
 * points to {fighter, outfit} per stage (two halfwords, outfit 0xFFFF for
 * the default; Jin's, 0x800B071C: 0, 5, 6, 13). The table stops at
 * character 22: a guest read 0 (Kazuya) or the actor state that follows
 * (higher IDs), then dereferenced it at 0x800B26D4. Copy it with a route
 * per guest ID whenever the overlay is loaded: the guest's own (F02, chosen
 * with the user, handoff/file-1.2.2.md), else Jin's. A guest boss is actor
 * 1 and loads as a CPU opponent does. A boss missing from the catalogue
 * gives way to Jin's boss of that stage. The overlay's code and routes
 * (0x800B071C..0x800B088B, Jin's first) arrive a few frames before its
 * table, zeros meanwhile: copied then (a guest's fight earlier, the
 * attract's too, keeps this tick running through the load), every native
 * read the route at address 0, Paul four times, and the patched code kept
 * the copy (B112). Only a table whose native entries all point at a route
 * is copied. */
enum { FORCE_TABLE=0x800b6378, FORCE_NATIVE=92, FORCE_ENTRIES=64*4, FORCE_DEFAULT=9,
       FORCE_JIN_ROUTE=0x800b071c, FORCE_ROUTES_END=0x800b088c, FORCE_STAGES=4, NO_BOSS=0xffffffffu };
static const struct { const char *guest,*boss[FORCE_STAGES]; } force_routes[]={
    {"kazuya",{"lee","paul","jin","heihachi"}},
    {"jun",{"kuma","lei","kazuya","heihachi"}},
    {"unknown",{"yoshimitsu","jin","jun","heihachi"}},
    {"devil",{"paul","jin","angel","heihachi"}},
    {"angel",{"xiaoyu","kazuya","devil","heihachi"}},
    {"lee",{"law","jin","kazuya","heihachi"}},
    {"bruce",{"eddy","bryan","kazuya","heihachi"}},
    {"baek",{"eddy","jin","hwoarang","heihachi"}},
    {"armorking",{"bryan","ganryu","king","heihachi"}},
    {"kunimitsu",{"lei","michelle","yoshimitsu","heihachi"}},
    {"michelle",{"kunimitsu","ganryu","julia","heihachi"}},
    {"ganryu",{"kuma","michelle","julia","heihachi"}},
    {"wang",{"lei","xiaoyu","kazuya","heihachi"}},
    {"jack2",{"kuma","pjack","gunjack","heihachi"}},
    {"pjack",{"bryan","jack2","gunjack","heihachi"}},
    {"roger",{"kuma","panda","alex","heihachi"}},
    {"alex",{"kuma","panda","roger","heihachi"}},
    {"tetsujin",{"tetsujin","tetsujin","tetsujin","tetsujin"}},
};
extern int tekken3_guest_id(const char *key);
/* {fighter, outfit} of a boss, NO_BOSS when it is not in the catalogue. */
static uint32_t force_boss(const char *key) {
    static const char *stock[]={"paul","law","lei","king","yoshimitsu","nina","hwoarang","xiaoyu","eddy","jin",
        "julia","kuma","bryan","heihachi","ogre","mokujin","gunjack"};
    if(!strcmp(key,"panda"))return 11|1u<<16;                    /* Kuma's second outfit */
    for(unsigned i=0;i<sizeof stock/sizeof *stock;i++)if(!strcmp(stock[i],key))return i|0xffffu<<16;
    int id=tekken3_guest_id(key);
    return id<0?NO_BOSS:(uint32_t)id|0xffffu<<16;
}
static void install_force_bosses(void) {
    enum { ROUTES=sizeof force_routes/sizeof *force_routes };
    static uint32_t table,routes;
    if(psx_mod_read_word(0x800b2658)!=0x27bdffb8 || psx_mod_read_word(0x800b26d4)!=0x84720002 ||
       psx_mod_read_word(0x800b2694)!=0x3c05800b || psx_mod_read_word(0x800b2698)!=0x24a56378)return;
    for(unsigned i=0;i<FORCE_NATIVE;i++) {
        uint32_t route=psx_mod_read_word(FORCE_TABLE+i*4);
        if(route<FORCE_JIN_ROUTE || route>=FORCE_ROUTES_END || (route-FORCE_JIN_ROUTE)%16)return;
    }
    if(!table && !(table=psx_mod_alloc_guest_memory(FORCE_ENTRIES*4,16)))return;
    if(!routes && !(routes=psx_mod_alloc_guest_memory(ROUTES*FORCE_STAGES*4,16)))return;
    for(unsigned i=0;i<FORCE_ENTRIES;i++)
        psx_mod_write_word(table+i*4,psx_mod_read_word(FORCE_TABLE+(i<FORCE_NATIVE?i:FORCE_DEFAULT*4+i%4)*4));
    for(unsigned r=0;r<ROUTES;r++) {
        int id=tekken3_guest_id(force_routes[r].guest);
        if(id<0)continue;
        uint32_t route=routes+r*FORCE_STAGES*4;
        for(unsigned s=0;s<FORCE_STAGES;s++) {
            uint32_t boss=force_boss(force_routes[r].boss[s]);
            psx_mod_write_word(route+s*4,boss!=NO_BOSS?boss:psx_mod_read_word(FORCE_JIN_ROUTE+s*4));
        }
        for(unsigned c=0;c<4;c++)psx_mod_write_word(table+((unsigned)id*4+c)*4,route);
    }
    patch_base(0x800b2694,0x800b2698,5,table);
    fprintf(stderr,"TTT1 characters: Tekken Force boss routes extended, each guest its own\n");
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
     * pack. +0x1A4 is the move the engine queues: it plays the current one
     * up to the frame at +0x198 first (fighter_move_advance, 0x8002F3AC in
     * t3-ps1) and takes no cancel meanwhile (fighter_cancel_step,
     * 0x8002D9E8). Left at its value, that was the stance's 60 frames, a
     * second with no move after L1 (F14); at 1 the stance starts on the
     * next frame and takes moves at once, as TTT1's switch, a cancel into
     * the new stance (0x800FD268: the cancel's move read in the new table). */
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
    psx_mod_write_half(actor+0x58,1);psx_mod_write_half(actor+0x198,1);
}
int tekken3_ttt1_switch_ready(unsigned player) {
    return player<2 && ttt1_moves(player) && slots[player].loaded &&
           may_switch(player,psx_mod_read_word(0x800a9228+player*0x188c+0x54));
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
/* The CPU's candidate scan (0x80056764, a0 = its state) walks the list of
 * its record (state +88) and, past the end of the clip, the list of the
 * record the 0xC000 link leads to: destination -> record through the
 * state's copy of the alias table (+12, read once into the frame at
 * 0x800567CC), 4 bytes a move number. A native's table holds the engine's
 * aliases only. Standing on the other player's guest record (a reaction
 * that record animates: Heihachi's low parry 0x220F against Jin's TTT1
 * 0x2127, a stagger), the links name guest moves (8192 +): the scan read far
 * past the table and followed whatever it found as a list, up to its next
 * 0xC000 - one game frame in some hundred vblanks, the game nearly frozen
 * for a minute (B64, GH#121, GH#125). For that call the scan reads a table
 * of its own aliases with both guests' records at their move numbers, and
 * its stance everywhere else, as a guest's table. */
static uint32_t cpu_mixed_table(uint32_t table) {
    static uint32_t mixed,key[6];
    /* The native table may be another fighter's at the same address. */
    uint32_t sum=0;
    for(unsigned i=0;i<4023;i++)sum=sum*31+psx_mod_read_word(table+i*4);
    uint32_t now[6]={table,sum,players[0].records,players[1].records,slots[0].generation,slots[1].generation};
    if(!mixed && !(mixed=psx_mod_alloc_guest_memory(ALIAS_ENTRIES*4,16)))return 0;
    if(memcmp(now,key,sizeof now)) {
        uint32_t stance=psx_mod_read_word(table+3*4);
        for(unsigned i=0;i<ALIAS_ENTRIES;i++)psx_mod_write_word(mixed+i*4,i<4023?psx_mod_read_word(table+i*4):stance);
        for(unsigned p=0;p<2;p++)if(slots[p].loaded && players[p].records)
            for(unsigned i=0;i<slots[p].count;i++)psx_mod_write_word(mixed+(slot_base(p)+i)*4,players[p].records+i*56);
        memcpy(key,now,sizeof now);
    }
    return mixed;
}
void __wrap_func_80056764(CPUState *cpu) {
    uint32_t state=cpu->gpr[4],table=0,mixed=0;
    if(cpu->pc==0 || cpu->pc==0x80056764) {
        table=psx_mod_read_word(state+12);
        int owner=record_owner(psx_mod_read_word(state+88));
        if(owner>=0 && !guest_alias_table(table) && alias_table_sound(table) && (mixed=cpu_mixed_table(table)))
            psx_mod_write_word(state+12,mixed);
    }
    __real_func_80056764(cpu);
    if(mixed)psx_mod_write_word(state+12,table);
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
                /* A cinematic holds its record's frame (src/tekken3_cine.c): its
                 * own frame advances the face instead, else it stayed on the
                 * first blink (eyes shut for the whole scene). */
                static int face_cine[2]={-1,-1};
                int cine_frame=tekken3_cine_engine_frame();
                if(cine_frame>=0 && cine_frame!=face_cine[player]) advanced=1;
                face_cine[player]=cine_frame;
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
                else if(tekken3_ttt1_player_motion_mode(player)==4)   /* Jin's Omen: the Devil mark */
                    tekken3_jin_omen_face(player,psx_mod_read_half(actor+0x18),advanced,expression,duration);
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
/* Player s's side of a throw ends with this frame: no throw flag (+0x74), or
 * its next clip already set (+0x1A4), or an automatic entry (0x0010) of its
 * record opening within six frames - the engine's look-ahead starts five
 * frames before the end of the victim's clip when a button is down, and the
 * two fighters run in either order within a frame. P. Jack's 0x309 goes on
 * to his last hit (0x30B) at frame 31, as his victim's lift ends. */
static int pair_ends(unsigned s) {
    uint32_t actor=0x800a9228+s*0x188c,record=psx_mod_read_word(actor+0x54);
    unsigned frame=psx_mod_read_half(actor+0x58);
    if((int16_t)psx_mod_read_half(actor+0x74)<=0 || psx_mod_read_word(actor+0x1a4))return 1;
    uint32_t e=psx_mod_read_word(record+12);
    for(unsigned k=0;k<256;k++,e+=12) {
        unsigned command=psx_mod_read_half(e),window=psx_mod_read_byte(e+9);
        if(command==0x10 && window>=frame && window<=frame+6)return 1;
        if(command==0xc000)break;
    }
    return 0;
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
            /* The end of a victim's clip back on its feet: the engine looks
             * ahead (0x8002DBFC, asking at 0x8002DC00) into the list of the
             * clip it ends on, with the victim's pad, and takes the entry
             * found there, half-turn included. TTT1 (0x800FDB40) reads that
             * alias in the victim's own table: P. Jack's Megaton Punishment
             * lifts it (0x80083380), ends on its dash (0x41), whose list
             * sends it on running (0x0210, no half-turn) or, 1+2 mashed, into
             * its own 1+2 - then the last hit lands from the front, or as a
             * counter (B42). On the guest's dash instead, every entry was
             * refused and the end's half-turn cancelled the clip's 0x7FFF
             * turn: hit from behind, never a counter. Only on a standing
             * record (flags & 0x3000 clear: Jack-2's 809 ends lying on 78),
             * and when the pair ends with this frame (pair_ends): leaving
             * the guest's clips while its throw goes on froze both. */
            int lookahead=s!=player && on_guest && native && cpu->gpr[31]==0x8002dc08 &&
                          !(psx_mod_read_word(base+index*56+4)&0x3000) && pair_ends(s);
            /* The look-ahead reads the list with the victim's directions of
             * the frame (+0x402, set again each frame by 0x8002C580). TTT1's
             * dash takes any direction to 0x3D, flags 0x842, and the last hit
             * launches from the front as with none. A native's T3 dash list
             * differs: back is its back step, guarding from its first frame
             * (0x1052: the guard reaction, the victim left standing and
             * turning), and forward matches nothing, back on the guest's dash
             * (hit from behind). Neutral (5) for this frame, whatever the
             * victim's list; the buttons still count (1+2 mashed: the
             * counter, B42). B68. */
            if(lookahead)psx_mod_write_half(cpu->gpr[4]+0x402,0x200);
            /* A victim's unique clip only holds it while the throw goes on: a
             * plain hit's reaction (Paul's 422, crouched) would have kept the
             * CPU in the attacker's crouch 15 for its 70 frames. */
            if(!lookahead && ((on_guest && !slots[s].recovery[(current-base)/56] && (throwing || s==player)) || unique_throw))
                native=0;
            /* The other way round: out of the unique clips, on a record with
             * an engine alias, towards one without. Paul's TTT1 moves (native
             * pack, 284 aliases) end a crouched reaction (422) on his crouch
             * 15 (alias 40), which loops with 16 (none): a CPU hit there
             * crouched in Paul's clips until the next hit. It takes its own
             * entry for the record it stands on. Not for a hit's reaction
             * (0x8002EBA4 asks at 0x8002EE70): P. Jack's Megaton Punishment
             * leaves its victim on his dash (record 3, aliases 0x1B / 0x1C)
             * as the last hit lands, and its launch (0x2298..0x229C, no
             * alias) became the victim's own dash, then run - no fall, and
             * 1+2 mashed there started the victim's running moves (B42). */
            else if(!native && s!=player && on_guest && cpu->gpr[31]!=0x8002ee78)
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
/* The cinematic engine's poses (src/tekken3_cine.c): its actors play
 * records whose clip is a sentinel of its own. */
extern const uint16_t *tekken3_cine_clip_pose(uint32_t clip);
static const uint16_t *pose(uint32_t clip,int frame) {
    const uint16_t *cine=tekken3_cine_clip_pose(clip);
    if(cine)return cine;
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
