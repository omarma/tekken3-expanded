/* Our cutscenes in a fight: the Tekken Tag Tournament (PS2) endings of
 * Kazuya and Armor King, in place of their Arcade ending movies (the TTT
 * Cinematics feature, tools/ttt_cinematics.py). Ported from the attract-mode Embu's tools (branch
 * endings-release), which keeps the capture and conversion tools.
 *
 * The feature's activation reads mods/ttt-cinematics/cinematics.txt beside the TTT1
 * catalogue: KEY=VALUE lines, $DIR standing for that folder. Each becomes an
 * environment variable unless already set, so a test can still set them:
 * TEKKEN3_ENDING, TEKKEN3_FIGHT_CINE, TEKKEN3_EMBU_CAMERA_TRACK,
 * TEKKEN3_EMBU_FADE, TEKKEN3_EMBU_MUSIC, TEKKEN3_EMBU_MODEL_P2,
 * TEKKEN3_EMBU_EFFECT_P1 / _P2 / _LIGHT, TEKKEN3_ENDING_PACKS (below). */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* A cinematic's frame: a fight's cutscene (state 8, phase 17: Ogre taking
 * Heihachi in, or one of ours, TEKKEN3_FIGHT_CINE) at its counter
 * 0x800B4A54, after our pre-roll; -1 otherwise. */
static int fight_cine, cine_preroll;
int tekken3_cine_frame(void) {
    if(psx_mod_read_word(0x800ae204)==8 && fight_cine && psx_mod_read_half(0x800ae224)==17) {
        int frame=(int)psx_mod_read_word(0x800b4a54)-cine_preroll;
        return frame<0?-1:frame;
    }
    return -1;
}

/* TEKKEN3_FIGHT_CINE: "script@delay", a cutscene of ours in an Arcade fight
 * (prototype: `delay` frames into its first round). The fight's phase
 * machine (0x80050D00, phase 0x800AE224) plays Ogre's cutscene as phases
 * 16 (0x800B3CA0: the player's actor becomes Heihachi, both actors at the
 * origin turned 0x4000, the script pointer 0x800B4A4C set) and 17
 * (0x800B4060 each frame, done at the script's -1 record). Its script is
 * the Embu's format, (frame, cmd, arg, start, end) halfwords: cmd 2 / 3
 * player 1 / 2 plays move arg from frame start to end, 5 a fade, 6 a
 * sound. Both functions are the Arcade overlay's, interpreted: their code
 * words are rewritten while ours runs, the script pointer to our copy,
 * the change to Heihachi dropped; then phase 16. The script file: one
 * record a line, five integers, ended by a -1 record (added a frame after
 * the last if missing). */
enum { CINE_MAX=512 };
static const uint32_t cine_words[][2]={
    {0x800b3d90,0x3c02800bu},{0x800b3d94,0x24420728u},{0x800b3dc8,0x0c00d87bu},
    {0x800b3e70,0x3c02800bu},{0x800b3e74,0x2442075cu},{0x800b3ea8,0x0c00d87bu},
    {0x800b4380,0x02c02021u},{0x800b449c,0x0c01b5f3u},{0x800b40d8,0x24060200u}};
enum { CINE_WORDS=sizeof cine_words/sizeof *cine_words };
/* The tick never runs the hit effects (0x8007745C(1), which the Embu's and
 * the fight's own loops call each frame): Jin's lightning was spawned but
 * never drawn. A trampoline where Ogre's scripts lie (0x800B0728: unused
 * while ours plays, put back after) calls it before the tick's own
 * 0x8006D7CC, whose call is sent there. */
enum { TRAMPOLINE=0x800b0728 };
static const uint32_t trampoline[]={
    0x27bdffe8u,            /* addiu sp, sp, -24 */
    0xafbf0010u,            /* sw ra, 16(sp) */
    0x0c01dd17u,            /* jal 0x8007745C */
    0x24040001u,            /* addiu a0, zero, 1 */
    0x0c01b5f3u,            /* jal 0x8006D7CC */
    0x00000000u,            /* nop */
    0x8fbf0010u,            /* lw ra, 16(sp) */
    0x03e00008u,            /* jr ra */
    0x27bd0018u};           /* addiu sp, sp, 24 */
