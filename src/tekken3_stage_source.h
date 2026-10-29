/* Which stages a fight is drawn with, Tekken 3's or Tekken Tag Tournament's:
 * the Options menu's STAGES row (T3, TTT, AUTO, RANDOM) decided per fight
 * (src/tekken3_stage_source.c). Read by the stage engine
 * (src/tekken3_arcade_stages.c) and the stage music. */
#ifndef TEKKEN3_STAGE_SOURCE_H
#define TEKKEN3_STAGE_SOURCE_H
#ifdef __cplusplus
extern "C" {
#endif

enum { TEKKEN3_STAGE_T3 = 0, TEKKEN3_STAGE_TTT = 1 };

/* The source of the fight being loaded or fought: TEKKEN3_STAGE_TTT only for
 * an arena 0..12 of a fight of Arcade, VS, Team Battle, Time Attack, Survival,
 * Practice or the attract's demo the row gave to TTT (Gon's and Dr. B's
 * arenas 13 and 14 given a TTT stage are loaded as its arena, see
 * tekken3_stage_source_load_arena); TEKKEN3_STAGE_T3 for everything else
 * (the row's T3, Gon's and Dr. B's PS1 stages, the dark arena, Tekken Ball,
 * Tekken Force, the Embu, a cinematic's scene, TTT Stages off). */
int tekken3_stage_source(void);
/* The arena that source applies to (0x800ADC84, a guest's arena already
 * that of guests.txt's third column), or -1 where the game's own stage
 * stays, as listed above. */
int tekken3_stage_arena(void);
/* With TEKKEN3_STAGE_TTT, the TTT stage to draw: 0..12 (TTT stage n is
 * arena n), 13 Eddy-A (in arena 10, beside Eddy-B 10), 14 Unknown's (her
 * own, and True Ogre's as Arcade's CPU); -1 otherwise. Not always the arena,
 * then. */
int tekken3_stage_ttt_stage(void);
/* Nonzero when the fight's TTT stage is Unknown's for True Ogre as Arcade's
 * CPU: drawn as it is in the dark arena, where any other TTT stage is drawn
 * at night (B124). */
int tekken3_stage_true_ogre_boss(void);

/* Bumped at each decision (each fight, Continues included): TTT's storm
 * starts again with it, as at TTT's stage load. */
unsigned tekken3_stage_decisions(void);

/* The engine's side: nonzero when it can draw that source (TTT: its packs
 * are there). A source it cannot draw is never offered nor decided. */
int tekken3_arcade_stages_source_ready(int source);

/* TTT Stages' side (its own tick, with or without TTT1 Characters; the
 * decision from TTT1 Characters' 0x8004F3B0 wrapper). On the Options screen: the STAGES row
 * (added once, when two values at least can be drawn). From the routine that
 * picks the fight's arena (0x8004F3B0): the fight's stage, for `mode`
 * (0x800AFA88), the deciding player (-1 none), its guest's key (NULL for a
 * native) and the arena its record gives. Every VBlank: Continues (the same
 * fight again, the same stage). */
void tekken3_stage_source_menu(void);
void tekken3_stage_source_decide(unsigned mode, int player, const char *guest, int arena);
void tekken3_stage_source_tick(void);
/* After a decision that gave Gon's or Dr. B's arena a TTT stage (B122): the
 * arena the game must load instead (Eddy's 10 for Eddy-A, Nina's 9), which
 * the tick writes until the fight and a guest's arena correction must
 * follow; -1 otherwise. */
int tekken3_stage_source_load_arena(void);

#ifdef __cplusplus
}
#endif
#endif
