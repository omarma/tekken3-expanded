/* TTT1 sounds other than voices. A TTT1 event names a sound by an index
 * into the arcade's sound table (80194CA8, read by 80113C78), and T3 uses
 * the same numbers and the same engine rules (swing, impact, guard,
 * footsteps) with its own samples. This file plays TTT1's samples, from the
 * guest's pack recorded from the arcade driver (tools/ttt1/sfx.py): for the
 * engine's sounds of a guest's own moves, for the sounds of TTT1 event
 * scripts (marked with bit 0x800 of the index by the importer, which T3's
 * own events never set: the Jacks' laugh after their Body Press...), and
 * for the lasers' sound, which TTT1 asks for directly. Mixed on the
 * emulation thread with the voices (tekken3_ttt1_voices.c). */
#include "psx_runtime.h"
#include "mod_plugins.h"
#include "tekken3_ttt1_assets.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern unsigned tekken3_ttt1_player_motion_mode(unsigned player);
/* A guest (mode 2) or a native fighter on its TTT1 moves (mode 4): both
 * play their moves' TTT1 sounds. */
static int ttt1_moves(unsigned p) {
    unsigned mode=tekken3_ttt1_player_motion_mode(p);
    return mode==2 || mode==4;
}
extern int tekken3_devil_jin_player(unsigned player);
extern int tekken3_ttt1_laser_record(unsigned p,uint32_t record);
extern void __real_func_80040DF4(CPUState *cpu);
extern void __real_func_800757A8(CPUState *cpu);
extern int tekken3_guest_character(unsigned id);

/* LASER_SOUND: the lasers' sound, which TTT1 asks for outside its table
 * (tools/ttt1/sfx.py RAW). NAME_SOUND: the announcer calling the guest's
 * name (tools/ttt1/sfx.py NAME). */
enum { SFX_MARK=0x800, SFX_INDEXES=0x800, LASER_SOUND=1024, NAME_SOUND=1025, CHANNELS=8, PACK_MAGIC=0x3153554a /* "JUS1" */ };
typedef struct { const unsigned char *pcm; uint32_t frames; } SfxSample;
typedef struct {
    unsigned generation;
    int attempted,loaded;
    unsigned char *pack;
    unsigned count;
    const unsigned char *entries;
} SfxBank;
typedef struct { const unsigned char *pcm; uint32_t frames,pos; unsigned index,age; } SfxChannel;
static SfxBank banks[2];
static SfxChannel channels[CHANNELS];
static unsigned started;

static uint32_t rd32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static int in_fight(void) { return psx_mod_read_half(0x800ae204)==8; }

void tekken3_ttt1_sfx_stop(void) { memset(channels,0,sizeof channels); }

/* <prefix>-sfx.jus: header of eight words (magic, version 1, size, count,
 * rate 44100), then count entries of four words (sound index, offset,
 * frames, driver sound ID) in index order, then mono 16-bit PCM. */
/* any_motion: the announcer's name only needs the guest's identity, not its
 * model in place. */
