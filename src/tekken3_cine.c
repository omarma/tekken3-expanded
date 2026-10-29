/* The cinematic engine: tekken3_cine_play() plays a .cine file
 * (docs/CINE-FORMAT.md) in a fight, on a frame loop of its own. It replaced
 * the old way, which played our cutscenes through Ogre's (the Arcade
 * overlay's phases 16 and 17, rewritten words, clips added to the .jmv
 * packs as fake moves; removed, TIPS.md section 130). The game's hooks it
 * draws and records through: src/tekken3_cine_hooks.c.
 *
 * The loop. While a cinematic plays, the fight's phase is held at 17 (so
 * every check made for Ogre's cutscene holds: no HUD, no fighting), but the
 * fight's frame function (0x80050428) never reaches its phase machine or the
 * overlay: the wrapper of its piece 0x80050450 runs one frame of ours
 * instead (a coroutine, see "Calling the game"), calling the game's
 * own routines as the overlay's 0x800B3CA0 (setup) and 0x800B4060 (a frame)
 * do, without their script: each actor's animation step (0x8003A818), the
 * camera (0x800670FC, its view built from our track by the wrapper of
 * 0x80063EEC), the arena, the actors, the effects, the fade.
 *
 * The poses. Each actor plays a record of the engine's own (guest memory,
 * never in a pack or the move graph): a copy of its stance record whose clip
 * is a sentinel. The game's decoder (0x80038B4C / 0x800389C0, wrapped in
 * src/tekken3_ttt1_combat.c) asks tekken3_cine_clip_pose() for a sentinel's
 * pose: the actor's track at the current frame, 57 TTT1 channels. So the
 * root goes through the game's own root motion and a native's bones through
 * its basis change (0x8003AD10, src/tekken3_ttt1_motion.c), as for a TTT1
 * move; the record's frame is held, its timed properties are the actor's
 * aura for this frame. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "tekken3_arcade_stages.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { ACTORS_MAX=8, PLAYED=2, MODELS_MAX=8, FADES_MAX=64, BONES_MAX=32, CHANNELS=57, HAND_STEPS=512 };
enum { SPARKS_MAX=64, SPRITES_MAX=16, SPRITE_POINTS_MAX=32, SWAPS_MAX=16, LOADS_MAX=2*(SWAPS_MAX+1), SHOWS_MAX=64, STORMS_MAX=64 };
enum { ACTOR0=0x800a9228, ACTOR_SIZE=0x188c, STATE=0x800ae204, PHASE=0x800ae224 };
typedef struct { int from,to,a,b; } Fade;
typedef struct { int frame,actor,bone,kind; } Spark;
/* A sprite block: k soft puffs a frame, each x y z (stage), radius, alpha (0: not drawn). */
typedef struct { int first,count,points; uint32_t colour; int32_t (*p)[5]; } Sprites;
typedef struct {
    char character[32]; int costume;
    int place[4];
    struct { int frame; char prefix[96]; } models[MODELS_MAX]; int model_count;
    char effect[512];
    int aura_from,aura_to,aura_step,aura_bones[BONES_MAX],aura_bone_count;
    int pose_first,pose_count; uint16_t (*poses)[CHANNELS];
    struct { int frame,index; } hands[2][HAND_STEPS]; int hand_count[2];
    /* `swap`: from each frame on, another character (segment i; -1 the actor's own). */
    struct { int frame; char character[32]; int costume; } swaps[SWAPS_MAX]; int swap_count;
    /* `hide` / `show`: from each frame on, drawn or not (shown before the first). */
    struct { int frame,shown; } shows[SHOWS_MAX]; int show_count;
    /* `eyes`: from each frame on, closed (1) or open (0); the game's own before the first. */
    struct { int frame,closed; } eyes[SHOWS_MAX]; int eye_count;
} Actor;
typedef struct {
    char name[32],dir[1024];
    int length,arena,dark,background;           /* background: -1 the arena's */
    int actor_count; Actor actors[ACTORS_MAX];
    int cam_first,cam_count; int16_t (*cam)[6];
    Fade fades[FADES_MAX]; int fade_count;
    Spark sparks[SPARKS_MAX]; int spark_count;
    Sprites sprites[SPRITES_MAX]; int sprite_count;
    char music[1024],music_fallback[1024]; int music_frame,music_fallback_frame;
    int light;                                  /* -1 none */
    int ttt_stage;                              /* a TTT arcade stage drawn instead, -1 none */
    int ttt_courtyard;                          /* its courtyard, |x|, |z| <= this (the floor), 0 no limit */
    struct { int frame,type; } storms[STORMS_MAX]; int storm_count;
} Cine;
static void storms(void);

static Cine *cine;                  /* the prepared or playing cinematic */
static int playing, tick, preroll;
extern int g_psx_gpu_allow_oversize;     /* psxrecomp/runtime/include/gpu_primitive_reject.h */
static int loaded[PLAYED];          /* the segment each played actor has in place (-1 its own character) */
static void (*done)(void);

static void cine_free(Cine *c) {
    if(!c) return;
    for(int i=0;i<ACTORS_MAX;i++) free(c->actors[i].poses);
    for(int i=0;i<c->sprite_count;i++) free(c->sprites[i].p);
    free(c->cam); free(c);
}

/* ---- The .cine file ---------------------------------------------------- */

static int words(char *line,char **w,int max) {
    char *hash=strchr(line,'#'); if(hash) *hash=0;
    int n=0;
    for(char *s=strtok(line," \t\r\n");s && n<max;s=strtok(NULL," \t\r\n")) w[n++]=s;
    return n;
}
static int num(const char *s) { return (int)strtol(s,NULL,0); }
static Actor *actor_of(Cine *c,const char *index) {
    int i=num(index);
    if(i<0 || i>=ACTORS_MAX) return NULL;
    if(i>=c->actor_count) c->actor_count=i+1;
    return &c->actors[i];
}
/* A block of n lines of `width` integers after its header line (as16: int16,
 * 0: uint16, 32: int32). */
