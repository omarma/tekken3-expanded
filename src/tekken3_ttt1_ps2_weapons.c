/* Unknown's PS2 weapons, step 4 (TIPS.md sections 226 to 228): the pack the
 * setup makes from the TTT PS2 disc (mods/ttt-ps2-laser/unknown-weapons.bin,
 * tools/ps2/ttt_weapons.py) and its images in the upper VRAM half.
 *
 * The pack: 'UPW1', u16 format 2, u16 costumes (2); per costume u16 styles,
 * u16 images; the images, each a u32 size and a 4-bit TIM (16-colour CLUT,
 * then the pixels); per style u16 moveset (4 the katana, 26 the dagger), u16
 * T3 bone, u16 points, u16 polygons; the points (s16 x, y, z of the bone's
 * frame); the polygons, 16 bytes: u8 corners (3 or 4), u8 image, u8 flags
 * (1 additive), u8 0, 4 x u8 point, 4 x (u8 u, v), in the GPU's corner order.
 * Read at activation, with the PS2 lasers' version.txt (PACK_VERSION).
 *
 * The images of both costumes and their palettes are placed together in the
 * upper half, each inside one texture page, outside the loaded stage, TTT
 * Hitspark's cells, the wolf's pages (Unknown is the one fighting) and the
 * PS2 lasers' cells; chosen again with each stage pack and when the wolf
 * comes or goes, and uploaded whenever Unknown fights and the half does not
 * hold them. Not enough room: the arcade's blade, said in the log. */
#include "tekken3_ttt1_ps2_weapons.h"
#include "tekken3_ttt1_ps2_laser.h"
#include "gpu.h"
#include "mod_plugins.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { PACK_FORMAT = 2, COSTUMES = 2, STYLES = 2, IMAGES = 4, FIGHT = 8, SCREEN = 0x800ae204 };

typedef struct {
    unsigned w, h;                      /* halfwords, rows */
    const uint16_t *pixels, *clut;
    uint16_t x, y, clut_x, clut_y;      /* where they are placed */
} Image;
typedef struct {
    unsigned moveset, bone, points, polygons;
    int16_t point[TEKKEN3_PS2_WEAPON_POINTS][3];
    struct { uint8_t corners, image, additive, point[4], uv[4][2]; } raw[TEKKEN3_PS2_WEAPON_POLYGONS];
    Tekken3Ps2WeaponPolygon polygon[TEKKEN3_PS2_WEAPON_POLYGONS];
    Tekken3Ps2Weapon weapon;
} Style;
static struct {
    int ok;
    unsigned char *file;
    struct { unsigned images, styles; Image image[IMAGES]; Style style[STYLES]; } costume[COSTUMES];
    uint32_t packets;
    int packets_tried;
} pack;
static struct {
    int chosen;                         /* -1 no room, 0 not chosen, 1 chosen */
    unsigned generation; int wolf;
} place_state;

extern int tekken3_stage_high_vram_used(int x, int y, int w, int h);
extern unsigned tekken3_stage_high_vram_generation(void);
extern int tekken3_hit_effect_high_vram_used(int x, int y, int w, int h);
extern int tekken3_ttt1_wolf_high_vram_used(int x, int y, int w, int h);
extern int tekken3_ps2_laser_high_vram_used(int x, int y, int w, int h);
extern unsigned tekken3_ttt1_hilt_costume(unsigned player);

static unsigned u16(const unsigned char *p) { return p[0] | p[1] << 8; }
static uint32_t u32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

/* --- The pack ------------------------------------------------------------ */

