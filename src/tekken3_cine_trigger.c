/* The cinematic engine's triggers: a table of events, each playing a .cine
 * file, read from mods/ttt-cinematics/triggers.txt (written by
 * tools/ttt_cinematics.py; docs/CINE-FORMAT.md, "Déclencheurs"). No
 * environment variables: everything an event plays with is in its line and
 * in the .cine itself (arena, dark look, actors), explicit per cinematic,
 * never taken from the fight it interrupts.
 *
 *   triggers 1
 *   arcade-end p1=kazuya cine=kazuya.cine then=credits
 *
 * Played today: arcade-end (player 1 = that character, any costume, wins
 * the Arcade's last stage: the cinematic in place of the ending movie, then
 * the credits) and attract (the attract's Embu, state 6, at its turn of the
 * Embus' rotation: the cinematic in its place, then the title as after the
 * Embu). The others are read and kept, not played yet (a message): boss
 * (before a boss fight), mode-start / mode-end, theater.
 *
 * The engine loads the scene itself (src/tekken3_cine_scene.c,
 * tekken3_cine_play_scene: arena and actors from the .cine, then it puts
 * back the mode, fighters and arena it found); this file only chooses the
 * cinematic and what comes after it. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "tekken3_arcade_stages.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { TRIGGERS_MAX=32, CINE_SCENE_BLACK=1 };
typedef enum { EV_ARCADE_END, EV_BOSS, EV_MODE_START, EV_MODE_END, EV_ATTRACT, EV_THEATER, EV_COUNT } Event;
static const char *const event_names[EV_COUNT]={"arcade-end","boss","mode-start","mode-end","attract","theater"};
typedef enum { THEN_CREDITS, THEN_ATTRACT } Then;
typedef struct {
    Event event;
    char p1[32];            /* character key or ID, "" any */
    int p1_id;              /* resolved, -2 not yet, -1 any */
    char mode[16];          /* reserved events: arcade, survival… */
    int stage, slot;        /* reserved events: boss stage, attract / theater slot (-1 any) */
    int every, seen;        /* attract: one Embu in `every`, from the first; Embus seen so far */
    int rotation;           /* attract: the TTT Embu of the Embus' rotation (2..4, its place before B104; 0 none; see state_leave_to) */
    char cine[1024];        /* full path */
    Then then;
} Trigger;
static Trigger triggers[TRIGGERS_MAX];
static int trigger_count;

extern int tekken3_guest_id(const char *key);
extern int tekken3_t3_key_id(const char *key);
static int character(const char *token) {
    if(*token>='0' && *token<='9') return atoi(token);
    int id=tekken3_guest_id(token);
    return id>=0?id:tekken3_t3_key_id(token);
}

/* ---- The table ----------------------------------------------------------- */

