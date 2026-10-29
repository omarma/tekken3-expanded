/* TTT Stages S5: the music of TTT's arcade stages in place of Tekken 3's.
 *
 * TTT's sound driver (an H8) plays a piece by writing to the C352 sound chip;
 * those writes, recorded once in MAME (tools/ttt_stages/music.py, TIPS), are
 * replayed here on the C352 of tools/ttt1/c352.py over the chip's samples
 * from the player's tektagt.zip: mods/ttt-music/music.ttm
 * (tools/ttt_stages/music_install.py; TEKKEN3_TTT_MUSIC_DIR for benches).
 * Through MAME 0.289's lofi resampler, the first pass is MAME's -wavwrite to
 * the sample. A piece plays its intro and its turn, then jumps from `seam`
 * back to `loop` with a short crossfade (the turns are not the same to the
 * sample: the H8's tick falls between the chip's samples).
 *
 * Tekken 3 still runs its XA music (states, fades, pause, rounds): while a
 * TTT stage is shown and T3 plays the round's music, that music is muted
 * and the piece of the stage mixed instead, at T3's current XA level
 * (0x800A068C, DsMix's matrix, mono option). T3 starts its music at each
 * round's setup (0x8006AE14) and keeps it when it is already playing: the
 * piece starts when T3's XA becomes audible and goes on over the rounds; a
 * stop (end of match, quitting) ends it, unless T3 kept a resume point. The
 * next fight decided while that music still fades (its round music, stage
 * and version already others) does not: the piece fades out with it.
 *
 * The stage is the fight's (tekken3_stage_ttt_stage, the STAGES row decided
 * per fight): only a fight given a TTT stage plays its piece. In such a
 * fight, TEKKEN3_TTT_MUSIC_STAGE=n plays stage n's piece instead (benches).
 * Without the file, without a TTT stage, the game is untouched.
 *
 * GAME OPTION's BGM SELECT picks the version as it does for Tekken 3's own
 * music: REMIXED (0x80097F05 = 0) plays the stage's piece of TTT's PS2
 * version, copied from the player's PS2 disc (mods/ttt-ps2-music/
 * ps2-music.ttp, tools/ttt_stages/ps2_music_install.py;
 * TEKKEN3_TTT_PS2_MUSIC_DIR for benches) when it is there, else the arcade
 * piece; ARCADE plays the arcade piece; SILENT, T3 starts no music in a fight
 * and neither does this; RANDOM, the version drawn for the fight
 * (src/tekken3_bgm_select.c), REMIXED again falling back on the arcade
 * piece without the PS2 one. The PS2 pieces are PS-ADPCM streams the PS2 driver
 * loops by reading the disc again from a loop sector (RSPU2DRV.IRX): decoded
 * here the same way, at the driver's volume, the decoder's history going on
 * over the jump. */
#include "mod_plugins.h"
#include "psx_runtime.h"
#include "psx_sdl.h"
#include "spu.h"
#include "tekken3_stage_source.h"
#include "tekken3_bgm_select.h"
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

enum { BUSY = 0x8000, KEYON = 0x4000, KEYOFF = 0x2000, LOOPHIST = 0x800, PHASEFL = 0x100, PHASEFR = 0x80,
       LDIR = 0x40, LINK = 0x20, NOISE = 0x10, MULAW = 8, FILTER = 4, LOOP = 2, REVERSE = 1 };
enum { FORMAT = 1, VOICES = 32, RING = 32, MAX_PIECES = 32 };

/* TTT stage -> piece (0x8012AA5C of TTT): 0 Paul .. 12 Heihachi, 13 Eddy-A, 14 Unknown. */
static const uint8_t STAGE_PIECES[15] = { 0x11, 0x1E, 0x16, 0x10, 0x19, 0x13, 0x1C, 0x1B, 0x17, 0x15,
                                          0x18, 0x14, 0x1A, 0x18, 0x12 };
/* The same stages' PS2 pieces (0x4FB8C0 of SLUS_200.01). */
static const uint8_t STAGE_PS2_PIECES[15] = { 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12,
                                              0x13, 0x14, 0x15, 0x13, 0x16 };
enum { PS2_FORMAT = 1, PS2_MAX = 16, SECTOR = 2048, SECTOR_SAMPLES = 1792 };

typedef struct { uint32_t n; uint16_t reg, value, mask, pad; } Write;
typedef struct {
    uint32_t number, loop, seam, fade, init_count, write_count;
    const uint8_t *init;          /* u16 register, u16 value */
    Write *writes;                /* n: chip samples since the request */
} Piece;

