/* GAME OPTION's BGM SELECT with a fourth value, RANDOM (F11, GH#116, GH#96).
 *
 * The game's row (0x800B908C + 7 * 20 in the options overlay, TIPS.md
 * section 109) shows REMIXED (0, the console version), ARCADE (1) and SILENT
 * (2) of the byte music_option, 0x80097F05, which the memory card keeps.
 * music_play (0x8006AE14) reads it at each call: column 0 or 1 of the
 * fight's piece in 0x80024FD0; 2 and over, no music in game states 8..17
 * (the selector, the fights, the results), column 0 elsewhere. Both columns are XA tracks of the PS1
 * disc: on Tekken 3's stages both versions are always there. On TTT's, the
 * stage music (src/tekken3_ttt_music.c) reads the version through
 * tekken3_bgm_select_version(): REMIXED is TTT's PS2 piece when installed,
 * else the arcade one.
 *
 * RANDOM never reaches the card: a game without this code would read 3 as
 * SILENT in the fights and draw a label past its list. On the Options
 * screen the row is given a value byte of ours, four labels and a count of
 * 4 (as the difficulty mod lengthens its row); a choice of REMIXED, ARCADE
 * or SILENT goes to 0x80097F05 as before, RANDOM puts REMIXED there (what a
 * game without it plays) and is kept beside the card in bgm-select.txt
 * ("random", or "game": the card's value).
 *
 * The draw: from 0x8004F3B0, which picks each fight's arena and music (TTT1
 * Characters' wrapper, src/tekken3_ttt1_roster.c), one draw per fight
 * between REMIXED and ARCADE with the host's generator, as the CPU draws its
 * moveset. A Continue (a human side handed to the CPU in the fight, TIPS.md
 * section 74) fights the same fight again and keeps it. The draw lives in
 * mod memory, which save states keep: a state loaded plays the version it
 * was saved with. Without that wrapper the draw is made at the fight's
 * first music. While music_play runs in a fight (state 8: the selector,
 * the Continue and the results keep the card's version), 0x80097F05 holds
 * the fight's version, then its own value again.
 *
 * Benches: TEKKEN3_BGM_SELECT=random|game overrides the saved choice,
 * TEKKEN3_BGM_SEED fixes the draws (tools/test_bgm_random.py). */
#include "tekken3_bgm_select.h"
#include "cpu_state.h"
#include "memcard.h"
#include "mod_plugins.h"
#include "tekken3_moveset_draw.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { SCREEN = 0x800ae204, OPTIONS = 5, FIGHT = 8, SELECTOR = 9, LOADING = 11,
       MUSIC_OPTION = 0x80097f05, ROWS = 0x800b908c, GAME_ROWS = 9, ROW_SIZE = 20,
       FIRST_VALUE = 0x80097f06, LAST_VALUE = 0x80097f04,
       HUMAN = 0x800ae1f8, ENTRIES = 0x80024fd0, MUSIC_PLAY = 0x8006ae14 };
enum { REMIXED = TEKKEN3_BGM_REMIXED, ARCADE = TEKKEN3_BGM_ARCADE, SILENT = TEKKEN3_BGM_SILENT, RANDOM, VALUES };
static const char *const labels[VALUES] = { "REMIXED", "ARCADE", "SILENT", "RANDOM" };

static int random_on = -1;               /* the saved choice, -1 not read */
static int forced;                       /* TEKKEN3_BGM_SELECT */
static uint64_t draw_state;
static uint32_t mem;                     /* +0 the row's value, +1 the fight's draw (0 none, 1 + version) */
static uint32_t label_list;
static int shown = -1;                   /* the row's value last seen */
static int continuing;
static unsigned fights, events;          /* draws; draws and Continues (the log) */

