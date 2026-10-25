/* Rows added to the Options menu's GAME OPTION page, and its scrolling.
 *
 * The page is data in the options overlay (TIPS.md section 13): a stack of
 * menu levels at 0x800EAD24, 0x34 bytes each (+0 cursor, +0x14 first row's
 * y, +0x18 row spacing, +0x20 rows, +0x28 item count), the level shown in
 * the byte 0x800EC020. GAME OPTION is level 1: nine 20-byte rows from
 * 0x800B908C, then EXIT. A row is +0 the value byte's address, +4 its name,
 * +8 its label list, +12 1 (a row of values), +13 the number of values, +15
 * the default (drawn in green, any other value in white), +16 2, +18 the
 * modes lit in the box on the right.
 *
 * Eleven items fill the screen, down to y 456. With more, the game is given
 * a window of eleven out of the whole list (the game's nine rows copied again
 * every frame, the mods' rows, EXIT), and the window follows the cursor: it
 * keeps a row on screen past the cursor while there are more. The game moves
 * its cursor in 0x800DC804 (pad 0x800ADF00 | 0x800ADF02: +1 down, -1 up, the
 * ends wrapping) and plays sound 0x546C (0x800753BC, return 0x800DC890) with
 * the new cursor in s0 before it stores it, then reads the row under it and
 * draws the page: there the window and s0 are set for the whole list, so the
 * frame drawn is already the right one. Arrows over and under the list tell
 * that rows are hidden there (drawn in the display list, tekken3_native_moves.c).
 *
 * Nothing happens until a mod adds a row: without one the page is the game's. */
#include "tekken3_game_options.h"
#include "cpu_state.h"
#include "mod_plugins.h"
#include <stdio.h>
#include <string.h>

enum { SCREEN = 0x800ae204, OPTIONS = 5, LEVEL = 0x800ec020, ENTRY = 0x800ead58,
       DESCRIPTOR = ENTRY + 0x20, ROWS = 0x800b908c, GAME_ROWS = 9, ROW_SIZE = 20,
       GAME_ITEMS = GAME_ROWS + 1, VISIBLE = 11, MAX_ROWS = 8, MAX_LABELS = 16,
       MOVE_SOUND = 0x546c, MOVED = 0x800dc890, PAD = 0x800adf00 };

static uint32_t extra[MAX_ROWS], value_byte[MAX_ROWS];
static unsigned extras;
static uint32_t all, window;             /* the whole list; the eleven the game sees */
static unsigned top;                     /* the whole list's item at the window's top */

static uint32_t text(const char *s) {
    uint32_t n = (uint32_t)strlen(s) + 1, at = psx_mod_alloc_guest_memory(n, 4);
    for (uint32_t i = 0; at && i < n; i++) psx_mod_write_byte(at + i, (uint8_t)s[i]);
    return at;
}

int tekken3_game_options_add(const char *name, const char *const *labels, unsigned count,
                             unsigned value, unsigned default_value, unsigned modes) {
    if (extras >= MAX_ROWS || !count || count > MAX_LABELS) return -1;
    if (!all) {
        all = psx_mod_alloc_guest_memory((GAME_ITEMS + MAX_ROWS) * ROW_SIZE, 4);
        window = psx_mod_alloc_guest_memory(VISIBLE * ROW_SIZE, 4);
        if (!all || !window) { all = window = 0; return -1; }
    }
    uint32_t row = psx_mod_alloc_guest_memory(ROW_SIZE, 4), byte = psx_mod_alloc_guest_memory(4, 4);
    uint32_t list = psx_mod_alloc_guest_memory(count * 4, 4), title = text(name);
    if (!row || !byte || !list || !title) return -1;
    for (unsigned i = 0; i < count; i++) {
        uint32_t label = text(labels[i]);
        if (!label) return -1;
        psx_mod_write_word(list + i * 4, label);
    }
    psx_mod_write_word(byte, value < count ? value : 0);
    psx_mod_write_word(row, byte);
    psx_mod_write_word(row + 4, title);
    psx_mod_write_word(row + 8, list);
    psx_mod_write_word(row + 12, 1u | count << 8 | (default_value < count ? default_value : 0) << 24);
    psx_mod_write_word(row + 16, (modes & 0xffffu) << 16 | 2u);
    extra[extras] = row; value_byte[extras] = byte;
    fprintf(stderr, "Game options: %s row added to GAME OPTION (%u values)\n", name, count);
    return (int)extras++;
}

int tekken3_game_options_value(int row) {
    if (row < 0 || (unsigned)row >= extras) return -1;
    return psx_mod_read_byte(value_byte[row]);
}

static unsigned items(void) { return GAME_ITEMS + extras; }
static unsigned shown(void) { return items() < VISIBLE ? items() : VISIBLE; }

static void copy_row(uint32_t to, uint32_t from) {
    for (unsigned i = 0; i < ROW_SIZE; i += 4) {
        uint32_t w = psx_mod_read_word(from + i);
        if (psx_mod_read_word(to + i) != w) psx_mod_write_word(to + i, w);
    }
}
static void fill_window(void) {
    for (unsigned i = 0; i < shown(); i++) copy_row(window + i * ROW_SIZE, all + (top + i) * ROW_SIZE);
}

/* The game's page: its overlay's own table (first row the difficulty, last
 * the speaker), or our window over it. */