static struct {
    int tried, ok, count;
    uint32_t chip_start, out_start;
    Piece pieces[MAX_PIECES];
    const uint8_t *bank[256];
    uint8_t *body;
} lib;
static const uint8_t zero_bank[65536];

typedef struct { uint16_t regs[8]; uint32_t pos; int32_t counter, sample, last, vol[2]; } Voice;
typedef struct { Voice v[VOICES]; uint32_t noise, busy, t, cursor; } Chip;

/* The player: all of it goes into save states while it plays. */
typedef struct {
    uint32_t magic, size;
    int32_t piece;            /* index in lib.pieces, -1: idle */
    int32_t paused;           /* T3 stopped its music keeping a resume point */
    int32_t waiting;          /* started; T3's XA not audible yet */
    int32_t last_cur;         /* T3's music number when last seen playing */
    int32_t snapshot_ok, fading;
    int64_t produced;         /* chip samples made since the start (the stream) */
    int64_t d;                /* next output sample, MAME's 44 100 Hz clock */
    Chip a, b, snap;
    int16_t ring[RING];
    int16_t ring_r[RING];
    /* From here on, added for the PS2 pieces: a save state of the arcade
     * pieces' player alone ends above (TTT Stages S5). */
    int32_t ps2;              /* index in ps2.p, -1: an arcade piece or none */
    uint32_t ps2_pos;         /* next sample from the piece's start */
    int32_t ps2_hist[2][2];   /* PS-ADPCM decoder, left and right */
    int16_t ps2_frame[2][28]; /* the frame ps2_pos is in */
} Player;
#define PLAYER_MAGIC 0x314D5454u   /* "TTM1" */
#define PLAYER_S5_SIZE ((uint32_t)offsetof(Player, ps2))
_Static_assert(offsetof(Player, ps2) == 4064, "the S5 player's save state is 4 064 bytes");
static Player pl = { .piece = -1, .ps2 = -1 };
static int stage_seen = -1;       /* for the log */

static int16_t MU[256], LIN[256];
static float f0[0x1001], f1[0x1001];

static void tables(void) {
    int t[128], j = 0;
    for (int i = 0; i < 128; i++) {
        t[i] = j << 5;
        j += i < 16 ? 1 : i < 24 ? 2 : i < 48 ? 4 : i < 100 ? 8 : 16;
    }
    for (int i = 0; i < 128; i++) { MU[i] = (int16_t)t[i]; MU[i + 128] = (int16_t)(~t[i] & 0xffe0); }
    for (int b = 0; b < 256; b++) LIN[b] = (int16_t)(b << 8);
    /* MAME 0.289's lofi interpolation table, float as there (1.0 a double). */
    for (int i = 1; i < 4096; i++) { float p = (float)(i / 4096.0); f0[i] = (p - p * p * p) / 6.0f; }
    for (int i = 1; i < 2049; i++) { float p = (float)(i / 4096.0); f1[i] = p + (p * p - p * p * p) / 2.0f; }
    for (int i = 2049; i < 4096; i++) f1[i] = (float)(1.0 + (double)f0[i] + (double)f0[4096 - i] - (double)f1[4096 - i]);
    f1[0x1000] = 1.0f;
}

