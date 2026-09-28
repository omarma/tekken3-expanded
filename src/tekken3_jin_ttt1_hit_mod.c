/* Jin's strong-hit effect from Tekken Tag Tournament: the red lightning in
 * place of his blue one.
 *
 * Each fighter's file carries a pack of 4-bit TIMs (16-colour palette,
 * 32 x 32 image) that the fight loader places in VRAM: frame k in column
 * 368/376 (player 1) or 496/504 (player 2), row 32*(k/2), palette at
 * (16*player, 503); Jin's has 22 frames. The replacement pack is converted
 * from the user's own TTT1 ROM by tools/ttt1_jin_hit_effect.py and read from
 * mods/jin-ttt1-hit-effect next to the executable (TEKKEN3_JIN_HIT_EFFECT
 * overrides the file). While a fight runs (0x800AE204 == 8), it is written
 * over Jin's whenever the loader has put the original back. Guests imported
 * through Jin's file carry their own character ID (23), so they are left
 * alone. Without the file the feature does nothing.
 */
#include "mod_plugins.h"
#include "gpu_render.h"
#include "psx_sdl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { JIN_ID = 9, FRAME_BYTES = 576, JIN_FRAMES = 22 };

static unsigned char *pack;
static int attempted;

static uint32_t word(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void load_pack(void) {
    if (attempted) return;
    attempted = 1;
    char path[4096];
    const char *override = getenv("TEKKEN3_JIN_HIT_EFFECT");
    if (override && *override) {
        if (snprintf(path, sizeof path, "%s", override) >= (int)sizeof path) return;
    } else {
        const char *base = SDL_GetBasePath();
        if (!base) return;
        int n = snprintf(path, sizeof path, "%smods/jin-ttt1-hit-effect/Jin-TTT1-hiteffect.tim", base);
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
        if (n < 0 || n >= (int)sizeof path) return;
    }
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "Jin TTT1 hit effect: %s missing, run tools/ttt1_jin_hit_effect.py\n", path);
        return;
    }
    unsigned char *p = malloc(JIN_FRAMES * FRAME_BYTES + 1);
    size_t n = p ? fread(p, 1, JIN_FRAMES * FRAME_BYTES + 1, f) : 0;
    fclose(f);
    int ok = p && n == JIN_FRAMES * FRAME_BYTES;
    for (size_t o = 0; ok && o < n; o += FRAME_BYTES)
        ok = word(p + o) == 0x10 && word(p + o + 4) == 8 && word(p + o + 8) == 44 &&
             word(p + o + 16) == 0x10010 && word(p + o + 52) == 524 && word(p + o + 60) == 0x200008;
    if (!ok) {
        fprintf(stderr, "Jin TTT1 hit effect: %s is not a %d-frame effect pack\n", path, JIN_FRAMES);
        free(p);
        return;
    }
    pack = p;
    fprintf(stderr, "Jin TTT1 hit effect: loaded %s\n", path);
}

static void place(unsigned player) {
    unsigned x = player ? 496 : 368;
    uint16_t row[16], pal[16];
    gr_vram_transfer_out(x, 0, 8, 1, row);
    gr_vram_transfer_out(16 * player, 503, 16, 1, pal);
    if (!memcmp(row, pack + 64, 16) && !memcmp(pal, pack + 20, 32)) return;
    for (unsigned k = 0; k < JIN_FRAMES; k++)
        gr_vram_transfer_in(x + 8 * (k & 1), 32 * (k >> 1), 8, 32, (const uint16_t *)(pack + k * FRAME_BYTES + 64));
    gr_vram_transfer_in(16 * player, 503, 16, 1, (const uint16_t *)(pack + 20));
}

static void tekken3_jin_ttt1_hit_tick(void) {
    if (!psx_mod_game_started() || psx_mod_read_word(0x800AE204u) != 8) return;
    load_pack();
    if (!pack) return;
    for (unsigned player = 0; player < 2; player++)
        if (psx_mod_read_half(0x800A9240u + player * 0x188Cu) == JIN_ID) place(player);
}

PSX_MOD_CONSTRUCTOR(tekken3_register_jin_ttt1_hit) {
    (void)psx_mod_register_vblank_plugin("tekken3.jin-ttt1-hit-effect", tekken3_jin_ttt1_hit_tick);
}