/* Reads `dir`/triggers.txt; the number of triggers, 0 without the file. */
int tekken3_cine_triggers_load(const char *dir) {
    char path[4200],line[2048];
    snprintf(path,sizeof path,"%s/triggers.txt",dir);
    FILE *f=fopen(path,"r");
    if(!f) return 0;
    int version=0,lineno=0;
    while(fgets(line,sizeof line,f)) {
        lineno++;
        char *hash=strchr(line,'#'); if(hash) *hash=0;
        char *w[16]; int n=0;
        for(char *s=strtok(line," \t\r\n");s && n<16;s=strtok(NULL," \t\r\n")) w[n++]=s;
        if(!n) continue;
        if(!strcmp(w[0],"triggers") && n==2) { version=atoi(w[1]); continue; }
        if(version!=1) { fprintf(stderr,"Cine triggers: %s does not start with \"triggers 1\"\n",path); break; }
        int e=0;
        while(e<EV_COUNT && strcmp(w[0],event_names[e])) e++;
        if(e==EV_COUNT) { fprintf(stderr,"Cine triggers: %s line %d: event \"%s\" ignored\n",path,lineno,w[0]); continue; }
        if(trigger_count==TRIGGERS_MAX) { fprintf(stderr,"Cine triggers: more than %d, line %d on ignored\n",TRIGGERS_MAX,lineno); break; }
        Trigger *t=&triggers[trigger_count];
        memset(t,0,sizeof *t);
        t->event=(Event)e; t->p1_id=-2; t->then=e==EV_ARCADE_END?THEN_CREDITS:THEN_ATTRACT;
        t->slot=-1; t->every=1;
        int ok=1;
        for(int k=1;k<n;k++) {
            char *eq=strchr(w[k],'=');
            if(!eq) { ok=0; break; }
            *eq=0; const char *v=eq+1;
            if(!strcmp(w[k],"p1")) snprintf(t->p1,sizeof t->p1,"%s",strcmp(v,"*")?v:"");
            else if(!strcmp(w[k],"cine")) snprintf(t->cine,sizeof t->cine,"%s/%s",dir,v);
            else if(!strcmp(w[k],"then")) {
                if(!strcmp(v,"credits")) t->then=THEN_CREDITS;
                else if(!strcmp(v,"attract")) t->then=THEN_ATTRACT;
                else ok=0;
            }
            else if(!strcmp(w[k],"mode")) snprintf(t->mode,sizeof t->mode,"%s",v);
            else if(!strcmp(w[k],"stage")) t->stage=atoi(v);
            else if(!strcmp(w[k],"slot")) t->slot=atoi(v);
            else if(!strcmp(w[k],"every")) t->every=atoi(v)>0?atoi(v):1;
            else if(!strcmp(w[k],"rotation")) { t->rotation=atoi(v); if(t->rotation<2 || t->rotation>4) ok=0; }
            else fprintf(stderr,"Cine triggers: %s line %d: \"%s\" ignored\n",path,lineno,w[k]);
        }
        if(!ok || !t->cine[0]) { fprintf(stderr,"Cine triggers: %s line %d: bad trigger\n",path,lineno); continue; }
        if(!t->p1[0]) t->p1_id=-1;
        if(t->event!=EV_ARCADE_END && t->event!=EV_ATTRACT)
            fprintf(stderr,"Cine triggers: line %d, \"%s\": not played yet\n",lineno,event_names[t->event]);
        trigger_count++;
    }
    fclose(f);
    fprintf(stderr,"Cine triggers: %s, %d triggers\n",path,trigger_count);
    return trigger_count;
}

/* The first trigger of `event` whose player 1 is `p1` (keys resolved once
 * the roster is read), -1 for none. */
static int find(Event event,unsigned p1) {
    for(int i=0;i<trigger_count;i++) {
        Trigger *t=&triggers[i];
        if(t->event!=event) continue;
        if(t->p1_id==-2 && (t->p1_id=character(t->p1))<0) { t->p1_id=-2; continue; }   /* not known yet */
        if(t->p1_id<0 || t->p1_id==(int)p1) return i;
    }
    return -1;
}

/* ---- What comes after ---------------------------------------------------- */

extern int tekken3_cine_prepare(const char *path);
extern int tekken3_cine_play_scene(const char *path,int flags,void (*on_done)(void));

static const Trigger *active;       /* from the trigger to the end of what follows */
static int credits;                 /* 1: on the way to the credits */

/* The Arcade's ending goes on as after its movie: state 18 towards 19, the
 * ending state; its phase 2 would play the movie (0x800FDC78, its `jal` at
 * 0x800FF2CC in the ending overlay): that call is dropped (credits_tick),
 * then put back once the credits run. The mode is the Arcade's again (the
 * scene put it back). */
static void to_credits(void) {
    fprintf(stderr,"Cine trigger: \"%s\" over, the credits\n",active?active->cine:"?");
    credits=1;
    psx_mod_write_byte(0x80097f38,19); psx_mod_write_byte(0x80097f39,8);
    psx_mod_write_half(0x800ae224,0); psx_mod_write_half(0x800ae204,18);
}
static void credits_tick(unsigned state) {
    if(!credits || state!=19) return;
    unsigned phase=psx_mod_read_half(0x800ae224);
    if(phase<=2 && psx_mod_read_word(0x800ff2cc)==0x0c03f71eu) {
        psx_mod_write_code_word(0x800ff2cc,0);
        fprintf(stderr,"Cine trigger: no ending movie\n");
    }
    if(phase>=3) {
        if(!psx_mod_read_word(0x800ff2cc)) psx_mod_write_code_word(0x800ff2cc,0x0c03f71eu);
        credits=0; active=NULL;
        fprintf(stderr,"Cine trigger: credits, all back to normal\n");
    }
}
/* The attract, as a demo fight ends: what the scene does without on_done
 * (src/tekken3_cine_scene.c, finished), +2 cleared too; straight to the
 * title, as T3's Embu ends on it (its phases 6-7). The attract's cycle
 * 0x80097F3E (after the title: 0 the intro video, 1 the Embu, 2 a shorter
 * video, 3 the title alone) chooses what state 3 shows: the Embu took it at
 * 1, which played the whole intro ("Namco presents") again. At 3, state 2
 * (0x8004FA60, phase 0) goes the short way, the title without a video; once
 * it is over (state 3 left), the cycle is put at 2, where T3's Embu leaves
 * it, for the attract to go on as after T3's own Embu. */
