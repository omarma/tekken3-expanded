/* The stage engine (src/tekken3_arcade_stages.c): Tekken 3 arcade's stages
 * and Tekken Tag Tournament arcade's, drawn in place of the PS1 stage.
 * Entries for the cinematics (TTT Stages S3, TIPS.md section 112), on the
 * emulation thread (a cinematic's per-frame code, a function hook). */
#ifndef TEKKEN3_ARCADE_STAGES_H
#define TEKKEN3_ARCADE_STAGES_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Draw TTT stage `stage` (0..14, TTT's numbers: 4 = Hwoarang's temple) from
 * now on, whatever the STAGES row says and outside the fights too (the
 * Embu's state 6, cinematics), wherever the PS1 draws an arena stage: it
 * replaces that arena's stage. Returns 1 when it will be drawn; 0
 * "unavailable": the TTT Stages feature off, its pack missing or bad, or no
 * upper VRAM half (psx_mod_gpu_high_vram_ready(), e.g. Vulkan): nothing is
 * forced and the caller keeps its own behaviour. -1 releases it (returns 1).
 * Forced, stage 4's storm makes no flash of its own: tekken3_ttt_stage_flash
 * drives it. The caller releases it when its scene ends. */
int tekken3_ttt_stage_force(int stage);

/* The upper VRAM half the loaded stage holds: a value that changes with each
 * stage pack loaded or freed, and whether rectangle x, y, w, h (y 512..1023)
 * overlaps what it uploaded or moves there. TTT Hitspark places TTT1's common
 * sparks around it. */
unsigned tekken3_stage_high_vram_generation(void);
int tekken3_stage_high_vram_used(int x, int y, int w, int h);

/* Stage 4's storm: a lightning flash of `type` 0..5 (0-2 lit clouds, 3-5 a
 * visible bolt; 4 runs into 5) starting at this frame (the stage's next
 * drawing): lit sky, light on the fighters, thunder, as TTT's 0x8015C2A8
 * plays it. `type | TEKKEN3_TTT_FLASH_QUIET`: the same flash without its
 * thunder (the PS2 Embu's flashes are silent). Returns 1 if taken; 0
 * "unavailable" (the same rules as tekken3_ttt_stage_force, or TTT stage 4 is
 * neither forced nor drawn, or a type out of range). */
#define TEKKEN3_TTT_FLASH_QUIET 0x100
int tekken3_ttt_stage_flash(int type);

/* A TTT stage's floor: a grid of 15 x 15 cells (19 500 units across on stage
 * 4) centred on the fighters' middle, enough in a fight; a cinematic's camera
 * far from them sees its edge (the Embu's balustrades, nothing at their
 * foot). `on`: the grid centred on world x, z from now on (no shift along the
 * camera's yaw) with its 8 neighbours a whole grid away (seamless), only the
 * cells within |x|, |z| <= `half` (the stage's courtyard; 0: no limit); the
 * floor's light still from the fighters. 0: the game's floor again, as
 * tekken3_ttt_stage_force(-1) does. */
void tekken3_ttt_floor_centre(int on, int x, int z, int half);

/* B126: TTT stage 11's wind this frame, x and z (world, 4096 = 1), or 0:
 * none (another stage, or not drawn). TTT pulls the accessory bones in the
 * air sideways by it times their gravity / 256. */
int tekken3_ttt_stage_wind(int wind[2]);

/* B87: the T3 arcade stage drawn (0..12, the PS1 arena), or -1: none, a TTT
 * stage, the PS1's own. For src/tekken3_arcade_cameras.c, which gives that
 * stage the arcade's K.O., replay and winner cameras. */
int tekken3_arcade_stages_t3_stage(void);

/* The thunder's mixer, called by the spu_render wrapper
 * (src/tekken3_ttt1_voices.c) with the TTT1 sounds; stop: a reset of the
 * SPU or a save state loaded. */
void tekken3_arcade_stages_thunder_mix(int16_t *out, int frames, int audible, const int16_t main_volume[2], int gain);
void tekken3_arcade_stages_thunder_stop(void);

#ifdef __cplusplus
}
#endif
#endif
