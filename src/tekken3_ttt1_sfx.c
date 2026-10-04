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
extern void __real_func_8008D658(CPUState *cpu);
extern void __real_func_8003CB84(CPUState *cpu);
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
/* A hit on a metallic fighter: T3's hit handler (80040EA0) answers it with
 * 80041B70 (events 0x705D / 0x7098 / 0x7099, recorded for replays) in place of
 * the limb's impact (80041CB4), when the struck fighter's ID is 16, Gun Jack.
 * TTT1 (801141B0..801141D4, 801148D0) does the same for sound profiles 18,
 * 30 and 35: Gun Jack, Jack-2, P.Jack. A guest has its own ID, so Jack-2 and
 * P.Jack answered with the flesh impact. 80041CB4(attacker) is wrapped to
 * call 80041B70(attacker, victim) when the victim is one of them; the
 * sound it asks for plays TTT1's sample (the victim's pack carries them). */
enum { ACTOR_BASE=0x800a9228, ACTOR_SIZE=0x188c, METAL_HIT_RETURN=0x80041c2c };
extern void __real_func_80041CB4(CPUState *cpu);
extern void func_80041B70(CPUState *cpu);
static int metal_guest(unsigned p) {
    if(p>1 || tekken3_ttt1_player_motion_mode(p)!=2)return 0;
    const char *prefix=tekken3_guest_data_prefix_for(p);
    return prefix && (!strcmp(prefix,"Jack2-TTT1") || !strcmp(prefix,"Pjack-TTT1"));
}
void __wrap_func_80041CB4(CPUState *cpu) {
    uint32_t attacker=cpu->gpr[4];
    unsigned p=(attacker-ACTOR_BASE)/ACTOR_SIZE;
    if((cpu->pc==0 || cpu->pc==0x80041cb4) && in_fight() && p<2 && attacker==ACTOR_BASE+p*ACTOR_SIZE && metal_guest(p^1)) {
        cpu->gpr[5]=ACTOR_BASE+(p^1)*ACTOR_SIZE;
        cpu->pc=0;
        func_80041B70(cpu);
        return;
    }
    __real_func_80041CB4(cpu);
}
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
        /* The metallic answer to a hit on Jack-2 / P.Jack (80041B70 above): the
         * victim's own pack holds TTT1's clang. */
        if(ra==METAL_HIT_RETURN && p<2 && metal_guest(p) && find(p,index,&s)) {
            play(&s,index);
            static unsigned said;
            if(said<400){said++;fprintf(stderr,"TTT1 characters: P%u metal hit %04X (TTT1)\n",p+1,command);}
            cpu->pc=cpu->gpr[31];return;
        }
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
/* Set by each name call, cleared once "wins" may follow (8008D658 below);
 * name_guest: the name plays in our mixer, voice 1 keeps what it had. */
static unsigned name_wait;
static int name_guest;
void __wrap_func_800757A8(CPUState *cpu) {
    unsigned p=cpu->gpr[4];
    if(cpu->pc==0 || cpu->pc==0x800757a8){name_wait=1;name_guest=0;}
    /* A native on its TTT1 moves and Devil Jin keep T3's call of their name. */
    if((cpu->pc==0 || cpu->pc==0x800757a8) && p<2 && tekken3_ttt1_player_motion_mode(p)!=4 &&
       !tekken3_devil_jin_player(p) &&
       tekken3_guest_character(psx_mod_read_half(0x800a9240+p*0x188c))>=0) {
        SfxSample s;
        int found=load_bank_for(p,1) && lookup(p,NAME_SOUND,&s);
        if(found){play(&s,NAME_SOUND);name_guest=1;}
        fprintf(stderr,"%s: P%u announced name%s\n",tekken3_guest_name_for(p),p+1,found?"":" (none in its pack)");
        cpu->gpr[2]=!found;
        cpu->pc=cpu->gpr[31];return;
    }
    __real_func_800757A8(cpu);
}

/* A Team Battle winner is announced as "<name> wins": 8003E0E4 calls the
 * name (800757A8, voice 1), then 8006F1D4 starts a task (80074494) that
 * waits while SpuGetKeyStatus(voice 1) (8008D658, a0 = 2, returning to
 * 800744AC) gives 1, keyed on with its envelope up, then says "wins"
 * (0x86DA) on the same voice. The emulated SPU only moves the envelope
 * when it renders, between frames: the task's first check still read 0
 * and got 3, "wins" came at once and cut a native's name. A guest's name
 * plays in our mixer, not on voice 1: "wins" came over it, or never came
 * while voice 1 still played the K.O.'s sound. The task now hears voice 1
 * busy while a guest's name plays and free after it, and reads a native's
 * 3 as still starting for the few frames before its envelope is up. */
/* SURVIVAL RESULTS (state 14) announces the player's fighter the same way,
 * from 80075864 (returning to 800758B4), which says "wins" once voice 1 is
 * free: a guest's name now plays there too and waits the same. */
