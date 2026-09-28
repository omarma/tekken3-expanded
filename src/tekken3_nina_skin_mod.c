/* Optional host texture skin. Guest assets, gameplay and saves stay intact. */
#include "mod_plugins.h"
#include "gpu_gl_renderer.h"
#include "psx_sdl.h"
#include <stdio.h>
static void tekken3_nina_skin_activate(void) {
    const char *base = SDL_GetBasePath();
    if (base) {
        char path[1024];
        int n = snprintf(path, sizeof path, "%smods/nina-white-satin", base);
        if (n > 0 && n < (int)sizeof path) gl_renderer_set_skin_texture_pack(path);
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
}
PSX_MOD_CONSTRUCTOR(tekken3_register_nina_skin) {
    (void)psx_mod_register_activation_plugin("tekken3.nina-white-satin", tekken3_nina_skin_activate);
}