static void setting_path(char *out, size_t size) {
    const char *card = NULL; out[0] = 0;
    if (memcard_debug_info(0, &card, NULL, NULL, NULL) || !card || !*card) return;
    const char *slash = strrchr(card, '/'), *back = strrchr(card, '\\');
    if (back && (!slash || back > slash)) slash = back;
    int n = slash ? (int)(slash - card) : 1;
    snprintf(out, size, "%.*s/bgm-select.txt", n, slash ? card : ".");
}
static void save(void) {
    char path[4096]; setting_path(path, sizeof path);
    FILE *f = path[0] ? fopen(path, "wb") : NULL;
    if (f) { fprintf(f, "%s\n", random_on ? "random" : "game"); fclose(f); }
}
static void read_setting(void) {
    if (random_on >= 0) return;
    random_on = 0;
    const char *e = getenv("TEKKEN3_BGM_SELECT");
    if (e && *e) { random_on = !strcmp(e, "random"); forced = 1; }
    else {
        char path[4096]; setting_path(path, sizeof path);
        FILE *f = path[0] ? fopen(path, "rb") : NULL;
        char word[32] = "";
        if (f) { if (fscanf(f, "%31s", word) == 1) random_on = !strcmp(word, "random"); fclose(f); }
    }
    const char *seed = getenv("TEKKEN3_BGM_SEED");
    tekken3_moveset_seed(&draw_state, seed && *seed ? strtoull(seed, NULL, 0)
        : (uint64_t)time(NULL) * 1000003u + (uint64_t)clock() + (uint64_t)(uintptr_t)&draw_state);
    if (random_on) fprintf(stderr, "BGM SELECT: RANDOM%s\n", forced ? " (TEKKEN3_BGM_SELECT)" : "");
}

static unsigned card_value(void) {
    unsigned v = psx_mod_read_byte(MUSIC_OPTION);
    return v < RANDOM ? v : REMIXED;
}
/* The fight itself: the game's states 8..17 also hold the selector, the
 * Continue and the results, whose music keeps the card's version. */
static int in_fight(void) { return psx_mod_read_half(SCREEN) == FIGHT; }

/* ---- The row ---- */

static int is_ram(uint32_t a) { return (a & 0xffe00000u) == 0x80000000u; }
static int name_is(uint32_t a, const char *s) {
    if (!is_ram(a)) return 0;
    do if (psx_mod_read_byte(a++) != (uint8_t)*s) return 0; while (*s++);
    return 1;
}
/* The BGM SELECT row while the options overlay is resident: its first and
 * last rows the difficulty and the speaker (as tekken3_game_options.c), the
 * row's value the game's byte or ours. */
static uint32_t bgm_row(void) {
    if (psx_mod_read_half(SCREEN) != OPTIONS || psx_mod_read_word(ROWS) != FIRST_VALUE ||
        psx_mod_read_word(ROWS + (GAME_ROWS - 1) * ROW_SIZE) != LAST_VALUE)
        return 0;
    for (unsigned i = 0; i < GAME_ROWS; i++) {
        uint32_t row = ROWS + i * ROW_SIZE, value = psx_mod_read_word(row);
        if ((value == MUSIC_OPTION || value == mem) && name_is(psx_mod_read_word(row + 4), "BGM SELECT")) return row;
    }
    return 0;
}
/* The four labels in guest memory, written as text: the overlay's own list
 * may not be loaded yet when the row first shows. */
static uint32_t build_labels(void) {
    uint32_t size = VALUES * 4;
    for (unsigned i = 0; i < VALUES; i++) size += (uint32_t)strlen(labels[i]) + 1;
    uint32_t list = psx_mod_alloc_guest_memory(size, 4), text = list + VALUES * 4;
    if (!list) return 0;
    for (unsigned i = 0; i < VALUES; i++) {
        psx_mod_write_word(list + i * 4, text);
        const char *s = labels[i];
        do psx_mod_write_byte(text++, (uint8_t)*s); while (*s++);
    }
    return list;
}
static void menu(void) {
    uint32_t row = bgm_row();
    if (!row) { shown = -1; return; }
    if (!label_list && !(label_list = build_labels())) return;
    if (psx_mod_read_word(row) != mem) psx_mod_write_word(row, mem);
    if (psx_mod_read_word(row + 8) != label_list) psx_mod_write_word(row + 8, label_list);
    if (psx_mod_read_byte(row + 13) != VALUES) psx_mod_write_byte(row + 13, VALUES);
    unsigned v = psx_mod_read_byte(mem);
    if (shown >= 0 && v != (unsigned)shown && v < VALUES) {          /* the player's choice */
        random_on = v == RANDOM;
        if (!forced) save();
        psx_mod_write_byte(MUSIC_OPTION, (uint8_t)(random_on ? REMIXED : v));
        fprintf(stderr, "BGM SELECT: set to %s\n", labels[v]);
    }
    unsigned want = random_on ? RANDOM : card_value();
    if (v != want) psx_mod_write_byte(mem, (uint8_t)want);
    shown = (int)want;
}