static int page_ours(void) {
    uint32_t rows = psx_mod_read_word(DESCRIPTOR);
    if (rows != ROWS && rows != window) return 0;
    if (rows == ROWS && psx_mod_read_word(DESCRIPTOR + 8) != GAME_ITEMS) return 0;
    return psx_mod_read_word(ROWS) == 0x80097f06 &&
           psx_mod_read_word(ROWS + (GAME_ROWS - 1) * ROW_SIZE) == 0x80097f04;
}

void tekken3_game_options_tick(void) {
    if (!extras || !psx_mod_game_started()) return;
    if (psx_mod_read_word(SCREEN) != OPTIONS) { top = 0; return; }
    if (!page_ours()) return;
    /* The game's nine rows every frame (the difficulty mod edits its own
     * in the game's table), the mods' rows, EXIT last. */
    for (unsigned i = 0; i < GAME_ROWS; i++) copy_row(all + i * ROW_SIZE, ROWS + i * ROW_SIZE);
    for (unsigned i = 0; i < extras; i++) copy_row(all + (GAME_ROWS + i) * ROW_SIZE, extra[i]);
    copy_row(all + (items() - 1) * ROW_SIZE, ROWS + GAME_ROWS * ROW_SIZE);
    if (psx_mod_read_word(DESCRIPTOR) == ROWS) top = 0;          /* the game set the page up again */
    if (top + shown() > items()) top = items() - shown();
    fill_window();
    if (psx_mod_read_word(DESCRIPTOR) != window) {
        psx_mod_write_word(DESCRIPTOR, window);
        psx_mod_write_word(DESCRIPTOR + 8, shown());
    }
}

/* The window that keeps item `at` on screen with one more item past it, as
 * far as the list goes. */
static unsigned top_for(unsigned at, unsigned from) {
    unsigned k = shown(), n = items(), t = from;
    if (at < t + 1) t = at ? at - 1 : 0;
    if (at + 2 > t + k) t = at + 2 - k;
    if (t + k > n) t = n - k;
    return t;
}

void tekken3_game_options_cursor(CPUState *cpu) {
    if (!extras || items() <= VISIBLE || cpu->gpr[5] != MOVE_SOUND || cpu->gpr[31] != MOVED ||
        cpu->gpr[19] != ENTRY || psx_mod_read_word(SCREEN) != OPTIONS ||
        psx_mod_read_word(DESCRIPTOR) != window)
        return;
    unsigned pad = psx_mod_read_half(PAD) | psx_mod_read_half(PAD + 2);
    int step = (int)(pad >> 14 & 1) - (int)(pad >> 12 & 1);
    if (!step) return;
    unsigned n = items(), from = top + psx_mod_read_word(ENTRY);
    unsigned at = (unsigned)((int)from + step + (int)n) % n;
    unsigned t = top_for(at, top);
    if (t != top) { top = t; fill_window(); }
    cpu->gpr[16] = at - top;
}

/* An arrow pointing up (dir -1) or down (dir 1), its tip at (x, y), 8 lines
 * high, outlined like the MOVESET card's. */
typedef struct { uint32_t at, end; unsigned words; } Prims;
static void put(Prims *p, uint32_t w) { if (p->at < p->end) { psx_mod_write_word(p->at, w); p->at += 4; p->words++; } }
static uint32_t xy(int x, int y) { return (uint32_t)(y & 0xffff) << 16 | (uint32_t)(x & 0xffff); }
static void triangle(Prims *p, uint32_t colour, int x0, int y0, int x1, int y1, int x2, int y2) {
    put(p, 0x20000000u | colour); put(p, xy(x0, y0)); put(p, xy(x1, y1)); put(p, xy(x2, y2));
}
enum { ARROW_X = 184, OUTLINE = 0x101010, ARROW = 0x38c8f8 };   /* 0xBBGGRR: (248, 200, 56) */
static void arrow(Prims *p, int y, int dir) {
    triangle(p, OUTLINE, ARROW_X, y, ARROW_X - 9, y - 8 * dir, ARROW_X + 9, y - 8 * dir);
    triangle(p, ARROW, ARROW_X, y - 2 * dir, ARROW_X - 6, y - 7 * dir, ARROW_X + 6, y - 7 * dir);
}

int tekken3_game_options_scrolls(void) {
    return extras && items() > VISIBLE && psx_mod_read_word(SCREEN) == OPTIONS &&
           psx_mod_read_byte(LEVEL) == 1 && psx_mod_read_word(DESCRIPTOR) == window;
}

uint32_t tekken3_game_options_arrows(uint32_t base, uint32_t bytes, uint32_t link, unsigned frame) {
    if (!tekken3_game_options_scrolls()) return link;
    int above = top > 0, below = top + shown() < items();
    int first = (int)psx_mod_read_word(ENTRY + 0x14), step = (int)psx_mod_read_word(ENTRY + 0x18);
    int sway = frame % 60 < 30;                                    /* a line out and back once a second */
    Prims p = { base + 4, base + bytes, 0 };
    /* A row's text is lines 1..14 of its row; the screen shows lines 20..467.
     * The tips 15 lines over the first row, 12 under the last one's text:
     * clear of the mode box above and of the screen's edge below. */
    if (above) arrow(&p, first - 14 - sway, -1);
    if (below) arrow(&p, first + ((int)shown() - 1) * step + 25 + sway, 1);
    psx_mod_write_word(base, (uint32_t)p.words << 24 | (link & 0xffffff));
    return base & 0xffffff;
}