static int block(FILE *f,int n,int width,void *out,int as16) {
    enum { WIDTH_MAX=5*SPRITE_POINTS_MAX };
    static char line[4*1024]; char *w[WIDTH_MAX+1];
    for(int k=0;k<n;k++) {
        if(!fgets(line,sizeof line,f) || words(line,w,WIDTH_MAX+1)!=width) return 0;
        for(int j=0;j<width;j++) {
            if(as16==32) ((int32_t*)out)[k*width+j]=num(w[j]);
            else if(as16) ((int16_t*)out)[k*width+j]=(int16_t)num(w[j]);
            else ((uint16_t*)out)[k*width+j]=(uint16_t)num(w[j]);
        }
    }
    return 1;
}
static Cine *cine_read(const char *path) {
    FILE *f=fopen(path,"r");
    if(!f) { fprintf(stderr,"Cine: no %s\n",path); return NULL; }
    Cine *c=calloc(1,sizeof *c);
    if(!c) { fclose(f); return NULL; }
    snprintf(c->dir,sizeof c->dir,"%s",path);
    char *slash=strrchr(c->dir,'/'),*back=strrchr(c->dir,'\\');
    if(back>slash) slash=back;
    if(slash) *slash=0; else snprintf(c->dir,sizeof c->dir,".");
    c->background=-1; c->light=-1; c->ttt_stage=-1;
    for(int i=0;i<ACTORS_MAX;i++) c->actors[i].place[3]=0x4000;
    char line[4096],*w[64]; int version=0,ok=1,lineno=0;
    while(ok && fgets(line,sizeof line,f)) {
        lineno++;
        int n=words(line,w,64);
        if(!n) continue;
        Actor *a;
        if(!strcmp(w[0],"cine") && n==2) version=num(w[1]);
        else if(!version) { fprintf(stderr,"Cine: %s does not start with \"cine 1\"\n",path); ok=0; }
        else if(!strcmp(w[0],"name") && n==2) snprintf(c->name,sizeof c->name,"%s",w[1]);
        else if(!strcmp(w[0],"length") && n==2) c->length=num(w[1]);
        else if(!strcmp(w[0],"arena") && n==2) c->arena=num(w[1]);
        else if(!strcmp(w[0],"dark") && n==2) c->dark=num(w[1]);
        else if(!strcmp(w[0],"background") && n==2) c->background=strcmp(w[1],"arena")?(int)strtol(w[1],NULL,16):-1;
        else if(!strcmp(w[0],"light") && n==2) c->light=(int)strtol(w[1],NULL,16);
        else if(!strcmp(w[0],"ttt-stage") && (n==2 || n==3)) { c->ttt_stage=num(w[1]); c->ttt_courtyard=n==3?num(w[2]):0; }
        else if(!strcmp(w[0],"storm") && (n==3 || (n==4 && !strcmp(w[3],"quiet"))) && c->storm_count<STORMS_MAX) {
            c->storms[c->storm_count].frame=num(w[1]);
            c->storms[c->storm_count++].type=num(w[2])|(n==4?TEKKEN3_TTT_FLASH_QUIET:0);
        }
        else if(!strcmp(w[0],"actor") && n==4 && (a=actor_of(c,w[1]))) {
            snprintf(a->character,sizeof a->character,"%s",w[2]); a->costume=num(w[3]);
        }
        else if(!strcmp(w[0],"place") && n==6 && (a=actor_of(c,w[1])))
            for(int k=0;k<4;k++) a->place[k]=num(w[2+k]);
        else if(!strcmp(w[0],"model") && n==4 && (a=actor_of(c,w[1])) && a->model_count<MODELS_MAX) {
            snprintf(a->models[a->model_count].prefix,sizeof a->models[0].prefix,"%s",w[2]);
            a->models[a->model_count++].frame=num(w[3]);
        }
        else if(!strcmp(w[0],"hand") && n==5 && (a=actor_of(c,w[1])) && num(w[2])>=0 && num(w[2])<2) {
            int h=num(w[2]);
            if(a->hand_count[h]<HAND_STEPS) {
                a->hands[h][a->hand_count[h]].frame=num(w[3]); a->hands[h][a->hand_count[h]++].index=num(w[4]);
            }
        }
        else if(!strcmp(w[0],"swap") && n==5 && (a=actor_of(c,w[1]))) {
            int frame=num(w[4]);
            if(a->swap_count==SWAPS_MAX || (a->swap_count && frame<=a->swaps[a->swap_count-1].frame)) ok=0;
            else {
                snprintf(a->swaps[a->swap_count].character,sizeof a->swaps[0].character,"%s",w[2]);
                a->swaps[a->swap_count].costume=num(w[3]); a->swaps[a->swap_count++].frame=frame;
            }
        }
        else if((!strcmp(w[0],"hide") || !strcmp(w[0],"show")) && n==3 && (a=actor_of(c,w[1]))) {
            int frame=num(w[2]);
            if(a->show_count==SHOWS_MAX || (a->show_count && frame<a->shows[a->show_count-1].frame)) ok=0;
            else { a->shows[a->show_count].frame=frame; a->shows[a->show_count++].shown=w[0][0]=='s'; }
        }
        else if(!strcmp(w[0],"eyes") && n==4 && (a=actor_of(c,w[1]))) {
            int frame=num(w[2]);
            if(a->eye_count==SHOWS_MAX || (a->eye_count && frame<a->eyes[a->eye_count-1].frame)) ok=0;
            else { a->eyes[a->eye_count].frame=frame; a->eyes[a->eye_count++].closed=num(w[3])!=0; }
        }
        else if(!strcmp(w[0],"effect") && n==3 && (a=actor_of(c,w[1])))
            snprintf(a->effect,sizeof a->effect,"%s/%s",c->dir,w[2]);
        else if(!strcmp(w[0],"aura") && n>=6 && (a=actor_of(c,w[1]))) {
            a->aura_from=num(w[2]); a->aura_to=num(w[3]); a->aura_step=num(w[4])>0?num(w[4]):1;
            for(int k=5;k<n && a->aura_bone_count<BONES_MAX;k++) a->aura_bones[a->aura_bone_count++]=num(w[k]);
        }
        else if(!strcmp(w[0],"fade") && n==5 && c->fade_count<FADES_MAX)
            c->fades[c->fade_count++]=(Fade){num(w[1]),num(w[2]),num(w[3]),num(w[4])};
        else if(!strcmp(w[0],"music") && n==3) {
            snprintf(c->music,sizeof c->music,"%s/%s",c->dir,w[1]); c->music_frame=num(w[2]);
        }
        else if(!strcmp(w[0],"music-fallback") && n==3) {
            snprintf(c->music_fallback,sizeof c->music_fallback,"%s/%s",c->dir,w[1]); c->music_fallback_frame=num(w[2]);
        }
        else if(!strcmp(w[0],"camera") && n==3) {
            c->cam_first=num(w[1]); c->cam_count=num(w[2]);
            free(c->cam);
            ok=c->cam_count>0 && (c->cam=malloc(sizeof *c->cam*(size_t)c->cam_count)) && block(f,c->cam_count,6,c->cam,1);
        }
        else if(!strcmp(w[0],"poses") && n==4 && (a=actor_of(c,w[1]))) {
            /* Blocks follow one another: the first block's start, grown. */
            int first=num(w[2]),count=num(w[3]);
            if(!a->pose_count) a->pose_first=first;
            int at=first-a->pose_first;
            void *m=count>0 && at>=a->pose_count?realloc(a->poses,sizeof *a->poses*(size_t)(at+count)):NULL;
            ok=m!=NULL;
            if(ok) {
                a->poses=m;
                for(int k=a->pose_count;k<at;k++) memcpy(a->poses[k],a->poses[a->pose_count-1],sizeof *a->poses);
                ok=block(f,count,CHANNELS,a->poses[at],0);
                a->pose_count=at+count;
            }
        }
        else if(!strcmp(w[0],"spark") && n==5 && c->spark_count<SPARKS_MAX) {
            Spark *s=&c->sparks[c->spark_count++];
            s->frame=num(w[1]); s->actor=num(w[2]); s->bone=num(w[3]); s->kind=num(w[4]);
        }
        else if(!strcmp(w[0],"sprite") && n==5 && c->sprite_count<SPRITES_MAX) {
            Sprites *s=&c->sprites[c->sprite_count];
            s->first=num(w[1]); s->count=num(w[2]); s->points=num(w[3]); s->colour=(uint32_t)strtoul(w[4],NULL,16);
            ok=s->count>0 && s->points>0 && s->points<=SPRITE_POINTS_MAX
               && (s->p=malloc(sizeof *s->p*(size_t)s->count*(size_t)s->points))
               && block(f,s->count,5*s->points,s->p,32);
            if(ok) c->sprite_count++;
            else { free(s->p); s->p=NULL; }
        }
        else if(!strcmp(w[0],"sound") || !strcmp(w[0],"devil")) {}
                                                         /* reserved: not played by version 1 */
        else fprintf(stderr,"Cine: %s line %d: \"%s\" ignored\n",path,lineno,w[0]);
        if(!ok) fprintf(stderr,"Cine: %s line %d: bad \"%s\"\n",path,lineno,w[0]);
    }
    fclose(f);
    if(ok && (version!=1 || c->length<=0 || c->actor_count<1)) {
        fprintf(stderr,"Cine: %s: version %d, %d frames, %d actors: not playable\n",path,version,c->length,c->actor_count);
        ok=0;
    }
    if(!ok) { cine_free(c); return NULL; }
    fprintf(stderr,"Cine: %s \"%s\", %d frames, %d actors, camera %d frames, %d fades, %d sparks, %d sprite blocks, %d character changes\n",
            path,c->name,c->length,c->actor_count,c->cam_count,c->fade_count,c->spark_count,c->sprite_count,
            c->actors[0].swap_count+c->actors[1].swap_count);
    if(c->actor_count>PLAYED)
        fprintf(stderr,"Cine: actors %d and after are not drawn yet (two players only)\n",PLAYED);
    return c;
}

/* ---- What the rest of the game asks ----------------------------------- */

/* The frame of the cinematic, -1 before its first (the pre-roll) or when
 * none plays: the frame its tracks, model steps and fades are read at. */
int tekken3_cine_engine_frame(void) {
    if(!playing || tick<2) return -1;
    int f=tick-2-preroll;
    return f<0?-1:f;
}
int tekken3_cine_engine_active(void) { return playing; }
static int line;                    /* where the coroutine goes on, 0 to start (see "Calling the game") */
/* Its first tick still running: the characters of the `swap`s read ahead
 * (src/tekken3_cine_scene.c keeps the screen black meanwhile). */
int tekken3_cine_preloading(void) { return playing && tick==0 && line; }
static int frame_or_zero(void) { int f=tekken3_cine_engine_frame(); return f<0?0:f; }

/* Model files a player is drawn with (a prefix under the TTT1 catalogue),
 * NULL for its own; from the cinematic's preparation on, so that a player
 * reloaded for it loads the first ones already. */
extern int tekken3_cine_pending(void);
const char *tekken3_cine_model(unsigned player,int *known) {
    *known=cine && (playing || tekken3_cine_pending()) && player<PLAYED && player<(unsigned)cine->actor_count && cine->actors[player].model_count;
    if(!*known) return NULL;
    const Actor *a=&cine->actors[player];
    int f=frame_or_zero();
    /* The steps of the character in place only (`swap`: each segment its
     * own), from the frame it came in to the next change. */
    int s=playing?loaded[player]:-1;
    int from=s<0?-0x7fffffff:a->swaps[s].frame,to=s+1<a->swap_count?a->swaps[s+1].frame:0x7fffffff;
    /* Before its first step the actor already has the first model files:
     * only textures change during the cinematic, and the geometry it is
     * loaded with must match them. */
    const char *out=NULL;
    for(int i=0;i<a->model_count;i++)
        if(a->models[i].frame>=from && a->models[i].frame<to && (!out || f>=a->models[i].frame)) out=a->models[i].prefix;
    if(!out) *known=0;
    return out;
}
/* A player's hand level (0 open .. 3 fist; the pose of the model's own table nearest
 * to it is shown, tekken3_ttt1_mod.c hand_pose) at this frame,
 * from its "hand" steps (the first one held before it), -1 for the game's own. */
int tekken3_cine_hand(unsigned player,unsigned hand) {
    if(!playing || player>=PLAYED || player>=(unsigned)cine->actor_count || hand>1) return -1;
    const Actor *a=&cine->actors[player];
    if(!a->hand_count[hand]) return -1;
    int f=frame_or_zero(),out=a->hands[hand][0].index;
    for(int i=0;i<a->hand_count[hand] && a->hands[hand][i].frame<=f;i++) out=a->hands[hand][i].index;
    return out;
}
/* A player's eyes at this frame (`eyes`): 1 closed, 0 open, -1 the game's own
 * (its blinking; before the first step), for the guests' faces
 * (src/tekken3_ttt1_mod.c, tekken3_ttt1_face_tick). */