enum { CYCLE=0x80097f3e, CYCLE_TITLE=3, CYCLE_AFTER_EMBU=2 };
static int titled;                  /* 1: the title after a cinematic, the cycle to put back */
static void to_attract(void) {
    active=NULL;
    psx_mod_write_byte(0x80097f38,3); psx_mod_write_byte(0x80097f39,8); psx_mod_write_byte(0x80097f3a,0);
    psx_mod_write_byte(CYCLE,CYCLE_TITLE); titled=1;
    psx_mod_write_half(0x800ae224,0); psx_mod_write_half(0x800ae204,2);
}
/* The game left the scene (Start: the modes menu, src/tekken3_cine_scene.c):
 * neither the title nor the credits follow, the next trigger can play. */
void tekken3_cine_trigger_left(void) { active=NULL; }
static void title_tick(unsigned state) {
    static unsigned before;
    if(titled && before==3 && state!=3) { psx_mod_write_byte(CYCLE,CYCLE_AFTER_EMBU); titled=0; }
    before=state;
}

/* The wrapper of 0x8004FF74 (state 18, its target at 0x80097F38) asks: the
 * Arcade's own ending (target 19, mode 0, stage 10 cleared, the Arcade
 * overlay), player 1 with a trigger. 1 if taken: the handler is skipped. */
int tekken3_cine_trigger_arcade_end(void) {
    if(!trigger_count || active || psx_mod_read_byte(0x80097f38)!=19 || psx_mod_read_byte(0x800afa88)!=0 ||
       psx_mod_read_byte(0x800afaac)!=10 || psx_mod_read_word(0x800b2870)!=0x24020014u) return 0;
    unsigned p1=psx_mod_read_half(0x800add5c);
    int i=find(EV_ARCADE_END,p1);
    if(i<0) return 0;
    const Trigger *t=&triggers[i];
    if(!tekken3_cine_prepare(t->cine)) { fprintf(stderr,"Cine trigger: %s cannot be played, the ending movie\n",t->cine); return 0; }
    active=t;
    /* No loading screen: the last fight's "YOU WIN" goes to black. */
    if(!tekken3_cine_play_scene(NULL,CINE_SCENE_BLACK,t->then==THEN_CREDITS?to_credits:to_attract)) {
        fprintf(stderr,"Cine trigger: %s could not load its scene, the ending movie\n",t->cine);
        active=NULL; return 0;
    }
    fprintf(stderr,"Cine trigger: arcade-end, player 1 %u: %s\n",p1,t->cine);
    return 1;
}

/* The attract's Embu (state 6, TIPS § 28): its variant is the byte
 * 0x80097F20 (the save's, unlock_chars +0x30), the file 0x45 + variant its
 * script. 0x8004F8F8(3), the way back to the title (also from the modes
 * menu left alone), turns it: when the attract's cycle (0x80097F3E) makes
 * this return the Embu, variant + 1, back to 0 past the save's tier (+0x2F:
 * 0 under 15 characters, 1 from 15, 2 with Dr. B), so 0 / 0-1 / 0-1-2. L1,
 * R1, L1 + R1 held (pad 0x800ADD68: 4, 8, 12, alone) with a tier above 0:
 * variant 1, 0, 2 if the tier allows it, and the Embu at once.
 * With the mod's Embus (the TTT Embu, a trigger with rotation=, and the
 * guests' Embu, variant 0 with the Embu TTT casting: B104, GH#155) the
 * rotation is ours, in the user's order: TTT, guests, variant 2, 0, 1. A
 * turn not there is skipped: the TTT Embu without its stage (TTT Stages
 * off) or its .cine, the guests' without a casting, a variant past the
 * tier. Ours is chosen on the way back, the variant byte written as state
 * 2 starts (before it loads the files): the byte never holds anything the
 * game does not know (0 for the TTT Embu). The next turn follows the save
 * (<card>-embu-rotation.txt: read when the card is read, written when it
 * is written, with the variant it goes with); a new one starts with TTT.
 * L1 / R1 / L1 + R1: the game's variant, the turn kept. L2 alone held on
 * the way back: the TTT Embu at once, any tier, then the guests'. Without
 * either Embu of the mod (mod off) nothing changes.
 * Other triggers (slot= that variant, or none: any; every=N: one Embu in N,
 * the first one included) take the Embu as it comes. The cinematic plays
 * from the Embu's first frame (nothing of it drawn yet: the scene goes to
 * state 7 at once, the image black while it loads); the title follows as
 * after the Embu (to_attract: the title through state 2). */
