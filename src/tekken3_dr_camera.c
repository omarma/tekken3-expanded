/* Dark Resurrection's move cameras replayed on a DR moveset (PSP-DR.md, A3
 * "Caméra"). In DR a move's property 0x815f picks a camera of the engine:
 * the Deathfist family cuts to a close shot at the impact (6), the throws
 * turn round the fighters (82..90, 27). Tekken 3 has nothing like the
 * first and plays its own throw cameras from the move's +0x24 low byte,
 * which a pack's records leave at 0 (the generic throw shot). The cameras
 * were filmed in DR, frame by frame, and written by tools/psp/dr_camera.py
 * as <moves prefix>-camera.txt beside the pack: per pack record, the eye
 * and the target of each frame in the attacker's frame at the start (origin
 * on the floor under him, forward towards the opponent, up, and the side the
 * camera was on), and the projection distance.
 *
 * The camera's key goes through camera_key_apply (0x80064080, a0 the key of
 * camera_keys 0x800A02A8 it applies: eye, pitch, yaw on 18 bits, projection
 * distance), whichever way the fight camera got it (follow, shots, throw
 * tracks, blends): while a track plays, its key replaces the game's, blended
 * at the ends a throw's track asks for (a hit's cut is a cut), and the
 * projection range of camera_work (+0x66 / +0x68, 500 both in a fight) is
 * opened for that call. The side of the track is the side the game's camera
 * is on when it starts: Paul on the right plays it mirrored. A hit's cut is
 * turned round its pivot to one of DR's three angles, picked by the frame
 * counter (the same frame, the same angle).
 *
 * DR draws a throw's camera among several (Jin's 1+3: three, J7), as Tekken 3
 * draws its own moves' cameras (camera_seq_load: rand() & 0xFFF walks the
 * sequence's cumulative thresholds). A record may have several tracks, each
 * with its threshold (DRCAM 2): the one played is drawn the same way, with
 * the number rand() would give next (its seed 0x800A39B8 read, not stepped:
 * the game's own draws stay as they were).
 *
 * A round's K.O. (round_ko_seen) stops the game's camera where it is until
 * the replay: a track playing then runs to its end and holds its last key,
 * without the blend back into a key the game no longer moves (the throw's
 * K.O. turned the camera into Devil Jin before the replay). The replay's own
 * camera (camera_replay_active, camera_key_apply(1)) plays without tracks:
 * the throw replayed there started its track again. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "tekken3_ttt1_assets.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { ACTOR0=0x800a9228, ACTOR_SIZE=0x188c, STATE=0x800ae204, FRAME=0x800adefc,
       CAMERA_KEYS=0x800a02a8, CAMERA_WORK=0x800a8c70, ROUND_KO_SEEN=0x80095498, REPLAY_ACTIVE=0x800a04cd, RAND_SEED=0x800a39b8,
       TRACKS_MAX=64, FRAMES_MAX=600 };

typedef struct {
    int record,hit,delay,blend_in,blend_out,frames,pivot[2];
    int threshold;                     /* DRCAM 2: drawn when rand() & 0xFFF <= it, its record's first such (0xFFF: always) */
    int16_t (*key)[7];                 /* eye s u f, target s u f, projection */
} Track;
typedef struct {
    unsigned generation;
    int attempted,count;
    Track tracks[TRACKS_MAX];
} Table;
typedef struct {
    const Track *track;                /* playing (t >= 0) or waiting for its delay (t < 0) */
    int t,side;                        /* side: 0 until the first key decides it */
    double turn[2];                    /* a hit's cut: cos, sin of its angle round the pivot */
    int32_t origin[3],forward[2];      /* forward: x, z, 4096 = 1 */
    int last_record,opponent_hit;
    int ko;                            /* the round's K.O. seen: no blend out, the last key held */
    int fight;                         /* a throw's: the fight camera's place against the fighters, read at its start */
    double fight_u,fight_v;            /* the eye off their midpoint, along the line to the opponent and across it */
    int32_t fight_y,fight_pitch,fight_yaw,fight_proj;   /* yaw against the line's */
    int fight_side;                    /* at the blend out: 1 the thrower on his side of the screen, -1 the sides
                                        * swapped (DR's own camera stays and they cross), 0 not decided yet */
} Play;

extern int tekken3_ttt1_record_index(unsigned p,uint32_t record);
extern int tekken3_cine_pending(void);
static Table tables[2];
static Play plays[2];
static uint32_t last_frame;
static int post_trace;                 /* trace: frames left to print the game's key after a track */
/* A throw's track over: the key it last applied held HOLD frames, then blended into the game's over BLEND. The
 * game kept its own keys on the thrower's side through the track (its key 1, then the throw's end blend from the
 * key 3 it saved) and applied them as the track ended: half a turn at once, then 7 degrees a frame (Christie's 1+3,
 * key 1 at 33 degrees against the track's 262; the user, 2026-11-04: "T3 force a revenir dans le cote initial").
 * Once that blend is over its fight camera follows the fighters' order on screen, DR's then. */