int tekken3_cine_eyes(unsigned player) {
    if(!playing || player>=PLAYED || player>=(unsigned)cine->actor_count) return -1;
    const Actor *a=&cine->actors[player];
    int f=frame_or_zero(),out=-1;
    for(int i=0;i<a->eye_count && a->eyes[i].frame<=f;i++) out=a->eyes[i].closed;
    return out;
}
/* A player's lightning pack and the strong-hit light while it plays. */
const char *tekken3_cine_effect(unsigned player) {
    if(!playing || player>=PLAYED || player>=(unsigned)cine->actor_count) return NULL;
    return cine->actors[player].effect[0]?cine->actors[player].effect:"";
}
int tekken3_cine_light(void) { return playing?cine->light:-2; }

/* The camera at this frame, held before its first and after its last. */
int tekken3_cine_camera(int16_t eye[3],int16_t target[3]) {
    int f=tekken3_cine_engine_frame();
    if(!playing || !cine->cam_count || f<0) return 0;     /* the pre-roll keeps the game's camera */
    int i=f-cine->cam_first;
    if(i<0) i=0;
    if(i>=cine->cam_count) i=cine->cam_count-1;
    for(int k=0;k<3;k++) { eye[k]=cine->cam[i][k]; target[k]=cine->cam[i][3+k]; }
    return 1;
}

/* The fade level at a frame (-256 black, 0 none, 256 white); the pre-roll is black. */
static int fade_level(int *on) {
    int f=tekken3_cine_engine_frame();
    *on=1;
    if(f<0) return -256;
    for(int i=0;i<cine->fade_count;i++) {
        const Fade *d=&cine->fades[i];
        if(f<d->from || f>d->to) continue;
        int level=d->to>d->from?d->a+(d->b-d->a)*(f-d->from)/(d->to-d->from):d->b;
        return level<-256?-256:level>256?256:level;
    }
    *on=0;
    return 0;
}

/* The music: raw 16-bit stereo PCM at 44 100 Hz from its frame, the game's
 * own muted for the whole cinematic, dimmed by fades to black. Returns
 * whether the engine answers (then *mute: mute the game's music). */
static int16_t *music; static uint32_t music_frames,music_pos; static int music_from=-2;
int tekken3_cine_music_mix(int16_t *out,int frames,int audible,int gain,int *mute) {
    if(!playing) { music_pos=0; return 0; }
    if(music_from==-2) {
        music_from=-1;
        const char *paths[2]={cine->music,cine->music_fallback}; int at[2]={cine->music_frame,cine->music_fallback_frame};
        for(int k=0;k<2 && music_from<0;k++) {
            FILE *f=paths[k][0]?fopen(paths[k],"rb"):NULL;
            if(!f) continue;
            fseek(f,0,SEEK_END); long size=ftell(f); fseek(f,0,SEEK_SET);
            free(music); music=malloc((size_t)size);
            if(music && fread(music,1,(size_t)size,f)==(size_t)size) { music_frames=(uint32_t)(size/4); music_from=at[k]; }
            fclose(f);
            fprintf(stderr,"Cine: music %s, %u frames from frame %d\n",paths[k],music_frames,music_from);
        }
    }
    *mute=1;
    int f=tekken3_cine_engine_frame();
    if(music_from<0 || f<music_from || music_pos>=music_frames) return 1;
    int on,level=fade_level(&on);
    int scale=gain*(level<0?level+256:256)/256;
    for(int i=0;i<frames && music_pos<music_frames;i++,music_pos++)
        for(int ch=0;ch<2;ch++) {
            int32_t v=audible?music[music_pos*2+ch]*scale/200:0, mixed=out[i*2+ch]+v;
            out[i*2+ch]=(int16_t)(mixed>32767?32767:mixed<-32768?-32768:mixed);
        }
    return 1;
}

/* ---- Poses through the game's own decoder ------------------------------ */

/* Per played actor: the sentinel clip, the record it plays (a copy of its
 * stance with that clip), its aura's timed properties, and what it played
 * before (put back at the end). */
static uint32_t sentinel[PLAYED],record[PLAYED],props[PLAYED],saved_record[PLAYED][2];
enum { HELD=2, PROPS_MAX=4 };       /* the record's frame window: 1 -> 2 every frame */

const uint16_t *tekken3_cine_clip_pose(uint32_t clip) {
    if(!playing || !clip) return NULL;
    for(unsigned p=0;p<PLAYED;p++) {
        if(clip!=sentinel[p]) continue;
        const Actor *a=&cine->actors[p];
        if(!a->pose_count) return NULL;
        int i=frame_or_zero()-a->pose_first;
        if(i<0) i=0;
        if(i>=a->pose_count) i=a->pose_count-1;
        return a->poses[i];
    }
    return NULL;
}

/* This frame's strong-hit effects on the actor (timed properties fired by
 * 0x800458C8 between the record's frames 1 and 2, at actor + 0x908 + 68 ·
 * bone): the aura's lightning, and the sparks (measured in the engine: 7
 * gives the actor its own effect, 6 the other one's: Kunimitsu's yellow and
 * Yoshimitsu's green were crossed with 6 for the own one). */
static void aura(unsigned p) {
    const Actor *a=&cine->actors[p];
    int f=tekken3_cine_engine_frame(),n=0;
    if(a->aura_bone_count && f>=a->aura_from && f<=a->aura_to && !((f-a->aura_from)%a->aura_step)) {
        int bone=a->aura_bones[(f-a->aura_from)/a->aura_step%a->aura_bone_count];
        psx_mod_write_half(props[p],HELD); psx_mod_write_half(props[p]+2,(uint16_t)(6<<8|(bone&255)));
        n=1;
    }
    for(int i=0;i<cine->spark_count && n<PROPS_MAX-1;i++) {
        const Spark *s=&cine->sparks[i];
        if(s->frame!=f || s->actor!=(int)p) continue;
        psx_mod_write_half(props[p]+n*4,HELD);
        psx_mod_write_half(props[p]+n*4+2,(uint16_t)((s->kind==(int)p?7:6)<<8|(s->bone&255)));
        n++;
    }
    psx_mod_write_word(props[p]+n*4,0);
}

/* A cut of the camera: the track's jump into this frame, 256 or more and
 * over 4 times the moves around it (the cuts of the seven TTT scenes, none
 * of their pans: Armor King's camera sweeps 399 a frame, his smallest cut is
 * 548). */
static int cam_jump(int i) {
    if(i<=0 || i>=cine->cam_count) return 0;
    int m=0;
    for(int k=0;k<6;k++) { int d=abs(cine->cam[i][k]-cine->cam[i-1][k]); if(d>m) m=d; }
    return m;
}
static int cut_at(int f) {
    int i=f-cine->cam_first,j=cam_jump(i),before=cam_jump(i-1),after=cam_jump(i+1);
    return j>=256 && j>4*(before>after?before:after);
}
/* A strong-hit effect never outlives a cut: the ones still running are put
 * out before the frame's properties fire (a spark on the cut starts in the
 * new shot), as the game ends one (0x80076E70: +2, its image, back to 0; the
 * three at 0x800A3408), and their light with them (its timer 0x8009E5EC at
 * 1: 0x80039F84 turns it off at the frame's end; only with a spark put out:
 * the storm's lightning lights it too, and goes on across the Embu's cuts at
 * 489, 621 and 1169). Paul's spark on Hwoarang (Embu, 1834) stayed on in
 * Jun's shot from 1849; the PS2 has none. Not while an aura plays: Kazuya's
 * lightning goes on across his ending's cuts. */
enum { EFFECTS=0x800a3408, EFFECT_SIZE=0x40, EFFECT_COUNT=3, LIGHT_TIMER=0x8009e5ec };
static int cut_last=-1;
static void cuts(void) {
    int f=tekken3_cine_engine_frame(),n=0;
    if(f<0 || f==cut_last) return;
    cut_last=f;
    if(!cut_at(f)) return;
    for(unsigned p=0;p<PLAYED && p<(unsigned)cine->actor_count;p++) {
        const Actor *a=&cine->actors[p];
        if(a->aura_bone_count && f>=a->aura_from && f<=a->aura_to) return;
    }
    for(uint32_t k=0;k<EFFECT_COUNT;k++)
        if((int16_t)psx_mod_read_half(EFFECTS+k*EFFECT_SIZE+2)>0) { psx_mod_write_half(EFFECTS+k*EFFECT_SIZE+2,0); n++; }
    if(!n) return;
    if((int32_t)psx_mod_read_word(LIGHT_TIMER)>1) psx_mod_write_word(LIGHT_TIMER,1);
    fprintf(stderr,"Cine: cut at %d, %d hit effect(s) put out\n",f,n);
}

/* ---- Calling the game ---------------------------------------------------- */

/* The engine never runs the game's code from C (psx_dispatch_call from a
 * wrapper is not something to build on): it is a coroutine in the fight's
 * frame function 0x80050428, at 0x80050450, the piece after its first call
 * (0x8005101C, non-zero while the game is paused) where the phase machine
 * starts. A call sets the arguments and jumps to the function with
 * 0x80050450 as its return address: the dispatcher brings its return back
 * into the wrapper, which goes on where it stopped, v0 in hand. The frame
 * ends at the function's own epilogue (0x80050EC0, its saved registers and
 * return). FRAME bytes below the stack pointer hold a fifth argument
 * (sp + 16) and some scratch (sp + SCRATCH). */
