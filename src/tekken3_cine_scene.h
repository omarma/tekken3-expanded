#pragma once
#ifdef __cplusplus
extern "C" {
#endif
/* Every VBlank: 1 runs the guest unpaced (a cinematic's black loading, the
 * way back to the title after it), -1 holds the pace (the cinematic, the
 * title after it), 0 leaves it to the fast-loading mod. */
int tekken3_cine_scene_turbo(void);
#ifdef __cplusplus
}
#endif