enum { TRAMPOLINE_WORDS=sizeof trampoline/sizeof *trampoline };
static uint32_t ogre_scripts[TRAMPOLINE_WORDS];
/* TEKKEN3_ENDING="P1:P2:ARENA[:DARK]", P1 and P2 character IDs or guest keys
 * (tools/data/ttt1_characters.json): the Arcade P1 finishes plays our cutscene
 * (TEKKEN3_FIGHT_CINE "script@ending") instead of its ending movie, in the
 * same fight, with P2 reloaded as our cutscene's partner and the ending's
 * own arena (a fighter record's byte 10; Kazuya's: Ogre's temple, 6),
 * dark (2) as in True Ogre's fight or lit (0, the default). After "P1 wins" the Arcade asks for state 19 (the ending)
 * through state 18, whose handler (0x8004FF74) queues the ending overlay
 * and goes on to the target at 0x80097F38. Stage 1: that handler is
 * skipped and the fight goes back to its phase 19, the way Ogre's cutscene
 * ends: 0x8002960C(0), then phase 20 writes True Ogre in the opponent list
 * (0x800B2870) and reloads the opponent from it in place (0x8004F3B0,
 * 0x8002A40C: made our partner below), phases 5 and 7;
 * our cutscene starts as the round begins, on a pre-roll of black frames
 * (see fight_cine_tick). Stage 2, once it is over: state 18 again towards 19; the ending
 * state's phase 2 plays movie 0x800ADC94 (0x800FDC78, `jal` at 0x800FF2CC,
 * ending overlay) then starts the credits: the call is dropped. */
static int ending_p1=-2, ending_p2, ending_arena=-1, ending_dark, ending_stage, cine_in_round;
/* The endings table: cinematics.txt sections "[ending KEY]", one per
 * character whose Arcade ends on a cutscene, each with its own TEKKEN3_*
 * lines (explicit settings per ending, never taken from the fight). The
 * one whose P1 finishes the Arcade is selected as its ending starts: its
 * lines go to the environment and every reader of them reads again
 * (cine_reset). TEKKEN3_ENDING already in the environment (a test) defines
 * a single ending from the environment instead, the sections ignored. */
enum { ENDINGS_MAX=8 };
static struct { char key[32]; char lines[4096]; int p1,p2; } endings[ENDINGS_MAX];
static int ending_count, ending_selected=-1;
extern int tekken3_guest_id(const char *key);
extern int tekken3_t3_key_id(const char *key);
static int character(const char *token) {
    if(*token>='0' && *token<='9') return atoi(token);
    int id=tekken3_guest_id(token);
    return id>=0?id:tekken3_t3_key_id(token);        /* a native partner (King) by its key */
}
static void ending_parse(void) {
    if(ending_p1!=-2) return;
    const char *e=getenv("TEKKEN3_ENDING");
    char p1[32],p2[32];
    ending_p1=-1;
    if(!e || sscanf(e,"%31[^:]:%31[^:]:%d:%d",p1,p2,&ending_arena,&ending_dark)<3) return;
    /* Guest keys before the roster is read: asked again later. */
    if((ending_p1=character(p1))<0 || (ending_p2=character(p2))<0) { ending_p1=-2; return; }
    fprintf(stderr,"Ending: P1 %d's Arcade ends on a cutscene with %d, arena %d%s\n",
            ending_p1,ending_p2,ending_arena,ending_dark?", dark":"");
}
/* The table's ending for this character as P1, -1 for none (keys resolved
 * once the roster is read). */
static int ending_for(unsigned id) {
    for(int i=0;i<ending_count;i++) {
        if(endings[i].p1==-2) {
            const char *e=strstr(endings[i].lines,"\nTEKKEN3_ENDING=");
            char p1[32],p2[32];
            if(!e || sscanf(e+16,"%31[^:]:%31[^:]",p1,p2)<2) { endings[i].p1=-1; continue; }
            int a=character(p1),b=character(p2);
            if(a<0 || b<0) continue;
            endings[i].p1=a; endings[i].p2=b;
        }
        if(endings[i].p1==(int)id) return i;
    }
    return -1;
}
static void cine_reset(void);
static void select_ending(int i) {
    char *lines=strdup(endings[i].lines);
    if(!lines) return;
    for(char *l=strtok(lines,"\n");l;l=strtok(NULL,"\n")) {
        char *eq=strchr(l,'=');
        if(!eq) continue;
        *eq=0;
#ifdef _WIN32
        _putenv_s(l,eq+1);
#else
        setenv(l,eq+1,1);
#endif
    }
    free(lines);
    ending_p1=-2; ending_parse();
    cine_reset();
    ending_selected=i;
    fprintf(stderr,"TTT Cinematics: %s's ending selected\n",endings[i].key);
}
int tekken3_cine_pending(void) { return ending_stage==1 || fight_cine || cine_in_round; }
/* Whether a player's guest takes its ending pack (TEKKEN3_ENDING_PACKS, read
 * by src/tekken3_ttt1_combat.c) rather than the catalogue's. P1 always: its
 * pack is read as soon as the selector's cursor is on the guest, before any
 * mode or pick is known, and its clips must be there when stage 10 is won,
 * without a reload; the extra records are inert outside the script. P2 only
 * once reloaded as the ending's partner: the CPU drawing Kazuya or Devil
 * keeps the catalogue's (B30). */