enum { ENTRY=0x80050450, EPILOGUE=0x80050ec0, FRAME=64, SCRATCH=32 };
static int tracing(void) {
    static int t=-1;
    if(t<0) t=getenv("TEKKEN3_CINE_TRACE")!=NULL;
    return t;
}
static void issue(CPUState *cpu,uint32_t fn,int argc,const uint32_t *args) {
    if(tracing()) { fprintf(stderr,"Cine: tick %d calls %08X sp %08X\n",tick,fn,cpu->gpr[29]); fflush(stderr); }
    for(int i=0;i<argc && i<4;i++) cpu->gpr[4+i]=args[i];
    if(argc>4) psx_mod_write_word(cpu->gpr[29]+16,args[4]);
    cpu->gpr[31]=ENTRY; cpu->pc=fn;
}
/* One call a line: the line is its resume point. */
#define CALL(fn,...) do { const uint32_t args_[]={__VA_ARGS__}; \
    issue(cpu,(fn),(int)(sizeof args_/sizeof *args_),args_); line=__LINE__; return 0; case __LINE__:; } while(0)
#define CALL0(fn) do { issue(cpu,(fn),0,NULL); line=__LINE__; return 0; case __LINE__:; } while(0)
#define H(a) ((uint32_t)(int32_t)(int16_t)psx_mod_read_half(a))

/* ---- The loop ------------------------------------------------------------ */

void tekken3_cine_floor_before(void);                          /* src/tekken3_cine_floor.c */
void tekken3_cine_floor_after(CPUState *cpu,uint32_t p1,uint32_t p2);

static uint32_t tiles;          /* the black tile at the display list's far end, one per buffer */
static uint32_t ot(void) { return psx_mod_read_word(psx_mod_read_word(0x800a8c54)+4); }
static void far_tile(void) {
    if(psx_mod_read_word(0x800adca4)) return;          /* a dark arena links its own (0x80048374) */
    uint32_t t=tiles+16*(psx_mod_read_word(0x800adefc)&1);
    psx_mod_write_word(t+4,0x60000000u); psx_mod_write_word(t+8,0); psx_mod_write_word(t+12,0x01e00170u);
    uint32_t at=ot()+0xffc;
    /* Never twice in the list (a loop the GPU would walk for ever). */
    uint32_t n=at;
    for(unsigned k=0;k<16384 && (n&0x00ffffffu)!=0x00ffffffu;k++) {
        if((n&0x00ffffffu)==(t&0x00ffffffu)) {
            static int told;
            if(!told++) fprintf(stderr,"Cine: the far tile was linked already (tick %d)\n",tick);
            return;
        }
        n=0x80000000u|(psx_mod_read_word(0x80000000u|(n&0x00ffffffu))&0x00ffffffu);
    }
    psx_mod_write_word(t,(psx_mod_read_word(at)&0x00ffffffu)|0x03000000u);
    psx_mod_write_word(at,(psx_mod_read_word(at)&0xff000000u)|(t&0x00ffffffu));
}

/* ---- Sprites ------------------------------------------------------------- */

/* Each `sprite` point of this frame, a soft round puff facing the camera: a
 * fan of Gouraud-shaded additive polygons (no texture: the colour falls from
 * the centre to black at the rim, the soft disc of TTT's effect texture),
 * radius in stage units divided by the depth. Projected through the view
 * (rotation in the GTE as the floor left it, translation 0x800ADF70 + 0x14:
 * camera = R · p + T), linked near the front of the display list (one packet
 * a puff: E1 additive, then its polygons). */
enum { WORLD_VIEW=0x800adf70, NEAR_PX=120, PUFFS_MAX=64, SEGMENTS=10, PUFF_WORDS=1+SEGMENTS*6+2*SEGMENTS*8 };
static uint32_t puffs;              /* PUFFS_MAX packets per buffer */
static void sprites(CPUState *cpu) {
    int f=tekken3_cine_engine_frame();
    if(getenv("TEKKEN3_CINE_GTE") && f>=0 && !(f%60))   /* the projection, against the PS2's focal */
        fprintf(stderr,"Cine: frame %d, GTE H %u, OFX %d, OFY %d\n",f,cpu->gte_ctrl[26]&0xffff,(int32_t)cpu->gte_ctrl[24]>>16,(int32_t)cpu->gte_ctrl[25]>>16);
    if(f<0 || !cine->sprite_count) return;
    if(!puffs && !(puffs=psx_mod_alloc_gpu_dma_memory(2*PUFFS_MAX*4*(1+PUFF_WORDS),16))) {
        static int told;
        if(!told++) fprintf(stderr,"Cine: no GPU-DMA memory left for the sprites' puffs, they are not drawn\n");
        return;
    }
    /* The view's rotation from the world-view matrix, as its translation: the
     * GTE's no longer holds it here (an Arcade or TTT stage's floor, drawn
     * just before, leaves its own; the puffs were thousands of units off). */
    const uint32_t *c=cpu->gte_ctrl;
    double r[9],t[3],h=(double)(c[26]&0xffff),ofx=(int32_t)c[24]/65536.0,ofy=(int32_t)c[25]/65536.0;
    for(int i=0;i<9;i++) r[i]=(int16_t)psx_mod_read_half(WORLD_VIEW+2*(uint32_t)i);
    for(int i=0;i<3;i++) t[i]=(int32_t)psx_mod_read_word(WORLD_VIEW+0x14+4*(uint32_t)i);
    uint32_t base=puffs+(psx_mod_read_word(0x800adefc)&1)*PUFFS_MAX*4*(1+PUFF_WORDS),slot=ot()+4;
    static const double ring[3]={0.35,0.7,1.0},shade[4]={1.0,0.8,0.4,0.0};   /* the texture's falloff */
    int drawn=0;
    #define XY(x,y) ((((uint32_t)(int32_t)lround(y))&0xffffu)<<16|(((uint32_t)(int32_t)lround(x))&0xffffu))
    for(int b=0;b<cine->sprite_count;b++) {
        const Sprites *s=&cine->sprites[b];
        int row=f-s->first;
        if(row<0 || row>=s->count) continue;
        for(int k=0;k<s->points && drawn<PUFFS_MAX;k++) {
            const int32_t *q=s->p[row*s->points+k];
            if(q[4]<=0) continue;
            double v[3];
            for(int i=0;i<3;i++) v[i]=(r[3*i]*q[0]+r[3*i+1]*q[1]+r[3*i+2]*q[2])/4096.0+t[i];
            if(v[2]<64) continue;                               /* at or behind the camera */
            double sx=ofx+h*v[0]/v[2],sy=ofy+h*v[1]/v[2],rad=h*q[3]/v[2];
            /* A puff at the camera grows past what a PS1 polygon may span (1023
             * x 511: the GPU drops the bigger ones, a sharp arc was left):
             * faded out from NEAR_PX of radius, gone at twice that. */
            if(rad<1 || rad>=2*NEAR_PX || sx+rad<-512 || sx-rad>880 || sy+rad<0 || sy-rad>480) continue;
            double near=rad>NEAR_PX?(2*NEAR_PX-rad)/NEAR_PX:1.0;
            uint32_t col[4];
            for(int j=0;j<4;j++) {
                uint32_t rgb=0;
                for(int ch=0;ch<3;ch++) {
                    double x=((s->colour>>(8*(2-ch)))&255)*(q[4]>256?256:q[4])/256.0*shade[j]*near;
                    rgb|=(uint32_t)lround(x)<<(8*ch);                 /* BGR */
                }
                col[j]=rgb;
            }
            uint32_t pkt=base+(uint32_t)drawn*4*(1+PUFF_WORDS),o=pkt+4;
            psx_mod_write_word(o,0xE1000000u|1u<<5|1u<<9|1u<<10); o+=4;       /* additive */
            double px[3][SEGMENTS],py[3][SEGMENTS];
            for(int j=0;j<3;j++)
                for(int a=0;a<SEGMENTS;a++) {
                    double ang=a*2*3.141592653589793/SEGMENTS;
                    px[j][a]=sx+cos(ang)*rad*ring[j]; py[j][a]=sy+sin(ang)*rad*ring[j];
                }
            for(int a=0;a<SEGMENTS;a++) {
                int n=(a+1)%SEGMENTS;
                psx_mod_write_word(o,0x32000000u|col[0]); psx_mod_write_word(o+4,XY(sx,sy));
                psx_mod_write_word(o+8,col[1]);           psx_mod_write_word(o+12,XY(px[0][a],py[0][a]));
                psx_mod_write_word(o+16,col[1]);          psx_mod_write_word(o+20,XY(px[0][n],py[0][n]));
                o+=24;
                for(int j=0;j<2;j++) {
                    psx_mod_write_word(o,0x3A000000u|col[j+1]); psx_mod_write_word(o+4,XY(px[j][a],py[j][a]));
                    psx_mod_write_word(o+8,col[j+1]);           psx_mod_write_word(o+12,XY(px[j][n],py[j][n]));
                    psx_mod_write_word(o+16,col[j+2]);          psx_mod_write_word(o+20,XY(px[j+1][a],py[j+1][a]));
                    psx_mod_write_word(o+24,col[j+2]);          psx_mod_write_word(o+28,XY(px[j+1][n],py[j+1][n]));
                    o+=32;
                }
            }
            uint32_t words=(o-pkt-4)/4;
            psx_mod_write_word(pkt,(psx_mod_read_word(slot)&0xffffffu)|words<<24);
            psx_mod_write_word(slot,(psx_mod_read_word(slot)&0xff000000u)|(pkt&0xffffffu));
            drawn++;
        }
    }
    #undef XY
}

/* The engine's records: each actor's stance (its record when the cinematic
 * starts) copied, with the sentinel clip, no sounds, the aura's properties
 * and a length the held frame never reaches. Put on the actor every frame. */