enum {HOLD=40,BLEND=16};
static int hold;static uint32_t hold_frame;static int32_t last_key[6];
/* TEKKEN3_DR_CAMERA_TRACE: both fighters in the track's frame, every 5 frames. */
static int trace=-1;

static void table_free(Table *t) {
    for(int i=0;i<t->count;i++)free(t->tracks[i].key);
    memset(t,0,sizeof *t);
}

/* <prefix>-camera.txt: "DRCAM 1", then per track
 * "track <record> <hit|throw> <delay> <blend in> <blend out> <frames>", a
 * DRCAM 2 track's threshold (0..4095, a record's tracks in order), a
 * hit's pivot (across, forward: the point its cut turns round), and its
 * frames, seven numbers each. Only DR packs have one. */
static const Table *table_for(unsigned p) {
    Table *t=&tables[p];
    unsigned generation=tekken3_guest_moves_generation(p);
    if(t->generation!=generation){table_free(t);t->generation=generation;}
    if(t->attempted)return t->count?t:NULL;
    t->attempted=1;
    const char *root=tekken3_ttt1_asset_root(),*prefix=tekken3_guest_moves_prefix_for(p);
    char path[4096],kind[8];
    if(!root || !prefix || snprintf(path,sizeof path,"%s/%s-camera.txt",root,prefix)>=(int)sizeof path)return NULL;
    FILE *f=fopen(path,"r");
    if(!f)return NULL;
    int version=0;
    if(fscanf(f," DRCAM %d",&version)!=1 || (version!=1 && version!=2)){fclose(f);return NULL;}
    while(t->count<TRACKS_MAX) {
        Track *k=&t->tracks[t->count];
        if(fscanf(f," track %d %7s %d %d %d %d",&k->record,kind,&k->delay,&k->blend_in,&k->blend_out,&k->frames)!=6)break;
        if(k->frames<1 || k->frames>FRAMES_MAX)break;
        k->hit=!strcmp(kind,"hit");
        k->threshold=0xfff;
        if(version>=2 && fscanf(f,"%d",&k->threshold)!=1)break;
        if(k->hit && fscanf(f,"%d %d",&k->pivot[0],&k->pivot[1])!=2)break;
        k->key=calloc((size_t)k->frames,sizeof *k->key);
        int ok=k->key!=NULL;
        for(int i=0;ok && i<k->frames;i++)
            for(int j=0;j<7;j++){int v;if(fscanf(f,"%d",&v)!=1){ok=0;break;}k->key[i][j]=(int16_t)v;}
        if(!ok){free(k->key);k->key=NULL;break;}
        t->count++;
    }
    fclose(f);
    fprintf(stderr,"DR camera: P%u %s, %d tracks\n",p+1,prefix,t->count);
    return t->count?t:NULL;
}
/* The record's track, drawn among its tracks as camera_seq_load draws: rand() & 0xFFF, the first track whose
 * threshold is not below it (the last one when none). */
static const Track *find(const Table *t,int record,int hit) {
    uint32_t seed=psx_mod_read_word(RAND_SEED)*0x41c64e6du+0x3039u;
    int r=(int)((seed>>16)&0xfff);
    const Track *last=NULL;
    for(int i=0;i<t->count;i++) {
        const Track *k=&t->tracks[i];
        if(k->record!=record || k->hit!=hit)continue;
        if(k->threshold>=r)return k;
        last=k;
    }
    return last;
}
static int32_t s32(uint32_t a){return (int32_t)psx_mod_read_word(a);}
/* A fighter's facing as a unit vector (x, z): his heading, actor +0x2C (+0x2A, the angle to the opponent, is
 * atan2(dx, dz) in 1/65536 of a turn, the same way). For a paired throw, whose thrower Tekken 3 puts on his
 * victim's very place as it starts (Christie's 1+3: both at 2583, 757), so that their line is no direction. */
static void facing(uint32_t me,double *x,double *z) {
    double h=psx_mod_read_half(me+0x2c)*(2*M_PI/65536.0);
    *x=sin(h);*z=cos(h);
}

static void start(unsigned p,const Track *k,int t) {
    Play *s=&plays[p];
    uint32_t me=ACTOR0+p*ACTOR_SIZE,them=ACTOR0+(p^1)*ACTOR_SIZE;
    s->track=k;s->t=t;s->side=0;s->fight=0;s->fight_side=0;
    /* DR draws a cut's angle: across, or 60 degrees towards either end of the line. */
    double a=k->hit?((int)(last_frame%3)-1)*M_PI/3:0;
    s->turn[0]=cos(a);s->turn[1]=sin(a);
    s->origin[0]=s32(me+0xf68);s->origin[1]=s32(me+4);s->origin[2]=s32(me+0xf70);
    double dx=s32(them+0xf68)-s->origin[0],dz=s32(them+0xf70)-s->origin[2],d=sqrt(dx*dx+dz*dz);
    if(d<1){facing(me,&dx,&dz);d=1;}           /* paired on one place: his facing (was +z, a camera at random) */
    s->forward[0]=(int32_t)lround(dx/d*4096);s->forward[1]=(int32_t)lround(dz/d*4096);
    fprintf(stderr,"DR camera: P%u record %d, %s track (threshold %d)\n",p+1,k->record,k->hit?"hit":"throw",k->threshold);
}
/* One game frame: a throw's track starts as its record does, a hit's once
 * the opponent is hit in its record and the delay has passed. */
