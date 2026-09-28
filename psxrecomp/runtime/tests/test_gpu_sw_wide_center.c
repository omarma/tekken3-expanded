/* White-box regression for the software native-wide present source.
 *
 * Include the renderer implementation so this focused test can exercise the
 * real sidecar state without adding test-only hooks to the production ABI. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "native_wide_present_authority.h"

int g_ws_bd_stretch_on;
int g_ws_bd_stretch_pct;
int psx_ws_prim_in_backdrop(void) { return 0; }

#include "../src/gpu_sw_renderer.c"

static int failures;
#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "FAIL: %s\n", message); failures++; } \
} while (0)

static void expect_pixel(uint32_t actual, uint16_t expected, const char *message) {
    CHECK(actual == rgb555_to_argb(expected), message);
}

static void test_native_wrap_and_margins(void) {
    static uint16_t vram[VRAM_WIDTH * VRAM_HEIGHT];
    uint32_t out[6] = {0};
    const uint16_t center[4] = { 0x001f, 0x03e0, 0x7c00, 0x7fff };
    const uint16_t margin = 0x4210;

    memset(vram, 0, sizeof(vram));
    sw_renderer_init(vram);
    sw_renderer_set_scale(1);
    sw_set_draw_area(0, 0, VRAM_WIDTH - 1, VRAM_HEIGHT - 1);
    sw_wide_configure(6, 1); /* four canonical pixels + one reveal each side */
    sw_wide_set_target(1022);
    sw_wide_clear(1022, 0, 1, margin);

    /* Direct canonical writes model a CPU upload / VRAM copy that is not a
     * drawing primitive and therefore is not mirrored into the sidecar. */
    vram[1022] = center[0];
    vram[1023] = center[1];
    vram[0] = center[2];
    vram[1] = center[3];

    CHECK(sw_render_wide_display(out, (int)sizeof(out), 1022, 0, 1) == 6,
          "native wide present writes the complete row");
    expect_pixel(out[0], margin, "left synthetic margin is preserved");
    for (int i = 0; i < 4; i++)
        expect_pixel(out[i + 1], center[i], "canonical centre is wrap-safe");
    expect_pixel(out[5], margin, "right synthetic margin is preserved");
}

static void test_zero_offset_identity(void) {
    static uint16_t vram[VRAM_WIDTH * VRAM_HEIGHT];
    uint32_t out[4] = {0};
    const uint16_t center[4] = { 0x0001, 0x0020, 0x0400, 0x7fff };

    memset(vram, 0, sizeof(vram));
    sw_renderer_init(vram);
    sw_renderer_set_scale(1);
    sw_wide_configure(4, 0);
    sw_wide_set_target(40);
    sw_wide_clear(40, 0, 1, 0x1234);
    memcpy(vram + 40, center, sizeof(center));

    CHECK(sw_render_wide_display(out, (int)sizeof(out), 40, 0, 1) == 4,
          "zero-offset present writes the complete row");
    for (int i = 0; i < 4; i++)
        expect_pixel(out[i], center[i], "zero-offset centre is exact identity");
}

static void test_supersampled_center(void) {
    static uint16_t vram[VRAM_WIDTH * VRAM_HEIGHT];
    uint32_t out[24] = {0};
    const uint16_t center[4] = { 0x0005, 0x00a0, 0x1400, 0x2d6b };
    const uint16_t margin = 0x4631;

    memset(vram, 0, sizeof(vram));
    sw_renderer_init(vram);
    sw_renderer_set_scale(2);
    sw_set_draw_area(0, 0, VRAM_WIDTH - 1, VRAM_HEIGHT - 1);
    sw_wide_configure(6, 1);
    sw_wide_set_target(1022);
    sw_wide_clear(1022, 0, 1, margin);
    sw_vram_transfer_in(1022, 0, 2, 1, center);
    sw_vram_transfer_in(0, 0, 2, 1, center + 2);

    CHECK(sw_render_wide_display(out, 12 * (int)sizeof(uint32_t), 1022, 0, 1) == 24,
          "supersampled wide present writes the complete row");
    expect_pixel(out[0], margin, "supersampled left margin pixel 0 is preserved");
    expect_pixel(out[1], margin, "supersampled left margin pixel 1 is preserved");
    for (int i = 0; i < 4; i++) {
        expect_pixel(out[2 + i * 2], center[i],
                     "supersampled canonical pixel first sample is exact");
        expect_pixel(out[3 + i * 2], center[i],
                     "supersampled canonical pixel second sample is exact");
    }
    expect_pixel(out[10], margin, "supersampled right margin pixel 0 is preserved");
    expect_pixel(out[11], margin, "supersampled right margin pixel 1 is preserved");

    sw_renderer_set_scale(1);
}