static int records(void) {
    if(!sentinel[0]) {
        uint32_t m=psx_mod_alloc_guest_memory(PLAYED*(16+56+PROPS_MAX*4),16);
        if(!m) return 0;
        for(unsigned p=0;p<PLAYED;p++) {
            sentinel[p]=m+p*16; record[p]=m+PLAYED*16+p*56; props[p]=m+PLAYED*(16+56)+p*PROPS_MAX*4;
            psx_mod_write_word(sentinel[p],0x454e4943u);            /* "CINE" */
            psx_mod_write_word(sentinel[p]+4,p);
        }
    }
    for(unsigned p=0;p<PLAYED;p++) {
        uint32_t x=ACTOR0+p*ACTOR_SIZE,stance=psx_mod_read_word(x+0x54);
        saved_record[p][0]=stance; saved_record[p][1]=psx_mod_read_word(x+0x4c);
        if(stance<0x80010000u) return 0;
        for(unsigned k=0;k<56;k+=4) psx_mod_write_word(record[p]+k,psx_mod_read_word(stance+k));
        psx_mod_write_word(record[p],sentinel[p]);
        psx_mod_write_word(record[p]+24,(psx_mod_read_word(record[p]+24)&0xffffff00u)|0xff);
        psx_mod_write_word(record[p]+28,0);                          /* no sounds */
        psx_mod_write_word(record[p]+32,props[p]);
        psx_mod_write_word(props[p],0);
    }
    return 1;
}
/* An actor on its engine record for this frame. A guest's stance is ready
 * only once its moves are in the guests' pool: copied again while the
 * pre-roll lasts. */
static void hold(unsigned p) {
    uint32_t x=ACTOR0+p*ACTOR_SIZE;
    if(tekken3_cine_engine_frame()<0 && psx_mod_read_word(x+0x54)!=record[p]) {
        uint32_t stance=psx_mod_read_word(x+0x54);
        for(unsigned k=4;k<56;k+=4) if(k!=24 && k!=28 && k!=32) psx_mod_write_word(record[p]+k,psx_mod_read_word(stance+k));
        saved_record[p][0]=stance; saved_record[p][1]=psx_mod_read_word(x+0x4c);
    }
    psx_mod_write_word(x+0x54,record[p]); psx_mod_write_word(x+0x4c,record[p]);
    psx_mod_write_half(x+0x5a,HELD-1); psx_mod_write_half(x+0x58,HELD); psx_mod_write_half(x+0x50,HELD);
    aura(p);
}

/* The fill tiles the arena's background is drawn with keep the colour of the
 * fight that loaded them: the cinematic's own. */
static void background(void) {
    /* Version 1 loads no arena: in another one than the cinematic's (a
     * test in any fight), that arena's own colour. */
    int arena=psx_mod_read_byte(0x800adc84);
    if(arena!=cine->arena) {
        static int told;
        if(!told++) fprintf(stderr,"Cine: played in arena %d, not its own %d\n",arena,cine->arena);
    }
    int colour=cine->background;
    if(colour<0) colour=cine->dark || arena>=14?0:(int)(psx_mod_read_word(0x80097a64+(uint32_t)arena*4)&0x00ffffffu);
    for(unsigned i=0;i<4;i++) psx_mod_write_word(0x8009e73cu+i*16,0x60000000u|(uint32_t)colour);
    psx_mod_write_byte(0x800afaa0,(uint8_t)cine->dark);
}

/* ---- The floor's grid --------------------------------------------------- */

/* The arena's floor is a grid of 10 x 10 big tiles (1 800 units in Gon's
 * arena) around the midpoint of the two fighters (0x80048E58: actor +0xF68
 * and +0xF70, x and z), enough in a fight, where they stay close. In a
 * cinematic one may walk far away (Angel's ending, from ~1000: Angel leaves
 * Kazuya lying): the grid follows the midpoint, and whole tiles go missing
 * round the one the camera looks at. When the fighters are more than APART
 * from each other, the floor is drawn around the one nearer to where the
 * camera looks at the floor (its line of sight met with y 0; the track's
 * target is only a point 2 000 units ahead of the eye): both are put at its
 * place for the floor's call (the arena drawing, 0x80048240, after the
 * actors), then back. Fighters near each other keep the game's own grid:
 * centred on the point looked at, a camera at the floor's level (the Embu's
 * Eddy) sent it thousands of units away. */
enum { FLOOR_X=0xf68, FLOOR_Z=0xf70, APART=6000, TTT_AHEAD=8000 };
extern int tekken3_cine_camera(int16_t eye[3],int16_t target[3]);
static int stage_forced;
/* A TTT stage's floor (`ttt-stage`, 15 x 15 cells of 1 300 on stage 4): the
 * Embu's camera, up to ~6 000 from Jin looking away, saw the grid's edge at
 * the foot of the stairs and the balustrades (frames 630-720, 1340-1380: the
 * user). Centred on where the line of sight meets the floor, TTT_AHEAD at
 * most ahead of the eye along the floor (the Eddy shots look level), with
 * its 8 neighbours, kept within `ttt-stage`'s courtyard (stage 4: 12 350,
 * the cell edge past the balustrades' feet; 10 000 and 11 050 left bands,
 * the user's picture at 726). */
static void ttt_floor_centre(int on) {
    int16_t eye[3],target[3];
    if(!on || !stage_forced || !tekken3_cine_camera(eye,target)) { tekken3_ttt_floor_centre(0,0,0,0); return; }
    double d[3]={target[0]-eye[0],target[1]-eye[1],target[2]-eye[2]};
    double h=sqrt(d[0]*d[0]+d[2]*d[2]);
    if(h<1) { tekken3_ttt_floor_centre(1,eye[0],eye[2],cine->ttt_courtyard); return; }
    double ahead=d[1]>0 && eye[1]<0?-eye[1]/d[1]*h:TTT_AHEAD;
    if(ahead>TTT_AHEAD) ahead=TTT_AHEAD;
    tekken3_ttt_floor_centre(1,(int)(eye[0]+d[0]/h*ahead),(int)(eye[2]+d[2]/h*ahead),cine->ttt_courtyard);
}
static void floor_centre(int on) {
    static int moved; static uint32_t kept[2][2];
    ttt_floor_centre(on);
    if(!on) {
        if(moved) for(unsigned p=0;p<2;p++) {
            psx_mod_write_word(ACTOR0+p*ACTOR_SIZE+FLOOR_X,kept[p][0]); psx_mod_write_word(ACTOR0+p*ACTOR_SIZE+FLOOR_Z,kept[p][1]);
        }
        moved=0;
        return;
    }
    int16_t eye[3],target[3];
    if(!tekken3_cine_camera(eye,target)) return;
    double px[2],pz[2];
    for(unsigned p=0;p<2;p++) {
        kept[p][0]=psx_mod_read_word(ACTOR0+p*ACTOR_SIZE+FLOOR_X); kept[p][1]=psx_mod_read_word(ACTOR0+p*ACTOR_SIZE+FLOOR_Z);
        px[p]=(int32_t)kept[p][0]; pz[p]=(int32_t)kept[p][1];
    }
    if((px[0]-px[1])*(px[0]-px[1])+(pz[0]-pz[1])*(pz[0]-pz[1])<(double)APART*APART) return;
    /* y grows downwards: a line of sight towards the floor has its y growing;
     * one that never meets it looks along its horizontal direction. */
    double d[3]={target[0]-eye[0],target[1]-eye[1],target[2]-eye[2]};
    double t=d[1]>0?-eye[1]/d[1]:1.0;
    if(t<0) t=1.0;
    double x=eye[0]+t*d[0],z=eye[2]+t*d[2];
    unsigned near=(x-px[1])*(x-px[1])+(z-pz[1])*(z-pz[1])<(x-px[0])*(x-px[0])+(z-pz[0])*(z-pz[0]);
    for(unsigned p=0;p<2;p++) {
        psx_mod_write_word(ACTOR0+p*ACTOR_SIZE+FLOOR_X,kept[near][0]);
        psx_mod_write_word(ACTOR0+p*ACTOR_SIZE+FLOOR_Z,kept[near][1]);
    }
    moved=1;
}

/* ---- Character changes (`swap`) ----------------------------------------- */

/* An actor changes character by the game's own fighter loading, done for one
 * actor as the fight's 0x8002A40C does it for both: the fields (0x8004F274),
 * the move key (0x8002D1DC) and the move table (0x80069AA8), the files wanted
 * (0x8006C618), the moves (0x80069F74, 0x8006A158), the load (0x80036310:
 * files, textures and palettes in the side's VRAM band, hit-effect pack,
 * sound bank), the model (0x80035CE0, 0x80035CE8), the files marked loaded
 * (0x8006C63C), then the actor's setup as the cinematic's own (0x8003C258,
 * 0x8002BD78), its placement kept. Its
 * files come from src/tekken3_cine_swap.c: read once in the pre-roll (each
 * character the cinematic changes to, then the actor's own again), served at
 * once at the change, which then takes a single frame. */