static void reach_step(unsigned state);
static void reaction_end_step(unsigned state);
static void air_push_step(unsigned state);
static void step(void) {
    unsigned state=psx_mod_read_word(STATE);
    reach_step(state);
    reaction_end_step(state);
    air_push_step(state);
    if(trace<0)trace=getenv("TEKKEN3_DR_CAMERA_TRACE")!=NULL;
    int ko=psx_mod_read_word(ROUND_KO_SEEN)!=0,replay=psx_mod_read_byte(REPLAY_ACTIVE)!=0;
    for(unsigned p=0;p<2;p++) {
        Play *s=&plays[p];
        const Table *t=state==8 && !replay && !tekken3_cine_pending()?table_for(p):NULL;
        if(!t){memset(s,0,sizeof *s);s->last_record=-1;continue;}
        uint32_t me=ACTOR0+p*ACTOR_SIZE,them=ACTOR0+(p^1)*ACTOR_SIZE;
        int record=tekken3_ttt1_record_index(p,psx_mod_read_word(me+0x54));
        int hit=psx_mod_read_byte(them+0xd0)!=0;
        s->ko=ko;
        if(s->track && ++s->t>=s->track->frames){if(ko)s->t=s->track->frames-1;else{if(!s->track->hit)hold=HOLD+BLEND;s->track=NULL;post_trace=60;}}
        if(s->track && s->t>=0 && s->t%5==0 && trace) {
            double fx=s->forward[0]/4096.0,fz=s->forward[1]/4096.0,v[2][2];
            uint32_t who[2]={me,them};
            for(int i=0;i<2;i++){double x=s32(who[i]+0xf68)-s->origin[0],z=s32(who[i]+0xf70)-s->origin[2];
                v[i][0]=s->side*(x*fz-z*fx);v[i][1]=x*fx+z*fz;}
            fprintf(stderr,"DR camera: t %d me %.0f %.0f them %.0f %.0f\n",s->t,v[0][0],v[0][1],v[1][0],v[1][1]);
        }
        if(!s->track || s->t<0) {
            const Track *k;
            if(record>=0 && record!=s->last_record && (k=find(t,record,0)))start(p,k,0);
            else if(record>=0 && hit && !s->opponent_hit && (k=find(t,record,1)))start(p,k,-k->delay);
        }
        s->last_record=record;s->opponent_hit=hit;
    }
}

static const double TURN=262144.0/(2*M_PI);   /* 18-bit angles */
static int32_t lerp_angle(int32_t a,int32_t b,int w) {
    int32_t d=(b-a)&0x3ffff;
    if(d&0x20000)d|=~0x3ffff;
    return a+(int32_t)((int64_t)d*w/4096);
}
/* The track's key for this frame, into the game's key k (6 words), blended
 * by the track's ends; the projection distance it needs, 0 for none. */
