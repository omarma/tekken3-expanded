/* The STAGES row of GAME OPTION and the source it decides for each fight.
 *
 * T3: Tekken 3's stage. TTT: TTT's stage of the arena (TTT stage n is arena
 * n; arena 10, Eddy-B 10 or Eddy-A 13, one chance in two). RANDOM: T3 or TTT
 * as above, one chance in two. AUTO (handoff/ttt-stages.md, the user's
 * choices of 2026-10-20): the fighter whose record gives the fight's arena
 * (0x8004F3B0: the CPU in Arcade, the player who chose last in VS, TIPS.md
 * section 26) decides. A guest: TTT's stage of its arena (guests.txt, third
 * column; Bruce: Bryan's arena 0), Unknown her own, TTT's stage 14, in AUTO,
 * TTT and RANDOM alike (the user's choice, 2026-10-25). A native: Tekken 3's stage, but in the
 * arenas of native_draws, where TTT's stages would never come up otherwise:
 * arena 5 (Lei) T3 or TTT 5, arena 7 (Xiaoyu and Jin in costumes 3 and 4) T3
 * or School, arena 10 (Eddy, Tiger) T3, Eddy-B or Eddy-A. Every draw is
 * made once per fight with the host's generator, as the CPU draws its
 * moveset. True Ogre (ID 20) on either side makes the fight the game's dark
 * arena (0x800AFAA0, 0x80050F5C; Arcade: Ogre's arena 6, decided again when
 * the cutscene reloads Ogre as True Ogre): the same rules decide, a TTT
 * stage is drawn at night as TTT draws its stages with True Ogre in a team,
 * Tekken 3's stays the PS1's dark arena (B124, GH#172, the user's choices of
 * 2026-10-28). But True Ogre as Arcade's CPU, the boss, keeps 1.4.0's rule:
 * TTT's stage 14, Unknown's, as it is, in TTT, T3 or 14 in RANDOM, his
 * Tekken 3 stage in AUTO and T3. A Continue fights the same fight again: it
 * keeps its stage. Gon's arena 13 (Roger and Alex's too) and Dr. B's 14 have no TTT
 * stage of their own (B122, GH#171, the user's choice of 2026-10-27): Gon's
 * takes Eddy-A by day (13), Dr. B's Nina's (9), as any arena does in TTT,
 * RANDOM and for a guest in AUTO (Roger, Alex); a native in AUTO, and T3,
 * keep the PS1 stage. The game then loads the arena of that TTT stage
 * (Eddy's 10, Nina's 9, as the STAGE line of F18 does), its music the
 * fighter's.
 *
 * Only what can be drawn is offered: TTT once the engine has TTT packs, so
 * AUTO and RANDOM too; Tekken 3's stage always (the arcade stage with Arcade
 * Stages and tekken3.zip, the PS1 stage without). With a single value left
 * the row is not added. A saved value that cannot be drawn now leaves the
 * file alone and shows, and decides, the default (or the first value left).
 *
 * The choice is kept beside the memory card in ttt-stages.txt (t3, ttt,
 * auto or random), not in the game's options block. Benches:
 * TEKKEN3_STAGES (t3, ttt, auto, random) overrides the menu,
 * TEKKEN3_STAGES_SEED fixes RANDOM's draw, TEKKEN3_STAGES_TTT=1 offers TTT
 * before its packs exist (the engine then draws Tekken 3's).
 *
 * In VS and Practice the STAGE line (F18, src/tekken3_stage_select.c) comes
 * first: a stage chosen there is the fight's, the row's value only with the
 * line's AUTO. */
#include "tekken3_stage_source.h"
#include "tekken3_stage_select.h"
#include "tekken3_game_options.h"
#include "tekken3_moveset_draw.h"
#include "memcard.h"
#include "mod_plugins.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { SCREEN = 0x800ae204, OPTIONS = 5, FIGHT = 8, LOADING = 11, MENU = 4, MODE = 0x800afa88,
       ARENA = 0x800adc84, ARENA_COPY = 0x800afaa2, DARK_ARENA = 0x800afaa0, NO_STAGE = 0x800adca4,
       HUMAN = 0x800ae1f8, LAST_ARCADE_ARENA = 12, GON_ARENA = 13, DR_B_ARENA = 14, ARCADE = 0, PRACTICE = 5, DEMO = 6,
       STAGE_MODES = 0x3f };
enum { SET_T3, SET_TTT, SET_AUTO, SET_RANDOM, SETTINGS };
static const char *const words[SETTINGS] = { "t3", "ttt", "auto", "random" };
static const char *const labels[SETTINGS] = { "TEKKEN 3", "TEKKEN TAG TOURNAMENT", "AUTO", "RANDOM" };
static const char *const mode_names[] = { "Arcade", "VS", "Team Battle", "Time Attack", "Survival", "Practice",
                                          "Attract demo" };
