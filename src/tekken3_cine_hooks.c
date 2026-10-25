/* The game's hooks of the cinematic engine (src/tekken3_cine.c): the TTT
 * Cinematics feature's activation (its trigger table, mods/ttt-cinematics/
 * triggers.txt, src/tekken3_cine_trigger.c), the Arcade's ending handed to
 * that table, and the wrappers of the game's routines a cinematic draws,
 * films and records through. The old way (Ogre's cutscene played with our
 * script, clips added to the .jmv packs, environment variables from
 * cinematics.txt, TIPS.md sections 57, 68, 69) is gone: section 130. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include <stdio.h>

extern int tekken3_cine_engine_active(void);
extern int tekken3_cine_engine_frame(void);
extern int tekken3_cine_camera(int16_t eye[3],int16_t target[3]);
extern void tekken3_cine_record_camera(const int32_t view[6]);
extern void tekken3_cine_test_tick(void);
extern void tekken3_cine_scene_tick(void);
extern int tekken3_cine_scene_loading(void);
/* A cinematic's frame while the engine plays one, -1 otherwise. */
int tekken3_cine_frame(void) { return tekken3_cine_engine_active()?tekken3_cine_engine_frame():-1; }
/* A cinematic playing, or its scene loading (its fighters' models and moves
 * are the cinematic's from the loading on). */
int tekken3_cine_pending(void) { return tekken3_cine_engine_active() || tekken3_cine_scene_loading(); }

/* After "P1 wins" the Arcade asks for state 19 (the ending) through state
 * 18, whose handler (0x8004FF74) queues the ending overlay and goes on to
 * the target at 0x80097F38. The trigger table first: an ending it plays
 * skips the handler (src/tekken3_cine_trigger.c, the credits after it). */
extern int tekken3_cine_trigger_arcade_end(void);
extern void tekken3_cine_trigger_tick(unsigned state);
extern void __real_func_8004FF74(CPUState *cpu);
void __wrap_func_8004FF74(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8004ff74) && tekken3_cine_trigger_arcade_end()) { cpu->pc=cpu->gpr[31]; return; }
    __real_func_8004FF74(cpu);
}

/* A captured ending's camera often looks where a Tekken 3 arena has nothing
 * (the PS2 temples are far larger): nothing covers those pixels and the
 * previous frames stay on screen, the actors leaving trails. While a
 * cinematic plays, a black tile goes to the far end of the display list
 * before the arena draws (0x8006D7CC, every frame, the OT ready): what the
 * arena leaves out shows black. The game does the same in True Ogre's dark
 * arena (0x80048374: a tile linked at OT[1023]); the tile is the fade's,
 * 368 x 480 from 0,0 (0x8004E000). */
/* The fade tile (0x8004E000: a0 the display list entry it links at, a1 its
 * buffer, a2 the level) goes in front of everything while a cinematic
 * plays: at the entry the cinematic's frame passes, polygons right at the
 * camera (King's mask in a close-up) were drawn over the white flash. OT[0],
 * the list's last entry, is drawn last. */
extern void __real_func_8004E000(CPUState *cpu);
void __wrap_func_8004E000(CPUState *cpu) {
    if((cpu->pc==0 || cpu->pc==0x8004e000) && tekken3_cine_engine_active()) {
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
     * fill tiles, src/tekken3_cine.c) must come after the tile to show;
     * linked before, the tile covered it. */
    __real_func_8006D7CC(cpu);
    if((cpu->pc==0 || cpu->pc==0x8006d7cc) && tekken3_cine_engine_active()) {
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

/* The cinematic's camera goes straight to the view: 0x80063EEC (called from
 * 0x80066A18) builds it from the eye (a1..a3) and the target (the caller's
 * stack, +20 / +24 / +28), in stage coordinates, after the camera object
 * has turned, moved and scaled them; giving it the cinematic's eye and
 * target bypasses all that. The view given is recorded (TEKKEN3_CINE_RECORD). */
extern void __real_func_80063EEC(CPUState *cpu);
void __wrap_func_80063EEC(CPUState *cpu) {
    int16_t eye[3],target[3];
    if((cpu->pc==0 || cpu->pc==0x80063eec) && tekken3_cine_engine_active()) {
        if(tekken3_cine_camera(eye,target))
            for(unsigned k=0;k<3;k++) {
                cpu->gpr[5+k]=(uint32_t)(int32_t)eye[k];
                psx_mod_write_word(cpu->gpr[29]+20+k*4,(uint32_t)(int32_t)target[k]);
            }
    }
    if((cpu->pc==0 || cpu->pc==0x80063eec) && tekken3_cine_frame()>=0) {
        int32_t view[6];
        for(unsigned k=0;k<3;k++) { view[k]=(int32_t)cpu->gpr[5+k]; view[3+k]=(int32_t)psx_mod_read_word(cpu->gpr[29]+20+k*4); }
        tekken3_cine_record_camera(view);
    }
    __real_func_80063EEC(cpu);
}

/* Every frame (embu_tick, src/tekken3_ttt1_mod.c). */
void tekken3_cine_hooks_tick(void) {
    unsigned state=psx_mod_read_word(0x800ae204);
    tekken3_cine_trigger_tick(state);
    tekken3_cine_test_tick();
    tekken3_cine_scene_tick();
}

/* The TTT Cinematics feature: the trigger table mods/ttt-cinematics/
 * triggers.txt (tools/ttt_cinematics.py) beside the TTT1 catalogue. */
extern const char *tekken3_ttt1_asset_root(void);
extern int tekken3_cine_triggers_load(const char *dir);
static void activate_cinematics(void) {
    static int done;
    const char *root=tekken3_ttt1_asset_root();
    char dir[4096];
    if(done || !root || snprintf(dir,sizeof dir,"%s/../ttt-cinematics",root)>=(int)sizeof dir) return;
    if(tekken3_cine_triggers_load(dir)) { done=1; return; }
    fprintf(stderr,"TTT Cinematics: no %s/triggers.txt (run the setup with the TTT endings)\n",dir);
}
PSX_MOD_CONSTRUCTOR(register_ttt_cinematics) {
    (void)psx_mod_register_activation_plugin("tekken3.ttt-cinematics",activate_cinematics);
}