static int32_t apply(unsigned p,int32_t k[6]) {
    Play *s=&plays[p];
    const Track *t=s->track;
    if(!t || s->t<0)return 0;
    int32_t fx=s->forward[0],fz=s->forward[1];
    if(!s->side) {                      /* the game's camera's side of the forward line */
        int64_t c=(int64_t)(k[0]-s->origin[0])*fz-(int64_t)(k[2]-s->origin[2])*fx;
        s->side=c<0?-1:1;
    }
    const int16_t *v=t->key[s->t];
    double sx=(double)s->side*fz/4096,sz=-(double)s->side*fx/4096,ex[3],tg[3];
    for(int i=0;i<2;i++) {
        double *o=i?tg:ex,a=v[3*i],f=v[3*i+2];
        if(t->hit) {
            double x=a-t->pivot[0],z=f-t->pivot[1];
            a=t->pivot[0]+x*s->turn[0]-z*s->turn[1];f=t->pivot[1]+x*s->turn[1]+z*s->turn[0];
        }
        o[0]=s->origin[0]+a*sx+f*fx/4096.0;
        o[1]=s->origin[1]-v[3*i+1];
        o[2]=s->origin[2]+a*sz+f*fz/4096.0;
    }
    double dx=tg[0]-ex[0],dy=tg[1]-ex[1],dz=tg[2]-ex[2];
    int32_t mine[6]={(int32_t)lround(ex[0]),(int32_t)lround(ex[1]),(int32_t)lround(ex[2]),
                     (int32_t)lround(atan2(dy,sqrt(dx*dx+dz*dz))*TURN),(int32_t)lround(atan2(-dx,dz)*TURN),v[6]};
    int w=4096;
    if(t->blend_in>0 && s->t<t->blend_in)w=(s->t+1)*4096/(t->blend_in+1);
    int left=s->ko?t->frames:t->frames-1-s->t;
    if(t->blend_out>0 && left<t->blend_out){int o=(left+1)*4096/(t->blend_out+1);if(o<w)w=o;}
    /* A throw's track blends back into the fight camera: its place against the fighters as the throw
     * starts (the game's key is still the fight's then), the eye off their midpoint along the line
     * from the thrower and across it, its height, pitch, yaw against the line's and projection, put
     * where the fighters are at the end, on the same side of the line (the thrower kept on his side
     * of the screen). The game's key of those frames was no target: the game's camera goes on from
     * the key applied (camera_keys, the track's), and after the track it turned back to the fight's
     * angle for some 40 frames more (38 degrees after 2+4; the user: "elle galère pour revenir à
     * l'angle classique"); it now goes on from the fight's own place, 4 to 7 degrees off. This also
     * replaces the half turn put in when the fighters swapped places (1+3 passes behind Paul). */
    if(!t->hit) {
        uint32_t me=ACTOR0+p*ACTOR_SIZE,them=ACTOR0+(p^1)*ACTOR_SIZE;
        double px=s32(me+0xf68),pz=s32(me+0xf70),jx=s32(them+0xf68),jz=s32(them+0xf70);
        double lx=jx-px,lz=jz-pz,ld=sqrt(lx*lx+lz*lz),ux=ld>1?lx/ld:0,uz=ld>1?lz/ld:1,mx=(px+jx)/2,mz=(pz+jz)/2;
        if(ld<=1 && s->t==0){facing(me,&ux,&uz);ld=2;}   /* paired on one place as the throw starts: his facing */
        int32_t line=(int32_t)lround(atan2(-ux,uz)*TURN);
        if(s->t==0 && ld>1) {
            double ex=k[0]-mx,ez=k[2]-mz;
            s->fight_u=ex*ux+ez*uz;s->fight_v=ex*uz-ez*ux;
            s->fight_y=k[1];s->fight_pitch=k[3];s->fight_proj=k[5];
            s->fight_yaw=(k[4]-line)&0x3ffff;
            s->fight=1;
        }
        if(trace>0)fprintf(stderr,"DR camera: t %d left %d line %d\n",s->t,left,line);
        if(t->blend_out>0 && left<t->blend_out && s->fight && ld>1) {
            /* The side the fight camera comes back on: the one nearer the track's own at its first blended frame.
             * A throw crossing the fighters over (Christie's 1+3 and 2+4, about 100 to 120 degrees round, DR's
             * camera staying where it was) came back on the thrower's side and swung half round as it blended
             * (the user, 2026-11-04: "T3 force a revenir dans le cote initial"). */
            if(!s->fight_side) {
                int32_t keep=(line+s->fight_yaw)&0x3ffff,cross=(keep+0x20000)&0x3ffff;
                int32_t dk=(mine[4]-keep)&0x3ffff,dc=(mine[4]-cross)&0x3ffff;
                if(dk&0x20000)dk=0x40000-dk;
                if(dc&0x20000)dc=0x40000-dc;
                s->fight_side=dc<dk?-1:1;
                if(trace>0)fprintf(stderr,"DR camera: fight side %d (track yaw %d, keep %d, cross %d, start line %d)\n",
                                   s->fight_side,mine[4],keep,cross,(int)s->fight_yaw);
            }
            double fu=s->fight_u*s->fight_side,fv=s->fight_v*s->fight_side;
            k[0]=(int32_t)lround(mx+fu*ux+fv*uz);k[1]=s->fight_y;
            k[2]=(int32_t)lround(mz+fu*uz-fv*ux);
            k[3]=s->fight_pitch;k[4]=(line+s->fight_yaw+(s->fight_side<0?0x20000:0))&0x3ffff;k[5]=s->fight_proj;
        }
    }
    for(int i=0;i<3;i++)k[i]+=(int32_t)((int64_t)(mine[i]-k[i])*w/4096);
    k[3]=lerp_angle(k[3],mine[3],w);k[4]=lerp_angle(k[4],mine[4],w);
    k[5]+=(mine[5]-k[5])*w/4096;
    return k[5];
}

