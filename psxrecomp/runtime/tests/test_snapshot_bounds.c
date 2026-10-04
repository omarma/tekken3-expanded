/*
 * Savestate restore must refuse cursors/counts that would index past the
 * fixed buffers the live device code uses (sio mc_data[128], gpu
 * gp0_cmd_buf[16], cdrom FIFOs/sector buffer, spu samples[28], mdec input[]).
 * Each case starts from a genuine snapshot, which must round-trip, then
 * corrupts one field and expects the module reader to return 0 — and the
 * rejected value must not have become live (a re-snapshot still shows the
 * previous, in-range value).
 *
 * Build/run: ctest -R snapshot_bounds_test
 */
#include "sio.h"
#include "gpu.h"
#include "cdrom.h"
#include "spu.h"
#include "mdec.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint32_t sio_snapshot_bytes(void);
void     sio_snapshot_write(uint8_t *p);
int      sio_snapshot_read(const uint8_t *p, uint32_t len);
void     sio_snapshot_section_ends(uint32_t out[5]);
uint32_t gpu_snapshot_bytes(void);
void     gpu_snapshot_write(uint8_t *p);
int      gpu_snapshot_read(const uint8_t *p, uint32_t len);
uint32_t cdrom_snapshot_bytes(void);
uint32_t mdec_snapshot_bytes(void);

static int failures;
static int checks;

#define EXPECT(label, want, got) do {                                         \
    long long w_ = (long long)(want), g_ = (long long)(got);                  \
    checks++;                                                                 \
    if (w_ != g_) {                                                           \
        fprintf(stderr, "FAIL %s: want %lld got %lld\n", (label), w_, g_);     \
        failures++;                                                           \
    }                                                                         \
} while (0)

static void put_u32(uint8_t *p, uint32_t off, uint32_t v) {
    p[off] = (uint8_t)v; p[off + 1] = (uint8_t)(v >> 8);
    p[off + 2] = (uint8_t)(v >> 16); p[off + 3] = (uint8_t)(v >> 24);
}
static uint32_t get_u32(const uint8_t *p, uint32_t off) {
    return (uint32_t)p[off] | ((uint32_t)p[off + 1] << 8) |
           ((uint32_t)p[off + 2] << 16) | ((uint32_t)p[off + 3] << 24);
}

typedef uint32_t (*SnapBytesFn)(void);
typedef void     (*SnapWriteFn)(uint8_t *p);
typedef int      (*SnapReadFn)(const uint8_t *p, uint32_t len);

typedef struct {
    const char *name;
    SnapBytesFn bytes;
    SnapWriteFn write;
    SnapReadFn  read;
    uint8_t    *base;   /* genuine snapshot of the current state */
    uint32_t    len;
} Snap;

static void snap_take(Snap *s) {
    s->len = s->bytes();
    free(s->base);
    s->base = (uint8_t *)calloc(1, s->len ? s->len : 1);
    if (!s->base) { fprintf(stderr, "FAIL %s: alloc\n", s->name); exit(1); }
    s->write(s->base);
}

/* Unmodified snapshot loads and re-serializes byte-identically. */
static void snap_roundtrip(Snap *s) {
    char label[96];
    uint8_t *again;
    snprintf(label, sizeof label, "%s.roundtrip.read", s->name);
    EXPECT(label, 1, s->read(s->base, s->len));
    again = (uint8_t *)calloc(1, s->len ? s->len : 1);
    if (!again) exit(1);
    snprintf(label, sizeof label, "%s.roundtrip.len", s->name);
    EXPECT(label, s->len, s->bytes());
    s->write(again);
    snprintf(label, sizeof label, "%s.roundtrip.bytes", s->name);
    EXPECT(label, 0, memcmp(again, s->base, s->len));
    free(again);
}

/* Load base with u32 fields overwritten; return the reader's verdict. When
 * the load is refused, also require that re-snapshotting still reports the
 * base value at every patched offset (the bad value never became live). */