static int load_bank_for(unsigned p,int any_motion) {
    SfxBank *k=&banks[p];
    unsigned generation=tekken3_guest_moves_generation(p);
    if(k->generation!=generation) {
        for(unsigned c=0;c<CHANNELS;c++)
            if(k->pack && channels[c].pcm>=k->pack && channels[c].pcm<k->pack+rd32(k->pack+8))
                memset(&channels[c],0,sizeof channels[c]);
        free(k->pack);memset(k,0,sizeof *k);k->generation=generation;
    }
    /* Not (yet) a guest in the fight: a native after a guest keeps that
     * guest's identity, and a failure cached here would stick to the guest. */
    if(!any_motion && !ttt1_moves(p))return 0;
    if(k->attempted)return k->loaded;
    k->attempted=1;
    const char *root=tekken3_ttt1_asset_root();
    if(!root)return 0;
    char path[4096];
    if(snprintf(path,sizeof path,"%s/%s-sfx.jus",root,tekken3_guest_moves_prefix_for(p))>=(int)sizeof path)return 0;
    FILE *f=fopen(path,"rb");
    if(!f){fprintf(stderr,"%s sounds: no sound pack\n",tekken3_guest_name_for(p));return 0;}
    unsigned char head[32];
    if(fread(head,1,sizeof head,f)!=sizeof head){fclose(f);return 0;}
    unsigned size=rd32(head+8),count=rd32(head+12);
    int ok=rd32(head)==PACK_MAGIC && rd32(head+4)==1 && rd32(head+16)==44100 &&
           size>=32 && size<=64u*1024*1024 && count<=SFX_INDEXES && size>=32+count*16;
    unsigned char *data=ok?malloc(size):NULL;
    if(data) {
        memcpy(data,head,sizeof head);
        ok=fread(data+sizeof head,1,size-sizeof head,f)==size-sizeof head && fgetc(f)==EOF;
    }
    fclose(f);
    uint32_t next=32+count*16;
    for(unsigned i=0;ok && data && i<count;i++) {
        const unsigned char *e=data+32+i*16;
        uint32_t index=rd32(e),offset=rd32(e+4),frames=rd32(e+8);
        if(index>=SFX_INDEXES || (i && index<=rd32(e-16)) || offset!=next || !frames || frames>(size-offset)/2)ok=0;
        next+=frames*2;
    }
    if(!data || !ok || next!=size) {
        fprintf(stderr,"%s sounds: rejected corrupt or incompatible sound pack\n",tekken3_guest_name_for(p));
        free(data);return 0;
    }
    k->pack=data;k->count=count;k->entries=data+32;
    fprintf(stderr,"%s sounds: %u TTT1 sounds\n",tekken3_guest_name_for(p),count);
    return k->loaded=1;
}
static int load_bank(unsigned p){return load_bank_for(p,0);}
static int lookup(unsigned p,unsigned index,SfxSample *s) {
    const SfxBank *k=&banks[p];
    unsigned lo=0,hi=k->count;
    while(lo<hi) {
        unsigned mid=(lo+hi)/2,at=rd32(k->entries+mid*16);
        if(at==index){s->pcm=k->pack+rd32(k->entries+mid*16+4);s->frames=rd32(k->entries+mid*16+8);return 1;}
        if(at<index)lo=mid+1;else hi=mid;
    }
    return 0;
}
static int find(unsigned p,unsigned index,SfxSample *s) {
    return p<2 && load_bank(p) && lookup(p,index,s);
}
static void play(const SfxSample *s,unsigned index) {
    /* A free channel, else the one that started first. */
    unsigned pick=0;
    for(unsigned c=0;c<CHANNELS;c++) {
        if(!channels[c].pcm){pick=c;break;}
        if(channels[c].age<channels[pick].age)pick=c;
    }
    channels[pick]=(SfxChannel){s->pcm,s->frames,0,index,++started};
}

/* A guest in one of its own TTT1 moves (records in guest memory). */
static int guest_move(unsigned p) {
    if(p>1 || !ttt1_moves(p))return 0;
    uint32_t record=psx_mod_read_word(0x800a9228+p*0x188c+0x54);
    return record>=0x9f000000u && record<0x9f400000u;
}

/* 80040DF4(player, event) plays a sound event on T3's sound engine. Every
 * live path ends there: a script or a move's hit list (via 80040DA0, which
 * also records the event for replays: 8003352C, replayed by 80040C20) and
 * the engine's own sounds. */