extern void __real_func_80064080(CPUState *cpu);
static int32_t was[6];static unsigned was_n=~0u;   /* trace: the key last applied */
void __wrap_func_80064080(CPUState *cpu) {
    if(cpu->pc!=0 && cpu->pc!=0x80064080){__real_func_80064080(cpu);return;}
    uint32_t frame=psx_mod_read_word(FRAME);
    if(frame!=last_frame){last_frame=frame;step();}
    unsigned n=cpu->gpr[4];
    int32_t key[6],proj=0;
    uint32_t at=CAMERA_KEYS+n*24;
    if(n<5) {
        for(int i=0;i<6;i++)key[i]=s32(at+i*4);
        if(trace>0 && psx_mod_read_word(ROUND_KO_SEEN))
            fprintf(stderr,"DR camera: KO frame %u key %u %s replay %d track %d t %d\n",frame,n,
                    was_n==n && !memcmp(was,key,sizeof was)?"same":"new",psx_mod_read_byte(REPLAY_ACTIVE),
                    plays[0].track?plays[0].track->record:-1,plays[0].t);
        for(unsigned p=0;p<2 && !proj;p++)proj=apply(p,key);   /* one camera: player 1's first */
    }
    if(n<5){memcpy(was,key,sizeof was);was_n=n;}
    if(!proj && trace>0 && post_trace>0 && n<5){post_trace--;fprintf(stderr,"DR camera: after, frame %u key %u eye %d %d %d yaw %d head %d %d\n",frame,n,key[0],key[1],key[2],key[4],(int16_t)psx_mod_read_half(ACTOR0+0x1278),(int16_t)psx_mod_read_half(ACTOR0+ACTOR_SIZE+0x1278));}
    if(!proj && hold>0 && n<5) {
        if(frame!=hold_frame){hold_frame=frame;hold--;}
        int w=hold>=BLEND?4096:hold*4096/BLEND;      /* the track's key's weight */
        for(int i=0;i<3;i++)key[i]+=(int32_t)((int64_t)(last_key[i]-key[i])*w/4096);
        key[3]=lerp_angle(key[3],last_key[3],w);key[4]=lerp_angle(key[4],last_key[4],w);
        key[5]+=(last_key[5]-key[5])*w/4096;
        proj=key[5];
    }
    if(!proj){__real_func_80064080(cpu);return;}
    for(int i=0;i<6;i++)psx_mod_write_word(at+i*4,(uint32_t)key[i]);
    if(hold<=0 || hold>HOLD+BLEND-1)memcpy(last_key,key,sizeof last_key);
    uint32_t lo=psx_mod_read_half(CAMERA_WORK+0x66),hi=psx_mod_read_half(CAMERA_WORK+0x68);
    psx_mod_write_half(CAMERA_WORK+0x66,(uint16_t)proj);psx_mod_write_half(CAMERA_WORK+0x68,(uint16_t)proj);
    __real_func_80064080(cpu);
    psx_mod_write_half(CAMERA_WORK+0x66,(uint16_t)lo);psx_mod_write_half(CAMERA_WORK+0x68,(uint16_t)hi);
}

/* The reach of a DR moveset's hits (A4, the user's choice of 2026-10-28): <prefix>-reach.txt beside the
 * pack, one number. Tekken 3's capsule is a bare segment between two joints and only the victim's 14 hit
 * spheres (+0x20C, 20 bytes: radius +0x0C, its square +0x10, set once by fighter_hurt_radii_init) have a
 * size; DR's hits land wider (1, 2, 4's 2 passed 340 from Paul's chest sphere, radius 300, where DR's
 * lands). While a player is on one of his DR pack's records, his opponent's spheres are that much wider,
 * set again each frame (the recompiled hit test, attack_capsules_test, runs in pieces: a wrap round it
 * put the radii back before the spheres were tested), and their own sizes back otherwise. */
static struct {unsigned generation;int attempted,reach;} reaches[2];
static struct {int applied;uint16_t base[14];} widened[2];
static int reach_for(unsigned p) {
    unsigned generation=tekken3_guest_moves_generation(p);
    if(reaches[p].generation!=generation || !reaches[p].attempted) {
        reaches[p].generation=generation;reaches[p].attempted=1;reaches[p].reach=0;
        const char *root=tekken3_ttt1_asset_root(),*prefix=tekken3_guest_moves_prefix_for(p);
        char path[4096];
        FILE *f=root && prefix && snprintf(path,sizeof path,"%s/%s-reach.txt",root,prefix)<(int)sizeof path?fopen(path,"r"):NULL;
        if(f){if(fscanf(f,"%d",&reaches[p].reach)!=1 || reaches[p].reach<0 || reaches[p].reach>300)reaches[p].reach=0;fclose(f);}
    }
    return reaches[p].reach;
}
static void reach_step(unsigned state) {
    for(unsigned p=0;p<2;p++) {
        uint32_t me=ACTOR0+p*ACTOR_SIZE,them=ACTOR0+(p^1)*ACTOR_SIZE;
        int reach=state==8 && tekken3_ttt1_record_index(p,psx_mod_read_word(me+0x54))>=0?reach_for(p):0;
        int was=widened[p^1].applied;
        if(reach==was)continue;
        for(int i=0;i<14;i++) {
            uint32_t at=them+0x20c+i*20;
            uint16_t r=psx_mod_read_half(at+0xc);
            if(!was)widened[p^1].base[i]=r;                   /* the sizes the game gave */
            int base=widened[p^1].base[i],v=base?base+reach:0;
            psx_mod_write_half(at+0xc,(uint16_t)v);psx_mod_write_word(at+0x10,(uint32_t)(v*v));
        }
        widened[p^1].applied=reach;
    }
}