static int snap_try(Snap *s, const char *what, int n,
                    const uint32_t *offs, const uint32_t *vals, int want) {
    char label[128];
    uint8_t *b = (uint8_t *)malloc(s->len);
    int ok;
    if (!b) exit(1);
    memcpy(b, s->base, s->len);
    for (int k = 0; k < n; k++) put_u32(b, offs[k], vals[k]);
    ok = s->read(b, s->len);
    snprintf(label, sizeof label, "%s.%s", s->name, what);
    EXPECT(label, want, ok);
    if (!ok && s->bytes() == s->len) {
        s->write(b);
        for (int k = 0; k < n; k++) {
            snprintf(label, sizeof label, "%s.%s.not_live[%d]", s->name, what, k);
            if (get_u32(b, offs[k]) == vals[k] && get_u32(s->base, offs[k]) != vals[k])
                EXPECT(label, get_u32(s->base, offs[k]), get_u32(b, offs[k]));
        }
    }
    free(b);
    /* Put the module back on the genuine state for the next case. */
    (void)s->read(s->base, s->len);
    return ok;
}
#define TRY1(s, what, off, val, want) do {                                    \
    const uint32_t o_[1] = { (off) }, v_[1] = { (uint32_t)(val) };            \
    (void)snap_try((s), (what), 1, o_, v_, (want));                           \
} while (0)
#define TRY2(s, what, o1, v1, o2, v2, want) do {                              \
    const uint32_t o_[2] = { (o1), (o2) };                                    \
    const uint32_t v_[2] = { (uint32_t)(v1), (uint32_t)(v2) };                \
    (void)snap_try((s), (what), 2, o_, v_, (want));                           \
} while (0)
#define TRY3(s, what, o1, v1, o2, v2, o3, v3, want) do {                      \
    const uint32_t o_[3] = { (o1), (o2), (o3) };                              \
    const uint32_t v_[3] = { (uint32_t)(v1), (uint32_t)(v2), (uint32_t)(v3) };\
    (void)snap_try((s), (what), 3, o_, v_, (want));                           \
} while (0)

/* ---- SIO ---------------------------------------------------------------- */
/* McState values (sio.c enum order). */
enum { MC_IDLE_ = 0, MC_READ_DATA_ = 10, MC_READ_CHK_ = 11,
       MC_WRITE_LSB_ECHO_ = 13, MC_WRITE_DATA_ = 14, MC_WRITE_CHK_ = 15 };

