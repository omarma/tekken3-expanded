/* F18 (GH#148): the fight's stage picked at the selector, after Tekken Tag
 * Tournament's PS2 SCENE line (played on PCSX2, 2026-10-27): no screen of its
 * own, a line in the middle of VS BATTLE SELECT that both players change once
 * both have chosen (B127, the user's, 2026-10-29: TTT's lets the first one
 * done change it alone while the other chooses), the value kept for the next
 * fights, so that a rematch goes straight to the same stage.
 *
 * Two steps, the game then its stages (the user's, 2026-10-27): GAME is
 * DEFAULT (the game's rule and GAME OPTION's STAGES row, as without this line),
 * RANDOM (any stage of both games, drawn at each fight with the host's
 * generator), TEKKEN 3 or TEKKEN TAG TOURNAMENT; STAGE then lists that
 * game's, RANDOM (one of them) first.
 *
 * VS (mode 1): VS BATTLE SELECT (screen 10), player blocks at 0x800B8D70 +
 * 172 * player, +0 the state: 3 choosing, 4 the handicap's LIFE bar, 12 done
 * (grid_side_update, t3-ps1 src/chargement/800529C4.c: a face button takes
 * the handicap, 0xF0 of its pad). The last player's take, the other one in
 * state 12, is held: it opens the band on GAME for both pads (B127). Left and
 * right change the game; down goes to its STAGE, up back to GAME. Cross or
 * start, either player, hands the held take to the game, which then loads
 * the fight on the line's stage (one press more than the game's, the
 * rematches included: both players choose again in VS). Circle or select
 * goes back a step: from the STAGE to GAME, then, the last player's, back to
 * the handicap. Two takes in the same frame: the second one is held.
 * Practice (mode 5): the Arcade grid (screen 9), blocks at 0x8011864C +
 * 0x7C * player. Player 1's pad picks the dummy in block 2 (state 3); that
 * pick opens the band under the clock on GAME and waits: left and right
 * change it, cross or start goes to its STAGE (DEFAULT and RANDOM: takes it),
 * where cross or start takes the stage (the pick goes to the game then, its
 * button, so its costume); circle or select goes back a step, to the grid
 * from GAME. TTT's PS2 Practice has no stage choice (a dojo); this one is the
 * mod's own.
 *
 * The stages: Tekken 3's by fighter, the arena and the music of the
 * fighter's record (0x80097D40, bytes 10 and 11; the user's, 2026-10-27):
 * GUN JACK is Nina's arena with Gun Jack's piece. Grouped by arena, its owner
 * first; Xiaoyu's and Jin's second costumes fight at the school (arena 7) to
 * their own piece. The arcade stage with Arcade Stages, else the PS1's (Gon's
 * 13 and Dr. B's 14 the PS1's). TTT's stages 0..14 when TTT Stages can draw
 * them (TTT stage n on arena n, Eddy-A 13 on Eddy's 10, Unknown's 14 on
 * Ogre's 6), TEKKEN TAG TOURNAMENT left out otherwise; named as on TTT's PS2
 * line, each plays its own piece (src/tekken3_ttt_music.c) over the Tekken 3
 * piece of its owner, which plays when that piece does not (TTT's school:
 * Xiaoyu's, Unknown's: Ogre's). A stage and its music always go together,
 * RANDOM's draws too (the user's, 2026-10-27: TTT's school had played to
 * the deciding Paul's piece).
 *
 * The line shows only while it can be changed: in VS while the last take
 * waits, in Practice once the dummy is picked. Its first row
 * says STAGE SELECT (the user's, 2026-10-27), so that a player knows what it
 * is for.
 *
 * GAME OPTION's STAGE SELECT row (OFF, ON; ON the default) turns the line
 * off for those who want no press more (the user's, 2026-10-27): the fights
 * then load as without it. Kept in stage-select.txt ("select off").
 *
 * The arena is the game's at 0x800ADC84 (copy 0x800AFAA2), the music at
 * 0x800ADD08 (copy 0x800AFAA3), both set by 0x8004F3B0 from the deciding
 * fighter's record: written again every VBlank until the fight, as the
 * guests' (src/tekken3_ttt1_roster.c, which writes the same).
 * The choice is kept beside the memory card in stage-select.txt, a line per
 * mode ("vs ttt-5", "practice t3-random") and the row ("select on"). Benches: TEKKEN3_STAGE_SELECT
 * ("vs=t3-9,practice=random") overrides it, TEKKEN3_STAGE_SELECT_SEED fixes
 * RANDOM's draw. Feature stage-select of the package
 * tekken3.gameplay.stage-select: off, nothing of this runs. */