enum { TARGET=0x80097f38, TIER=0x80097f1f, VARIANT=0x80097f20, PAD_HELD=0x800add68, PAD_L2=0x0001 };
typedef enum { TURN_TTT, TURN_GUESTS, TURN_V2, TURN_V0, TURN_V1, TURNS } Turn;
static const char *const turn_keys[TURNS]={"ttt","guests","v2","v0","v1"};
static const unsigned turn_variant[TURNS]={0,0,2,0,1};
extern int tekken3_cine_ttt_stage(void);
extern int tekken3_card_file(char *out,size_t size,const char *suffix,int shared);
extern int tekken3_ttt1_embu_cast_active(void);
static int next_turn=-1;            /* the next turn to try; -1 unknown (a new save: TTT) */
static int guests_turn;             /* 1: the Embu playing is the guests' */
static const Trigger *planned;      /* chosen by the way back, played as state 6 starts */

static const Trigger *rotation_trigger(void) {
    for(int i=0;i<trigger_count;i++)
        if(triggers[i].event==EV_ATTRACT && triggers[i].rotation) return &triggers[i];
    return NULL;
}
/* Prepared and its TTT stage there (asked, then let go: forced as it plays). */
static int playable(const Trigger *t) {
    if(!tekken3_cine_prepare(t->cine)) { fprintf(stderr,"Cine trigger: %s cannot be played, the Embu\n",t->cine); return 0; }
    int stage=tekken3_cine_ttt_stage();
    if(stage<0) return 1;
    if(!tekken3_ttt_stage_force(stage)) { fprintf(stderr,"Cine trigger: TTT stage %d unavailable, the game's own Embu\n",stage); return 0; }
    tekken3_ttt_stage_force(-1);
    return 1;
}
/* The next turn there from next_turn on, -1 for none; the .cine (1.4 MB)
 * only read when the TTT Embu's turn comes. */
static int pick(unsigned tier) {
    const Trigger *t=rotation_trigger();
    if(next_turn<0) next_turn=TURN_TTT;
    for(int k=0;k<TURNS;k++) {
        Turn u=(Turn)((next_turn+k)%TURNS);
        int there=u==TURN_TTT?t && playable(t):u==TURN_GUESTS?tekken3_ttt1_embu_cast_active():turn_variant[u]<=tier;
        if(there) { next_turn=(u+1)%TURNS; return u; }
    }
    return -1;
}
int tekken3_embu_guests_turn(void) { return guests_turn; }

/* Called as 0x8004F8F8 is (on each dispatch: the call resumes inside it
 * after display_freeze, and ends in pieces of its own); a0 = the state it
 * leaves to, read on entry. Its choice (target 0x80097F38, variant) is read
 * as state 2 (0x8004FA60), which it always enters, starts: before state 2
 * loads the Embu's files (embu_loader_files, file 0x45 + variant). */
static int leave_seen,leave_turn=-1,leave_l2;
extern void __real_func_8004F8F8(CPUState *cpu);
void __wrap_func_8004F8F8(CPUState *cpu) {
    const Trigger *t=rotation_trigger();
    if((cpu->pc==0 || cpu->pc==0x8004f8f8) && cpu->gpr[4]==3 && !active && (t || tekken3_ttt1_embu_cast_active())) {
        unsigned tier=psx_mod_read_byte(TIER),pad=psx_mod_read_half(PAD_HELD);
        /* L1 / R1 / L1 + R1 taken by the game (its variant within the tier): kept. */
        int forced=tier && ((pad==4 && tier>=1) || pad==8 || (pad==12 && tier>=2));
        leave_l2=pad==PAD_L2 && t && playable(t);
        /* Only a return the Embu takes (the cycle at 1, or L2) chooses a turn. */
        leave_turn=leave_l2?TURN_TTT:!forced && psx_mod_read_byte(CYCLE)==1?pick(tier):-1;
        if(leave_l2) { psx_mod_write_byte(CYCLE,1); next_turn=TURN_GUESTS; }   /* the Embu now, as L1 / R1 do */
        leave_seen=1;
    }
    __real_func_8004F8F8(cpu);
}
extern void __real_func_8004FA60(CPUState *cpu);
void __wrap_func_8004FA60(CPUState *cpu) {
    if(leave_seen && (cpu->pc==0 || cpu->pc==0x8004fa60)) {
        leave_seen=0;
        if(psx_mod_read_byte(TARGET)==6) {
            unsigned variant=psx_mod_read_byte(VARIANT);
            guests_turn=leave_turn==TURN_GUESTS;
            if(leave_turn>=0) {
                psx_mod_write_byte(VARIANT,(uint8_t)turn_variant[leave_turn]);
                if(leave_turn==TURN_TTT) planned=rotation_trigger();
                fprintf(stderr,"Cine trigger: Embu rotation, %s%s (variant %u put at %u)\n",
                        leave_turn==TURN_TTT?planned->cine:turn_keys[leave_turn],leave_l2?" (L2)":"",
                        variant,turn_variant[leave_turn]);
            } else
                fprintf(stderr,"Cine trigger: Embu rotation, the game's variant %u (L1 / R1)\n",variant);
        }
        leave_turn=-1;
    }
    __real_func_8004FA60(cpu);
}