static void test_sio(void) {
    Snap s = { "sio", sio_snapshot_bytes, sio_snapshot_write, sio_snapshot_read, NULL, 0 };
    uint32_t ends[5];
    uint32_t sel, mc, mc_state, mc_slot, mc_idx, slot0, slot0_state, slot0_idx;
    sio_init();
    snap_take(&s);
    snap_roundtrip(&s);
    sio_snapshot_section_ends(ends);
    /* pads: analog[N] u8 connected, u32 pad_state, i32 selected_slot, ... */
    sel = ends[0] + PSX_MAX_PLAYERS + 1u + 4u;
    /* memcard: u32 state, i32 slot, u8 cmd, u16 sector, u8 msb, u8 lsb,
     * data[128], i32 data_idx, u8 checksum, u8 flag, then 2 x McSlotState
     * (u32 state, u8, u16, u8, u8, data[128], i32 data_idx, u8, u8), u32 dev. */
    mc = ends[1];
    EXPECT("sio.layout.memcard_bytes", 141u + 4u + 2u + 2u * 143u + 4u, ends[2] - ends[1]);
    mc_state = mc; mc_slot = mc + 4u; mc_idx = mc + 141u;
    slot0 = mc + 147u; slot0_state = slot0; slot0_idx = slot0 + 137u;

    TRY1(&s, "selected_slot.1", sel, 1, 1);
    TRY1(&s, "selected_slot.2", sel, 2, 0);
    TRY1(&s, "selected_slot.neg", sel, -1, 0);
    TRY1(&s, "mc_slot.1", mc_slot, 1, 1);
    TRY1(&s, "mc_slot.2", mc_slot, 2, 0);
    TRY1(&s, "mc_slot.neg", mc_slot, 0x80000000u, 0);
    /* data_idx reaches 128 only once the data phase has handed over to *_CHK. */
    TRY2(&s, "mc_data_idx.write_data.127", mc_state, MC_WRITE_DATA_, mc_idx, 127, 1);
    TRY2(&s, "mc_data_idx.write_chk.128", mc_state, MC_WRITE_CHK_, mc_idx, 128, 1);
    TRY2(&s, "mc_data_idx.read_chk.128", mc_state, MC_READ_CHK_, mc_idx, 128, 1);
    TRY2(&s, "mc_data_idx.idle.128", mc_state, MC_IDLE_, mc_idx, 128, 1);
    TRY2(&s, "mc_data_idx.write_data.128", mc_state, MC_WRITE_DATA_, mc_idx, 128, 0);
    TRY2(&s, "mc_data_idx.read_data.128", mc_state, MC_READ_DATA_, mc_idx, 128, 0);
    TRY2(&s, "mc_data_idx.lsb_echo.128", mc_state, MC_WRITE_LSB_ECHO_, mc_idx, 128, 0);
    TRY2(&s, "mc_data_idx.idle.129", mc_state, MC_IDLE_, mc_idx, 129, 0);
    TRY2(&s, "mc_data_idx.write_data.130", mc_state, MC_WRITE_DATA_, mc_idx, 130, 0);
    TRY1(&s, "mc_data_idx.neg", mc_idx, -1, 0);
    TRY2(&s, "slot0.data_idx.read_data.5", slot0_state, MC_READ_DATA_, slot0_idx, 5, 1);
    TRY2(&s, "slot0.data_idx.read_data.128", slot0_state, MC_READ_DATA_, slot0_idx, 128, 0);
    TRY1(&s, "slot0.data_idx.4096", slot0_idx, 4096, 0);
    free(s.base);
}

/* ---- GPU ---------------------------------------------------------------- */
/* Wire = u32 fields in gpu_snap_emit order. */
#define GPU_OFF_TEXPAGE_X     0u
#define GPU_OFF_DRAW_AREA_L  48u
#define GPU_OFF_DISPLAY_X   112u
#define GPU_OFF_DISPLAY_Y   116u
#define GPU_OFF_GP0_STATE   140u
#define GPU_OFF_COLLECTED   208u
#define GPU_OFF_NEEDED      212u
enum { GP0_IDLE_ = 0, GP0_COLLECTING_ = 1 };

