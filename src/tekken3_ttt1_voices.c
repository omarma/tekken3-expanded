/* Original local TTT1 PCM, routed by the game's character-voice dispatcher.
 * Playback runs on the emulation thread, before the existing host audio queue,
 * fade, master volume and resampler. No sample ROM is embedded in the binary. */
#include "psx_runtime.h"
#include "mod_plugins.h"
#include "psx_sha256.h"
#include "spu.h"
#include "audio_trace.h"
#include "tekken3_ttt1_assets.h"
#include "tekken3_arcade_stages.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

extern unsigned tekken3_ttt1_player_motion_mode(unsigned player);
extern void __real_func_80040C90(CPUState *cpu);
extern void __real_spu_render(int16_t *out, int frames);
extern void __real_spu_set_host_mix_volume(int sfx, int music);
extern void __real_spu_init(void);
extern int __real_spu_snapshot_read(const uint8_t *p, uint32_t len);
/* TTT1 sounds other than voices: tekken3_ttt1_sfx.c. */
extern void tekken3_ttt1_sfx_mix(int16_t *out,int frames,int audible,const int16_t main_volume[2],int gain);
extern void tekken3_ttt1_sfx_stop(void);
extern void tekken3_ttt1_sfx_tick(void);

typedef struct { const unsigned char *pcm; uint32_t frames; } GuestSample;
typedef struct { unsigned id, group, slot; uint32_t pos, calls; } GuestVoice;
/* A guest's sample count and IDs are its own: Jun has twelve, numbered 160..171
 * without a gap; Kazuya has ten, non-contiguous, one of them used by two
 * categories. Routing therefore goes through the category/rank word the pack
 * carries for each entry instead of arithmetic on the sample ID. */
enum { MAX_SAMPLES=32, GROUP_MIN=2, GROUP_MAX=5, GROUP_KO=4, GROUP_VICTORY=5 };
/* B140: the cabinet files Baek's and Wang's real KO cries (their Tekken 2
 * ones) as their victory voice, and gives the KO category an attack-like
 * shout (Baek 187) or a damage-like one (Wang 234); TTT1's ko_voice_choose
 * (80113E50) can only pick that one. The KO plays the victory sample instead,
 * which keeps its own role. The pack decoded it at its measured frequency;
 * Wang's is played back at Tekken 2's pitch: the cabinet's 6319 sounds 11 %
 * higher (f0 469 Hz against 416), 5604 matches. */
static const struct { unsigned ko, victory, measured, wanted; } ko_fixes[] = {
    {187, 186, 6319, 6319},
    {234, 235, 6319, 5604},
};
/* T3's KO echo is not in the sample: 80040C90 starts a type-0x11 task
 * (8006F208 -> 800744E0) that plays the same cry again 16 frames later at
 * half volume, then 32 frames later at a quarter. Guests skip 80040C90, so
 * the mixer replays their KO cry the same way. */
enum { ECHO_DELAY=44100*16/60 };
/* Each player has two voices: its cries, and its KO cry with the echoes. A
 * KO by a move that hits again (a multi-hit string, a juggle) sends a damage
 * cry a few frames after the KO cry (0x80041590, life already 0): on a
 * single voice it cut the KO cry and both echoes, whose task is separate in
 * T3. The cry that follows plays over them instead. */
enum { CRY_VOICE, KO_VOICE };
/* Each player's guest has its own bank, following that guest's identity. */
typedef struct {
    unsigned generation;
    int attempted,loaded;
    int mute;                     /* the guest has no voice file: it does not speak (Tetsujin) */
    unsigned char *bank;
    unsigned char *ko_pcm;        /* B140: a KO cry played at another pitch, owned */
    GuestSample samples[MAX_SAMPLES+1];
    unsigned ids[MAX_SAMPLES+1];
    unsigned sample_count;
    unsigned char group_slot[GROUP_MAX+1][MAX_SAMPLES];
    unsigned group_count[GROUP_MAX+1];
    unsigned pool,odds;           /* F35: header words 5 and 6, DR's attack-cry draw (dr_cry) */
} GuestBank;
static GuestBank banks[2];
static GuestVoice voices[2][2];
static int sfx_gain = 100, music_gain = 100, music_muted;
/* A cinematic's music (src/tekken3_cine.c) mutes the game's. */
extern int tekken3_cine_music_mix(int16_t *out,int frames,int audible,int gain,int *mute);
/* So does a TTT stage's music (tekken3_ttt_music.c, TTT Stages). */
extern int tekken3_ttt_music_mix(int16_t *out,int frames,int audible,const int16_t main_volume[2],int gain);
extern void tekken3_ttt_music_state_reset(void);
static uint32_t telemetry;