#include "tekken3_stage_select.h"
#include "tekken3_stage_source.h"
#include "tekken3_moveset_draw.h"
#include "tekken3_game_options.h"
#include "memcard.h"
#include "mod_plugins.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { SCREEN = 0x800ae204, PHASE = 0x800ae224, MODE = 0x800afa88, FIGHT = 8, ARCADE_GRID = 9, VS_GRID = 10,
       ARENA = 0x800adc84, ARENA_COPY = 0x800afaa2, MUSIC = 0x800add08, MUSIC_COPY = 0x800afaa3,
       VS_BLOCKS = 0x800b8d70, VS_STRIDE = 172, VS_CHOOSING = 3, VS_HANDICAP = 4, VS_DONE = 12,
       GRID_BLOCKS = 0x8011864c, GRID_STRIDE = 0x7c, CHOOSING = 1, CHOOSING_CPU = 3, ABSENT = 22,
       VS = 1, PRACTICE = 5, OPTIONS = 5, OPTION_MODES = 1u << VS | 1u << PRACTICE };
/* Pad bits, active low. */
enum { PAD_SELECT = 0x0001, PAD_START = 0x0008, PAD_UP = 0x0010, PAD_RIGHT = 0x0020, PAD_DOWN = 0x0040,
       PAD_LEFT = 0x0080, PAD_TRIANGLE = 0x1000, PAD_CIRCLE = 0x2000, PAD_CROSS = 0x4000, PAD_SQUARE = 0x8000,
       DIRECTIONS = PAD_UP | PAD_RIGHT | PAD_DOWN | PAD_LEFT,
       PICK = PAD_START | PAD_TRIANGLE | PAD_CIRCLE | PAD_CROSS | PAD_SQUARE,
       BAND_KEYS = PICK | PAD_SELECT | DIRECTIONS, INJECT_POLLS = 3 };
enum { LINE_VS = 0, LINE_PRACTICE = 1, LINES };
static const char *const line_words[LINES] = { "vs", "practice" };

/* The catalogue, by game: DEFAULT, RANDOM, then each game's RANDOM and
 * stages. name: on the STAGE step; full: the log; music: the record's piece
 * (a TTT stage: its owner's, under the TTT piece), -1 the game's. */
enum { GAME_DEFAULT, GAME_RANDOM, GAME_T3, GAME_TTT, GAMES };
static const char *const game_names[GAMES] = { "DEFAULT", "RANDOM", "TEKKEN 3", "TEKKEN TAG TOURNAMENT" };
typedef struct { int game, source, stage, arena, music; char word[24], name[16], full[24]; } Entry;
enum { DEFAULT, RANDOM, T3_STAGES = 24, MAX_ENTRIES = 2 + 1 + T3_STAGES + 1 + 15 };
/* Tekken 3's: arena and music of each record (SLUS-00402, read 2026-10-27). */
static const struct { int arena, music; const char *name; } t3_stages[T3_STAGES] = {
    { 0, 0x07, "PAUL" }, { 0, 0x13, "BRYAN" }, { 1, 0x08, "LAW" }, { 1, 0x12, "KUMA" },
    { 2, 0x0b, "YOSHIMITSU" }, { 2, 0x16, "MOKUJIN" }, { 3, 0x0e, "XIAOYU" }, { 4, 0x0d, "HWOARANG" },
    { 5, 0x09, "LEI" }, { 6, 0x15, "OGRE" }, { 6, 0x1b, "TRUE OGRE" }, { 7, 0x0e, "XIAOYU SCHOOL" },
    { 7, 0x10, "JIN SCHOOL" }, { 8, 0x10, "JIN" }, { 9, 0x0c, "NINA" }, { 9, 0x18, "ANNA" },
    { 9, 0x17, "GUN JACK" }, { 10, 0x0f, "EDDY" }, { 10, 0x1c, "TIGER" }, { 11, 0x0a, "KING" },
    { 12, 0x11, "JULIA" }, { 12, 0x14, "HEIHACHI" }, { 13, 0x1a, "GON" }, { 14, 0x19, "DR B" } };