static void test_gpu(void) {
    Snap s = { "gpu", gpu_snapshot_bytes, gpu_snapshot_write, gpu_snapshot_read, NULL, 0 };
    gpu_init();
    /* Pin the wire offsets with real register writes: GP1(05h) display area,
     * then the first word of a 4-word mono triangle (GP0 0x20) leaves the
     * collector mid-command (collected=1, needed=4). */
    gpu_write_gp1(0x05000000u | (0x1ABu << 10) | 0x2CDu);
    gpu_write_gp0(0x20112233u);
    snap_take(&s);
    EXPECT("gpu.layout.display_x", 0x2CD, get_u32(s.base, GPU_OFF_DISPLAY_X));
    EXPECT("gpu.layout.display_y", 0x1AB, get_u32(s.base, GPU_OFF_DISPLAY_Y));
    EXPECT("gpu.layout.gp0_state", GP0_COLLECTING_, get_u32(s.base, GPU_OFF_GP0_STATE));
    EXPECT("gpu.layout.collected", 1, get_u32(s.base, GPU_OFF_COLLECTED));
    EXPECT("gpu.layout.needed", 4, get_u32(s.base, GPU_OFF_NEEDED));
    snap_roundtrip(&s);

    TRY2(&s, "gp0.collecting.3of4", GPU_OFF_COLLECTED, 3, GPU_OFF_NEEDED, 4, 1);
    TRY2(&s, "gp0.collecting.15of16", GPU_OFF_COLLECTED, 15, GPU_OFF_NEEDED, 16, 1);
    TRY3(&s, "gp0.idle.done.12of12", GPU_OFF_GP0_STATE, GP0_IDLE_,
         GPU_OFF_COLLECTED, 12, GPU_OFF_NEEDED, 12, 1);
    TRY3(&s, "gp0.idle.reset", GPU_OFF_GP0_STATE, GP0_IDLE_,
         GPU_OFF_COLLECTED, 0, GPU_OFF_NEEDED, 0, 1);
    TRY2(&s, "gp0.collecting.4of4", GPU_OFF_COLLECTED, 4, GPU_OFF_NEEDED, 4, 0);
    TRY2(&s, "gp0.collecting.16of16", GPU_OFF_COLLECTED, 16, GPU_OFF_NEEDED, 16, 0);
    TRY2(&s, "gp0.collecting.16of17", GPU_OFF_COLLECTED, 16, GPU_OFF_NEEDED, 17, 0);
    TRY1(&s, "gp0.collected.huge", GPU_OFF_COLLECTED, 0x10000, 0);
    TRY1(&s, "gp0.collected.neg", GPU_OFF_COLLECTED, -1, 0);
    TRY3(&s, "gp0.idle.collected_gt_needed", GPU_OFF_GP0_STATE, GP0_IDLE_,
         GPU_OFF_COLLECTED, 9, GPU_OFF_NEEDED, 4, 0);
    TRY1(&s, "display_x.3ff", GPU_OFF_DISPLAY_X, 0x3FF, 1);
    TRY1(&s, "display_x.400", GPU_OFF_DISPLAY_X, 0x400, 0);
    TRY1(&s, "display_y.200", GPU_OFF_DISPLAY_Y, 0x200, 0);
    TRY1(&s, "texpage_x.10", GPU_OFF_TEXPAGE_X, 0x10, 0);
    TRY1(&s, "draw_area_left.400", GPU_OFF_DRAW_AREA_L, 0x400, 0);
    free(s.base);
}

/* ---- CD-ROM ------------------------------------------------------------- */
/* 5 x u8 regs, i32, u32, u32, i32, param_fifo[16], i32 param_count,
 * response_fifo[16], i32 read, i32 count, sector_buffer[2340], i32 pos,
 * i32 available, i32 size, last_sector_buffer[2340], i32 lba, i32 size. */
#define CD_OFF_PARAM_COUNT      37u
#define CD_OFF_RESPONSE_READ    57u
#define CD_OFF_RESPONSE_COUNT   61u
#define CD_OFF_SECTOR_POS     2405u
#define CD_OFF_SECTOR_SIZE    2413u
#define CD_OFF_LAST_SIZE      4761u
#define CD_SECTOR_BUFFER_SIZE 2340

