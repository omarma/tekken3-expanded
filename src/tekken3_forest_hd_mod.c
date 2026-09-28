/* Trusted renderer-only mod; no guest memory or disc writes. */
#include "mod_plugins.h"
#include "gpu_gl_renderer.h"
#include "psx_sdl.h"
#include <stdio.h>
static void tekken3_forest_hd_activate(void) {
    const char *base = SDL_GetBasePath();
    if (base) {
        char path[1024];
        int n = snprintf(path, sizeof path, "%smods/forest-hd", base);
        if (n > 0 && n < (int)sizeof path) gl_renderer_set_hd_texture_pack(path);
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
}
PSX_MOD_CONSTRUCTOR(tekken3_register_forest_hd) {
    (void)psx_mod_register_activation_plugin("tekken3.forest-hd", tekken3_forest_hd_activate);
}
