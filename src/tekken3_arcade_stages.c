/* Arcade Stages (steps E4 to E6): the Tekken 3 arcade stages in place of
 * the PS1 ones, arenas 0..12, with their animations. Package
 * tekken3.stage.arcade-stages, feature "Arcade Stages"; its packs come from
 * the player's tekken3.zip at setup (tools/arcade_stages/install.py). TIPS
 * sections 92 to 95 and 106 (the Embu).
 *
 * The PS1 game is a port of the arcade one and keeps its world: same units
 * (floor cells of 2500), same camera struct (0x800A85C0 = 0x802C6BD4: pitch,
 * yaw, roll at +0, +4, +8, position at +0x14), same fight axis (0x800A9188 =
 * 0x8021FB60, both 0 at the start of a fight, both moved in the tile drawing
 * by the same routine, 0x8006E1B8 = 0x801DB238), same stage placement (the
 * tiles' origin under the fighters' midpoint, smoothed over 4 frames, turned
 * by minus the axis). Only the display differs: 368 x 480 instead of
 * 512 x 240, so the PS1 camera matrix has its own row scaling, roll sign and
 * GTE screen. The arcade stage is therefore drawn with the PS1's own
 * matrices, built as the PS1 builds them for its own stage (0x8006D014) and
 * its floor (0x80045CA8, 0x8004ADC4), with the arcade data (tiles in world
 * units / 10, stage origin y 50 as 0x8017C454) from a stageNN.ast pack
 * (tools/arcade_stages/pack.py, format 3).
 *
 * E5b, once per stage frame (tools/arcade_stages/anim.py is the reference):
 * the animated texture of stages 6 and 12 (0x801E2114: the next of 16
 * frames moved in every 4th frame), the stage 3 objects (0x801E5AD0, every
 * frame) and the stage 11 helicopter (0x801E3F68 / 0x801E40C0), started
 * again at each round as 0x801E3D94 does; the objects drawn as 0x801E2A68
 * (main ranks 1011 and 1009, stage 11: 1022), the helicopter only once the
 * round is decided, as in the arcade.
 *
 * Hooks, all inert until the package's activation found the upper VRAM half:
 *   0x80048E58 / 0x80049848  the PS1 floor (called through 0x8009E728 by
 *            0x80048240, before the fighters move): skipped, the arcade
 *            floor (0x801A941C / 0x801AA9C0, scene.floor_commands) linked
 *            at main OT ranks 1021..982 instead;
 *   0x8006D014  the PS1 tiles: run unchanged (it also counts frames,
 *            0x800A08F0, keeps the fighters' history and moves the axis),
 *            then its private OT 0x800A08C8 + 8 * buffer is emptied; the
 *            tiles the arcade's cone walk keeps (0x801DA734) in OT A (main
 *            rank 1010) and OT B (1021), the far background (0x801A7688)
 *            at rank 1023.
 *   0x80048240 / 0x80048208  the two callers of *0x8009E728: in the Embu
 *            (state 6) 0x8004808C points it at the overlay's own floor
 *            (0x800D494C, a small grid of FT4 that met the PS1 tiles only),
 *            pointed at 0x80048E58 instead so the arcade floor is drawn.
 * Any missing piece (no pack for the arena, Vulkan, a special mode) leaves
 * the frame to the PS1 code.
 *
 * TTT Stages S3 (TIPS section 112): a second source of stages, Tekken Tag
 * Tournament arcade's (format 4 packs, source 'TTTA', tools/arcade_stages/
 * pack.py --game ttt, beside the game as mods/ttt-stages), drawn by the same
 * hooks: tools/arcade_stages/ttt.py's Stage.frame is the reference (its
 * tiles with masks, frame test and per-stage OT ranks, its far background
 * rules, its floor of another format, and stage 4's storm: lit skies, a
 * point light on the fighters through the PS1's own hit-flash light
 * 0x80039F0C, thunder). The stage of a fight comes from the STAGES row
 * (src/tekken3_stage_source.c); cinematics force one through
 * src/tekken3_arcade_stages.h. Feature "TTT Stages" of the TTT1 package
 * (plugin tekken3.ttt-stages); either feature brings up the engine. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "psx_sdl.h"
#include "tekken3_arcade_stages.h"
#include "tekken3_stage_source.h"
#include <math.h>
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PACK_FORMAT 3u
#define PACK_FORMAT_TTT 4u
#define BUFFER_BYTES 0x30000u        /* packets of one OT buffer */
#define FLOOR_BYTES 0x10000u         /* of which the floor's (B87: and its widened copies) */

/* PS1 addresses */
#define ARENA        0x800ADC84u
#define CAMERA       0x800A85C0u
#define AXIS         0x800A9188u
#define OT_BUFFER    0x800ADEFCu
#define PRIVATE_OT   0x800A08C8u
#define DRAWENV      0x800A8C54u
#define WORLD        0x800ADF70u
#define FLOOR_SHOWN  0x800ADFD0u
#define FLOOR_FN     0x8009E728u    /* the floor routine, set by 0x8004808C at each stage load */
#define EMBU_FLOOR   0x800D494Cu    /* ... in the Embu (state 0x800AE204 = 6): the overlay's */
#define KIND0_FLOOR  0x80048E58u
#define MODE         0x800AFA88u
#define DARK_ARENA   0x800AFAA0u
#define FIXED_STAGE  0x800AFAA1u
#define NO_STAGE     0x800ADCA4u
#define P1_X 0x800AA190u
#define P1_Z 0x800AA198u
#define P2_X 0x800ABA1Cu
#define P2_Z 0x800ABA24u
#define HISTORY_P1 0x800A08F8u       /* 4 x (x, -, z, -) */
#define HISTORY_P2 0x800A0938u
#define SIN_PS1 0x8001E8C4u
#define COS_PS1 0x8001F0C4u
#define SCREEN_W 368
#define SCREEN_H 480
#define STAGE_Y  50                  /* arcade 0x8017C454, every stage */

typedef struct { int16_t x, y, z, pad; } Vert;
typedef struct {
    uint32_t header;
    uint8_t kind, code, cull, ncol, idx[4], uv[4][2];
    uint16_t clut, tpage;
    uint8_t rgb[4][3], win[4];
} Prim;
typedef struct { uint8_t slot, layer_b, skipped, pad; uint16_t nv, np; } TileHead;
typedef struct { const TileHead *head; const Vert *v; const Prim *p; } Tile;
typedef struct { const Vert *v; const Prim *p; unsigned nv, np; } Model;
typedef struct { uint8_t model, pad; uint16_t rank, size, pad2; } Layout;   /* OBJS: drawing call order */

typedef struct { uint16_t sound; uint32_t frames; const int16_t *pcm; } Thunder;

typedef struct {
    int stage;
    int source;                         /* TEKKEN3_STAGE_T3 (format 3) or TEKKEN3_STAGE_TTT (format 4) */
    int axis0;                          /* TTT: the fight axis at the round start (MISC) */
    unsigned rank_a, rank_b;            /* main OT ranks of OT A, OT B */
    /* TTT far background rules (FAR2) */
    uint8_t fmode, fclamp, fhas_min, fgradient[3];
    int16_t fmin_y;
    /* TTT floor (FLR2) */
    int gfloor;
    int16_t gkind, gfog, gsize;
    uint8_t gcols, grows, ghalf;
    const uint32_t *gcells;             /* 15 x 15 (w0, w1) */
    const uint8_t *gunique, *gramp;     /* 15 x 15 ranks, 1024 kind-0 shades */
    uint16_t gnv;
    const int16_t *gverts;              /* (x, z) x gnv */
    uint32_t gnq;
    const uint32_t *gquads;
    const uint16_t *gcorners;           /* rotation x mirror x flip: 16 x 4 uv offsets */
    const int16_t *tsine, *tsqrt;       /* TRG2: 1.12 sine x 5120, SquareRoot0 table */
    /* stage 4's storm (STRM) and thunder (THND) */
    int storm;
    int16_t sthreshold[5];
    uint8_t scolour[6][3];
    const int8_t *sseq[6];
    uint8_t sseqlen[6];
    const uint16_t *sskydesc[6], *sskyclut[6];
    uint16_t ssound[5][2], sforced[2][2];
    unsigned nthunder;
    Thunder thunder[8];
    uint8_t *file;
    uint32_t size;
    Tile tiles[256];
    unsigned ntiles, tile_size;          /* tile size: world units / 10 */
    /* far background */
    int16_t fcols, frows, fring, fyoff, fdegrees, fpitch;
    const uint8_t *fcolours;            /* cell rgb, top rgb, top on, bottom rgb, bottom on */
    const uint16_t *fdesc, *fcluts;
    const uint8_t *fkinds;
    /* floor */
    int16_t lkind, lfog;
    int32_t lnear;
    const uint32_t *lcells, *lhalves;   /* (w0, w1) x 100, x 400 */
    const uint8_t *lunique;
    uint16_t lnv;
    const int16_t *lverts;              /* (x, z) x lnv */
    uint8_t lcount[100];
    const uint32_t *lquads[100];
    const uint16_t *luv[5];             /* [n]: 4 rotations x n x 4 */
    /* tables */
    const int16_t *sin, *cos, *sqrt1, *sqrt2;
    const uint8_t *fog;
    /* objects (stages 3, 11) */
    Model models[4];
    unsigned nmodels, nlayout;
    const Layout *layout;
    const uint32_t *rot;                /* 0x8021688C: sine | cosine << 16 */
    /* animated texture (stages 6, 12): frames moved onto (ax, ay) */
    uint16_t ax, ay, aw, ah, aperiod, aframes;
    uint16_t *apixels;                  /* aframes x aw x ah, from the VRAM section */
    /* TTT Stages S4 (format 4): objects' frame, animated textures, stage 11's
     * floor lights and light beams, stage 2's particles */
    int32_t oframe[3];                  /* OBJS: the model frame 0x8019C9CC */
    const uint8_t *tanm;                /* TANM (stages 3, 6, 7, 14) */
    uint16_t *hivram;                   /* the upper half as the pack poses it (y 512..1023): MoveImage's source */
    const uint32_t *lite;               /* LITE: 480 CLUT << 16 (stage 11) */
    const uint8_t *part;                /* PART (stage 2) */
    const uint8_t *glow;                /* GLOW (stage 11) */
    const uint8_t *togr;                /* TOGR: True Ogre's colour, floor kind (0xFF none) */
} Pack;

static int s_on;                        /* the engine is up (either feature's activation) */
static int s_t3_on, s_ttt_on;           /* Arcade Stages / TTT Stages activated with their packs */
static int s_shadow;                    /* probe: computed and logged, the PS1 frame untouched */
static FILE *s_probe;
static uint32_t s_memory;               /* 2 x BUFFER_BYTES of GPU-DMA memory */
static Pack s_pack;
static int s_tried = -1;                /* arena whose pack was last looked for (T3) */
static int s_tried_ttt = -1;            /* TTT stage whose pack was last looked for */
static int s_force = -1;                /* TTT stage forced by a cinematic (tekken3_ttt_stage_force) */
static int s_floor_at, s_floor_xz[2], s_floor_half;   /* a cinematic's TTT floor (tekken3_ttt_floor_centre) */
static int16_t s_sin[4096], s_cos[4096];
static int s_trig_ps1;
static int s_log = -1;
static unsigned s_frames;
static unsigned s_stat_tiles, s_stat_floor, s_stat_far, s_stat_cone, s_stat_behind;
/* TTT Stages S4: the TTT stages' animation state (section "TTT Stages S4" below) */
static struct {
    unsigned a98, a9a;                  /* 0x80243A98 / 0x80243A9A, u16 */
    int state, count, tick, frame;      /* stage 7's machine (0x80243A9E..) */
    int cage_cleared;                   /* stage 7's empty cage written this round (B114) */
    int c, k, yaw;                      /* stage 3's object (0x80243B10, 0x80243B0C, 0x803535B2) */
    int was_over;                       /* the round was decided last frame */
    unsigned light;                     /* stage 11's floor lights (0x802437A8, 0..0xEF) */
} s_tttanim;

/* ------------------------------------------------------------------ */
/* small helpers                                                      */
/* ------------------------------------------------------------------ */
static int tdiv(int64_t a, int64_t b) { return (int)(a / b); }           /* C: towards zero */
static int tmod(int64_t a, int64_t b) { return (int)(a % b); }
static int pmod(int a, int b) { int r = a % b; return r < 0 ? r + b : r; }
static int s12(int a) { a &= 0xFFF; return a >= 0x800 ? a - 0x1000 : a; }
static int shift12(int64_t v) { return (int)((v < 0 ? v + 0xFFF : v) >> 12); }
static int16_t sat16(int64_t v) { return (int16_t)(v < -0x8000 ? -0x8000 : v > 0x7FFF ? 0x7FFF : v); }
static uint32_t xy(int x, int y) { return (uint32_t)(y & 0xFFFF) << 16 | (uint32_t)(x & 0xFFFF); }

/* Sub-pixel precision ([video] geometry_correction / perspective_texturing,
 * psxrecomp/ENHANCEMENTS.md G1.13): beside each projected position word, the
 * 16.16 point it was rounded from, as the game's own GTE projections get.
 * NO_PRECISE: none (a saturated projection). s_precise: the options are on
 * this frame; off, nothing is computed. */
#define NO_PRECISE INT32_MIN
static int s_precise;
/* s_tj: geometry correction is on this frame. The T-junction pass below only
 * moves sub-pixel positions, which perspective texturing alone never draws,
 * so with geometry off it keeps no point and does nothing. */
static int s_tj;

/* The point kept inside the word's pixel: a point this module rounds its
 * own way (floor midpoints, near pieces) is then always accepted, and every
 * packet that shares the vertex gets the same one. */
static int32_t in_pixel(int64_t p16, int v) {
    int64_t lo = (int64_t)v << 16;
    return (int32_t)(p16 < lo ? lo : p16 > lo + 0xFFFF ? lo + 0xFFFF : p16);
}

static uint32_t depth16(int64_t z) { return (uint32_t)(z < 1 ? 1 : z > 0xFFFF ? 0xFFFF : z); }

/* T-junctions (PGXP J2c, TIPS § 123-124, psxrecomp/ENHANCEMENTS.md G1.14).
 * The arcade's tiles meet edge on edge: a tile's corners lie on its
 * neighbour's edge, collinear in integer coordinates, and the floor's split
 * cells and the tiles meet the same way. The console's integer positions
 * keep such edges on one line; at sub-pixel precision each tile's own
 * rounding parts them and a crack opens along the whole edge (up to half a
 * pixel). So every frame the points written here and their triangles are
 * kept, and after each drawing hook every point lying on another triangle's
 * edge in integer coordinates (within half a pixel, strictly between its
 * ends: the T-junction of tools/pgxp_gates.py) is moved onto that edge's
 * precise line, in place, sweep after sweep until nothing moves (chains:
 * a host's corner is often a T point itself; a single sweep made it worse),
 * then put back inside its word's pixel and handed over again. Only while
 * geometry correction is on (s_tj). */
#define TJ_POINTS 8192
#define TJ_WORDS 16384
#define TJ_TRIS 8192
#define TJ_RELS 32768
#define TJ_HASH 16384
#define TJ_SWEEPS 16
typedef struct { int x, y, fixed; int64_t px, py; double fx, fy; int next; } TjPoint;
static TjPoint s_tj_pt[TJ_POINTS];
static struct { uint32_t addr, word; int pt; int64_t z; } s_tj_word[TJ_WORDS];
static int s_tj_tri[TJ_TRIS][3], s_tj_rel[TJ_RELS][3], s_tj_cur[4];
static int s_tj_hash[TJ_HASH];
static int s_tj_npt, s_tj_nword, s_tj_ntri, s_tj_ncur;
static int s_tj_buffer = -1;
static unsigned s_tj_hooks;
#define TJ_HOOK_FLOOR 1u
#define TJ_HOOK_STAGE 2u

/* The point of an integer position: every word written on that pixel this
 * frame, with the precise position of the first (px, py inside the pixel).
 * psxrecomp's pixel-cell merge (gpu.c) already gives a pixel's corrected
 * vertices one position, the first drawn; deciding it here, before the fix,
 * keeps every T-junction relation of the pixel on the position drawn. */
static int tj_point(int x, int y, int64_t px, int64_t py) {
    uint32_t h = ((uint32_t)x * 0x9E3779B1u ^ (uint32_t)y * 0x85EBCA77u) & (TJ_HASH - 1);
    for (int i = s_tj_hash[h]; i >= 0; i = s_tj_pt[i].next) {
        const TjPoint *p = &s_tj_pt[i];
        if (p->x == x && p->y == y) return i;
    }
    if (s_tj_npt == TJ_POINTS) return -1;
    TjPoint *p = &s_tj_pt[s_tj_npt];
    p->x = x; p->y = y;
    p->fixed = px == NO_PRECISE || py == NO_PRECISE;
    p->px = p->fixed ? NO_PRECISE : in_pixel(px, x);
    p->py = p->fixed ? NO_PRECISE : in_pixel(py, y);
    p->next = s_tj_hash[h];
    s_tj_hash[h] = s_tj_npt;
    return s_tj_npt++;
}

static void put_xy(uint32_t a, int x, int y, int64_t px, int64_t py, int64_t z) {
    uint32_t w = xy(x, y);
    psx_mod_write_word(a, w);
    if (!s_precise) return;
    if (px != NO_PRECISE && py != NO_PRECISE)
        psx_mod_precise_word(a, w, in_pixel(px, x), in_pixel(py, y), depth16(z));
    if (!s_tj) return;
    int p = tj_point(x, y, px, py);
    if (s_tj_ncur < 4) s_tj_cur[s_tj_ncur++] = p;
    if (p >= 0 && s_tj_nword < TJ_WORDS) {
        s_tj_word[s_tj_nword].addr = a; s_tj_word[s_tj_nword].word = w; s_tj_word[s_tj_nword].pt = p;
        s_tj_word[s_tj_nword].z = z;
        s_tj_nword++;
    }
}

/* After the position words of one primitive: its triangles, in the GPU's
 * order (a quad is 0 1 2 and 2 1 3). */
static void tj_prim_end(void) {
    int n = s_tj_ncur, *c = s_tj_cur;
    s_tj_ncur = 0;
    if (!s_tj || (n != 3 && n != 4)) return;
    for (int i = 0; i < n; i++) if (c[i] < 0) return;
    for (int t = 0; t < n - 2; t++) {
        if (s_tj_ntri == TJ_TRIS) return;
        int *r = s_tj_tri[s_tj_ntri++];
        if (t == 0) { r[0] = c[0]; r[1] = c[1]; r[2] = c[2]; }
        else { r[0] = c[2]; r[1] = c[1]; r[2] = c[3]; }
    }
}

static void tj_fix(void) {
    if (!s_tj || !s_tj_ntri) return;
    for (int i = 0; i < s_tj_npt; i++) {
        TjPoint *p = &s_tj_pt[i];
        p->fx = p->fixed ? p->x : p->px / 65536.0;
        p->fy = p->fixed ? p->y : p->py / 65536.0;
    }
    /* points by 8 x 8 cell of their integer position */
    static int head[4096], next[TJ_POINTS];
    memset(head, -1, sizeof head);
    for (int i = 0; i < s_tj_npt; i++) {
        unsigned c = ((unsigned)(s_tj_pt[i].x >> 3) & 63u) | ((unsigned)(s_tj_pt[i].y >> 3) & 63u) << 6;
        next[i] = head[c]; head[c] = i;
    }
    int nrel = 0;
    for (int t = 0; t < s_tj_ntri; t++)
        for (int e = 0; e < 3; e++) {
            const TjPoint *a = &s_tj_pt[s_tj_tri[t][e]], *b = &s_tj_pt[s_tj_tri[t][(e + 1) % 3]];
            int64_t dx = b->x - a->x, dy = b->y - a->y, l2 = dx * dx + dy * dy;
            if (!l2) continue;
            int cx0 = (dx < 0 ? b->x : a->x) >> 3, cx1 = (dx < 0 ? a->x : b->x) >> 3;
            int cy0 = (dy < 0 ? b->y : a->y) >> 3, cy1 = (dy < 0 ? a->y : b->y) >> 3;
            if (cx1 - cx0 > 63) cx1 = cx0 + 63;
            if (cy1 - cy0 > 63) cy1 = cy0 + 63;
            for (int cy = cy0; cy <= cy1; cy++)
                for (int cx = cx0; cx <= cx1; cx++)
                    for (int i = head[((unsigned)cx & 63u) | ((unsigned)cy & 63u) << 6]; i >= 0; i = next[i]) {
                        const TjPoint *v = &s_tj_pt[i];
                        if (v->fixed || (v->x >> 3) != cx || (v->y >> 3) != cy) continue;
                        if ((v->x == a->x && v->y == a->y) || (v->x == b->x && v->y == b->y)) continue;
                        if (i == s_tj_tri[t][0] || i == s_tj_tri[t][1] || i == s_tj_tri[t][2]) continue;
                        int64_t u = (v->x - a->x) * dx + (v->y - a->y) * dy;
                        if (u <= 0 || u >= l2) continue;
                        int64_t cr = dx * (v->y - a->y) - dy * (v->x - a->x);
                        if ((double)cr * cr > 0.25 * (double)l2) continue;
                        if (nrel == TJ_RELS) goto sweep;
                        s_tj_rel[nrel][0] = i; s_tj_rel[nrel][1] = s_tj_tri[t][e];
                        s_tj_rel[nrel][2] = s_tj_tri[t][(e + 1) % 3];
                        nrel++;
                    }
        }
sweep:
    for (int s = 0; nrel && s < TJ_SWEEPS; s++) {
        double moved = 0;
        for (int r = 0; r < nrel; r++) {
            TjPoint *v = &s_tj_pt[s_tj_rel[r][0]];
            const TjPoint *a = &s_tj_pt[s_tj_rel[r][1]], *b = &s_tj_pt[s_tj_rel[r][2]];
            double dx = b->fx - a->fx, dy = b->fy - a->fy, l2 = dx * dx + dy * dy;
            if (l2 == 0) continue;
            double u = ((v->fx - a->fx) * dx + (v->fy - a->fy) * dy) / l2;
            u = u < 0 ? 0 : u > 1 ? 1 : u;
            double nx = a->fx + u * dx, ny = a->fy + u * dy;
            /* inside the word's pixel, as put_xy keeps it */
            const double top = 1.0 - 1.0 / 65536;
            nx = nx < v->x ? v->x : nx > v->x + top ? v->x + top : nx;
            ny = ny < v->y ? v->y : ny > v->y + top ? v->y + top : ny;
            double d = fabs(nx - v->fx) + fabs(ny - v->fy);
            if (d > moved) moved = d;
            v->fx = nx; v->fy = ny;
        }
        if (moved < 1.0 / 1024) break;
    }
    for (int w = 0; w < s_tj_nword; w++) {
        const TjPoint *p = &s_tj_pt[s_tj_word[w].pt];
        if (p->fixed) continue;
        int64_t nx = (int64_t)llround(p->fx * 65536.0), ny = (int64_t)llround(p->fy * 65536.0);
        psx_mod_precise_word(s_tj_word[w].addr, s_tj_word[w].word, in_pixel(nx, p->x), in_pixel(ny, p->y),
                             depth16(s_tj_word[w].z));
    }
}

static int64_t mean_precise(int64_t a, int64_t b) {
    return a == NO_PRECISE || b == NO_PRECISE ? NO_PRECISE : (a + b) / 2;
}
static uint32_t rgbw(const uint8_t c[3]) { return (uint32_t)c[0] | (uint32_t)c[1] << 8 | (uint32_t)c[2] << 16; }

static int log_on(void) {
    if (s_log < 0) s_log = getenv("TEKKEN3_ARCADE_STAGES_LOG") != NULL;
    return s_log;
}

/* TEKKEN3_ARCADE_STAGES_PERF: every 600 frames, the module's time per frame
 * (floor hook + stage frame) and the time between two stage frames */
#ifdef _WIN32
__declspec(dllimport) int __stdcall QueryPerformanceCounter(long long *count);
__declspec(dllimport) int __stdcall QueryPerformanceFrequency(long long *frequency);
static uint64_t now_ns(void) {
    static long long f;
    long long c;
    if (!f) QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return (uint64_t)((double)c * 1e9 / (double)f);
}
#else
#include <time.h>
static uint64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec;
}
#endif
static int s_perf = -1;
static uint64_t s_perf_mod, s_perf_mod_max, s_perf_last, s_perf_gap_max, s_perf_gap_sum;
static unsigned s_perf_frames, s_perf_gaps, s_perf_slow, s_perf_hitch;

static int perf_on(void) {
    if (s_perf < 0) s_perf = getenv("TEKKEN3_ARCADE_STAGES_PERF") != NULL;
    return s_perf;
}

static void perf_frame(uint64_t mod_ns) {
    uint64_t t = now_ns();
    s_perf_mod += mod_ns;
    if (mod_ns > s_perf_mod_max) s_perf_mod_max = mod_ns;
    if (s_perf_last) {
        uint64_t gap = t - s_perf_last;
        s_perf_gap_sum += gap; s_perf_gaps++;
        if (gap > s_perf_gap_max) s_perf_gap_max = gap;
        s_perf_slow += gap > 17500000u;           /* a frame missed at 60 Hz */
        s_perf_hitch += gap > 25000000u;
        if (gap > 50000000u)
            fprintf(stdout, "arcade stages perf: %.1f ms before frame %u (state %u, phase %u)\n", gap / 1e6,
                    psx_mod_read_word(0x800A08F0u), psx_mod_read_word(0x800AE204u), psx_mod_read_half(0x800AE224u));
    }
    s_perf_last = t;
    if (++s_perf_frames == 600) {
        fprintf(stdout, "arcade stages perf: stage %d, module %.3f ms a frame (max %.3f), frame %.2f ms (max %.2f), "
                "%u over 17.5 ms, %u over 25 ms\n", s_pack.stage, s_perf_mod / 600e6, s_perf_mod_max / 1e6,
                s_perf_gaps ? s_perf_gap_sum / (s_perf_gaps * 1e6) : 0.0, s_perf_gap_max / 1e6, s_perf_slow, s_perf_hitch);
        fflush(stdout);
        s_perf_mod = s_perf_mod_max = s_perf_gap_max = s_perf_gap_sum = 0;
        s_perf_frames = s_perf_gaps = s_perf_slow = s_perf_hitch = 0;
    }
}
static uint64_t s_perf_floor;           /* the floor hook's time this frame */

/* ------------------------------------------------------------------ */
/* GTE: RTPS (sf 1, lm 0) and NCLIP, as tools/arcade_stages/gte.py     */
/* ------------------------------------------------------------------ */
typedef struct { int32_t r[3][3]; int32_t t[3]; int32_t ofx, ofy; uint32_t h; } Gte;
static uint8_t s_unr[0x101];

static void unr_init(void) {
    for (int i = 0; i < 0x101; i++) {
        int v = (0x40000 / (i + 0x100) + 1) / 2 - 0x101;
        s_unr[i] = (uint8_t)(v < 0 ? 0 : v);
    }
}

static uint32_t gte_divide(uint32_t h, uint32_t sz3) {
    if (h >= sz3 * 2u) return 0x1FFFF;
    int z = 0;
    while (z < 15 && !(sz3 << z & 0x8000u)) z++;
    uint64_t n = (uint64_t)h << z;
    int64_t d = (int64_t)(sz3 << z);
    int64_t u = s_unr[(d - 0x7FC0) >> 7] + 0x101;
    d = (0x2000080 - d * u) >> 8;
    d = (0x0000080 + d * u) >> 8;
    uint64_t q = (n * (uint64_t)d + 0x8000) >> 16;
    return q > 0x1FFFF ? 0x1FFFF : (uint32_t)q;
}

/* px, py (may be null): the 16.16 screen point before rounding, NO_PRECISE
 * when the projection saturates (IR, divide or screen clamp). */
static void rtps(const Gte *g, int x, int y, int z, int *sx, int *sy, int *sz, int32_t *px, int32_t *py) {
    int64_t mac[3];
    for (int i = 0; i < 3; i++)
        mac[i] = (((int64_t)g->t[i] << 12) + (int64_t)g->r[i][0] * x + (int64_t)g->r[i][1] * y
                  + (int64_t)g->r[i][2] * z) >> 12;
    int64_t ir0 = mac[0] < -0x8000 ? -0x8000 : mac[0] > 0x7FFF ? 0x7FFF : mac[0];
    int64_t ir1 = mac[1] < -0x8000 ? -0x8000 : mac[1] > 0x7FFF ? 0x7FFF : mac[1];
    uint32_t sz3 = (uint32_t)(mac[2] < 0 ? 0 : mac[2] > 0xFFFF ? 0xFFFF : mac[2]);
    int64_t q = gte_divide(g->h, sz3);
    int64_t vx = (q * ir0 + g->ofx) >> 16, vy = (q * ir1 + g->ofy) >> 16;
    *sx = (int)(vx < -0x400 ? -0x400 : vx > 0x3FF ? 0x3FF : vx);
    *sy = (int)(vy < -0x400 ? -0x400 : vy > 0x3FF ? 0x3FF : vy);
    *sz = (int)sz3;
    if (px) {
        int ok = ir0 == mac[0] && ir1 == mac[1] && q < 0x1FFFF && vx == *sx && vy == *sy;
        *px = ok ? (int32_t)(q * ir0 + g->ofx) : NO_PRECISE;
        *py = ok ? (int32_t)(q * ir1 + g->ofy) : NO_PRECISE;
    }
}

/* rtps without the GTE's clamps: the screen point as far as it really
 * lands, and the signed depth (negative behind the camera). */
static void rtps_raw(const Gte *g, int x, int y, int z, int64_t *sx, int64_t *sy, int64_t *depth,
                     int64_t *px, int64_t *py) {
    int64_t mac[3];
    for (int i = 0; i < 3; i++)
        mac[i] = (((int64_t)g->t[i] << 12) + (int64_t)g->r[i][0] * x + (int64_t)g->r[i][1] * y
                  + (int64_t)g->r[i][2] * z) >> 12;
    *depth = mac[2];
    int64_t d = mac[2] < 1 ? 1 : mac[2];
    *sx = (g->ofx >> 16) + mac[0] * (int64_t)g->h / d;
    *sy = (g->ofy >> 16) + mac[1] * (int64_t)g->h / d;
    /* the same point in 16.16, untruncated (precision only) */
    *px = ((int64_t)(g->ofx >> 16) << 16) + (int64_t)((double)mac[0] * g->h * 65536.0 / (double)d);
    *py = ((int64_t)(g->ofy >> 16) << 16) + (int64_t)((double)mac[1] * g->h * 65536.0 / (double)d);
}

static int64_t nclip(int x0, int y0, int x1, int y1, int x2, int y2) {
    return (int64_t)x0 * y1 + (int64_t)x1 * y2 + (int64_t)x2 * y0
         - (int64_t)x0 * y2 - (int64_t)x1 * y0 - (int64_t)x2 * y1;
}

/* ------------------------------------------------------------------ */
/* PS1 matrices: 0x8003A490 (rotation through the GTE's GPF), MulMatrix2, */
/* ApplyMatrix                                                        */
/* ------------------------------------------------------------------ */
static void trig_ps1(void) {
    if (s_trig_ps1) return;
    for (unsigned i = 0; i < 4096; i++) {
        s_sin[i] = (int16_t)psx_mod_read_half(SIN_PS1 + 2 * i);
        s_cos[i] = (int16_t)psx_mod_read_half(COS_PS1 + 2 * i);
    }
    s_trig_ps1 = 1;
}

static int gpf(int ir0, int v) { return sat16(((int64_t)ir0 * v) >> 12); }

static void rot_ps1(int ax, int ay, int az, int32_t m[3][3]) {
    int sx = s_sin[ax & 0xFFF], cx = s_cos[ax & 0xFFF];
    int sy = s_sin[ay & 0xFFF], cy = s_cos[ay & 0xFFF];
    int sz = s_sin[az & 0xFFF], cz = s_cos[az & 0xFFF];
    int a1 = gpf(sx, cz), a2 = gpf(sx, sz), a3 = gpf(sx, cy);
    int i6 = (cx * cz) >> 12;
    int b1 = gpf(sy, a1), b2 = gpf(sy, a2), b3 = gpf(sy, i6);
    int i9 = (cx * sz) >> 12;
    int c1 = gpf(cy, cz), c2 = gpf(cy, -sz), c3 = gpf(cy, cx);
    m[0][0] = (int16_t)c1; m[0][1] = (int16_t)c2; m[0][2] = (int16_t)sy;
    m[1][0] = (int16_t)(b1 + i9); m[1][1] = (int16_t)(i6 - b2); m[1][2] = (int16_t)-a3;
    m[2][0] = (int16_t)(a2 - b3); m[2][1] = (int16_t)(((i9 * sy) >> 12) + a1); m[2][2] = (int16_t)c3;
}