enum { WINS_TASK_RETURN=0x800744ac, RESULTS_WINS_RETURN=0x800758b4, NAME_START_CHECKS=4 };
/* Frames seen by the round's end (8003CB84 below), the last one on which
 * the task checked voice 1, and the frames "wins" still plays. */
static unsigned round_frames,wins_checked,wins_left;
static int wins_task;
enum { WINS_FRAMES=45 };
void __wrap_func_8008D658(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8008d658) && cpu->gpr[31]==RESULTS_WINS_RETURN && cpu->gpr[4]==2 && name_wait && name_guest) {
        cpu->gpr[2]=0;
        for(unsigned c=0;c<CHANNELS;c++)
            if(channels[c].pcm && channels[c].index==NAME_SOUND && channels[c].pos<channels[c].frames)cpu->gpr[2]=1;
        static unsigned checks;
        checks++;
        if(!cpu->gpr[2]){name_wait=0;fprintf(stderr,"SURVIVAL RESULTS: guest's name over after %u checks, \"wins\" may follow\n",checks);checks=0;}
        cpu->pc=cpu->gpr[31];return;
    }
    if((cpu->pc==0 || cpu->pc==0x8008d658) && cpu->gpr[31]==WINS_TASK_RETURN && cpu->gpr[4]==2) {
        if(name_wait && name_guest) {
            cpu->gpr[2]=0;
            for(unsigned c=0;c<CHANNELS;c++)
                if(channels[c].pcm && channels[c].index==NAME_SOUND && channels[c].pos<channels[c].frames)cpu->gpr[2]=1;
            if(!cpu->gpr[2])name_wait=0;
            cpu->pc=cpu->gpr[31];
        } else {
            __real_func_8008D658(cpu);
            if(name_wait) {
                if(cpu->gpr[2]==3 && name_wait<=NAME_START_CHECKS){name_wait++;cpu->gpr[2]=1;}
                else name_wait=0;
            }
        }
        wins_task=1;wins_checked=round_frames;
        if(cpu->gpr[2]!=1)wins_left=WINS_FRAMES;       /* the task says "wins" now */
        return;
    }
    __real_func_8008D658(cpu);
}

/* 8003CB84 runs the end of a round (sub-state 0x80096F2C, frames in
 * 0x80096F30). In sub-state 6 the winner holds its pose and is announced,
 * then the game moves on: to the next round ~190 frames
 * after the name, but to the next fight's loading ~60 frames after it,
 * which clears the task list. A name longer than that (Wang, Bruce, Lee,
 * Baek, Michelle, Jun, some natives) lost its "wins", and a guest's name
 * was cut where our mixer stops outside the fight. The frame on which the
 * game would move on (below, as 8003D27C..8003D3A4 decide it) is skipped
 * while the task waits or "wins" plays: the poses hold, for 150 frames at
 * most. 8002AE58, its caller, reads its result from memory, not from v0. */
enum { ROUND_END=0x80096f2c, ROUND_END_FRAMES=0x80096f30, ROUND_END_POSE=6, ROUND_KIND=0x8009546c,
       POSE_OVER=0x8009e5f8, HOLD_MAX=150 };
/* A fighter is done when down (actor+72 <= 0) or at the end of its pose
 * (frame actor+88 at its animation's length - 1), flags 0x8009E5F8 + 4 * p. */
static int pose_over(unsigned p) {
    uint32_t actor=0x800a9228+p*0x188c;
    return psx_mod_read_word(POSE_OVER+p*4) || (int16_t)psx_mod_read_half(actor+72)<=0 ||
           (int16_t)psx_mod_read_half(actor+88)>=(int)psx_mod_read_byte(psx_mod_read_word(actor+84)+24)-1;
}
/* Sub-state 6 ends after 75 frames (kind 2), after 60 (kinds 6 and 7, the
 * fight's last round; 240 in mode 7), or once both fighters are done (other
 * kinds but 5). The frame count is raised before the test. */
static int round_end_moves_on(void) {
    unsigned kind=psx_mod_read_word(ROUND_KIND),next=psx_mod_read_word(ROUND_END_FRAMES)+1;
    if(kind==2)return next==75;
    if(kind==6 || kind==7)return next==(psx_mod_read_word(0x800afa88)==7?240u:60u);
    return kind!=5 && pose_over(0) && pose_over(1);
}
void __wrap_func_8003CB84(CPUState *cpu) {
    static unsigned held;
    if(cpu->pc==0 || cpu->pc==0x8003cb84) {
        round_frames++;
        int waiting=wins_task && round_frames-wins_checked<=2;
        if(!waiting)wins_task=0;
        if(wins_left && !waiting)wins_left--;
        if(!waiting && !wins_left)held=0;
        else if(psx_mod_read_word(ROUND_END)==ROUND_END_POSE && round_end_moves_on() && held<HOLD_MAX) {
            held++;
            cpu->pc=cpu->gpr[31];return;
        }
    }
    __real_func_8003CB84(cpu);
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
    /* SURVIVAL RESULTS (state 14) announces the fighter: a guest's name. */
    if(!in_fight() && psx_mod_read_half(0x800ae204)!=14){tekken3_ttt1_sfx_stop();return;}
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