static uint32_t rd32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static int16_t rd16(const unsigned char *p) {
    return (int16_t)(p[0] | (unsigned)p[1]<<8);
}
extern int tekken3_devil_jin_player(unsigned player);
/* Devil Jin plays TTT1 moves (mode 2) but keeps Jin's cries (native_cry). */
static int guest_active(unsigned p) {
    return p<2 && tekken3_ttt1_player_motion_mode(p)==2 && !tekken3_devil_jin_player(p);
}
static int load_bank(unsigned p);
/* F35: a native on its DR moves (mode 4) whose pack has <Name>-DR-voices.juv
 * (tools/psp/dr_sounds.py, from the player's DR ISO: Jin) speaks with that
 * bank, as a guest does, instead of its Tekken 3 cries. Its TTT1 moves have
 * no voice bank: those keep native_cry. */
static int dr_voiced(unsigned p) {
    return p<2 && tekken3_ttt1_player_motion_mode(p)==4 && !tekken3_devil_jin_player(p) && load_bank(p);
}
static int bank_voiced(unsigned p) { return guest_active(p) || dr_voiced(p); }
enum { DR_DRAW=0xfff };
static uint32_t dr_rand(void) {
    static uint32_t x;
    if(!x)x=(uint32_t)time(NULL)*2654435761u|1u;
    x^=x<<13;x^=x>>17;x^=x<<5;
    return x>>8;
}
static void stop_voices(void) { memset(voices,0,sizeof voices); tekken3_ttt1_sfx_stop(); }

/* B140: point the KO category at the victory sample (ko_fixes), stretched
 * when it plays at another pitch. Matched on the pack's sample IDs, so any
 * bank carrying these arcade samples gets it. */
static void ko_fix(unsigned p,GuestBank *k) {
    if(k->group_count[GROUP_KO]!=1)return;
    unsigned ko=k->ids[k->group_slot[GROUP_KO][0]];
    for(unsigned f=0;f<sizeof ko_fixes/sizeof *ko_fixes;f++) {
        if(ko!=ko_fixes[f].ko)continue;
        for(unsigned i=0;i<k->group_count[GROUP_VICTORY];i++) {
            unsigned slot=k->group_slot[GROUP_VICTORY][i];
            if(k->ids[slot]!=ko_fixes[f].victory)continue;
            const GuestSample *victory=&k->samples[slot];
            if(ko_fixes[f].wanted!=ko_fixes[f].measured) {
                /* Lower pitch, longer cry: linear interpolation of the
                 * 44100 Hz PCM, whose content stays under 5 kHz. */
                uint32_t step=(uint32_t)(((uint64_t)ko_fixes[f].wanted<<16)/ko_fixes[f].measured);
                uint32_t frames=(uint32_t)(((uint64_t)(victory->frames-1)<<16)/step)+1;
                unsigned char *pcm=(unsigned char*)malloc((size_t)frames*2);
                if(!pcm)return;
                for(uint32_t n=0;n<frames;n++) {
                    uint64_t at=(uint64_t)n*step;
                    uint32_t i0=(uint32_t)(at>>16),frac=(uint32_t)(at&65535);
                    int32_t a=rd16(victory->pcm+i0*2),
                            b=i0+1<victory->frames?rd16(victory->pcm+(i0+1)*2):0;
                    int32_t v=a+(int32_t)(((int64_t)(b-a)*frac)>>16);
                    pcm[n*2]=(unsigned char)(v&255);pcm[n*2+1]=(unsigned char)((v>>8)&255);
                }
                k->ko_pcm=pcm;
                slot=k->sample_count++;
                k->samples[slot].pcm=pcm;k->samples[slot].frames=frames;
                k->ids[slot]=ko_fixes[f].victory;
            }
            k->group_slot[GROUP_KO][0]=(unsigned char)slot;
            fprintf(stderr,"%s voices: KO cry %u -> %u at %u Hz, %u frames (B140)\n",
                    tekken3_guest_name_for(p),ko,ko_fixes[f].victory,ko_fixes[f].wanted,
                    k->samples[slot].frames);
            return;
        }
    }
}