/* TTT's in the PS2 line's order: Eddy-B (10), Eddy-A (13), then King; the
 * Tekken 3 piece of the stage's owner under each. */
static const struct { int stage, arena, music; const char *name; } ttt_stages[15] = {
    { 0, 0, 0x07, "PAUL" }, { 1, 1, 0x08, "LAW" }, { 2, 2, 0x0b, "YOSHIMITSU" }, { 3, 3, 0x0e, "XIAOYU" },
    { 4, 4, 0x0d, "HWOARANG" }, { 5, 5, 0x09, "LEI" }, { 6, 6, 0x15, "OGRE" }, { 7, 7, 0x0e, "SCHOOL" },
    { 8, 8, 0x10, "JIN" }, { 9, 9, 0x0c, "NINA" }, { 10, 10, 0x0f, "EDDY B" }, { 13, 10, 0x0f, "EDDY A" },
    { 11, 11, 0x0a, "KING" }, { 12, 12, 0x14, "HEIHACHI" }, { 14, 6, 0x15, "UNKNOWN" } };
static Entry entries[MAX_ENTRIES];
static int entry_count;

static int on;                           /* the feature, at activation */
static int enabled = 1;                  /* GAME OPTION's STAGE SELECT row */
static int row = -1;
static int chosen[LINES];                /* each mode's line, an entry */
static int forced;                       /* TEKKEN3_STAGE_SELECT */
static uint64_t draw_state;
static Entry fight;                      /* the fight that loads */
static int fight_mode = -1, arena_pending;

/* arena -1: DEFAULT or a RANDOM. Words: default, random, t3-random,
 * t3-gun-jack (the name, lower case, dashes), ttt-random, ttt-N. */
static void add(int game, int source, int stage, int arena, int music, const char *name) {
    static const char *const prefix[GAMES] = { "default", "random", "t3", "ttt" }, *const shown[GAMES] = { "", "", "T3", "TTT" };
    Entry *e = &entries[entry_count++];
    e->game = game; e->source = source; e->stage = stage; e->arena = arena; e->music = music;
    snprintf(e->name, sizeof e->name, "%s", name);
    if (game < GAME_T3) {
        snprintf(e->word, sizeof e->word, "%s", prefix[game]);
        snprintf(e->full, sizeof e->full, "%s", name);
        return;
    }
    if (arena < 0) snprintf(e->word, sizeof e->word, "%s-random", prefix[game]);
    else if (source == TEKKEN3_STAGE_TTT) snprintf(e->word, sizeof e->word, "%s-%d", prefix[game], stage);
    else {
        int n = snprintf(e->word, sizeof e->word, "%s-", prefix[game]);
        for (const char *c = name; *c && n < (int)sizeof e->word - 1; c++)
            e->word[n++] = *c == ' ' ? '-' : (char)(*c >= 'A' && *c <= 'Z' ? *c - 'A' + 'a' : *c);
        e->word[n] = 0;
    }
    snprintf(e->full, sizeof e->full, "%s %s", shown[game], name);
}
static void build_catalogue(void) {
    entry_count = 0;
    add(GAME_DEFAULT, TEKKEN3_STAGE_T3, -1, -1, -1, "DEFAULT");
    add(GAME_RANDOM, TEKKEN3_STAGE_T3, -1, -1, -1, "RANDOM");
    add(GAME_T3, TEKKEN3_STAGE_T3, -1, -1, -1, "RANDOM");
    for (int i = 0; i < T3_STAGES; i++)
        add(GAME_T3, TEKKEN3_STAGE_T3, -1, t3_stages[i].arena, t3_stages[i].music, t3_stages[i].name);
    const char *e = getenv("TEKKEN3_STAGES_TTT");
    if (!tekken3_arcade_stages_source_ready(TEKKEN3_STAGE_TTT) && !(e && *e == '1')) return;
    add(GAME_TTT, TEKKEN3_STAGE_TTT, -1, -1, -1, "RANDOM");
    for (int i = 0; i < 15; i++)
        add(GAME_TTT, TEKKEN3_STAGE_TTT, ttt_stages[i].stage, ttt_stages[i].arena, ttt_stages[i].music,
            ttt_stages[i].name);
}
static int entry_of(const char *word) {
    for (int i = 0; i < entry_count; i++) if (!strcmp(entries[i].word, word)) return i;
    return DEFAULT;
}