static char s_dir[1024];
static const char *music_dir(void) {
    if (s_dir[0]) return s_dir;
    const char *e = getenv("TEKKEN3_TTT_MUSIC_DIR");
    if (e && *e) snprintf(s_dir, sizeof s_dir, "%s", e);
    else {
        const char *base = SDL_GetBasePath();
        snprintf(s_dir, sizeof s_dir, "%smods/ttt-music", base ? base : "");
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
    return s_dir;
}

static uint32_t u32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static uint16_t u16(const uint8_t *p) { uint16_t v; memcpy(&v, p, 2); return v; }

/* music.ttm (format in tools/ttt_stages/music_install.py), read once. */
static int load(void) {
    if (lib.tried) return lib.ok;
    lib.tried = 1;
    tables();
    char path[1100];
    snprintf(path, sizeof path, "%s/music.ttm", music_dir());
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    uint8_t head[12];
    uLong raw = 0;
    uint8_t *packed = NULL;
    long size = 0;
    if (fread(head, 1, 12, f) == 12 && !memcmp(head, "TTTM", 4) && u32(head + 4) == FORMAT) {
        raw = u32(head + 8);
        fseek(f, 0, SEEK_END); size = ftell(f) - 12; fseek(f, 12, SEEK_SET);
        packed = size > 0 ? malloc((size_t)size) : NULL;
        if (packed && fread(packed, 1, (size_t)size, f) != (size_t)size) { free(packed); packed = NULL; }
    }
    fclose(f);
    if (!packed) { fprintf(stderr, "TTT music: %s is not a music file of format %d\n", path, FORMAT); return 0; }
    lib.body = malloc(raw);
    uLong got = raw;
    int z = lib.body ? uncompress(lib.body, &got, packed, (uLong)size) : Z_MEM_ERROR;
    free(packed);
    if (z != Z_OK || got != raw || raw < 16) { fprintf(stderr, "TTT music: %s does not inflate\n", path); return 0; }
    const uint8_t *p = lib.body, *end = lib.body + raw;
    lib.chip_start = u32(p); lib.out_start = u32(p + 4);
    uint32_t pieces = u32(p + 8), banks = u32(p + 12);
    const uint8_t *bank_ids = p + 16;
    p = bank_ids + ((banks + 3) & ~3u);
    if (pieces > MAX_PIECES) return 0;
    for (uint32_t i = 0; i < pieces; i++) {
        Piece *q = &lib.pieces[i];
        if (end - p < 24) return 0;
        q->number = u32(p); q->loop = u32(p + 4); q->seam = u32(p + 8); q->fade = u32(p + 12);
        q->init_count = u32(p + 16); q->write_count = u32(p + 20);
        p += 24;
        q->init = p;
        p += 4 * (size_t)q->init_count;
        if (end - p < 10 * (int64_t)q->write_count || q->fade > q->loop || q->loop >= q->seam) return 0;
        q->writes = malloc(sizeof(Write) * (q->write_count ? q->write_count : 1));
        if (!q->writes) return 0;
        uint32_t n = 0;
        for (uint32_t w = 0; w < q->write_count; w++, p += 10) {
            n += u32(p);                       /* stored as gaps */
            q->writes[w] = (Write){ n, u16(p + 4), u16(p + 6), u16(p + 8), 0 };
        }
    }
    for (int b = 0; b < 256; b++) lib.bank[b] = zero_bank;
    if ((uint64_t)(end - p) < (uint64_t)banks << 16) return 0;
    for (uint32_t b = 0; b < banks; b++, p += 65536) lib.bank[bank_ids[b]] = p;
    lib.count = (int)pieces;
    lib.ok = 1;
    fprintf(stderr, "TTT music: %d pieces, %u banks from %s\n", lib.count, banks, path);
    return 1;
}

static int piece_of_stage(int stage) {
    if (stage < 0 || stage > 14 || !load()) return -1;
    for (int i = 0; i < lib.count; i++)
        if (lib.pieces[i].number == STAGE_PIECES[stage]) return i;
    return -1;
}

/* ---- The PS2 pieces: ps2-music.ttp (tools/ttt_stages/ps2_music_install.py) ---- */

static struct {
    int tried, ok, count;
    char path[1100];
    struct { uint32_t number, offset, sectors, loop, volume; } p[PS2_MAX];
    int data_piece;           /* the piece in data, -1: none */
    uint8_t *data;
} ps2 = { .data_piece = -1 };

static int ps2_load(void) {
    if (ps2.tried) return ps2.ok;
    ps2.tried = 1;
    const char *e = getenv("TEKKEN3_TTT_PS2_MUSIC_DIR");
    if (e && *e) snprintf(ps2.path, sizeof ps2.path, "%s/ps2-music.ttp", e);
    else {
        const char *base = SDL_GetBasePath();
        snprintf(ps2.path, sizeof ps2.path, "%smods/ttt-ps2-music/ps2-music.ttp", base ? base : "");
#if !defined(PSX_SDL3)
        SDL_free((void *)base);
#endif
    }
    FILE *f = fopen(ps2.path, "rb");
    if (!f) return 0;
    uint8_t head[12 + 20 * PS2_MAX];
    size_t got = fread(head, 1, sizeof head, f);
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fclose(f);
    uint32_t count = got >= 12 ? u32(head + 8) : 0;
    if (got < 12 || memcmp(head, "TTP2", 4) || u32(head + 4) != PS2_FORMAT || count > PS2_MAX || got < 12 + 20 * count) {
        fprintf(stderr, "TTT music: %s is not a PS2 music file of format %d\n", ps2.path, PS2_FORMAT);
        return 0;
    }
    for (uint32_t i = 0; i < count; i++) {
        const uint8_t *q = head + 12 + 20 * i;
        ps2.p[i].number = u32(q); ps2.p[i].offset = u32(q + 4); ps2.p[i].sectors = u32(q + 8);
        ps2.p[i].loop = u32(q + 12); ps2.p[i].volume = u32(q + 16);
        if (!ps2.p[i].sectors || ps2.p[i].loop >= ps2.p[i].sectors
            || (uint64_t)ps2.p[i].offset + (uint64_t)ps2.p[i].sectors * SECTOR > (uint64_t)size) {
            fprintf(stderr, "TTT music: %s is cut short\n", ps2.path);
            return 0;
        }
    }
    ps2.count = (int)count;
    ps2.ok = 1;
    fprintf(stderr, "TTT music: %d PS2 pieces from %s\n", ps2.count, ps2.path);
    return 1;
}

static int ps2_of_stage(int stage) {
    if (stage < 0 || stage > 14 || !ps2_load()) return -1;
    for (int i = 0; i < ps2.count; i++)
        if (ps2.p[i].number == STAGE_PS2_PIECES[stage]) return i;
    return -1;
}

/* GAME OPTION's BGM SELECT (0x80097F05, Tekken 3's music_option) is REMIXED,
 * or RANDOM drew it for the fight (src/tekken3_bgm_select.c). */
static int remixed(void) { return tekken3_bgm_select_version() == TEKKEN3_BGM_REMIXED; }

/* The piece's sectors in memory, one piece at a time (5.5 MB at most). */
static int ps2_data(int i) {
    if (ps2.data_piece == i) return 1;
    free(ps2.data);
    ps2.data = NULL;
    ps2.data_piece = -1;
    size_t n = (size_t)ps2.p[i].sectors * SECTOR;
    FILE *f = fopen(ps2.path, "rb");
    if (!f) return 0;
    ps2.data = malloc(n);
    int ok = ps2.data && !fseek(f, (long)ps2.p[i].offset, SEEK_SET) && fread(ps2.data, 1, n, f) == n;
    fclose(f);
    if (!ok) { free(ps2.data); ps2.data = NULL; fprintf(stderr, "TTT music: %s unreadable\n", ps2.path); return 0; }
    ps2.data_piece = i;
    return 1;
}

/* One PS-ADPCM frame (16 bytes, 28 samples) of a channel. */
static void ps2_decode(const uint8_t *fr, int32_t h[2], int16_t out[28]) {
    static const int F0[5] = { 0, 60, 115, 98, 122 }, F1[5] = { 0, 0, -52, -55, -60 };
    int shift = fr[0] & 15, filter = fr[0] >> 4;
    if (shift > 12) shift = 9;
    if (filter > 4) filter = 4;
    for (int k = 0; k < 28; k++) {
        int nib = (fr[2 + k / 2] >> ((k & 1) * 4)) & 15;
        int32_t v = ((int32_t)(int16_t)(nib << 12)) >> shift;
        v += (h[0] * F0[filter] + h[1] * F1[filter] + 32) >> 6;
        v = v < -32768 ? -32768 : v > 32767 ? 32767 : v;
        out[k] = (int16_t)v;
        h[1] = h[0]; h[0] = v;
    }
}

/* The next 44 100 Hz sample of the PS2 piece; at its end, on from its loop
 * sector as the driver reads the disc again (the SPU2 voice decodes on). */
static void ps2_sample(int16_t out[2]) {
    const uint8_t *d = ps2.data;
    uint32_t pos = pl.ps2_pos, k = pos % 28;
    if (!k) {
        const uint8_t *fr = d + (size_t)(pos / SECTOR_SAMPLES) * SECTOR + (pos % SECTOR_SAMPLES) / 28 * 16;
        ps2_decode(fr, pl.ps2_hist[0], pl.ps2_frame[0]);
        ps2_decode(fr + 1024, pl.ps2_hist[1], pl.ps2_frame[1]);
    }
    out[0] = pl.ps2_frame[0][k];
    out[1] = pl.ps2_frame[1][k];
    if (++pos == ps2.p[pl.ps2].sectors * SECTOR_SAMPLES) {
        pos = ps2.p[pl.ps2].loop * SECTOR_SAMPLES;
        fprintf(stderr, "TTT music: PS2 piece 0x%02X loops back to %.2f s\n", ps2.p[pl.ps2].number, pos / 44100.0);
    }
    pl.ps2_pos = pos;
}

static int playing_piece(void) { return pl.piece >= 0 || pl.ps2 >= 0; }
static unsigned piece_number(void) { return pl.ps2 >= 0 ? ps2.p[pl.ps2].number : lib.pieces[pl.piece].number; }
static const char *piece_kind(void) { return pl.ps2 >= 0 ? "PS2 piece" : "piece"; }

/* ---- The C352 (tools/ttt1/c352.py render, MAME's c352.cpp) ---- */

static void chip_reset(Chip *c, const Piece *p) {
    memset(c, 0, sizeof *c);
    for (uint32_t i = 0; i < p->init_count; i++) {
        uint16_t reg = u16(p->init + 4 * i), value = u16(p->init + 4 * i + 2);
        if (reg < 0x100) c->v[reg / 8].regs[reg % 8] = value & ~BUSY;
    }
    c->noise = 0x1234;
}

static void chip_writes(Chip *c, const Piece *p) {
    while (c->cursor < p->write_count && p->writes[c->cursor].n <= c->t) {
        const Write *w = &p->writes[c->cursor++];
        if (w->reg < 0x100) {
            Voice *v = &c->v[w->reg / 8];
            int r = w->reg % 8;
            v->regs[r] = (uint16_t)((v->regs[r] & ~w->mask) | (w->value & w->mask));
            if (r == 3) {
                if (v->regs[3] & BUSY) c->busy |= 1u << (w->reg / 8);
                else c->busy &= ~(1u << (w->reg / 8));
            }
        } else if (w->reg == 0x202 && w->mask == 0xffff) {
            for (int i = 0; i < VOICES; i++) {
                Voice *v = &c->v[i];
                uint16_t f = v->regs[3];
                if (f & KEYON) {
                    v->pos = ((uint32_t)v->regs[4] << 16) | v->regs[5];
                    v->sample = v->last = 0;
                    v->counter = 0xffff;
                    f = (uint16_t)((f | BUSY) & ~(KEYON | LOOPHIST));
                    v->vol[0] = v->vol[1] = 0;
                }
                if (f & KEYOFF) { f &= (uint16_t)~(BUSY | KEYOFF); v->counter = 0xffff; }
                v->regs[3] = f;
                if (f & BUSY) c->busy |= 1u << i; else c->busy &= ~(1u << i);
            }
        }
    }
}

/* One 88 200 Hz sample: the writes due, then the voices. */
static void chip_step(Chip *c, const Piece *p, int16_t out[2]) {
    chip_writes(c, p);
    int32_t o0 = 0, o1 = 0;
    for (uint32_t m = c->busy; m; m &= m - 1) {
        int i = __builtin_ctz(m);
        Voice *v = &c->v[i];
        uint16_t fl = v->regs[3];
        int32_t cnt = v->counter, nc = cnt + v->regs[2];
        if (nc & 0x10000) {
            v->last = v->sample;
            if (fl & NOISE) {
                c->noise = (c->noise >> 1) ^ ((0u - (c->noise & 1)) & 0xfff6);
                v->sample = (int16_t)c->noise;
            } else {
                uint32_t a = v->pos & 0xffffff;
                uint8_t b = lib.bank[a >> 16][a & 0xffff];
                v->sample = fl & MULAW ? MU[b] : LIN[b];
                uint32_t q = v->pos & 0xffff;
                if ((fl & LOOP) && (fl & REVERSE)) {
                    if ((fl & LDIR) && q == v->regs[7]) fl &= (uint16_t)~LDIR;
                    else if (!(fl & LDIR) && q == v->regs[6]) fl |= LDIR;
                    v->pos += fl & LDIR ? (uint32_t)-1 : 1u;
                } else if (q == v->regs[6]) {
                    if ((fl & LINK) && (fl & LOOP)) { v->pos = ((uint32_t)v->regs[5] << 16) | v->regs[7]; fl |= LOOPHIST; }
                    else if (fl & LOOP) { v->pos = (v->pos & 0xff0000) | v->regs[7]; fl |= LOOPHIST; }
                    else { fl = (uint16_t)((fl | KEYOFF) & ~BUSY); v->sample = 0; }
                } else v->pos += fl & REVERSE ? (uint32_t)-1 : 1u;
            }
            v->regs[3] = fl;
            if (!(fl & BUSY)) c->busy &= ~(1u << i);
        }
        if ((nc ^ cnt) & 0x18000) {               /* volume ramp, one step at a time */
            int tg[2] = { v->regs[0] >> 8, v->regs[0] & 0xff };
            for (int ch = 0; ch < 2; ch++) if (v->vol[ch] != tg[ch]) v->vol[ch] += v->vol[ch] < tg[ch] ? 1 : -1;
        }
        v->counter = nc & 0xffff;
        int32_t s = v->sample;
        if (!(fl & FILTER)) s = v->last + (int32_t)(((int64_t)v->counter * (s - v->last)) >> 16);
        o0 += ((fl & PHASEFL ? -s : s) * v->vol[0]) >> 8;
        o1 += ((fl & PHASEFR ? -s : s) * v->vol[1]) >> 8;
    }
    out[0] = (int16_t)(o0 >> 3);
    out[1] = (int16_t)(o1 >> 3);
    c->t++;
}

/* The next sample of the stream: chip A, crossfaded into chip B (the turn
 * from `loop - fade`) over the last `fade` samples before the seam. */
static void produce(void) {
    const Piece *p = &lib.pieces[pl.piece];
    int16_t a[2], b[2];
    if (!pl.snapshot_ok && pl.a.t == p->loop - p->fade) { pl.snap = pl.a; pl.snapshot_ok = 1; }
    if (!pl.fading && pl.snapshot_ok && pl.a.t == p->seam - p->fade) { pl.b = pl.snap; pl.fading = 1; }
    chip_step(&pl.a, p, a);
    if (pl.fading) {
        int32_t i = (int32_t)(pl.a.t - 1 - (p->seam - p->fade)), n = (int32_t)p->fade;
        chip_step(&pl.b, p, b);
        for (int ch = 0; ch < 2; ch++) a[ch] = (int16_t)((a[ch] * (n - i) + b[ch] * i) / n);
        if (pl.a.t == p->seam) {
            pl.a = pl.b; pl.fading = 0;
            fprintf(stderr, "TTT music: piece 0x%02X loops back to %.2f s\n", p->number, p->loop / 88200.0);
        }
    } else if (pl.a.t >= p->seam) {
        /* no turn kept (cannot happen with a stream started at 0): from the top */
        chip_reset(&pl.a, p);
        pl.snapshot_ok = 0;
    }
    pl.ring[pl.produced % RING] = a[0];
    pl.ring_r[pl.produced % RING] = a[1];
    pl.produced++;
}

static float stream(int64_t s, int ch) {
    if (s < 0) return 0.0f;
    return (ch ? pl.ring_r : pl.ring)[s % RING] / 32768.0f;
}

/* MAME 0.289's lofi resampler, 88 200 to 44 100 Hz, at output sample d
 * (tools/ttt1/c352.py output): averages of 3, 4-point interpolation 4
 * averages late, phase re-derived every 882 samples. */
static void resample(int16_t out[2]) {
    int64_t d = pl.d, update = d - (d - 1) % 882, delta = (2 * update) % 3;
    int64_t phase = (((delta << 12) / 3) << 12) + (d - update) * 11184810;
    int64_t k = (2 * update - delta) / 3 - 4 + (phase >> 24);
    int c = (int)((phase & 0xffffff) >> 12);
    int64_t first = (int64_t)lib.chip_start;
    while (pl.produced <= 3 * (k + 3) + 2 - first) produce();
    for (int ch = 0; ch < 2; ch++) {
        float av[4];
        for (int j = 0; j < 4; j++) {
            int64_t i = 3 * (k + j) - first;
            av[j] = ((0.0f + stream(i, ch)) + stream(i + 1, ch) + stream(i + 2, ch)) / 3.0f;
        }
        float y = -av[0] * f0[4096 - c] + av[1] * f1[4096 - c];
        y = y + av[2] * f1[c];
        y = y - av[3] * f0[c];
        int64_t q = (int64_t)(y * 32768.0f);
        out[ch] = (int16_t)(q > 32767 ? 32767 : q < -32768 ? -32768 : q);
    }
    pl.d++;
}

static uint32_t state_bytes(void);
static void state_write(uint8_t *p);
static int state_read(const uint8_t *p, uint32_t len);

static void register_state(void) {
    static int registered;
    if (!registered) { psx_mod_audio_state_register(state_bytes, state_write, state_read); registered = 1; }
}

/* An arcade piece (piece >= 0) or a PS2 one (ps2_piece >= 0). */
static void start(int piece, int ps2_piece) {
    register_state();
    memset(&pl, 0, sizeof pl);
    pl.magic = PLAYER_MAGIC;
    pl.size = sizeof pl;
    pl.piece = piece;
    pl.ps2 = ps2_piece;
    pl.waiting = 1;
    if (piece >= 0) {
        pl.d = lib.out_start;
        chip_reset(&pl.a, &lib.pieces[piece]);
    }
}

static void stop(const char *why) {
    if (playing_piece()) fprintf(stderr, "TTT music: %s 0x%02X stops (%s)\n", piece_kind(), piece_number(), why);
    pl.piece = pl.ps2 = -1;
}

/* TEKKEN3_TTT_MUSIC_DUMP=file: the stream as MAME would record it (before
 * any level), from the start of the piece, for tools/ttt_stages/music.py. */
static void dump(const int16_t s[2]) {
    static FILE *f;
    static int state;
    static int64_t written;
    if (state < 0) return;
    if (!state) {
        const char *e = getenv("TEKKEN3_TTT_MUSIC_DUMP");
        f = e && *e ? fopen(e, "wb") : NULL;
        state = f ? 1 : -1;
        if (!f) return;
    }
    fwrite(s, 2, 2, f);
    if (++written >= 44100LL * 120) { fclose(f); state = -1; }
}

/* ---- The fight's stage (src/tekken3_stage_source.c, the STAGES row) ---- */

int tekken3_ttt_music_has(int stage) { return piece_of_stage(stage) >= 0 || ps2_of_stage(stage) >= 0; }

/* The TTT stage the fight was given, -1 for Tekken 3's music (a T3 stage). */
static int wanted_stage(void) {
    int stage = tekken3_stage_ttt_stage();
    if (stage >= 0) {
        static int forced = -2;
        if (forced == -2) { const char *e = getenv("TEKKEN3_TTT_MUSIC_STAGE"); forced = e && *e ? atoi(e) : -1; }
        if (forced >= 0) stage = forced;
    }
    if (stage != stage_seen) {
        if (stage >= 0)
            fprintf(stderr, "TTT music: TTT stage %d, arcade piece %s, PS2 piece %s\n", stage,
                    piece_of_stage(stage) >= 0 ? "installed" : "missing", ps2_of_stage(stage) >= 0 ? "installed" : "missing");
        stage_seen = stage;
    }
    return stage;
}

/* ---- Mixed in the TTT1 voices' spu_render wrapper ---- */

static int gain_percent(void) {
    static int percent = -1;
    if (percent < 0) {
        const char *v = getenv("TEKKEN3_TTT_MUSIC_VOLUME");
        percent = v && *v ? atoi(v) : 500;
        if (percent < 0) percent = 0;
        if (percent > 1600) percent = 1600;
    }
    return percent;
}

/* Returns 1 while a piece replaces T3's music (then mute T3's). */
int tekken3_ttt_music_mix(int16_t *out, int frames, int audible, const int16_t main_volume[2], int gain) {
    int stage = wanted_stage();
    int cur = (int16_t)psx_mod_read_half(0x800a0620), state = psx_mod_read_half(0x800a05d8);
    int round = psx_mod_read_half(0x800add08), xa = (int16_t)psx_mod_read_half(0x800a061c);
    /* The next fight may be decided while T3's music of this one still
     * plays, fading out (Team Battle: the next fighter's loading screen
     * comes during the fade). The piece goes on with that music, whatever
     * the next fight's stage and version, until T3 stops it (B118). */
    int tail = playing_piece() && !pl.paused && cur >= 0 && cur == pl.last_cur && cur != round
               && (state == 2 || state == 3);
    /* REMIXED: the PS2 piece when installed; else, and with ARCADE, the arcade one */
    int ps2_piece = tail ? pl.ps2 : remixed() ? ps2_of_stage(stage) : -1;
    int piece = tail ? pl.piece : ps2_piece >= 0 ? -1 : piece_of_stage(stage);
    if (piece < 0 && ps2_piece < 0) { if (playing_piece()) stop("no TTT stage"); return 0; }
    int playing = cur >= 0 && (cur == round || tail) && (state == 2 || state == 3);
    if (!playing) {
        /* 0x8006B54C(1): stopped with a resume point that 0x8006AE14 takes back */
        if (playing_piece() && !pl.paused && cur < 0 && (int32_t)psx_mod_read_word(0x800a0630) == pl.last_cur
            && (int32_t)psx_mod_read_word(0x800a062c) > 0) {
            pl.paused = 1;
            fprintf(stderr, "TTT music: %s 0x%02X paused with T3's music\n", piece_kind(), piece_number());
        } else if (playing_piece() && !pl.paused) stop("T3's music stopped");
        return 0;
    }
    if (pl.piece != piece || pl.ps2 != ps2_piece || (!pl.paused && cur != pl.last_cur)) {
        start(piece, ps2_piece);
        fprintf(stderr, "TTT music: %s 0x%02X for T3's music 0x%02X\n", piece_kind(), piece_number(), cur);
    }
    if (pl.ps2 >= 0 && !ps2_data(pl.ps2)) { stop("PS2 piece unreadable"); return 0; }
    pl.paused = 0;
    pl.last_cur = cur;
    if (pl.waiting) {
        if (xa != 1) return 1;                    /* T3's XA not audible yet */
        pl.waiting = 0;
        fprintf(stderr, "TTT music: %s 0x%02X audible\n", piece_kind(), piece_number());
    }
    /* T3's XA level through DsMix (0x8006BA44): 0x80097F04 = 0 is mono,
     * 80 % of the level from both sides; then the SPU's CD input volume. */
    int level = (int16_t)psx_mod_read_half(0x800a068c), mono = !psx_mod_read_byte(0x80097f04);
    int mix = mono ? level * 80 / 100 : level;
    int cd_l = (int16_t)spu_read(0x1f801db0), cd_r = (int16_t)spu_read(0x1f801db2);
    int cd_on = spu_read(0x1f801daa) & 1, boost = gain_percent();
    /* A PS2 piece at its driver's volume (0x3FFF = full): about T3's XA level. */
    int32_t scale = pl.ps2 >= 0 ? (int32_t)ps2.p[pl.ps2].volume : boost, unit = pl.ps2 >= 0 ? 0x3fff : 100;
    for (int f = 0; f < frames; f++) {
        int16_t s[2];
        if (pl.ps2 >= 0) ps2_sample(s);
        else resample(s);
        dump(s);
        if (!audible || !cd_on || xa != 1) continue;
        int32_t x[2];
        for (int ch = 0; ch < 2; ch++) {
            int32_t v = s[ch] * scale / unit;
            x[ch] = v > 32767 ? 32767 : v < -32768 ? -32768 : v;
        }
        int32_t l = mono ? ((x[0] * mix) >> 7) + ((x[1] * mix) >> 7) : (x[0] * mix) >> 7;
        int32_t r = mono ? l : (x[1] * mix) >> 7;
        int32_t y[2] = { l > 32767 ? 32767 : l < -32768 ? -32768 : l, r > 32767 ? 32767 : r < -32768 ? -32768 : r };
        y[0] = (y[0] * cd_l) >> 15;
        y[1] = (y[1] * cd_r) >> 15;
        for (int ch = 0; ch < 2; ch++) {
            int32_t v = y[ch] * gain / 100 * main_volume[ch] / 32768, m = out[f * 2 + ch] + v;
            out[f * 2 + ch] = (int16_t)(m > 32767 ? 32767 : m < -32768 ? -32768 : m);
        }
    }
    return 1;
}

/* ---- Save states (BS_SEC_MOD_AUDIO) ---- */

static uint32_t state_bytes(void) { return playing_piece() ? (uint32_t)sizeof pl : 0u; }
static void state_write(uint8_t *p) { memcpy(p, &pl, sizeof pl); }
/* A state of the arcade pieces' player alone (before the PS2 pieces) reads too. */
static int state_read(const uint8_t *p, uint32_t len) {
    Player in;
    memset(&in, 0, sizeof in);
    in.ps2 = -1;
    if (len != sizeof in && len != PLAYER_S5_SIZE) return 0;
    memcpy(&in, p, len);
    if (in.magic != PLAYER_MAGIC || in.size != len) return 0;
    in.size = sizeof in;
    if (in.ps2 >= 0) {
        if (in.piece >= 0 || !ps2_load() || in.ps2 >= ps2.count || in.ps2_pos >= ps2.p[in.ps2].sectors * SECTOR_SAMPLES
            || !ps2_data(in.ps2)) { pl.piece = pl.ps2 = -1; return 1; }
        pl = in;
        fprintf(stderr, "TTT music: PS2 piece 0x%02X back from a save state at %.2f s\n", ps2.p[pl.ps2].number,
                pl.ps2_pos / 44100.0);
        return 1;
    }
    if (in.piece < 0 || !load() || in.piece >= lib.count) { pl.piece = pl.ps2 = -1; return 1; }
    pl = in;
    fprintf(stderr, "TTT music: piece 0x%02X back from a save state at %.2f s\n", lib.pieces[pl.piece].number,
            (double)(pl.d - (int64_t)lib.out_start) / 44100.0);
    return 1;
}

/* Every SPU state read (save state, rollback): the player goes with it; the
 * MOD_AUDIO section, read after, brings it back when it was playing. */
void tekken3_ttt_music_state_reset(void) {
    register_state();
    pl.piece = pl.ps2 = -1;
}