int tekken3_ending_pack_wanted(unsigned player) {
    ending_parse();
    if(ending_p1<0 && !ending_count) return 0;
    return player==0 || (player==1 && ending_stage==1);
}
extern void __real_func_8004FF74(CPUState *cpu);
void __wrap_func_8004FF74(CPUState *cpu) {
    if(cpu->pc==0 || cpu->pc==0x8004ff74) {
        ending_parse();
        /* The table's ending of the character who finishes the Arcade. */
        int e=ending_count && !ending_stage?ending_for(psx_mod_read_half(0x800add5c)):-1;
        if(e>=0 && e!=ending_selected) select_ending(e);
        /* Only the Arcade's own ending, stage 10 cleared (its index, from 0,
         * already moved on to 10): nothing else that goes through state 18
         * towards 19 is touched. */
        if(ending_p1>=0 && !ending_stage && psx_mod_read_byte(0x80097f38)==19 &&
           psx_mod_read_byte(0x800afa88)==0 && psx_mod_read_byte(0x800afaac)==10 &&
           psx_mod_read_half(0x800add5c)==(unsigned)ending_p1 &&
           psx_mod_read_word(0x800b2870)==0x24020014u) {
            psx_mod_write_half(0x800ae204,8); psx_mod_write_half(0x800ae224,19);
            ending_stage=1;
            fprintf(stderr,"Ending: P2 reloaded as %d in the fight, instead of the ending movie\n",ending_p2);
            cpu->pc=cpu->gpr[31];
            return;
        }
    }
    __real_func_8004FF74(cpu);
}
static void ending_tick(unsigned state) {
    /* The reload takes the arena 0x800ADC84 names (else its new opponent's):
     * the ending's own, whatever the last fight's was. */
    if(ending_stage==1 && !fight_cine) {
        psx_mod_write_byte(0x800adc84,(uint8_t)ending_arena); psx_mod_write_byte(0x800afaa2,(uint8_t)ending_arena);
    }
    /* The arena's dark look, True Ogre's fight's (0x800AFAA0 = 2: only the
     * floor drawn, 0x8006D7CC), or its lit one (0). */
    if(ending_stage==1) psx_mod_write_byte(0x800afaa0,(uint8_t)ending_dark);
    /* The fill tiles the fight draws its background with (0x8009E738, four
     * 16-byte tiles: two 368 x 480 frames and two lower bands) keep the
     * colour of the fight that loaded them: True Ogre's black after his
     * fight, the sky of King's stage left black in Armor King's ending. The
     * arena's own colour (0x80097A64 + 4 * arena, 0x00BBGGRR, as a fight's
     * loading sets it), black for a dark arena. Once the cutscene runs (its
     * pre-roll is black): earlier, the "YOU WIN" screen of the last fight
     * turned blue on its last frame. */
    if(ending_stage==1 && fight_cine && ending_arena>=0 && ending_arena<14) {
        uint32_t colour=ending_dark?0:psx_mod_read_word(0x80097a64+(uint32_t)ending_arena*4)&0x00ffffffu;
        for(unsigned i=0;i<4;i++) psx_mod_write_word(0x8009e73cu+i*16,0x60000000u|colour);
    }
    if(ending_stage==2 && state==19 && psx_mod_read_half(0x800ae224)<=2 && psx_mod_read_word(0x800ff2cc)==0x0c03f71eu) {
        psx_mod_write_code_word(0x800ff2cc,0);
        fprintf(stderr,"Ending: no ending movie, the credits\n");
    }
    /* The credits started (phase 3): everything back as the game has it,
     * the movie call too, the mod armed for the next Arcade. */
    if(ending_stage==2 && state==19 && psx_mod_read_half(0x800ae224)>=3) {
        if(!psx_mod_read_word(0x800ff2cc)) psx_mod_write_code_word(0x800ff2cc,0x0c03f71eu);
        ending_stage=0;
        fprintf(stderr,"Ending: credits, all back to normal\n");
    }
}
/* Phase 20's reload (0x8002A40C: P1, ?, P1's costume, P2 in a3, ?, P2's
 * costume at sp+20) reads P2 from the opponent list, whose byte takes
 * natives only: P2 becomes our partner there, a guest the roster follows. */