extern void tekken3_guest_note_guard(unsigned defender);
void __wrap_func_80040DF4(CPUState *cpu) {
    unsigned p=cpu->gpr[4]&0xffff,command=cpu->gpr[5]&65535,group=command>>12;
    static int soundlog=-1;
    if(soundlog<0)soundlog=getenv("TEKKEN3_TTT1_SOUND_LOG")!=NULL;
    if(soundlog && (cpu->pc==0 || cpu->pc==0x80040df4))
        fprintf(stderr,"SOUNDLOG P%u %04X ra=%08X\n",p+1,command,cpu->gpr[31]);
    if((cpu->pc==0 || cpu->pc==0x80040df4) && (group<2 || group>5) && group<8 && in_fight()) {
        unsigned index=command&(SFX_MARK-1);
        SfxSample s;
        if(command&SFX_MARK) {
            /* Category 0 stops a sound: TTT1 sends it through 801255B0,
             * which rewrites the request slot without its request bit, so
             * the driver drops what that channel plays. Scripts pair them
             * (Jacks' machinery: 0x1891 then 0x0891, 0x188C then 0x008C). */
            if(!group) {
                for(unsigned c=0;c<CHANNELS;c++)
                    if(channels[c].pcm && channels[c].index==index)memset(&channels[c],0,sizeof channels[c]);
                static unsigned stopped;
                if(stopped<400){stopped++;fprintf(stderr,"TTT1 characters: P%u stop %04X (index %u)\n",p+1,command,index);}
                cpu->pc=cpu->gpr[31];return;
            }
            /* A marked TTT1 script sound. A script can make the other
             * fighter sound (a throw's victim): the sound is still in the
             * guest's own pack. */
            if(find(p,index,&s) || find(p^1,index,&s)) {
                play(&s,index);
                static unsigned logged;
                if(logged<400){logged++;fprintf(stderr,"TTT1 characters: P%u sound %04X (index %u)\n",p+1,command,index);}
            }
            cpu->pc=cpu->gpr[31];return;
        }
        /* T3's engine applies TTT1's own rules to a guest's move, with the
         * same numbers (swing 80041B5C, impact 80041F0C, hit list 80041364,
         * guard 8004127C / 8004129C on the defender): TTT1's sample of the
         * same number replaces T3's. The guard sound belongs to the
         * attacker's move. */
        uint32_t ra=cpu->gpr[31];
        /* Unknown played by the CPU switches under pressure, guarding too. */
        if(ra==0x8004127c || ra==0x8004129c)tekken3_guest_note_guard(p);
        int owner=guest_move(p)?(int)p:
                  ((ra==0x8004127c || ra==0x8004129c) && guest_move(p^1))?(int)(p^1):-1;
        if(owner>=0 && find((unsigned)owner,index,&s)) {
            play(&s,index);
            static unsigned logged;
            if(logged<400){logged++;fprintf(stderr,"TTT1 characters: P%u engine sound %04X (TTT1)\n",p+1,command);}
            cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_80040DF4(cpu);
}

/* 800757A8(player) is T3's announcer calling a fighter's name (Practice at
 * the start of the stage, and its two other callers 8003DC68 / 8003E0E4): it
 * keys on program 0, note 60 of the fighter's own voice bank, whose last
 * sample is the name. A guest is loaded through Jin's bank, so the announcer
 * said "Jin Kazama"; its pack carries the name TTT1's announcer gives it
 * when it is picked. It returns 0 once the name is playing, 1 when there is
 * none (actor+0x14 == 0x22, Eddy's third costume); a guest without a name
 * (Tetsujin) stays silent too. */
void __wrap_func_800757A8(CPUState *cpu) {
    unsigned p=cpu->gpr[4];
    /* A native on its TTT1 moves and Devil Jin keep T3's call of their name. */
    if((cpu->pc==0 || cpu->pc==0x800757a8) && p<2 && tekken3_ttt1_player_motion_mode(p)!=4 &&
       !tekken3_devil_jin_player(p) &&
       tekken3_guest_character(psx_mod_read_half(0x800a9240+p*0x188c))>=0) {
        SfxSample s;
        int found=load_bank_for(p,1) && lookup(p,NAME_SOUND,&s);
        if(found)play(&s,NAME_SOUND);
        fprintf(stderr,"%s: P%u announced name%s\n",tekken3_guest_name_for(p),p+1,found?"":" (none in its pack)");
        cpu->gpr[2]=!found;
        cpu->pc=cpu->gpr[31];return;
    }
    __real_func_800757A8(cpu);
}

/* The lasers' own sound: 80116EA4 asks for it when the beam starts
 * (80116F8C), on the frame the move's active window opens (record+45, frame
 * actor+0x58, as for the beam), whatever the beam type. */
void tekken3_ttt1_sfx_tick(void) {
    static uint32_t last_record[2];
    static unsigned last_frame[2];
    if(!in_fight())return;
    for(unsigned p=0;p<2;p++) {
        if(!guest_move(p))continue;
        uint32_t actor=0x800a9228+p*0x188c,record=psx_mod_read_word(actor+0x54);
        unsigned frame=psx_mod_read_half(actor+0x58);
        if(record==last_record[p] && frame==last_frame[p])continue;
        last_record[p]=record;last_frame[p]=frame;
        unsigned start=psx_mod_read_byte(record+45);
        SfxSample s;
        if(start && frame==start && tekken3_ttt1_laser_record(p,record) && find(p,LASER_SOUND,&s)) {
            play(&s,LASER_SOUND);
            static unsigned said;
            if(said<100){said++;fprintf(stderr,"TTT1 characters: P%u laser sound\n",p+1);}
        }
    }
}

/* Called by the voices' spu_render wrapper: out is the stereo output about
 * to be queued; gain as for the voices (host SFX volume, 0..100). */
void tekken3_ttt1_sfx_mix(int16_t *out,int frames,int audible,const int16_t main_volume[2],int gain) {
    if(!in_fight()){tekken3_ttt1_sfx_stop();return;}
    static int boost=-1;
    if(boost<0) {
        const char *v=getenv("TEKKEN3_TTT1_SFX_VOLUME");
        boost=v?atoi(v):200;
        if(boost<0)boost=0;
        if(boost>800)boost=800;
    }
    for(unsigned c=0;c<CHANNELS;c++) {
        SfxChannel *ch=&channels[c];
        if(!ch->pcm)continue;
        for(int f=0;f<frames && ch->pos<ch->frames;f++,ch->pos++) {
            const unsigned char *q=ch->pcm+ch->pos*2;
            int32_t value=(int16_t)(q[0]|(unsigned)q[1]<<8);
            /* The pack holds the arcade driver's level relative to the
             * voices; against T3's own sounds it plays quiet, so it gets a
             * boost (TEKKEN3_TTT1_SFX_VOLUME, percent, default 200). */
            value=value*gain/100*boost/100;
            if(!audible)value=0;
            for(unsigned k=0;k<2;k++) {
                int32_t mixed=(int32_t)out[f*2+k]+value*main_volume[k]/32768;
                out[f*2+k]=(int16_t)(mixed>32767?32767:mixed< -32768?-32768:mixed);
            }
        }
        if(ch->pos>=ch->frames)memset(ch,0,sizeof *ch);
    }
}