/* DR's hand poses (B3, the user's choice of 2026-10-29: Devil Jin keeps a half-closed claw in his stance,
 * the guests' gauge closed it). <prefix>-hands.bin beside a DR character's pack (tools/psp/dr_pack.py
 * hands()): per pack record the frames where DR sets a hand pose (move properties 0x814A..0x814D), each
 * already the model's own: version 2 its pose index (0 open .. 16 DR's guard claw, tools/psp/dr_pack.py
 * HAND_STEPS), version 1 one of four levels (0 open .. 3 fist), 255 leaving that hand. A pose stays until
 * another record sets one, as in DR (a jab carries none). tekken3_dr_hand gives the pose of hand h (0: row
 * 13) or -1 when the player has no such file (the guests' gauge then); tekken3_dr_hand_indexed says whether
 * it is the table's index (version 2) or a level the closest pose stands for. Levels 0..3 showed the
 * model's poses 0..3 of 16, all nearly open: the stance's claw had straight fingers (the user, 2026-11-01). */
static struct {unsigned generation;int attempted;uint8_t *data;uint32_t size,count,steps;
               int record,frame;uint8_t level[2];} hands[2];
int tekken3_dr_hand(unsigned p,unsigned h) {
    if(p>1 || h>1)return -1;
    unsigned generation=tekken3_guest_moves_generation(p);
    if(hands[p].generation!=generation || !hands[p].attempted) {
        free(hands[p].data);
        memset(&hands[p],0,sizeof hands[p]);
        hands[p].generation=generation;hands[p].attempted=1;hands[p].record=-1;
        hands[p].steps=3;hands[p].level[0]=hands[p].level[1]=3;
        const char *root=tekken3_ttt1_asset_root(),*prefix=tekken3_guest_moves_prefix_for(p);
        char path[4096];
        FILE *f=root && prefix && snprintf(path,sizeof path,"%s/%s-hands.bin",root,prefix)<(int)sizeof path?fopen(path,"rb"):NULL;
        if(f) {
            fseek(f,0,SEEK_END);long n=ftell(f);fseek(f,0,SEEK_SET);
            uint8_t *d=n>=12 && n<(1<<20)?malloc((size_t)n):NULL;
            uint32_t count;
            if(d && fread(d,1,(size_t)n,f)==(size_t)n && !memcmp(d,"JHD1",4) &&
               (memcpy(&count,d+8,4),12+4ull*count<=(uint64_t)n)) {
                hands[p].data=d;hands[p].size=(uint32_t)n;hands[p].count=count;
                uint32_t version;memcpy(&version,d+4,4);
                if(version==2)hands[p].steps=16,hands[p].level[0]=hands[p].level[1]=16;
            } else free(d);
            fclose(f);
        }
    }
    if(!hands[p].data)return -1;
    uint32_t me=ACTOR0+p*ACTOR_SIZE;
    int record=tekken3_ttt1_record_index(p,psx_mod_read_word(me+0x54));
    int frame=(int)psx_mod_read_half(me+0x58);
    if(record!=hands[p].record || frame<hands[p].frame)hands[p].frame=-1;  /* a new record, or the same again */
    hands[p].record=record;
    if(record>=0 && (uint32_t)record<hands[p].count) {
        uint32_t at;memcpy(&at,hands[p].data+12+4*record,4);
        if(at && at+2<=hands[p].size) {
            uint16_t n;memcpy(&n,hands[p].data+at,2);
            for(uint32_t i=0;i<n && at+2+4*i+4<=hands[p].size;i++) {
                const uint8_t *e=hands[p].data+at+2+4*i;
                if(e[0]>frame || e[0]<=hands[p].frame)continue;      /* not yet, or applied already */
                if(e[1]<=hands[p].steps)hands[p].level[0]=e[1];
                if(e[2]<=hands[p].steps)hands[p].level[1]=e[2];
            }
        }
    }
    hands[p].frame=frame;
    return hands[p].level[h];
}
int tekken3_dr_hand_indexed(unsigned p) { return p<2 && hands[p].data && hands[p].steps==16; }

/* DR's own reactions on a victim in the air (B3, the user's review of 2026-10-31): <prefix>-air.txt beside
 * a DR pack (tools/psp/dr_pack.py AIR_OWN), lines "attack reaction", both records of the pack. DR gives a
 * victim hit in the air its own reaction by condition 289 (Spinning Demon's 2nd hit: aDw_ym_y01L, the
 * falling victim spun up), Tekken 3 its computed fall (reaction_air 0x8002EE94: face up). The juggles'
 * common falls are left to Tekken 3; the file names the spinning lifts only. tekken3_dr_air_reaction gives
 * the reaction record of player p's current record, -1 when it has none. */