/* The modes that decide: Arcade to Practice, and the attract's demo fight
 * (B75, GH#130: as any CPU fight; its arena is player 1's). */
static int deciding_mode(unsigned mode) { return mode <= PRACTICE || mode == DEMO; }
/* Decision 5 of handoff/ttt-stages.md (the user's, 2026-10-20): AUTO. */
enum { DEFAULT_SETTING = SET_AUTO };

static int setting = -1;                 /* the saved choice, -1 not read */
static int forced;                       /* TEKKEN3_STAGES */
static uint64_t draw_state;
static int decided = -1;                 /* the fight's source, -1 none yet */
static int decided_stage = -1, decided_arena = -1;   /* its TTT stage, its arena */
static int decided_moved;                /* Gon's or Dr. B's arena: the game loads decided_arena instead */
static int decided_boss;                 /* Unknown's stage 14 for True Ogre as Arcade's CPU (B124) */
static int moving;                       /* that arena written until the fight */
static int continuing;
static unsigned decisions;               /* tekken3_stage_decisions */
static int row = -1, offered[SETTINGS], offered_count, shown = -1;

static int ready(int source) {
    if (source == TEKKEN3_STAGE_T3) return 1;
    const char *e = getenv("TEKKEN3_STAGES_TTT");
    return tekken3_arcade_stages_source_ready(source) || (e && *e == '1');
}
static int available(int s) {
    return s == SET_T3 ? ready(TEKKEN3_STAGE_T3) : s == SET_TTT ? ready(TEKKEN3_STAGE_TTT)
         : ready(TEKKEN3_STAGE_T3) && ready(TEKKEN3_STAGE_TTT);
}

static void setting_path(char *out, size_t size) {
    const char *card = NULL; out[0] = 0;
    if (memcard_debug_info(0, &card, NULL, NULL, NULL) || !card || !*card) return;
    const char *slash = strrchr(card, '/'), *back = strrchr(card, '\\');
    if (back && (!slash || back > slash)) slash = back;
    int n = slash ? (int)(slash - card) : 1;
    snprintf(out, size, "%.*s/ttt-stages.txt", n, slash ? card : ".");
}
static int parse(const char *word) {
    for (int i = 0; i < SETTINGS; i++) if (!strcmp(word, words[i])) return i;
    return DEFAULT_SETTING;
}
static void save(void) {
    char path[4096]; setting_path(path, sizeof path);
    FILE *f = path[0] ? fopen(path, "wb") : NULL;
    if (f) { fprintf(f, "%s\n", words[setting]); fclose(f); }
}
static void read_setting(void) {
    if (setting >= 0) return;
    setting = DEFAULT_SETTING;
    const char *e = getenv("TEKKEN3_STAGES");
    if (e && *e) { setting = parse(e); forced = 1; }
    else {
        char path[4096]; setting_path(path, sizeof path);
        FILE *f = path[0] ? fopen(path, "rb") : NULL;
        char word[32] = "";
        if (f) { if (fscanf(f, "%31s", word) == 1) setting = parse(word); fclose(f); }
    }
    const char *seed = getenv("TEKKEN3_STAGES_SEED");
    tekken3_moveset_seed(&draw_state, seed && *seed ? strtoull(seed, NULL, 0)
        : (uint64_t)time(NULL) * 1000003u + (uint64_t)clock() + (uint64_t)(uintptr_t)&draw_state);
}
/* The value that stands: the saved one if it can be drawn, else the default,
 * else the first that can. */
static int effective(void) {
    read_setting();
    if (available(setting)) return setting;
    if (available(DEFAULT_SETTING)) return DEFAULT_SETTING;
    for (int i = 0; i < SETTINGS; i++) if (available(i)) return i;
    return SET_T3;
}

void tekken3_stage_source_menu(void) {
    if (row < 0 && !offered_count) {
        const char *list[SETTINGS];
        int now = effective(), value = 0, fallback = 0;
        for (int i = 0; i < SETTINGS; i++)
            if (available(i)) {
                if (i == now) value = offered_count;
                if (i == DEFAULT_SETTING) fallback = offered_count;
                list[offered_count] = labels[i]; offered[offered_count++] = i;
            }
        if (offered_count < 2) {
            fprintf(stderr, "TTT Stages: no STAGES row, Tekken 3's stages only\n");
            return;
        }
        row = tekken3_game_options_add("STAGES", list, (unsigned)offered_count, (unsigned)value,
                                       (unsigned)fallback, STAGE_MODES);
        shown = value;
    }
    if (row < 0) return;
    /* The player's choice, kept beside the memory card. */
    int v = tekken3_game_options_value(row);
    if (v >= 0 && v < offered_count && v != shown) {
        shown = v;
        if (!forced) { setting = offered[v]; save(); }
        fprintf(stderr, "TTT Stages: STAGES set to %s\n", words[offered[v]]);
    }
}