static void test_cdrom(void) {
    Snap s = { "cdrom", cdrom_snapshot_bytes, cdrom_snapshot_write, cdrom_snapshot_read, NULL, 0 };
    cdrom_init(NULL);
    /* Index 0, then two parameter bytes: pins param_count's wire offset. */
    cdrom_write(0x1F801800u, 0);
    cdrom_write(0x1F801802u, 0x11);
    cdrom_write(0x1F801802u, 0x22);
    snap_take(&s);
    EXPECT("cdrom.layout.param_count", 2, get_u32(s.base, CD_OFF_PARAM_COUNT));
    EXPECT("cdrom.layout.param0", 0x11, s.base[CD_OFF_PARAM_COUNT - 16u]);
    snap_roundtrip(&s);

    TRY1(&s, "param_count.16", CD_OFF_PARAM_COUNT, 16, 1);
    TRY1(&s, "param_count.17", CD_OFF_PARAM_COUNT, 17, 0);
    TRY1(&s, "param_count.neg", CD_OFF_PARAM_COUNT, -1, 0);
    TRY2(&s, "response.16of16", CD_OFF_RESPONSE_READ, 16, CD_OFF_RESPONSE_COUNT, 16, 1);
    TRY1(&s, "response_count.17", CD_OFF_RESPONSE_COUNT, 17, 0);
    TRY1(&s, "response_read.neg", CD_OFF_RESPONSE_READ, -5, 0);
    TRY2(&s, "sector.full", CD_OFF_SECTOR_POS, CD_SECTOR_BUFFER_SIZE,
         CD_OFF_SECTOR_SIZE, CD_SECTOR_BUFFER_SIZE, 1);
    TRY1(&s, "sector_size.over", CD_OFF_SECTOR_SIZE, CD_SECTOR_BUFFER_SIZE + 1, 0);
    TRY1(&s, "sector_size.huge", CD_OFF_SECTOR_SIZE, 0x7FFFFFFF, 0);
    TRY1(&s, "sector_pos.neg", CD_OFF_SECTOR_POS, -4, 0);
    TRY1(&s, "last_sector_size.over", CD_OFF_LAST_SIZE, 1 << 20, 0);
    free(s.base);
}

/* ---- SPU ---------------------------------------------------------------- */
#define SPU_VOICES          24u
#define SPU_VOICE_WIRE     106u
#define SPU_TAIL_WIRE       64u
#define SPU_VOICE_IDX_OFF   74u  /* active, cur, repeat, samples[28], prev[3] */

static void test_spu(void) {
    Snap s = { "spu", spu_snapshot_bytes, spu_snapshot_write, spu_snapshot_read, NULL, 0 };
    uint32_t regs, v5_idx, cap;
    spu_init();
    snap_take(&s);
    snap_roundtrip(&s);
    regs = s.len - SPU_VOICES * SPU_VOICE_WIRE - SPU_TAIL_WIRE;
    EXPECT("spu.layout.regs", 512, regs);
    v5_idx = regs + 5u * SPU_VOICE_WIRE + SPU_VOICE_IDX_OFF;
    cap = s.len - 12u - 4u;   /* capture_pos precedes the 2 main sweep envs */
    TRY1(&s, "sample_idx.28", v5_idx, 28, 1);
    TRY1(&s, "sample_idx.neg", v5_idx, -100, 0);
    TRY1(&s, "sample_idx.29", v5_idx, 29, 0);
    TRY1(&s, "capture_pos.3fe", cap, 0x3FE, 1);
    TRY1(&s, "capture_pos.huge", cap, 0x7FFFF, 0);
    free(s.base);
}

/* ---- MDEC --------------------------------------------------------------- */
#define MDEC_OFF_EXPECTED 8u   /* ver, command, expected_halfwords */

extern uint64_t psx_cycle_count;

static void test_mdec(void) {
    Snap s = { "mdec", mdec_snapshot_bytes, mdec_snapshot_write, mdec_snapshot_read, NULL, 0 };
    /* Past the first 1000 cycles so the colour-decode age (rebased on load
     * from psx_cycle_count) re-serializes to the same value. */
    psx_cycle_count = 100000000u;
    mdec_init();
    snap_take(&s);
    snap_roundtrip(&s);
    TRY1(&s, "expected.decode_max", MDEC_OFF_EXPECTED, 0xFFFFu * 2u, 1);
    TRY1(&s, "expected.over", MDEC_OFF_EXPECTED, 0xFFFFu * 2u + 2u, 0);
    TRY1(&s, "expected.huge", MDEC_OFF_EXPECTED, 0xFFFFFFF0u, 0);
    free(s.base);
}

int main(void) {
    test_sio();
    test_gpu();
    test_cdrom();
    test_spu();
    test_mdec();
    if (failures) {
        fprintf(stderr, "snapshot_bounds_test: %d of %d checks FAILED\n", failures, checks);
        return 1;
    }
    printf("snapshot_bounds_test: all %d checks passed\n", checks);
    return 0;
}

