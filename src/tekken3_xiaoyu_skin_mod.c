/* Guarded host textures; independent from the other character skin packs. */
#include "mod_plugins.h"
#include "gpu_gl_renderer.h"
#include "psx_sdl.h"
#include <stdio.h>
static void tekken3_xiaoyu_skin_activate(void) {
    const char *base = SDL_GetBasePath();
    if (base) {
        char path[1024];
        int n = snprintf(path, sizeof path, "%smods/xiaoyu-cherry-blossom", base);
        if (n > 0 && n < (int)sizeof path) gl_renderer_set_xiaoyu_texture_pack(path);
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
}
PSX_MOD_CONSTRUCTOR(tekken3_register_xiaoyu_skin) {
    (void)psx_mod_register_activation_plugin("tekken3.xiaoyu-cherry-blossom", tekken3_xiaoyu_skin_activate);
}
