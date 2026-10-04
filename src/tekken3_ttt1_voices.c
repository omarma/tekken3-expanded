/* Original local TTT1 PCM, routed by the game's character-voice dispatcher.
 * Playback runs on the emulation thread, before the existing host audio queue,
 * fade, master volume and resampler. No sample ROM is embedded in the binary. */
#include "psx_runtime.h"
#include "mod_plugins.h"
#include "psx_sha256.h"
#include "spu.h"
#include "tekken3_ttt1_assets.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
enum { MAX_SAMPLES=32, GROUP_MIN=2, GROUP_MAX=5, GROUP_KO=4 };
/* T3's KO echo is not in the sample: 80040C90 starts a type-0x11 task
 * (8006F208 -> 800744E0) that plays the same cry again 16 frames later at
 * half volume, then 32 frames later at a quarter. Guests skip 80040C90, so
 * the mixer replays their KO cry the same way. */
enum { ECHO_DELAY=44100*16/60 };
/* Each player's guest has its own bank, following that guest's identity. */
typedef struct {
    unsigned generation;
    int attempted,loaded;
    int mute;                     /* the guest has no voice file: it does not speak (Tetsujin) */
    unsigned char *bank;
    GuestSample samples[MAX_SAMPLES];
    unsigned sample_count;
    unsigned char group_slot[GROUP_MAX+1][MAX_SAMPLES];
    unsigned group_count[GROUP_MAX+1];
} GuestBank;
static GuestBank banks[2];
static GuestVoice voices[2];
static int sfx_gain = 100, music_gain = 100, music_muted;
/* The Embu's music of our own (tekken3_embu_scenes.c) mutes the game's. */
extern int tekken3_embu_music_mix(int16_t *out,int frames,int audible,int gain);
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
static void stop_voices(void) { memset(voices,0,sizeof voices); tekken3_ttt1_sfx_stop(); }

static int load_bank(unsigned p) {
    GuestBank *k=&banks[p];
    unsigned generation=tekken3_guest_generation(p);
    if(k->generation!=generation) {
        voices[p].group=0;
        free(k->bank);
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
        fprintf(stderr,"%s voices: no voice bank, character cries muted\n",tekken3_guest_name_for(p));
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
    for(unsigned i=0;i<count;i++) {
        const unsigned char *entry=k->bank+32+i*16;
        k->samples[i].pcm=k->bank+rd32(entry+4);
        k->samples[i].frames=rd32(entry+8);
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
    return k->loaded=1;
}

void tekken3_ttt1_voices_tick(void) {
    tekken3_ttt1_sfx_tick();
    for(unsigned p=0;p<2;p++) {
        if(!guest_active(p) || psx_mod_read_half(0x800ae204)!=8)voices[p].group=0;
        else (void)load_bank(p);
        if(telemetry) {
            uint32_t dst=telemetry+p*32;
            GuestVoice *v=&voices[p];
            psx_mod_write_word(dst,v->calls);
            psx_mod_write_word(dst+4,v->id);
            psx_mod_write_word(dst+8,v->group);
            psx_mod_write_word(dst+12,v->pos);
            psx_mod_write_word(dst+16,v->slot<banks[p].sample_count?banks[p].samples[v->slot].frames:0);
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
void __wrap_func_80040C90(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x80040c90) && cpu->gpr[4]<2 &&
       tekken3_ttt1_player_motion_mode(cpu->gpr[4])==2 && tekken3_devil_jin_player(cpu->gpr[4]))native_cry(cpu);
    unsigned p=cpu->gpr[4], command=cpu->gpr[6]&65535;
    if((cpu->pc==0 || cpu->pc==0x80040c90) && p<2 && tekken3_ttt1_player_motion_mode(p)==4)native_cry(cpu);
    /* A guest without voices must not borrow the cries of Jin, whose
     * character file it goes through: its cries are simply not played. */
    if((cpu->pc==0 || cpu->pc==0x80040c90) && guest_active(p) && !load_bank(p) && banks[p].mute) {
        cpu->pc=cpu->gpr[31];return;
    }
    if((cpu->pc==0 || cpu->pc==0x80040c90) && guest_active(p) && load_bank(p)) {
        const GuestBank *k=&banks[p];
        unsigned group=command>>12, index=command&4095, id;
        /* The native common/reaction records still use Jin's category sizes.
         * Translate within the guest's matching category; never into another
         * bank. The guest's own commands are in range and keep their exact ID. */
        if(group<GROUP_MIN || group>GROUP_MAX || !k->group_count[group]) {
            cpu->pc=cpu->gpr[31];return;
        }
        unsigned slot=k->group_slot[group][index%k->group_count[group]];
        id=rd32(k->bank+32+slot*16);
        GuestVoice *v=&voices[p];
        v->id=id;v->slot=slot;v->group=group;v->pos=0;v->calls++;
        fprintf(stderr,"%s voice: P%u command=%04X sample=%u\n",tekken3_guest_name_for(p),p+1,command,id);
        /* Only this actor's character cry is replaced. Shared hit, movement,
         * announcer and opponent calls keep the native sound path. */
        cpu->pc=cpu->gpr[31];return;
    }
    __real_func_80040C90(cpu);
}

void __wrap_spu_render(int16_t *out,int frames) {
    __real_spu_render(out,frames);
    if(!out || frames<=0)return;
    SpuGlobalState g;spu_get_global_state(&g);
    int audible=(g.ctrl&0xc000)==0xc000;
    int16_t main_volume[2]={(int16_t)spu_read(0x1f801db8),(int16_t)spu_read(0x1f801dba)};
    tekken3_ttt1_sfx_mix(out,frames,audible,main_volume,sfx_gain);
    int embu_music=tekken3_embu_music_mix(out,frames,audible,music_gain);
    if(embu_music!=music_muted) {
        music_muted=embu_music;
        __real_spu_set_host_mix_volume(sfx_gain,embu_music?0:music_gain);
    }
    if(!banks[0].loaded && !banks[1].loaded)return;
    for(unsigned p=0;p<2;p++) {
        GuestVoice *v=&voices[p];
        if(!v->group || !banks[p].loaded)continue;
        if(!guest_active(p) || psx_mod_read_half(0x800ae204)!=8){v->group=0;continue;}
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
void __wrap_spu_set_host_mix_volume(int sfx,int music) {
    sfx_gain=sfx<0?0:sfx>100?100:sfx;
    music_gain=music<0?0:music>100?100:music;
    __real_spu_set_host_mix_volume(sfx,music_muted?0:music);
}
void __wrap_spu_init(void) { stop_voices();__real_spu_init(); }
int __wrap_spu_snapshot_read(const uint8_t *p,uint32_t len) {
    int result=__real_spu_snapshot_read(p,len);
    if(result)stop_voices();
    return result;
}