extern void tekken3_guest_follow(unsigned player,unsigned id,unsigned costume);
extern void tekken3_native_moves_reload(unsigned player,unsigned id);
extern int tekken3_native_moves_force(unsigned player,unsigned id);
extern void __real_func_8002A40C(CPUState *cpu);
void __wrap_func_8002A40C(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8002a40c) && ending_stage==1 && !fight_cine) {
        cpu->gpr[7]=(uint32_t)ending_p2;
        psx_mod_write_word(cpu->gpr[29]+20,0);
        psx_mod_write_half(0x800add5e,(uint16_t)ending_p2); psx_mod_write_half(0x800add9a,0);
        psx_mod_write_byte(0x800adc84,(uint8_t)ending_arena); psx_mod_write_byte(0x800afaa2,(uint8_t)ending_arena);
        tekken3_guest_follow(1,(unsigned)ending_p2,0);
        fprintf(stderr,"Ending: P2 loads as %d\n",ending_p2);
    }
    /* The moves each fighter fights on, chosen again for a new one (the
     * TTT1 moveset the CPU drew for Ogre would stay on True Ogre, or on
     * our partner: Ogre's model with its textures). */
    if(cpu->pc==0 || cpu->pc==0x8002a40c) {
        tekken3_native_moves_reload(0,cpu->gpr[4]&0xffff);
        tekken3_native_moves_reload(1,cpu->gpr[7]&0xffff);
        /* The ending's native partner (King beside Armor King) on its TTT1
         * moves: the ending's clips are in its TTT1 pack, played on its own
         * model and skeleton. */
        if(ending_stage==1 && ending_p2>=0 && ending_p2<23 && !tekken3_native_moves_force(1,(unsigned)ending_p2))
            fprintf(stderr,"Ending: no TTT1 moves for native %d (natives.txt, <Key>-TTT1-combat.jmv)\n",ending_p2);
    }
    __real_func_8002A40C(cpu);
}
/* Our cutscene over, the Arcade's ending goes on (see above). */
static void ending_resume(void) {
    ending_stage=2;
    psx_mod_write_byte(0x80097f38,19); psx_mod_write_byte(0x80097f39,8);
    psx_mod_write_half(0x800ae224,0); psx_mod_write_half(0x800ae204,18);
    fprintf(stderr,"Ending: cutscene over, on to the credits\n");
}