static int parse(const unsigned char *b, long size) {
    if (size < 8 || memcmp(b, "UPW1", 4) || u16(b + 4) != PACK_FORMAT || u16(b + 6) != COSTUMES) return 0;
    long at = 8;
    for (unsigned c = 0; c < COSTUMES; c++) {
        if (at + 4 > size) return 0;
        unsigned styles = u16(b + at), images = u16(b + at + 2);
        if (styles != STYLES || !images || images > IMAGES) return 0;
        at += 4;
        pack.costume[c].styles = styles; pack.costume[c].images = images;
        for (unsigned i = 0; i < images; i++) {
            if (at + 4 + 64 > size) return 0;
            uint32_t n = u32(b + at);
            const unsigned char *t = b + at + 4, *clut = t + 8, *img = clut + 44;
            if (at + 4 + (long)n > size || u32(t) != 0x10 || u32(t + 4) != 8 || u32(clut) != 44 ||
                u16(clut + 8) != 16 || u16(clut + 10) != 1) return 0;
            Image *m = &pack.costume[c].image[i];
            m->w = u16(img + 8); m->h = u16(img + 10);
            if (!m->w || m->w > 64 || !m->h || m->h > 256 || u32(img) != 12 + 2 * m->w * m->h ||
                img + u32(img) > t + n) return 0;
            m->clut = (const uint16_t *)(clut + 12);
            m->pixels = (const uint16_t *)(img + 12);
            at += 4 + n;
        }
        for (unsigned s = 0; s < styles; s++) {
            if (at + 8 > size) return 0;
            Style *st = &pack.costume[c].style[s];
            st->moveset = u16(b + at); st->bone = u16(b + at + 2);
            st->points = u16(b + at + 4); st->polygons = u16(b + at + 6);
            at += 8;
            if (st->bone > 20 || !st->points || st->points > TEKKEN3_PS2_WEAPON_POINTS ||
                !st->polygons || st->polygons > TEKKEN3_PS2_WEAPON_POLYGONS ||
                at + 6 * (long)st->points + 16 * (long)st->polygons > size) return 0;
            for (unsigned i = 0; i < st->points * 3; i++) st->point[i / 3][i % 3] = (int16_t)u16(b + at + 2 * i);
            at += 6 * st->points;
            for (unsigned i = 0; i < st->polygons; i++, at += 16) {
                const unsigned char *f = b + at;
                if ((f[0] != 3 && f[0] != 4) || f[1] >= images) return 0;
                st->raw[i].corners = f[0]; st->raw[i].image = f[1]; st->raw[i].additive = f[2] & 1;
                for (unsigned k = 0; k < 4; k++) {
                    if (k < f[0] && f[4 + k] >= st->points) return 0;
                    st->raw[i].point[k] = f[4 + k];
                    st->raw[i].uv[k][0] = f[8 + 2 * k]; st->raw[i].uv[k][1] = f[9 + 2 * k];
                }
            }
        }
    }
    return at == size;
}

static void ps2_weapons_activate(void) {
    char path[4096];
    const char *dir = tekken3_ps2_effects_dir();
    if (snprintf(path, sizeof path, "%s/unknown-weapons.bin", dir) >= (int)sizeof path) return;
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "PS2 weapons: no %s (the setup makes it from the TTT PS2 disc), Unknown's energy blade\n", path);
        return;
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    pack.file = n > 0 && n < 1024 * 1024 ? malloc((size_t)n) : NULL;
    int good = pack.file && fread(pack.file, 1, (size_t)n, f) == (size_t)n && parse(pack.file, n);
    fclose(f);
    if (!good) {
        fprintf(stderr, "PS2 weapons: %s unreadable or of another format, Unknown's energy blade\n", path);
        free(pack.file); pack.file = NULL;
        return;
    }
    pack.ok = 1;
    fprintf(stderr, "PS2 weapons: %s read (%ld bytes)\n", path, n);
}

/* --- The images in the upper half ----------------------------------------- */

static int overlaps_placed(int x, int y, int w, int h, unsigned upto_c, unsigned upto_i) {
    for (unsigned c = 0; c <= upto_c && c < COSTUMES; c++)
        for (unsigned i = 0; i < pack.costume[c].images && (c < upto_c || i < upto_i); i++) {
            const Image *m = &pack.costume[c].image[i];
            if (x < m->x + (int)m->w && m->x < x + w && y < m->y + (int)m->h && m->y < y + h) return 1;
        }
    return 0;
}
static int free_for(int x, int y, int w, int h) {
    return !tekken3_stage_high_vram_used(x, y, w, h) && !tekken3_hit_effect_high_vram_used(x, y, w, h) &&
           !tekken3_ttt1_wolf_high_vram_used(x, y, w, h) && !tekken3_ps2_laser_high_vram_used(x, y, w, h);
}
/* Each image inside one texture page (64 halfwords, 256 rows), from the top
 * left of the upper half; the palettes in a row block of 16 after them. */
