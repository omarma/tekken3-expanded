/* Devil's and Angel's PS2 laser, steps 3 and 4 (TIPS.md section 164): the
 * textures read on the TTT PS2 disc (tools/ps2/ttt_laser_install.py, section
 * 163) in the upper VRAM half, and GAME OPTION's PS2 EFFECTS row (OFF, ON).
 *
 * The pack (mods/ttt-ps2-laser): ps2-laser.tim (Devil's) and
 * ps2-laser-angel.tim (Angel's, the same images with gold palettes), 32 4-bit
 * TIMs each: 0 a 128 x 128 image of Devil's strong-hit set (not the laser's,
 * not loaded), 1..15 the orb, 16..23 the beam's series A, 24..31 its series B;
 * version.txt = PACK_VERSION. Read at activation; the upper half is made only
 * for a pack read whole (the renderer compiles its upper-half shader only if
 * the half exists when it starts).
 *
 * The images take 24 cells of 16 x 64 halfwords (15 orbs, 8 cells of two
 * 64 x 32 segments, 1 of palettes: rows 0..30 Devil's, 32..62 Angel's),
 * chosen from the bottom right of the upper half up and left, outside the
 * loaded stage (tekken3_stage_high_vram_used), TTT Hitspark's cells
 * (tekken3_hit_effect_high_vram_used) and the wolf's pages while Unknown
 * fights (tekken3_ttt1_wolf_high_vram_used); chosen again with each stage
 * pack and when the wolf comes or goes, and placed whenever Devil or Angel
 * fights and the half does not hold them (a save state may have other
 * images there). Too few cells: the arcade's yellow beam, said in the log.
 *
 * PS2 EFFECTS turns the TTT PS2 content on together, as the user chose
 * (2026-10-24): these lasers, and the PS2 strong-hit effects of the Mishima
 * once they come (tekken3_ps2_effects_on). It shows only for a pack read and
 * an upper half the renderer draws (not Vulkan); OFF by default (the user,
 * 2026-10-25). The choice is kept beside the memory card in
 * ttt-ps2-effects.txt (off or on).
 * TEKKEN3_PS2_EFFECTS=off|on overrides it (benches). */
#include "tekken3_ttt1_ps2_laser.h"
#include "tekken3_game_options.h"
#include "gpu.h"
#include "memcard.h"
#include "mod_plugins.h"
#include "psx_sdl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { PACK_VERSION = 3,                /* tools/ps2/laser_version.py LASER_VERSION */
       TIMS = 32, ORB_BYTES = 16 * 64 * 2, SEGMENT_BYTES = 16 * 32 * 2,
       CELLS = TEKKEN3_PS2_LASER_ORBS + 8 + 1, PALETTE_CELL = CELLS - 1, ANGEL_ROW = 32,
       SCREEN = 0x800ae204, OPTIONS = 5, FIGHT = 8,
       LASER_MODES = 0x1bf };           /* Arcade .. Practice, Tekken Ball, Tekken Force */
enum { SET_OFF, SET_ON, SETTINGS, DEFAULT_SETTING = SET_OFF };
static const char *const words[SETTINGS] = { "off", "on" };
static const char *const labels[SETTINGS] = { "OFF", "ON" };

static struct {
    int ok, upper;
    unsigned char *file[2];             /* Devil's, Angel's */
    const uint16_t *pixels[TEKKEN3_PS2_LASER_IMAGES];        /* Devil's file */
    const uint16_t *palette[2][TEKKEN3_PS2_LASER_IMAGES];
    uint32_t packets;                   /* 2 players x 2 buffers */
    int packets_tried;
} pack;
static struct {
    int chosen;                         /* -1 too few cells, 0 not chosen, 1 chosen */
    unsigned generation; int wolf;      /* what the cells were chosen around */
    uint16_t x[CELLS], y[CELLS];
    Tekken3Ps2LaserImage image[2][TEKKEN3_PS2_LASER_IMAGES];
} cells;
static int setting = -1, forced, row = -1, shown = -1;

/* What else holds the upper half: the loaded stage, TTT Hitspark, the wolf. */
extern int tekken3_stage_high_vram_used(int x, int y, int w, int h);
extern unsigned tekken3_stage_high_vram_generation(void);
extern int tekken3_hit_effect_high_vram_used(int x, int y, int w, int h);
extern int tekken3_ttt1_wolf_high_vram_used(int x, int y, int w, int h);
extern int tekken3_ttt1_has_lasers(unsigned p);
extern const char *tekken3_guest_moves_prefix_for(unsigned player);

/* --- The pack ------------------------------------------------------------ */