static struct {unsigned generation;int attempted;unsigned count;uint16_t attack[64],reaction[64];} airs[2];
int tekken3_dr_air_reaction(unsigned p) {
    if(p>1)return -1;
    unsigned generation=tekken3_guest_moves_generation(p);
    if(airs[p].generation!=generation || !airs[p].attempted) {
        memset(&airs[p],0,sizeof airs[p]);
        airs[p].generation=generation;airs[p].attempted=1;
        const char *root=tekken3_ttt1_asset_root(),*prefix=tekken3_guest_moves_prefix_for(p);
        char path[4096];
        FILE *f=root && prefix && snprintf(path,sizeof path,"%s/%s-air.txt",root,prefix)<(int)sizeof path?fopen(path,"r"):NULL;
        if(f) {
            unsigned a,r;
            while(airs[p].count<64 && fscanf(f,"%u %u",&a,&r)==2 && a<4096 && r<4096) {
                airs[p].attack[airs[p].count]=(uint16_t)a;airs[p].reaction[airs[p].count++]=(uint16_t)r;
            }
            fclose(f);
        }
    }
    int record=tekken3_ttt1_record_index(p,psx_mod_read_word(ACTOR0+p*ACTOR_SIZE+0x54));
    for(unsigned i=0;record>=0 && i<airs[p].count;i++)if(airs[p].attack[i]==(unsigned)record)return airs[p].reaction[i];
    return -1;
}

/* A victim leaving a DR pack's reaction for one of Tekken 3's own states keeps its body where it was
 * (the user, 2026-10-31). DR turns the fighter by its reaction's last yaw at that change (Jin's WS+3:
 * sDm_ROL00LD ends with the body a quarter turn from the fighter's facing, DR's heading went -137 to
 * 133 at dwDWN_00U); Tekken 3's lying state is drawn on the facing as it was, and Jin, lying, turned
 * 94 degrees at once as he started to get up (hips -90 to 176, measured on the bones). The body's
 * yaw is read on the bones (+0x908 + 68 * bone: hips 12 and 15) each frame; at the change, the facing
 * (+0x2C, +0x0E) turns by the jump, 20 degrees or more, and Tekken 3's own get-up turns it to the
 * opponent from there. */
static struct {int on_reaction,yaw,valid,facing,dir;} reaction_ends[2];
static int body_yaw(uint32_t actor) {
    uint32_t a=actor+0x908+12*68,b=actor+0x908+15*68;
    int32_t dx=(int32_t)psx_mod_read_word(b)-(int32_t)psx_mod_read_word(a),dz=(int32_t)psx_mod_read_word(b+8)-(int32_t)psx_mod_read_word(a+8);
    if(!dx && !dz)return 0x7fffffff;
    return (int)lround(atan2((double)dx,(double)dz)*32768.0/M_PI);
}
static void reaction_end_step(unsigned state) {
    for(unsigned p=0;p<2;p++) {
        uint32_t them=ACTOR0+(p^1)*ACTOR_SIZE;
        const char *prefix=tekken3_guest_moves_prefix_for(p);
        int on=state==8 && prefix && strstr(prefix,"-DR") && tekken3_ttt1_record_index(p,psx_mod_read_word(them+0x54))>=0;
        int yaw=state==8?body_yaw(them):0x7fffffff;
        if(state==8 && reaction_ends[p].on_reaction && !on &&
           reaction_ends[p].valid && yaw!=0x7fffffff) {
            int jump=(int16_t)(uint16_t)(yaw-reaction_ends[p].yaw);
            if(jump>=0x0e39 || jump<=-0x0e39) {
                uint16_t turn=(uint16_t)-jump;
                psx_mod_write_half(them+0x2c,(uint16_t)(psx_mod_read_half(them+0x2c)+turn));
                psx_mod_write_half(them+0x0e,(uint16_t)(psx_mod_read_half(them+0x0e)+turn));
                reaction_ends[p].facing=90;
                int off=(int16_t)(uint16_t)(psx_mod_read_half(them+0x2c)-psx_mod_read_half(them+0x2a));
                reaction_ends[p].dir=(off>=0x4000 || off<=-0x4000)==(off>0)?1:-1;
                if(getenv("TEKKEN3_DR_REACTION_END_LOG"))fprintf(stderr,"DR reaction end: P%u turned %d\n",(p^1)+1,(int)(int16_t)turn);
            }
        }
        /* Then the get-up turns to the opponent, not to the nearer side: lying a quarter turn and more
         * from him, Tekken 3 stood Jin up with his back to him. DR's roll up (cOKI_R0, sOKI_R0) turns
         * the body as much, by its back: lying, DR's heading goes on away from him (-147 to -172, then
         * sOKI_R1 turns round), so more than a quarter turn off it turns the long way, by the back (Jin
         * got up turning by the right, DR's by the left: the user, 2026-10-31); less, the short way.
         * Until he faces him, 90 frames at most, or a reaction again. */
        if(on || state!=8)reaction_ends[p].facing=0;
        if(reaction_ends[p].facing>0) {
            uint16_t opp=psx_mod_read_half(them+0x2a);
            int off=(int16_t)(uint16_t)(psx_mod_read_half(them+0x2c)-opp);
            if(off<0x16c && off>-0x16c)reaction_ends[p].facing=0;
            else {
                int rest=reaction_ends[p].dir>0?(uint16_t)-off:(uint16_t)off;
                int step=reaction_ends[p].dir*(rest<0x500?rest:0x500);
                uint16_t rot=(uint16_t)(psx_mod_read_half(them+0x2c)+step);
                psx_mod_write_half(them+0x2c,rot);psx_mod_write_half(them+0x0e,rot);psx_mod_write_half(them+0x34,opp);
                reaction_ends[p].facing--;
            }
        }
        reaction_ends[p].on_reaction=on;reaction_ends[p].yaw=yaw;reaction_ends[p].valid=yaw!=0x7fffffff;
    }
}