static void mul_matrix2(const int32_t a[3][3], int32_t b[3][3]) {      /* b = a x b */
    int32_t out[3][3];
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            out[i][j] = sat16(((int64_t)a[i][0] * b[0][j] + (int64_t)a[i][1] * b[1][j]
                               + (int64_t)a[i][2] * b[2][j]) >> 12);
    memcpy(b, out, sizeof out);
}

static void apply_matrix(const int32_t m[3][3], int x, int y, int z, int32_t out[3]) {
    for (int i = 0; i < 3; i++)
        out[i] = (int32_t)(((int64_t)m[i][0] * x + (int64_t)m[i][1] * y + (int64_t)m[i][2] * z) >> 12);
}

/* The tiles' GTE state, as 0x8006D014 builds it for the PS1 stage, with
 * the arcade stage's units (/ 10, not >> 3) and origin height. */
static void tile_matrix(Gte *g, int ps1_units) {
    int32_t cam[3][3], axis[3][3];
    int pitch = (int)psx_mod_read_word(CAMERA), yaw = (int)psx_mod_read_word(CAMERA + 4);
    int roll = (int)psx_mod_read_word(CAMERA + 8);
    int camx = (int)psx_mod_read_word(CAMERA + 0x14), camy = (int)psx_mod_read_word(CAMERA + 0x18);
    int camz = (int)psx_mod_read_word(CAMERA + 0x1C);
    rot_ps1(pitch, yaw, -roll, cam);
    for (int k = 0; k < 3; k++) cam[1][k] = (int16_t)((cam[1][k] * 0x14) / 0xC);
    /* a TTT stage's axis starts at its own value (stage 3: 0x800, 7: 0xF0),
     * the PS1's at 0: the stage turned by that much more (0 for T3) */
    rot_ps1(0, -((int)psx_mod_read_word(AXIS) + (ps1_units ? 0 : s_pack.axis0)), 0, axis);
    /* the point the stage follows (0x80062B04 picks the smoothed fighter) */
    int dx, dz;
    if (psx_mod_read_byte(FIXED_STAGE)) {
        dx = -camx; dz = -camz;
    } else {
        int p1x = (int)psx_mod_read_word(P1_X), p1z = (int)psx_mod_read_word(P1_Z);
        int p2x = (int)psx_mod_read_word(P2_X), p2z = (int)psx_mod_read_word(P2_Z);
        int pick = -1;
        if (psx_mod_read_half(0x800A923Eu) == 4 && psx_mod_read_byte(psx_mod_read_word(0x800A927Cu) + 0x24) == 'S')
            pick = 0;
        else if (psx_mod_read_half(0x800AAACAu) == 4 && psx_mod_read_byte(psx_mod_read_word(0x800AAB08u) + 0x24) == 'S')
            pick = 1;
        if (pick == 0) {
            int hx = 0, hz = 0;
            for (unsigned k = 0; k < 4; k++) {
                hx += (int)psx_mod_read_word(HISTORY_P1 + 16 * k);
                hz += (int)psx_mod_read_word(HISTORY_P1 + 8 + 16 * k);
            }
            dx = (((hx >> 2) + p2x) >> 1) - camx;
            dz = (((hz >> 2) + p2z) >> 1) - camz;
        } else if (pick == 1) {
            int hx = 0, hz = 0;
            for (unsigned k = 0; k < 4; k++) {
                hx += (int)psx_mod_read_word(HISTORY_P2 + 16 * k);
                hz += (int)psx_mod_read_word(HISTORY_P2 + 8 + 16 * k);
            }
            dx = (((hx >> 2) + p1x) >> 1) - camx;
            dz = (((hz >> 2) + p1z) >> 1) - camz;
        } else {
            dx = ((p2x + p1x) >> 1) - camx;
            dz = ((p2z + p1z) >> 1) - camz;
        }
    }
    int vx, vy, vz;
    if (ps1_units) {        /* the PS1's own stage (probe: the GTE it must give) */
        int y0 = (int16_t)psx_mod_read_half(0x80025138u + 4 * psx_mod_read_word(0x800B0460u));
        vx = (int16_t)(dx >> 3); vz = (int16_t)((int16_t)dz >> 3); vy = (int16_t)((int16_t)(y0 - camy) >> 3);
    } else {
        vx = (int16_t)dx / 10; vz = (int16_t)dz / 10; vy = (int16_t)(STAGE_Y - camy) / 10;
    }
    apply_matrix(cam, vx, vy, vz, g->t);
    memcpy(g->r, axis, sizeof axis);
    mul_matrix2(cam, g->r);
}

/* ------------------------------------------------------------------ */
/* the pack                                                           */
/* ------------------------------------------------------------------ */
/* mods/arcade-stages beside the game (PC and Android), where CMakeLists.txt
 * stages the setup's packs (tools/arcade_stages/install.py);
 * TEKKEN3_ARCADE_STAGES_DIR for the development benches. TTT's: mods/ttt-stages
 * (tools/arcade_stages/pack.py --game ttt), TEKKEN3_TTT_STAGES_DIR. */
static char s_dir[2][1024];