extern int tekken3_guest_id(const char *key);
extern int tekken3_t3_key_id(const char *key);
extern void tekken3_guest_follow(unsigned player,unsigned id,unsigned costume);
extern int tekken3_native_moves_force(unsigned player,unsigned id);
extern int tekken3_native_moves_set(unsigned player,unsigned id,const char *key,unsigned moveset);
extern void tekken3_ttt1_guest_now(unsigned player);
extern void tekken3_cine_swap_loading(int on,unsigned side);
extern void tekken3_cine_swap_forget(void);
enum { NATIVES=23 };
static int character_id(const char *token) {
    if(*token>='0' && *token<='9') return atoi(token);
    int k=tekken3_guest_id(token);
    return k>=0?k:tekken3_t3_key_id(token);
}
static const char *segment_character(const Actor *a,int s,int *costume) {
    *costume=s<0?a->costume:a->swaps[s].costume;
    return s<0?a->character:a->swaps[s].character;
}
static int segment_at(const Actor *a,int f) {
    int s=-1;
    for(int i=0;i<a->swap_count && a->swaps[i].frame<=f;i++) s=i;
    return s;
}
/* This tick's loads: in the pre-roll's first tick each character the actors
 * change to (once each: its files serve both actors), then each actor's own;
 * afterwards an actor whose segment begins. */
typedef struct { unsigned player; int segment; } Load;
static Load loads[LOADS_MAX];
static int load_count;
static void plan_loads(void) {
    load_count=0;
    if(tick==0) {
        for(unsigned p=0;p<PLAYED && p<(unsigned)cine->actor_count;p++) {
            const Actor *a=&cine->actors[p];
            loaded[p]=-1;
            for(int s=0;s<a->swap_count;s++) {
                int seen=0,c,c2;
                const char *who=segment_character(a,s,&c);
                for(int k=0;k<load_count;k++) {
                    const char *w2=segment_character(&cine->actors[loads[k].player],loads[k].segment,&c2);
                    if(!strcmp(who,w2) && c==c2) seen=1;
                }
                if(!seen && strcmp(who,a->character)) loads[load_count++]=(Load){p,s};
            }
        }
        int preloaded=load_count;
        for(unsigned p=0;p<PLAYED && p<(unsigned)cine->actor_count;p++)
            for(int k=0;k<preloaded;k++) if(loads[k].player==p) { loads[load_count++]=(Load){p,-1}; break; }
        if(load_count) fprintf(stderr,"Cine: %d characters read ahead for the changes\n",preloaded);
        return;
    }
    int f=frame_or_zero();
    for(unsigned p=0;p<PLAYED && p<(unsigned)cine->actor_count;p++) {
        int s=segment_at(&cine->actors[p],f);
        if(s!=loaded[p]) loads[load_count++]=(Load){p,s};
    }
}
/* Before the game loads the actor: who it is to the roster and the moves. */
static int load_begin(unsigned p,int s,int *id,int *costume) {
    const char *who=segment_character(&cine->actors[p],s,costume);
    if((*id=character_id(who))<0) { fprintf(stderr,"Cine: no character \"%s\" for actor %u\n",who,p); return 0; }
    tekken3_guest_follow(p,(unsigned)*id,(unsigned)*costume);
    if(*id<NATIVES) {
        /* A native plays the poses on its TTT1 moves (mode 4), as the scene loads it. */
        if(!tekken3_native_moves_force(p,(unsigned)*id)) fprintf(stderr,"Cine: no TTT1 moves for native %d, its poses will not play\n",*id);
    } else tekken3_native_moves_set(p,0,NULL,0);
    fprintf(stderr,"Cine: actor %u becomes %s (%d, costume %d) at tick %d\n",p,who,*id,*costume,tick);
    tekken3_cine_swap_loading(1,0);
    return 1;
}

/* One tick of the coroutine: 1 once the frame is done, 0 when it called
 * the game (it comes back here). Tick 0 is the overlay's setup (0x800B3CA0)
 * without its script or its change of the player's actor to Heihachi; tick
 * 1 its first frame (0x800B4060, state 0); then a frame each (state 1,
 * without the script). Everything kept across a call is static. */
static int run(CPUState *cpu) {
    const uint32_t p1=ACTOR0,p2=ACTOR0+ACTOR_SIZE;
    static unsigned p;
    static uint32_t x,a,b,s0,v,bit;
    static int k,id,costume; static uint32_t keep[12];
    switch(line) { case 0:
    plan_loads();
    for(k=0;k<load_count;k++) {
        p=loads[k].player; x=ACTOR0+p*ACTOR_SIZE;
        if(!load_begin(p,loads[k].segment,&id,&costume)) { loaded[p]=loads[k].segment; continue; }
        for(unsigned i=0;i<12;i++) keep[i]=psx_mod_read_word(x+i*4);
        /* The last frame's display list may still wait in libgpu's queue (it
         * leaves at the next transfer, the loader's first LoadImage): drawn
         * now, while the packets it links are still in place. */
        CALL(0x8007c3a4,0);
        /* No frame sent by the VSync callback until the end (the game's
         * loaders hold it with this counter only while they run). */
        CALL(0x80029638,1);
        CALL(0x8004f274,x,(uint32_t)id,(uint32_t)costume);
        CALL(0x8002d1dc,H(x+0x16));
        psx_mod_write_half(x+0x16,(uint16_t)cpu->gpr[2]);
        CALL(0x80069aa8,0);
        CALL(0x8006c618,(uint32_t)psx_mod_read_half(0x800adc84),H(p1+0x1c),H(p2+0x1c),H(p1+0x16),H(p2+0x16));
        CALL(0x80069f74,0);         /* the move table's new slot: its file read, relocated */
        CALL0(0x8006a158);          /* each player on its slot's moves (0x8002CE14, 0x8002D07C) */
        /* The files loaded on this side (0x800A0898 + 2 * side) forgotten: the
         * loader then loads whatever it is told (the cinematic's setup marks
         * player 2 as having player 1's files, see tick 0). */
        psx_mod_write_half(0x800a0898+2u*psx_mod_read_byte(x+0x1e),0xffff);
        CALL(0x80036310,x,cpu->gpr[29]+SCRATCH,cpu->gpr[29]+SCRATCH+4);
        a=psx_mod_read_word(cpu->gpr[29]+SCRATCH); b=psx_mod_read_word(cpu->gpr[29]+SCRATCH+4);
        /* The textures go up through libgpu's queue (LoadImage 0x8007C650),
         * read from the staging buffer when their turn comes: all of them
         * up (DrawSync(0), 0x8007C3A4) before its bytes are put back, after
         * the model's packets are built (0x80035CE8 reads it too), but for
         * this side's packet areas, which lie under it and which it has just
         * filled (src/tekken3_cine_swap.c). */
        CALL(0x8007c3a4,0);
        CALL(0x80035ce0,x,a,b);
        CALL(0x80035ce8,x,a,b);
        tekken3_cine_swap_loading(0,psx_mod_read_byte(x+0x1e));
        CALL(0x8006c63c,(uint32_t)psx_mod_read_byte(x+0x1e)+1,1);
        /* The other buffer's list (the last frame's) links the old model's
         * packets, in places the new one's now fill: emptied, in case it is
         * sent again before the next frame rebuilds it. */
        {
            uint32_t cur=psx_mod_read_word(0x800adefc)&1,other=ot()+(cur?-0x1000u:0x1000u);
            psx_mod_write_word(other+0xffc,0x00ffffffu);
        }
        CALL(0x8003c258,x);
        CALL(0x8002bd78,x,x==p1?p2:p1);
        CALL(0x80029638,0);
        /* Its place as the cinematic set it (+0x00 to +0x11 position and
         * angles, +0x2C its facing), not its identity (+0x14 to +0x1E). */
        for(unsigned i=0;i<12;i++) if(i<4 || i==11) psx_mod_write_word(x+i*4,keep[i]);
        psx_mod_write_half(x+0x10,(uint16_t)keep[4]);
        loaded[p]=loads[k].segment;     /* before the graft: its model steps are this segment's */
        tekken3_ttt1_guest_now(p);
        /* The engine's record again from the new character's stance (its
         * moves are another file). */
        if(record[p] && psx_mod_read_word(x+0x54)!=record[p]) {
            v=psx_mod_read_word(x+0x54);
            if(v>=0x80010000u) {
                for(unsigned i=4;i<56;i+=4) if(i!=24 && i!=28 && i!=32) psx_mod_write_word(record[p]+i,psx_mod_read_word(v+i));
                saved_record[p][0]=v; saved_record[p][1]=psx_mod_read_word(x+0x4c);
            }
        }
    }
    if(tick==0) {
        CALL(0x800482b0,6);
        psx_mod_write_byte(0x800afaa1,1);
        CALL(0x8004b688,0);
        CALL(0x8003c258,p1);
        CALL(0x8003c258,p2);
        CALL(0x8002bd78,p1,p2);
        CALL(0x8002bd78,p2,p1);
        CALL0(0x80074f44);
        /* The side the human plays (0x800AFA88 + 0x1D bit 0) is the one
         * Ogre's cutscene turns into Heihachi; the rest of its setup kept. */
        a=psx_mod_read_byte(0x800afa88+0x1d)&1?p1:p2; b=a==p1?p2:p1;
        psx_mod_write_half(a+0x16,(uint16_t)((int16_t)psx_mod_read_half(a+0x14)/4));
        psx_mod_write_half(a+0x18,(uint16_t)((int16_t)psx_mod_read_half(a+0x14)/4));
        CALL(0x8006c618,(uint32_t)psx_mod_read_half(0x800adc84),H(p1+0x1c),H(p1+0x1c),H(p2+0x16),H(p2+0x16));
        s0=psx_mod_read_byte(b+0x1e);
        CALL(0x80036310,a,cpu->gpr[29]+SCRATCH,cpu->gpr[29]+SCRATCH+4);
        CALL(0x80035ce0,a,psx_mod_read_word(cpu->gpr[29]+SCRATCH),psx_mod_read_word(cpu->gpr[29]+SCRATCH+4));
        CALL(0x80035ce8,a,psx_mod_read_word(cpu->gpr[29]+SCRATCH),psx_mod_read_word(cpu->gpr[29]+SCRATCH+4));
        CALL(0x80035ed0,s0);
        v=cpu->gpr[2];
        CALL(0x80035eec,s0);
        CALL(0x80035ce8,b,v,cpu->gpr[2]);
        CALL(0x8006c63c,1,1);
        CALL(0x8006c63c,2,1);
        for(p=0;p<2;p++) {
            x=ACTOR0+p*ACTOR_SIZE;
            psx_mod_write_half(x+0x0e,0x4000); psx_mod_write_half(x+0x0c,0);
            psx_mod_write_word(x,0); psx_mod_write_word(x+4,0); psx_mod_write_word(x+8,0); psx_mod_write_half(x+0x10,0);
            psx_mod_write_half(x+0x2c,0x4000);
        }
        /* The actors' own placement (the default is the one above). */
        for(p=0;p<PLAYED && p<(unsigned)cine->actor_count;p++) {
            const int *pl=cine->actors[p].place; x=ACTOR0+p*ACTOR_SIZE;
            psx_mod_write_word(x,(uint32_t)pl[0]); psx_mod_write_word(x+4,(uint32_t)pl[1]); psx_mod_write_word(x+8,(uint32_t)pl[2]);
            psx_mod_write_half(x+0x0e,(uint16_t)pl[3]); psx_mod_write_half(x+0x2c,(uint16_t)pl[3]);
        }
        if(!records()) fprintf(stderr,"Cine: no stance record to copy\n");
        far_tile();
    } else if(tick==1) {
        CALL0(0x80062a10);
        CALL(0x800690a0,p1,p2);
        CALL(0x80065ed8,p1,p2);
        CALL(0x800670fc,2);
        far_tile();
    } else {
        background();
        cuts();                     /* before the frame's sparks fire */
        for(p=0;p<2;p++) {
            x=ACTOR0+p*ACTOR_SIZE;
            if(p<(unsigned)cine->actor_count) hold(p);
            bit=psx_mod_read_word(psx_mod_read_word(x+0x54)+0x24)&0x40000000u;
            psx_mod_write_word(psx_mod_read_word(x+0x54)+0x24,psx_mod_read_word(psx_mod_read_word(x+0x54)+0x24)&0xbfffffffu);
            CALL(0x800458c8,x,p2);
            psx_mod_write_word(0x80096ea8,1);
            CALL(0x8003a818,x);
            psx_mod_write_word(psx_mod_read_word(x+0x54)+0x24,(psx_mod_read_word(psx_mod_read_word(x+0x54)+0x24)&0xbfffffffu)|bit);
        }
        storms();                   /* the TTT stage's lightning (`storm`) */
        CALL(0x800670fc,0);
        tekken3_cine_floor_before();
        floor_centre(1);
        CALL(0x80048240,p1,p2);
        tekken3_cine_floor_after(cpu,p1,p2);    /* the tiles near the camera it dropped */
        floor_centre(0);
        sprites(cpu);               /* the GTE still holds the view */
        CALL(0x8007745c,1);         /* the hit effects (Jin's lightning), as the fight's loop runs them */
        CALL0(0x8006d7cc);
        if(!psx_mod_read_word(0x800adca4)) far_tile();
        else CALL(0x80048374,psx_mod_read_word(0x800adefc));
        CALL(0x80039ddc,(uint32_t)psx_mod_read_half(0x800adc84));
        CALL(0x8003ec64,p1,p2);
        CALL0(0x80039f84);
        CALL0(0x80036000);
        CALL0(0x800378f8);
        {
            int on,level=fade_level(&on);
            if(on) {
                v=(uint32_t)(level+256);
                CALL(0x8004e000,psx_mod_read_word(0x800a9218)+8,psx_mod_read_word(0x800adf64),v);
                psx_mod_write_word(0x800adf64,cpu->gpr[2]);
            }
        }
    }
    }
    line=0;
    return 1;
}