static void setting_path(char *out, size_t size) {
    const char *card = NULL; out[0] = 0;
    if (memcard_debug_info(0, &card, NULL, NULL, NULL) || !card || !*card) return;
    const char *slash = strrchr(card, '/'), *back = strrchr(card, '\\');
    if (back && (!slash || back > slash)) slash = back;
    int n = slash ? (int)(slash - card) : 1;
    snprintf(out, size, "%.*s/stage-select.txt", n, slash ? card : ".");
}
static void save(void) {
    if (forced) return;
    char path[4096]; setting_path(path, sizeof path);
    FILE *f = path[0] ? fopen(path, "wb") : NULL;
    if (!f) return;
    for (int i = 0; i < LINES; i++) fprintf(f, "%s %s\n", line_words[i], entries[chosen[i]].word);
    fprintf(f, "select %s\n", enabled ? "on" : "off");
    fclose(f);
}
/* "vs ttt-5" lines (the file) or "vs=ttt-5,practice=default,select=off"
 * (the bench's). */
static void parse(const char *text) {
    char line[16], word[24];
    while (*text) {
        if (sscanf(text, " %15[a-z] %*[=] %23[a-z0-9-]", line, word) == 2 ||
            sscanf(text, " %15[a-z] %23[a-z0-9-]", line, word) == 2)
        {
            for (int i = 0; i < LINES; i++) if (!strcmp(line, line_words[i])) chosen[i] = entry_of(word);
            if (!strcmp(line, "select")) enabled = strcmp(word, "off") != 0;
        }
        const char *next = strpbrk(text, ",\n");
        if (!next) break;
        text = next + 1;
    }
}
/* Once the game runs: the engine's packs are known by then. */
static void ready(void) {
    static int done;
    if (done) return;
    done = 1;
    build_catalogue();
    const char *e = getenv("TEKKEN3_STAGE_SELECT");
    if (e && *e) { parse(e); forced = 1; }
    else {
        char path[4096], text[256] = "";
        setting_path(path, sizeof path);
        FILE *f = path[0] ? fopen(path, "rb") : NULL;
        if (f) { text[fread(text, 1, sizeof text - 1, f)] = 0; fclose(f); }
        parse(text);
    }
    const char *seed = getenv("TEKKEN3_STAGE_SELECT_SEED");
    tekken3_moveset_seed(&draw_state, seed && *seed ? strtoull(seed, NULL, 0)
        : (uint64_t)time(NULL) * 1000003u + (uint64_t)clock() + (uint64_t)(uintptr_t)&draw_state);
    int stages = 0;
    for (int i = 0; i < entry_count; i++) stages += entries[i].arena >= 0;
    fprintf(stderr, "Stage select: %d stages (TTT's %s), VS %s, Practice %s, STAGE SELECT %s%s\n", stages,
            entries[entry_count - 1].game == GAME_TTT ? "in" : "out", entries[chosen[LINE_VS]].word,
            entries[chosen[LINE_PRACTICE]].word, enabled ? "ON" : "OFF", forced ? " (TEKKEN3_STAGE_SELECT)" : "");
}

static int line_of(unsigned mode) { return mode == VS ? LINE_VS : mode == PRACTICE ? LINE_PRACTICE : -1; }

void tekken3_stage_select_fight(unsigned mode) {
    fight_mode = -1; arena_pending = 0;
    if (!on) return;
    ready();
    int line = enabled ? line_of(mode) : -1;
    if (line < 0) return;
    int i = chosen[line];
    if (i == DEFAULT) return;
    if (entries[i].arena < 0) {          /* RANDOM: a stage of both games, or of its own */
        int pool[MAX_ENTRIES], n = 0;
        for (int j = 0; j < entry_count; j++)
            if (entries[j].arena >= 0 && (i == RANDOM || entries[j].game == entries[i].game)) pool[n++] = j;
        i = pool[tekken3_moveset_draw((unsigned)n, &draw_state)];
    }
    fight = entries[i]; fight_mode = (int)mode; arena_pending = 1;
    char music[24] = "the stage's music";
    if (fight.music >= 0) snprintf(music, sizeof music, "music 0x%02X", fight.music);
    fprintf(stderr, "Stage select: %s fight on %s (arena %d, %s%s)\n", mode == VS ? "VS" : "Practice",
            fight.full, fight.arena, music, i != chosen[line] ? ", RANDOM" : "");
}
int tekken3_stage_select_choice(unsigned mode, int *source, int *ttt_stage, int *arena) {
    if (fight_mode < 0 || (unsigned)fight_mode != mode) return 0;
    *source = fight.source; *ttt_stage = fight.stage; *arena = fight.arena;
    return 1;
}
int tekken3_stage_select_arena(void) { return fight_mode >= 0 ? fight.arena : -1; }
int tekken3_stage_select_music(void) { return fight_mode >= 0 ? fight.music : -1; }