static const char *pack_dir_of(int source) {
    int k = source == TEKKEN3_STAGE_TTT;
    if (s_dir[k][0]) return s_dir[k];
    const char *e = getenv(k ? "TEKKEN3_TTT_STAGES_DIR" : "TEKKEN3_ARCADE_STAGES_DIR");
    if (e && *e) snprintf(s_dir[k], sizeof s_dir[k], "%s", e);
    else {
        const char *base = SDL_GetBasePath();
        snprintf(s_dir[k], sizeof s_dir[k], "%smods/%s", base ? base : "", k ? "ttt-stages" : "arcade-stages");
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
    return s_dir[k];
}

static const char *pack_dir(void) { return pack_dir_of(TEKKEN3_STAGE_T3); }

/* the section table: from byte 16 (format 3), 24 (format 4: the source) */
static const uint8_t *section(const uint8_t *b, const char *id) {
    uint32_t n; memcpy(&n, b + 8, 4);
    uint16_t version; memcpy(&version, b + 4, 2);
    unsigned base = version >= PACK_FORMAT_TTT ? 24 : 16;
    for (uint32_t i = 0; i < n; i++)
        if (!memcmp(b + base + 12 * i, id, 4)) { uint32_t o; memcpy(&o, b + base + 4 + 12 * i, 4); return b + o; }
    return NULL;
}

static unsigned s_pack_generation;      /* a new value at each pack loaded or freed */
static void pack_free(void) {
    free(s_pack.file);
    free(s_pack.apixels);
    free(s_pack.hivram);
    memset(&s_pack, 0, sizeof s_pack);
    s_pack.stage = -1;
    s_pack_generation++;
}

/* The upper half the loaded stage pack holds (TTT Hitspark places TTT1's
 * common sparks around it, src/tekken3_ttt1_combat.c): its generation, and
 * whether a rectangle overlaps the pack's VRAM rectangles, its animated
 * texture or where a TTT stage's moving textures land (tanm_step: fixed
 * places, and a palette row read from its TANM). No pack, nothing held. */
static int overlap(int x, int y, int w, int h, int rx, int ry, int rw, int rh) {
    return x < rx + rw && rx < x + w && y < ry + rh && ry < y + h;
}
static int tanm_overlap(int x, int y, int w, int h) {
    const Pack *p = &s_pack;
    if (!p->tanm) return 0;
    const uint8_t *q = p->tanm + 4, *dest = NULL;
    static const int16_t moves[][5] = {   /* stage, x, y, w, h */
        {3, 0x10, 0x280, 16, 64}, {3, 0x10, 0x2C0, 16, 64}, {3, 0x50, 0x300, 16, 64},
        {6, 0x58, 0x2C0, 8, 64}, {6, 0x90, 0x230, 16, 32}, {6, 0, 0x240, 16, 64}, {6, 0, 0x200, 16, 64},
        {7, 0x20, 0x3C0, 16, 64}};
    for (unsigned i = 0; i < sizeof moves / sizeof *moves; i++)
        if (moves[i][0] == p->stage && overlap(x, y, w, h, moves[i][1], moves[i][2], moves[i][3], moves[i][4]))
            return 1;
    if (p->stage == 6) { uint32_t nm; memcpy(&nm, q + 608, 4); dest = q + 612 + 12 * nm; }
    else if (p->stage == 7) dest = q + 364 + 8 * 53;
    else if (p->stage == 14) dest = q + 64 + 128;
    if (!dest) return 0;
    uint16_t d[2]; memcpy(d, dest, 4);
    return overlap(x, y, w, h, d[0], d[1], 16, 1);
}
unsigned tekken3_stage_high_vram_generation(void) { return s_pack_generation; }
int tekken3_stage_high_vram_used(int x, int y, int w, int h) {
    const Pack *p = &s_pack;
    const uint8_t *o = p->file ? section(p->file, "VRAM") : NULL;
    if (!o) return 0;
    if (tanm_overlap(x, y, w, h)) return 1;
    if (p->aframes && overlap(x, y, w, h, p->ax, p->ay, p->aw, p->ah)) return 1;
    uint32_t n; memcpy(&n, o, 4); o += 4;
    for (uint32_t i = 0; i < n; i++) {
        uint16_t r[4]; memcpy(r, o, 8); o += 8 + 2u * r[2] * r[3];
        if (overlap(x, y, w, h, r[0], r[1], r[2], r[3])) return 1;
    }
    return 0;
}

static void anim_reset(void);
static void storm_reset(void);
static void ttt_anim_reset(void);
static uint32_t ttt_floor_light(int row, int col, uint32_t clut);

/* E5a: the 13 arcade stages, fixed (their objects and animations: E5b);
 * Gon's (13) and Dr. B's (14) arenas keep the PS1 stage. */
static int stage_supported(int arena) { return arena >= 0 && arena <= 12; }

/* A format 3 (T3) or 4 (TTT) pack's file, checked; NULL otherwise. */
static uint8_t *pack_read(int source, int stage, long *out_size, char *path, size_t path_size) {
    snprintf(path, path_size, "%s/stage%02d.ast", pack_dir_of(source), stage);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *b = size > 64 ? malloc((size_t)size) : NULL;
    int ok = b && fread(b, 1, (size_t)size, f) == (size_t)size;
    fclose(f);
    uint16_t version = 0, number = 0; uint32_t total = 0;
    if (ok) { memcpy(&version, b + 4, 2); memcpy(&number, b + 6, 2); memcpy(&total, b + 12, 4); }
    int ttt = source == TEKKEN3_STAGE_TTT;
    unsigned want = ttt ? PACK_FORMAT_TTT : PACK_FORMAT;
    if (!ok || memcmp(b, "ASTG", 4) || version != want || number != stage || total != (uint32_t)size
        || (ttt && memcmp(b + 16, "TTTA", 4)) || !section(b, "VRAM") || !section(b, "TILE")
        || (ttt ? !section(b, "FAR2") || !section(b, "TRG2") || !section(b, "MISC")
                : !section(b, "FARB") || !section(b, "FLOR") || !section(b, "TRIG"))) {
        fprintf(stdout, "arcade stages: %s is not a format %u pack of stage %d\n", path, want, stage);
        free(b);
        return NULL;
    }
    *out_size = size;
    return b;
}

/* TTT's sections (format 4): far background rules, floor, sine, storm,
 * thunder, axis and OT ranks. */
static int pack_ttt(Pack *p) {
    const uint8_t *b = p->file, *o;
    o = section(b, "MISC");
    uint32_t axis; uint16_t ranks[2];
    memcpy(&axis, o, 4); memcpy(ranks, o + 4, 4);
    p->axis0 = (int)axis; p->rank_a = ranks[0]; p->rank_b = ranks[1];
    if (p->rank_a > 1023 || p->rank_b > 1023) return 0;
    o = section(b, "TRG2");
    p->tsine = (const int16_t *)o; p->tsqrt = p->tsine + 5120;
    /* FAR2: FARB's fields, then the rules */
    o = section(b, "FAR2");
    int16_t h[6]; memcpy(h, o, 12);
    p->fcols = h[0]; p->frows = h[1]; p->fring = h[2]; p->fyoff = h[3]; p->fdegrees = h[4]; p->fpitch = h[5];
    p->fcolours = o + 12;
    p->fmode = o[23]; p->fclamp = o[24]; p->fhas_min = o[25];
    memcpy(&p->fmin_y, o + 26, 2);
    memcpy(p->fgradient, o + 28, 3);
    o += 32;
    p->fdesc = (const uint16_t *)o; o += 2 * p->fcols * p->frows;
    p->fcluts = (const uint16_t *)o; o += 2 * p->fcols * p->frows;
    p->fkinds = o;
    if (p->fcols <= 0 || p->frows < 0 || p->fring <= 0 || p->fdegrees <= 0) return 0;
    /* FLR2 */
    o = section(b, "FLR2");
    if (o) {
        int16_t f[3]; memcpy(f, o, 6);
        p->gkind = f[0]; p->gfog = f[1]; p->gsize = f[2];
        p->gcols = o[6]; p->grows = o[7]; p->ghalf = o[8];
        o += 12;
        p->gcells = (const uint32_t *)o; o += 1800;
        p->gunique = o; o += 228;
        p->gramp = o; o += 1024;
        memcpy(&p->gnv, o, 2); p->gverts = (const int16_t *)(o + 2);
        o += (2 + 4 * p->gnv + 3) & ~3u;
        memcpy(&p->gnq, o, 4); p->gquads = (const uint32_t *)(o + 4);
        o += 4 + 4 * p->gnq;
        p->gcorners = (const uint16_t *)o;
        p->gfloor = p->gkind >= 0 && p->gkind <= 2 && p->gsize > 0 && p->gcols && p->gcols <= 15 && p->grows
                 && p->grows <= 15 && p->gnv <= 256 && p->gnq == (uint32_t)p->gcols * p->grows;
    }
    /* STRM: stage 4's storm */
    o = section(b, "STRM");
    if (o) {
        memcpy(p->sthreshold, o, 10); o += 12;
        for (int k = 0; k < 6; k++) memcpy(p->scolour[k], o + 4 * k, 3);
        o += 24;
        const uint8_t *q = o;
        for (int k = 0; k < 6; k++) { p->sseqlen[k] = *q; p->sseq[k] = (const int8_t *)(q + 1); q += 1 + *q; }
        o += ((size_t)(q - o) + 3) & ~(size_t)3;
        size_t n = (size_t)p->fcols * p->frows;
        for (int k = 0; k < 6; k++) {
            p->sskydesc[k] = (const uint16_t *)o; o += 2 * n;
            p->sskyclut[k] = (const uint16_t *)o; o += 2 * n;
        }
        memcpy(p->ssound, o, 20); o += 20;
        memcpy(p->sforced, o, 8);
        p->storm = 1;
        for (int k = 0; k < 6; k++) if (!p->sseqlen[k]) p->storm = 0;
    }
    o = section(b, "THND");
    if (o) {
        uint32_t n; memcpy(&n, o, 4);
        for (uint32_t i = 0; i < n && i < 8; i++) {
            uint16_t sound; uint32_t frames, off;
            memcpy(&sound, o + 4 + 12 * i, 2); memcpy(&frames, o + 8 + 12 * i, 4); memcpy(&off, o + 12 + 12 * i, 4);
            if (o + off + 2u * frames > b + p->size) break;
            p->thunder[p->nthunder++] = (Thunder){sound, frames, (const int16_t *)(o + off)};
        }
    }
    /* TTT Stages S4: stage 11's floor lights and light beams, stage 2's particles */
    o = section(b, "LITE");
    if (o) {
        uint32_t nl; memcpy(&nl, o, 4);
        if (nl == 480) p->lite = (const uint32_t *)(o + 4);
    }
    p->part = section(b, "PART");
    p->glow = section(b, "GLOW");
    p->togr = section(b, "TOGR");
    return 1;
}

static int pack_load_from(int source, int stage) {
    char path[1024];
    long size = 0;
    uint8_t *b = pack_read(source, stage, &size, path, sizeof path);
    if (!b) return 0;
    pack_free();
    Pack *p = &s_pack;
    p->file = b; p->size = (uint32_t)size; p->stage = stage; p->source = source;
    p->rank_a = 1010; p->rank_b = 1021;
    /* animated texture: its frames are kept from the VRAM rectangles */
    const uint8_t *o = source == TEKKEN3_STAGE_T3 ? section(b, "ANIM") : NULL;
    const uint16_t *frames = NULL;
    if (o) {
        uint16_t h[6]; memcpy(h, o, 12);
        p->ax = h[0]; p->ay = h[1]; p->aw = h[2]; p->ah = h[3]; p->aperiod = h[4]; p->aframes = h[5];
        frames = (const uint16_t *)(o + 12);
        p->apixels = p->aframes && p->aperiod ? calloc((size_t)p->aframes * p->aw * p->ah, 2) : NULL;
        if (!p->apixels) p->aframes = 0;
    }
    /* TTT's animated textures copy VRAM to VRAM (MoveImage): a copy of the
     * upper half as the pack poses it is their source */
    if (source == TEKKEN3_STAGE_TTT && (p->tanm = section(b, "TANM")) != NULL) {
        p->hivram = calloc((size_t)1024 * 512, 2);
        if (!p->hivram) p->tanm = NULL;
    }
    /* VRAM: rectangles in the upper half */
    o = section(b, "VRAM");
    uint32_t n; memcpy(&n, o, 4); o += 4;
    for (uint32_t i = 0; i < n; i++) {
        uint16_t r[4]; memcpy(r, o, 8); o += 8;
        if (!psx_mod_gpu_high_vram_upload(r[0], r[1], r[2], r[3], (const uint16_t *)o)) {
            fprintf(stdout, "arcade stages: upload %u,%u %ux%u refused\n", r[0], r[1], r[2], r[3]);
            pack_free();
            return 0;
        }
        if (p->hivram && r[1] >= 512 && r[1] + r[3] <= 1024 && r[0] + r[2] <= 1024)
            for (unsigned y = 0; y < r[3]; y++)
                memcpy(&p->hivram[(size_t)(r[1] - 512 + y) * 1024 + r[0]], o + 2u * y * r[2], 2u * r[2]);
        for (unsigned f = 0; f < p->aframes; f++) {        /* the parts of the frames this one holds */
            int fx = frames[2 * f], fy = frames[2 * f + 1];
            for (int y = 0; y < p->ah; y++) {
                int vy = fy + y - r[1];
                if (vy < 0 || vy >= r[3]) continue;
                for (int x = 0; x < p->aw; x++) {
                    int vx = fx + x - r[0];
                    if (vx >= 0 && vx < r[2])
                        memcpy(&p->apixels[((size_t)f * p->ah + y) * p->aw + x], o + 2u * ((unsigned)vy * r[2] + vx), 2);
                }
            }
        }
        o += 2u * r[2] * r[3];
    }
    s_pack_generation++;
    /* objects: models, then the drawing calls (T3's stages 3 and 11; TTT's
     * stage 3, its stage 11 helicopter flying in the rankings only: TTT Stages
     * S4), then (format 4) the model frame */
    o = section(b, "OBJS");
    p->rot = (const uint32_t *)section(b, "ROTT");
    if (o && p->rot) {
        uint32_t nm; memcpy(&nm, o, 4); o += 4;
        for (uint32_t i = 0; i < nm && i < 4; i++) {
            uint16_t c[2]; memcpy(c, o, 4); o += 4;
            Model *m = &p->models[p->nmodels++];
            m->nv = c[0]; m->np = c[1];
            m->v = (const Vert *)o; o += 8u * m->nv;
            m->p = (const Prim *)o; o += sizeof(Prim) * m->np;
        }
        memcpy(&p->nlayout, o, 4);
        p->layout = (const Layout *)(o + 4);
        if (nm > 4 || p->nlayout > 8) { pack_free(); return 0; }
        if (source == TEKKEN3_STAGE_TTT) memcpy(p->oframe, o + 4 + sizeof(Layout) * p->nlayout, 12);
        for (unsigned i = 0; i < p->nlayout; i++)
            if (p->layout[i].model >= p->nmodels || p->models[p->layout[i].model].nv > 0x100) { pack_free(); return 0; }
    }
    /* tiles */
    o = section(b, "TILE");
    memcpy(&p->tile_size, o, 4); memcpy(&p->ntiles, o + 4, 4); o += 8;
    if (p->ntiles > 256) { pack_free(); return 0; }
    for (unsigned i = 0; i < p->ntiles; i++) {
        Tile *t = &p->tiles[i];
        t->head = (const TileHead *)o; o += 8;
        t->v = (const Vert *)o; o += 8u * t->head->nv;
        t->p = (const Prim *)o; o += sizeof(Prim) * t->head->np;
    }
    if (source == TEKKEN3_STAGE_TTT) {
        if (!pack_ttt(p)) { fprintf(stdout, "arcade stages: %s: bad TTT sections\n", path); pack_free(); return 0; }
        fprintf(stdout, "arcade stages: TTT stage %d loaded from %s (%ld bytes, %u textures and palettes, floor %s, "
                "storm %s, %u thunder sounds, %u objects, animated textures %s, floor lights %s, particles %s, "
                "light beams %s)\n", stage, path, size, (unsigned)n, p->gfloor ? "yes" : "no",
                p->storm ? "yes" : "no", p->nthunder, p->nlayout, p->tanm ? "yes" : "no", p->lite ? "yes" : "no",
                p->part ? "yes" : "no", p->glow ? "yes" : "no");
        fflush(stdout);
        storm_reset();
        ttt_anim_reset();
        return 1;
    }
    /* far background */
    o = section(b, "FARB");
    int16_t h[6]; memcpy(h, o, 12); o += 12;
    p->fcols = h[0]; p->frows = h[1]; p->fring = h[2]; p->fyoff = h[3]; p->fdegrees = h[4]; p->fpitch = h[5];
    p->fcolours = o; o += 12;
    p->fdesc = (const uint16_t *)o; o += 2 * p->fcols * p->frows;
    p->fcluts = (const uint16_t *)o; o += 2 * p->fcols * p->frows;
    p->fkinds = o;
    /* floor */
    o = section(b, "FLOR");
    memcpy(&p->lkind, o, 2); memcpy(&p->lfog, o + 2, 2); memcpy(&p->lnear, o + 4, 4); o += 8;
    p->lcells = (const uint32_t *)o; p->lhalves = p->lcells + 200; o += 4000;
    p->lunique = o; o += 100;
    memcpy(&p->lnv, o, 2); p->lverts = (const int16_t *)(o + 2);
    o += (2 + 4 * p->lnv + 3) & ~3u;
    memcpy(p->lcount, o, 100); o += 100;
    for (unsigned c = 0; c < 100; c++) { p->lquads[c] = (const uint32_t *)o; o += 4u * p->lcount[c]; }
    for (unsigned k = 1; k <= 4; k <<= 1) { p->luv[k] = (const uint16_t *)o; o += 2u * 4 * k * 4; }
    if (p->lkind < 0 || p->lkind > 2 || p->lnv > 256) { pack_free(); return 0; }
    o = section(b, "TRIG");
    p->sin = (const int16_t *)o; p->cos = p->sin + 4096; p->sqrt1 = p->cos + 4096;
    p->fog = (const uint8_t *)(p->sqrt1 + 192); p->sqrt2 = (const int16_t *)(p->fog + 1024);
    fprintf(stdout, "arcade stages: stage %d loaded from %s (%ld bytes, %u textures and palettes, %u objects, "
            "%u animation frames)\n", stage, path, size, (unsigned)n, p->nlayout, p->aframes);
    fflush(stdout);
    anim_reset();
    return 1;
}

static int pack_load(int arena) { return pack_load_from(TEKKEN3_STAGE_T3, arena); }

/* The TTT stage this frame wants: a cinematic's, else the STAGES row's for
 * the fight; -1 none. */
static int ttt_wanted(void) {
    if (!s_ttt_on) return -1;
    if (s_force >= 0) return s_force;
    return tekken3_stage_source() == TEKKEN3_STAGE_TTT ? tekken3_stage_ttt_stage() : -1;
}

/* B124: TTT's True Ogre variant, its stages at night (0x801501C4 with
 * 0x8015CE68(0x14): True Ogre in a team), here in Tekken 3's dark arena
 * (0x800AFAA0: True Ogre fights, 0x80050F5C) of a fight, not a cinematic's
 * stage: every colour the stage's TOGR byte (but stage 6's rewritten FT4),
 * the tiles and primitives skipped with True Ogre, TOGR's floor kind, a
 * black far background (0x80243790), no objects (0x801600C0), no stage 7
 * animation (0x8015F6A4; its night texture file 5/12 lands only where the
 * tiles left at night never read). ttt.Stage(true_ogre=True) is the
 * reference. Not Unknown's stage for True Ogre as Arcade's CPU, the boss:
 * drawn as it is. */
static int ttt_night(void) {
    return s_pack.source == TEKKEN3_STAGE_TTT && s_pack.togr && s_force < 0 && psx_mod_read_byte(DARK_ARENA)
           && !tekken3_stage_true_ogre_boss();
}

/* The arcade stage draws this frame. */
static int active(void) {
    if (!s_on || !psx_mod_gpu_high_vram_ready() || !psx_mod_game_started()) return 0;
    if (psx_mod_read_byte(NO_STAGE)) return 0;
    uint32_t mode = psx_mod_read_word(MODE);
    if (mode == 7 || mode == 8) return 0;
    /* The dark arena (True Ogre's fight) keeps the PS1's flat stage, unless
     * a TTT stage is wanted there: drawn at night (ttt_night). */
    int ttt = ttt_wanted();
    if (psx_mod_read_byte(DARK_ARENA) && ttt < 0) return 0;
    if (ttt >= 0) {
        if (s_pack.source != TEKKEN3_STAGE_TTT || ttt != s_pack.stage) {
            if (ttt == s_tried_ttt) return 0;
            s_tried_ttt = ttt;
            if (!pack_load_from(TEKKEN3_STAGE_TTT, ttt)) return 0;
            s_tried = -1;
        }
        trig_ps1();
        return 1;
    }
    s_tried_ttt = -1;
    if (!s_t3_on) return 0;
    int arena = psx_mod_read_half(ARENA);
    if (s_pack.source != TEKKEN3_STAGE_T3 || arena != s_pack.stage) {
        if (arena == s_tried) return 0;
        s_tried = arena;
        if (!stage_supported(arena) || !pack_load(arena)) return 0;
    }
    trig_ps1();
    return 1;
}

/* ------------------------------------------------------------------ */
/* packets                                                            */
/* ------------------------------------------------------------------ */
static uint32_t s_cursor, s_end;

static uint32_t alloc_words(unsigned words) {
    uint32_t a = s_cursor;
    if (a + 4u * words > s_end) return 0;
    s_cursor += 4u * words;
    return a;
}

static void add_prim(uint32_t ot, uint32_t p, unsigned words) {
    uint32_t e = psx_mod_read_word(ot);
    psx_mod_write_word(p, (uint32_t)words << 24 | (e & 0xFFFFFFu));
    psx_mod_write_word(ot, (e & 0xFF000000u) | (p & 0xFFFFFFu));
}

static uint32_t main_ot(unsigned rank) {
    return psx_mod_read_word(psx_mod_read_word(DRAWENV) + 4) + 4u * rank;
}

static unsigned buffer(void) { return psx_mod_read_word(OT_BUFFER) & 1u; }

/* At the start of a drawing hook, while the options are on: the points of
 * one frame are the floor's and the tiles' (T-junctions between them are
 * common). The frame is told by the OT buffer both draw into, not by the
 * counter 0x800A08F0, which advances inside 0x8006D014 between the floor
 * and the tiles; a hook that comes back with no buffer change starts a new
 * frame too. */
static void tj_begin(unsigned hook) {
    int b = (int)buffer();
    if (b != s_tj_buffer || (s_tj_hooks & hook)) {
        s_tj_buffer = b;
        s_tj_hooks = 0;
        s_tj_npt = s_tj_nword = s_tj_ntri = s_tj_ncur = 0;
        memset(s_tj_hash, -1, sizeof s_tj_hash);
    }
    s_tj_hooks |= hook;
}

/* TTT's ranks are TTT's own order (far background 1023, OT B 1021, floor
 * 1021 - rank of its texture down to 981, OT A 995; stage 3: A 1021, B 1022),
 * not the PS1's: in the PS1's OT, T3 draws its HUD at 1009..1006 and its stage
 * at 1010 (§ 92-93). So a TTT stage goes in a private OT of TTT ranks
 * 976..1023, the order MAME gives kept inside, linked as a whole at main rank
 * 1010, where the PS1 links its own stage: behind everything T3 draws nearer
 * (HUD, fighters, effects, pause menu). It lies at the start of the buffer's
 * packet memory, set up once a frame (the floor, drawn before the tiles,
 * may come first). B77: three slots more behind rank 1023 (TTT's ranks
 * stop there), drawn first, in this order: TTT_OT_FILL, plain colours only
 * seen where nothing else covers (the far background's empty cells and the
 * band below its lowest); TTT_OT_FAR, the far background (TTT's 1023);
 * TTT_OT_WIDE, the tiles and the floor's cells widened by a pixel
 * (wide_prim, ttt_floor_grid). The widened copies thus cover the slits
 * between the stage's pieces, where the far background showed through, but
 * nothing of the stage itself. B121: an empty end entry before rank 976,
 * like T3's list: linking rewrites the end's next word, and stage 2's
 * snow and stage 11's beams, linked at 976 (TTT_OT_FIRST), went with it. */
#define TTT_OT_END    975
#define TTT_OT_FIRST  976
#define TTT_OT_LAST   1023
#define TTT_OT_WIDE   1024
#define TTT_OT_FAR    1025
#define TTT_OT_FILL   1026
#define TTT_OT_RANKS  (TTT_OT_FILL - TTT_OT_END + 1)
#define TTT_OT_LINK  1010
static uint32_t s_ttt_ot;
static unsigned s_draws, s_ttt_ot_draw = ~0u;   /* stage frames drawn; the one the OT was set up for */

static uint32_t ttt_ot(void) {
    if (s_ttt_ot_draw != s_draws) {
        s_ttt_ot = s_memory + BUFFER_BYTES * buffer();
        psx_mod_write_word(s_ttt_ot, 0xFFFFFFu);
        for (unsigned i = 1; i < TTT_OT_RANKS; i++)
            psx_mod_write_word(s_ttt_ot + 4 * i, (s_ttt_ot + 4 * (i - 1)) & 0xFFFFFFu);
        s_ttt_ot_draw = s_draws;
    }
    return s_ttt_ot;
}

/* where a stage packet of `rank` is linked: the main OT (T3, as before), or
 * TTT's private OT (ranks up to 1023; ttt_slot for the slots behind) */
static uint32_t stage_ot(unsigned rank) {
    if (s_pack.source != TEKKEN3_STAGE_TTT) return main_ot(rank);
    if (rank < TTT_OT_FIRST) rank = TTT_OT_FIRST;
    if (rank > TTT_OT_LAST) rank = TTT_OT_LAST;
    return ttt_ot() + 4u * (rank - TTT_OT_END);
}

static uint32_t ttt_slot(unsigned slot) { return ttt_ot() + 4u * (slot - TTT_OT_END); }

static unsigned stage_rank(uint32_t ot) {
    return s_pack.source == TEKKEN3_STAGE_TTT ? (unsigned)((ot - s_ttt_ot) / 4 + TTT_OT_END) : (unsigned)((ot - main_ot(0)) / 4);
}

/* the TTT OT into the main one at 1010, once the frame's stage is drawn */
static void ttt_ot_link(void) {
    uint32_t ot = ttt_ot(), r = main_ot(TTT_OT_LINK);
    psx_mod_write_word(ot, (psx_mod_read_word(ot) & 0xFF000000u) | (psx_mod_read_word(r) & 0xFFFFFFu));
    psx_mod_write_word(r, (psx_mod_read_word(r) & 0xFF000000u) | ((ot + 4u * (TTT_OT_RANKS - 1)) & 0xFFFFFFu));
}

/* B87: T3's arcade stages have slits a pixel wide between their pieces
 * (tiles, the floor grid's cells), seen under the PS1's cameras: the layer
 * of widened copies behind them (wide_prim), in a list at the start of the
 * buffer's packet memory like TTT's OT: an empty end entry (linking rewrites
 * its next word), then the slot, linked at main rank 1022: over the far
 * background (1023), under the floor (1021..982) and the tiles (1021, 1010),
 * before stage 11's helicopter is put at 1022 in front of it. */
#define T3_OT_END   0
#define T3_OT_WIDE  1
#define T3_OT_SLOTS 2
#define T3_OT_LINK  1022
static uint32_t s_t3_ot;
static unsigned s_t3_ot_draw = ~0u;

static uint32_t t3_ot(void) {
    if (s_t3_ot_draw != s_draws) {
        s_t3_ot = s_memory + BUFFER_BYTES * buffer();
        psx_mod_write_word(s_t3_ot + 4 * T3_OT_END, 0xFFFFFFu);
        psx_mod_write_word(s_t3_ot + 4 * T3_OT_WIDE, (s_t3_ot + 4 * T3_OT_END) & 0xFFFFFFu);
        s_t3_ot_draw = s_draws;
    }
    return s_t3_ot;
}

static void t3_ot_link(void) {
    uint32_t end = t3_ot() + 4u * T3_OT_END, r = main_ot(T3_OT_LINK);
    psx_mod_write_word(end, (psx_mod_read_word(end) & 0xFF000000u) | (psx_mod_read_word(r) & 0xFFFFFFu));
    psx_mod_write_word(r, (psx_mod_read_word(r) & 0xFF000000u) | ((end + 4u * T3_OT_WIDE) & 0xFFFFFFu));
}

/* the widened copies' slot, either source */
static uint32_t wide_slot(void) {
    return s_pack.source == TEKKEN3_STAGE_TTT ? ttt_slot(TTT_OT_WIDE) : t3_ot() + 4u * T3_OT_WIDE;
}

static void tile_rect(uint32_t ot, int x, int y, int w, int h, const uint8_t c[3]) {
    if (w <= 0 || h <= 0) return;
    uint32_t p = alloc_words(4);
    if (!p) return;
    psx_mod_write_word(p + 4, 0x60000000u | rgbw(c));
    psx_mod_write_word(p + 8, xy(x, y));
    psx_mod_write_word(p + 12, (uint32_t)h << 16 | (uint32_t)w);
    add_prim(ot, p, 3);
    s_stat_far++;
}

/* ------------------------------------------------------------------ */
/* far background (0x801A7688), arcade 512 x 240 mapped on the PS1      */
/* screen at the same angle per pixel                                 */
/* ------------------------------------------------------------------ */
typedef struct { int ofx, ofy, h, margin; } Screen;

static int map_x(const Screen *s, int x) { return s->ofx + (int)(((int64_t)(x - 256) * s->h) / 600); }
static int map_y(const Screen *s, int y) { return s->ofy + (int)(((int64_t)(y - 120) * s->h) / 225); }

static int per_degree(int degrees) {
    int64_t v = (int64_t)degrees << 12;
    int64_t hi = (v * ((int64_t)0xB60B60B7 - ((int64_t)1 << 32))) >> 32;
    return (int)(((hi + v) >> 8) - (v >> 31));
}

static void band(uint32_t ot, const Screen *s, int y0, int y1, const uint8_t c[3]) {
    int a = map_y(s, y0), b = map_y(s, y1);
    if (a < 0) a = 0;
    tile_rect(ot, -s->margin, a, SCREEN_W + 2 * s->margin, b - a, c);
}

/* One far background cell of row r (kind index ci, column k) on the screen
 * rectangle given: a 64 x 64 texel cell (0x31), the cell colour (0x74), the
 * bottom colour (0x64), or nothing (any other kind: returns 0). ot = 0:
 * only whether it draws. */
static int far_cell(uint32_t ot, int r, int ci, int k, int xa, int ya, int xb, int yb) {
    const Pack *p = &s_pack;
    int kind = p->fkinds[r * p->fring + ci];
    if (kind != 0x31 && kind != 0x74 && kind != 0x64) return 0;
    if (!ot) return 1;
    if (kind == 0x74 || kind == 0x64) {
        tile_rect(ot, xa, ya, xb - xa, yb - ya, kind == 0x74 ? p->fcolours : p->fcolours + 7);
        return 1;
    }
    uint16_t d = p->fdesc[r * p->fcols + k];
    int tx = (d >> 2) & 0x3C0, ty = (d >> 4) & 0x300;
    uint32_t tp = (uint32_t)(((ty & 0x100) >> 4 | tx >> 6) | (ty & 0x200) << 2);
    int u = (d & 3) << 6, v = (d << 4) & 0xC0;
    int v0 = v, v1 = v + 0x3F;
    if (p->stage == 5 && r == 3) { v0 = v + 0x3F; v1 = v; }
    uint32_t clut = p->fcluts[r * p->fcols + k];
    uint32_t q = alloc_words(10);
    if (q) {
        psx_mod_write_word(q + 4, 0x2C808080u);
        psx_mod_write_word(q + 8, xy(xa, ya));
        psx_mod_write_word(q + 12, clut << 16 | (uint32_t)v0 << 8 | (uint32_t)u);
        psx_mod_write_word(q + 16, xy(xb, ya));
        psx_mod_write_word(q + 20, tp << 16 | (uint32_t)v0 << 8 | (uint32_t)(u + 0x3F));
        psx_mod_write_word(q + 24, xy(xa, yb));
        psx_mod_write_word(q + 28, (uint32_t)v1 << 8 | (uint32_t)u);
        psx_mod_write_word(q + 32, xy(xb, yb));
        psx_mod_write_word(q + 36, (uint32_t)v1 << 8 | (uint32_t)(u + 0x3F));
        add_prim(ot, q, 9);
        s_stat_far++;
    }
    return 1;
}

static void far_background(const Screen *s, int yaw, int pitch) {
    const Pack *p = &s_pack;
    uint32_t ot = main_ot(1023);
    const uint8_t *cell_rgb = p->fcolours, *top_rgb = p->fcolours + 3, *bottom_rgb = p->fcolours + 7;
    int top_on = p->fcolours[6], bottom_on = p->fcolours[10];
    const int H = 0xF0, step = 0x20;
    int a = tdiv((int64_t)((-yaw) & 0xFFF) << 9, per_degree(p->fdegrees));
    int scroll = tmod(a, p->fcols << 6);
    int col0 = tdiv(scroll, 64), kind0 = tdiv(tmod(a, p->fring << 6), 64);
    int y = tdiv((int64_t)-s12(pitch) * p->fpitch, 256) + p->fyoff;
    int st = p->stage;
    if (st == 6) { band(ot, s, 0, H, top_rgb); return; }
    if (st == 3) {      /* a gradient, then the bottom colour */
        if (y > 0) y = 0;
        int y2 = y + 0x60;
        uint32_t q = alloc_words(9);
        if (q) {
            int ya = map_y(s, y), yb = map_y(s, y2), xa = -s->margin, xb = SCREEN_W + s->margin;
            const uint32_t top = 0x661400u;                       /* (0, 0x14, 0x66) */
            psx_mod_write_word(q + 4, 0x38000000u | top); psx_mod_write_word(q + 8, xy(xa, ya));
            psx_mod_write_word(q + 12, top); psx_mod_write_word(q + 16, xy(xb, ya));
            psx_mod_write_word(q + 20, 0); psx_mod_write_word(q + 24, xy(xa, yb));
            psx_mod_write_word(q + 28, 0); psx_mod_write_word(q + 32, xy(xb, yb));
            add_prim(ot, q, 8);
        }
        band(ot, s, y2, H * 75 / 100, bottom_rgb);
        return;
    }
    if ((st == 11 || st == 0 || st == 5) && y > 0) y = 0;
    if (st == 11 && y < -0x60) y = -0x60;
    if (y > 0 && top_on) band(ot, s, 0, y, top_rgb);
    /* columns: the arcade's 9 from the left edge, more for the 16:9 margins */
    int left = (int)(((int64_t)(s->margin + s->ofx) * 600) / s->h) - 256;   /* arcade pixels left of 0 */
    int extra = left > 0 ? (left + 63) / 64 : 0;
    int count = 9 + 2 * extra;
    for (int r = 0; r < p->frows; r++) {
        int x = tdiv(scroll, 64) * 64 - scroll - 64 * extra;
        for (int c = -extra; c < count - extra; c++) {
            if (!(y < -0x40 || y > H)) {
                int ci = pmod(kind0 + c, p->fring), k = pmod(col0 + c, p->fcols);
                int xa = map_x(s, x), xb = map_x(s, x + 0x40), ya = map_y(s, y), yb = map_y(s, y + step);
                if (!far_cell(ot, r, ci, k, xa, ya, xb, yb)) {
                    /* B87: a cell the arcade leaves empty, behind buildings
                     * its cameras always see; the PS1's replay cameras turn
                     * past them (stage 7's roof, stage 1's wall end) and
                     * showed older frames there. The nearest cell above in
                     * the column (its sky) drawn again in its place, else
                     * the top colour, else the cell colour. */
                    int up = r - 1;
                    while (up >= 0 && !far_cell(0, up, ci, k, 0, 0, 0, 0)) up--;
                    if (up >= 0) far_cell(ot, up, ci, k, xa, ya, xb, yb);
                    else tile_rect(ot, xa, ya, xb - xa, yb - ya, top_on ? top_rgb : cell_rgb);
                }
            }
            x += 0x40;
        }
        y += step;
    }
    if (y < H && bottom_on) band(ot, s, y < 0 ? 0 : y, H * 75 / 100, bottom_rgb);
}

/* B77: the bottom colour on from TTT's lowest band (75 % of its screen) to
 * the PS1 screen's bottom, under everything (TTT_OT_FILL).
 * TTT's horizon never comes lower; under the PS1's cameras looking up, the
 * ground's horizon does, and the gap kept older frames. */
static void below_band(const Screen *s, int y, const uint8_t c[3]) {
    int a = map_y(s, y);
    if (a < 0) a = 0;
    tile_rect(ttt_slot(TTT_OT_FILL), -s->margin, a, SCREEN_W + 2 * s->margin, SCREEN_H - a, c);
}

/* TTT's far background (0x8011C7CC, ttt.farbg_commands): T3's algorithm with
 * the rules carried by the pack (mode 0 cells, 1 gradient, 2 the top colour
 * on the whole screen; y kept <= 0; a lowest y), its cell words (u = d * 32,
 * v = (d & 0x38) * 4, page from bits 8-11 and 12-13), and the cell textures
 * of `desc` / `cluts`: stage 4's storm swaps them (entries 15..20). Low
 * resolution (FT4 64 x 32), as MAME runs TTT; mapped on the PS1 screen as
 * T3's. */
static void ttt_far_texture(uint32_t ot, int r, uint16_t d, uint32_t clut, int xa, int ya, int xb, int yb) {
    uint32_t tp = (uint32_t)(((d >> 4) & 0x100) >> 4 | ((d >> 8) & 0xF) | ((d >> 4) & 0x200) << 2);
    int u = (d * 32) & 0xFF, v = ((d & 0x38) * 4) & 0xFF;
    int v0 = v, v1 = v + 0x3F;
    if (s_pack.stage == 5 && r == 3) { v0 = v + 0x3F; v1 = v; }
    uint32_t q = alloc_words(10);
    if (q) {
        psx_mod_write_word(q + 4, 0x2C808080u);
        psx_mod_write_word(q + 8, xy(xa, ya));
        psx_mod_write_word(q + 12, clut << 16 | (uint32_t)(v0 & 0xFF) << 8 | (uint32_t)u);
        psx_mod_write_word(q + 16, xy(xb, ya));
        psx_mod_write_word(q + 20, tp << 16 | (uint32_t)(v0 & 0xFF) << 8 | (uint32_t)((u + 0x3F) & 0xFF));
        psx_mod_write_word(q + 24, xy(xa, yb));
        psx_mod_write_word(q + 28, (uint32_t)(v1 & 0xFF) << 8 | (uint32_t)u);
        psx_mod_write_word(q + 32, xy(xb, yb));
        psx_mod_write_word(q + 36, (uint32_t)(v1 & 0xFF) << 8 | (uint32_t)((u + 0x3F) & 0xFF));
        add_prim(ot, q, 9);
        s_stat_far++;
    }
}

static void far_background_ttt(const Screen *s, int yaw, int pitch, const uint16_t *desc, const uint16_t *cluts) {
    const Pack *p = &s_pack;
    uint32_t ot = ttt_slot(TTT_OT_FAR);     /* TTT's rank 1023 */
    const uint8_t *cell_rgb = p->fcolours, *top_rgb = p->fcolours + 3, *bottom_rgb = p->fcolours + 7;
    int top_on = p->fcolours[6], bottom_on = p->fcolours[10];
    const int H = 0xF0, step = 0x20;
    if (p->fmode == 2) { band(ot, s, 0, H, top_rgb); return; }
    int a = tdiv((int64_t)((-yaw) & 0xFFF) << 9, tdiv((int64_t)p->fdegrees << 12, 360));
    int scroll = tmod(a, p->fcols << 6);
    int col0 = tdiv(scroll, 64), kind0 = tdiv(tmod(a, p->fring << 6), 64);
    int y = tdiv((int64_t)-s12(pitch) * p->fpitch, 256) + p->fyoff;
    if (p->fmode == 1) {        /* a gradient to black, then the bottom colour */
        if (y > 0) y = 0;
        int y2 = y + 0x60;
        uint32_t q = alloc_words(9);
        if (q) {
            int ya = map_y(s, y), yb = map_y(s, y2), xa = -s->margin, xb = SCREEN_W + s->margin;
            uint32_t top = rgbw(p->fgradient);
            psx_mod_write_word(q + 4, 0x38000000u | top); psx_mod_write_word(q + 8, xy(xa, ya));
            psx_mod_write_word(q + 12, top); psx_mod_write_word(q + 16, xy(xb, ya));
            psx_mod_write_word(q + 20, 0); psx_mod_write_word(q + 24, xy(xa, yb));
            psx_mod_write_word(q + 28, 0); psx_mod_write_word(q + 32, xy(xb, yb));
            add_prim(ot, q, 8);
        }
        band(ot, s, y2, H * 75 / 100, bottom_rgb);
        below_band(s, H * 75 / 100, bottom_rgb);
        return;
    }
    if (p->fclamp && y > 0) y = 0;
    if (p->fhas_min && y < p->fmin_y) y = p->fmin_y;
    if (y > 0 && top_on) band(ot, s, 0, y, top_rgb);
    int left = (int)(((int64_t)(s->margin + s->ofx) * 600) / s->h) - 256;
    int extra = left > 0 ? (left + 63) / 64 : 0;
    int count = 9 + 2 * extra;
    for (int r = 0; r < p->frows; r++) {
        int x = tdiv(scroll, 64) * 64 - scroll - 64 * extra;
        for (int c = -extra; c < count - extra; c++) {
            if (!(y < -0x40 || y > H)) {
                int kind = p->fkinds[r * p->fring + pmod(kind0 + c, p->fring)];
                int k = pmod(col0 + c, p->fcols);
                int xa = map_x(s, x), xb = map_x(s, x + 0x40), ya = map_y(s, y), yb = map_y(s, y + step);
                if (kind == 0x31) {
                    ttt_far_texture(ot, r, desc[r * p->fcols + k], cluts[r * p->fcols + k], xa, ya, xb, yb);
                } else if (kind == 0x74) {
                    tile_rect(ot, xa, ya, xb - xa, yb - ya, cell_rgb);
                } else if (kind == 0x64) {
                    tile_rect(ot, xa, ya, xb - xa, yb - ya, bottom_rgb);
                } else {
                    /* B77: a cell TTT leaves empty, which its cameras always
                     * see covered by the stage (stage 5 has many); the PS1's
                     * see through it. The cell colour, under everything
                     * (TTT_OT_FILL): only what nothing else covers.
                     * A cinematic's cameras (the PS2's) look anywhere: there,
                     * B87's rule, the nearest textured cell above in the
                     * column (its sky) drawn again in its place (Wang's
                     * ending, stage 1: row 1's empty cells behind the gate
                     * showed black over the roofs). */
                    int up = s_force >= 0 ? r - 1 : -1, ci = pmod(kind0 + c, p->fring);
                    while (up >= 0 && p->fkinds[up * p->fring + ci] != 0x31) up--;
                    if (up >= 0)
                        ttt_far_texture(ttt_slot(TTT_OT_FILL), up, desc[up * p->fcols + k], cluts[up * p->fcols + k], xa, ya, xb, yb);
                    else
                        tile_rect(ttt_slot(TTT_OT_FILL), xa, ya, xb - xa, yb - ya, cell_rgb);
                }
            }
            x += 0x40;
        }
        y += step;
    }
    if (y < H && bottom_on) band(ot, s, y < 0 ? 0 : y, H * 75 / 100, bottom_rgb);
    if (bottom_on) below_band(s, H * 75 / 100, bottom_rgb);
}

/* ------------------------------------------------------------------ */
/* tiles (0x801D911C, 0x801DB560)                                     */
/* ------------------------------------------------------------------ */
static const unsigned PRIM_WORDS[7] = {7, 9, 5, 9, 12, 6, 8};   /* FT3 FT4 F4 GT3 GT4 G3 G4 */
static const unsigned PRIM_VERTS[7] = {3, 4, 4, 3, 4, 3, 4};

static uint32_t tex_window(const uint8_t w[4]) {
    unsigned x = w[0], y = w[1], ww = w[2], hh = w[3];
    if (!(ww || hh || x || y)) return 0xE2000000u;
    return 0xE2000000u | ((~(ww - 1u) & 0xFFu) >> 3) | ((~(hh - 1u) & 0xFFu) >> 3) << 5
         | (x >> 3) << 10 | (y >> 3) << 15;
}

static int emit_prim(uint32_t ot, const Prim *pr, const int *sx, const int *sy, const int32_t *px,
                     const int32_t *py, const int *sz) {
    unsigned kind = pr->kind, n = PRIM_VERTS[kind], words = PRIM_WORDS[kind];
    int win = (pr->header & 0x80000000u) != 0;
    uint32_t q = alloc_words(1 + words + 2 * win);
    if (!q) return 0;
    uint32_t o = q + 4;
    if (win) { psx_mod_write_word(o, tex_window(pr->win)); o += 4; }
    int gouraud = kind >= 3, textured = kind != 2 && kind != 5 && kind != 6;
    for (unsigned k = 0; k < n; k++) {
        unsigned i = pr->idx[k];
        if (k == 0 || gouraud) {
            uint32_t c = rgbw(pr->rgb[gouraud ? k : 0]);
            psx_mod_write_word(o, k == 0 ? (uint32_t)pr->code << 24 | c : c); o += 4;
        }
        put_xy(o, sx[i], sy[i], px[i], py[i], sz[i]); o += 4;
        if (textured) {
            uint32_t w = (uint32_t)pr->uv[k][1] << 8 | pr->uv[k][0];
            if (k == 0) w |= (uint32_t)pr->clut << 16;
            if (k == 1) w |= (uint32_t)pr->tpage << 16;
            psx_mod_write_word(o, w); o += 4;
        }
    }
    tj_prim_end();
    if (win) psx_mod_write_word(o, 0xE2000000u);
    add_prim(ot, q, words + 2 * win);
    return 1;
}

/* B77: a TTT tile primitive again, every vertex a pixel further from its
 * centre, over the far background and the ground but under the whole stage
 * (TTT_OT_WIDE). The tiles of TTT's stages do not quite meet (T-junctions,
 * edges a pixel apart): under the PS1's cameras the slits showed the older
 * frames, or the far background where it lies behind (a dark line at a wall's
 * foot). Seen only there and on the stage's outline against the far
 * background, a pixel wider, with the texture next to it. Not for
 * semi-transparent primitives (code bit 1), blended over their own copy.
 * B87: T3's tiles too (wide_slot). Out of PGXP: whole pixels, and kept from
 * the T-junction pass, whose points are the stage's own.
 * B98: a vertex rtps saturated (-1024 or 1023, the GTE's screen limits) stays
 * there. A pixel further it left the GPU's 11 bits and wrapped to the other
 * side of the screen: under the TTT Embu's opening camera, looking up, the
 * copies of tiles all below the screen (y saturated at 1023) went up from
 * -1024 and crossed the sky in vertical bands (a cinematic lets the GPU draw
 * polygons past 1023 x 511, tekken3_cine.c). */
static int wide_coord(int v, int d) {
    v += d;
    return v < -0x400 ? -0x400 : v > 0x3FF ? 0x3FF : v;
}

static void wide_prim(const Prim *pr, const int *sx, const int *sy) {
    unsigned n = PRIM_VERTS[pr->kind];
    int wx[4], wy[4], wz[4] = {0, 0, 0, 0}, cx = 0, cy = 0;
    int32_t wp[4] = {NO_PRECISE, NO_PRECISE, NO_PRECISE, NO_PRECISE};
    Prim w = *pr;
    for (unsigned k = 0; k < n; k++) { cx += sx[pr->idx[k]]; cy += sy[pr->idx[k]]; }
    for (unsigned k = 0; k < n; k++) {
        int x = sx[pr->idx[k]], y = sy[pr->idx[k]];
        wx[k] = wide_coord(x, (x * (int)n > cx) - (x * (int)n < cx));
        wy[k] = wide_coord(y, (y * (int)n > cy) - (y * (int)n < cy));
        w.idx[k] = (uint8_t)k;
    }
    int precise = s_precise, tj = s_tj;
    s_precise = s_tj = 0;
    emit_prim(wide_slot(), &w, wx, wy, wp, wp, wz);
    s_precise = precise; s_tj = tj;
}

/* 0x801DA734 (scene.tile_visibility): the tiles the arcade draws, from a
 * 2D cone on the 16 x 16 grid. dir(a) is the (sine, cosine) of the ray at
 * angle a; x, z the camera in the grid's frame; size the world units of a
 * tile. Every tile as near to the camera's as the nearest centre tile is
 * dropped: nothing between the camera and the fighters. */
static void tile_visibility(int fov, int yaw, int x, int z, int size, int8_t vis[256], int fine) {
    memset(vis, 0, 256);
    if (size <= 0) return;
    int step = tdiv((int64_t)size * 14, 20);
    if (x < -7 * size) x = -8 * size;
    if (!(x < 7 * size)) x = 8 * size - 1;
    if (z < -7 * size) z = -8 * size;
    if (!(z < 7 * size)) z = 8 * size - 1;
    int end[2][2] = {{0, 0}, {0, 0}};
    for (int k = 0; k < 2; k++) {
        int a = (-yaw + (k ? 1 : -1) * tdiv(fov, 2)) & 0xFFF;
        /* 4.12 for T3 arcade's 1.15 (<< 3); TTT (0x80154BC4) steps with its
         * 1.12 sine and the same >> 15: rays 8 times finer */
        int sh = fine ? 0 : 3;
        int dx = (step * (s_sin[a] << sh)) >> 15, dz = (step * (s_cos[a] << sh)) >> 15;
        int px = x + 8 * size, pz = z + 8 * size;
        for (;;) {
            int c = tdiv(px, size), r = tdiv(pz, size);
            if (c < 0 || c > 15 || r < 0 || r > 15) break;
            vis[16 * r + c] = 1;
            end[k][0] = c; end[k][1] = r;
            px += dx; pz += dz;
        }
    }
    int c1 = end[0][0], r1 = end[0][1], c2 = end[1][0], r2 = end[1][1];
    for (int n = 0; n < 64; n++) {          /* the border walk, 64 steps go round */
        if (r1 == 15 && c1 < 15) { vis[0xF0 + ++c1] = 1; if (c1 == c2 && r1 == r2) break; }
        if (c1 == 15 && r1 > 0) { vis[16 * --r1 + 15] = 1; if (c1 == c2 && r1 == r2) break; }
        if (r1 == 0 && c1 > 0) { vis[--c1] = 1; if (c1 == c2 && r1 == r2) break; }
        if (c1 == 0 && r1 < 15) { vis[16 * ++r1] = 1; if (c1 == c2 && r1 == r2) break; }
    }
    for (int r = 0; r < 16; r++) {
        int first = -1, last = -1;
        for (int c = 0; c < 16; c++) if (vis[16 * r + c]) { if (first < 0) first = c; last = c; }
        for (int c = first; c >= 0 && c < last; c++) vis[16 * r + c] = 1;
    }
    int cc = tdiv(x + 8 * size, size), cr = tdiv(z + 8 * size, size);
    vis[16 * cr + cc] = -2;
    int near = 0x7FFF;
    static const int centre[4][2] = {{7, 7}, {7, 8}, {8, 7}, {8, 8}};
    for (int k = 0; k < 4; k++) {
        int c = centre[k][0], r = centre[k][1];
        if (vis[16 * r + c] && abs(c - cc) + abs(r - cr) < near) near = abs(c - cc) + abs(r - cr);
    }
    for (int r = 0; r < 16; r++)
        for (int c = 0; c < 16; c++)
            if (vis[16 * r + c] && abs(c - cc) + abs(r - cr) <= near) vis[16 * r + c] = 0;
}

/* The cone's inputs on the PS1, as 0x801D911C builds them: the camera
 * minus the fighters' midpoint (the world origin when the stage is fixed),
 * turned by the axis; its width from the PS1 screen (GTE H, OFX and the
 * 16:9 margin) instead of the arcade's per-stage table (0x80186858), with
 * the arcade's slack (its cone is 1.17 to 1.29 times its screen). */
static void visible_tiles(const Screen *s, int8_t vis[256]) {
    int ttt = s_pack.source == TEKKEN3_STAGE_TTT;
    int axis = (int)psx_mod_read_word(AXIS) + s_pack.axis0;
    int camx = (int)psx_mod_read_word(CAMERA + 0x14), camz = (int)psx_mod_read_word(CAMERA + 0x1C);
    int vx, vz;
    if (psx_mod_read_byte(FIXED_STAGE)) {
        vx = (int16_t)camx; vz = (int16_t)camz;
    } else {
        int p1x = (int)psx_mod_read_word(P1_X), p1z = (int)psx_mod_read_word(P1_Z);
        int p2x = (int)psx_mod_read_word(P2_X), p2z = (int)psx_mod_read_word(P2_Z);
        vx = (int16_t)(camx - (p1x + (int16_t)tdiv((int64_t)p2x - p1x, 2)));
        vz = (int16_t)(camz - (p1z + (int16_t)tdiv((int64_t)p2z - p1z, 2)));
    }
    int32_t m[3][3], v[3];
    rot_ps1(0, axis, 0, m);
    apply_matrix(m, vx, 0, vz, v);
    int half_w = s->ofx > SCREEN_W - s->ofx ? s->ofx : SCREEN_W - s->ofx;
    half_w += s->margin;
    int a = 0;      /* half the screen's angle: the first a with tan a >= half_w / H */
    while (a < 0x3FF && (int64_t)s_sin[a] * s->h < (int64_t)half_w * s_cos[a]) a++;
    /* TTT's cone is T3's without its x 9 / 10 (0x80154BC4): 10 / 9 of T3's slack */
    int fov = ttt ? 2 * a * 13 / 9 : 2 * a * 13 / 10;
    tile_visibility(fov, (int)psx_mod_read_word(CAMERA + 4) - axis, v[0], v[2], 10 * (int)s_pack.tile_size, vis, ttt);
    if (s_probe) {          /* stage_check.py probe: against scene.tile_visibility */
        fprintf(s_probe, "cone %u fov %d yaw %d x %d z %d size %d tiles ", psx_mod_read_word(0x800A08F0u), fov,
                (int)psx_mod_read_word(CAMERA + 4) - axis, v[0], v[2], 10 * (int)s_pack.tile_size);
        for (int r = 0; r < 16; r++) {
            unsigned bits = 0;
            for (int c = 0; c < 16; c++) bits |= (vis[16 * r + c] > 0) << c;
            fprintf(s_probe, "%04X", bits);
        }
        fprintf(s_probe, ttt ? " ttt\n" : "\n");
    }
}

enum { PRIM_MASKED = 0x80, PRIM_MASKED_TO = 0x40, PRIM_FRAMED = 0x20, PRIM_NO_NCLIP = 0x10, PRIM_KEEPS_COLOUR = 0x08 };

static int in_frame(const Screen *s, int x, int y) {
    return y >= -24 && x >= -s->margin - 32 && x <= SCREEN_W + s->margin + 32;
}

static void tiles(const Gte *g, const Screen *s, uint32_t ot_a, uint32_t ot_b) {
    static int sx[256], sy[256], sz[256];
    static int32_t px[256], py[256];
    int8_t vis[256];
    int ttt = s_pack.source == TEKKEN3_STAGE_TTT, night = ttt_night();
    visible_tiles(s, vis);
    /* stage_check.py probe: every 15th frame, the inputs of ttt.geometry_commands
     * and every primitive TTT's rules keep (before the guard behind the camera) */
    int tlog = ttt && s_probe && psx_mod_read_word(0x800A08F0u) % 15 == 0;
    if (tlog) {
        fprintf(s_probe, "ttttiles %u", psx_mod_read_word(0x800A08F0u));
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) fprintf(s_probe, " %d", g->r[i][j]);
        fprintf(s_probe, " %d %d %d %d %d %u %d ", g->t[0], g->t[1], g->t[2], g->ofx, g->ofy, g->h, s->margin);
        for (int r = 0; r < 16; r++) {
            unsigned bits = 0;
            for (int c = 0; c < 16; c++) bits |= (vis[16 * r + c] > 0) << c;
            fprintf(s_probe, "%04X", bits);
        }
        fprintf(s_probe, "\n");
    }
    for (unsigned t = 0; t < s_pack.ntiles; t++) {
        const Tile *tl = &s_pack.tiles[t];
        unsigned nv = tl->head->nv;
        s_stat_cone += vis[t] > 0;
        /* format 4: TileHead pad = skipped with True Ogre (pack.py) */
        if (!tl->head->np || (night ? tl->head->pad : tl->head->skipped) || nv > 0x100 || vis[t] <= 0) continue;
        for (unsigned i = 0; i < nv; i++) rtps(g, tl->v[i].x, tl->v[i].y, tl->v[i].z, &sx[i], &sy[i], &sz[i], &px[i], &py[i]);
        uint32_t ot = (tl->head->layer_b ? ot_b : ot_a) + 4u * tl->head->slot;
        for (unsigned k = 0; k < tl->head->np; k++) {
            const Prim *pr = &tl->p[k];
            /* format 4: PRIM byte 6 = third culling vertex | flags (pack.py) */
            unsigned flags = ttt ? pr->cull & 0xF8u : 0;
            if (pr->kind > 6 || (flags & PRIM_MASKED) || (night && (flags & PRIM_MASKED_TO))) continue;
            unsigned a = pr->idx[0], b = pr->idx[1], c = pr->idx[pr->cull & 7];
            if (a >= nv || b >= nv || c >= nv) continue;
            /* TTT (0x801542A4): a frame test before NCLIP (one of the three
             * vertices in -32 <= x <= 544, y >= -12 of TTT's 512 x 240),
             * here the PS1 screen with the 16:9 margins and the same slack */
            if ((flags & PRIM_FRAMED) && !in_frame(s, sx[a], sy[a]) && !in_frame(s, sx[b], sy[b]) && !in_frame(s, sx[c], sy[c]))
                continue;
            if (!(flags & PRIM_NO_NCLIP) && nclip(sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]) <= 0) continue;
            /* not in the arcade: a vertex behind the camera gives a stray
             * polygon (never seen in the arcade's fights: its cone drops the
             * tiles near the camera) */
            int behind = 0;
            for (unsigned q = 0; q < PRIM_VERTS[pr->kind]; q++)
                if (pr->idx[q] < nv && sz[pr->idx[q]] < 16) behind = 1;
            if (tlog) {
                fprintf(s_probe, "tp %u %u %d %u", tl->head->layer_b, tl->head->slot, behind, pr->code);
                for (unsigned q = 0; q < PRIM_VERTS[pr->kind]; q++) fprintf(s_probe, " %d %d", sx[pr->idx[q]], sy[pr->idx[q]]);
                fprintf(s_probe, "\n");
            }
            if (behind) { s_stat_behind++; continue; }
            Prim dark;
            if (night && !(flags & PRIM_KEEPS_COLOUR)) {
                dark = *pr;
                memset(dark.rgb, s_pack.togr[0], sizeof dark.rgb);
                pr = &dark;
            }
            s_stat_tiles += emit_prim(ot, pr, sx, sy, px, py, sz);
            if (!(pr->code & 2)) wide_prim(pr, sx, sy);
        }
    }
}

/* ------------------------------------------------------------------ */
/* the objects' animation (0x801E3D0C, tools/arcade_stages/anim.py):    */
/* stage 3's turning model (0x801E5AD0), stage 11's helicopter          */
/* (0x801E3F68 / 0x801E40C0 and its three flights). The arcade's memory  */
/* as s16 halves, by address, so the port reads as the reference.       */
/* ------------------------------------------------------------------ */
static int16_t s_st[0x40], s_ang[16], s_pos[16];
#define ST(a)  s_st[((a) - 0x8021F9F8u) >> 1]      /* 0x8021F9F8..0x8021FA78 */
#define ANG(a) s_ang[((a) - 0x802FECE4u) >> 1]     /* 4 SVECTORs: angles */
#define POS(a) s_pos[((a) - 0x8031E134u) >> 1]     /* 4 SVECTORs: positions */
#define U16(v) ((int)(uint16_t)(v))
static unsigned s_anim_count;           /* animated texture: 0x8021F9CC */
static unsigned s_anim_frame;           /* 0x8021F9D0 */
static int s_was_over;                  /* the round was decided last frame */
static unsigned s_stat_objects, s_stat_obj_behind;