static void choose(void) {
    unsigned generation = tekken3_stage_high_vram_generation();
    int wolf = tekken3_ttt1_wolf_high_vram_used(640, 512, 16, 64);
    if (place_state.chosen && place_state.generation == generation && place_state.wolf == wolf) return;
    place_state.generation = generation; place_state.wolf = wolf;
    place_state.chosen = -1;
    for (unsigned c = 0; c < COSTUMES; c++)
        for (unsigned i = 0; i < pack.costume[c].images; i++) {
            Image *m = &pack.costume[c].image[i];
            int found = 0;
            for (int y = 512; !found && y + (int)m->h <= 1024; y += 4) {
                if ((y - 512) % 256 + (int)m->h > 256) continue;
                for (int x = 0; !found && x + (int)m->w <= 1024; x += 4) {
                    if (x % 64 + (int)m->w > 64) continue;
                    if (free_for(x, y, (int)m->w, (int)m->h) && !overlaps_placed(x, y, (int)m->w, (int)m->h, c, i)) {
                        m->x = (uint16_t)x; m->y = (uint16_t)y; found = 1;
                    }
                }
            }
            if (!found) {
                fprintf(stderr, "PS2 weapons: no room for a %ux%u image in the upper VRAM half beside this stage%s: "
                        "Unknown's energy blade\n", m->w, m->h, wolf ? " and her wolf" : "");
                return;
            }
        }
    /* palettes: 16 x 1 each, x a multiple of 16 */
    unsigned want = 0;
    for (unsigned c = 0; c < COSTUMES; c++) want += pack.costume[c].images;
    int px = -1, py = -1;
    for (int y = 512; px < 0 && y + (int)want <= 1024; y += 1)
        for (int x = 0; px < 0 && x + 16 <= 1024; x += 16)
            if (free_for(x, y, 16, (int)want) && !overlaps_placed(x, y, 16, (int)want, COSTUMES, 0)) { px = x; py = y; }
    if (px < 0) {
        fprintf(stderr, "PS2 weapons: no room for the palettes in the upper VRAM half: Unknown's energy blade\n");
        return;
    }
    unsigned row = 0;
    for (unsigned c = 0; c < COSTUMES; c++)
        for (unsigned i = 0; i < pack.costume[c].images; i++, row++) {
            pack.costume[c].image[i].clut_x = (uint16_t)px; pack.costume[c].image[i].clut_y = (uint16_t)(py + row);
        }
    /* the GPU words of every polygon */
    for (unsigned c = 0; c < COSTUMES; c++)
        for (unsigned s = 0; s < pack.costume[c].styles; s++) {
            Style *st = &pack.costume[c].style[s];
            for (unsigned k = 0; k < st->polygons; k++) {
                const Image *m = &pack.costume[c].image[st->raw[k].image];
                unsigned tpage = (unsigned)(m->x / 64 | ((m->y - 512) / 256) << 4 | (st->raw[k].additive ? 0x20 : 0) | 0x800);
                unsigned clut = (unsigned)(0x8000 | (m->clut_y - 512) << 6 | m->clut_x / 16);
                unsigned u0 = m->x % 64 * 4, v0 = (m->y - 512) % 256;
                Tekken3Ps2WeaponPolygon *g = &st->polygon[k];
                g->corners = st->raw[k].corners; g->additive = st->raw[k].additive;
                for (unsigned j = 0; j < 4; j++) {
                    g->point[j] = st->raw[k].point[j];
                    g->uv[j] = (uint32_t)(v0 + st->raw[k].uv[j][1]) << 8 | (u0 + st->raw[k].uv[j][0]);
                }
                g->uv[0] |= (uint32_t)clut << 16;
                g->uv[1] |= (uint32_t)tpage << 16;
            }
            st->weapon.bone = st->bone; st->weapon.points = st->points; st->weapon.polygons = st->polygons;
            st->weapon.point = (const int16_t (*)[3])st->point; st->weapon.polygon = st->polygon;
        }
    place_state.chosen = 1;
    fprintf(stderr, "PS2 weapons: images and palettes given their place in the upper VRAM half (palettes at %d, %d)%s\n",
            px, py, wolf ? ", outside Unknown's wolf" : "");
}
/* The images and palettes uploaded unless the half holds them already. */
static void upload(void) {
    const uint16_t *hi = gpu_high_vram_pixels();
    int same = hi != NULL;
    for (unsigned c = 0; same && c < COSTUMES; c++)
        for (unsigned i = 0; same && i < pack.costume[c].images; i++) {
            const Image *m = &pack.costume[c].image[i];
            same = !memcmp(hi + (size_t)(m->clut_y - 512) * 1024 + m->clut_x, m->clut, 32);
            for (unsigned r = 0; same && r < m->h; r++)
                same = !memcmp(hi + (size_t)(m->y - 512 + r) * 1024 + m->x, m->pixels + r * m->w, 2 * m->w);
        }
    if (same) return;
    for (unsigned c = 0; c < COSTUMES; c++)
        for (unsigned i = 0; i < pack.costume[c].images; i++) {
            const Image *m = &pack.costume[c].image[i];
            psx_mod_gpu_high_vram_upload(m->clut_x, m->clut_y, 16, 1, m->clut);
            psx_mod_gpu_high_vram_upload(m->x, m->y, (int)m->w, (int)m->h, m->pixels);
        }
    static int said;
    if (!said++) fprintf(stderr, "PS2 weapons: images and palettes placed in the upper VRAM half\n");
}
static int ready(void) {
    if (!pack.ok || !tekken3_ps2_effects_on()) return 0;
    choose();
    if (place_state.chosen != 1) return 0;
    upload();
    return 1;
}
static int packets(void) {
    if (pack.packets_tried) return pack.packets != 0;
    pack.packets_tried = 1;
    uint32_t a = psx_mod_alloc_gpu_dma_memory(4 * TEKKEN3_PS2_WEAPON_PACKET_BYTES, 16);
    if (!a || !psx_mod_gpu_high_vram_source(a, 4 * TEKKEN3_PS2_WEAPON_PACKET_BYTES)) {
        fprintf(stderr, "PS2 weapons: no GPU-DMA packet memory (%u bytes) or no upper-half source left, "
                "Unknown's energy blade\n", 4 * TEKKEN3_PS2_WEAPON_PACKET_BYTES);
        return 0;
    }
    pack.packets = a;
    return 1;
}