static unsigned char *read_file(const char *dir, const char *name, long *size) {
    char path[4096];
    if (snprintf(path, sizeof path, "%s/%s", dir, name) >= (int)sizeof path) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *b = n > 0 && n < 1024 * 1024 ? malloc((size_t)n) : NULL;
    if (b && fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); b = NULL; }
    fclose(f);
    *size = n;
    return b;
}
static uint32_t u32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static unsigned u16(const unsigned char *p) { return p[0] | p[1] << 8; }

/* 32 4-bit TIMs end to end, each a 16 x 1 palette then its image: 0 is
 * 32 x 128 halfwords, 1..15 16 x 64, 16..31 16 x 32. */
static int parse(const unsigned char *b, long size, const uint16_t **pixels, const uint16_t **palettes) {
    long at = 0;
    for (unsigned k = 0; k < TIMS; k++) {
        if (at + 8 + 12 + 32 + 12 > size || u32(b + at) != 0x10 || u32(b + at + 4) != 8) return 0;
        const unsigned char *clut = b + at + 8, *img = clut + 44;
        if (u32(clut) != 44 || u16(clut + 8) != 16 || u16(clut + 10) != 1) return 0;
        unsigned w = u16(img + 8), h = u16(img + 10), want_h = k == 0 ? 128 : k <= 15 ? 64 : 32;
        if (w != (k ? 16u : 32u) || h != want_h || u32(img) != 12 + 2 * w * h || img + u32(img) > b + size) return 0;
        if (k) {
            palettes[k - 1] = (const uint16_t *)(clut + 12);
            if (pixels) pixels[k - 1] = (const uint16_t *)(img + 12);
        }
        at = img + u32(img) - b;
    }
    return at == size;
}

