/* Arcade CPU difficulty levels in the Options menu, for the exact SLUS-00402
 * executable.
 *
 * The game chooses its CPU's behaviour in 0x80061488 from a table at
 * 0x800231AC: 3 difficulties (the menu's EASY / MEDIUM / HARD, capped at 2)
 * x 10 stages of 110-byte blocks, copied into the player's AI structure at
 * +568; the HARD / stage 10 block is also copied at +678. The arcade boards
 * carry the same blocks with more levels; tools/difficulty/import.py reads,
 * from the user's ROMs, the ones beyond the PS1 HARD into levels.bin.
 *
 * Menu. The GAME OPTION page is data in the options overlay: one 20-byte row
 * per setting (value address, name, label list, then a byte holding the
 * number of values). The DIFFICULTY LEVEL row gets a label list with the
 * extra levels after EASY / MEDIUM / HARD and its count raised, so the menu
 * cycles through them and saves the value like any other. The labels are
 * long, so while an extra level is shown the row is named LEVEL (the end of
 * the game's own "DIFFICULTY LEVEL") to leave them room.
 *
 * Game. A menu value past HARD selects extra level (value - 3): its ten
 * blocks are written over the three rows of the table, so the game's own code
 * reads them. The game's copy of the difficulty (0x800AE208, taken when a
 * mode starts) is held at HARD, the value its other readers (0x8005B5CC,
 * the arcade overlay) know. Back on EASY / MEDIUM / HARD, the original table
 * is put back. Ordinary stores above 0x10000 do not mark code pages dirty, so
 * none of this disturbs the recompiled code.
 *
 * TEKKEN3_DIFFICULTY=<key> forces a level whatever the menu says (scripts).
 * Research and usage: DIFFICULTY.md.
 */
#include "mod_plugins.h"
#include "psx_sdl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { TABLE = 0x800231AC, BLOCK = 110, STAGES = 10, ROWS = 3,
       HEADER = 16, KEY = 24, LABEL = 64, ENTRY = KEY + LABEL + STAGES * BLOCK,
       MAX_EXTRA = 16 };
/* Options menu (overlay) and the game's difficulty variables. */
enum { MENU_VALUE = 0x80097F06, GAME_VALUE = 0x800AE208,
       ROW = 0x800B908C,              /* DIFFICULTY LEVEL row: value, name, labels, count byte */
       ROW_NAME = 0x800B91D8,         /* "DIFFICULTY LEVEL" */
       ROW_SHORT = 0x800B91E3,        /* "LEVEL" */
       LABELS = 0x800EACC8 };         /* the game's EASY, MEDIUM, HARD list */

static unsigned char *levels;          /* levels.bin, validated */
static const unsigned char *reference[ROWS];   /* ps1-easy, ps1-medium, ps1-hard blocks */
static const unsigned char *extra[MAX_EXTRA];  /* levels beyond the PS1 HARD, easiest first */
static unsigned extras;
static const unsigned char *forced;    /* TEKKEN3_DIFFICULTY */
static uint32_t label_list;            /* guest copy of the menu's label list */
static int loaded, verified, refused, written;

static unsigned read_u32(const unsigned char *p) {
    return p[0] | p[1] << 8 | p[2] << 16 | (unsigned)p[3] << 24;
}

static void load(void) {
    loaded = 1;
    char path[1024];
    const char *env = getenv("TEKKEN3_DIFFICULTY_TABLE");
    if (env && *env) snprintf(path, sizeof path, "%s", env);
    else {
        const char *base = SDL_GetBasePath();
        if (!base) return;
        snprintf(path, sizeof path, "%smods/difficulty/levels.bin", base);
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "Difficulty: %s missing, run tools/difficulty/import.py\n", path); return; }
    fseek(f, 0, SEEK_END); long size = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *data = size > HEADER ? malloc((size_t)size) : NULL;
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size || memcmp(data, "T3DF", 4) ||
        read_u32(data + 4) != 1 || read_u32(data + 12) != BLOCK ||
        (unsigned long)size != HEADER + (unsigned long)read_u32(data + 8) * ENTRY) {
        fprintf(stderr, "Difficulty: %s is not a levels table\n", path);
        free(data); fclose(f); return;
    }
    fclose(f);
    static const char *rows[ROWS] = { "ps1-easy", "ps1-medium", "ps1-hard" };
    unsigned n = read_u32(data + 8);
    for (unsigned i = 0; i < n; i++) {
        const unsigned char *e = data + HEADER + i * ENTRY;
        int ref = -1;
        for (unsigned r = 0; r < ROWS; r++) if (!strncmp((const char *)e, rows[r], KEY)) ref = (int)r;
        if (ref >= 0) reference[ref] = e + KEY + LABEL;
        else if (extras < MAX_EXTRA) extra[extras++] = e;
    }
    if (!reference[0] || !reference[1] || !reference[2] || !extras) {
        fprintf(stderr, "Difficulty: %s lacks the game's rows or extra levels\n", path);
        free(data); memset(reference, 0, sizeof reference); extras = 0; return;
    }
    levels = data;
    const char *key = getenv("TEKKEN3_DIFFICULTY");
    if (key && *key) {
        for (unsigned i = 0; i < extras; i++)
            if (!strncmp((const char *)extra[i], key, KEY)) forced = extra[i];
        if (!forced) fprintf(stderr, "Difficulty: level '%s' not in the table\n", key);
        else fprintf(stderr, "Difficulty: CPU level forced to %s (%s)\n", key, (const char *)forced + KEY);
    }
}