static int load_bank(unsigned p) {
    GuestBank *k=&banks[p];
    unsigned generation=tekken3_guest_generation(p);
    if(k->generation!=generation) {
        voices[p][CRY_VOICE].group=voices[p][KO_VOICE].group=0;
        free(k->bank);free(k->ko_pcm);
        memset(k,0,sizeof *k);k->generation=generation;
    }
    if(k->attempted)return k->loaded;
    k->attempted=1;
    const char *root=tekken3_ttt1_asset_root();
    if(!root)return 0;
    char path[4096];
    if(snprintf(path,sizeof path,"%s/%s-voices.juv",root,tekken3_guest_data_prefix_for(p))>=(int)sizeof path)return 0;
    FILE *f=fopen(path,"rb");
    if(!f){
        k->mute=1;
        if(guest_active(p))fprintf(stderr,"%s voices: no voice bank, character cries muted\n",tekken3_guest_name_for(p));
        return 0;
    }
    /* The pack states its own length; the old fixed 527148 was Jun's. */
    unsigned char head[32];
    if(fread(head,1,sizeof head,f)!=sizeof head){fclose(f);return 0;}
    unsigned size=rd32(head+8), count=rd32(head+12);
    if(size<32 || size>8u*1024*1024 || count<1 || count>MAX_SAMPLES ||
       size<32+count*16){fclose(f);return 0;}
    unsigned char *data=(unsigned char*)malloc(size);
    if(!data){fclose(f);return 0;}
    memcpy(data,head,sizeof head);
    int ok=fread(data+sizeof head,1,size-sizeof head,f)==size-sizeof head && fgetc(f)==EOF;
    fclose(f);
    unsigned char digest[32];char hash[65];
    if(ok) {
        psx_sha256_compute(data,size,digest);
        for(unsigned i=0;i<32;i++)snprintf(hash+i*2,3,"%02x",digest[i]);
        /* Identity check only; every structural check below still runs. */
        ok=!tekken3_guest_digests_frozen() ||
           !strcmp(hash,"a83562e4efd6d6d0db0e23ed8a7a6cb4cb5972e74fad66d873d3122ef81a0be3");
    }
    ok=ok && rd32(data)==0x3156554a && rd32(data+4)==1 && rd32(data+16)==44100;
    /* Payload contiguity and bounds are still enforced; only the requirement
     * that the i-th sample be numbered 160+i is gone - it described Jun. */
    uint32_t next=32+count*16;
    for(unsigned i=0;ok && i<count;i++) {
        const unsigned char *entry=data+32+i*16;
        uint32_t offset=rd32(entry+4),frames=rd32(entry+8);
        unsigned group=rd32(entry+12)>>16, index=rd32(entry+12)&65535;
        if(offset!=next || offset>size || !frames || frames>(size-offset)/2 ||
           group<GROUP_MIN || group>GROUP_MAX || index>=MAX_SAMPLES) {
            ok=0;break;
        }
        next+=frames*2;
    }
    if(!ok || next!=size) {
        fprintf(stderr,"%s voices: rejected corrupt or incompatible voice bank\n",tekken3_guest_name_for(p));
        free(data);return 0;
    }
    k->bank=data;
    k->sample_count=count;
    k->pool=rd32(data+20);k->odds=rd32(data+24);
    for(unsigned i=0;i<count;i++) {
        const unsigned char *entry=k->bank+32+i*16;
        k->samples[i].pcm=k->bank+rd32(entry+4);
        k->samples[i].frames=rd32(entry+8);
        k->ids[i]=rd32(entry);
        unsigned group=rd32(entry+12)>>16;
        k->group_slot[group][k->group_count[group]++]=(unsigned char)i;
    }
    for(unsigned g=GROUP_MIN;g<=GROUP_MAX;g++)
        if(!k->group_count[g]) {
            fprintf(stderr,"%s voices: category %u is empty\n",tekken3_guest_name_for(p),g);
            free(data);k->bank=NULL;return 0;
        }
    if(!telemetry)telemetry=psx_mod_alloc_guest_memory(80,16);
    if(telemetry)for(unsigned i=0;i<80;i+=4)psx_mod_write_word(telemetry+i,0);
    fprintf(stderr,"%s voices: %u samples (attack %u, damage %u, ko %u, "
            "victory %u); telemetry=%08X\n",tekken3_guest_name_for(p),count,
            k->group_count[2],k->group_count[3],k->group_count[4],k->group_count[5],telemetry);
    ko_fix(p,k);
    return k->loaded=1;
}