static int parsed_cine, cine_delay=-1, cine_count, cine_armed, cine_running;
static int16_t cine_script[CINE_MAX][5];
static uint32_t cine_copy;
static void fight_cine_tick(unsigned state) {
#define delay cine_delay
#define count cine_count
#define armed cine_armed
#define running cine_running
#define script cine_script
#define copy cine_copy
    if(!parsed_cine) {
        parsed_cine=1;
        const char *e=getenv("TEKKEN3_FIGHT_CINE"), *at=e?strrchr(e,'@'):NULL;
        if(!at) return;
        char path[1024]; size_t n=(size_t)(at-e)<sizeof path-1?(size_t)(at-e):sizeof path-1;
        memcpy(path,e,n); path[n]=0;
        ending_parse();
        FILE *f=fopen(path,"r"); int v[5];
        if(!f) return;
        while(count<CINE_MAX-1 && fscanf(f,"%d %d %d %d %d",&v[0],&v[1],&v[2],&v[3],&v[4])==5) {
            for(int k=0;k<5;k++) script[count][k]=(int16_t)v[k];
            count++;
        }
        fclose(f);
        if(!count) return;
        if(script[count-1][1]!=-1) {                   /* ended by a -1 record, a frame after the last */
            script[count][0]=(int16_t)(script[count-1][0]+1); script[count][1]=-1;
            script[count][2]=script[count][3]=script[count][4]=0; count++;
        }
        delay=strcmp(at+1,"ending")?atoi(at+1):0;
        cine_in_round=delay>0;
        fprintf(stderr,"Fight cinematic: %d records from %s, %s\n",count,path,delay?"a delay into the round":"at the Arcade's end");
    }
    if(delay<0) return;
    unsigned phase=psx_mod_read_half(0x800ae224);
    if(running) {
        /* Once its camera timeline (0x800670FC, Ogre's) is over, the tick
         * stores that at 0x800B4A80 and follows player 2 (0x800630D8)
         * instead, a path that never reaches our track: keep it on. */
        if(state==8 && (phase==16 || phase==17)) {
            psx_mod_write_word(0x800b4a80,0);
            /* A white flash (the fade at 256) sets 0x800B4A88, and from then
             * on the arena's background sprites (King's clouds, mountains,
             * ropes) are no longer drawn: Ogre's cutscene turning to True
             * Ogre's dark temple. Not in ours. */
            psx_mod_write_word(0x800b4a88,0);
            int counter=(int)psx_mod_read_word(0x800b4a54);
            if(phase==17 && counter<cine_preroll) {
                /* Black (the cutscene's own fade tile) while it rolls in; its
                 * first record waits for P2's guest moves (table and record
                 * in the guests' pool). */
                psx_mod_write_word(0x800b4a5c,1); psx_mod_write_word(0x800b4a60,(uint32_t)-256); psx_mod_write_word(0x800b4a64,0);
                uint32_t moves=psx_mod_read_word(0x800adc24),record=psx_mod_read_word(0x800aaab4+0x54);
                if(counter>=cine_preroll-2 && (moves<0x9f000000u || moves>=0x9f400000u || record<0x9f000000u || record>=0x9f400000u))
                    psx_mod_write_word(0x800b4a54,(uint32_t)(cine_preroll-3));
            }
            /* Timed properties (0x800458C8) fire between an actor's previous
             * frame (+0x5A) and its current one (+0x58). The fight's loop
             * keeps +0x5A (0x80029760), the Embu's too; this tick does not:
             * it stayed where the round left it, the lightning of a chunk's
             * first frames never fired and the rest fired every frame. */
            for(unsigned p=0;p<2;p++) {
                uint32_t actor=0x800a9228+p*0x188c;
                psx_mod_write_half(actor+0x5a,psx_mod_read_half(actor+0x58));
            }
            return;
        }
        for(unsigned i=0;i<CINE_WORDS;i++) psx_mod_write_code_word(cine_words[i][0],cine_words[i][1]);
        for(unsigned i=0;i<TRAMPOLINE_WORDS;i++) psx_mod_write_code_word(TRAMPOLINE+i*4,ogre_scripts[i]);
        running=0; fight_cine=0;
        fprintf(stderr,"Fight cinematic: over (state %u, phase %u)\n",state,phase);
        if(ending_stage==1) ending_resume();
        return;
    }
    if(!delay) {
        /* The Arcade's ending: on the round's first frame (phase 7; before
         * it the game neither flips its frames nor shows the display, which
         * the reload turned off), before its intro ("FINAL ROUND") can show.
         * The actors go on initialising for a while (guest graft, moves): a
         * pre-roll of black frames first, the script played after it. */
        if(ending_stage!=1 || state!=8 || phase<7 || phase>8) return;
        cine_preroll=90;
    } else {
        cine_preroll=0;
        if(state!=8 || phase!=8) { armed=0; return; }
        if(++armed<delay || armed>delay) return;
    }
    for(unsigned i=0;i<CINE_WORDS;i++) if(psx_mod_read_word(cine_words[i][0])!=cine_words[i][1]) {
        fprintf(stderr,"Fight cinematic: not the Arcade overlay (%08X at %08X)\n",psx_mod_read_word(cine_words[i][0]),cine_words[i][0]);
        return;
    }
    if(!copy && !(copy=psx_mod_alloc_guest_memory(CINE_MAX*10,4))) return;
    for(int i=0;i<count;i++) for(int k=0;k<5;k++)
        psx_mod_write_half(copy+(uint32_t)(i*10+k*2),(uint16_t)(script[i][k]+(k==0?cine_preroll:0)));
    for(unsigned side=0;side<2;side++) {
        psx_mod_write_code_word(side?0x800b3e70:0x800b3d90,0x3c020000u|(copy>>16));           /* lui v0, hi */
        psx_mod_write_code_word(side?0x800b3e74:0x800b3d94,0x34420000u|(copy&0xffff));        /* ori v0, v0, lo */
        psx_mod_write_code_word(side?0x800b3ea8:0x800b3dc8,0);                                 /* no Heihachi */
    }
    /* Each frame the tick runs the timed properties (0x800458C8) of both
     * actors with player 1's (`addu a0, s6, zero`): Ogre's cutscene has
     * none. Give each actor its own (s3), or Jin's lightning never fires. */
    psx_mod_write_code_word(0x800b4380,0x02602021u);
    /* Its end (state 2, after the -1 record) draws two frames of the fade
     * tile at 512, white (Ogre's flash into True Ogre), which stayed on
     * screen while the ending overlay loaded: black instead. */
    psx_mod_write_code_word(0x800b40d8,0x24060000u);
    for(unsigned i=0;i<TRAMPOLINE_WORDS;i++) {
        ogre_scripts[i]=psx_mod_read_word(TRAMPOLINE+i*4);
        psx_mod_write_code_word(TRAMPOLINE+i*4,trampoline[i]);
    }
    psx_mod_write_code_word(0x800b449c,0x0c000000u|((TRAMPOLINE&0x0fffffffu)>>2));
    psx_mod_write_half(0x800ae224,16);
    running=1; fight_cine=1;
    fprintf(stderr,"Fight cinematic: started, script at %08X\n",copy);
#undef delay
#undef count
#undef armed
#undef running
#undef script
#undef copy
}