/* ---- The selectors ---- */

static unsigned vs_state(unsigned p) { return psx_mod_read_word(VS_BLOCKS + p * VS_STRIDE); }
static int vs_open(void) {
    if (psx_mod_read_word(SCREEN) != VS_GRID || psx_mod_read_word(MODE) != VS) return 0;
    unsigned s = vs_state(0);
    return s == VS_CHOOSING || s == VS_HANDICAP || s == VS_DONE;
}
/* VS BATTLE SELECT's band: waiting, the player whose handicap take waits on
 * it (the last one done), -1 closed; take, that button; vs_inject: the polls
 * left that hand it to the game, to player target; vs_hold[pad]: the band's
 * keys stay away from the game until let go; passed[pad]: the VBlank of the
 * last take let through, the player done by the next frame. */
static unsigned vblanks;
static int waiting = -1, vs_inject, target;
static uint16_t take, vs_hold[2];
static unsigned passed[2];
enum { TAKES = PAD_TRIANGLE | PAD_CIRCLE | PAD_CROSS | PAD_SQUARE, TAKE_FRAMES = 2 };
static int done_by_now(unsigned p) {
    unsigned s = vs_state(p);
    return s == VS_DONE || (s == VS_HANDICAP && vblanks - passed[p] <= TAKE_FRAMES);
}
static int vs_waits(void) {
    return waiting >= 0 && vs_open() && vs_state((unsigned)waiting) == VS_HANDICAP && done_by_now((unsigned)waiting ^ 1);
}
static unsigned grid_state(unsigned p) { return psx_mod_read_word(GRID_BLOCKS + p * GRID_STRIDE); }
/* The Practice grid while player 1's pad picks the dummy. */
static int practice_dummy(void) {
    return psx_mod_read_word(SCREEN) == ARCADE_GRID && psx_mod_read_word(MODE) == PRACTICE &&
           psx_mod_read_word(0x8010ff4c) == 0x27bdffd0 && psx_mod_read_half(PHASE) <= 1 &&
           grid_state(0) != CHOOSING && grid_state(1) == CHOOSING_CPU;
}

/* Each line's step: 0 GAME, 1 STAGE (DEFAULT and RANDOM have none). */
static int on_stage[LINES];
static int has_stages(int line) { return entries[chosen[line]].game >= GAME_T3; }

/* GAME: the next game, on the same arena's stage (Tekken 3's n <-> TTT's
 * stage n, Eddy-A and Unknown to Eddy's and Ogre's), RANDOM to RANDOM, else
 * its first stage. STAGE: the next of the game's. */
static void step(int line, int by, unsigned player) {
    const Entry *e = &entries[chosen[line]];
    int i = chosen[line], n = entry_count;
    if (!on_stage[line]) {
        int games = entries[n - 1].game + 1, game = (e->game + by + games) % games, first;
        for (first = 0; entries[first].game != game; first++) {}
        i = first;
        if (game >= GAME_T3) {
            i = first + 1;
            for (int j = first; e->game >= GAME_T3 && j < n && entries[j].game == game; j++)
                if (e->arena < 0 ? entries[j].arena < 0
                    : entries[j].arena == e->arena && (e->source == TEKKEN3_STAGE_TTT || entries[j].stage == e->arena))
                    { i = j; break; }
        }
        fprintf(stderr, "Stage select: P%u sets the %s game to %s (%s)\n", player + 1, line ? "Practice" : "VS",
                game_names[game], entries[i].full);
    } else {
        do i = (i + by + n) % n; while (entries[i].game != e->game);
        fprintf(stderr, "Stage select: P%u sets the %s stage to %s\n", player + 1, line ? "Practice" : "VS",
                entries[i].full);
    }
    chosen[line] = i;
    save();
}