static const char *pack_dir(void) {
    static char dir[4096];
    if (dir[0]) return dir;
    const char *e = getenv("TEKKEN3_TTT_PS2_LASER_DIR");
    if (e && *e) snprintf(dir, sizeof dir, "%s", e);
    else {
        const char *base = SDL_GetBasePath();
        snprintf(dir, sizeof dir, "%smods/ttt-ps2-laser", base ? base : "");
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
    return dir;
}

/* Where the PS2 EFFECTS pack is (the strong-hit effects' .hfx too). */
const char *tekken3_ps2_effects_dir(void) { return pack_dir(); }

static void ps2_laser_activate(void) {
    const char *dir = pack_dir();
    long size[2] = { 0, 0 }, vsize = 0;
    unsigned char *version = read_file(dir, "version.txt", &vsize);
    if (!version) {
        fprintf(stderr, "PS2 lasers: no pack in %s (the setup makes it from the TTT PS2 disc), the arcade's beam\n", dir);
        return;
    }
    char text[16] = { 0 };
    memcpy(text, version, vsize < 15 ? (size_t)vsize : 15);
    free(version);
    int v = atoi(text);
    if (v != PACK_VERSION) {
        fprintf(stderr, "PS2 lasers: pack version %d, this build reads %d (run the setup again), the arcade's beam\n",
                v, PACK_VERSION);
        return;
    }
    pack.file[0] = read_file(dir, "ps2-laser.tim", &size[0]);
    pack.file[1] = read_file(dir, "ps2-laser-angel.tim", &size[1]);
    const uint16_t *angel_pixels[TEKKEN3_PS2_LASER_IMAGES];
    int good = pack.file[0] && pack.file[1] && parse(pack.file[0], size[0], pack.pixels, pack.palette[0]) &&
               parse(pack.file[1], size[1], angel_pixels, pack.palette[1]);
    for (unsigned i = 0; good && i < TEKKEN3_PS2_LASER_IMAGES; i++)
        good = !memcmp(pack.pixels[i], angel_pixels[i], i < TEKKEN3_PS2_LASER_ORBS ? ORB_BYTES : SEGMENT_BYTES);
    if (!good) {
        fprintf(stderr, "PS2 lasers: %s/ps2-laser.tim or ps2-laser-angel.tim missing or unreadable, the arcade's beam\n", dir);
        free(pack.file[0]); free(pack.file[1]); pack.file[0] = pack.file[1] = NULL;
        return;
    }
    pack.ok = 1;
    pack.upper = psx_mod_gpu_high_vram_enable();
    fprintf(stderr, "PS2 lasers: pack version %d read, %s\n", v,
            pack.upper ? "upper VRAM half on" : "no upper VRAM half, the arcade's beam");
}

/* --- PS2 EFFECTS --------------------------------------------------------- */

static void setting_path(char *out, size_t size) {
    const char *card = NULL; out[0] = 0;
    if (memcard_debug_info(0, &card, NULL, NULL, NULL) || !card || !*card) return;
    const char *slash = strrchr(card, '/'), *back = strrchr(card, '\\');
    if (back && (!slash || back > slash)) slash = back;
    int n = slash ? (int)(slash - card) : 1;
    snprintf(out, size, "%.*s/ttt-ps2-effects.txt", n, slash ? card : ".");
}
static int parse_setting(const char *word) {
    for (int i = 0; i < SETTINGS; i++) if (!strcmp(word, words[i])) return i;
    return DEFAULT_SETTING;
}
static void read_setting(void) {
    if (setting >= 0) return;
    setting = DEFAULT_SETTING;
    const char *e = getenv("TEKKEN3_PS2_EFFECTS");
    if (e && *e) { setting = parse_setting(e); forced = 1; return; }
    char path[4096]; setting_path(path, sizeof path);
    FILE *f = path[0] ? fopen(path, "rb") : NULL;
    char word[32] = "";
    if (f) { if (fscanf(f, "%31s", word) == 1) setting = parse_setting(word); fclose(f); }
}
static void save_setting(void) {
    char path[4096]; setting_path(path, sizeof path);
    FILE *f = path[0] ? fopen(path, "wb") : NULL;
    if (f) { fprintf(f, "%s\n", words[setting]); fclose(f); }
}
static int drawable(void) { return pack.ok && pack.upper && psx_mod_gpu_high_vram_ready(); }

static void menu(void) {
    if (row < 0) {
        static int said;
        if (!drawable()) {
            if (!said++) fprintf(stderr, "PS2 lasers: no PS2 EFFECTS row (%s), the arcade's beam\n",
                                 pack.ok ? "the renderer has no upper VRAM half" : "no pack");
            return;
        }
        read_setting();
        row = tekken3_game_options_add("PS2 EFFECTS", labels, SETTINGS, (unsigned)setting, DEFAULT_SETTING, LASER_MODES);
        shown = setting;
        if (row < 0) return;
    }
    int v = tekken3_game_options_value(row);
    if (v >= 0 && v < SETTINGS && v != shown) {
        shown = v;
        if (!forced) { setting = v; save_setting(); }
        fprintf(stderr, "PS2 lasers: PS2 EFFECTS set to %s\n", words[v]);
    }
}

/* --- The cells ------------------------------------------------------------ */

static int cell_free(int x, int y) {
    return !tekken3_stage_high_vram_used(x, y, 16, 64) && !tekken3_hit_effect_high_vram_used(x, y, 16, 64) &&
           !tekken3_ttt1_wolf_high_vram_used(x, y, 16, 64);
}
/* Additive (ABR 1), 4 bits, the upper half (texpage bit 11, CLUT bit 15). */
static Tekken3Ps2LaserImage image_at(unsigned x, unsigned y, unsigned clut_x, unsigned clut_y) {
    Tekken3Ps2LaserImage m;
    m.tpage = (uint16_t)(x / 64 | ((y - 512) / 256) << 4 | 0x20 | 0x800);
    m.clut = (uint16_t)(0x8000 | (clut_y - 512) << 6 | clut_x / 16);
    m.u = (uint8_t)(x % 64 * 4); m.v = (uint8_t)(y % 256);
    return m;
}
static void choose(void) {
    unsigned generation = tekken3_stage_high_vram_generation();
    int wolf = tekken3_ttt1_wolf_high_vram_used(640, 512, 16, 64);
    if (cells.chosen && cells.generation == generation && cells.wolf == wolf) return;
    cells.generation = generation; cells.wolf = wolf;
    unsigned n = 0;
    for (int y = 960; y >= 512 && n < CELLS; y -= 64)
        for (int x = 1008; x >= 0 && n < CELLS; x -= 16)
            if (cell_free(x, y)) { cells.x[n] = (uint16_t)x; cells.y[n] = (uint16_t)y; n++; }
    if (n < CELLS) {
        cells.chosen = -1;
        fprintf(stderr, "PS2 lasers: %u free cells of 16 x 64 in the upper VRAM half beside this stage%s, %u needed: "
                "the arcade's beam\n", n, wolf ? " and Unknown's wolf" : "", CELLS);
        return;
    }
    cells.chosen = 1;
    unsigned px = cells.x[PALETTE_CELL], py = cells.y[PALETTE_CELL];
    for (unsigned who = 0; who < 2; who++)
        for (unsigned i = 0; i < TEKKEN3_PS2_LASER_IMAGES; i++) {
            unsigned c = i < TEKKEN3_PS2_LASER_ORBS ? i : TEKKEN3_PS2_LASER_ORBS + (i - TEKKEN3_PS2_LASER_ORBS) / 2;
            unsigned y = cells.y[c] + (i < TEKKEN3_PS2_LASER_ORBS ? 0 : (i - TEKKEN3_PS2_LASER_ORBS) % 2 * 32);
            cells.image[who][i] = image_at(cells.x[c], y, px, py + who * ANGEL_ROW + i);
        }
    fprintf(stderr, "PS2 lasers: %u cells of the upper VRAM half taken, from (%u, %u) to (%u, %u)%s\n", CELLS,
            cells.x[CELLS - 1], cells.y[CELLS - 1], cells.x[0], cells.y[0], wolf ? ", outside Unknown's wolf" : "");
}
/* The images and palettes in their cells, unless the half holds them already. */
static void place(void) {
    const uint16_t *hi = gpu_high_vram_pixels();
    int same = hi != NULL;
    unsigned px = cells.x[PALETTE_CELL], py = cells.y[PALETTE_CELL];
    for (unsigned who = 0; same && who < 2; who++)
        for (unsigned i = 0; same && i < TEKKEN3_PS2_LASER_IMAGES; i++)
            same = !memcmp(hi + (size_t)(py - 512 + who * ANGEL_ROW + i) * 1024 + px, pack.palette[who][i], 32);
    for (unsigned i = 0; same && i < TEKKEN3_PS2_LASER_IMAGES; i++) {
        const Tekken3Ps2LaserImage *m = &cells.image[0][i];
        unsigned x = (m->tpage & 15) * 64 + m->u / 4, y = 512 + (m->tpage >> 4 & 1) * 256 + m->v;
        unsigned h = i < TEKKEN3_PS2_LASER_ORBS ? 64 : 32;
        for (unsigned r = 0; same && r < h; r++)
            same = !memcmp(hi + (size_t)(y - 512 + r) * 1024 + x, pack.pixels[i] + r * 16, 32);
    }
    if (same) return;
    for (unsigned who = 0; who < 2; who++)
        for (unsigned i = 0; i < TEKKEN3_PS2_LASER_IMAGES; i++)
            psx_mod_gpu_high_vram_upload((int)px, (int)(py + who * ANGEL_ROW + i), 16, 1, pack.palette[who][i]);
    for (unsigned i = 0; i < TEKKEN3_PS2_LASER_IMAGES; i++) {
        const Tekken3Ps2LaserImage *m = &cells.image[0][i];
        unsigned x = (m->tpage & 15) * 64 + m->u / 4, y = 512 + (m->tpage >> 4 & 1) * 256 + m->v;
        psx_mod_gpu_high_vram_upload((int)x, (int)y, 16, i < TEKKEN3_PS2_LASER_ORBS ? 64 : 32, pack.pixels[i]);
    }
    static int said;
    if (!said++) fprintf(stderr, "PS2 lasers: images and palettes placed in the upper VRAM half\n");
}
/* For the PS2 strong-hit effects: PS2 EFFECTS on, with a pack read and an
 * upper half drawn. */
int tekken3_ps2_effects_on(void) {
    if (!drawable()) return 0;
    read_setting();
    return setting == SET_ON;
}
static int ready(void) {
    if (!drawable()) return 0;
    read_setting();
    if (setting != SET_ON) return 0;
    choose();
    if (cells.chosen != 1) return 0;
    place();
    return 1;
}

static int packets(void) {
    if (pack.packets_tried) return pack.packets != 0;
    pack.packets_tried = 1;
    uint32_t a = psx_mod_alloc_gpu_dma_memory(4 * TEKKEN3_PS2_LASER_PACKET_BYTES, 16);
    if (!a || !psx_mod_gpu_high_vram_source(a, 4 * TEKKEN3_PS2_LASER_PACKET_BYTES)) {
        fprintf(stderr, "PS2 lasers: no GPU-DMA packet memory (%u bytes) or no upper-half source left, "
                "the arcade's beam\n", 4 * TEKKEN3_PS2_LASER_PACKET_BYTES);
        return 0;
    }
    pack.packets = a;
    return 1;
}

int tekken3_ps2_laser_frame(unsigned p, unsigned buffer, const Tekken3Ps2LaserImage **images, uint32_t *out) {
    if (p > 1 || !ready() || !packets()) return 0;
    const char *moves = tekken3_guest_moves_prefix_for(p);
    *images = cells.image[moves && strstr(moves, "Angel-TTT1") ? 1 : 0];
    *out = pack.packets + (p * 2 + (buffer & 1)) * TEKKEN3_PS2_LASER_PACKET_BYTES;
    return 1;
}

/* Every VBlank: the row on the Options screen; the images placed as soon as
 * Devil or Angel fights, before the first laser. */
static void ps2_laser_tick(void) {
    if (!pack.ok || !psx_mod_game_started()) return;
    unsigned screen = psx_mod_read_word(SCREEN);
    if (screen == OPTIONS) menu();
    else if (screen == FIGHT && (tekken3_ttt1_has_lasers(0) || tekken3_ttt1_has_lasers(1))) (void)ready();
}

PSX_MOD_CONSTRUCTOR(register_ttt1_ps2_laser) {
    (void)psx_mod_register_activation_plugin("tekken3.ttt1-ps2-laser", ps2_laser_activate);
    (void)psx_mod_register_vblank_plugin("tekken3.ttt1-ps2-laser", ps2_laser_tick);
}