/* 0x801E59FC */
static void stage3_init(void) {
    for (int i = 0; i < 3; i++) {
        POS(0x8031E134u + 8 * i) = 0; POS(0x8031E136u + 8 * i) = -300; POS(0x8031E138u + 8 * i) = 0xC1C;
    }
    ANG(0x802FECE6u) = 0x955; ANG(0x802FECE4u) = 0; ANG(0x802FECE8u) = 0;
    ANG(0x802FECECu) = 0; ANG(0x802FECEEu) = 0; ANG(0x802FECF0u) = 0;
    ANG(0x802FECF4u) = 0; ANG(0x802FECF6u) = 0x800; ANG(0x802FECF8u) = 0;
    ST(0x8021FA74u) = 0;
    POS(0x8031E14Cu) = 0; POS(0x8031E14Eu) = 0; POS(0x8031E150u) = 0;
    ANG(0x802FECFCu) = 0; ANG(0x802FECFEu) = 0x800; ANG(0x802FED00u) = 0;
}

/* 0x801E5AD0: model 0 turns by -5 a frame, back to 0x955 every 0x88 */
static void stage3_step(void) {
    ANG(0x802FECE6u) -= 5;
    ST(0x8021FA74u) += 1;
    if (ST(0x8021FA74u) == 0x88) { ANG(0x802FECE6u) = 0x955; ST(0x8021FA74u) = 0; }
}

/* 0x801E3DE0; mode: the buttons held (0x8021FBF4) or the vsync count & 3 in
 * the arcade */
static void stage11_init(int mode) {
    ANG(0x802FECE4u) = -0x9F; ANG(0x802FECE6u) = 0x71C;
    POS(0x8031E136u) = -0x190; POS(0x8031E13Eu) = -0x12C; POS(0x8031E146u) = 0x118; POS(0x8031E148u) = -0x4CE;
    ST(0x8021FA04u) = 0x80; ST(0x8021FA14u) = -2;
    ANG(0x802FECE8u) = 0; ANG(0x802FECECu) = 0; ANG(0x802FECEEu) = 0; ANG(0x802FECF0u) = 0;
    ANG(0x802FECF4u) = 0; ANG(0x802FECF6u) = 0; ANG(0x802FECF8u) = 0;
    POS(0x8031E134u) = 0; POS(0x8031E138u) = 0x1068; POS(0x8031E13Cu) = 0; POS(0x8031E140u) = 0; POS(0x8031E144u) = 0;
    ST(0x8021FA1Cu) = 0; ST(0x8021FA4Cu) = 0; ST(0x8021FA00u) = -1; ST(0x8021FA6Cu) = 0x20; ST(0x8021FA08u) = -1;
    ST(0x8021FA0Cu) = 0x20; ST(0x8021FA10u) = -1; ST(0x8021FA18u) = 0; ST(0x8021FA20u) = 0; ST(0x8021FA24u) = 0;
    ST(0x8021FA28u) = 0; ST(0x8021FA54u) = 0; ST(0x8021FA34u) = 0; ST(0x8021FA48u) = 0; ST(0x8021FA5Cu) = -0x46;
    ST(0x8021FA60u) = 0x46; ST(0x8021FA50u) = 0; ST(0x8021FA64u) = 1; ST(0x8021FA30u) = 1; ST(0x8021FA70u) = 0x1068;
    ST(0x8021F9FEu) = 1;
    ST(0x8021FA44u) = (int16_t)(mode & 3);
}

/* x, z on the circle: sine[-angle], sine[-angle + 0x400] x radius */
static void circle(int angle, int radius) {
    const int16_t *sine = s_pack.sin;
    int a = -angle;
    int v = sine[a & 0xFFF] * radius;
    POS(0x8031E134u) = (int16_t)((v < 0 ? v + 0xFFF : v) >> 12);
    v = sine[(a + 0x400) & 0xFFF] * radius;
    POS(0x8031E138u) = (int16_t)((v < 0 ? v + 0xFFF : v) >> 12);
}

static void f3f68(int yaw) {
    ANG(0x802FECE6u) = (int16_t)(U16(ANG(0x802FECE6u)) & 0xFFF);
    ST(0x8021FA20u) = (int16_t)(U16(ST(0x8021FA20u)) & 0xFFF);
    int mode = ST(0x8021FA44u);
    if (mode >= 1 && mode <= 3) {
        ST(0x8021FA50u) += 1;
        ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) | 0x1000);
        return;
    }
    if (mode != 0) return;
    yaw = (int16_t)yaw;
    ST(0x8021FA58u) = (int16_t)yaw;
    if (ST(0x8021FA1Cu) & 2) return;
    int last = ST(0x8021FA54u), d, bits;
    if (last < yaw) { d = yaw - last; bits = 7; } else { d = last - yaw; bits = 0x23; }
    if (d > 0x17C) {
        uint32_t table = d > 0x352 ? 0x802045F4u : 0x802045ECu;   /* read by 0x801E42DC only: never in mode 0 */
        ST(0x8021F9F8u) = (int16_t)(table & 0xFFFF); ST(0x8021F9FAu) = (int16_t)(table >> 16);
        ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) | bits);
        ST(0x8021FA54u) = (int16_t)yaw;
        ST(0x8021FA20u) = ANG(0x802FECE6u);
        ST(0x8021FA18u) = 0;
        return;
    }
    ST(0x8021FA50u) += 1;
}

/* mode 1 (0x801E4A0C) */
static void f4a0c(void) {
    int t = ST(0x8021FA50u), st = ST(0x8021FA4Cu);
    switch (st) {
    case 0:
        if (t < 200) { ANG(0x802FECE6u) += 4; return; }
        break;
    case 1:
        if (t < 0x118) { ANG(0x802FECE6u) += 4; return; }
        break;
    case 2: {
        ST(0x8021FA38u) = (int16_t)((ST(0x8021FA34u) >> 3) | 1);
        if (t == 500) ST(0x8021F9FCu) = 0;
        if (ST(0x8021F9FCu) == 0) {
            if (t < 0x212) ANG(0x802FECE8u) += (int16_t)(ST(0x8021FA30u) * 6);
            if (t < 0x230) ANG(0x802FECE4u) += 4;
            ST(0x8021FA34u) += ST(0x8021F9FEu) == 0 ? 1 : -1;
            if (ST(0x8021FA34u) == 0) { ST(0x8021FA4Cu) = 5; ST(0x8021FA50u) = 0; }
        } else {
            if (t < 0x1F) ANG(0x802FECE8u) -= (int16_t)(ST(0x8021FA30u) * 6);
            if (t < 0x3D) ANG(0x802FECE4u) -= 1;
            if (abs(ST(0x8021FA38u)) < 8) ST(0x8021FA34u) += ST(0x8021F9FEu) != 0 ? 1 : -1;
            else ST(0x8021FA38u) = ST(0x8021F9FEu) != 0 ? 8 : -8;
        }
        int step = ST(0x8021FA38u), angle = (int16_t)(ST(0x8021FA24u) + step);
        ST(0x8021FA24u) = (int16_t)angle;
        circle(angle, 0x1068);
        ANG(0x802FECE6u) -= (int16_t)step;
        return;
    }
    case 4:
        if (t < 0x118) { ANG(0x802FECE6u) -= 4; return; }
        break;
    case 5:
        if (t < 0x1E) return;
        if (t < 0xD2) ANG(0x802FECE4u) -= 1;
        if (t > 0x137) {
            if (ST(0x8021FA34u) == 0) ST(0x8021F9FEu) = (int16_t)(1 - ST(0x8021F9FEu));
            ST(0x8021F9FCu) = 1;
            ST(0x8021FA30u) = (int16_t)-ST(0x8021FA30u);
            ST(0x8021FA4Cu) = 2;
            ST(0x8021FA50u) = 0;
            return;
        }
        ANG(0x802FECE6u) += ST(0x8021F9FEu) != 0 ? -4 : 4;
        return;
    default:
        return;
    }
    ST(0x8021FA4Cu) = 2; ST(0x8021FA50u) = 0; ST(0x8021F9FCu) = 1;
}

/* mode 2 (0x801E4E04): radius in 0x8021FA70 */
static void radius_circle(int a) {
    const int16_t *sine = s_pack.sin;
    int r = ST(0x8021FA70u);
    int v = r * sine[a & 0xFFF];
    POS(0x8031E134u) = (int16_t)((v < 0 ? v + 0xFFF : v) >> 12);
    v = r * sine[(a + 0x400) & 0xFFF];
    POS(0x8031E138u) = (int16_t)((v < 0 ? v + 0xFFF : v) >> 12);
}

static void f4e04(void) {
    int st = ST(0x8021FA4Cu), t = ST(0x8021FA50u), next;
    switch (st) {
    case 0:
        if (t < 0x1E) ANG(0x802FECE8u) -= 8;
        if ((uint32_t)(U16(ST(0x8021FA50u)) - 0x82) < 0x1Eu) ANG(0x802FECE8u) += 8;
        if (t < 0xA0) ANG(0x802FECE6u) -= 0xB;
        if (t == 0x8C) ST(0x8021F9FCu) = 1;
        if (t < 0x8D) return;
        ST(0x8021FA38u) = ST(0x8021FA34u) > 1 ? 0x19 : 5;
        if (t == 0x15E) ST(0x8021F9FCu) = 0;
        if (ST(0x8021F9FCu) == 0) {
            ST(0x8021FA34u) -= 1;
            if (ST(0x8021FA34u) == 0) { ST(0x8021FA4Cu) = 2; ST(0x8021FA50u) = 0; }
        } else {
            if (ST(0x8021FA38u) > 200) ST(0x8021FA38u) = 200;
            ST(0x8021FA34u) += 1;
        }
        ST(0x8021FA70u) += ST(0x8021FA38u);
        radius_circle(-U16(ST(0x8021FA24u)));
        break;
    case 2:
        if (t < 0x50) { ANG(0x802FECE6u) -= 0xB; ANG(0x802FECE8u) -= 3; }
        else {
            ST(0x8021F9FCu) = 1; ST(0x8021FA4Cu) = 3; ST(0x8021FA50u) = 0; ST(0x8021FA24u) = 0; ST(0x8021FA34u) = 0;
            ANG(0x802FECE6u) -= 0xB; ANG(0x802FECE8u) -= 5;
        }
        break;
    case 3: {
        if (t < 0x14) { ANG(0x802FECE6u) -= 0x16; ANG(0x802FECE8u) -= 5; }
        else ANG(0x802FECE6u) -= ST(0x8021FA38u);
        ST(0x8021FA38u) = (int16_t)((ST(0x8021FA34u) >> 3) | 1);
        if (ST(0x8021FA50u) == 0x578) ST(0x8021F9FCu) = 0;
        if (ST(0x8021F9FCu) == 0) {
            next = ST(0x8021FA34u) - 1;
            if (ST(0x8021FA34u) == 1) { ST(0x8021FA4Cu) = 4; ST(0x8021FA50u) = 0; }
        } else {
            next = ST(0x8021FA34u) + 1;
            if (ST(0x8021FA38u) > 8) { ST(0x8021FA38u) = 8; next = ST(0x8021FA34u); }
        }
        ST(0x8021FA34u) = (int16_t)next;
        int old = U16(ST(0x8021FA24u));
        ST(0x8021FA70u) -= 10;
        ST(0x8021FA24u) = (int16_t)(old + ST(0x8021FA38u));
        int a = -(old + U16(ST(0x8021FA38u)));
        if (ST(0x8021FA70u) < 0x1068) ST(0x8021FA70u) = 0x1068;
        radius_circle(a);
        break;
    }
    case 4:
        if (t < 100) ANG(0x802FECE8u) += 3;
        if (t > 0xA0) { ST(0x8021FA50u) = 0; ST(0x8021FA4Cu) = 5; }
        break;
    case 5:
        if (t < 0x15E) ANG(0x802FECE6u) -= 5;
        else if (t < 0x1D6) ANG(0x802FECE8u) += 2;
        if (t < 0x3C) ANG(0x802FECE4u) += 1;
        if (t < 0x78) ANG(0x802FECE8u) -= 2;
        if (t > 0x208) { ST(0x8021FA4Cu) = 6; ST(0x8021FA50u) = 0; ST(0x8021F9FCu) = 1; }
        break;
    case 6: {
        if (t < 0x1E) ANG(0x802FECE4u) -= 1;
        if (t < 0x50) ANG(0x802FECE8u) += 4;
        ST(0x8021FA38u) = (int16_t)((ST(0x8021FA34u) >> 3) | 1);
        if (ST(0x8021F9FCu) == 0) {
            next = ST(0x8021FA34u) - 1;
            if (ST(0x8021FA34u) == 1) { ST(0x8021FA4Cu) = 7; ST(0x8021FA50u) = 0; }
        } else {
            next = ST(0x8021FA34u) + 1;
            if (ST(0x8021FA38u) > 8) { ST(0x8021FA38u) = 8; next = ST(0x8021FA34u); }
        }
        ST(0x8021FA34u) = (int16_t)next;
        int angle = (int16_t)(ST(0x8021FA24u) - ST(0x8021FA38u));
        ST(0x8021FA24u) = (int16_t)angle;
        circle(angle, 0x1068);
        ANG(0x802FECE6u) += ST(0x8021FA38u);
        break;
    }
    default:
        break;
    }
}

/* mode 3 (0x801E54B4) */
static void f54b4(void) {
    int st = ST(0x8021FA4Cu), t = ST(0x8021FA50u), next;
    switch (st) {
    case 0:
        if (t < 0x1E) ANG(0x802FECE4u) -= 1;
        if (t < 0x10E) POS(0x8031E136u) += 10;
        else {
            ST(0x8021FA4Cu) = 1; ST(0x8021FA50u) = 0;
            ST(0x8021FA68u) = ST(0x8021FA64u) ? ST(0x8021FA5Cu) : ST(0x8021FA60u);
        }
        break;
    case 1:
        if (t < 0x79) {
            if (ST(0x8021FA64u)) POS(0x8031E138u) += ST(0x8021FA68u);
            else POS(0x8031E134u) += ST(0x8021FA68u);
        } else {
            ST(0x8021FA50u) = 0;
            if (ST(0x8021FA64u)) ST(0x8021FA5Cu) = (int16_t)-ST(0x8021FA5Cu);
            else ST(0x8021FA60u) = (int16_t)-ST(0x8021FA60u);
            ST(0x8021FA4Cu) = 2;
            ST(0x8021FA64u) = (int16_t)(1 - ST(0x8021FA64u));
        }
        break;
    case 2:
        if (t < 0x41) ANG(0x802FECE6u) += 0x20;
        else { ST(0x8021FA4Cu) = 3; ST(0x8021FA50u) = 0; ST(0x8021FA24u) += 0x800; }
        break;
    case 3:
        if ((uint32_t)(U16(ST(0x8021FA50u)) - 0xF1) < 0x1Du) ANG(0x802FECE4u) += 1;
        if (t < 0x10E) POS(0x8031E136u) -= 10;
        else { ST(0x8021FA4Cu) = 4; ST(0x8021FA50u) = 0; ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) & 0xFFFD); }
        break;
    case 4:
        if (t < 0x79) return;
        ST(0x8021FA4Cu) = 5; ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) | 2); ST(0x8021FA50u) = 0;
        break;
    case 5:
        if (t < 0x32) { ANG(0x802FECE4u) += 3; ANG(0x802FECE6u) -= 1; POS(0x8031E136u) -= 1; return; }
        if (t < 0x118) { ANG(0x802FECE6u) -= 5; POS(0x8031E136u) -= 6; return; }
        ST(0x8021FA4Cu) = 6; ST(0x8021F9FCu) = 1;
        ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) & 0xFFFD); ST(0x8021FA50u) = 0;
        break;
    case 6: {
        int d = (ST(0x8021FA34u) >> 4) * 2 + 1;
        ST(0x8021FA38u) = (int16_t)d;
        if (t == 0x66) ST(0x8021F9FCu) = 0;
        if (ST(0x8021F9FCu) == 0) {
            next = ST(0x8021FA34u) - 1;
            if (ST(0x8021FA34u) == 1) {
                ST(0x8021FA4Cu) = 7; ST(0x8021FA50u) = 0;
                ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) & 0xFFFD); ST(0x8021FA38u) = 5;
            }
        } else {
            next = ST(0x8021FA34u) + 1;
            if (d > 10) { ST(0x8021FA38u) = 10; next = ST(0x8021FA34u); }
        }
        ST(0x8021FA34u) = (int16_t)next;
        int angle = (int16_t)(ST(0x8021FA24u) - ST(0x8021FA38u));
        ST(0x8021FA24u) = (int16_t)angle;
        circle(angle, 0x1068);
        ANG(0x802FECE6u) += ST(0x8021FA38u);
        break;
    }
    case 7:
        if (t < 300) { ANG(0x802FECE6u) += 4; if (t < 0x11E) POS(0x8031E136u) += 5; }
        if ((uint32_t)(U16(ST(0x8021FA50u)) - 0xC9) < 0x95u) ANG(0x802FECE4u) -= 1;
        if (t < 0x15F) return;
        ST(0x8021FA4Cu) = 8; ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) & 0xFFFD); ST(0x8021FA50u) = 0;
        break;
    case 8:
        if (t < 0x79) return;
        ST(0x8021FA4Cu) = 0; ST(0x8021FA1Cu) = (int16_t)(U16(ST(0x8021FA1Cu)) | 2); ST(0x8021FA50u) = 0;
        break;
    default:
        break;
    }
}

static void f40c0(void) {
    ANG(0x802FECEEu) -= 0x29F;
    ANG(0x802FECF4u) += 0x29F;
    int flags = U16(ST(0x8021FA1Cu)), mode = ST(0x8021FA44u);
    if (!(flags & 1) || mode != 2) {
        int v = U16(ST(0x8021FA04u));
        if (v & 2) ANG(0x802FECE6u) += ST(0x8021FA08u);
        ST(0x8021FA04u) = (int16_t)(v + 1);
        if (ST(0x8021FA04u) == 0x100) { ST(0x8021FA04u) = 0; ST(0x8021FA08u) = (int16_t)-ST(0x8021FA08u); }
    }
    /* else 0x801E42DC / 0x801E4674: bit 0 is only set in mode 0, never with mode 2 */
    flags = U16(ST(0x8021FA1Cu));
    if (!(flags & 1) || !(flags & 0x1000)) {
        POS(0x8031E136u) += ST(0x8021FA00u) > 0 ? 1 : -1;
        ST(0x8021FA6Cu) += 1;
        if (ST(0x8021FA6Cu) == 0x40) { ST(0x8021FA6Cu) = 0; ST(0x8021FA00u) = (int16_t)-ST(0x8021FA00u); }
        ANG(0x802FECE8u) += ST(0x8021FA10u);
        ST(0x8021FA0Cu) += 1;
        if (ST(0x8021FA0Cu) == 0x40) { ST(0x8021FA10u) = (int16_t)-ST(0x8021FA10u); ST(0x8021FA0Cu) = 0; }
        if (!(U16(ST(0x8021FA1Cu)) & 0x1000)) return;
    }
    switch (ST(0x8021FA44u)) {
    case 1: f4a0c(); break;
    case 2: f4e04(); break;
    case 3: f54b4(); break;
    default: break;
    }
}

/* 0x801E3D0C for stage 11 (while the objects show) */
static void stage11_step(int yaw) {
    if (ST(0x8021FA48u) > 0x78) f3f68(yaw);
    else ST(0x8021FA48u) += 1;
    f40c0();
}

/* the arcade starts the objects again at each round (0x801E3D94) */
static void anim_round_start(void) {
    memset(s_st, 0, sizeof s_st); memset(s_ang, 0, sizeof s_ang); memset(s_pos, 0, sizeof s_pos);
    if (s_pack.stage == 3) stage3_init();
    else if (s_pack.stage == 11) stage11_init((int)psx_mod_read_word(0x800A08F0u));   /* as the vsync count */
}

static void anim_reset(void) {
    s_anim_count = s_anim_frame = 0;            /* 0x801E2090 */
    s_was_over = 0;
    anim_round_start();
}

/* The round is decided: a fighter's life at 0 (KO, until the next round
 * gives it back) or the timer (frames left, 2400 at the start) at 0; or
 * the match is over (phase u16 0x800AE224 past 8, the fight's; it stays 8
 * through the KO and the round winner's pose). The stage 11 objects show
 * as in the arcade (0x801E2A2C: 0x8021F0C0 >= 6, round decided, or a
 * replay): only after the fight, the user's choice (2026-10-13). */
#define PHASE   0x800AE224u
#define PAUSED  0x80095494u     /* 1 while the pause menu is open (measured; the TTT1 mod's wings read it) */
#define LIFE_P1 0x800A961Eu
#define LIFE_P2 0x800AAEAAu
#define TIMER   0x800ADBCCu

int tekken3_arcade_stages_t3_stage(void) {
    return !s_shadow && active() && s_pack.source == TEKKEN3_STAGE_T3 ? s_pack.stage : -1;
}

static int round_over(void) {
    int phase = psx_mod_read_half(PHASE);
    if (phase != 8) return phase > 8;           /* before 8: the round is set up, lives not given yet */
    return (int16_t)psx_mod_read_half(LIFE_P1) <= 0 || (int16_t)psx_mod_read_half(LIFE_P2) <= 0
        || psx_mod_read_half(TIMER) == 0;
}

/* Once per frame of the stage (0x801E2114 every 4th call; 0x801E3D0C),
 * not in the pause: the PS1 draws the stage under its pause menu, the
 * arcade's fight loop skips both while paused */
static void anim_tick(void) {
    Pack *p = &s_pack;
    if (psx_mod_read_word(PAUSED)) return;
    if (p->aframes && ++s_anim_count >= p->aperiod) {
        unsigned f = s_anim_frame % p->aframes;
        psx_mod_gpu_high_vram_upload(p->ax, p->ay, p->aw, p->ah, p->apixels + (size_t)f * p->aw * p->ah);
        if (s_probe) fprintf(s_probe, "tex %u %d %u\n", psx_mod_read_word(0x800A08F0u), p->stage, f);
        s_anim_count = 0;
        s_anim_frame = (s_anim_frame + 1) & 0xF;
    }
    if (!p->nlayout) return;
    int over = round_over();
    if (s_was_over && !over) anim_round_start();      /* the next round starts */
    s_was_over = over;
    if (s_probe) {          /* anim.py probe: the C port against the reference */
        fprintf(s_probe, "anim %u %d %d %d %d", psx_mod_read_word(0x800A08F0u), p->stage,
                (int)psx_mod_read_word(CAMERA + 4), over, (int)psx_mod_read_half(PHASE));
        for (int i = 0; i < 0x40; i++) fprintf(s_probe, " %d", s_st[i]);
        for (int i = 0; i < 16; i++) fprintf(s_probe, " %d", s_ang[i]);
        for (int i = 0; i < 16; i++) fprintf(s_probe, " %d", s_pos[i]);
        fprintf(s_probe, "\n");
    }
    if (p->stage == 3) stage3_step();
    else if (p->stage == 11 && over) stage11_step((int)psx_mod_read_word(CAMERA + 4));
}

/* RotMatrix (0x801F0D64) and RotMatrixYXZ (0x801F0034), table 0x8021688C:
 * a negative angle reads entry -a and negates the sine */
static void rot_sc(int a, int *s, int *c) {
    a = (int16_t)a;
    uint32_t w = s_pack.rot[(a < 0 ? -a : a) & 0xFFF];
    int sv = (int16_t)(w & 0xFFFF), cv = (int16_t)(w >> 16);
    *s = a < 0 ? -sv : sv;
    *c = cv;
}

static void rot_matrix(const int16_t *ang, int yxz, int32_t m[3][3]) {
    int sx, cx, sy, cy, sz, cz, t;
    rot_sc(ang[0], &sx, &cx); rot_sc(ang[1], &sy, &cy); rot_sc(ang[2], &sz, &cz);
    if (!yxz) {
        m[0][2] = (int16_t)sy;
        m[1][2] = (int16_t)(-(cy * sx) >> 12);
        m[2][2] = (int16_t)((cy * cx) >> 12);
        m[0][0] = (int16_t)((cz * cy) >> 12);
        m[0][1] = (int16_t)(-(sz * cy) >> 12);
        t = (cz * -sy) >> 12;
        m[1][0] = (int16_t)((int16_t)((sz * cx) >> 12) - (int16_t)((t * sx) >> 12));
        m[2][0] = (int16_t)((int16_t)((sz * sx) >> 12) + (int16_t)((t * cx) >> 12));
        t = (sz * -sy) >> 12;
        m[1][1] = (int16_t)((int16_t)((cz * cx) >> 12) + (int16_t)((t * sx) >> 12));
        m[2][1] = (int16_t)((int16_t)((cz * sx) >> 12) - (int16_t)((t * cx) >> 12));
    } else {
        m[1][2] = (int16_t)-sx;
        m[0][2] = (int16_t)((sy * cx) >> 12);
        m[2][2] = (int16_t)((cy * cx) >> 12);
        m[1][0] = (int16_t)((sz * cx) >> 12);
        m[1][1] = (int16_t)((cz * cx) >> 12);
        t = (sy * sx) >> 12;
        m[0][0] = (int16_t)((int16_t)((cy * cz) >> 12) + (int16_t)((t * sz) >> 12));
        m[0][1] = (int16_t)((int16_t)((t * cz) >> 12) - (int16_t)((cy * sz) >> 12));
        t = (cy * sx) >> 12;
        m[2][1] = (int16_t)((int16_t)((sy * sz) >> 12) + (int16_t)((t * cz) >> 12));
        m[2][0] = (int16_t)((int16_t)((t * sz) >> 12) - (int16_t)((sy * cz) >> 12));
    }
}

/* 0x801E2C64 (stage 11: model 1 hangs from model 0) and 0x801E2E80 (stage
 * 3): each model's GTE from the tiles' (anim.object_matrices) */
static void object_gte(const Gte *tile, unsigned k, Gte *out) {
    const int16_t *ang = &s_ang[4 * k], *pos = &s_pos[4 * k];
    int32_t r[3][3], v[3];
    *out = *tile;
    if (s_pack.stage == 11 && k == 1) {
        Gte parent;
        object_gte(tile, 0, &parent);
        rot_matrix(ang, 1, r);
        memcpy(out->r, r, sizeof r);
        mul_matrix2(parent.r, out->r);
        apply_matrix(parent.r, pos[0], pos[1], pos[2], v);
        for (int i = 0; i < 3; i++) out->t[i] = parent.t[i] + v[i];
        return;
    }
    rot_matrix(ang, s_pack.stage == 11, r);
    memcpy(out->r, r, sizeof r);
    mul_matrix2(tile->r, out->r);
    apply_matrix(tile->r, pos[0], pos[1], pos[2], v);
    for (int i = 0; i < 3; i++) out->t[i] = tile->t[i] + v[i];
}

/* 0x801E2A68 (scene.object_commands): each drawing call's model through
 * its GTE, the primitives facing the camera (vertices 0, 1, 2) sorted by
 * AVSZ (ZSF4 0x100, ZSF3 0x155 of SZ >> 5) into a private OT linked at its
 * main rank: 128 slots, slot 0 overwritten by the link (lost), or (size
 * 1) one slot before the link */
static void objects(const Gte *tile) {
    const Pack *p = &s_pack;
    static int sx[256], sy[256], sz[256];
    static int32_t px[256], py[256];
    uint32_t ots[8] = {0};
    unsigned sizes[8] = {0}, ranks[8] = {0}, nots = 0;
    if (p->stage == 11 && !s_was_over) return;      /* round_over() of this frame's tick */
    for (unsigned c = 0; c < p->nlayout; c++) {
        const Layout *l = &p->layout[c];
        const Model *m = &p->models[l->model];
        unsigned o = 0;
        while (o < nots && ranks[o] != l->rank) o++;
        if (o == nots) {        /* ClearOTagR: each entry leads to the one before */
            unsigned n = l->size > 1 ? l->size : 2;
            if (l->size > 128 || nots == 8 || !(ots[o] = alloc_words(n))) return;
            for (unsigned i = 0; i < n; i++)
                psx_mod_write_word(ots[o] + 4 * i, i ? (ots[o] + 4 * (i - 1)) & 0xFFFFFFu : 0xFFFFFFu);
            sizes[o] = l->size; ranks[o] = l->rank; nots++;
        }
        Gte g;
        object_gte(tile, l->model, &g);
        for (unsigned i = 0; i < m->nv; i++) rtps(&g, m->v[i].x, m->v[i].y, m->v[i].z, &sx[i], &sy[i], &sz[i], &px[i], &py[i]);
        for (unsigned k = 0; k < m->np; k++) {
            const Prim *pr = &m->p[k];
            if (pr->kind > 6) continue;
            unsigned nvp = PRIM_VERTS[pr->kind], a = pr->idx[0], b = pr->idx[1], c2 = pr->idx[2], bad = 0;
            for (unsigned q = 0; q < nvp; q++) bad |= pr->idx[q] >= m->nv;
            if (bad) continue;
            int cross = (int16_t)(sx[b] - sx[a]) * (int16_t)(sy[c2] - sy[b])
                      - (int16_t)(sy[b] - sy[a]) * (int16_t)(sx[c2] - sx[b]);
            if (cross <= 0) continue;
            unsigned slot = 1;
            if (sizes[o] > 1) {
                int z = 0;
                for (unsigned q = 0; q < nvp; q++) z += sz[pr->idx[q]] >> 5;
                slot = (unsigned)((z * (nvp == 4 ? 0x100 : 0x155)) >> 12);
                if (slot > 0xFFFF) slot = 0xFFFF;
                if (slot >= sizes[o] || slot == 0) continue;      /* outside the table, or lost with slot 0 */
            }
            int behind = 0;         /* not in the arcade, as the tiles' guard */
            for (unsigned q = 0; q < nvp; q++) if (sz[pr->idx[q]] < 16) behind = 1;
            if (behind) { s_stat_obj_behind++; continue; }
            s_stat_objects += emit_prim(ots[o] + 4 * slot, pr, sx, sy, px, py, sz);
        }
    }
    for (unsigned o = 0; o < nots; o++) {     /* entry 0 to the main rank, the main rank to the last entry */
        unsigned last = sizes[o] > 1 ? sizes[o] - 1 : 1;
        uint32_t r = main_ot(ranks[o]);
        psx_mod_write_word(ots[o], (psx_mod_read_word(ots[o]) & 0xFF000000u) | (psx_mod_read_word(r) & 0xFFFFFFu));
        psx_mod_write_word(r, (psx_mod_read_word(r) & 0xFF000000u) | ((ots[o] + 4 * last) & 0xFFFFFFu));
    }
}

/* ------------------------------------------------------------------ */
/* floor (0x801A91A8, 0x801A941C, 0x801AA9C0: scene.floor_commands)     */
/* ------------------------------------------------------------------ */
typedef struct {
    Gte world;                  /* 0x800ADF70: rotation, translation */
    int pitch, yaw, cam[3], p1[2], p2[2];
} View;

static int sqrt0(int64_t a, const int16_t *table) {
    if (a <= 0) return 0;
    uint32_t v32 = (uint32_t)a;
    int bits = 0;
    while (bits < 32 && (v32 >> bits)) bits++;
    int lz = (32 - bits) & ~1;
    uint32_t v = lz < 24 ? v32 >> (24 - lz) : v32 << (lz - 24);
    int t = table[v - 0x40];
    return (int)(((uint32_t)t << ((31 - lz) >> 1)) >> 12);
}