void tekken3_ttt1_voices_tick(void) {
    tekken3_ttt1_sfx_tick();
    for(unsigned p=0;p<2;p++) {
        if(!bank_voiced(p) || psx_mod_read_half(0x800ae204)!=8)
            voices[p][CRY_VOICE].group=voices[p][KO_VOICE].group=0;
        if(telemetry) {
            /* +0..+16 the cries' voice, +20..+28 the KO voice: commands,
             * position, end with the echoes (0 when silent). */
            uint32_t dst=telemetry+p*32;
            GuestVoice *v=&voices[p][CRY_VOICE],*ko=&voices[p][KO_VOICE];
            psx_mod_write_word(dst,v->calls);
            psx_mod_write_word(dst+4,v->id);
            psx_mod_write_word(dst+8,v->group);
            psx_mod_write_word(dst+12,v->pos);
            psx_mod_write_word(dst+16,v->slot<banks[p].sample_count?banks[p].samples[v->slot].frames:0);
            psx_mod_write_word(dst+20,ko->calls);
            psx_mod_write_word(dst+24,ko->pos);
            psx_mod_write_word(dst+28,ko->group && ko->slot<banks[p].sample_count?
                                      banks[p].samples[ko->slot].frames+2*ECHO_DELAY:0);
        }
    }
    if(telemetry)psx_mod_write_word(telemetry+64,(uint32_t)sfx_gain);
}

/* A native fighter on its TTT1 moves (mode 4, and Devil Jin) keeps its own
 * cries, but its moves name them by TTT1's numbers. 80040C90 finds the
 * fighter's voice table at 0x8001AD54 + 24 * a1: one halfword count per
 * category (2 attack, 3 damage, 4 KO, 5 victory), and plays nothing for an
 * index past it. Bring the index into the native category, as a guest's is
 * into its own bank. */
static void native_cry(CPUState *cpu) {
    unsigned command=cpu->gpr[6]&65535,group=command>>12,index=command&4095;
    if(group<2 || group>5)return;
    uint32_t table=psx_mod_read_word(0x8001ad54+cpu->gpr[5]*24);
    if(table<0x80010000 || table>=0x80200000)return;
    int count=(int16_t)psx_mod_read_half(table+(group-2)*2);
    if(count<=0 || (int)index<count)return;
    cpu->gpr[6]=(cpu->gpr[6]&~0xfffu)|(index%(unsigned)count);
}
/* Gon's win pose (the "Tarzan" pose Namco copied from Jack-2: one move per
 * button, 0xD67 square, 0xD68 triangle, 0xD69 cross, 0xD6A circle, the same
 * animation) ends on cry 0x2007 of his voice table 18: key 0xD986, tone 6 of his own
 * bank, a metal crash (F27, GH#32). The pose plays it through its script
 * (0x80041590); in the pose only, sound_play (0x800753BC) is given the
 * landing of the common bank instead (tone 1, event 0x104F, which Gon plays
 * himself when he lands), on the cry's channel and volume: key bank 01,
 * channel 6, volume 6, program 0, tone 1. Chosen by ear by the user over the
 * jump landing (tone 12), the take-off (tone 5) and no sound. The Jacks'
 * crash is an event of their own scripts (0x7098, 0x80040DF4): untouched. */
enum { GON=17, GON_POSE_FIRST=0xd67, GON_POSE_LAST=0xd6a, GON_CRASH=0x2007, GON_FALL=0x4000|6<<10|6<<6|1,
       FIGHTER=0x800a9228, FIGHTER_SIZE=0x188c, NESTED_RETURN=0x80010000 };