/* The card's file: the boot's read starts from nothing (the EXE's variant
 * 0), a read takes the file if it goes with the card's variant, a write
 * writes it (src/tekken3_ttt1_records.c calls these). Before B104 the file
 * held "ttt-next N variant V": not read, the rotation starts again. */
void tekken3_embu_rotation_forget(void) { next_turn=-1; }
void tekken3_embu_rotation_load(void) {
    char path[1024],key[16]; unsigned with;
    next_turn=-1;
    if(!tekken3_card_file(path,sizeof path,"embu-rotation.txt",0)) return;
    FILE *f=fopen(path,"r");
    if(!f) return;
    if(fscanf(f,"next %15s variant %u",key,&with)==2 && with==psx_mod_read_byte(VARIANT))
        for(int u=0;u<TURNS;u++) if(!strcmp(key,turn_keys[u])) next_turn=u;
    fclose(f);
    fprintf(stderr,"Cine trigger: Embu rotation from %s: %s\n",path,next_turn<0?"not this card's":turn_keys[next_turn]);
}
void tekken3_embu_rotation_save(void) {
    char path[1024];
    if(next_turn<0 || !tekken3_card_file(path,sizeof path,"embu-rotation.txt",0)) return;
    FILE *f=fopen(path,"w");
    if(!f) { fprintf(stderr,"Cine trigger: cannot write %s\n",path); return; }
    fprintf(f,"next %s variant %u\n",turn_keys[next_turn],psx_mod_read_byte(VARIANT));
    fclose(f);
}

static void play(const Trigger *t,unsigned variant) {
    /* A cinematic on a TTT arcade stage (`ttt-stage`) without it (TTT
     * Stages off, no pack, no upper VRAM): the game's own Embu. */
    int stage=tekken3_cine_ttt_stage();
    if(stage>=0 && !tekken3_ttt_stage_force(stage)) {
        fprintf(stderr,"Cine trigger: TTT stage %d unavailable, the game's own Embu\n",stage); return;
    }
    active=t;
    if(!tekken3_cine_play_scene(NULL,CINE_SCENE_BLACK,t->then==THEN_CREDITS?to_credits:to_attract)) {
        fprintf(stderr,"Cine trigger: %s could not load its scene, the Embu\n",t->cine);
        if(stage>=0) tekken3_ttt_stage_force(-1);
        active=NULL; return;
    }
    fprintf(stderr,"Cine trigger: attract, Embu variant %u: %s\n",variant,t->cine);
}
static void attract_tick(unsigned state) {
    static unsigned before;
    int entered=state==6 && before!=6;
    before=state;
    if(!entered || !trigger_count || active) return;
    unsigned variant=psx_mod_read_byte(VARIANT);
    if(planned) {
        const Trigger *t=planned; planned=NULL;
        play(t,variant);
        return;
    }
    for(int i=0;i<trigger_count;i++) {
        Trigger *t=&triggers[i];
        if(t->event!=EV_ATTRACT || t->rotation || (t->slot>=0 && t->slot!=(int)variant)) continue;
        if(t->seen++%t->every) { fprintf(stderr,"Cine trigger: attract, the game's own Embu this time\n"); return; }
        if(!tekken3_cine_prepare(t->cine)) { fprintf(stderr,"Cine trigger: %s cannot be played, the Embu\n",t->cine); return; }
        play(t,variant);
        return;
    }
}

void tekken3_cine_trigger_tick(unsigned state) { credits_tick(state); title_tick(state); attract_tick(state); }