/* AUTO: a native in these arenas draws among T3 (-1) and TTT stages. */
static const struct { int arena, count, choices[3]; } native_draws[] = {
    { 5, 2, { -1, 5 } },                  /* Lei: T3 or TTT 5 */
    { 7, 2, { -1, 7 } },                  /* Xiaoyu, Jin in costumes 3, 4: T3 or School */
    { 10, 3, { -1, 10, 13 } },            /* Eddy, Tiger: T3, Eddy-B or Eddy-A */
};
enum { EDDY_ARENA = 10, EDDY_B = 10, EDDY_A = 13, NINA = 9, OGRE_ARENA = 6 };
enum { FIGHTERS = 0x800add5c, TRUE_OGRE = 20, UNKNOWN_STAGE = 14 };   /* fighter IDs of players 1, 2 */

static int pick(int count) { return (int)tekken3_moveset_draw((unsigned)count, &draw_state); }
/* TTT's stage of an arena (TTT, RANDOM, a guest in AUTO); Unknown's is 14
 * whatever her arena; Gon's arena Eddy-A, Dr. B's Nina's (B122). */
static int ttt_stage_of(const char *guest, int arena) {
    if (guest && !strcmp(guest, "unknown")) return UNKNOWN_STAGE;
    if (arena == GON_ARENA) return EDDY_A;
    if (arena == DR_B_ARENA) return NINA;
    return arena == EDDY_ARENA ? (pick(2) ? EDDY_A : EDDY_B) : arena;
}
/* The arena the game loads for TTT's stage in Gon's or Dr. B's arena:
 * Eddy-A's is Eddy's, Unknown's Ogre's (Unknown in Gon's arena), as on F18's
 * STAGE line. */
static int arena_of_stage(int stage) {
    return stage == EDDY_A ? EDDY_ARENA : stage == UNKNOWN_STAGE ? OGRE_ARENA : stage;
}
/* AUTO's stage: -1 Tekken 3's. */
static int auto_stage(const char *guest, int arena) {
    if (guest) return ttt_stage_of(guest, arena);
    for (unsigned i = 0; i < sizeof native_draws / sizeof native_draws[0]; i++)
        if (native_draws[i].arena == arena) return native_draws[i].choices[pick(native_draws[i].count)];
    return -1;
}

void tekken3_stage_source_decide(unsigned mode, int player, const char *guest, int arena) {
    decisions++;
    if (!deciding_mode(mode)) { decided = -1; decided_moved = moving = 0; return; }
    if (continuing && decided >= 0) {
        continuing = 0; moving = decided_moved;
        fprintf(stderr, "TTT Stages: %s Continue, the same fight on %s stage %d\n", mode_names[mode],
                decided == TEKKEN3_STAGE_TTT ? "TTT" : "T3",
                decided == TEKKEN3_STAGE_TTT ? decided_stage : decided_arena);
        return;
    }
    continuing = 0;
    /* The STAGE line of VS and Practice (src/tekken3_stage_select.c): its
     * stage, on the arena it has the game load. */
    int chosen_source, chosen_stage, chosen_arena;
    if (tekken3_stage_select_choice(mode, &chosen_source, &chosen_stage, &chosen_arena)) {
        decided = chosen_source; decided_stage = chosen_stage; decided_arena = chosen_arena;
        decided_moved = moving = decided_boss = 0;
        fprintf(stderr, "TTT Stages: %s fight, the STAGE line's %s stage %d in arena %d\n", mode_names[mode],
                decided == TEKKEN3_STAGE_TTT ? "TTT" : "T3", decided == TEKKEN3_STAGE_TTT ? decided_stage : decided_arena,
                decided_arena);
        return;
    }
    int s = effective(), stage = -1;
    /* True Ogre (ID 20) on either side (Team Battle: the fighter on the
     * field): the dark arena (B124). As Arcade's CPU (no human on his
     * side), the boss: Unknown's stage 14 in TTT, T3 or 14 in RANDOM, T3 in
     * AUTO and T3, as in 1.4.0 (the user's choice of 2026-10-28). */
    int ogre[2], boss = 0;
    for (int p = 0; p < 2; p++) {
        ogre[p] = psx_mod_read_half(FIGHTERS + 2 * p) == TRUE_OGRE;
        boss |= mode == ARCADE && ogre[p] && !psx_mod_read_half(HUMAN + 2 * p);
    }
    int true_ogre = ogre[0] || ogre[1];
    if (arena >= 0 && arena <= DR_B_ARENA)
        stage = boss ? (s == SET_TTT || (s == SET_RANDOM && pick(2)) ? UNKNOWN_STAGE : -1)
              : s == SET_TTT ? ttt_stage_of(guest, arena)
              : s == SET_RANDOM ? (pick(2) ? ttt_stage_of(guest, arena) : -1)
              : s == SET_AUTO ? auto_stage(guest, arena) : -1;
    decided = stage >= 0 ? TEKKEN3_STAGE_TTT : TEKKEN3_STAGE_T3;
    /* Gon's or Dr. B's arena given a TTT stage: the game loads its arena. */
    decided_moved = moving = stage >= 0 && arena > LAST_ARCADE_ARENA;
    decided_stage = stage; decided_arena = decided_moved ? arena_of_stage(stage) : arena;
    decided_boss = boss && stage >= 0;
    char moved[32] = "";
    if (decided_moved) snprintf(moved, sizeof moved, ", loads arena %d", decided_arena);
    fprintf(stderr, "TTT Stages: %s fight in arena %d, P%d's %s%s decides%s%s, STAGES %s -> %s stage %d\n",
            mode_names[mode], arena, player + 1, guest ? "guest " : player < 0 ? "-" : "native",
            guest ? guest : "", boss ? " (True Ogre, Arcade's CPU)" : true_ogre ? " (True Ogre fights: at night)" : "", moved, words[s], stage >= 0 ? "TTT" : "T3",
            stage >= 0 ? stage : arena);
}
int tekken3_stage_source_load_arena(void) { return moving ? decided_arena : -1; }