static int gon_pose_fall(CPUState *cpu) {
    unsigned p=cpu->gpr[4];
    if(p>1 || (cpu->gpr[6]&65535)!=GON_CRASH)return 0;
    uint32_t a=FIGHTER+p*FIGHTER_SIZE;
    unsigned move=psx_mod_read_half(a+0xa0);
    if(psx_mod_read_half(a+0x18)!=GON || move<GON_POSE_FIRST || move>GON_POSE_LAST)return 0;
    fprintf(stderr,"Gon: Tarzan pose fall, P%u move %03X cry %04X -> common sound %04X\n",p+1,move,GON_CRASH,GON_FALL);
    /* a nested call that stops at a return address never reached */
    uint32_t ra=cpu->gpr[31];
    cpu->gpr[5]=GON_FALL;cpu->gpr[6]=0;cpu->gpr[31]=NESTED_RETURN;cpu->pc=0;
    psx_dispatch_call(cpu,0x800753bc,NESTED_RETURN);
    cpu->gpr[31]=ra;
    cpu->pc=ra;
    return 1;
}
void __wrap_func_80040C90(CPUState *cpu) {
    static int soundlog=-1;
    if(soundlog<0)soundlog=getenv("TEKKEN3_TTT1_SOUND_LOG")!=NULL;
    if(soundlog && (cpu->pc==0 || cpu->pc==0x80040c90))
        fprintf(stderr,"SOUNDLOG P%u voice %04X table %u ra=%08X\n",cpu->gpr[4]+1,cpu->gpr[6]&65535,cpu->gpr[5],cpu->gpr[31]);
    if((cpu->pc==0 || cpu->pc==0x80040c90) && gon_pose_fall(cpu))return;
    if((cpu->pc==0 || cpu->pc==0x80040c90) && cpu->gpr[4]<2 &&
       tekken3_ttt1_player_motion_mode(cpu->gpr[4])==2 && tekken3_devil_jin_player(cpu->gpr[4]))native_cry(cpu);
    unsigned p=cpu->gpr[4], command=cpu->gpr[6]&65535;
    if((cpu->pc==0 || cpu->pc==0x80040c90) && p<2 && tekken3_ttt1_player_motion_mode(p)==4 && !dr_voiced(p))native_cry(cpu);
    /* A guest without voices must not borrow the cries of Jin, whose
     * character file it goes through: its cries are simply not played. */
    if((cpu->pc==0 || cpu->pc==0x80040c90) && guest_active(p) && !load_bank(p) && banks[p].mute) {
        cpu->pc=cpu->gpr[31];return;
    }
    if((cpu->pc==0 || cpu->pc==0x80040c90) && (guest_active(p) ? load_bank(p) : dr_voiced(p))) {
        const GuestBank *k=&banks[p];
        unsigned group=command>>12, index=command&4095, id;
        /* The native common/reaction records still use Jin's category sizes.
         * Translate within the guest's matching category; never into another
         * bank. The guest's own commands are in range and keep their exact ID. */
        if(group<GROUP_MIN || group>GROUP_MAX || !k->group_count[group]) {
            cpu->pc=cpu->gpr[31];return;
        }
        /* F35: DR_DRAW, written by tools/psp/dr_pack.py on a DR move that
         * names no cry, is DR's own draw of an attack cry: one of the bank's
         * first `pool` attack cries, `odds` times in 256 (measured in DR;
         * Tekken 3 draws once in 4 from its own list). T3 has already set
         * the cry's cooldown: a draw without a cry stays silent. */
        if(group==2 && index==DR_DRAW && !guest_active(p)) {
            unsigned pool=k->pool && k->pool<k->group_count[2]?k->pool:k->group_count[2];
            if((dr_rand()&255)>=k->odds) {
                if(soundlog)fprintf(stderr,"%s voice: P%u DR draw, no cry\n",tekken3_guest_name_for(p),p+1);
                cpu->pc=cpu->gpr[31];return;
            }
            index=dr_rand()%pool;
        }
        unsigned slot=k->group_slot[group][index%k->group_count[group]];
        id=k->ids[slot];
        GuestVoice *v=&voices[p][group==GROUP_KO?KO_VOICE:CRY_VOICE];
        v->id=id;v->slot=slot;v->group=group;v->pos=0;v->calls++;
        fprintf(stderr,"%s voice: P%u command=%04X sample=%u\n",tekken3_guest_name_for(p),p+1,command,id);
        /* Only this actor's character cry is replaced. Shared hit, movement,
         * announcer and opponent calls keep the native sound path. */
        cpu->pc=cpu->gpr[31];return;
    }
    /* Natives, Devil Jin and natives on TTT1 moves included: Tekken 3 plays
     * the KO cry and its own echo task. Logged for tools/test_ko_echo.py. */
    if((cpu->pc==0 || cpu->pc==0x80040c90) && p<2 && (cpu->gpr[6]&65535)>>12==GROUP_KO && !bank_voiced(p))
        fprintf(stderr,"TTT1 voices: P%u native KO cry %04X\n",p+1,cpu->gpr[6]&65535);
    __real_func_80040C90(cpu);
}