/* A captured ending's camera often looks where a Tekken 3 arena has nothing
 * (the PS2 temples are far larger): nothing covers those pixels and the
 * previous frames stay on screen, the actors leaving trails. While our
 * cutscene runs, a black tile goes to the far end of the display list
 * before the arena draws (0x8006D7CC, every frame, the OT ready): what the
 * arena leaves out shows black. The game does the same in True Ogre's dark
 * arena (0x80048374: a tile linked at OT[1023]); the tile is the fade's,
 * 368 x 480 from 0,0 (0x8004E000). */
/* The fade tile (0x8004E000: a0 the display list entry it links at, a1 its
 * buffer, a2 the level) goes in front of everything while a cutscene of ours
 * plays: at the entry the cutscene's tick passes, polygons right at the
 * camera (King's mask in a close-up) were drawn over the white flash. OT[0],
 * the list's last entry, is drawn last. */
extern void __real_func_8004E000(CPUState *cpu);
void __wrap_func_8004E000(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8004e000) && (fight_cine || tekken3_cine_frame()>=0)) {
        uint32_t ot=psx_mod_read_word(psx_mod_read_word(0x800a8c54)+4);
        if(ot>=0x80000000u) cpu->gpr[4]=ot;
    }
    __real_func_8004E000(cpu);
}
static uint32_t cine_clear_tiles;
extern void __real_func_8006D7CC(CPUState *cpu);
void __wrap_func_8006D7CC(CPUState *cpu) {
    /* Linked after the arena drew: a prim goes to the head of its bucket
     * and the DMA walks from the head, so the arena's own background (the
     * fill tiles above) must come after the tile to show; linked before,
     * the tile covered it. */
    __real_func_8006D7CC(cpu);
    if((cpu->pc==0 || cpu->pc==0x8006d7cc) && fight_cine) {
        if(!cine_clear_tiles) cine_clear_tiles=psx_mod_alloc_gpu_dma_memory(32,16);
        uint32_t ot=psx_mod_read_word(psx_mod_read_word(0x800a8c54)+4)+4092;
        uint32_t tile=cine_clear_tiles+16*(psx_mod_read_word(0x800adefc)&1);
        if(cine_clear_tiles && ot>=0x80000000u) {
            psx_mod_write_word(tile+4,0x60000000u);              /* tile, black, opaque */
            psx_mod_write_word(tile+8,0);                        /* 0,0 */
            psx_mod_write_word(tile+12,0x01e00170u);             /* 368 x 480 */
            psx_mod_write_word(tile,(psx_mod_read_word(ot)&0x00ffffffu)|0x03000000u);
            psx_mod_write_word(ot,(psx_mod_read_word(ot)&0xff000000u)|(tile&0x00ffffffu));
        }
    }
}

/* TEKKEN3_EMBU_CAMERA_TRACK: a file, first line the cutscene frame it starts
 * at, then one "ex ey ez tx ty tz" line a frame (an ending captured on the
 * PS2, retargeted on branch endings-release). */
static int16_t (*track)[6];
static int track_start, track_count, track_parsed;
static void parse_track(void) {
    const char *path=getenv("TEKKEN3_EMBU_CAMERA_TRACK");
    FILE *f=path?fopen(path,"r"):NULL;
    if(!f)return;
    int cap=0,v[6];
    if(fscanf(f,"%d",&track_start)!=1){fclose(f);return;}
    while(fscanf(f,"%d %d %d %d %d %d",&v[0],&v[1],&v[2],&v[3],&v[4],&v[5])==6) {
        if(track_count==cap){cap=cap?cap*2:1024;void *m=realloc(track,sizeof *track*(size_t)cap);if(!m)break;track=m;}
        for(unsigned k=0;k<6;k++)track[track_count][k]=(int16_t)v[k];
        track_count++;
    }
    fclose(f);
    fprintf(stderr,"Cutscene camera: track of %d frames from frame %d\n",track_count,track_start);
}

/* A captured track goes straight to the view: 0x80063EEC (called from
 * 0x80066A18) builds it from the eye (a1..a3) and the target (the caller's
 * stack, +20 / +24 / +28), in stage coordinates, after the camera object
 * has turned, moved and scaled them; giving it the captured eye and target
 * bypasses all that. */