/* The Practice band: open[pad] the button that picked the dummy while it is
 * open, 0 closed; inject: that button, handed on for a few polls once taken;
 * hold: the band's keys stay away from the game until let go. */
static uint16_t band, injecting, hold;
static int inject;

uint16_t tekken3_stage_select_input(int player, uint16_t buttons) {
    static uint16_t previous[2] = { 0xffff, 0xffff };
    if (!on || player < 0 || player > 1 || !psx_mod_game_started()) return buttons;
    unsigned p = (unsigned)player;
    uint16_t edges = previous[p] & (uint16_t)~buttons;
    previous[p] = buttons;
    ready();
    if (!enabled) return buttons;
    if (vs_open()) {
        if (vs_inject > 0 && p == (unsigned)target) { vs_inject--; return (uint16_t)~take; }
        if (waiting >= 0 && !vs_waits()) waiting = -1;           /* the take was undone */
        if (waiting >= 0) {
            int *stage = &on_stage[LINE_VS];
            if (edges & (PAD_LEFT | PAD_RIGHT)) step(LINE_VS, edges & PAD_LEFT ? -1 : 1, p);
            else if ((edges & PAD_DOWN) && !*stage && has_stages(LINE_VS)) *stage = 1;
            else if (edges & PAD_UP) *stage = 0;
            else if (edges & (PAD_CROSS | PAD_START)) {
                target = waiting; vs_inject = INJECT_POLLS; waiting = -1; vs_hold[0] = vs_hold[1] = BAND_KEYS;
                fprintf(stderr, "Stage select: P%u takes %s for VS, P%d's handicap goes to the game\n", p + 1,
                        entries[chosen[LINE_VS]].full, target + 1);
            } else if ((edges & (PAD_CIRCLE | PAD_SELECT)) && *stage) *stage = 0;
            else if ((edges & (PAD_CIRCLE | PAD_SELECT)) && p == (unsigned)waiting) {
                waiting = -1; vs_hold[0] = vs_hold[1] = BAND_KEYS;
                fprintf(stderr, "Stage select: VS, back to P%u's handicap\n", p + 1);
            }
            return 0xffff;                   /* the grid stays still */
        }
        vs_hold[p] &= (uint16_t)~buttons;
        if (vs_state(p) == VS_HANDICAP && (edges & TAKES)) {
            if (done_by_now(p ^ 1)) {        /* the last one: both choose the stage */
                take = (uint16_t)(edges & TAKES & -(edges & TAKES));
                waiting = (int)p; vs_hold[p] = BAND_KEYS; on_stage[LINE_VS] = 0;
                fprintf(stderr, "Stage select: VS, P%u done last, the handicap waits on the STAGE band\n", p + 1);
                return 0xffff;
            }
            passed[p] = vblanks;
        }
        return buttons | vs_hold[p];
    }
    waiting = -1; vs_inject = 0; vs_hold[p] = 0;      /* a take still held off the screen: not the next one's */
    if (p != 0 || !practice_dummy()) { if (p == 0) band = inject = hold = 0; return buttons; }
    if (inject > 0) { inject--; return (uint16_t)~injecting; }
    if (band) {
        int *stage = &on_stage[LINE_PRACTICE];
        if (edges & (PAD_LEFT | PAD_RIGHT)) step(LINE_PRACTICE, edges & PAD_LEFT ? -1 : 1, p);
        else if ((edges & (PAD_CROSS | PAD_START | PAD_DOWN)) && !*stage && has_stages(LINE_PRACTICE)) *stage = 1;
        else if (edges & PAD_UP) *stage = 0;
        else if (edges & (PAD_CROSS | PAD_START)) {
            injecting = band; inject = INJECT_POLLS; band = 0; hold = BAND_KEYS;
            fprintf(stderr, "Stage select: Practice takes %s\n", entries[chosen[LINE_PRACTICE]].full);
        } else if ((edges & (PAD_CIRCLE | PAD_SELECT)) && *stage) *stage = 0;
        else if (edges & (PAD_CIRCLE | PAD_SELECT)) {
            band = 0; hold = BAND_KEYS;
            fprintf(stderr, "Stage select: Practice, back to the grid\n");
        }
        return 0xffff;                   /* the grid stays still */
    }
    hold &= (uint16_t)~buttons;          /* held keys, still down */
    /* Start with Select held leaves the mode, both punches are Devil Jin's
     * (src/tekken3_ttt1_selector.c): the game's. Start picks only a fighter
     * with a third costume (its bit of 0x80097EF4 for a native). */
    int leaving = (!(buttons & PAD_SELECT) && (edges & PAD_START)) ||
                  (!(buttons & PAD_SQUARE) && !(buttons & PAD_TRIANGLE));
    uint16_t picks = edges & PICK;
    unsigned under = psx_mod_read_word(GRID_BLOCKS + GRID_STRIDE + 0x1c);
    if (under < ABSENT && !(psx_mod_read_word(0x80097ef4) >> (under & 31) & 1)) picks &= (uint16_t)~PAD_START;
    if (picks && !leaving) {
        band = (uint16_t)(picks & -picks);
        hold = BAND_KEYS; on_stage[LINE_PRACTICE] = 0;
        fprintf(stderr, "Stage select: Practice, the dummy's pick waits on the STAGE band\n");
        return 0xffff;
    }
    return buttons | hold;
}