static void mix_render(int16_t *out,int frames) {
    __real_spu_render(out,frames);
    if(!out || frames<=0)return;
    SpuGlobalState g;spu_get_global_state(&g);
    int audible=(g.ctrl&0xc000)==0xc000;
    int16_t main_volume[2]={(int16_t)spu_read(0x1f801db8),(int16_t)spu_read(0x1f801dba)};
    tekken3_ttt1_sfx_mix(out,frames,audible,main_volume,sfx_gain);
    /* TTT stage 4's thunder (src/tekken3_arcade_stages.c), with the sounds. */
    tekken3_arcade_stages_thunder_mix(out,frames,audible,main_volume,sfx_gain);
    int embu_music=0;
    if(!tekken3_cine_music_mix(out,frames,audible,music_gain,&embu_music))embu_music=0;
    if(!embu_music)embu_music=tekken3_ttt_music_mix(out,frames,audible,main_volume,music_gain);
    if(embu_music!=music_muted) {
        music_muted=embu_music;
        __real_spu_set_host_mix_volume(sfx_gain,embu_music?0:music_gain);
    }
    if(!banks[0].loaded && !banks[1].loaded)return;
    for(unsigned p=0;p<2;p++)for(unsigned which=CRY_VOICE;which<=KO_VOICE;which++) {
        GuestVoice *v=&voices[p][which];
        if(!v->group || !banks[p].loaded)continue;
        if(!(guest_active(p) || (tekken3_ttt1_player_motion_mode(p)==4 && !tekken3_devil_jin_player(p))) ||
           psx_mod_read_half(0x800ae204)!=8){v->group=0;continue;}
        const GuestSample *sample=&banks[p].samples[v->slot];
        uint32_t echoes=v->group==GROUP_KO?2:0, end=sample->frames+echoes*ECHO_DELAY;
        for(int f=0;f<frames && v->pos<end;f++,v->pos++) {
            int32_t value=0;
            /* Match the PS1 voice mix level, with a short attack ramp. PCM
             * stays uncompressed; SFX and host master controls both apply. */
            for(uint32_t e=0;e<=echoes && v->pos>=e*ECHO_DELAY;e++) {
                uint32_t at=v->pos-e*ECHO_DELAY;
                if(at>=sample->frames)continue;
                int ramp=at<220?(int)at:220;
                value+=(rd16(sample->pcm+at*2)*ramp/220)>>e;
            }
            value=value*sfx_gain/100/4;
            if(!audible)value=0;
            for(unsigned ch=0;ch<2;ch++) {
                int32_t mixed=(int32_t)out[f*2+ch]+value*main_volume[ch]/32768;
                out[f*2+ch]=(int16_t)(mixed>32767?32767:mixed< -32768?-32768:mixed);
            }
        }
        if(v->pos==end)v->group=0;
    }
}

/* Benches (tools/test_f35_jin_dr_sounds.py --wav): a game started with
 * --headless opens no audio device, so the debug server's host tap stays
 * empty, and its SPU taps are taken before this mixer (the guests' cries and
 * sounds). TEKKEN3_AUDIO_MIX_TAP=1 records the whole mix into the host tap
 * instead. */
void __wrap_spu_render(int16_t *out,int frames) {
    static int tap=-1;
    mix_render(out,frames);
    if(tap<0)tap=getenv("TEKKEN3_AUDIO_MIX_TAP")!=NULL;
    if(tap && out && frames>0)audio_trace_pcm(AUDIO_TAP_HOST,out,frames);
}
void __wrap_spu_set_host_mix_volume(int sfx,int music) {
    sfx_gain=sfx<0?0:sfx>100?100:sfx;
    music_gain=music<0?0:music>100?100:music;
    __real_spu_set_host_mix_volume(sfx,music_muted?0:music);
}
void __wrap_spu_init(void) { stop_voices();tekken3_ttt_music_state_reset();tekken3_arcade_stages_thunder_stop();__real_spu_init(); }
int __wrap_spu_snapshot_read(const uint8_t *p,uint32_t len) {
    int result=__real_spu_snapshot_read(p,len);
    if(result){stop_voices();tekken3_ttt_music_state_reset();tekken3_arcade_stages_thunder_stop();}
    return result;
}
