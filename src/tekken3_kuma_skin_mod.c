/* Polar-bear fur is a host texture pack selected independently per player. */
#include "mod_plugins.h"
#include "gpu_gl_renderer.h"
#include "psx_sdl.h"
#include <stdio.h>
static void tekken3_kuma_skin_activate(void) {
    const char *base = SDL_GetBasePath();
    if (base) {
        char path[1024];
        int n = snprintf(path, sizeof path, "%smods/kuma-polar-bear", base);
        if (n > 0 && n < (int)sizeof path) gl_renderer_set_kuma_texture_pack(path);
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
}
PSX_MOD_CONSTRUCTOR(tekken3_register_kuma_skin) {
    (void)psx_mod_register_activation_plugin("tekken3.kuma-polar-bear", tekken3_kuma_skin_activate);
}
