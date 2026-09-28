/* Game-owned, independently selectable cosmetic packs. */
#include "mod_plugins.h"
#include "gpu_gl_renderer.h"
#include "tekken3_outfits.h"
#include "psx_sdl.h"
#include <stdio.h>
static void activate_skin(int skin, const char *folder) {
    const char *base = SDL_GetBasePath();
    if (!base) return;
    char path[1024];
    int n = snprintf(path, sizeof path, "%smods/%s", base, folder);
    if (n > 0 && n < (int)sizeof path) gl_renderer_set_character_texture_pack(skin, path);
#if !defined(PSX_SDL3)
    SDL_free((void *)base);
#endif
}
static void eddy(void) { activate_skin(T3_SKIN_EDDY, "eddy-monochrome"); }
static void julia(void) { activate_skin(T3_SKIN_JULIA, "julia-blue"); }
static void heihachi(void) { activate_skin(T3_SKIN_HEIHACHI, "heihachi-tiger-coat"); }
PSX_MOD_CONSTRUCTOR(tekken3_register_new_skins) {
    psx_mod_register_activation_plugin("tekken3.eddy-monochrome", eddy);
    psx_mod_register_activation_plugin("tekken3.julia-blue", julia);
    psx_mod_register_activation_plugin("tekken3.heihachi-tiger-coat", heihachi);
}