extern void __real_func_80063EEC(CPUState *cpu);
void __wrap_func_80063EEC(CPUState *cpu) {
    int frame=(cpu->pc==0 || cpu->pc==0x80063eec)?tekken3_cine_frame():-1;
    if(frame>=0) {
        if(!track_parsed){track_parsed=1;parse_track();}
        if(track_count && frame>=track_start && frame<track_start+track_count) {
            const int16_t *c=track[frame-track_start];
            for(unsigned k=0;k<3;k++) {
                cpu->gpr[5+k]=(uint32_t)(int32_t)c[k];
                psx_mod_write_word(cpu->gpr[29]+20+k*4,(uint32_t)(int32_t)c[3+k]);
            }
        }
    }
    __real_func_80063EEC(cpu);
}

/* A fight cutscene's full-screen fade (0x800B4060: 0x800B4A5C switch,
 * 0x800B4A60 level, 0x800B4A64 step), drawn by 0x8004E000 as a 368 x 480
 * tile: level 0..255 subtracts 255 - level (0 is black), 256..511 adds
 * level - 256 (511 is white).
 * TEKKEN3_EMBU_FADE: "from-to:a:b;..." in cutscene frames
 * (tekken3_cine_frame), the level going from a to b over the span, -256
 * black, 0 the plain image, 256 white; outside the spans the switch is left
 * off. */
typedef struct { int from,to,a,b; } Fade;
enum { FADES_MAX=64 };          /* a captured ending's fades: a few segments each */
static Fade fades[FADES_MAX];
static int fade_count=-1, fade_on;
static void fade_tick(void) {
    if(fade_count<0) {
        fade_count=0;
        const char *e=getenv("TEKKEN3_EMBU_FADE");
        while(e && *e && fade_count<FADES_MAX) {
            Fade f;
            if(sscanf(e,"%d-%d:%d:%d",&f.from,&f.to,&f.a,&f.b)==4) fades[fade_count++]=f;
            e=strchr(e,';'); if(e) e++;
        }
    }
    if(!fade_count) return;
    int frame=tekken3_cine_frame();
    const uint32_t words=0x800b4a5c;
    for(int i=0;i<fade_count && frame>=0;i++) {
        const Fade *f=&fades[i];
        if(frame<f->from || frame>f->to) continue;
        int level=f->to>f->from ? f->a+(f->b-f->a)*(frame-f->from)/(f->to-f->from) : f->b;
        if(level<-255) level=-256;
        if(level>256) level=256;
        psx_mod_write_word(words,1);
        psx_mod_write_word(words+4,(uint32_t)level);
        psx_mod_write_word(words+8,0);
        fade_on=(int)words;
        return;
    }
    if(fade_on) { psx_mod_write_word((uint32_t)fade_on,0); fade_on=0; }
}

/* TEKKEN3_EMBU_MUSIC: "file@frame", raw 16-bit little-endian stereo PCM at
 * 44 100 Hz (the host mix rate) played from that cutscene frame to its end
 * or the cutscene's (TTT's endings' music, tools/ttt_cinematics.py). Mixed by
 * the TTT1 voices' spu_render wrapper at the host's music volume, following
 * the fade (a level below 0 dims it); the game's own music is muted from
 * the cutscene's first frame to its end. Returns whether to mute it. */
static int16_t *music;
static uint32_t music_frames, music_pos;
static int music_from=-2;
int tekken3_embu_music_mix(int16_t *out,int frames,int audible,int gain) {
    if(music_from==-2) {
        music_from=-1;
        const char *e=getenv("TEKKEN3_EMBU_MUSIC"), *at=e?strrchr(e,'@'):NULL;
        if(at) {
            char path[1024]; size_t n=(size_t)(at-e)<sizeof path-1?(size_t)(at-e):sizeof path-1;
            memcpy(path,e,n); path[n]=0;
            FILE *f=fopen(path,"rb");
            if(f) {
                fseek(f,0,SEEK_END); long size=ftell(f); fseek(f,0,SEEK_SET);
                music=malloc((size_t)size);
                if(music && fread(music,1,(size_t)size,f)==(size_t)size) {
                    music_frames=(uint32_t)(size/4); music_from=atoi(at+1);
                }
                fclose(f);
            }
            fprintf(stderr,"Cutscene music: %s, %u frames from frame %d\n",path,music_frames,music_from);
        }
    }
    if(music_from<0) return 0;
    int frame=tekken3_cine_frame();
    /* A fight's cutscene of ours mutes the round's music from its first
     * (pre-roll) frame, before our own starts. */
    if(frame<0 && fight_cine && psx_mod_read_word(0x800ae204)==8) { music_pos=0; return 1; }
    if(frame<0) { music_pos=0; return 0; }
    if(frame<music_from) return 0;
    if(music_pos>=music_frames) return 1;          /* the game's stays muted to the cutscene's end */
    const uint32_t words=0x800b4a5c;               /* the fade's level */
    int level=psx_mod_read_word(words) ? (int)psx_mod_read_word(words+4) : 0;
    int scale=gain*(level<0 ? (level<-256 ? 0 : level+256) : 256)/256;   /* percent */
    for(int f=0;f<frames && music_pos<music_frames;f++,music_pos++) {
        for(int ch=0;ch<2;ch++) {
            int32_t v=audible ? music[music_pos*2+ch]*scale/200 : 0;
            int32_t mixed=out[f*2+ch]+v;
            out[f*2+ch]=(int16_t)(mixed>32767?32767:mixed< -32768?-32768:mixed);
        }
    }
    return 1;
}