extern void tekken3_ttt1_embu_effects_reset(void);
/* The fight as the cinematic found it: phase, the actors' placement (+0x00
 * to +0x2F: position, angles, base), the fill tiles' colour, the dark look,
 * and its camera: the setup starts the scripted camera (0x800670FC(2): its
 * mode at 0x800A0418, eye and target at 0x800A0428, the camera object at
 * 0x800A8C70), which the fight's own (0x800630D8, following the fighters)
 * never took back: it stayed on the cinematic's last shot. */
enum { CAM_MODE=0x800a0400, CAM_MODE_SIZE=0x80, CAM_OBJECT=0x800a8c40, CAM_OBJECT_SIZE=0xc0 };
static struct { unsigned phase; uint32_t actor[2][12],fill[4]; uint8_t dark;
                uint32_t mode[CAM_MODE_SIZE/4],object[CAM_OBJECT_SIZE/4]; } resume;
/* `ttt-stage` / `storm`: a TTT arcade stage drawn instead of the arena (TTT
 * Stages, src/tekken3_arcade_stages.h: 0 when unavailable, the arena's own then)
 * and its storm's lightning at given frames, once each (a held frame flashes
 * once; `quiet`: without its thunder, the Embu's). The stage let go when the
 * cinematic ends. */
static int storm_last=-1;
static void storms(void) {
    int f=tekken3_cine_engine_frame();
    if(f<0 || f==storm_last) return;
    storm_last=f;
    for(int i=0;i<cine->storm_count;i++)
        if(cine->storms[i].frame==f && !tekken3_ttt_stage_flash(cine->storms[i].type))
            fprintf(stderr,"Cine: no TTT stage for the lightning at %d\n",f);
}
/* The prepared cinematic's TTT arcade stage, -1 none (src/tekken3_cine_trigger.c). */
int tekken3_cine_ttt_stage(void) { return cine?cine->ttt_stage:-1; }

/* What the cinematic took, let go: at its end, or when the game leaves the
 * fight under it. */
static void let_go(void) {
    for(unsigned p=0;p<PLAYED && p<(unsigned)cine->actor_count;p++) {
        uint32_t x=ACTOR0+p*ACTOR_SIZE;
        if(saved_record[p][0]) { psx_mod_write_word(x+0x54,saved_record[p][0]); psx_mod_write_word(x+0x4c,saved_record[p][1]); }
    }
    playing=0; line=0;
    if(stage_forced) { tekken3_ttt_stage_force(-1); stage_forced=0; }
    g_psx_gpu_allow_oversize=0;
    tekken3_cine_swap_forget();
    tekken3_ttt1_embu_effects_reset();
}
/* The game left the fight under it (Start in the demo fight's mode, which
 * the scene borrows: 0x8005101C, the fight's first call, goes to the modes
 * menu, src/tekken3_cine_scene.c): no frame of its comes again, the wrapper
 * below is not called out of state 8. Let go, nobody called. */
void tekken3_cine_abandon(void) {
    if(!playing) return;
    let_go(); done=NULL;
    fprintf(stderr,"Cine: \"%s\" left after %d frames\n",cine->name,tick-2-preroll);
}

static void finish(void) {
    let_go();
    fprintf(stderr,"Cine: \"%s\" over after %d frames\n",cine->name,tick-2-preroll);
    void (*then)(void)=done; done=NULL;
    if(then) { then(); return; }
    /* Nobody takes over (a test in a fight): the fight goes on where it was. */
    psx_mod_write_half(PHASE,(uint16_t)resume.phase);
    for(unsigned p=0;p<2;p++)
        for(unsigned k=0;k<0x30;k+=4) psx_mod_write_word(ACTOR0+p*ACTOR_SIZE+k,resume.actor[p][k/4]);
    for(unsigned i=0;i<4;i++) psx_mod_write_word(0x8009e73cu+i*16,resume.fill[i]);
    psx_mod_write_byte(0x800afaa0,resume.dark);
    for(unsigned k=0;k<CAM_MODE_SIZE;k+=4) psx_mod_write_word(CAM_MODE+k,resume.mode[k/4]);
    for(unsigned k=0;k<CAM_OBJECT_SIZE;k+=4) psx_mod_write_word(CAM_OBJECT+k,resume.object[k/4]);
}

/* `hide`: an actor not drawn, its body nor its shadow, while its animation
 * goes on. Both are drawn by 0x8003B4F8 (actor), at the end of its animation
 * step (0x8003A818): the shadow's packets (0x80037B28), the body
 * (0x80037924, a pointer to 0x8003792C), the sword glow (0x8003172C). */
static int hidden(unsigned p) {
    if(!playing || p>=PLAYED || p>=(unsigned)cine->actor_count) return 0;
    const Actor *a=&cine->actors[p];
    int f=frame_or_zero(),shown=1;
    for(int i=0;i<a->show_count && a->shows[i].frame<=f;i++) shown=a->shows[i].shown;
    return !shown;
}
/* Once an actor is drawn (its draw returned: a generated function returns
 * at each call it makes), Unknown's wolf after her (src/tekken3_ttt1_wolf.c). */
extern void __real_func_8003B4F8(CPUState *cpu);
extern void tekken3_ttt1_wolf_after_actor(CPUState *cpu,uint32_t actor);
void __wrap_func_8003B4F8(CPUState *cpu) {
    static uint32_t return_pc,return_sp,actor;
    if(cpu->pc==0 || cpu->pc==0x8003b4f8u) {
        if((cpu->gpr[4]==ACTOR0 || cpu->gpr[4]==ACTOR0+ACTOR_SIZE) && hidden(cpu->gpr[4]!=ACTOR0)) {
            cpu->pc=cpu->gpr[31]; return;
        }
        return_pc=cpu->gpr[31]; return_sp=cpu->gpr[29]; actor=cpu->gpr[4];
    }
    __real_func_8003B4F8(cpu);
    if(return_pc && cpu->pc==return_pc && cpu->gpr[29]==return_sp) {
        return_pc=0;
        tekken3_ttt1_wolf_after_actor(cpu,actor);
    }
}