/* GAME and the game while on GAME, the game and the stage on STAGE. */
static void shown(int line, const char **label, const char **name) {
    const Entry *e = &entries[chosen[line]];
    if (!on_stage[line]) { *label = "GAME"; *name = game_names[e->game]; }
    else { *label = game_names[e->game]; *name = e->name; }
}
/* Only while the line can be changed: it keeps no room on the screen
 * otherwise (the user's, 2026-10-27). */
int tekken3_stage_select_line(const char **label, const char **name, int *arrows) {
    if (!on || !psx_mod_game_started()) return 0;
    ready();
    if (!enabled) return 0;
    if (vs_open()) {
        if (!vs_waits()) return 0;
        *arrows = 3;
        shown(LINE_VS, label, name);
        return 1;
    }
    if (band && practice_dummy()) {
        *arrows = 2;
        shown(LINE_PRACTICE, label, name);
        return 2;
    }
    return 0;
}

/* ---- Every VBlank ---- */

/* GAME OPTION's row, added at the first visit of the Options screen. */
static void menu(void) {
    static const char *const labels[2] = { "OFF", "ON" };
    static int row_value = -1;
    ready();
    if (row < 0) {
        row = tekken3_game_options_add("STAGE SELECT", labels, 2, (unsigned)enabled, 1, OPTION_MODES);
        row_value = enabled;
        if (row < 0) return;
    }
    int v = tekken3_game_options_value(row);
    if (v >= 0 && v != row_value) {
        row_value = enabled = v;
        save();
        fprintf(stderr, "Stage select: STAGE SELECT set to %s\n", enabled ? "ON" : "OFF");
    }
}

static void tick(void) {
    vblanks++;
    if (!psx_mod_game_started()) return;
    unsigned screen = psx_mod_read_word(SCREEN);
    if (on && screen == OPTIONS) menu();
    if (band && !practice_dummy()) band = 0;          /* the clock picked, the grid left */
    if (!arena_pending) return;
    if (screen == FIGHT) { arena_pending = 0; return; }
    if (psx_mod_read_half(ARENA) != (uint16_t)fight.arena) psx_mod_write_half(ARENA, (uint16_t)fight.arena);
    if (psx_mod_read_byte(ARENA_COPY) != (uint8_t)fight.arena) psx_mod_write_byte(ARENA_COPY, (uint8_t)fight.arena);
    if (fight.music < 0) return;
    if (psx_mod_read_half(MUSIC) != (uint16_t)fight.music) psx_mod_write_half(MUSIC, (uint16_t)fight.music);
    if (psx_mod_read_byte(MUSIC_COPY) != (uint8_t)fight.music) psx_mod_write_byte(MUSIC_COPY, (uint8_t)fight.music);
}

static void activate(void) {
    on = 1;
    fprintf(stderr, "Stage select: on\n");
}

PSX_MOD_CONSTRUCTOR(tekken3_register_stage_select) {
    (void)psx_mod_register_activation_plugin("tekken3.stage-select", activate);
    (void)psx_mod_register_vblank_plugin("tekken3.stage-select", tick);
}