void tekken3_embu_scenes_tick(void) {
    unsigned state=psx_mod_read_word(0x800ae204);
    fade_tick();
    fight_cine_tick(state);
    ending_tick(state);
}

/* Another ending selected: everything read from its TEKKEN3_* lines is
 * read again (the script, the camera track, the fades, the music, the model
 * steps and effect packs of the TTT1 code). */
extern void tekken3_ttt1_embu_models_reset(void);
extern void tekken3_ttt1_embu_effects_reset(void);
static void cine_reset(void) {
    parsed_cine=0; cine_count=0; cine_delay=-1; cine_armed=0;
    track_count=0; track_parsed=0;
    fade_count=-1;
    free(music); music=NULL; music_frames=music_pos=0; music_from=-2;
    tekken3_ttt1_embu_models_reset();
    tekken3_ttt1_embu_effects_reset();
}

/* The TTT Cinematics feature: mods/ttt-cinematics/cinematics.txt (tools/ttt_cinematics.py)
 * beside the TTT1 catalogue, its KEY=VALUE lines made environment variables
 * unless set already, $DIR in a value standing for that folder; a line
 * "[ending KEY]" opens that character's ending, whose lines are kept for
 * its selection (the endings table above). */
extern const char *tekken3_ttt1_asset_root(void);
static void activate_cinematics(void) {
    static int done;
    const char *root=tekken3_ttt1_asset_root();
    char dir[4096],path[4200],line[4096];
    if(done || !root || snprintf(dir,sizeof dir,"%s/../ttt-cinematics",root)>=(int)sizeof dir) return;
    snprintf(path,sizeof path,"%s/cinematics.txt",dir);
    FILE *f=fopen(path,"r");
    if(!f) { fprintf(stderr,"TTT Cinematics: no %s (run the setup with the TTT endings)\n",path); return; }
    done=1;
    int in=-1;
    while(fgets(line,sizeof line,f)) {
        line[strcspn(line,"\r\n")]=0;
        if(line[0]=='[') {
            char key[32];
            in=-1;
            if(sscanf(line,"[ending %31[^]]]",key)==1 && ending_count<ENDINGS_MAX && !getenv("TEKKEN3_ENDING")) {
                in=ending_count++;
                snprintf(endings[in].key,sizeof endings[in].key,"%s",key);
                snprintf(endings[in].lines,sizeof endings[in].lines,"\n");
                endings[in].p1=endings[in].p2=-2;
            }
            continue;
        }
        char *eq=strchr(line,'='), value[8192];
        if(!eq || line[0]=='#') continue;
        *eq=0;
        size_t n=0;
        for(const char *v=eq+1;*v && n<sizeof value-1;) {
            if(!strncmp(v,"$DIR",4)) { n+=(size_t)snprintf(value+n,sizeof value-n,"%s",dir); v+=4; if(n>=sizeof value) n=sizeof value-1; }
            else value[n++]=*v++;
        }
        value[n]=0;
        if(in>=0) {
            size_t have=strlen(endings[in].lines);
            snprintf(endings[in].lines+have,sizeof endings[in].lines-have,"%s=%s\n",line,value);
            continue;
        }
        if(getenv(line)) continue;
#ifdef _WIN32
        _putenv_s(line,value);
#else
        setenv(line,value,0);
#endif
    }
    fclose(f);
    fprintf(stderr,"TTT Cinematics: %s, %d endings\n",path,ending_count);
}
PSX_MOD_CONSTRUCTOR(register_ttt_cinematics) {
    (void)psx_mod_register_activation_plugin("tekken3.ttt-cinematics",activate_cinematics);
}