static void test_present_authority_policy(void) {
    CHECK(psx_ws_wide_mirror_authority_allowed(1, 1, 0),
          "opted full-mirror gameplay makes the sidecar authoritative");
    CHECK(!psx_ws_wide_mirror_authority_allowed(0, 1, 0),
          "default fast mode retains the canonical centre splice");
    CHECK(!psx_ws_wide_mirror_authority_allowed(1, 0, 0),
          "4:3/non-wide presentation never grants sidecar authority");
    CHECK(!psx_ws_wide_mirror_authority_allowed(1, 1, 1),
          "quiet 2D restores splice for CPU uploads and VRAM copies");

    CHECK(psx_ws_wide_center_splice_required(1, 1, 0),
          "GL fast mode cannot skip a centre it did not mirror");
    CHECK(!psx_ws_wide_center_splice_required(1, 1, 1),
          "proven complete fast sidecar may own its centre");
    CHECK(!psx_ws_wide_center_splice_required(0, 1, 0),
          "complete authoritative mirror bypasses the centre splice");
    CHECK(psx_ws_wide_center_splice_required(0, 0, 1),
          "non-authoritative complete mirror still splices quiet 2D");
    CHECK(!psx_ws_wide_duplicate_present_may_skip(1),
          "authoritative mirror cannot reuse a canonically clean prior swap");
    CHECK(psx_ws_wide_duplicate_present_may_skip(0),
          "non-authoritative 2D retains the duplicate-present optimization");
}

static void test_full_mirror_present_and_dump(void) {
    static uint16_t vram[VRAM_WIDTH * VRAM_HEIGHT];
    static uint32_t dump[6 * VRAM_HEIGHT];
    uint32_t out[6] = {0};
    const uint16_t sidecar = 0x56b5;
    const uint16_t canonical[4] = { 0x001f, 0x03e0, 0x7c00, 0x7fff };
    int ow = 0, oh = 0;

    memset(vram, 0, sizeof(vram));
    memset(dump, 0, sizeof(dump));
    sw_renderer_init(vram);
    sw_renderer_set_scale(1);
    sw_set_draw_area(0, 0, VRAM_WIDTH - 1, VRAM_HEIGHT - 1);
    sw_wide_configure(6, 1);
    sw_wide_set_target(100);
    sw_wide_clear(100, 0, VRAM_HEIGHT, sidecar);
    memcpy(vram + 100, canonical, sizeof(canonical));

    sw_wide_set_mirror_authoritative(1);
    CHECK(sw_render_wide_display(out, (int)sizeof(out), 100, 0, 1) == 6,
          "authoritative full mirror presents a complete row");
    for (int i = 0; i < 6; i++)
        expect_pixel(out[i], sidecar,
                     "gameplay present preserves independently rasterized centre");

    CHECK(sw_wide_dump_full(dump, 6 * VRAM_HEIGHT, &ow, &oh, 100) ==
              6 * VRAM_HEIGHT,
          "authoritative full mirror dump writes the complete surface");
    CHECK(ow == 6 && oh == VRAM_HEIGHT,
          "full mirror dump reports exact sidecar geometry");
    for (int i = 0; i < 6; i++)
        expect_pixel(dump[i], sidecar,
                     "debug dump matches authoritative gameplay presentation");

    sw_wide_set_mirror_authoritative(0);
    CHECK(sw_render_wide_display(out, (int)sizeof(out), 100, 0, 1) == 6,
          "quiet 2D fallback still presents a complete row");
    expect_pixel(out[0], sidecar, "quiet 2D keeps the left reveal margin");
    for (int i = 0; i < 4; i++)
        expect_pixel(out[i + 1], canonical[i],
                     "quiet 2D restores canonical direct-upload centre");
    expect_pixel(out[5], sidecar, "quiet 2D keeps the right reveal margin");
}

int main(void) {
    test_native_wrap_and_margins();
    test_zero_offset_identity();
    test_supersampled_center();
    test_present_authority_policy();
    test_full_mirror_present_and_dump();
    if (failures) return 1;
    puts("ALL PASS");
    return 0;
}