static int floor_center_high(const View *w, int *ox, int *oz) {
    const Pack *p = &s_pack;
    int cx = w->cam[0], cy = w->cam[1], cz = w->cam[2];
    int u = (w->pitch + 0xEF) & 0xFFF;
    int i8 = tdiv((int64_t)abs(cy) * p->cos[u], p->sin[u]);
    int i2 = sqrt0((int64_t)i8 * i8 + (int64_t)cy * cy, p->sqrt2);
    int a = (w->yaw + 0x400) & 0xFFF;
    int c = p->cos[a], s = p->sin[a];
    i2 = tdiv((int64_t)i2 << 8, 0x218);
    int x0 = shift12((int64_t)i8 * c) + cx, z0 = shift12((int64_t)i8 * s) + cz;
    int q = (w->yaw + 0x600) & 0xFFF, quarter = q >> 10, odd = q >> 9 & 1;
    int d = shift12((int64_t)(-0x4CE - cy) * 0x8555);
    if (d > 0x30D4) d = 0x30D4;
    if (quarter == 1 || quarter == 3) {
        int t = shift12((int64_t)i2 * c);
        t = odd ? t : -t;
        int z = quarter == 1 ? z0 + t - 0x4E2 + d : z0 + t + 0x4E2 - d;
        if (!s) return 0;
        *ox = tdiv((int64_t)c * (z - cz), s) + cx; *oz = z;
        return 1;
    }
    int t = shift12((int64_t)i2 * s);
    t = odd ? -t : t;
    int x = quarter == 0 ? x0 + t - 0x4E2 + d : x0 + t + 0x4E2 - d;
    if (!c) return 0;
    *ox = x; *oz = tdiv((int64_t)s * (x - cx), c) + cz;
    return 1;
}

static int floor_center(const View *w, int *ox, int *oz) {
    const Pack *p = &s_pack;
    if (p->sin[(w->pitch + 0xEF) & 0xFFF] <= 0) return 0;
    int x = tdiv((int64_t)w->p1[0] + w->p2[0], 2), z = tdiv((int64_t)w->p1[1] + w->p2[1], 2);
    if (p->lkind == 0) {
        if ((w->pitch & 0xFFF) && !(w->pitch & 0x800) && w->cam[1] < -0x6B8)
            return floor_center_high(w, ox, oz);
        if (s12(w->pitch) < -0x25) {
            int a = (w->yaw + 0x400) & 0xFFF;
            x -= shift12((int64_t)p->cos[a] * 0x9C4);
            z -= shift12((int64_t)p->sin[a] * 0x9C4);
        }
    }
    *ox = x; *oz = z;
    return 1;
}

static int snap(int v) {
    int q = tdiv((int64_t)v + 0x4E2, 0x9C4);
    return v + 0x4E2 < 0 ? q - 1 : q;
}

typedef struct { int xy[4][2]; uint8_t c[4]; } Quad;

/* pxy, zv: the corners' precise points and depths (put_xy). */
static void floor_quad(uint32_t ot, const int xyv[4][2], const uint8_t c[4], uint32_t w0, uint32_t w1,
                       const uint16_t uvo_in[4], const int64_t pxy[4][2], const int64_t zv[4]) {
    uint16_t o[4] = {uvo_in[0], uvo_in[1], uvo_in[2], uvo_in[3]};
    if (w0 & 0x2000000u) { uint16_t t = o[0]; o[0] = o[1]; o[1] = t; t = o[2]; o[2] = o[3]; o[3] = t; }
    if (w0 & 0x4000000u) { uint16_t t = o[0]; o[0] = o[2]; o[2] = t; t = o[1]; o[1] = o[3]; o[3] = t; }
    uint32_t base = w0 & 0xFFFFu, clut = w1 >> 16 & 0xFFFFu, tpage = (w0 & 0x39FF0000u) >> 16 & 0xFFFFu;
    uint32_t q = alloc_words(13);
    if (!q) return;
    for (unsigned k = 0; k < 4; k++) {
        uint32_t uv = (base + o[k]) & 0xFFFFu;
        uint32_t col = (uint32_t)c[k] * 0x010101u;
        psx_mod_write_word(q + 4 + 12 * k, k == 0 ? 0x3C000000u | col : col);
        put_xy(q + 8 + 12 * k, xyv[k][0], xyv[k][1], pxy[k][0], pxy[k][1], zv[k]);
        psx_mod_write_word(q + 12 + 12 * k, uv | (k == 0 ? clut << 16 : k == 1 ? tpage << 16 : 0));
    }
    tj_prim_end();
    add_prim(ot, q, 12);
    s_stat_floor++;
}

static void floor_split(uint32_t ot, int rr, int cc, const int xyv[4][2], const uint8_t c[4], const uint16_t uvo[4],
                        const int64_t pv[4][2], const int64_t zv[4]) {
    const Pack *p = &s_pack;
    int m01[2] = {tdiv(xyv[0][0] + xyv[1][0], 2), tdiv(xyv[0][1] + xyv[1][1], 2)};
    int m02[2] = {tdiv(xyv[0][0] + xyv[2][0], 2), tdiv(xyv[0][1] + xyv[2][1], 2)};
    int m23[2] = {tdiv(xyv[2][0] + xyv[3][0], 2), tdiv(xyv[2][1] + xyv[3][1], 2)};
    int m13[2] = {tdiv(xyv[1][0] + xyv[3][0], 2), tdiv(xyv[1][1] + xyv[3][1], 2)};
    int mid[2] = {tdiv(m02[0] + m13[0], 2), tdiv(m01[1] + m23[1], 2)};
    uint8_t k01 = (uint8_t)((c[0] + c[1]) >> 1), k02 = (uint8_t)((c[0] + c[2]) >> 1);
    uint8_t k13 = (uint8_t)((c[1] + c[3]) >> 1), k23 = (uint8_t)((c[2] + c[3]) >> 1);
    uint8_t kc = (uint8_t)((k01 + k02 + k13 + k23) >> 2);
    const int *pts[4][4] = {{xyv[0], m01, m02, mid}, {m01, xyv[1], mid, m13},
                            {m02, mid, xyv[2], m23}, {mid, m13, m23, xyv[3]}};
    const uint8_t cols[4][4] = {{c[0], k01, k02, kc}, {k01, c[1], kc, k13},
                                {k02, kc, c[2], k23}, {kc, k13, k23, c[3]}};
    /* the same midpoints, precise (put_xy keeps each in its rounded pixel) */
    int64_t q01[2], q02[2], q23[2], q13[2], qmid[2];
    for (int i = 0; i < 2; i++) {
        q01[i] = mean_precise(pv[0][i], pv[1][i]); q02[i] = mean_precise(pv[0][i], pv[2][i]);
        q23[i] = mean_precise(pv[2][i], pv[3][i]); q13[i] = mean_precise(pv[1][i], pv[3][i]);
    }
    qmid[0] = mean_precise(q02[0], q13[0]); qmid[1] = mean_precise(q01[1], q23[1]);
    const int64_t z01 = (zv[0] + zv[1]) / 2, z02 = (zv[0] + zv[2]) / 2, z13 = (zv[1] + zv[3]) / 2,
                  z23 = (zv[2] + zv[3]) / 2, zm = (z01 + z02 + z13 + z23) / 4;
    const int64_t *ppts[4][4] = {{pv[0], q01, q02, qmid}, {q01, pv[1], qmid, q13},
                                 {q02, qmid, pv[2], q23}, {qmid, q13, q23, pv[3]}};
    const int64_t zpts[4][4] = {{zv[0], z01, z02, zm}, {z01, zv[1], zm, z13},
                                {z02, zm, zv[2], z23}, {zm, z13, z23, zv[3]}};
    for (int part = 0; part < 4; part++) {
        int hr = part >> 1, hc = part & 1;
        int pxy[4][2];
        int64_t pq[4][2];
        for (int k = 0; k < 4; k++) {
            pxy[k][0] = pts[part][k][0]; pxy[k][1] = pts[part][k][1];
            pq[k][0] = ppts[part][k][0]; pq[k][1] = ppts[part][k][1];
        }
        const uint32_t *h = &p->lhalves[2 * ((2 * rr + hr) * 20 + (2 * cc + hc))];
        floor_quad(ot, pxy, cols[part], h[0], h[1], uvo, pq, zpts[part]);
    }
}

/* Not in the arcade, whose camera never comes this low: a floor cell with
 * a corner behind the camera was dropped and the old frame showed there
 * (the Embu's low shots); only those cells, the others are drawn as before.
 * Split in four in the world, texture and shade interpolated, until every
 * piece is wholly in front and drawable, as src/tekken3_cine_floor.c does
 * for the PS1 floor; pieces wholly behind are dropped. Corners in GT4
 * order (0 1 on one edge, 2 3 on the other). */
typedef struct { int x, z, u, v, c; } Corner;
#define NEAR_Z 16
#define NEAR_DEPTH 5
#define NEAR_PIECES 384
static unsigned s_near_pieces;

static Corner mix(const Corner *c, int s, int t, int n) {   /* bilinear at (s, t) / n */
    int64_t w[4] = {(int64_t)(n - s) * (n - t), (int64_t)s * (n - t), (int64_t)(n - s) * t, (int64_t)s * t}, nn = (int64_t)n * n;
    int64_t x = 0, z = 0, u = 0, v = 0, k = 0;
    for (int i = 0; i < 4; i++) { x += w[i] * c[i].x; z += w[i] * c[i].z; u += w[i] * c[i].u; v += w[i] * c[i].v; k += w[i] * c[i].c; }
    Corner o = {(int)((x + nn / 2) / nn), (int)((z + nn / 2) / nn), (int)((u + nn / 2) / nn), (int)((v + nn / 2) / nn),
                (int)((k + nn / 2) / nn)};
    return o;
}

static void near_piece(const Gte *g, const Screen *s, uint32_t ot, const Corner q[4], int depth, uint32_t clut,
                       uint32_t tpage) {
    int64_t sx[4], sy[4], sz[4], px[4], py[4], minx = INT64_MAX, maxx = INT64_MIN, miny = INT64_MAX, maxy = INT64_MIN;
    int near = 0, behind = 0;
    for (int k = 0; k < 4; k++) {
        rtps_raw(g, q[k].x, 0, q[k].z, &sx[k], &sy[k], &sz[k], &px[k], &py[k]);
        if (sz[k] < NEAR_Z) { near = 1; behind++; }
        if (sx[k] < minx) minx = sx[k];
        if (sx[k] > maxx) maxx = sx[k];
        if (sy[k] < miny) miny = sy[k];
        if (sy[k] > maxy) maxy = sy[k];
    }
    if (behind == 4) return;
    if (!near && (maxx < -s->margin || minx >= SCREEN_W + s->margin || maxy < 0 || miny >= SCREEN_H)) return;
    if (!near && maxx - minx < 1000 && maxy - miny < 500 && minx >= -0x400 && maxx <= 0x3FF && miny >= -0x400 && maxy <= 0x3FF) {
        uint32_t a = alloc_words(13);
        if (!a) return;
        /* one pixel bigger on every side: the pieces meet each other and
         * the whole cells at T-junctions, hairline cracks otherwise */
        int64_t cx = (sx[0] + sx[1] + sx[2] + sx[3]) / 4, cy = (sy[0] + sy[1] + sy[2] + sy[3]) / 4;
        for (int k = 0; k < 4; k++) {
            int x = (int)(sx[k] + (sx[k] > cx) - (sx[k] < cx)), y = (int)(sy[k] + (sy[k] > cy) - (sy[k] < cy));
            int u = q[k].u < 0 ? 0 : q[k].u > 255 ? 255 : q[k].u, v = q[k].v < 0 ? 0 : q[k].v > 255 ? 255 : q[k].v;
            uint32_t col = (uint32_t)(q[k].c & 0xFF) * 0x010101u;
            psx_mod_write_word(a + 4 + 12 * k, k == 0 ? 0x3C000000u | col : col);
            int64_t dx = (sx[k] > cx) - (sx[k] < cx), dy = (sy[k] > cy) - (sy[k] < cy);
            put_xy(a + 8 + 12 * k, x, y, px[k] + (dx << 16), py[k] + (dy << 16), sz[k]);
            psx_mod_write_word(a + 12 + 12 * k, (uint32_t)(v << 8 | u) | (k == 0 ? clut << 16 : k == 1 ? tpage << 16 : 0));
        }
        tj_prim_end();
        add_prim(ot, a, 12);
        s_stat_floor++;
        s_near_pieces++;
        return;
    }
    if (depth >= NEAR_DEPTH || s_near_pieces >= NEAR_PIECES) return;
    Corner m[9];                        /* 3 x 3: corners, edge middles, centre */
    for (int t = 0; t < 3; t++) for (int u = 0; u < 3; u++) m[3 * t + u] = mix(q, u, t, 2);
    static const int parts[4][4] = {{0, 1, 3, 4}, {1, 2, 4, 5}, {3, 4, 6, 7}, {4, 5, 7, 8}};
    for (int i = 0; i < 4; i++) {
        Corner c[4] = {m[parts[i][0]], m[parts[i][1]], m[parts[i][2]], m[parts[i][3]]};
        near_piece(g, s, ot, c, depth + 1, clut, tpage);
    }
}

/* A whole cell for near_piece: its corners' texels as floor_quad lays them. */
static void near_cell(const Gte *g, const Screen *s, uint32_t ot, const unsigned vi[4], const uint8_t col[4], uint32_t w0,
                      uint32_t w1, const uint16_t uvo_in[4]) {
    const Pack *p = &s_pack;
    uint16_t o[4] = {uvo_in[0], uvo_in[1], uvo_in[2], uvo_in[3]};
    if (w0 & 0x2000000u) { uint16_t t = o[0]; o[0] = o[1]; o[1] = t; t = o[2]; o[2] = o[3]; o[3] = t; }
    if (w0 & 0x4000000u) { uint16_t t = o[0]; o[0] = o[2]; o[2] = t; t = o[1]; o[1] = o[3]; o[3] = t; }
    uint32_t base = w0 & 0xFFFFu;
    Corner q[4];
    for (int k = 0; k < 4; k++) {
        uint32_t uv = (base + o[k]) & 0xFFFFu;
        q[k].x = p->lverts[2 * vi[k]]; q[k].z = p->lverts[2 * vi[k] + 1];
        q[k].u = (int)(uv & 0xFF); q[k].v = (int)(uv >> 8); q[k].c = col[k];
    }
    near_piece(g, s, ot, q, 0, w1 >> 16 & 0xFFFFu, (w0 & 0x39FF0000u) >> 16 & 0xFFFFu);
}

/* The arcade floor's transform applied to the PS1 floor's own grid (its
 * cell size 0x8009E780, its TMD at *0x800ADD14: u32 z | x << 16 each), for
 * stage_check.py probe: against the PS1 floor's quads. Any source. */
static void probe_ps1grid(const View *w, int fx, int fz) {
    int32_t off[3];
    uint32_t tmd = psx_mod_read_word(0x800ADD14u), cell = psx_mod_read_word(0x8009E780u);
    uint32_t vp = tmd ? psx_mod_read_word(tmd + 0xC) : 0, nv = tmd ? psx_mod_read_word(tmd + 0x10) : 0;
    if (cell && nv <= 256) {
        int qx = tdiv((int64_t)fx + (int)cell / 2, cell), qz = tdiv((int64_t)fz + (int)cell / 2, cell);
        if (fx + (int)cell / 2 < 0) qx--;
        if (fz + (int)cell / 2 < 0) qz--;
        Gte g2 = w->world;
        apply_matrix(w->world.r, qx * (int)cell, 0, qz * (int)cell, off);
        for (int i = 0; i < 3; i++) g2.t[i] = off[i] + w->world.t[i];
        fprintf(s_probe, "ps1grid %u cell %u points", psx_mod_read_word(0x800A08F0u), cell);
        for (uint32_t i = 0; i < nv; i++) {
            uint32_t v = psx_mod_read_word(vp + 4 * i);
            int a, b, c;
            rtps(&g2, (int16_t)(v >> 16), 0, (int16_t)(v & 0xFFFF), &a, &b, &c, NULL, NULL);
            if (c) fprintf(s_probe, " %d,%d", a, b);
        }
        fprintf(s_probe, "\n");
    }
}

static void arcade_floor(const View *w, const Screen *s, int emit) {
    const Pack *p = &s_pack;
    int fx, fz;
    if (!floor_center(w, &fx, &fz)) return;
    int cx = snap(fx), cz = snap(fz);
    int col0 = pmod(tmod(cx, 10), 10), row0 = 9 - pmod(tmod(cz, 10), 10);
    Gte g = w->world;
    int32_t off[3];
    apply_matrix(w->world.r, cx * 0x9C4, 0, cz * 0x9C4, off);
    for (int i = 0; i < 3; i++) g.t[i] = off[i] + w->world.t[i];
    static int sx[256], sy[256], sz[256];
    static int32_t px[256], py[256];
    for (unsigned i = 0; i < p->lnv; i++)
        rtps(&g, p->lverts[2 * i], 0, p->lverts[2 * i + 1], &sx[i], &sy[i], &sz[i], &px[i], &py[i]);
    s_near_pieces = 0;
    if (!emit) {            /* probe: the grid's screen points */
        if (s_probe) {
            fprintf(s_probe, "floor %u centre %d %d points", psx_mod_read_word(0x800A08F0u), cx, cz);
            for (unsigned i = 0; i < p->lnv; i++) if (sz[i]) fprintf(s_probe, " %d,%d", sx[i], sy[i]);
            fprintf(s_probe, "\n");
            probe_ps1grid(w, fx, fz);
        }
        return;
    }
    int precise = s_precise, tj = s_tj;
    int mx = tdiv((int64_t)w->p1[0] + w->p2[0], 2), mz = tdiv((int64_t)w->p1[1] + w->p2[1], 2);
    int64_t ddx = w->cam[0] - mx, ddz = w->cam[2] - mz;
    int e0 = sqrt0(ddx * ddx + ddz * ddz, p->sqrt1);
    int sp = p->sin[(w->pitch + 0xEF) & 0xFFF];
    int e8 = (sp ? tdiv((int64_t)abs(w->cam[1]) << 12, sp) : 0) + p->lnear;
    int shade[256];
    for (unsigned i = 0; i < p->lnv; i++) shade[i] = -1;
    unsigned split = 0;
    int rr = row0;
    for (int r = 0; r < 10; r++) {
        int cc = col0;
        for (int c = 0; c < 10; c++) {
            uint32_t w0 = p->lcells[2 * (10 * rr + cc)], w1 = p->lcells[2 * (10 * rr + cc) + 1];
            unsigned nq = p->lcount[10 * r + c];
            uint32_t ot = main_ot(1021u - p->lunique[10 * rr + cc]);
            for (unsigned q = 0; q < nq; q++) {
                uint32_t idx = p->lquads[10 * r + c][q];
                unsigned vi[4];
                int ok = 1, near = 0;
                for (int k = 0; k < 4; k++) {
                    vi[k] = idx >> (8 * k) & 0xFF;
                    if (vi[k] >= p->lnv) ok = 0;
                    else if (!sz[vi[k]]) near = 1;     /* behind the camera: near_cell, dropped before */
                }
                if (!ok) continue;
                int xyv[4][2], iny = 0, inx = 0;
                int64_t pv[4][2], zv[4];
                for (int k = 0; k < 4; k++) {
                    xyv[k][0] = sx[vi[k]]; xyv[k][1] = sy[vi[k]];
                    pv[k][0] = px[vi[k]]; pv[k][1] = py[vi[k]]; zv[k] = sz[vi[k]];
                    if (xyv[k][1] >= 0 && xyv[k][1] < SCREEN_H) iny = 1;
                    if ((unsigned)((xyv[k][0] + s->margin) & 0xFFFF) < (unsigned)(SCREEN_W + 2 * s->margin)) inx = 1;
                }
                int x0 = xyv[0][0], x1 = x0, y0 = xyv[0][1], y1 = y0;
                for (int k = 1; k < 4; k++) {
                    if (xyv[k][0] < x0) x0 = xyv[k][0];
                    if (xyv[k][0] > x1) x1 = xyv[k][0];
                    if (xyv[k][1] < y0) y0 = xyv[k][1];
                    if (xyv[k][1] > y1) y1 = xyv[k][1];
                }
                if (!near && (!iny || !inx)) {
                    /* B87: a cell right in front of a camera low on the
                     * floor (K.O., replay and winner cameras; the arcade's
                     * never come so low) has its corners off the screen on
                     * both sides yet covers its bottom: in pieces, as a cell
                     * behind the camera. Dropped before, older frames there. */
                    if (x1 < -s->margin || x0 >= SCREEN_W + s->margin || y1 < 0 || y0 >= SCREEN_H) continue;
                    near = 1;
                } else if (!near && (x1 - x0 > 1023 || y1 - y0 > 511)) {
                    near = 1;           /* B87: too big for the GPU, which drops it */
                }
                if (nq != 1 && nq != 2 && nq != 4) continue;
                const uint16_t *uvo = p->luv[nq] + 4 * (nq * (w0 >> 30) + q);
                uint8_t col[4];
                for (int k = 0; k < 4; k++) {
                    unsigned i = vi[k];
                    if (p->lkind == 0 && !p->lfog) { col[k] = 0x80; continue; }
                    if (shade[i] < 0) {
                        int x = p->lverts[2 * i], z = p->lverts[2 * i + 1], v;
                        if (p->lkind == 0) {
                            int64_t d = sz[i] - e0; if (d < 0) d = 0;
                            int64_t kk = (d * 8 * 0x1E0 + d * -0x1E5) * 2;
                            kk = (kk < 0 ? kk + 0xFFFF : kk) >> 16;
                            if (kk > 0x3FF) kk = 0x3FF;
                            int64_t cv = (int64_t)p->fog[kk] * p->lfog;
                            cv = ((cv < 0 ? cv + 0x7F : cv) >> 7) + 0x80;
                            v = cv < 0 ? 0 : cv > 0xFE ? 0xFE : (int)cv;
                        } else if (p->lkind == 1) {
                            int64_t a1 = w->p1[0] - (int64_t)cx * 0x9C4 - x, b1 = w->p1[1] - (int64_t)cz * 0x9C4 - z;
                            int64_t a2 = w->p2[0] - (int64_t)cx * 0x9C4 - x, b2 = w->p2[1] - (int64_t)cz * 0x9C4 - z;
                            int64_t d1 = a1 * a1 + b1 * b1, d2 = a2 * a2 + b2 * b2;
                            if (!d1) d1 = 1;
                            if (!d2) d2 = 1;
                            int64_t cv = 0xF200000 / d1 + 0xF200000 / d2;
                            v = cv > 0xFE ? 0xFE : (int)cv;
                        } else {
                            int64_t a = mx - (x + (int64_t)cx * 0x9C4), b = mz - (z + (int64_t)cz * 0x9C4);
                            int64_t d = a * a + b * b;
                            if (!d) d = 1;
                            int64_t cv = 0x7A120000 / d;
                            v = cv > 0xC0 ? 0xC0 : (int)cv;
                        }
                        shade[i] = v & 0xFF;
                    }
                    col[k] = (uint8_t)shade[i];
                }
                if (near) {
                    near_cell(&g, s, ot, vi, col, w0 & 0x3FFFFFFFu, w1, uvo);
                    continue;
                }
                int nearq = ((uint32_t)(w->pitch - 0x400)) < 0x201u;
                for (int k = 0; k < 4; k++) if (sz[vi[k]] < e8) nearq = 1;
                if (split < 11 && nearq) {
                    floor_split(ot, rr, cc, xyv, col, uvo, pv, zv);
                    split++;
                } else {
                    floor_quad(ot, xyv, col, w0 & 0x3FFFFFFFu, w1, uvo, pv, zv);
                }
                /* B87: cells cut in 1, 2 or 4 quads meet in T-junctions,
                 * dotted slits under the low cameras: the cell's quad again,
                 * a pixel wider, behind the stage (wide_prim) */
                int wxy[4][2], sx4 = 0, sy4 = 0;
                for (int k = 0; k < 4; k++) { sx4 += xyv[k][0]; sy4 += xyv[k][1]; }
                for (int k = 0; k < 4; k++) {
                    wxy[k][0] = xyv[k][0] + (xyv[k][0] * 4 > sx4) - (xyv[k][0] * 4 < sx4);
                    wxy[k][1] = xyv[k][1] + (xyv[k][1] * 4 > sy4) - (xyv[k][1] * 4 < sy4);
                }
                s_precise = s_tj = 0;
                floor_quad(wide_slot(), wxy, col, w0 & 0x3FFFFFFFu, w1, uvo, pv, zv);
                s_precise = precise; s_tj = tj;
            }
            cc = cc == 9 ? 0 : cc + 1;
        }
        rr = rr == 0 ? 9 : rr - 1;
    }
}

/* TTT's floor (0x8011FCC4 / 0x8011E10C, ttt.floor_commands): a grid of
 * cols x rows cells of `size` (FLR2), one GT4 each, centred on the fighters'
 * middle moved forward along the camera yaw, its texture map wrapping every
 * cols / rows cells; T3's three lights; the cells nearest the camera (at most
 * 11) as four GT3 around the middle of the diagonal 1-2. Ranks 1021 minus
 * the cell's texture rank. TTT's screen test (a vertex above the bottom, one
 * across the 512 columns) on the PS1 screen and its 16:9 margins. A cell
 * with a vertex behind the camera, which TTT drops, goes to near_piece as
 * T3's floor does (the Embu's low shots). */
static int s_floor_probe;               /* this frame's TTT floor logged (stage_check.py probe) */

static void ttt_floor_cell(uint32_t ot, const int xyv[4][2], const uint8_t col[4], const uint8_t uv[4][2], uint32_t clut,
                           uint32_t tpage) {
    if (s_floor_probe) {
        fprintf(s_probe, "fq %u", stage_rank(ot));
        for (int k = 0; k < 4; k++) fprintf(s_probe, " %d %d %u %u %u", xyv[k][0], xyv[k][1], col[k], uv[k][0], uv[k][1]);
        fprintf(s_probe, " %u %u\n", clut, tpage);
    }
    uint32_t q = alloc_words(13);
    if (!q) return;
    for (unsigned k = 0; k < 4; k++) {
        uint32_t c = (uint32_t)col[k] * 0x010101u;
        uint32_t t = (uint32_t)uv[k][1] << 8 | uv[k][0];
        psx_mod_write_word(q + 4 + 12 * k, k == 0 ? 0x3C000000u | c : c);
        psx_mod_write_word(q + 8 + 12 * k, xy(xyv[k][0], xyv[k][1]));
        psx_mod_write_word(q + 12 + 12 * k, t | (k == 0 ? clut << 16 : k == 1 ? tpage << 16 : 0));
    }
    add_prim(ot, q, 12);
    s_stat_floor++;
}

static void ttt_floor_fan(uint32_t ot, const int m[2], uint8_t mc, const uint8_t muv[2], const int a[2], uint8_t ca,
                          const uint8_t uva[2], const int b[2], uint8_t cb, const uint8_t uvb[2], uint32_t clut, uint32_t tpage) {
    if (s_floor_probe)
        fprintf(s_probe, "ft %u %d %d %u %u %u %d %d %u %u %u %d %d %u %u %u %u %u\n", stage_rank(ot),
                m[0], m[1], mc, muv[0], muv[1], a[0], a[1], ca, uva[0], uva[1], b[0], b[1], cb, uvb[0], uvb[1], clut, tpage);
    uint32_t q = alloc_words(10);
    if (!q) return;
    psx_mod_write_word(q + 4, 0x34000000u | (uint32_t)mc * 0x010101u);
    psx_mod_write_word(q + 8, xy(m[0], m[1]));
    psx_mod_write_word(q + 12, clut << 16 | (uint32_t)muv[1] << 8 | muv[0]);
    psx_mod_write_word(q + 16, (uint32_t)ca * 0x010101u);
    psx_mod_write_word(q + 20, xy(a[0], a[1]));
    psx_mod_write_word(q + 24, tpage << 16 | (uint32_t)uva[1] << 8 | uva[0]);
    psx_mod_write_word(q + 28, (uint32_t)cb * 0x010101u);
    psx_mod_write_word(q + 32, xy(b[0], b[1]));
    psx_mod_write_word(q + 36, (uint32_t)uvb[1] << 8 | uvb[0]);
    add_prim(ot, q, 9);
    s_stat_floor++;
}

static int32_t i32(int64_t v) { return (int32_t)(uint32_t)(uint64_t)v; }


/* One copy of the grid around posx, posz (`first`: the one a probe logs);
 * `half` > 0: only the cells within |x|, |z| <= half (world); `wide`: every
 * cell again a pixel wider in TTT_OT_WIDE, over the far background, under
 * the whole stage. */
static void ttt_floor_grid(const View *w, const Screen *s, int light1[2], int light2[2], int posx, int posz, int first,
                           int half, int wide) {
    const Pack *p = &s_pack;
    const int16_t *sine = p->tsine;
    int t = p->gsize, cols = p->gcols, rows = p->grows;
    int yb = w->yaw & 0xFFF;
    int x = posx + (t >> 1), z = posz + (t >> 1);
    int ix = tdiv(x, t) - (x < 0), iz = tdiv(z, t) - (z < 0);
    int col = tmod(ix, cols); if (col < 0) col += cols;
    int s0 = tmod(iz, rows); if (s0 < 0) s0 += rows;
    s0 = rows - (s0 + 1);
    int cx = ix * t, cz = iz * t;
    Gte g = w->world;
    int32_t off[3];
    apply_matrix(w->world.r, cx, 0, cz, off);
    for (int i = 0; i < 3; i++) g.t[i] = off[i] + w->world.t[i];
    static int sx[256], sy[256], sz[256];
    static uint8_t lum[256];
    for (unsigned i = 0; i < p->gnv; i++) rtps(&g, p->gverts[2 * i], 0, p->gverts[2 * i + 1], &sx[i], &sy[i], &sz[i], NULL, NULL);
    /* B124: at night TOGR's kind (0x8011C204: kind 0 lit around the fighters, 2) */
    int kind = ttt_night() && p->togr[1] <= 2 ? p->togr[1] : p->gkind;
    if (kind == 0) {
        int dx = w->cam[0] - ((light1[0] + light2[0]) >> 1), dz = w->cam[2] - ((light1[1] + light2[1]) >> 1);
        int d = sqrt0(i32((int64_t)dx * dx + (int64_t)dz * dz), p->tsqrt);
        for (unsigned i = 0; i < p->gnv; i++) {
            int v = sz[i] - d;
            if (v < t) v = t;
            v = (int)(((int64_t)v * 0x1A36) >> 16);
            lum[i] = p->gramp[v > 0x3FF ? 0x3FF : v];
        }
    } else if (kind == 2) {
        int mx = (light1[0] + light2[0]) >> 1, mz = (light1[1] + light2[1]) >> 1;
        for (unsigned i = 0; i < p->gnv; i++) {
            int64_t ex = mx - (cx + p->gverts[2 * i]), ez = mz - (cz + p->gverts[2 * i + 1]);
            int32_t d = i32(ex * ex + ez * ez);
            if (!d) d = 1;
            int v = tdiv(0x7A120000, d);
            if (v > 0xC0) v = 0xC0;
            lum[i] = (uint8_t)(p->ghalf ? v >> 1 : v);
        }
    } else {
        int ax = light1[0] - cx, az = light1[1] - cz, bx = light2[0] - cx, bz = light2[1] - cz;
        for (unsigned i = 0; i < p->gnv; i++) {
            int64_t ex = ax - p->gverts[2 * i], ez = az - p->gverts[2 * i + 1];
            int64_t fx = bx - p->gverts[2 * i], fz = bz - p->gverts[2 * i + 1];
            int32_t d1 = i32(ex * ex + ez * ez), d2 = i32(fx * fx + fz * fz);
            if (!d1) d1 = 1;
            if (!d2) d2 = 1;
            int v = tdiv(0xF200000, d1) + tdiv(0xF200000, d2);
            lum[i] = (uint8_t)(v > 0xFE ? 0xFE : v);
        }
    }
    int k = (w->pitch + 0xEF) & 0xFFF;
    int limit = 0x7FFFFFFF;
    if (sine[k + 0x400]) {
        int s1 = tdiv((int64_t)sine[k] << 12, sine[k + 0x400]);
        int v = tdiv((int64_t)tdiv(t, 2) * sine[k + 0x400], 4096);
        v = tdiv((int64_t)v * (0x2000 - sine[yb + 0x400]), 4096);
        if (s1) limit = tdiv((int64_t)abs(w->cam[1]) << 12, s1) + v;
    }
    if (first) s_near_pieces = 0;
    unsigned quad = 0, cnt = 0;
    s_floor_probe = first && s_probe && psx_mod_read_word(0x800A08F0u) % 15 == 0;
    if (s_floor_probe) {        /* the inputs of ttt.floor_commands */
        fprintf(s_probe, "tttfloor %u", psx_mod_read_word(0x800A08F0u));
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) fprintf(s_probe, " %d", w->world.r[i][j]);
        for (int i = 0; i < 3; i++) fprintf(s_probe, " %d", w->world.t[i]);
        fprintf(s_probe, " %d %d %d %d %d %d %d %d %d %d %d %d %d %u %d %d %d %u\n", w->pitch, w->yaw, w->cam[0], w->cam[1],
                w->cam[2], w->p1[0], w->p1[1], w->p2[0], w->p2[1], light1[0], light1[1], light2[0], light2[1], w->world.h,
                w->world.ofx, w->world.ofy, s->margin, s_tttanim.light);
    }
    for (int r = 0; r < rows; r++) {
        int tc = col;
        for (int c = 0; c < cols; c++) {
            uint32_t q4 = p->gquads[quad++];
            unsigned vi[4];
            int ok = 1, near = 0;
            for (int j = 0; j < 4; j++) {
                vi[j] = q4 >> (8 * j) & 0xFF;
                if (vi[j] >= p->gnv) ok = 0;
                else if (!sz[vi[j]]) near = 1;
            }
            if (ok && half)
                for (int j = 0; j < 4; j++)
                    if (abs(cx + p->gverts[2 * vi[j]]) > half || abs(cz + p->gverts[2 * vi[j] + 1]) > half) ok = 0;
            if (ok) {
                uint32_t w0 = p->gcells[2 * (15 * s0 + tc)], w1 = p->gcells[2 * (15 * s0 + tc) + 1];
                const uint16_t *o = p->gcorners + 4 * (4 * (w0 >> 30) + 2 * (w0 >> 25 & 1) + (w0 >> 26 & 1));
                uint32_t base = w0 & 0xFFFF, clut = ttt_floor_light(s0, tc, w1 >> 16 & 0xFFFF), tpage = (w0 >> 16) & 0x39FF;
                uint8_t uv[4][2], cl[4];
                for (int j = 0; j < 4; j++) {
                    uint32_t u = (base + o[j]) & 0xFFFF;
                    uv[j][0] = (uint8_t)(u & 0xFF); uv[j][1] = (uint8_t)(u >> 8);
                    cl[j] = lum[vi[j]];
                }
                uint32_t ot = stage_ot(1021u - p->gunique[15 * s0 + tc]);
                if (near) {
                    Corner qc[4];
                    for (int j = 0; j < 4; j++)
                        qc[j] = (Corner){p->gverts[2 * vi[j]], p->gverts[2 * vi[j] + 1], uv[j][0], uv[j][1], cl[j]};
                    near_piece(&g, s, ot, qc, 0, clut, tpage);
                } else {
                    int xyv[4][2], iny = 0, inx = 0;
                    for (int j = 0; j < 4; j++) {
                        xyv[j][0] = sx[vi[j]]; xyv[j][1] = sy[vi[j]];
                        if (xyv[j][1] < SCREEN_H) iny = 1;
                        if (xyv[j][0] >= -s->margin && xyv[j][0] < SCREEN_W + s->margin) inx = 1;
                    }
                    if (iny && inx) {
                        if (sz[vi[0]] < limit && cnt < 11) {
                            cnt++;
                            int mid[2] = {(xyv[1][0] + xyv[2][0]) >> 1, (xyv[1][1] + xyv[2][1]) >> 1};
                            uint8_t mc = (uint8_t)((cl[1] + cl[2]) >> 1);
                            uint8_t muv[2] = {(uint8_t)((uv[1][0] + uv[2][0]) >> 1), (uint8_t)((uv[1][1] + uv[2][1]) >> 1)};
                            static const int fan[4][2] = {{0, 1}, {1, 3}, {3, 2}, {2, 0}};
                            for (int f = 0; f < 4; f++) {
                                int pa = fan[f][0], pb = fan[f][1];
                                ttt_floor_fan(ot, mid, mc, muv, xyv[pa], cl[pa], uv[pa], xyv[pb], cl[pb], uv[pb], clut, tpage);
                            }
                        } else {
                            ttt_floor_cell(ot, xyv, cl, uv, clut, tpage);
                        }
                        if (wide) {
                            /* B100: the cell a pixel wider, behind the
                             * stage (wide_prim): the slits at the grid's
                             * edges and a wall's foot, as B87 for T3 */
                            int wxy[4][2], sx4 = 0, sy4 = 0, probe = s_floor_probe;
                            for (int j = 0; j < 4; j++) { sx4 += xyv[j][0]; sy4 += xyv[j][1]; }
                            for (int j = 0; j < 4; j++) {
                                wxy[j][0] = wide_coord(xyv[j][0], (xyv[j][0] * 4 > sx4) - (xyv[j][0] * 4 < sx4));
                                wxy[j][1] = wide_coord(xyv[j][1], (xyv[j][1] * 4 > sy4) - (xyv[j][1] * 4 < sy4));
                            }
                            s_floor_probe = 0;
                            ttt_floor_cell(ttt_slot(TTT_OT_WIDE), wxy, cl, uv, clut, tpage);
                            s_floor_probe = probe;
                        }
                    }
                }
            }
            tc = tc + 1 >= cols ? 0 : tc + 1;
        }
        s0 = s0 - 1 < 0 ? rows - 1 : s0 - 1;
    }
    if (s_floor_probe) fprintf(s_probe, "fend %u\n", s_near_pieces);
    s_floor_probe = 0;
}