int tekken3_ps2_weapon_frame(unsigned p, unsigned moveset, unsigned buffer, const Tekken3Ps2Weapon **weapon,
                             uint32_t *out) {
    unsigned costume = p < 2 ? tekken3_ttt1_hilt_costume(p) : 0;
    if (!costume || costume > COSTUMES || !ready() || !packets()) return 0;
    for (unsigned s = 0; s < pack.costume[costume - 1].styles; s++) {
        const Style *st = &pack.costume[costume - 1].style[s];
        if (st->moveset != moveset) continue;
        *weapon = &st->weapon;
        *out = pack.packets + (p * 2 + (buffer & 1)) * TEKKEN3_PS2_WEAPON_PACKET_BYTES;
        return 1;
    }
    return 0;
}

int tekken3_ps2_weapons_high_vram_used(int x, int y, int w, int h) {
    if (place_state.chosen != 1) return 0;
    for (unsigned c = 0; c < COSTUMES; c++)
        for (unsigned i = 0; i < pack.costume[c].images; i++) {
            const Image *m = &pack.costume[c].image[i];
            if (x < m->x + (int)m->w && m->x < x + w && y < m->y + (int)m->h && m->y < y + h) return 1;
            if (x < m->clut_x + 16 && m->clut_x < x + w && y <= m->clut_y && m->clut_y < y + h) return 1;
        }
    return 0;
}

/* Every VBlank of a fight with Unknown in it: the images placed before her first weapon. */
static void ps2_weapons_tick(void) {
    if (!pack.ok || !psx_mod_game_started() || psx_mod_read_word(SCREEN) != FIGHT) return;
    if (tekken3_ttt1_hilt_costume(0) || tekken3_ttt1_hilt_costume(1)) (void)ready();
}

PSX_MOD_CONSTRUCTOR(register_ttt1_ps2_weapons) {
    (void)psx_mod_register_activation_plugin("tekken3.ttt1-ps2-weapons", ps2_weapons_activate);
    (void)psx_mod_register_vblank_plugin("tekken3.ttt1-ps2-weapons", ps2_weapons_tick);
}
