/* Rows that mods add to the Options menu's GAME OPTION page, and the page's
 * scrolling once they no longer fit (src/tekken3_game_options.c). */
#ifndef TEKKEN3_GAME_OPTIONS_H
#define TEKKEN3_GAME_OPTIONS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct CPUState;

/* A row after the game's nine, before EXIT, in the order added: its name,
 * its `count` labels (copied), the value shown first, the game's default
 * (shown in green, the others in white) and the modes lit in the box on the
 * right (bit = mode: Arcade 0, VS 1, Team Battle 2, Time Attack 3, Survival
 * 4, Practice 5, Tekken Ball 7, Tekken Force 8). Returns the row's handle,
 * or -1. Added once; the page scrolls when the rows outgrow the screen. */
int tekken3_game_options_add(const char *name, const char *const *labels, unsigned count,
                             unsigned value, unsigned default_value, unsigned modes);
/* The value a row shows (0 .. count - 1), -1 for no such row. */
int tekken3_game_options_value(int row);
/* Every VBlank (tekken3_main_menu_vblank): nothing without a row. */
void tekken3_game_options_tick(void);
/* From the game's sound call (0x800753BC): the page's cursor moves. */
void tekken3_game_options_cursor(struct CPUState *cpu);
/* Nonzero while the page shows part of its rows (arrows to draw). */
int tekken3_game_options_scrolls(void);
/* The rows above or below the screen, as two arrows: primitives written
 * from `base` (at most `bytes`), linked to `link`. Returns the 24-bit
 * address of the first one, or `link` when there is nothing to draw. */
uint32_t tekken3_game_options_arrows(uint32_t base, uint32_t bytes, uint32_t link, unsigned frame);
#ifdef __cplusplus
}
#endif
#endif
