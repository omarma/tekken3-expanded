/* The STAGE line of VS BATTLE SELECT and of the Practice grid (F18, GH#148):
 * the player picks the fight's stage, kept for the next fights
 * (src/tekken3_stage_select.c). */
#ifndef TEKKEN3_STAGE_SELECT_H
#define TEKKEN3_STAGE_SELECT_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* From 0x8004F3B0, which picks the fight's arena (src/tekken3_ttt1_roster.c),
 * before the stage source decides: the stage of the fight that loads, for
 * `mode` (0x800AFA88). */
void tekken3_stage_select_fight(unsigned mode);
/* The fight's chosen stage: nonzero in VS and Practice when the line holds
 * one (not DEFAULT); its source (TEKKEN3_STAGE_T3 / _TTT), TTT stage (-1 for
 * Tekken 3's) and the arena the game loads. */
int tekken3_stage_select_choice(unsigned mode, int *source, int *ttt_stage, int *arena);
/* The chosen arena of the fight that loads, -1 none. */
int tekken3_stage_select_arena(void);
/* Its music (0x800ADD08): the record's of the chosen Tekken 3 stage, its
 * owner's for a TTT stage (under the TTT piece); -1 none. */
int tekken3_stage_select_music(void);

/* The selector's pads (src/tekken3_ttt1_selector.c), before the MOVESET
 * cards: the line's own presses, kept from the game. */
uint16_t tekken3_stage_select_input(int player, uint16_t buttons);

/* What the line shows now, for the selector's packets
 * (src/tekken3_native_moves.c), under its STAGE SELECT title: 0 nothing,
 * 1 VS BATTLE SELECT's band, 2 the Practice grid's. *label: GAME or the
 * game; *name: the game or
 * the stage; *arrows: -1 none, else the colour of the player who changes it
 * (0 player 1, 1 player 2, 2 the CPU's green, 3 both: player 1's on the
 * left, player 2's on the right). */
int tekken3_stage_select_line(const char **label, const char **name, int *arrows);

#ifdef __cplusplus
}
#endif
#endif