/* ======================================================================== *
 * Link stubs: the five device modules are linked as-is; everything they    *
 * reach outside themselves (renderer, debug server, netplay, ISO reader,   *
 * CPU bus) is inert here. None of it is on the snapshot path under test.   *
 * ======================================================================== */
uint32_t i_stat, i_mask;
uint32_t g_debug_current_func_addr, g_debug_last_store_pc;
int      g_exec_phase;
int      g_psx_vram_dirty_tracking;
uint64_t psx_cycle_count;
uint64_t s_frame_count;
void    *debug_cpu_ptr;
static uint8_t s_ram[2u * 1024u * 1024u];

void audio_trace_event(uint16_t kind, uint32_t a, uint32_t b) { (void)kind; (void)a; (void)b; }
void audio_trace_pcm(int tap, const int16_t *stereo, int frames) { (void)tap; (void)stereo; (void)frames; }
void card_data_writes_arm(uint8_t value, uint16_t mc_state, uint8_t mc_data_idx, uint8_t slot) {
    (void)value; (void)mc_state; (void)mc_data_idx; (void)slot;
}
void card_read_summary_record(uint8_t slot, uint8_t cmd, uint16_t sector, uint8_t checksum,
                              uint8_t data_idx, const uint8_t *data128) {
    (void)slot; (void)cmd; (void)sector; (void)checksum; (void)data_idx; (void)data128;
}
uint32_t debug_guest_ra(void) { return 0; }
uint32_t debug_guest_sp(void) { return 0; }
int  debug_server_fmv_quiet(void) { return 1; }
void debug_server_log_sio_write(uint32_t addr, uint32_t value, uint8_t width) {
    (void)addr; (void)value; (void)width;
}
void debug_server_poll(void) {}
void disc_sector_log_used(uint32_t lba) { (void)lba; }
int  dma_cdrom_transfer_active(void) { return 0; }
void event_ring_record(uint16_t kind, uint8_t detail) { (void)kind; (void)detail; }
void event_ring_record_aux(uint16_t kind, uint8_t detail, uint32_t aux) {
    (void)kind; (void)detail; (void)aux;
}
void gpu_vram_dirty_mark_all(void) {}
void gpu_vram_dirty_mark_row_impl(uint32_t y) { (void)y; }
void gr_copy_rect(int a, int b, int c, int d, int e, int f) {
    (void)a; (void)b; (void)c; (void)d; (void)e; (void)f;
}
void gr_draw_flat_rect(int x, int y, int w, int h, uint16_t c) { (void)x; (void)y; (void)w; (void)h; (void)c; }
void gr_draw_flat_triangle(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t c) {
    (void)x0; (void)y0; (void)x1; (void)y1; (void)x2; (void)y2; (void)c;
}
void gr_draw_gouraud_triangle(int x0, int y0, uint16_t c0, int x1, int y1, uint16_t c1,
                              int x2, int y2, uint16_t c2) {
    (void)x0; (void)y0; (void)c0; (void)x1; (void)y1; (void)c1; (void)x2; (void)y2; (void)c2;
}
void gr_draw_line(int x0, int y0, int x1, int y1, uint16_t c) { (void)x0; (void)y0; (void)x1; (void)y1; (void)c; }
void gr_draw_shaded_line(int x0, int y0, uint16_t c0, int x1, int y1, uint16_t c1) {
    (void)x0; (void)y0; (void)c0; (void)x1; (void)y1; (void)c1;
}
void gr_draw_shaded_textured_triangle(int x0, int y0, int u0, int v0, uint32_t c0,
                                      int x1, int y1, int u1, int v1, uint32_t c1,
                                      int x2, int y2, int u2, int v2, uint32_t c2,
                                      uint16_t clut_x, uint16_t clut_y, uint16_t texpage,
                                      int raw_texture) {
    (void)x0; (void)y0; (void)u0; (void)v0; (void)c0; (void)x1; (void)y1; (void)u1;
    (void)v1; (void)c1; (void)x2; (void)y2; (void)u2; (void)v2; (void)c2;
    (void)clut_x; (void)clut_y; (void)texpage; (void)raw_texture;
}
void gr_draw_textured_rect(int x, int y, int w, int h, int u, int v,
                           uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    (void)x; (void)y; (void)w; (void)h; (void)u; (void)v; (void)clut_x; (void)clut_y; (void)texpage;
}
void gr_draw_textured_rect_scaled(int x, int y, int w, int h, int u0, int v0, int u1, int v1,
                                  uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    (void)x; (void)y; (void)w; (void)h; (void)u0; (void)v0; (void)u1; (void)v1;
    (void)clut_x; (void)clut_y; (void)texpage;
}
void gr_draw_textured_triangle(int x0, int y0, int u0, int v0, int x1, int y1, int u1, int v1,
                               int x2, int y2, int u2, int v2,
                               uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    (void)x0; (void)y0; (void)u0; (void)v0; (void)x1; (void)y1; (void)u1; (void)v1;
    (void)x2; (void)y2; (void)u2; (void)v2; (void)clut_x; (void)clut_y; (void)texpage;
}
void gr_fill_rect(int x, int y, int w, int h, uint16_t c) { (void)x; (void)y; (void)w; (void)h; (void)c; }
void gr_init(uint16_t *vram) { (void)vram; }
void gr_set_color_modulation(int r, int g, int b, int raw) { (void)r; (void)g; (void)b; (void)raw; }
void gr_set_draw_area(int x1, int y1, int x2, int y2) { (void)x1; (void)y1; (void)x2; (void)y2; }
void gr_set_draw_offset(int x, int y) { (void)x; (void)y; }
void gr_set_mask_bits(int set_bit, int check_bit) { (void)set_bit; (void)check_bit; }
void gr_set_perspective_triangle(int enabled, float q0, float q1, float q2) {
    (void)enabled; (void)q0; (void)q1; (void)q2;
}
void gr_set_precise_triangle(int enabled, int32_t x0, int32_t y0, int32_t x1, int32_t y1,
                             int32_t x2, int32_t y2) {
    (void)enabled; (void)x0; (void)y0; (void)x1; (void)y1; (void)x2; (void)y2;
}
void gr_set_semi_transparency(int enabled, int mode) { (void)enabled; (void)mode; }
void gr_set_texture_window(uint32_t raw) { (void)raw; }
uint16_t gr_vram_read(int x, int y) { (void)x; (void)y; return 0; }
void gr_vram_transfer_in(int x, int y, int w, int h, const uint16_t *data) {
    (void)x; (void)y; (void)w; (void)h; (void)data;
}
void gr_wide_clear(int base_x, int y, int h, uint16_t c) { (void)base_x; (void)y; (void)h; (void)c; }
void gr_wide_clear_margins(int base_x, int y, int h, uint16_t c, int sides) {
    (void)base_x; (void)y; (void)h; (void)c; (void)sides;
}
void gr_wide_configure(int wide_w, int offset) { (void)wide_w; (void)offset; }
void gr_wide_disable_target(void) {}
void gr_wide_set_mirror_authoritative(int v) { (void)v; }
void gr_wide_set_primitive_expanded(int v) { (void)v; }
void gr_wide_set_primitive_split(int lo, int hi) { (void)lo; (void)hi; }
void gr_wide_set_primitive_suppressed(int v) { (void)v; }
void gr_wide_set_primitive_unclipped(int v) { (void)v; }
void gr_wide_set_primitive_x_delta(int v) { (void)v; }
void gr_wide_set_sidecar_complete(int v) { (void)v; }
void gr_wide_set_target(int base_x) { (void)base_x; }
int  gte_geometry_correction_enabled(void) { return 0; }
int  gte_geometry_correction_lookup(uint32_t packed, int32_t *x16, int32_t *y16) {
    (void)packed; (void)x16; (void)y16; return 0;
}
int  gte_precision_load_word(uint32_t addr, uint32_t packed, int32_t *x16, int32_t *y16,
                             uint16_t *z) {
    (void)addr; (void)packed; (void)x16; (void)y16; (void)z; return 0;
}
void gte_precision_tracking_set(int enabled) { (void)enabled; }
uint32_t interrupts_get_cycles_since_vblank(void) { return 0; }
void  iso_close(void *h) { (void)h; }
void *iso_open(const char *path) { (void)path; return NULL; }
int   iso_read_raw_sector(void *h, uint32_t lba, uint8_t *buf, int size) {
    (void)h; (void)lba; (void)buf; (void)size; return 0;
}
int   iso_read_sector(void *h, uint32_t lba, uint8_t *buf, int size) {
    (void)h; (void)lba; (void)buf; (void)size; return 0;
}
uint32_t iso_sector_count(void *h) { (void)h; return 0; }
int      iso_track_count(void *h) { (void)h; return 0; }
int      iso_track_is_audio(void *h, int t) { (void)h; (void)t; return 0; }
uint32_t iso_track_pregap_lba(void *h, int t) { (void)h; (void)t; return 0; }
uint32_t iso_track_start_lba(void *h, int t) { (void)h; (void)t; return 0; }
uint8_t *memory_get_ram_ptr(void) { return s_ram; }
uint32_t memory_get_sr(void) { return 0; }
void mod_runtime_on_vblank(void) {}
uint32_t psx_compiled_irq_resume_pc(void) { return 0; }
void psx_fatal_halt(const char *reason) {
    fprintf(stderr, "FAIL psx_fatal_halt: %s\n", reason ? reason : "?");
    exit(2);
}
uint64_t psx_get_cycle_count(void) { return psx_cycle_count; }
int  psx_get_in_exception(void) { return 0; }
void psx_irq_raise(uint32_t bit, uint32_t detail) { (void)detail; i_stat |= 1u << bit; }
uint32_t psx_last_irq_check_pc(void) { return 0; }
uint32_t psx_mod_gpu_dma_resolve_address(uint32_t a) { return a; }
int  psx_netplay_active(void) { return 0; }
int  psx_netplay_cd_bisect_active(void) { return 0; }
int  psx_netplay_is_resimulating(void) { return 0; }
uint32_t psx_netplay_rb_sticky_bb_pc(void) { return 0; }
uint32_t psx_netplay_sim_tick(void) { return 0; }
uint8_t  psx_read_byte(uint32_t a) { (void)a; return 0; }
uint16_t psx_read_half(uint32_t a) { (void)a; return 0; }
uint32_t psx_read_word(uint32_t a) { (void)a; return 0; }
void psx_write_half(uint32_t a, uint16_t v) { (void)a; (void)v; }
bool spu_shadow_enabled(void) { return false; }
void spu_shadow_process(int16_t *canon, int frames) { (void)canon; (void)frames; }
void spu_shadow_reset(void) {}
void starvation_ring_record(uint8_t kind, uint8_t tx, uint8_t rx, uint16_t ctrl, uint16_t stat,
                            int shift_active, int shift_remaining, int tx_buffered,
                            int pending_ack, int ack_remaining, uint8_t bus_owner,
                            uint32_t bus_byte_index, uint8_t active_device, uint8_t mc_state,
                            uint8_t pad_state, uint8_t selected_slot, int timing_active) {
    (void)kind; (void)tx; (void)rx; (void)ctrl; (void)stat; (void)shift_active;
    (void)shift_remaining; (void)tx_buffered; (void)pending_ack; (void)ack_remaining;
    (void)bus_owner; (void)bus_byte_index; (void)active_device; (void)mc_state;
    (void)pad_state; (void)selected_slot; (void)timing_active;
}
uint32_t sw_perspective_triangle_count(void) { return 0; }
int  tekken3_outfits_available(void) { return 0; }
void text_xlate_vram_upload(int x, int y, int w, int h) { (void)x; (void)y; (void)w; (void)h; }