/* DR's push on a victim hit in the air (the user, 2026-10-31): <prefix>-airpush.txt beside a DR pack
 * (tools/psp/dr_pack.py AIR_PUSH), lines "attack curve", the curve an index (halfwords) of the pack's
 * pushback table. Tekken 3 moves a victim hit in the air by its arc's horizontal speed (+0x98, set by
 * reaction_air_arc_setup from the damage and the hits taken), DR adds its hit entry's condition 289 push
 * (Demolition Man's last hit: 35 frames at 30, then 150 ... 30; DR's Jin flew 3150 after it, Tekken
 * 3's 1170). tekken3_dr_air_push gives the curve of player p's current record, -1 when it has none. */
static struct {unsigned generation;int attempted;unsigned count;uint16_t attack[64],curve[64];} air_pushes[2];
int tekken3_dr_air_push(unsigned p) {
    if(p>1)return -1;
    unsigned generation=tekken3_guest_moves_generation(p);
    if(air_pushes[p].generation!=generation || !air_pushes[p].attempted) {
        memset(&air_pushes[p],0,sizeof air_pushes[p]);
        air_pushes[p].generation=generation;air_pushes[p].attempted=1;
        const char *root=tekken3_ttt1_asset_root(),*prefix=tekken3_guest_moves_prefix_for(p);
        char path[4096];
        FILE *f=root && prefix && snprintf(path,sizeof path,"%s/%s-airpush.txt",root,prefix)<(int)sizeof path?fopen(path,"r"):NULL;
        if(f) {
            unsigned a,c;
            while(air_pushes[p].count<64 && fscanf(f,"%u %u",&a,&c)==2 && a<4096 && c<0x8000) {
                air_pushes[p].attack[air_pushes[p].count]=(uint16_t)a;air_pushes[p].curve[air_pushes[p].count++]=(uint16_t)c;
            }
            fclose(f);
        }
    }
    int record=tekken3_ttt1_record_index(p,psx_mod_read_word(ACTOR0+p*ACTOR_SIZE+0x54));
    for(unsigned i=0;record>=0 && i<air_pushes[p].count;i++)if(air_pushes[p].attack[i]==(unsigned)record)return air_pushes[p].curve[i];
    return -1;
}

/* Each frame: a victim whose hits in the air (+0x94) went up while its opponent hits on an AIRPUSH
 * record (its frame at or past the record's first active, +0x54 -> +0x2D: the previous move's hit
 * can land on the record's first frame) gets that push on its arc's speed, spread over the curve's
 * frames (frames x velocity plus eight steps, over frames + 8). Not the push curve (+0x106..+0x110):
 * the arc is set twice for a hit, a hook round reaction_air_arc_setup came before the second, and a
 * second hit in the air did not move the victim by it. */
extern uint32_t tekken3_ttt1_push_base(void);
extern unsigned tekken3_ttt1_push_shift(unsigned s);
static int16_t air_hits_seen[2];
static void air_push_step(unsigned state) {
    for(unsigned p=0;p<2;p++) {
        uint32_t me=ACTOR0+p*ACTOR_SIZE,them=ACTOR0+(p^1)*ACTOR_SIZE;
        int16_t hits=(int16_t)psx_mod_read_half(them+0x94);
        if(state!=8 || !psx_mod_read_half(them+0x92)){air_hits_seen[p^1]=0;continue;}
        if(hits<=air_hits_seen[p^1])continue;
        air_hits_seen[p^1]=hits;
        int v=tekken3_dr_air_push(p);
        if(v<0)continue;
        uint32_t info=psx_mod_read_word(me+0x54);
        int frame=(int16_t)psx_mod_read_half(me+0x58),first=psx_mod_read_byte(info+0x2d);
        if(!first || frame<first)continue;
        if((unsigned)v*2>=0xce8-0x75c)v+=(int)(tekken3_ttt1_push_shift(p)/2);
        uint32_t curve=tekken3_ttt1_push_base()+(uint32_t)v*2;
        int n=(int16_t)psx_mod_read_half(curve),total=n*(int16_t)psx_mod_read_half(curve+2);
        for(unsigned k=0;k<8;k++)total+=(int16_t)psx_mod_read_half(curve+4+2*k);
        if(n+8<=0 || total<=0)continue;
        psx_mod_write_half(them+0x98,(uint16_t)((int16_t)psx_mod_read_half(them+0x98)+total/(n+8)));
    }
}