static void ttt_floor(const View *w, const Screen *s, int light1[2], int light2[2]) {
    const Pack *p = &s_pack;
    const int16_t *sine = p->tsine;
    if (!p->gfloor || sine[(w->pitch + 0xEF) & 0xFFF] <= 0) return;
    int t = p->gsize, cols = p->gcols, rows = p->grows;
    int posx = (w->p1[0] + w->p2[0]) >> 1, posz = (w->p1[1] + w->p2[1]) >> 1;
    int a = t + tdiv((int64_t)t * (abs(sine[w->pitch & 0xFFF]) << 2), 4096);
    int yb = w->yaw & 0xFFF;
    if (s_floor_at) {                   /* a cinematic's centre, as it is */
        posx = s_floor_xz[0];
        posz = s_floor_xz[1];
    } else {
        posx -= tdiv((int64_t)sine[yb] * a, 4096);
        posz += tdiv((int64_t)sine[yb + 0x400] * a, 4096);
    }
    if (!s_floor_at) {
        /* B100: the grid alone, as TTT draws it. B77 drew its 8 neighbours
         * behind the stage for the ground the PS1's throw, replay and winner
         * cameras see past it; they also laid floor where TTT has none:
         * Unknown's void (14), outside the ring (11), past the platforms'
         * edges (9, 12), over the canal (3), up to the horizon (10, 13).
         * There the far background shows, as in TTT, and the fallbacks of
         * TTT_OT_FILL under it; the cells widened by a pixel close the slits
         * between the grid and the stage. */
        ttt_floor_grid(w, s, light1, light2, posx, posz, 1, 0, 1);
        return;
    }
    /* a cinematic's centre: the grid's 8 neighbours too, a whole grid away
     * (the texture map wraps every cols / rows cells: seamless), every cell
     * kept within the stage's courtyard (`half`) */
    for (int dz = -1; dz <= 1; dz++)
        for (int dx = -1; dx <= 1; dx++)
            ttt_floor_grid(w, s, light1, light2, posx + dx * cols * t, posz + dz * rows * t, !dx && !dz, s_floor_half, 0);
}

static void read_gte_screen(const CPUState *cpu, Screen *s, Gte *g) {
    s->ofx = (int)cpu->gte_ctrl[24] >> 16;
    s->ofy = (int)cpu->gte_ctrl[25] >> 16;
    s->h = (int)(cpu->gte_ctrl[26] & 0xFFFF);
    s->margin = psx_mod_widescreen_x_margin();
    if (s->margin < 0) s->margin = 0;
    g->ofx = (int32_t)cpu->gte_ctrl[24];
    g->ofy = (int32_t)cpu->gte_ctrl[25];
    g->h = cpu->gte_ctrl[26] & 0xFFFF;
}

/* The PS1 floor, kinds 0 (0x80048E58) and 1-3 (0x80049848): a0, a1 the
 * fighters, the world matrix 0x800ADF70 just built by 0x80045CA8. */
static int floor_draw(CPUState *cpu) {
    if (!active()) return 0;
    int pitch = (int)psx_mod_read_word(CAMERA);
    if (!s_shadow) psx_mod_write_word(FLOOR_SHOWN, s_sin[(pitch + 0xEF) & 0xFFF] > 0);   /* as 0x80048E58 / 0x80049848 */
    View w;
    Screen s;
    read_gte_screen(cpu, &s, &w.world);
    for (int i = 0; i < 3; i++)
        for (int k = 0; k < 3; k++) w.world.r[i][k] = (int16_t)psx_mod_read_half(WORLD + 6 * i + 2 * k);
    for (int i = 0; i < 3; i++) w.world.t[i] = (int32_t)psx_mod_read_word(WORLD + 0x14 + 4 * i);
    w.pitch = pitch;
    w.yaw = (int)psx_mod_read_word(CAMERA + 4);
    for (int i = 0; i < 3; i++) w.cam[i] = (int)psx_mod_read_word(CAMERA + 0x14 + 4 * i);
    w.p1[0] = (int)psx_mod_read_word(cpu->gpr[4] + 0xF68); w.p1[1] = (int)psx_mod_read_word(cpu->gpr[4] + 0xF70);
    w.p2[0] = (int)psx_mod_read_word(cpu->gpr[5] + 0xF68); w.p2[1] = (int)psx_mod_read_word(cpu->gpr[5] + 0xF70);
    s_cursor = s_memory + BUFFER_BYTES * buffer();
    s_end = s_cursor + FLOOR_BYTES;
    if (s_pack.source == TEKKEN3_STAGE_TTT) {
        s_cursor += 4u * TTT_OT_RANKS;     /* TTT's private OT first */
    } else {                                /* T3's (B87), set up anew */
        s_t3_ot_draw = ~0u;
        t3_ot();
        s_cursor += 4u * T3_OT_SLOTS;
    }
    s_stat_floor = 0;
    /* PGXP (precise words, T-junction pass) covers the arcade stages it was
     * validated on; TTT Stages' packets stay as they were drawn before it. */
    s_precise = psx_mod_precision_wanted() && s_pack.source != TEKKEN3_STAGE_TTT;
    s_tj = s_precise && psx_mod_geometry_wanted();
    if (s_pack.source == TEKKEN3_STAGE_TTT) {
        if (s_pack.lite && !s_shadow && ++s_tttanim.light > 0xEF) s_tttanim.light = 0;   /* 0x8011E10C, stage 11 */
        if (!s_shadow) ttt_floor(&w, &s, w.p1, w.p2);
        else if (s_probe) probe_ps1grid(&w, tdiv((int64_t)w.p1[0] + w.p2[0], 2), tdiv((int64_t)w.p1[1] + w.p2[1], 2));
    } else {
        if (s_tj && !s_shadow) tj_begin(TJ_HOOK_FLOOR);
        arcade_floor(&w, &s, !s_shadow);
        tj_fix();
    }
    return !s_shadow;
}

static int floor_hook(CPUState *cpu) {
    if (!perf_on()) return floor_draw(cpu);
    uint64_t t = now_ns();
    int r = floor_draw(cpu);
    s_perf_floor = now_ns() - t;
    return r;
}

extern void __real_func_80048E58(CPUState *cpu);
void __wrap_func_80048E58(CPUState *cpu) {
    if ((cpu->pc == 0 || cpu->pc == 0x80048E58u) && floor_hook(cpu)) { cpu->pc = cpu->gpr[31]; return; }
    __real_func_80048E58(cpu);
}

extern void __real_func_80049848(CPUState *cpu);
void __wrap_func_80049848(CPUState *cpu) {
    if ((cpu->pc == 0 || cpu->pc == 0x80049848u) && floor_hook(cpu)) { cpu->pc = cpu->gpr[31]; return; }
    __real_func_80049848(cpu);
}

/* The Embu's floor. 0x8004808C, which picks the floor routine at each
 * stage load, gives the Embu (state 6) the overlay's 0x800D494C: a grid of
 * 24 FT4 that only meets the PS1 tiles, so under the arcade tiles it left
 * slits and gaps (the screen is never cleared: old frames showed through)
 * and the arcade tiles' own ground showed around it in another shade. With
 * the arcade stage drawing, the pointer is turned to 0x80048E58 for the
 * Embu, whose hook draws the arcade floor; put back if the stage stops
 * drawing (the next stage load sets it anyway). */
static int s_embu_floor;

static void embu_floor(CPUState *cpu, uint32_t entry) {
    if (cpu->pc != 0 && cpu->pc != entry) return;
    uint32_t fn = psx_mod_read_word(FLOOR_FN);
    if (fn == EMBU_FLOOR && !s_shadow && active()) {
        psx_mod_write_word(FLOOR_FN, KIND0_FLOOR);
        s_embu_floor = 1;
        if (log_on()) { fprintf(stdout, "arcade stages: the Embu's floor drawn by the arcade floor\n"); fflush(stdout); }
    } else if (s_embu_floor) {
        if (fn == KIND0_FLOOR && (int16_t)psx_mod_read_half(0x800AE204u) == 6 && !active())
            psx_mod_write_word(FLOOR_FN, EMBU_FLOOR);
        if (fn != KIND0_FLOOR || (int16_t)psx_mod_read_half(0x800AE204u) != 6) s_embu_floor = 0;
    }
}

extern void __real_func_80048240(CPUState *cpu);
void __wrap_func_80048240(CPUState *cpu) {
    embu_floor(cpu, 0x80048240u);
    __real_func_80048240(cpu);
}

extern void __real_func_80048208(CPUState *cpu);
void __wrap_func_80048208(CPUState *cpu) {
    embu_floor(cpu, 0x80048208u);
    __real_func_80048208(cpu);
}

/* ------------------------------------------------------------------ */
/* the tiles: after 0x8006D014 returns                                */
/* ------------------------------------------------------------------ */
static uint32_t s_ret, s_sp;
static int s_axis_before, s_running, s_probe_gte;
static int32_t s_ps1_gte[8];

static void probe_line(const Gte *mine, const Gte *ps1) {
    if (!s_probe) return;
    fprintf(s_probe, "frame %u arena %u axis %d cam", psx_mod_read_word(0x800A08F0u), psx_mod_read_half(ARENA),
            (int)psx_mod_read_word(AXIS));
    for (int i = 0; i < 8; i++) fprintf(s_probe, " %d", (int)psx_mod_read_word(CAMERA + 4 * i));
    fprintf(s_probe, " | gte_ps1 %d", s_probe_gte);
    for (int i = 0; i < 8; i++) fprintf(s_probe, " %08X", (unsigned)s_ps1_gte[i]);
    fprintf(s_probe, " | port_ps1");
    for (int i = 0; i < 3; i++) for (int k = 0; k < 3; k++) fprintf(s_probe, " %d", ps1->r[i][k]);
    for (int i = 0; i < 3; i++) fprintf(s_probe, " %d", ps1->t[i]);
    fprintf(s_probe, " | arcade");
    for (int i = 0; i < 3; i++) fprintf(s_probe, " %d", mine->t[i]);
    fprintf(s_probe, " | screen %d %d %u\n", mine->ofx >> 16, mine->ofy >> 16, mine->h);
    fflush(s_probe);
}

/* ------------------------------------------------------------------ */
/* TTT stage 4's storm (0x8015C454 at the stage load, 0x8015C2A8 every  */
/* frame at the head of the tiles, 0x8015BFA0 starts a flash;           */
/* ttt.TttStorm is the reference)                                     */
/* ------------------------------------------------------------------ */
/* Five counters climb by rand() & 0xF a frame against the thresholds of
 * STRM; the first over its threshold starts a flash of its type (0..4),
 * and two flashes are forced at idle frames 60 and 130 counted from the
 * stage load (here: from the fight's stage decision, which stands for TTT's
 * load). A flash plays its sequence, a frame a value: 1 lit (far background
 * entry 15 + type and the point light), 0 the normal sky (entry 4), -1 the
 * end; type 4 runs into type 5. The far background takes the sky the
 * previous frame chose (it is drawn before the storm runs). The light:
 * TTT's 0x8010CE8C is the PS1's hit-flash light 0x80039F0C (same structure:
 * point, colour column 1 of the colour matrix 0x8009E5C0, 48-frame timer
 * 0x8009E5EC that 0x80039FBC fades), set the same way. The thunder: types
 * 0-2 on voice 0x1C (no sound while 0x1C still sounds, the flash still
 * comes), 3-4 on 0x1D. rand(): the PsyQ formula on the host's own seed
 * (TEKKEN3_TTT_STAGES_SEED fixes it). A cinematic that forces a stage
 * drives the storm itself (tekken3_ttt_stage_flash): no random starts. */
static struct {
    int index, type, frames, sky, pending;
    int counters[5];
    int32_t point[3];
    unsigned decisions;
    uint64_t lit_frames, flashes;
} s_storm = {-1, 0, 0, 4, -1, {0}, {0}, 0, 0, 0};
static uint32_t s_rand;
static int s_rand_seeded;
typedef struct { const int16_t *pcm; uint32_t frames, pos; uint16_t sound; } ThunderVoice;
static ThunderVoice s_thunder[2];       /* voices 0x1C, 0x1D */

static int storm_rand(void) {
    if (!s_rand_seeded) {
        const char *e = getenv("TEKKEN3_TTT_STAGES_SEED");
        s_rand = e && *e ? (uint32_t)strtoul(e, NULL, 0) : (uint32_t)now_ns() ^ (uint32_t)(now_ns() >> 32);
        s_rand_seeded = 1;
    }
    s_rand = s_rand * 0x41C64E6Du + 12345u;
    return (int)(s_rand >> 16 & 0x7FFF);
}

void tekken3_arcade_stages_thunder_stop(void) { memset(s_thunder, 0, sizeof s_thunder); }

static void storm_reset(void) {
    s_storm.index = -1; s_storm.type = 0; s_storm.frames = 0; s_storm.sky = 4;
    s_storm.counters[0] = storm_rand() & 0x3FF;
    s_storm.counters[1] = storm_rand() & 0x3FF;
    s_storm.counters[2] = storm_rand() & 0x3FF;
    s_storm.counters[3] = storm_rand() & 0x7FF;
    s_storm.counters[4] = storm_rand() & 0x7FF;
    s_storm.decisions = tekken3_stage_decisions();
    tekken3_arcade_stages_thunder_stop();
}

static void thunder_play(int type) {
    const Pack *p = &s_pack;
    unsigned k = type > 4 ? 4 : (unsigned)type;
    uint16_t sound = p->ssound[k][0], voice = p->ssound[k][1];
    for (unsigned i = 0; i < p->nthunder; i++)
        if (p->thunder[i].sound == sound) {
            s_thunder[voice == 0x1D] = (ThunderVoice){p->thunder[i].pcm, p->thunder[i].frames, 0, sound};
            if (log_on()) { fprintf(stdout, "arcade stages: thunder 0x%03X on voice 0x%02X\n", sound, voice); fflush(stdout); }
            return;
        }
}

static int ratan2(int y, int x) { return (int)lround(atan2((double)y, (double)x) * 2048.0 / 3.14159265358979323846); }

/* 0x8015BFA0 once its type is known: the light's point near the fighters'
 * middle, on a side drawn around the camera's, 0x600..0xDFF above the
 * floor; then the thunder. */
static void storm_start(int type, int counted, int quiet) {
    const Pack *p = &s_pack;
    int p1x = (int)psx_mod_read_word(P1_X), p1z = (int)psx_mod_read_word(P1_Z);
    int p2x = (int)psx_mod_read_word(P2_X), p2z = (int)psx_mod_read_word(P2_Z);
    int mx = (p1x + p2x) >> 1, mz = (p1z + p2z) >> 1;
    int dx = (int16_t)(p1x - mx), dz = (int16_t)(p1z - mz);
    int r = (int)sqrt((double)dx * dx + (double)dz * dz);                 /* 0x801555A0 */
    int camx = (int)psx_mod_read_word(CAMERA + 0x14), camz = (int)psx_mod_read_word(CAMERA + 0x1C);
    int ca = (int16_t)((ratan2((int16_t)(camx - mx), (int16_t)(camz - mz)) - 0x400) & 0xFFF);   /* 0x801554E8 */
    int vy = (-0x3FF - ca) + (storm_rand() & 0x7FF);
    int dist = (int16_t)((r >> 1) + r);
    int sn = p->tsine[vy & 0xFFF], cs = p->tsine[(vy & 0xFFF) + 0x400];
    s_storm.point[0] = (int32_t)(((int64_t)sn * dist) >> 12) + mx;
    s_storm.point[2] = (int32_t)(((int64_t)cs * dist) >> 12) + mz;
    s_storm.point[1] = -0x600 - (storm_rand() & 0x7FF);
    s_storm.type = type;
    if (counted) {
        s_storm.counters[type] = 0;
        if (type > 2)
            for (int k = 0; k < 5; k++) s_storm.counters[k] = (int16_t)(s_storm.counters[k] - (s_storm.counters[k] >> 2));
    }
    s_storm.flashes++;
    if (log_on()) {
        fprintf(stdout, "arcade stages: storm flash type %d (%s) at frame %u, light at %d %d %d\n", type,
                counted ? "drawn" : "asked", psx_mod_read_word(0x800A08F0u), s_storm.point[0], s_storm.point[1],
                s_storm.point[2]);
        fflush(stdout);
    }
    if (quiet) return;                              /* TEKKEN3_TTT_FLASH_QUIET: the PS2 Embu's silent flashes */
    if (type <= 2 && s_thunder[0].pcm) return;      /* 0x8012568C(0x1C): voice busy, no sound */
    thunder_play(type);
}

/* The PS1's 0x80039F0C(point, colour) */
static void storm_light(CPUState *cpu, const uint8_t c[3]) {
    psx_mod_write_word(0x8009E5E0u, (uint32_t)s_storm.point[0]);
    psx_mod_write_word(0x8009E5E4u, (uint32_t)s_storm.point[1]);
    psx_mod_write_word(0x8009E5E8u, (uint32_t)s_storm.point[2]);
    psx_mod_write_half(0x8009E5C2u, (uint16_t)(c[0] << 4));
    psx_mod_write_half(0x8009E5C8u, (uint16_t)(c[1] << 4));
    psx_mod_write_half(0x8009E5CEu, (uint16_t)(c[2] << 4));
    uint16_t m[9];
    for (int i = 0; i < 9; i++) m[i] = psx_mod_read_half(0x8009E5C0u + 2u * i);
    cpu->gte_ctrl[16] = m[0] | (uint32_t)m[1] << 16;           /* SetColorMatrix */
    cpu->gte_ctrl[17] = m[2] | (uint32_t)m[3] << 16;
    cpu->gte_ctrl[18] = m[4] | (uint32_t)m[5] << 16;
    cpu->gte_ctrl[19] = m[6] | (uint32_t)m[7] << 16;
    cpu->gte_ctrl[20] = (uint32_t)(int32_t)(int16_t)m[8];
    psx_mod_write_word(0x8009E5ECu, 0x30);
}

static void storm_step(CPUState *cpu) {
    const Pack *p = &s_pack;
    if (!p->storm || psx_mod_read_word(PAUSED)) return;
    if (s_force < 0 && tekken3_stage_decisions() != s_storm.decisions) storm_reset();    /* a new fight */
    if (s_storm.pending >= 0) {                 /* a cinematic's flash, now */
        int type = s_storm.pending & 0xFF, quiet = (s_storm.pending & TEKKEN3_TTT_FLASH_QUIET) != 0;
        s_storm.pending = -1;
        s_storm.index = -1;
        storm_start(type, 0, quiet);
    } else if (s_storm.index == -1) {
        if (s_force >= 0) return;               /* a cinematic drives the storm */
        for (int k = 0; k < 5; k++) s_storm.counters[k] = (int16_t)(s_storm.counters[k] + (storm_rand() & 0xF));
        s_storm.frames++;
        for (int f = 0; f < 2; f++)
            if (s_storm.frames == p->sforced[f][0]) { s_storm.counters[p->sforced[f][1] % 5] = 0x7FFF; break; }
        int type = -1;
        for (int k = 0; k < 5 && type < 0; k++) if (s_storm.counters[k] > p->sthreshold[k]) type = k;
        if (type < 0) return;
        storm_start(type, 1, 0);
    }
    s_storm.index++;
    if (s_storm.type == 4 && (s_storm.index >= p->sseqlen[4] || p->sseq[4][s_storm.index] == -1)) {
        s_storm.type = 5;
        s_storm.index = 0;
    }
    if (s_storm.index >= p->sseqlen[s_storm.type]) { s_storm.index = -1; s_storm.sky = 4; return; }
    int v = p->sseq[s_storm.type][s_storm.index];
    if (v == 1) {
        s_storm.sky = 15 + s_storm.type;
        s_storm.lit_frames++;
        storm_light(cpu, p->scolour[s_storm.type]);
    } else if (v == -1) {
        s_storm.index = -1;
        s_storm.sky = 4;
    } else if (v == 0) {
        s_storm.sky = 4;
    }
}

/* Mixed by the voices' spu_render wrapper (tekken3_ttt1_voices.c) as the
 * TTT1 sounds are: host SFX volume, TEKKEN3_TTT1_SFX_VOLUME's boost
 * (percent, default 200), the SPU's main volume. MAME's front output of
 * these sounds is L = -R; the pack keeps L, played on both sides
 * (TEKKEN3_TTT_THUNDER_PHASE=1: the right side inverted, as MAME). */
void tekken3_arcade_stages_thunder_mix(int16_t *out, int frames, int audible, const int16_t main_volume[2], int gain) {
    static int boost = -1, phase = -1;
    if (boost < 0) {
        const char *v = getenv("TEKKEN3_TTT1_SFX_VOLUME");
        boost = v ? atoi(v) : 200;
        if (boost < 0) boost = 0;
        if (boost > 800) boost = 800;
        const char *ph = getenv("TEKKEN3_TTT_THUNDER_PHASE");
        phase = ph && *ph == '1';
    }
    if (s_pack.source != TEKKEN3_STAGE_TTT || !s_pack.storm) { tekken3_arcade_stages_thunder_stop(); return; }
    for (unsigned c = 0; c < 2; c++) {
        ThunderVoice *t = &s_thunder[c];
        if (!t->pcm) continue;
        for (int f = 0; f < frames && t->pos < t->frames; f++, t->pos++) {
            int32_t value = t->pcm[t->pos];
            value = value * gain / 100 * boost / 100;
            if (!audible) value = 0;
            for (unsigned k = 0; k < 2; k++) {
                int32_t side = k && phase ? -value : value;
                int32_t mixed = (int32_t)out[f * 2 + k] + side * main_volume[k] / 32768;
                out[f * 2 + k] = (int16_t)(mixed > 32767 ? 32767 : mixed < -32768 ? -32768 : mixed);
            }
        }
        if (t->pos >= t->frames) memset(t, 0, sizeof *t);
    }
}

/* ------------------------------------------------------------------ */
/* TTT Stages S4 (TIPS section 114): what moves on TTT's stages,        */
/* tools/arcade_stages/ttt.py being the reference: the animated textures */
/* (TttAnim), stage 3's object (TttObject3), stage 11's floor lights     */
/* (stage11_lights) and light beams at the fighters' feet               */
/* (glow_commands), stage 2's particles (TttParticles, particle_ps1).    */
/* All of it in TTT's private OT (stage_ot), behind the HUD and the     */
/* fighters (the user's rule): TTT draws the particles at their own     */
/* depth and the beams at rank 5, over the fighters.                     */
/* ------------------------------------------------------------------ */
static uint16_t rd16(const uint8_t *p) { uint16_t v; memcpy(&v, p, 2); return v; }
static int16_t rds16(const uint8_t *p) { int16_t v; memcpy(&v, p, 2); return v; }


static int s16v(int v) { return (int16_t)(uint16_t)v; }
static int tanm_rand(void) {            /* stage 7's draws, logged for the probe */
    int r = storm_rand();
    if (s_probe) fprintf(s_probe, "tr %d\n", r);
    return r;
}

/* MoveImage on the upper half: the copy made in our copy of it, then sent */
static void hivram_move(int sx, int sy, int w, int h, int dx, int dy) {
    uint16_t *v = s_pack.hivram, tmp[16 * 64];
    if (!v || w <= 0 || h <= 0 || w * h > 16 * 64 || sx < 0 || dx < 0 || sx + w > 1024 || dx + w > 1024 || sy < 512
        || dy < 512 || sy + h > 1024 || dy + h > 1024)
        return;
    for (int y = 0; y < h; y++) memcpy(&tmp[y * w], &v[(size_t)(sy - 512 + y) * 1024 + sx], 2u * w);
    for (int y = 0; y < h; y++) memcpy(&v[(size_t)(dy - 512 + y) * 1024 + dx], &tmp[y * w], 2u * w);
    psx_mod_gpu_high_vram_upload(dx, dy, w, h, tmp);
    if (s_probe) fprintf(s_probe, "tm %d %d %d %d %d %d\n", sx, sy, w, h, dx, dy);
}

/* 0x8015F6A4 (B114, TIPS section 189): stage 7's caged Panda is left out
 * when Panda takes part. TTT1 looks for Panda's models 0x5D and 0x17
 * (Kuma's kick costumes, table 0x8001110C) among the four team members and
 * the two fighters, and for True Ogre (0x14); it then loads archive 5 file
 * 12 instead of 11 (the cage's texture with an all-zero CLUT, so nothing
 * shows) and never runs the machine. Here: Kuma (ID 11) in his kick
 * costume, Panda, on either side, the fighters of the fight (Team Battle:
 * the ones on the field). True Ogre never fights on a TTT stage but 14. */
static int stage7_cage_empty(void) {
    for (unsigned p = 0; p < 2; p++)
        if (psx_mod_read_half(0x800ADD5Cu + 2 * p) == 11 && (psx_mod_read_half(0x800ADD98u + 2 * p) & 3) == 1) return 1;
    return 0;
}

/* The cage's CLUT (the machine's destination) set to zeros, as file 5:12
 * leaves it: needed when the pack stays loaded after a fight without Panda */
static void stage7_cage_clear(const uint8_t *dest) {
    int dx = rd16(dest), dy = rd16(dest + 2);
    uint16_t zero[16] = {0};
    if (!s_pack.hivram || dx < 0 || dx + 16 > 1024 || dy < 512 || dy >= 1024) return;
    memset(&s_pack.hivram[(size_t)(dy - 512) * 1024 + dx], 0, sizeof zero);
    psx_mod_gpu_high_vram_upload(dx, dy, 16, 1, zero);
    if (s_probe) fprintf(s_probe, "tz %d %d\n", dx, dy);
}

/* 0x8015F638 (each round, the stage load) */
static void tanm_reset(void) {
    s_tttanim.a98 = s_tttanim.a9a = 0xFFFF;
    s_tttanim.state = s_tttanim.count = s_tttanim.tick = 0;
    s_tttanim.frame = -1;
    s_tttanim.cage_cleared = 0;
}

/* stage 7's sequences: s16 x 26 x 7 after TANM's 4 bytes */
static int seq7(int k, int i) { return i < 26 ? rds16(s_pack.tanm + 4 + 2 * (26 * k + i)) : -1; }

static int play7(int k, int mask) {
    s_tttanim.tick = (s_tttanim.tick + 1) & 0xFFFF;
    if (s_tttanim.tick & mask) return 0;
    s_tttanim.frame = seq7(k, s_tttanim.tick >> (mask == 3 ? 2 : 3));
    return s_tttanim.frame == -1;
}

