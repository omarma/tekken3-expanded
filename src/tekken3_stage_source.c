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
 * moveset. True Ogre (ID 20) on either side: TTT's stage 14 (Unknown's) in
 * TTT, T3 or 14 in RANDOM (the user's choice, 2026-10-21); in AUTO his own
 * Tekken 3 stage (the user's choice, 2026-10-25: stage 14 is Unknown's); his
 * fight is the game's dark arena (0x800AFAA0 = 2, Ogre's arena 6, decided
 * again when the cutscene reloads Ogre as True Ogre), which keeps the PS1
 * stage otherwise. A Continue fights the same fight again: it keeps its
 * stage. Gon's arena 13 (Roger and Alex's too) and Dr. B's 14 keep the PS1
 * stage.
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
 * before its packs exist (the engine then draws Tekken 3's). */
#include "tekken3_stage_source.h"
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
       ARENA = 0x800adc84, DARK_ARENA = 0x800afaa0, NO_STAGE = 0x800adca4, HUMAN = 0x800ae1f8,
       LAST_ARCADE_ARENA = 12, PRACTICE = 5, DEMO = 6, STAGE_MODES = 0x3f };
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
static int decided_true_ogre;            /* TTT's stage 14 for True Ogre: drawn in the dark arena */
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
enum { EDDY_ARENA = 10, EDDY_B = 10, EDDY_A = 13 };
enum { FIGHTERS = 0x800add5c, TRUE_OGRE = 20, UNKNOWN_STAGE = 14 };   /* fighter IDs of players 1, 2 */

static int pick(int count) { return (int)tekken3_moveset_draw((unsigned)count, &draw_state); }
/* TTT's stage of an arena (TTT, RANDOM, a guest in AUTO); Unknown's is 14
 * whatever her arena. */
static int ttt_stage_of(const char *guest, int arena) {
    if (guest && !strcmp(guest, "unknown")) return UNKNOWN_STAGE;
    return arena == EDDY_ARENA ? (pick(2) ? EDDY_A : EDDY_B) : arena;
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
    if (!deciding_mode(mode)) { decided = -1; return; }
    if (continuing && decided >= 0) {
        continuing = 0;
        fprintf(stderr, "TTT Stages: %s Continue, the same fight on %s stage %d\n", mode_names[mode],
                decided == TEKKEN3_STAGE_TTT ? "TTT" : "T3",
                decided == TEKKEN3_STAGE_TTT ? decided_stage : decided_arena);
        return;
    }
    continuing = 0;
    int s = effective(), stage = -1;
    /* True Ogre (ID 20) on either side (Team Battle: the fighter on the field):
     * TTT's stage 14, Unknown's, whatever the arena, in TTT, and in RANDOM one
     * chance in two (the user's choice of 2026-10-21); AUTO and T3 his own
     * Tekken 3 stage (2026-10-25). */
    int true_ogre = psx_mod_read_half(FIGHTERS) == TRUE_OGRE || psx_mod_read_half(FIGHTERS + 2) == TRUE_OGRE;
    if (arena >= 0 && arena <= LAST_ARCADE_ARENA)
        stage = true_ogre ? (s == SET_TTT || (s == SET_RANDOM && pick(2)) ? UNKNOWN_STAGE : -1)
              : s == SET_TTT ? ttt_stage_of(guest, arena)
              : s == SET_RANDOM ? (pick(2) ? ttt_stage_of(guest, arena) : -1)
              : s == SET_AUTO ? auto_stage(guest, arena) : -1;
    decided = stage >= 0 ? TEKKEN3_STAGE_TTT : TEKKEN3_STAGE_T3;
    decided_stage = stage; decided_arena = arena;
    decided_true_ogre = true_ogre && stage >= 0;
    fprintf(stderr, "TTT Stages: %s fight in arena %d, P%d's %s%s decides%s, STAGES %s -> %s stage %d\n",
            mode_names[mode], arena, player + 1, guest ? "guest " : player < 0 ? "-" : "native",
            guest ? guest : "", true_ogre ? " (True Ogre fights)" : "", words[s], stage >= 0 ? "TTT" : "T3",
            stage >= 0 ? stage : arena);
}

void tekken3_stage_source_tick(void) {
    if (!psx_mod_game_started()) return;
    unsigned screen = psx_mod_read_word(SCREEN);
    if (screen == OPTIONS) tekken3_stage_source_menu();
    /* A Continue: in the fight, a human side handed to the CPU (TIPS.md
     * section 74). Any screen but the fight, the loading screen, the
     * selector (9) or screen 1 ends the match. */
    static uint16_t was_human[2];
    if (screen == MENU) decided = -1;
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
 * the decided one, Gon's or Dr. B's, the dark arena (but True Ogre's, when
 * TTT's stage 14 was decided for him). */
static int own_stage(void) {
    int arena = psx_mod_read_half(ARENA);
    return decided < 0 || !deciding_mode(psx_mod_read_word(MODE)) || arena != decided_arena ||
           arena < 0 || arena > LAST_ARCADE_ARENA || (psx_mod_read_byte(DARK_ARENA) && !decided_true_ogre) ||
           psx_mod_read_byte(NO_STAGE);
}
int tekken3_stage_source(void) { return own_stage() ? TEKKEN3_STAGE_T3 : decided; }
int tekken3_stage_arena(void) { return own_stage() ? -1 : psx_mod_read_half(ARENA); }
int tekken3_stage_ttt_stage(void) { return tekken3_stage_source() == TEKKEN3_STAGE_TTT ? decided_stage : -1; }
unsigned tekken3_stage_decisions(void) { return decisions; }