/* ---- The fight's draw ---- */

static void draw(const char *when) {
    unsigned v = tekken3_moveset_draw(2, &draw_state) ? ARCADE : REMIXED;
    psx_mod_write_byte(mem + 1, (uint8_t)(1 + v));
    events++;
    fprintf(stderr, "BGM SELECT: RANDOM, fight %u%s -> %s\n", ++fights, when, labels[v]);
}

void tekken3_bgm_select_fight(void) {
    read_setting();
    if (!mem) return;
    unsigned drawn = psx_mod_read_byte(mem + 1);
    if (continuing && drawn) {
        continuing = 0;
        if (random_on) fprintf(stderr, "BGM SELECT: Continue, the same fight keeps %s\n", labels[drawn - 1]);
        events++;
        return;
    }
    continuing = 0;
    if (!random_on) { if (drawn) psx_mod_write_byte(mem + 1, 0); return; }
    draw("");
}

/* The fight's music keeps its version over the Continue's screens, where it
 * goes on playing (a TTT stage's piece would start again otherwise). */
int tekken3_bgm_select_version(void) {
    read_setting();
    unsigned drawn = mem ? psx_mod_read_byte(mem + 1) : 0;
    if (!random_on || !drawn) return (int)psx_mod_read_byte(MUSIC_OPTION);
    return (int)drawn - 1;
}
/* What music_play starts: the fight's version in the fight, the card's
 * elsewhere (the selector, the results). */
static int started_version(void) { return in_fight() ? tekken3_bgm_select_version() : psx_mod_read_byte(MUSIC_OPTION); }

void tekken3_bgm_select_tick(void) {
    if (!psx_mod_game_started()) return;
    /* Allocated at the first frame of the game, always in the same order
     * with the other mods' first allocations: save states find it again. */
    if (!mem) {
        if (!(mem = psx_mod_alloc_guest_memory(4, 4))) return;
        fprintf(stderr, "BGM SELECT: the fight's draw kept at 0x%08X\n", mem + 1);
    }
    read_setting();
    menu();
    /* A Continue: in the fight, a human side handed to the CPU (as
     * src/tekken3_stage_source.c). Any screen but the fight, the loading
     * screen, the selector or screen 1 ends the match. */
    static uint16_t was_human[2];
    unsigned screen = psx_mod_read_half(SCREEN);
    if (screen != FIGHT && screen != LOADING && screen != SELECTOR && screen != 1) {
        continuing = 0; was_human[0] = was_human[1] = 0;
    }
    if (screen == FIGHT)
        for (unsigned p = 0; p < 2; p++) {
            uint16_t human = psx_mod_read_half(HUMAN + p * 2);
            if (was_human[p] && !human) continuing = 1;
            was_human[p] = human;
        }
}

/* music_play(n, loop): with RANDOM, in a fight, the fight's version in
 * 0x80097F05 while it reads it. */
extern void __real_func_8006AE14(CPUState *cpu);
void __wrap_func_8006AE14(CPUState *cpu) {
    unsigned own = psx_mod_read_byte(MUSIC_OPTION);
    read_setting();
    if (random_on && mem && in_fight() && !psx_mod_read_byte(mem + 1)) draw(" (at its music)");
    int v = started_version();
    if (random_on && mem && in_fight() && (cpu->pc == 0 || cpu->pc == MUSIC_PLAY)) {
        static unsigned logged_event = ~0u, logged_piece = ~0u;
        unsigned n = cpu->gpr[4] & 0xffff;
        if (n < 64 && (events != logged_event || n != logged_piece)) {
            fprintf(stderr, "BGM SELECT: music %u in %s (entry 0x%04X)\n", n, labels[v],
                    psx_mod_read_half(ENTRIES + n * 4 + (unsigned)v * 2));
            logged_event = events; logged_piece = n;
        }
    }
    if (v == (int)own) { __real_func_8006AE14(cpu); return; }
    psx_mod_write_byte(MUSIC_OPTION, (uint8_t)v);
    __real_func_8006AE14(cpu);
    psx_mod_write_byte(MUSIC_OPTION, (uint8_t)own);
}