/* 0x8015EB70's switch on u16 0x80243A9E (ttt.TttAnim.stage7; state 0 falls into 1) */
static void stage7_machine(void) {
    int st = s_tttanim.state;
    if (st == 0) {
        s_tttanim.count = tanm_rand() & 0x1F;
        s_tttanim.state = 1; s_tttanim.frame = seq7(0, 0);
    }
    if (st == 0 || st == 1) {
        s_tttanim.count = (s_tttanim.count - 1) & 0xFFFF;
        if (s_tttanim.count && !(s_tttanim.count & 0x8000)) return;
        int k = tanm_rand() % 3;
        if (k == 1) { s_tttanim.state = 3; s_tttanim.frame = seq7(1, 0); }
        else if (k == 0) { s_tttanim.count = (tanm_rand() & 3) + 5; s_tttanim.state = 2; s_tttanim.frame = seq7(0, 0); }
        else { s_tttanim.state = 6; s_tttanim.frame = seq7(5, 0); }
        s_tttanim.tick = 0;
    } else if (st == 2) {
        if (play7(0, 3)) {
            s_tttanim.count = (s_tttanim.count - 1) & 0xFFFF;
            if (!s_tttanim.count || (s_tttanim.count & 0x8000)) {
                s_tttanim.count = tanm_rand() & 0x1F; s_tttanim.state = 1; s_tttanim.frame = seq7(0, 0);
            } else { s_tttanim.tick = 0; s_tttanim.frame = seq7(0, 0); }
        }
    } else if (st == 3) {
        if (play7(1, 7)) { s_tttanim.count = (tanm_rand() & 0x7F) + 0x78; s_tttanim.state = 4; s_tttanim.frame = seq7(2, 0); }
    } else if (st == 4) {
        s_tttanim.count = (s_tttanim.count - 1) & 0xFFFF;
        if (!s_tttanim.count || (s_tttanim.count & 0x8000)) { s_tttanim.tick = 0; s_tttanim.state = 5; s_tttanim.frame = seq7(2, 0); }
    } else if (st == 5) {
        if (play7(2, 7)) { s_tttanim.count = (tanm_rand() & 3) + 5; s_tttanim.tick = 0; s_tttanim.state = 2; s_tttanim.frame = seq7(0, 0); }
    } else if (st == 6) {
        if (play7(5, 7)) { s_tttanim.count = (tanm_rand() & 3) + 1; s_tttanim.tick = 0; s_tttanim.state = 7; s_tttanim.frame = seq7(3, 0); }
    } else if (st == 7 || st == 8) {
        int k = st == 7 ? 3 : 4;
        if (play7(k, 7)) {
            s_tttanim.count = (s_tttanim.count - 1) & 0xFFFF;
            if (!s_tttanim.count || (s_tttanim.count & 0x8000)) {
                if ((tanm_rand() & 3) == 0) {
                    s_tttanim.count = (tanm_rand() & 3) + 1;
                    if (st == 7) { s_tttanim.state = 8; s_tttanim.frame = seq7(4, 0); }
                    else { s_tttanim.state = 7; s_tttanim.frame = seq7(3, 0); }
                } else { s_tttanim.state = 9; s_tttanim.frame = seq7(6, 0); }
                s_tttanim.tick = 0;
            } else { s_tttanim.tick = 0; s_tttanim.frame = seq7(k, 0); }
        }
    } else if (st == 9) {
        if (play7(6, 7)) { s_tttanim.count = (tanm_rand() & 3) + 5; s_tttanim.tick = 0; s_tttanim.state = 2; s_tttanim.frame = seq7(0, 0); }
    }
}

/* 0x8015EB70, one frame (ttt.TttAnim.step): the copies of the frame */
static void tanm_step(void) {
    const uint8_t *t = s_pack.tanm;
    if (!t) return;
    unsigned old = s_tttanim.a9a;
    s_tttanim.a98 = (s_tttanim.a98 + 1) & 0xFFFF;
    s_tttanim.a9a = (s_tttanim.a9a + 1) & 0xFFFF;
    int empty_cage = s_pack.stage == 7 && stage7_cage_empty();
    if (s_probe) fprintf(s_probe, "ttanim %u %d %u %u %d %d %d %d %d\n", psx_mod_read_word(0x800A08F0u), s_pack.stage,
                         s_tttanim.a98, s_tttanim.a9a, s_tttanim.state, s_tttanim.count, s_tttanim.tick, s_tttanim.frame,
                         !empty_cage);
    const uint8_t *q = t + 4;
    switch (s_pack.stage) {
    case 3: {
        if (s_tttanim.a98 & 3) return;
        int i = s_tttanim.a98 >> 2 & 0x3F;
        if (i > 0x3E) { i = 0; s_tttanim.a98 = 0; }
        int k = s16v((int)s_tttanim.a98) >> 2;
        static const int dst[3][2] = {{0x10, 0x280}, {0x10, 0x2C0}, {0x50, 0x300}};
        int src[3] = {i, (k + 0x15) & 0x3F, (k + 0x2A) & 0x3F};
        for (int j = 0; j < 3; j++) hivram_move(rd16(q + 4 * src[j]), rd16(q + 4 * src[j] + 2), 16, 64, dst[j][0], dst[j][1]);
        break;
    }
    case 6: {
        const uint8_t *even = q, *odd = q + 128, *sw = q + 512, *more = q + 612;
        uint32_t nm; memcpy(&nm, q + 608, 4);
        const uint8_t *clut = more + 8 * nm, *dest = clut + 4 * nm;
        if ((s16v((int)s_tttanim.a98) >> 1) > 0x5F) s_tttanim.a98 = 0;
        if (!(s_tttanim.a98 & 1)) {
            int e = (int)(((old + 1) * 2 & 0x7C) >> 2);
            hivram_move(rd16(even + 4 * e), rd16(even + 4 * e + 2), 8, 64, 0x58, 0x2C0);
        } else {
            int i = s16v((int)s_tttanim.a98) >> 1;
            if (i < 0 || i >= 96) break;
            hivram_move(rd16(odd + 4 * i), rd16(odd + 4 * i + 2), 16, 32, 0x90, 0x230);
            int b = sw[i];
            if (b && (uint32_t)b <= nm) {
                const uint8_t *m = more + 8 * (b - 1);
                hivram_move(rd16(m), rd16(m + 2), 16, 64, 0, 0x240);
                hivram_move(rd16(m + 4), rd16(m + 6), 16, 64, 0, 0x200);
                hivram_move(rd16(clut + 4 * (b - 1)), rd16(clut + 4 * (b - 1) + 2), 16, 1, rd16(dest), rd16(dest + 2));
            }
        }
        break;
    }
    case 7: {
        if (ttt_night()) break;         /* 0x8015F6A4: not with True Ogre (B124) */
        if (empty_cage) {
            if (!s_tttanim.cage_cleared) stage7_cage_clear(q + 364 + 8 * 53);
            s_tttanim.cage_cleared = 1;
            s_tttanim.state = 0;                     /* once she leaves, the machine starts over */
            s_tttanim.frame = -1;
            break;
        }
        s_tttanim.cage_cleared = 0;
        stage7_machine();
        if (s_tttanim.frame != -1 && s_tttanim.frame >= 0 && s_tttanim.frame < 53) {
            const uint8_t *f = q + 364 + 8 * s_tttanim.frame, *dest = q + 364 + 8 * 53;
            hivram_move(rd16(f), rd16(f + 2), 16, 64, 0x20, 0x3C0);
            hivram_move(rd16(f + 4), rd16(f + 6), 16, 1, rd16(dest), rd16(dest + 2));
        }
        s_tttanim.frame = -1;
        break;
    }
    case 14: {
        int b = q[s_tttanim.a98 >> 2 & 0x3F] & 0x1F;
        const uint8_t *src = q + 64 + 4 * b, *dest = q + 64 + 128;
        hivram_move(rd16(src), rd16(src + 2), 16, 1, rd16(dest), rd16(dest + 2));
        break;
    }
    default:
        break;
    }
}

/* 0x8016213C / 0x80162198 (ttt.TttObject3) */
static void object3_reset(void) { s_tttanim.yaw = 0x555; s_tttanim.c = 0x5550; s_tttanim.k = 0; }
static void object3_step(void) {
    s_tttanim.yaw = s16v(s_tttanim.c >> 4);
    s_tttanim.c -= 0x40;
    s_tttanim.k += 0x40;
    if (s_tttanim.k > 0x2AA9) { s_tttanim.c = 0x5550 - s_tttanim.k % 0x2AAA; s_tttanim.k = 0; }
}

/* ---- stage 2's particles ---- */
#define PARTICLES 0x50
typedef struct { int32_t x, y, z, vx, vy, vz; uint8_t live, born, start; } Particle;
static Particle s_particles[PARTICLES];
static unsigned s_particle_timer;

static void particles_spawn(int n, int round_start) {
    for (int i = 0; i < PARTICLES && n > 0; i++)
        if (!s_particles[i].live) {
            memset(&s_particles[i], 0, sizeof s_particles[i]);
            s_particles[i].live = 1; s_particles[i].start = (uint8_t)round_start;
            n--;
        }
}

static unsigned particles_live(void) {
    unsigned n = 0;
    for (int i = 0; i < PARTICLES; i++) n += s_particles[i].live;
    return n;
}

/* 0x80159ED0: born in front of the camera, in the view's width x 1.1 (the
 * PS1 screen's, its 16:9 margins included), 0xA00 + rand & 0x1FFF away;
 * at the round start y scaled by rand / 0x8000 (they fill the air) */
static void particle_born(Particle *p, const Screen *s) {
    const uint8_t *d = s_pack.part;
    const int16_t *sine = s_pack.tsine;
    int pitch = (int)psx_mod_read_word(CAMERA), yaw = (int)psx_mod_read_word(CAMERA + 4);
    int half_w = (s->ofx > SCREEN_W - s->ofx ? s->ofx : SCREEN_W - s->ofx) + s->margin;
    int hw = (int)lround(atan2((double)half_w, (double)(s->h > 0 ? s->h : 1)) * 2048.0 / 3.14159265358979323846);
    int w = s16v(2 * hw) * 11 / 10;
    int r = storm_rand();
    int ax = (pitch + ((2 * w / 3) >> 1)) & 0xFFF;
    int ay = (s16v((w * r) >> 15) - s16v(w >> 1) - yaw) & 0xFFF;
    int dist = (storm_rand() & rd16(d + 50)) + rd16(d + 48);
    int sx = sine[ax], cx = sine[ax + 0x400], sy = sine[ay], cy = sine[ay + 0x400];
    p->x = (int32_t)(((int64_t)((sy * cx) >> 12) * dist) >> 12) + (int32_t)psx_mod_read_word(CAMERA + 0x14);
    p->y = (int32_t)(((int64_t)-sx * dist) >> 12) + (int32_t)psx_mod_read_word(CAMERA + 0x18);
    p->z = (int32_t)(((int64_t)((cy * cx) >> 12) * dist) >> 12) + (int32_t)psx_mod_read_word(CAMERA + 0x1C);
    if (p->start) p->y = (int32_t)(((int64_t)p->y * (storm_rand() & 0xFFFF)) >> 15);
    p->vx = storm_rand() & rd16(d + 52);
    p->vz = -(storm_rand() & rd16(d + 56));
    p->vy = rd16(d + 54);
    storm_rand();
    p->born = 1;
}

/* 0x80155D34 for stage 2, once a stage frame (not in the pause): 15 at the
 * round start, one every `every` frames while fewer than `most` live, born,
 * moved, freed under the floor */
static void particles_step(const Screen *s) {
    const uint8_t *d = s_pack.part;
    if (!d) return;
    if (++s_particle_timer > (unsigned)rd16(d + 42) - 1u) {
        s_particle_timer = 0;
        if (particles_live() < rd16(d + 44)) particles_spawn(1, 0);
    }
    for (int i = 0; i < PARTICLES; i++) {
        Particle *p = &s_particles[i];
        if (!p->live) continue;
        if (!p->born) particle_born(p, s);
        p->x += p->vx; p->y += p->vy; p->z += p->vz;
        if (p->y > 0) p->live = 0;
    }
}

/* The FT4 of each live particle (ttt.particle_ps1): its centre through the
 * PS1 world matrix, the 30-unit quad added unrotated, scaled by the
 * matrix's row norms; drawn when SZ(vertex 0) >> 5 >= near, far ones first
 * (TTT sorts them at main rank SZ(vertex 1) >> 5) */
static void particles_draw(const Gte *world, uint32_t ot) {
    const uint8_t *d = s_pack.part;
    if (!d) return;
    int n[3];
    for (int k = 0; k < 3; k++)
        n[k] = (int)sqrt((double)world->r[k][0] * world->r[k][0] + (double)world->r[k][1] * world->r[k][1]
                         + (double)world->r[k][2] * world->r[k][2]);
    uint16_t tpage = rd16(d), clut = rd16(d + 4);
    unsigned u = d[2], v = d[3], near = rd16(d + 46);
    struct { int rank, i; uint32_t q; } order[PARTICLES];
    int count = 0;
    int tlog = s_probe && psx_mod_read_word(0x800A08F0u) % 15 == 0;
    if (tlog) {
        fprintf(s_probe, "ttpart %u", psx_mod_read_word(0x800A08F0u));
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) fprintf(s_probe, " %d", world->r[i][j]);
        fprintf(s_probe, " %d %d %d %d %d %u\n", world->t[0], world->t[1], world->t[2], world->ofx, world->ofy, world->h);
    }
    for (int i = 0; i < PARTICLES; i++) {
        const Particle *p = &s_particles[i];
        if (!p->live) continue;
        int64_t c[3];
        for (int k = 0; k < 3; k++)
            c[k] = (((int64_t)world->r[k][0] * p->x + (int64_t)world->r[k][1] * p->y + (int64_t)world->r[k][2] * p->z) >> 12)
                 + world->t[k];
        int sx[4], sy[4], sz[4];
        for (int j = 0; j < 4; j++) {
            Gte g = {{{0}}, {0}, world->ofx, world->ofy, world->h};
            for (int k = 0; k < 3; k++) g.t[k] = (int32_t)(c[k] + (((int64_t)rds16(d + 8 + 8 * j + 2 * k) * n[k]) >> 12));
            rtps(&g, 0, 0, 0, &sx[j], &sy[j], &sz[j], NULL, NULL);
        }
        int drawn = (sz[0] >> 5) >= (int)near;
        if (tlog) fprintf(s_probe, "pp %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d\n", p->x, p->y, p->z, p->vx, p->vy,
                          p->vz, sx[0], sy[0], sx[1], sy[1], sx[2], sy[2], sx[3], sy[3], drawn ? sz[1] >> 5 : -1);
        if (!drawn) continue;
        uint32_t q = alloc_words(10);
        if (!q) break;
        psx_mod_write_word(q + 4, 0x2E808080u);
        psx_mod_write_word(q + 8, xy(sx[0], sy[0]));
        psx_mod_write_word(q + 12, (uint32_t)clut << 16 | v << 8 | u);
        psx_mod_write_word(q + 16, xy(sx[1], sy[1]));
        psx_mod_write_word(q + 20, (uint32_t)tpage << 16 | v << 8 | (u + 15));
        psx_mod_write_word(q + 24, xy(sx[2], sy[2]));
        psx_mod_write_word(q + 28, (v + 15) << 8 | u);
        psx_mod_write_word(q + 32, xy(sx[3], sy[3]));
        psx_mod_write_word(q + 36, (v + 15) << 8 | (u + 15));
        int r = sz[1] >> 5, at = count;
        while (at > 0 && order[at - 1].rank > r) { order[at] = order[at - 1]; at--; }   /* stable, by rank */
        order[at].rank = r; order[at].i = i; order[at].q = q;
        count++;
    }
    for (int k = 0; k < count; k++) add_prim(ot, order[k].q, 9);   /* the farthest linked last: drawn first */
    s_stat_objects += (unsigned)count;
}

/* ---- stage 11's light beams at the fighters' feet ---- */
#define ACTOR(j) (0x800A9228u + 0x188Cu * (unsigned)(j))
#define BONE_T(j, b) (ACTOR(j) + 0x8F4u + 68u * (unsigned)(b) + 0x14u)
typedef struct { int timer, step, intensity, sign, phase; } Beam;
static Beam s_beam[2][2];
static int s_beam_angle, s_beam_dir[3];
static int s_beam_bones[2] = {-1, -1};

/* TTT's body parts 14 and 17 (the ankles) are the PS1 skeleton's... (see
 * TEKKEN3_TTT_BEAM_BONES; measured in tools/arcade_stages/stage_check.py) */
static void beam_bones(void) {
    if (s_beam_bones[0] >= 0) return;
    const char *e = getenv("TEKKEN3_TTT_BEAM_BONES");
    s_beam_bones[0] = 14; s_beam_bones[1] = 17;
    if (e && *e) sscanf(e, "%d,%d", &s_beam_bones[0], &s_beam_bones[1]);
}

/* ---- B126: stage 11's wind on the accessory bones ---- */
/* 0x801631FC gives the wind the beams' direction (x and z: the signs of the
 * round's angle's sine and cosine); 0x801649A4, once a frame of the fight,
 * blows it in gusts of 16 frames: b = 0..255..0 (+32 a frame), the vector
 * (x b, 256 - b, z b) normalized to 4096 (MAME: 0x80243B90 / 94). TTT's
 * accessory solver (0x80163B68) pulls a bone in the air sideways by its x and
 * z times the bone's gravity / 256; nothing on the other stages, where T3's
 * (0x80037CBC) pulls by gravity / 16 on every arena. */
static int s_wind_sign[2], s_wind_phase, s_wind[2];
static uint32_t s_wind_frame;

static void wind_reset(int dx, int dz) {
    s_wind_sign[0] = dx; s_wind_sign[1] = dz;
    s_wind_phase = 0;
    s_wind[0] = s_wind[1] = 0;
}

static void wind_step(void) {
    s_wind_phase += 0x20;
    int b = s_wind_phase & 0x100 ? ~s_wind_phase & 0xFF : s_wind_phase & 0xFF;
    double v[3] = {s_wind_sign[0] * b, 0x100 - b, s_wind_sign[1] * b};
    double l = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    s_wind[0] = (int)lround(v[0] * 4096 / l);
    s_wind[1] = (int)lround(v[2] * 4096 / l);
}

int tekken3_ttt_stage_wind(int wind[2]) {
    static int off = -1;            /* TEKKEN3_TTT_WIND=0: no wind, for comparison */
    if (off < 0) { const char *e = getenv("TEKKEN3_TTT_WIND"); off = e && !strcmp(e, "0"); }
    if (off || s_pack.source != TEKKEN3_STAGE_TTT || !s_pack.glow || psx_mod_read_word(0x800A08F0u) - s_wind_frame > 2) return 0;
    wind[0] = s_wind[0]; wind[1] = s_wind[1];
    return 1;
}

/* T3's solver: its pull, built at 0x80037FEC (x = z = gravity >> 4, y =
 * (256 - gravity) * 16, the bone's block in s3), goes to ApplyRotMatrix
 * (0x80081FD8, a0) back to 0x80038014; on stage 11, TTT's x and z */
extern void __real_func_80081FD8(CPUState *cpu);
void __wrap_func_80081FD8(CPUState *cpu) {
    int wind[2];
    if ((cpu->pc == 0 || cpu->pc == 0x80081FD8u) && cpu->gpr[31] == 0x80038014u && tekken3_ttt_stage_wind(wind)) {
        int g = (int16_t)psx_mod_read_half(cpu->gpr[19] + 10);
        psx_mod_write_half(cpu->gpr[4], (uint16_t)(wind[0] * g / 256));
        psx_mod_write_half(cpu->gpr[4] + 4, (uint16_t)(wind[1] * g / 256));
    }
    __real_func_80081FD8(cpu);
}

/* 0x801631FC at each round: one direction for the round, each part's walk */
static void beams_reset(void) {
    s_beam_angle = storm_rand() & 0xE00;
    const int16_t *sine = s_pack.tsine;
    int sn = sine[s_beam_angle & 0xFFF], cs = sine[(s_beam_angle & 0xFFF) + 0x400];
    int dx = sn > 0 ? 1 : sn < 0 ? -1 : 0, dz = cs > 0 ? 1 : cs < 0 ? -1 : 0;
    double l = sqrt((double)(dx * dx + dz * dz));
    s_beam_dir[0] = l > 0 ? (int)(dx * 4096 / l) : 0; s_beam_dir[1] = 0; s_beam_dir[2] = l > 0 ? (int)(dz * 4096 / l) : 0;
    wind_reset(dx, dz);
    s_beam[0][0].phase = -(storm_rand() & 0x1FE);
    s_beam[0][1].phase = -(storm_rand() & 0x1FE);
    s_beam[1][0].phase = s_beam[1][1].phase = 0;
    for (int f = 0; f < 2; f++)
        for (int k = 0; k < 2; k++) {
            s_beam[f][k].sign = 1;
            s_beam[f][k].timer = storm_rand() & 0x3F;
            s_beam[f][k].intensity = 0;
            s_beam[f][k].step = (storm_rand() & 0x3F) + 1;
        }
}

/* 0x80163554, both fighters (ttt.glow_commands for the packets) */
static void beams_draw(const Gte *world, uint32_t ot) {
    const uint8_t *d = s_pack.glow;
    if (!d) return;
    beam_bones();
    int paused = psx_mod_read_word(PAUSED) != 0;
    int32_t ry[3][3];
    int16_t ang[3] = {0, (int16_t)((s_beam_angle + 0x800) & 0xFFFF), 0};
    if (s_pack.rot) rot_matrix(ang, 0, ry);
    else return;
    int tlog = s_probe && psx_mod_read_word(0x800A08F0u) % 15 == 0;
    for (int f = 0; f < 2; f++) {
        int32_t base[3];
        for (int k = 0; k < 3; k++) base[k] = (int32_t)psx_mod_read_word(BONE_T(f, 0) + 4 * k);
        double cv[3] = {(int32_t)psx_mod_read_word(CAMERA + 0x14) - base[0], (int32_t)psx_mod_read_word(CAMERA + 0x18) - base[1],
                        (int32_t)psx_mod_read_word(CAMERA + 0x1C) - base[2]};
        double l = sqrt(cv[0] * cv[0] + cv[1] * cv[1] + cv[2] * cv[2]);
        int dot = l > 0 ? (int)((s_beam_dir[0] * cv[0] + s_beam_dir[2] * cv[2]) / l) : 0;
        if (tlog) {         /* the skeleton's heights, for TEKKEN3_TTT_BEAM_BONES */
            fprintf(s_probe, "bones %u %d", psx_mod_read_word(0x800A08F0u), f);
            for (int k = 0; k < 24; k++) fprintf(s_probe, " %d", (int32_t)psx_mod_read_word(BONE_T(f, k) + 4));
            fprintf(s_probe, "\n");
        }
        for (int part = 0; part < 2; part++) {
            Beam *b = &s_beam[f][part];
            if (!paused) b->phase = s16v(b->phase + 2);
            if (b->phase < 0) continue;
            if (b->phase > 0x1F) {
                if (abs(dot) > 0xF80) break;             /* along the beams: TTT returns */
                b->phase = 0;
            }
            int32_t pt[3];
            for (int k = 0; k < 3; k++) pt[k] = (int32_t)psx_mod_read_word(BONE_T(f, s_beam_bones[part]) + 4 * k);
            if (pt[1] <= -0x101) continue;
            int c = (uint8_t)(-(b->phase & 0x1F));
            int t0 = b->timer;
            b->timer = s16v(b->timer - 1);
            if (t0 < 1) { b->timer = storm_rand() & 0x3F; b->sign = -b->sign; b->step = (storm_rand() & 0x3F) + 1; }
            if (!paused) b->intensity = s16v(b->intensity + b->step * b->sign);
            if (b->intensity < 0) b->intensity = 0;
            if (b->intensity > 0x100) b->intensity = 0x100;
            Gte g = *world;
            memcpy(g.r, ry, sizeof ry);
            mul_matrix2(world->r, g.r);
            int32_t off[3];
            apply_matrix(world->r, pt[0], 0, pt[2], off);
            for (int k = 0; k < 3; k++) g.t[k] = world->t[k] + off[k];
            int sx[14], sy[14], sz[14];
            for (int i = 0; i < 14; i++) rtps(&g, rds16(d + 8 * i), rds16(d + 8 * i + 2), rds16(d + 8 * i + 4), &sx[i], &sy[i], &sz[i], NULL, NULL);
            if (tlog) {
                fprintf(s_probe, "beam %u %d %d", psx_mod_read_word(0x800A08F0u), f, part);
                for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) fprintf(s_probe, " %d", g.r[i][j]);
                fprintf(s_probe, " %d %d %d %d %d %u %d %d %d\n", g.t[0], g.t[1], g.t[2], g.ofx, g.ofy, g.h, b->phase, b->intensity,
                        pt[1]);
            }
            const uint8_t *idx = d + 112, *col = d + 136, *uvs = d + 232;
            uint16_t tpage = rd16(d + 236), clut = rd16(d + 238);
            int behind = 0;
            for (int i = 0; i < 14; i++) if (sz[i] < 16) behind = 1;
            if (behind) continue;
            for (int i = 0; i < 6; i++) {
                int j = i <= 2 ? i : i - 3;
                unsigned u0 = (unsigned)(c + uvs[j] - 0x40) & 0xFF, u1 = (unsigned)(c + uvs[j + 1] - 0x40) & 0xFF;
                const uint8_t *cc = col + 16 * i, *vi = idx + 4 * i;
                uint32_t rgb[4];
                for (int k = 0; k < 2; k++) rgb[k] = (uint32_t)cc[4 * k] | (uint32_t)cc[4 * k + 1] << 8 | (uint32_t)cc[4 * k + 2] << 16;
                for (int k = 2; k < 4; k++) {
                    rgb[k] = 0;
                    for (int m = 0; m < 3; m++) {
                        int v = cc[4 * k + m] * b->intensity;
                        rgb[k] |= (uint32_t)(((v < 0 ? v + 0xFF : v) >> 8) & 0xFF) << (8 * m);
                    }
                }
                uint32_t q = alloc_words(13);
                if (!q) return;
                static const unsigned vv[4] = {0, 0, 0x14, 0x14};
                for (int k = 0; k < 4; k++) {
                    unsigned uu = (k & 1) ? u1 : u0;
                    psx_mod_write_word(q + 4 + 12 * k, k == 0 ? 0x3E000000u | rgb[0] : rgb[k]);
                    psx_mod_write_word(q + 8 + 12 * k, xy(sx[vi[k]], sy[vi[k]]));
                    psx_mod_write_word(q + 12 + 12 * k, vv[k] << 8 | uu | (k == 0 ? (uint32_t)clut << 16 : k == 1 ? (uint32_t)tpage << 16 : 0));
                }
                add_prim(ot, q, 12);
                s_stat_objects++;
                if (tlog) {
                    fprintf(s_probe, "bq");
                    for (int k = 0; k < 4; k++) fprintf(s_probe, " %d %d %06X %u", sx[vi[k]], sy[vi[k]], rgb[k], k & 1 ? u1 : u0);
                    fprintf(s_probe, "\n");
                }
            }
        }
    }
}

/* ---- stage 3's object (0x801600C0 / 0x80160210 / 0x8015E4E0) ---- */
static void ttt_objects(const Gte *tile, const Screen *s) {
    const Pack *p = &s_pack;
    static int sx[256], sy[256], sz[256];
    static int32_t px[256], py[256];   /* emit_prim's precise positions: unused here (no PGXP on TTT Stages) */
    for (unsigned c = 0; c < p->nlayout; c++) {
        const Layout *l = &p->layout[c];
        if (l->pad2 || p->stage != 3) continue;          /* stage 11's helicopter: the rankings only */
        const Model *m = &p->models[l->model];
        unsigned size = l->size > 1 && l->size <= 128 ? l->size : 128;
        Gte g = *tile;
        int16_t ang[3] = {0, (int16_t)s_tttanim.yaw, 0};
        int32_t r[3][3], v[3];
        rot_matrix(ang, 0, r);
        memcpy(g.r, r, sizeof r);
        mul_matrix2(tile->r, g.r);
        apply_matrix(tile->r, 0, -0x16B, -0x1022, v);
        for (int i = 0; i < 3; i++) g.t[i] = tile->t[i] + v[i];
        for (unsigned i = 0; i < m->nv; i++) rtps(&g, m->v[i].x, m->v[i].y, m->v[i].z, &sx[i], &sy[i], &sz[i], &px[i], &py[i]);
        /* TTT's frame of vertex 0 (x -256..768, y >= -180 of its 512 x 240):
         * on the PS1 screen, its 16:9 margins */
        int framed = m->nv && sy[0] >= -360 && sx[0] >= -SCREEN_W - s->margin && sx[0] <= 2 * SCREEN_W + s->margin;
        int tlog = s_probe && psx_mod_read_word(0x800A08F0u) % 15 == 0;
        if (tlog) {
            fprintf(s_probe, "tttobj %u %d %d %d %d", psx_mod_read_word(0x800A08F0u), s_tttanim.c, s_tttanim.k, s_tttanim.yaw, framed);
            for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) fprintf(s_probe, " %d", g.r[i][j]);
            fprintf(s_probe, " %d %d %d %d %d %u %d\n", g.t[0], g.t[1], g.t[2], g.ofx, g.ofy, g.h, s->margin);
        }
        if (!framed) continue;
        uint32_t ot = alloc_words(size);
        if (!ot) return;
        for (unsigned i = 0; i < size; i++) psx_mod_write_word(ot + 4 * i, i ? (ot + 4 * (i - 1)) & 0xFFFFFFu : 0xFFFFFFu);
        for (unsigned k = 0; k < m->np; k++) {
            const Prim *pr = &m->p[k];
            if (pr->kind > 6) continue;
            unsigned nvp = PRIM_VERTS[pr->kind], bad = 0;
            for (unsigned q = 0; q < nvp; q++) bad |= pr->idx[q] >= m->nv;
            if (bad) continue;
            unsigned a = pr->idx[0], b = pr->idx[1], cc = pr->idx[nvp == 4 ? 3 : 2];
            if (nclip(sx[a], sy[a], sx[b], sy[b], sx[cc], sy[cc]) <= 0) continue;
            int z = 0;
            for (unsigned q = 0; q < nvp; q++) z += sz[pr->idx[q]] >> 5;
            unsigned slot = (unsigned)((z * (nvp == 4 ? 0x100 : 0x155)) >> 12);
            if (slot == 0 || slot >= size) continue;          /* lost with slot 0, as TTT */
            int behind = 0;
            for (unsigned q = 0; q < nvp; q++) if (sz[pr->idx[q]] < 16) behind = 1;
            if (tlog) {
                fprintf(s_probe, "op %u %d %u", slot, behind, pr->code);
                for (unsigned q = 0; q < nvp; q++) fprintf(s_probe, " %d %d", sx[pr->idx[q]], sy[pr->idx[q]]);
                fprintf(s_probe, "\n");
            }
            if (behind) { s_stat_obj_behind++; continue; }
            s_stat_objects += emit_prim(ot + 4 * slot, pr, sx, sy, px, py, sz);
        }
        uint32_t r1022 = stage_ot(l->rank);
        psx_mod_write_word(ot, (psx_mod_read_word(ot) & 0xFF000000u) | (psx_mod_read_word(r1022) & 0xFFFFFFu));
        psx_mod_write_word(r1022, (psx_mod_read_word(r1022) & 0xFF000000u) | ((ot + 4 * (size - 1)) & 0xFFFFFFu));
    }
}

/* 0x8015EB70 / 0x8016206C / 0x80155D34's per-frame steps, and their resets
 * at each round (as T3 arcade's, § 94: a round decided, then not) */
static void ttt_anim_reset(void) {
    tanm_reset();
    object3_reset();
    memset(s_particles, 0, sizeof s_particles);
    s_particle_timer = 0;
    s_tttanim.was_over = 0;
    if (s_pack.part) particles_spawn(rd16(s_pack.part + 40), 1);
    if (s_pack.glow) beams_reset();
}

static void ttt_anim_tick(const Screen *s) {
    int over = round_over();
    if (s_tttanim.was_over && !over) {               /* the next round */
        tanm_reset();
        object3_reset();
        memset(s_particles, 0, sizeof s_particles);
        s_particle_timer = 0;
        if (s_pack.part) particles_spawn(rd16(s_pack.part + 40), 1);
        if (s_pack.glow) beams_reset();
    }
    s_tttanim.was_over = over;
    s_wind_frame = psx_mod_read_word(0x800A08F0u);
    if (psx_mod_read_word(PAUSED)) return;
    if (s_pack.glow) wind_step();
    tanm_step();
    if (s_pack.stage == 3 && s_pack.nlayout) object3_step();
    particles_step(s);
}

/* The PS1 world matrix (0x800ADF70, the floor's: world units) and screen */
static void world_gte(const CPUState *cpu, Gte *w) {
    Screen s;
    read_gte_screen(cpu, &s, w);
    for (int i = 0; i < 3; i++)
        for (int k = 0; k < 3; k++) w->r[i][k] = (int16_t)psx_mod_read_half(WORLD + 6 * i + 2 * k);
    for (int i = 0; i < 3; i++) w->t[i] = (int32_t)psx_mod_read_word(WORLD + 0x14 + 4 * i);
}

/* stage 11's floor lights: the CLUT of map cell (row, column) of rows 0
 * and 2 (mod 4), ttt.stage11_lights */
static uint32_t ttt_floor_light(int row, int col, uint32_t clut) {
    const uint32_t *t = s_pack.lite;
    if (!t || (row % 4 != 0 && row % 4 != 2)) return clut;
    int second = row % 4 == 0 ? (col & 3) == 0 : col % 4 == 2;
    return t[2 * s_tttanim.light + second] >> 16;
}

/* ------------------------------------------------------------------ */
/* the cinematics' entries (src/tekken3_arcade_stages.h)              */
/* ------------------------------------------------------------------ */
static signed char s_ttt_pack_ok[15];   /* 0 unknown, 1 there, -1 missing or bad */

static int ttt_stage_available(int stage) {
    if (!s_on || !s_ttt_on || !psx_mod_gpu_high_vram_ready() || stage < 0 || stage > 14) return 0;
    if (s_pack.source == TEKKEN3_STAGE_TTT && s_pack.stage == stage) return 1;
    if (!s_ttt_pack_ok[stage]) {
        char path[1024];
        long size = 0;
        uint8_t *b = pack_read(TEKKEN3_STAGE_TTT, stage, &size, path, sizeof path);
        s_ttt_pack_ok[stage] = b ? 1 : -1;
        free(b);
    }
    return s_ttt_pack_ok[stage] > 0;
}

