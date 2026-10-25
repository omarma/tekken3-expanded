/* GAME OPTION's BGM SELECT with a fourth value, RANDOM: each fight plays the
 * remixed (console) or the arcade version of its music, drawn once per fight
 * (src/tekken3_bgm_select.c). */
#ifndef TEKKEN3_BGM_SELECT_H
#define TEKKEN3_BGM_SELECT_H
#ifdef __cplusplus
extern "C" {
#endif

enum { TEKKEN3_BGM_REMIXED = 0, TEKKEN3_BGM_ARCADE = 1, TEKKEN3_BGM_SILENT = 2 };

/* Every VBlank (tekken3_main_menu_vblank): the row on the Options screen,
 * the Continues in a fight. Before tekken3_game_options_tick, which copies
 * the game's rows. */
void tekken3_bgm_select_tick(void);
/* From 0x8004F3B0, which picks each fight's arena and music (Continues
 * included): RANDOM draws the fight's version, a Continue keeps it. */
void tekken3_bgm_select_fight(void);
/* The version of the fight's music: REMIXED, ARCADE or SILENT (the card's
 * 0x80097F05); with RANDOM, the fight's draw, kept over the Continue's
 * screens where that music goes on. music_play (0x8006AE14) starts the
 * fight's music in it in the fight (game state 8), any other in the card's
 * version (REMIXED). */
int tekken3_bgm_select_version(void);

#ifdef __cplusplus
}
#endif
#endif
