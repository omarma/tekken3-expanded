/*
 * Tekken 3 true-widescreen activation.
 *
 * Guarded visibility-angle alternatives reveal the original stage sections
 * without changing the section grid or writing guest code pages. This static
 * plugin selects native 16:9 before renderer initialization. Disabled, both
 * the renderer and the guest visibility cone remain exact 4:3.
 */
#include "mod_plugins.h"
#include "gpu.h"

static void tekken3_true_widescreen_activate(void)
{
    (void)psx_mod_set_fixed_display_aspect(16u, 9u);
    /* Tekken never clears its 3D framebuffer: while the fight camera pulls
     * back, stage sections briefly leave gaps that the PS1 fills with the
     * previous frame. Keep the wide surface's history the same way. */
    gpu_ws_set_nw_world_history(1);
}

/* Tekken Force's invisible walls. The overlay's stage setup (0x800B2AB4)
 * stores the left and right limits of the walk, in world units, as the
 * immediates of four ADDIUs: the stage's limits (-2553 and 1971; a boss
 * stage, id 0x12, has its own) end at the edges of the 4:3 screen, and the
 * camera does not read them. In 16:9 the player stopped that far inside the
 * wider view. Move each limit out by the width the wide view adds on its side:
 * 15 world units per screen pixel at the player's depth (measured, Michelle
 * at seven positions of stage 1's start; 61 px per side at 16:9, 915 units).
 * Only words that still hold the stock immediates are rewritten, so the patch
 * is made once per load of the overlay and a changed overlay is left alone. */
enum { FORCE_WALL_UNITS_PER_PIXEL = 15 };
static const struct { uint32_t at, word; int side; } force_walls[] = {
    {0x800B2AD4u, 0x2402F607u, -1}, {0x800B2B00u, 0x2402F673u, -1},
    {0x800B2AF0u, 0x240207B3u, +1}, {0x800B2B18u, 0x2402087Fu, +1},
};
static void tekken3_force_walls_tick(void)
{
    const int margin = psx_ws_x_margin();
    if (margin <= 0 || !psx_mod_game_started() ||
        psx_mod_read_word(0x800B2658u) != 0x27BDFFB8u)   /* the Tekken Force overlay */
        return;
    for (unsigned i = 0; i < sizeof force_walls / sizeof force_walls[0]; i++) {
        if (psx_mod_read_word(force_walls[i].at) != force_walls[i].word) continue;
        const int limit = (int16_t)(force_walls[i].word & 0xFFFFu) +
                          force_walls[i].side * margin * FORCE_WALL_UNITS_PER_PIXEL;
        psx_mod_write_code_word(force_walls[i].at,
                                (force_walls[i].word & 0xFFFF0000u) | ((uint32_t)limit & 0xFFFFu));
    }
    /* The setup has usually run already: the limits it stored are the two
     * words at 0x800B6608 (left) and 0x800B6610 (right), still the stock
     * ones for a stage not yet widened. */
    static const struct { uint32_t at; int stock[2]; int side; } stored[] = {
        {0x800B6608u, {-2553, -2445}, -1}, {0x800B6610u, {1971, 2175}, +1},
    };
    for (unsigned i = 0; i < 2; i++) {
        const int value = (int)psx_mod_read_word(stored[i].at);
        if (value == stored[i].stock[0] || value == stored[i].stock[1])
            psx_mod_write_word(stored[i].at,
                               (uint32_t)(value + stored[i].side * margin * FORCE_WALL_UNITS_PER_PIXEL));
    }
}

PSX_MOD_CONSTRUCTOR(tekken3_register_visual_plugins)
{
    (void)psx_mod_register_activation_plugin(
        "tekken3.true-widescreen", tekken3_true_widescreen_activate);
    (void)psx_mod_register_vblank_plugin(
        "tekken3.true-widescreen", tekken3_force_walls_tick);
}