static int table_is(const unsigned char *const rows[ROWS]) {
    for (unsigned r = 0; r < ROWS; r++)
        for (unsigned k = 0; k < STAGES * BLOCK; k++)
            if (psx_mod_read_byte(TABLE + r * STAGES * BLOCK + k) != rows[r][k]) return 0;
    return 1;
}

static void write_rows(const unsigned char *const rows[ROWS]) {
    for (unsigned r = 0; r < ROWS; r++)
        for (unsigned k = 0; k < STAGES * BLOCK; k++) {
            uint32_t a = TABLE + r * STAGES * BLOCK + k;
            if (psx_mod_read_byte(a) != rows[r][k]) psx_mod_write_byte(a, rows[r][k]);
        }
}

static void write_string(uint32_t a, const char *s) {
    do psx_mod_write_byte(a++, (uint8_t)*s); while (*s++);
}

/* The label list for the menu, built once in guest memory: EASY, MEDIUM,
 * HARD, then one string per extra level. The game's three labels are copied
 * as text rather than pointed at, since the overlay may not have loaded its
 * own list yet when the row first shows up. */
static uint32_t build_labels(void) {
    static const char *native[3] = { "EASY", "MEDIUM", "HARD" };
    char label[3 + MAX_EXTRA][LABEL + 1];
    unsigned n = 3 + extras;
    uint32_t size = n * 4;
    for (unsigned i = 0; i < n; i++) {
        if (i < 3) snprintf(label[i], sizeof label[i], "%s", native[i]);
        else { memcpy(label[i], extra[i - 3] + KEY, LABEL); label[i][LABEL] = 0; }
        size += (uint32_t)strlen(label[i]) + 1;
    }
    uint32_t list = psx_mod_alloc_guest_memory(size, 4);
    if (!list) return 0;
    uint32_t text = list + n * 4;
    for (unsigned i = 0; i < n; i++) {
        psx_mod_write_word(list + i * 4, text);
        write_string(text, label[i]);
        text += (uint32_t)strlen(label[i]) + 1;
    }
    return list;
}

/* The options overlay is resident when the DIFFICULTY LEVEL row is where it
 * belongs, pointing at the game's list or at ours. */
static int menu_resident(void) {
    if (psx_mod_read_word(ROW) != MENU_VALUE) return 0;
    uint32_t name = psx_mod_read_word(ROW + 4), list = psx_mod_read_word(ROW + 8);
    if (name != ROW_NAME && name != ROW_SHORT) return 0;
    if (list != LABELS && (!label_list || list != label_list)) return 0;
    static const char expected[] = "DIFFICULTY LEVEL";
    for (unsigned k = 0; k < sizeof expected; k++)
        if (psx_mod_read_byte(ROW_NAME + k) != (uint8_t)expected[k]) return 0;
    return 1;
}

static void menu(unsigned value) {
    if (!menu_resident()) return;
    if (!label_list && !(label_list = build_labels())) return;
    if (psx_mod_read_word(ROW + 8) != label_list) psx_mod_write_word(ROW + 8, label_list);
    if (psx_mod_read_byte(ROW + 13) != 3 + extras) psx_mod_write_byte(ROW + 13, (uint8_t)(3 + extras));
    uint32_t name = value >= 3 ? ROW_SHORT : ROW_NAME;
    if (psx_mod_read_word(ROW + 4) != name) psx_mod_write_word(ROW + 4, name);
}

static void tekken3_difficulty(void) {
    static unsigned tick;
    if (!psx_mod_game_started()) return;
    if (!loaded) load();
    if (!levels || refused) return;
    unsigned value = psx_mod_read_byte(MENU_VALUE);
    if (value >= 3 + extras) value = 2;          /* a save from a longer table */
    menu(value);
    const unsigned char *level = forced ? forced : value >= 3 ? extra[value - 3] : NULL;
    if (level && psx_mod_read_half(GAME_VALUE) > 2) psx_mod_write_half(GAME_VALUE, 2);
    if (tick++ % 30) return;
    if (!verified) {
        if (!table_is(reference)) {
            refused = 1;
            fprintf(stderr, "Difficulty: the game's CPU table is not the expected one, left unchanged\n");
            return;
        }
        verified = 1;
    }
    if (level) {
        const unsigned char *blocks = level + KEY + LABEL;
        const unsigned char *const rows[ROWS] = { blocks, blocks, blocks };
        write_rows(rows);
        written = 1;
    } else if (written) {
        write_rows(reference);
        written = 0;
    }
}

PSX_MOD_CONSTRUCTOR(tekken3_register_difficulty)
{
    (void)psx_mod_register_vblank_plugin("tekken3.arcade-difficulty", tekken3_difficulty);
}