/* The phase machine draws a phase's primitives from its display buffer's own
 * base (0x800AE040 + 28 * buffer + 24, buffer 0x800ADEFC) and gives the
 * pointer 0x800ADF64 back as it was afterwards: the engine's frame too. */
static uint32_t caller_prims;
extern void __real_func_80050450(CPUState *cpu);

/* A test: TEKKEN3_CINE_HOLD="f1,f2,..." holds each of these frames of the
 * cinematic HOLD_TICKS game frames ("Cine: hold frame N" in the log), long
 * enough for a bench to take its screenshot at that exact frame (a side by
 * side with the PS2's, tools/ps2/ttt_compare_shots.py).
 * TEKKEN3_CINE_HOLD_TICKS changes the length (tools/pgxp_cine.py: several
 * captures of one held frame, options switched between them). */
enum { HOLD_TICKS=60, HOLDS_MAX=256 };
static int held(void) {
    static int parsed,frames[HOLDS_MAX],count,next,left,ticks=HOLD_TICKS;
    if(!parsed) {
        parsed=1;
        const char *t=getenv("TEKKEN3_CINE_HOLD_TICKS");
        if(t && atoi(t)>0) ticks=atoi(t);
        const char *e=getenv("TEKKEN3_CINE_HOLD");
        for(const char *c=e;c && *c && count<HOLDS_MAX;) {
            frames[count++]=atoi(c);
            c=strchr(c,','); if(c) c++;
        }
    }
    if(left) { left--; return 1; }
    int f=tekken3_cine_engine_frame();
    while(next<count && frames[next]<f) next++;
    if(next<count && frames[next]==f) {
        next++; left=ticks-1;
        fprintf(stderr,"Cine: hold frame %d\n",f); fflush(stderr);
        return 1;
    }
    return 0;
}
void __wrap_func_80050450(CPUState *cpu) {
    if(playing && (cpu->pc==0 || cpu->pc==ENTRY) && (line || !cpu->gpr[2])) {
        if(!line) {                 /* the phase machine's turn, not paused: a frame begins */
            if(psx_mod_read_word(STATE)!=8) { tekken3_cine_abandon(); fprintf(stderr,"Cine: the fight ended under it\n"); }
            else {
                cpu->gpr[29]-=FRAME; psx_mod_write_half(PHASE,17);
                caller_prims=psx_mod_read_word(0x800adf64);
                psx_mod_write_word(0x800adf64,psx_mod_read_word(0x800ae040+28*psx_mod_read_word(0x800adefc)+24));
            }
        }
        if(playing) {
            if(!run(cpu)) return;   /* gone to the game, back here after */
            psx_mod_write_word(0x800adf64,caller_prims);
            cpu->gpr[29]+=FRAME;
            if(!held()) tick++;
            if(tick-2-preroll>=cine->length) finish();
            cpu->gpr[2]=0; cpu->pc=EPILOGUE;
            return;
        }
    }
    __real_func_80050450(cpu);
}

/* ---- The recorder -------------------------------------------------------- */

/* TEKKEN3_CINE_RECORD=file: what a cinematic shows, frame by frame, the old
 * way's as the engine's, to compare them (tools/cine_compare.py). Records of
 * int32 frame, int32 kind, then for an actor (kind 0, 1) its skeleton's root
 * (actor + 0xF54, 32 bytes), its 18 bones' local matrices (+0xF74, 576) and
 * its position (+0x00, 16); for the camera (kind -1) the eye and target given
 * to 0x80063EEC (6 int32). All of them each time the view is built: after
 * both actors' animation step (src/tekken3_cine_hooks.c). */
extern int tekken3_cine_frame(void);
static FILE *recording;
static FILE *recorder(void) {
    static int tried;
    if(!tried) {
        tried=1;
        const char *e=getenv("TEKKEN3_CINE_RECORD");
        if(e && (recording=fopen(e,"wb"))) fprintf(stderr,"Cine: recording to %s\n",e);
    }
    return tekken3_cine_frame()>=0?recording:NULL;
}
void tekken3_cine_record_camera(const int32_t view[6]) {
    FILE *f=recorder();
    if(!f) return;
    int32_t head[2]={tekken3_cine_frame(),-1};
    fwrite(head,4,2,f); fwrite(view,4,6,f);
    /* Both actors as their animation step left them this frame. */
    for(unsigned p=0;p<2;p++) {
        uint32_t actor=ACTOR0+p*ACTOR_SIZE;
        uint8_t body[32+576+16];
        for(unsigned k=0;k<32+576;k++) body[k]=psx_mod_read_byte(actor+0xf54+k);
        for(unsigned k=0;k<16;k++) body[608+k]=psx_mod_read_byte(actor+k);
        head[1]=(int32_t)p;
        fwrite(head,4,2,f); fwrite(body,1,sizeof body,f);
    }
    fflush(f);
}

/* ---- The API ------------------------------------------------------------- */

/* The prepared cinematic's scene, for its loading (src/tekken3_cine_scene.c):
 * arena, dark look and the played actors' characters and costumes (a single
 * actor stands for both). Returns the number of actors, 0 if none prepared. */
int tekken3_cine_scene_of(int *arena,int *dark,char character[PLAYED][32],int costume[PLAYED]) {
    if(!cine) return 0;
    *arena=cine->arena; *dark=cine->dark;
    for(unsigned p=0;p<PLAYED;p++) {
        const Actor *a=&cine->actors[p<(unsigned)cine->actor_count?p:0];
        snprintf(character[p],32,"%s",a->character); costume[p]=a->costume;
    }
    return cine->actor_count;
}

/* Reads a cinematic ahead of its playing (a player reloaded for it takes its
 * first model files); 1 if it can be played. */
int tekken3_cine_prepare(const char *path) {
    if(playing) return 0;
    Cine *c=cine_read(path);
    if(!c) return 0;
    cine_free(cine); cine=c;
    free(music); music=NULL; music_frames=music_pos=0; music_from=-2;
    return 1;
}
/* Plays the prepared cinematic (or `path`) in the running fight, after
 * `pre` black frames (actors still settling), then calls `on_done`. */
int tekken3_cine_play(const char *path,int pre,void (*on_done)(void)) {
    if(playing || (path && !tekken3_cine_prepare(path)) || !cine) return 0;
    if(psx_mod_read_word(STATE)!=8) { fprintf(stderr,"Cine: not in a fight\n"); return 0; }
    if(!tiles && !(tiles=psx_mod_alloc_gpu_dma_memory(32,16))) return 0;
    playing=1; tick=0; preroll=pre<0?0:pre; done=on_done; loaded[0]=loaded[1]=-1;
    /* Its close shots: a polygon near the camera spans more than the PS1 GPU
     * draws (1023 x 511 pixels: rejected whole), Angel's wing in front of the
     * camera went missing; the PS2 draws it. Allowed while it plays. */
    g_psx_gpu_allow_oversize=1;
    /* What a fight needs back when nobody takes over at the end (finish). */
    resume.phase=psx_mod_read_half(PHASE);
    for(unsigned p=0;p<2;p++)
        for(unsigned k=0;k<0x30;k+=4) resume.actor[p][k/4]=psx_mod_read_word(ACTOR0+p*ACTOR_SIZE+k);
    for(unsigned i=0;i<4;i++) resume.fill[i]=psx_mod_read_word(0x8009e73cu+i*16);
    resume.dark=psx_mod_read_byte(0x800afaa0);
    for(unsigned k=0;k<CAM_MODE_SIZE;k+=4) resume.mode[k/4]=psx_mod_read_word(CAM_MODE+k);
    for(unsigned k=0;k<CAM_OBJECT_SIZE;k+=4) resume.object[k/4]=psx_mod_read_word(CAM_OBJECT+k);
    tekken3_ttt1_embu_effects_reset();         /* its own lightning packs */
    storm_last=-1; cut_last=-1;
    if(cine->ttt_stage>=0 && !(stage_forced=tekken3_ttt_stage_force(cine->ttt_stage)))
        fprintf(stderr,"Cine: TTT stage %d unavailable, the arena's own\n",cine->ttt_stage);
    psx_mod_write_half(PHASE,17);
    fprintf(stderr,"Cine: \"%s\" plays, %d frames after %d of pre-roll\n",cine->name,cine->length,preroll);
    return 1;
}

/* A test: TEKKEN3_CINE_TEST="file.cine@frames" plays it in any fight, that
 * many frames into its first round, with the fighters there. */
void tekken3_cine_test_tick(void) {
    static int parsed,delay=-1,count;
    static char path[1024];
    if(!parsed) {
        parsed=1;
        const char *e=getenv("TEKKEN3_CINE_TEST"),*at=e?strrchr(e,'@'):NULL;
        if(!at) return;
        snprintf(path,sizeof path,"%.*s",(int)(at-e),e);
        delay=atoi(at+1);
    }
    if(delay<0 || playing) return;
    if(psx_mod_read_word(STATE)!=8 || psx_mod_read_half(PHASE)!=8) { count=0; return; }
    if(++count==delay) { tekken3_cine_play(path,0,NULL); delay=-1; }
}