void tekken3_stage_source_tick(void) {
    if (!psx_mod_game_started()) return;
    unsigned screen = psx_mod_read_word(SCREEN);
    if (screen == OPTIONS) tekken3_stage_source_menu();
    /* A Continue: in the fight, a human side handed to the CPU (TIPS.md
     * section 74). Any screen but the fight, the loading screen, the
     * selector (9) or screen 1 ends the match. */
    static uint16_t was_human[2];
    if (screen == MENU) { decided = -1; moving = 0; }
    /* Gon's or Dr. B's arena given a TTT stage: the arena of that stage,
     * every VBlank until the fight (as the STAGE line, F18). */
    if (moving && screen == FIGHT) moving = 0;
    if (moving && decided >= 0) {
        if (psx_mod_read_half(ARENA) != (uint16_t)decided_arena) psx_mod_write_half(ARENA, (uint16_t)decided_arena);
        if (psx_mod_read_byte(ARENA_COPY) != (uint8_t)decided_arena) psx_mod_write_byte(ARENA_COPY, (uint8_t)decided_arena);
    }
    /* The demo's decision ends with its fight: the Embu (state 6) that may
     * follow is mode 6 too, in Hwoarang's arena, and keeps the game's stage. */
    if (psx_mod_read_word(MODE) == DEMO && screen != FIGHT && screen != LOADING && screen != 1) decided = -1;
    if (screen != FIGHT && screen != LOADING && screen != 9 && screen != 1) {
        continuing = 0; was_human[0] = was_human[1] = 0;
    }
    if (screen == FIGHT)
        for (unsigned p = 0; p < 2; p++) {
            uint16_t human = psx_mod_read_half(HUMAN + p * 2);
            if (was_human[p] && !human) continuing = 1;
            was_human[p] = human;
        }
}

/* The game's own stage: nothing decided, another mode, another arena than
 * the decided one, Gon's or Dr. B's (when they keep it), the dark arena with
 * Tekken 3's stage decided (a TTT stage is drawn there at night, B124). */
static int own_stage(void) {
    int arena = psx_mod_read_half(ARENA);
    return decided < 0 || !deciding_mode(psx_mod_read_word(MODE)) || arena != decided_arena ||
           arena < 0 || arena > LAST_ARCADE_ARENA || (psx_mod_read_byte(DARK_ARENA) && decided != TEKKEN3_STAGE_TTT) ||
           psx_mod_read_byte(NO_STAGE);
}
int tekken3_stage_source(void) { return own_stage() ? TEKKEN3_STAGE_T3 : decided; }
int tekken3_stage_arena(void) { return own_stage() ? -1 : psx_mod_read_half(ARENA); }
int tekken3_stage_true_ogre_boss(void) { return tekken3_stage_source() == TEKKEN3_STAGE_TTT && decided_boss; }
int tekken3_stage_ttt_stage(void) { return tekken3_stage_source() == TEKKEN3_STAGE_TTT ? decided_stage : -1; }
unsigned tekken3_stage_decisions(void) { return decisions; }