int tekken3_ttt_stage_force(int stage) {
    if (stage < 0) {
        if (s_force >= 0 && log_on()) { fprintf(stdout, "arcade stages: TTT stage %d no longer forced\n", s_force); fflush(stdout); }
        s_force = -1;
        s_floor_at = 0;
        return 1;
    }
    if (!ttt_stage_available(stage)) {
        s_force = -1;
        return 0;
    }
    if (s_force != stage) {
        s_force = stage;
        s_tried_ttt = -1;
        fprintf(stdout, "arcade stages: TTT stage %d forced\n", stage);
        fflush(stdout);
    }
    return 1;
}

void tekken3_ttt_floor_centre(int on, int x, int z, int half) {
    s_floor_at = on;
    s_floor_xz[0] = x;
    s_floor_xz[1] = z;
    s_floor_half = half > 0 ? half : 0;
}

int tekken3_ttt_stage_flash(int type) {
    if (type & ~(0xFF | TEKKEN3_TTT_FLASH_QUIET) || (type & 0xFF) > 5) return 0;
    int stage = s_force >= 0 ? s_force : s_pack.source == TEKKEN3_STAGE_TTT ? s_pack.stage : -1;
    if (stage != 4 || !ttt_stage_available(4)) return 0;
    if (s_pack.source == TEKKEN3_STAGE_TTT && s_pack.stage == 4 && !s_pack.storm) return 0;
    s_storm.pending = type;
    return 1;
}

/* ------------------------------------------------------------------ */
/* B76: the light on the fighters of a TTT stage                      */
/* ------------------------------------------------------------------ */
/* Tekken 3 lights its fighters from an entry of 28 bytes per arena,
 * 0x80096C78 + 28 * arena: 0x80039960 at each round set-up (light matrix row
 * 0 from the angles at +12 / +14, colour matrix 0x8009E5C0 column 0 from the
 * colour at +8..+10 and column 2 from its half, SetColorMatrix), 0x8003A164
 * for each fighter every frame (SetBackColor from +0), and the shadows and
 * two colours at the stage load (+4, +16, +20 / +22: 0x80039DDC, 0x80039E44,
 * 0x80039E74, 0x80039E9C). TTT does the same from its own table of 24-byte
 * entries, the same fields (0x8010C18C, 0x8010CCA8: tools/arcade_stages/
 * ttt.py, fighter_light), the pack's LGHT section. While a TTT stage is the
 * stage of the scene, its entry stands in the arena's first 24 bytes (put
 * back after), so every one of those readers takes TTT's; and when the stage
 * changes after the round set-up (a cinematic's force) the light 0x80039960
 * computed is computed again here (light matrix row 0, colour matrix columns
 * 0 and 2; column 1 is the hit and storm light's) and given to the GTE at the
 * next stage frame. */
#define LIGHT_TABLE   0x80096C78u
#define LIGHT_ENTRY   28u
#define LIGHT_ARENAS  18
#define LIGHT_MATRIX  0x8009E5A0u
#define COLOUR_MATRIX 0x8009E5C0u
#define LIGHT_BYTES   24

static uint8_t s_ttt_light[15][LIGHT_BYTES];
static signed char s_ttt_light_ok[15];  /* 0 unknown, 1 read, -1 no LGHT (a pack before version 3) */
static int s_light_arena = -1, s_light_stage = -1;    /* the entry holding a TTT stage's */
static uint8_t s_light_saved[LIGHT_BYTES];            /* its own bytes */
static int s_light_key = -1;            /* the light last computed: stage << 5 | arena, -1 the arena's own */
static int s_light_push;                /* the colour matrix and back colour to give the GTE */
static uint16_t s_light_back;

static const uint8_t *ttt_light_of(int stage) {
    if (!ttt_stage_available(stage)) return NULL;
    if (!s_ttt_light_ok[stage]) {
        const uint8_t *l = NULL;
        uint8_t *b = NULL;
        if (s_pack.source == TEKKEN3_STAGE_TTT && s_pack.stage == stage) l = section(s_pack.file, "LGHT");
        else {
            char path[1024];
            long size = 0;
            b = pack_read(TEKKEN3_STAGE_TTT, stage, &size, path, sizeof path);
            l = b ? section(b, "LGHT") : NULL;
        }
        if (l) memcpy(s_ttt_light[stage], l, LIGHT_BYTES);
        s_ttt_light_ok[stage] = l ? 1 : -1;
        free(b);
    }
    return s_ttt_light_ok[stage] > 0 ? s_ttt_light[stage] : NULL;
}

/* The TTT stage whose light the fighters take: the stage drawn (active()'s
 * conditions, without its loading), -1 none. TEKKEN3_TTT_STAGES_LIGHT=0
 * (benches: the before of a before / after): never. */
static int light_stage(void) {
    static int off = -1;
    if (off < 0) { const char *e = getenv("TEKKEN3_TTT_STAGES_LIGHT"); off = e && *e == '0'; }
    if (off || !s_on || !s_ttt_on || !psx_mod_gpu_high_vram_ready() || !psx_mod_game_started()) return -1;
    uint32_t mode = psx_mod_read_word(MODE);
    if (mode == 7 || mode == 8) return -1;
    int ttt = ttt_wanted();
    return ttt >= 0 && ttt_light_of(ttt) ? ttt : -1;
}

/* 0x8002A324 */
static uint32_t light_sqrt(uint32_t a) {
    if (!a) return 0;
    uint32_t v = 1, b = a;
    while (v < b) { v <<= 1; b >>= 1; }
    for (;;) {
        uint32_t y = (a / v + v) >> 1;
        if (y >= v) return v;
        v = y;
    }
}

/* 0x80039960's light matrix row 0 and colour matrix columns 0 and 2 from an
 * entry (arena 17's column 2 is black, as there). */
static void light_compute(const uint8_t *e, int arena) {
    int a = rd16(e + 12) & 0xFFF, b = (rd16(e + 14) - 0x800) & 0xFFF;
    int ca = (int16_t)psx_mod_read_half(COS_PS1 + 2u * a), sa = (int16_t)psx_mod_read_half(SIN_PS1 + 2u * a);
    int cb = (int16_t)psx_mod_read_half(COS_PS1 + 2u * b), sb = (int16_t)psx_mod_read_half(SIN_PS1 + 2u * b);
    int32_t v[3] = {shift12((int64_t)cb * ca), sa, shift12((int64_t)sb * ca)};
    uint32_t n = light_sqrt((uint32_t)(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]));
    for (int i = 0; i < 3; i++) {
        if (n) v[i] = tdiv((int64_t)v[i] * 4096, (int32_t)n);
        psx_mod_write_half(LIGHT_MATRIX + 2u * i, (uint16_t)-v[i]);
    }
    for (int i = 0; i < 3; i++) {
        uint8_t c = e[10 - i];                              /* r, g, b */
        psx_mod_write_half(COLOUR_MATRIX + 6u * i, (uint16_t)(c << 4));
        psx_mod_write_half(COLOUR_MATRIX + 6u * i + 4u, (uint16_t)(arena == 17 ? 0 : (c >> 1) << 4));
    }
    s_light_back = (uint16_t)(rd16(e) >> 4);
    s_light_push = 1;
}

/* Every VBlank (TTT Stages' tick). */
static void light_tick(void) {
    int stage = light_stage();
    int arena = (int16_t)psx_mod_read_half(ARENA);
    if (arena < 0 || arena >= LIGHT_ARENAS) stage = -1;
    if (s_light_arena >= 0 && (stage < 0 || arena != s_light_arena || stage != s_light_stage)) {
        for (int i = 0; i < LIGHT_BYTES; i++) psx_mod_write_byte(LIGHT_TABLE + LIGHT_ENTRY * s_light_arena + i, s_light_saved[i]);
        s_light_arena = -1;
    }
    if (stage >= 0) {
        uint32_t at = LIGHT_TABLE + LIGHT_ENTRY * arena;
        const uint8_t *l = s_ttt_light[stage];
        if (s_light_arena < 0) {
            for (int i = 0; i < LIGHT_BYTES; i++) s_light_saved[i] = psx_mod_read_byte(at + i);
            s_light_arena = arena;
            s_light_stage = stage;
        }
        for (int i = 0; i < LIGHT_BYTES; i++)
            if (psx_mod_read_byte(at + i) != l[i]) psx_mod_write_byte(at + i, l[i]);
    }
    int key = stage < 0 ? -1 : stage << 5 | arena;
    if (key == s_light_key) return;
    if (log_on()) {
        if (stage >= 0) fprintf(stdout, "arcade stages: TTT stage %d's light on the fighters (arena %d)\n", stage, arena);
        else fprintf(stdout, "arcade stages: the arena's own light on the fighters (arena %d)\n", arena);
        fflush(stdout);
    }
    s_light_key = key;
    if (arena < 0 || arena >= LIGHT_ARENAS) return;
    uint8_t e[LIGHT_BYTES];
    int lit = arena;                    /* 0x80039960: Tekken Force's (mode 8) arena 12 */
    if (psx_mod_read_word(MODE) == 8 && psx_mod_read_word(0x800B6C10u)) lit = 12;
    for (int i = 0; i < LIGHT_BYTES; i++) e[i] = psx_mod_read_byte(LIGHT_TABLE + LIGHT_ENTRY * lit + i);
    light_compute(e, lit);
}

/* The light computed above to the GTE (SetColorMatrix, SetBackColor), from
 * the next stage frame. */
static void light_push(CPUState *cpu) {
    if (!s_light_push) return;
    s_light_push = 0;
    uint16_t m[9];
    for (int i = 0; i < 9; i++) m[i] = psx_mod_read_half(COLOUR_MATRIX + 2u * i);
    cpu->gte_ctrl[16] = m[0] | (uint32_t)m[1] << 16;
    cpu->gte_ctrl[17] = m[2] | (uint32_t)m[3] << 16;
    cpu->gte_ctrl[18] = m[4] | (uint32_t)m[5] << 16;
    cpu->gte_ctrl[19] = m[6] | (uint32_t)m[7] << 16;
    cpu->gte_ctrl[20] = (uint32_t)(int32_t)(int16_t)m[8];
    cpu->gte_ctrl[13] = cpu->gte_ctrl[14] = cpu->gte_ctrl[15] = (uint32_t)s_light_back << 4;
}

/* Bench (no cinematic engine needed): TEKKEN3_TTT_STAGES_FORCE=n[@state]
 * forces TTT stage n while the game is in that state (default 6, the
 * Embu; "any": always), released otherwise; TEKKEN3_TTT_STAGES_FLASH=
 * "frame:type,..." asks a flash of that type at that stage frame counted
 * from the force. Each call and its answer are logged. */
static void bench_force(void) {
    static int stage = -2, state = 6, forced;
    static unsigned frame;
    static char flashes[256];
    if (stage == -2) {
        const char *e = getenv("TEKKEN3_TTT_STAGES_FORCE");
        stage = e && *e ? atoi(e) : -1;
        const char *at = e ? strchr(e, '@') : NULL;
        if (at) state = !strcmp(at + 1, "any") ? -1 : atoi(at + 1);
        const char *f = getenv("TEKKEN3_TTT_STAGES_FLASH");
        snprintf(flashes, sizeof flashes, "%s", f ? f : "");
    }
    if (stage < 0 || !psx_mod_game_started()) return;
    int here = state < 0 || (int16_t)psx_mod_read_half(0x800AE204u) == state;
    if (here && !forced) {
        int ok = tekken3_ttt_stage_force(stage);
        fprintf(stdout, "arcade stages: bench: tekken3_ttt_stage_force(%d) = %d in state %d\n", stage, ok,
                (int16_t)psx_mod_read_half(0x800AE204u));
        fflush(stdout);
        forced = 1;
        frame = 0;
    } else if (!here && forced) {
        tekken3_ttt_stage_force(-1);
        fprintf(stdout, "arcade stages: bench: tekken3_ttt_stage_force(-1) in state %d\n", (int16_t)psx_mod_read_half(0x800AE204u));
        fflush(stdout);
        forced = 0;
    }
    if (!forced) return;
    frame++;
    for (const char *q = flashes; *q;) {
        unsigned at = (unsigned)strtoul(q, (char **)&q, 10);
        int type = *q == ':' ? (int)strtol(q + 1, (char **)&q, 0) : -1;     /* 0x103: quiet type 3 */
        if (at == frame && type >= 0) {
            int ok = tekken3_ttt_stage_flash(type);
            fprintf(stdout, "arcade stages: bench: tekken3_ttt_stage_flash(%d) = %d at forced frame %u\n", type, ok, frame);
            fflush(stdout);
        }
        while (*q && *q != ',') q++;
        if (*q == ',') q++;
    }
}

/* TEKKEN3_ARCADE_STAGES_ORDER (bench): every stage frame, the previous
 * frame's main OT walked over ranks 1023..1011, above 1010 where the stage is
 * linked (T3's OT A, TTT's whole stage): a game packet there is drawn before
 * the stage, i.e. hidden by it (the HUD is at 1009..1006); drawing commands
 * only (polygons, lines, rectangles). Logged when one is
 * found, and a count every 600 frames. */
static void order_probe(void) {
    static uint32_t bases[2];
    static int on = -1;
    static unsigned frames, bad;
    if (on < 0) on = getenv("TEKKEN3_ARCADE_STAGES_ORDER") != NULL;
    if (!on) return;
    uint32_t base = psx_mod_read_word(psx_mod_read_word(DRAWENV) + 4);
    uint32_t prev = bases[0] == base ? bases[1] : bases[0];
    if (bases[0] != base) { bases[1] = bases[0]; bases[0] = base; }
    if (!prev) return;
    unsigned game = 0;
    int where = -1;
    for (int r = 1023; r >= 1010; r--) {         /* 1010: what comes before our packets there */
        uint32_t a = psx_mod_read_word(prev + 4u * r) & 0xFFFFFFu, end = (prev + 4u * (r - 1)) & 0xFFFFFFu;
        for (unsigned k = 0; a != end && a != 0xFFFFFFu && k < 5000; k++) {
            if (r == 1010 && (a & 0xF00000u) == (s_memory & 0xF00000u)) break;
            uint32_t tag = psx_mod_read_word(0x80000000u | a);
            uint32_t op = psx_mod_read_word(0x80000000u | (a + 4)) >> 24;      /* drawing commands only */
            if (tag >> 24 && op >= 0x20 && op < 0x80 && (a & 0xF00000u) != (s_memory & 0xF00000u)) { game++; if (where < 0) where = r; }
            a = tag & 0xFFFFFFu;
            if (a >= (prev & 0xFFFFFFu) && a < ((prev + 4096u) & 0xFFFFFFu)) break;     /* another rank's entry */
        }
    }
    frames++;
    if (game) {
        bad++;
        fprintf(stdout, "arcade stages: order: frame %u, %u game packets above the stage, first at rank %d (state %d)\n",
                psx_mod_read_word(0x800A08F0u), game, where, (int16_t)psx_mod_read_half(0x800AE204u));
    }
    if (frames % 600 == 0)
        fprintf(stdout, "arcade stages: order: %u frames checked, %u with game packets above the stage\n", frames, bad);
    fflush(stdout);
}

static void stage_draw(CPUState *cpu) {
    Screen s;
    Gte g;
    order_probe();
    read_gte_screen(cpu, &s, &g);
    tile_matrix(&g, 0);
    if (s_probe) {
        Gte ps1 = g;
        tile_matrix(&ps1, 1);
        probe_line(&g, &ps1);
    }
    if (s_shadow) {         /* the PS1 floor this frame: its GT4 quads at ranks 1021..982 */
        if (!s_probe) return;
        uint32_t end = main_ot(981) & 0xFFFFFFu, lo = main_ot(0) & 0xFFFFFFu, hi = main_ot(1024) & 0xFFFFFFu;
        uint32_t a = psx_mod_read_word(main_ot(1021)) & 0xFFFFFFu;
        fprintf(s_probe, "ps1floor %u points", psx_mod_read_word(0x800A08F0u));
        for (unsigned n = 0; a != end && a != 0xFFFFFFu && n < 20000; n++) {
            uint32_t tag = psx_mod_read_word(0x80000000u | a);
            if ((a < lo || a >= hi) && tag >> 24 == 12 && (psx_mod_read_byte(0x80000007u | a) & 0xFC) == 0x3C)
                for (unsigned k = 0; k < 4; k++) {
                    uint32_t v = psx_mod_read_word(0x80000000u | (a + 8 + 12 * k));
                    fprintf(s_probe, " %d,%d", (int16_t)(v & 0xFFFF), (int16_t)(v >> 16));
                }
            a = tag & 0xFFFFFFu;
        }
        fprintf(s_probe, "\n");
        return;
    }
    unsigned b = buffer();
    s_cursor = s_memory + BUFFER_BYTES * b + FLOOR_BYTES;
    s_end = s_memory + BUFFER_BYTES * (b + 1);
    s_stat_tiles = s_stat_far = s_stat_cone = s_stat_behind = s_stat_objects = s_stat_obj_behind = 0;
    if (s_pack.source == TEKKEN3_STAGE_TTT) ttt_anim_tick(&s);
    else anim_tick();
    /* two private OTs of 16 (A then B), ClearOTagR'd, linked as 0x801D8FD0
     * links them: A at main rank 1010, B at 1021, every stage; TTT's in its
     * private OT at its own ranks (stage_ot) */
    uint32_t ot_a = alloc_words(16), ot_b = alloc_words(16);
    if (!ot_a || !ot_b) return;
    for (unsigned i = 1; i < 16; i++) {
        psx_mod_write_word(ot_a + 4 * i, (ot_a + 4 * (i - 1)) & 0xFFFFFFu);
        psx_mod_write_word(ot_b + 4 * i, (ot_b + 4 * (i - 1)) & 0xFFFFFFu);
    }
    /* T3: A at 1010, B at 1021; TTT (0x80153738): A at 995, B at 1021, stage 3
     * A 1021, B 1022 (MISC) */
    uint32_t r1010 = stage_ot(s_pack.rank_a), r1021 = stage_ot(s_pack.rank_b);
    int ttt = s_pack.source == TEKKEN3_STAGE_TTT;
    /* PGXP covers the arcade stages only (see the floor hook). */
    s_precise = psx_mod_precision_wanted() && !ttt;
    s_tj = s_precise && psx_mod_geometry_wanted();
    if (s_tj) tj_begin(TJ_HOOK_STAGE);
    /* TTT: the far background takes the sky of the previous frame's storm */
    int sky = ttt && s_pack.storm ? s_storm.sky : 4;
    if (ttt) storm_step(cpu);
    static unsigned night_said = ~0u;       /* the fight's decision and pack last said at night */
    unsigned night_key = tekken3_stage_decisions() ^ s_pack_generation << 16;
    if (ttt && ttt_night() && night_said != night_key) {
        night_said = night_key;
        fprintf(stdout, "arcade stages: TTT stage %d at night (True Ogre, colour %u, floor kind %d)\n", s_pack.stage,
                s_pack.togr[0], s_pack.togr[1] <= 2 ? s_pack.togr[1] : s_pack.gkind);
        fflush(stdout);
    }
    tiles(&g, &s, ot_a, ot_b);
    if (ttt) {      /* TTT Stages S4: stage 3's object, stage 11's beams, stage 2's particles */
        Gte w;
        if (!ttt_night()) ttt_objects(&g, &s);
        world_gte(cpu, &w);
        beams_draw(&w, stage_ot(TTT_OT_FIRST));
        particles_draw(&w, stage_ot(TTT_OT_FIRST));
    } else {
        t3_ot_link();       /* B87: before the helicopter takes rank 1022 */
        objects(&g);
    }
    tj_fix();
    /* B117: A and B lead to what their ranks hold once the objects are
     * linked: TTT's stage 3 links its carousel at 1022, B's rank, and the
     * game draws B, then the carousel (ttt.Stage.frame) */
    psx_mod_write_word(ot_a, psx_mod_read_word(r1010) & 0xFFFFFFu);
    psx_mod_write_word(ot_b, psx_mod_read_word(r1021) & 0xFFFFFFu);
    psx_mod_write_word(r1010, (psx_mod_read_word(r1010) & 0xFF000000u) | ((ot_a + 60) & 0xFFFFFFu));
    psx_mod_write_word(r1021, (psx_mod_read_word(r1021) & 0xFF000000u) | ((ot_b + 60) & 0xFFFFFFu));
    /* the PS1 tiles dropped: its private OT (2 slots, linked by 0x8006D7CC
     * at rank 1010, arena 11: 1021, once we return) left empty, slot 1
     * leading straight to slot 0 */
    uint32_t priv = PRIVATE_OT + 8u * b;
    psx_mod_write_word(priv + 4, (psx_mod_read_word(priv + 4) & 0xFF000000u) | (priv & 0xFFFFFFu));
    if (ttt && ttt_night()) {       /* B124: one black TILE (0x80243790) */
        static const uint8_t black[3];
        tile_rect(ttt_slot(TTT_OT_FAR), -s.margin, 0, SCREEN_W + 2 * s.margin, SCREEN_H, black);
    } else if (ttt) {
        int e = sky >= 15 && sky <= 20 ? sky - 15 : -1;
        far_background_ttt(&s, (int)psx_mod_read_word(CAMERA + 4) - s_axis_before - s_pack.axis0,
                           (int)psx_mod_read_word(CAMERA), e >= 0 ? s_pack.sskydesc[e] : s_pack.fdesc,
                           e >= 0 ? s_pack.sskyclut[e] : s_pack.fcluts);
    } else {
        far_background(&s, (int)psx_mod_read_word(CAMERA + 4) - s_axis_before, (int)psx_mod_read_word(CAMERA));
    }
    /* TEKKEN3_ARCADE_STAGES_HOLES (bench, tools/test_arcade_stage_holes.py):
     * magenta under everything, the far background included (T3: last into
     * rank 1023, drawn first; TTT: TTT_OT_FILL). A magenta pixel is one
     * nothing of the frame covers, where T3 shows an older frame; seen too
     * through transparent texels with nothing behind, which polygon coverage
     * counts as covered. */
    static int holes = -1;
    if (holes < 0) holes = getenv("TEKKEN3_ARCADE_STAGES_HOLES") != NULL;
    if (holes) {
        static const uint8_t magenta[3] = {255, 0, 255};
        tile_rect(ttt ? ttt_slot(TTT_OT_FILL) : main_ot(1023), -s.margin, 0, SCREEN_W + 2 * s.margin, SCREEN_H, magenta);
    }
    if (ttt) ttt_ot_link();
    if (log_on() && (++s_frames % 120) == 1) {
        fprintf(stdout, "arcade stages: frame %u, %u tiles in the cone, %u tile primitives (%u behind the camera "
                "dropped), %u object primitives (%u dropped), %u floor quads, %u far background, %u bytes, phase %d\n",
                psx_mod_read_word(0x800A08F0u), s_stat_cone, s_stat_tiles, s_stat_behind, s_stat_objects,
                s_stat_obj_behind, s_stat_floor, s_stat_far, (unsigned)(s_cursor - (s_memory + BUFFER_BYTES * b)),
                (int)psx_mod_read_half(PHASE));
        fflush(stdout);
    }
}

static void stage_frame(CPUState *cpu) {
    if (!perf_on()) { stage_draw(cpu); s_draws++; return; }
    uint64_t t = now_ns();
    stage_draw(cpu);
    s_draws++;
    perf_frame(s_perf_floor + (now_ns() - t));
    s_perf_floor = 0;
}

extern void __real_func_8006D014(CPUState *cpu);
void __wrap_func_8006D014(CPUState *cpu) {
    if (cpu->pc == 0 || cpu->pc == 0x8006D014u) {
        bench_force();          /* nothing without its variable */
        light_push(cpu);        /* nothing unless a TTT stage's light came or went */
        s_running = active();
        if (s_running) {
            s_ret = cpu->gpr[31];
            s_sp = cpu->gpr[29];
            s_axis_before = (int)psx_mod_read_word(AXIS);
            s_probe_gte = 0;
        }
    }
    __real_func_8006D014(cpu);
    if (!s_running) return;
    if (s_probe && !s_probe_gte && cpu->pc == 0x80036AF8u) {       /* first tile: the PS1's GTE */
        for (int i = 0; i < 8; i++) s_ps1_gte[i] = (int32_t)cpu->gte_ctrl[i];
        s_probe_gte = 1;
    }
    if (cpu->pc == s_ret && cpu->gpr[29] == s_sp) {
        s_running = 0;
        stage_frame(cpu);
    }
}

/* B79 (GH#133): 0x8004610C (a0 = a scene camera) copies a scripted camera
 * into the live one (0x800A85C0, pitch = the scene's / 64). Gun Jack's
 * flying win pose (move 3432) has it follow him up to pitch -0x1F0; the
 * arcade's camera for the same pose stays level (MAME: +0x3D down to 0
 * while he flies out of the top of the picture; every win pose and replay
 * measured stays within -0x22..+0x45), so its stages never had to cover
 * what lies above their buildings: empty cells of the far background, no
 * top colour, and older frames left there (T3 never clears the screen).
 * With an arcade stage drawn, T3's or TTT's (same defect measured on TTT's:
 * stage 7, 69 % of the picture), once the round is decided (K.O., replay,
 * win poses), the camera is held at the T3 arcade's: pitch no higher than
 * -0x22. The fight's cameras are left alone, and the PS1 stage (mod off),
 * whose own sky covers the picture under the same pose. B87: T3's stages
 * now have the arcade's own winner camera (src/tekken3_arcade_cameras.c),
 * level by itself, which this floor would cut (the arcade's camera climbs to
 * -0x53 on stages 4, 6, 7): TTT's stages only. */
#define ARCADE_PITCH_MIN (-0x22)
static uint32_t s_cam_ret, s_cam_sp;
static int s_cam_held;
extern void __real_func_8004610C(CPUState *cpu);
void __wrap_func_8004610C(CPUState *cpu) {
    if (cpu->pc == 0 || cpu->pc == 0x8004610Cu) {
        s_cam_held = (int16_t)psx_mod_read_half(0x800AE204u) == 8 && round_over() && !s_shadow && active()
                     && s_pack.source == TEKKEN3_STAGE_TTT;
        s_cam_ret = cpu->gpr[31];
        s_cam_sp = cpu->gpr[29];
    }
    __real_func_8004610C(cpu);
    if (!s_cam_held || cpu->pc != s_cam_ret || cpu->gpr[29] != s_cam_sp) return;
    s_cam_held = 0;
    if ((int32_t)psx_mod_read_word(CAMERA) < ARCADE_PITCH_MIN) psx_mod_write_word(CAMERA, (uint32_t)ARCADE_PITCH_MIN);
}

/* 0x80048374 (a0 = buffer): a TILE of the arena's colour (0x80097A64)
 * over the whole screen (368 x 480 in fights), main OT rank 1023, drawn
 * first; 0x8006D7CC calls it after the stage for arena 11 only (and for
 * the dark arenas, which keep the PS1 stage). Not part of the arcade
 * stage: skipped while ours draws.
 *
 * The dark arena (0x800AFAA0, True Ogre's fight): 0x8006D7CC calls only
 * this TILE (0x8006D810), never the stage routine 0x8006D014, and the
 * floor routine is 0x80049848 (0x80048134), hooked as usual. With a TTT
 * stage wanted there (drawn at night, ttt_night, src/tekken3_stage_source.c)
 * the TTT stage is drawn here instead of the TILE, as after 0x8006D014 (its
 * far background covers the screen, as in a lit arena): the camera and the
 * GTE screen are the fight's; no axis step (the PS1 routine that turns it
 * does not run). */
extern void __real_func_80048374(CPUState *cpu);
void __wrap_func_80048374(CPUState *cpu) {
    int entry = cpu->pc == 0 || cpu->pc == 0x80048374u;
    if (entry) light_push(cpu);
    if (entry && !s_shadow && psx_mod_read_half(ARENA) == 11 && active()) {
        cpu->pc = cpu->gpr[31];
        return;
    }
    if (entry && !s_shadow && psx_mod_read_byte(DARK_ARENA) && cpu->gpr[31] == 0x8006D82Cu && active()
        && s_pack.source == TEKKEN3_STAGE_TTT) {
        s_axis_before = (int)psx_mod_read_word(AXIS);
        stage_frame(cpu);
        cpu->pc = cpu->gpr[31];
        return;
    }
    __real_func_80048374(cpu);
}

/* The sources this engine draws (src/tekken3_stage_source.h): Tekken 3's
 * arcade stages with Arcade Stages and its packs, TTT's with TTT Stages and
 * its packs (the STAGES row then appears). */
int tekken3_arcade_stages_source_ready(int source) {
    return s_on && (source == TEKKEN3_STAGE_T3 ? s_t3_on : source == TEKKEN3_STAGE_TTT ? s_ttt_on : 0);
}

/* ------------------------------------------------------------------ */
/* Any pack present: T3's 13 (the setup makes them all from tekken3.zip),
 * TTT's 15 (from tektagt.zip). */
static int packs_present(int source) {
    char path[1024];
    int last = source == TEKKEN3_STAGE_TTT ? 14 : 12;
    for (int stage = 0; stage <= last; stage++) {
        snprintf(path, sizeof path, "%s/stage%02d.ast", pack_dir_of(source), stage);
        FILE *f = fopen(path, "rb");
        if (f) { fclose(f); return 1; }
    }
    return 0;
}

/* The engine, once for both features: the upper VRAM half and the packet
 * memory. */
static int engine_up(void) {
    if (s_on) return 1;
    if (!psx_mod_gpu_high_vram_enable()) {
        fprintf(stdout, "arcade stages: no upper VRAM half, PS1 stages kept\n");
        return 0;
    }
    s_memory = psx_mod_alloc_gpu_dma_memory(2 * BUFFER_BYTES, 16);
    if (!s_memory || !psx_mod_gpu_high_vram_source(s_memory, 2 * BUFFER_BYTES)) {
        fprintf(stdout, "arcade stages: no packet memory, PS1 stages kept\n");
        return 0;
    }
    unr_init();
    s_pack.stage = -1;
    const char *probe = getenv("TEKKEN3_ARCADE_STAGES_PROBE");
    if (probe && *probe) s_probe = fopen(probe, "w");
    s_shadow = s_probe && getenv("TEKKEN3_ARCADE_STAGES_SHADOW");
    s_on = 1;
    return 1;
}

static void tekken3_arcade_stages_activate(void) {
    /* No packs (no tekken3.zip at setup): nothing allocated, the game as
     * with the feature off. */
    if (!packs_present(TEKKEN3_STAGE_T3)) {
        fprintf(stdout, "arcade stages: no stage packs in %s, PS1 stages kept\n", pack_dir());
        return;
    }
    if (!engine_up()) return;
    s_t3_on = 1;
    fprintf(stdout, "arcade stages: on, packs from %s\n", pack_dir());
    fflush(stdout);
}

/* TTT Stages (feature ttt-stages of the TTT1 package): the same engine with
 * TTT's packs; nothing allocated without them. */
static void tekken3_ttt_stages_activate(void) {
    if (!packs_present(TEKKEN3_STAGE_TTT)) {
        fprintf(stdout, "arcade stages: no TTT stage packs in %s, TTT stages off\n", pack_dir_of(TEKKEN3_STAGE_TTT));
        return;
    }
    if (!engine_up()) return;
    s_ttt_on = 1;
    fprintf(stdout, "arcade stages: TTT stages on, packs from %s\n", pack_dir_of(TEKKEN3_STAGE_TTT));
    fflush(stdout);
}

/* TTT Stages' own tick (TTT Stages S7): the STAGES row and the Continues,
 * with or without TTT1 Characters. The fight's stage is decided from
 * 0x8004F3B0 (src/tekken3_ttt1_roster.c) whenever TTT's packs are up: with
 * the characters off, natives only. Plugins run in the manifest's order:
 * TTT1 Characters' tick (the CPU MOVESET row) before this one, so STAGES
 * comes after CPU MOVESET. */
static void tekken3_ttt_stages_tick(void) {
    tekken3_stage_source_tick();
    light_tick();
}

PSX_MOD_CONSTRUCTOR(tekken3_register_arcade_stages) {
    (void)psx_mod_register_activation_plugin("tekken3.arcade-stages",
                                             tekken3_arcade_stages_activate);
    (void)psx_mod_register_activation_plugin("tekken3.ttt-stages",
                                             tekken3_ttt_stages_activate);
    (void)psx_mod_register_vblank_plugin("tekken3.ttt-stages",
                                         tekken3_ttt_stages_tick);
}
