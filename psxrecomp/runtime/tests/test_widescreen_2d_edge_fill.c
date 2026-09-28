#include "widescreen_2d_edge_fill.h"

#include <stdio.h>
#include <string.h>

static int failures;
#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "FAIL: %s\n", message); failures++; } \
} while (0)

static void test_scene_gate(void) {
    CHECK(psx_ws_2d_edge_fill_allowed(1, 1, 0, 0, 3),
          "opted native-wide 2D frame fills after the quiet guard");
    CHECK(!psx_ws_2d_edge_fill_allowed(0, 1, 0, 0, 99),
          "feature is inert without per-game opt-in");
    CHECK(!psx_ws_2d_edge_fill_allowed(1, 0, 0, 0, 99),
          "4:3/non-native-wide path is exact identity");
    CHECK(!psx_ws_2d_edge_fill_allowed(1, 1, 1, 0, 99),
          "depth24 movie is never filled");
    CHECK(!psx_ws_2d_edge_fill_allowed(1, 1, 0, 1, 99),
          "recent MDEC movie is never filled");
    CHECK(!psx_ws_2d_edge_fill_allowed(1, 1, 0, 0, 2),
          "a transient GTE lull cannot overwrite revealed 3D geometry");
}

static void test_margins_only(void) {
    enum { W = 10, H = 4, M = 2 };
    uint32_t frame[W * H];
    uint32_t before[W * H];
    for (int y = 0; y < H; y++) {
        frame[y * W + 0] = frame[y * W + 1] = 0xff000000u;
        for (int x = M; x < W - M; x++) {
            uint32_t r = (uint32_t)(30 + x * 9 + y * 4);
            uint32_t g = (uint32_t)(60 + x * 3 + y * 5);
            uint32_t b = (uint32_t)(90 + x * 2 + y * 6);
            frame[y * W + x] = 0xff000000u | (r << 16) | (g << 8) | b;
        }
        frame[y * W + W - 2] = frame[y * W + W - 1] = 0xff000000u;
    }
    memcpy(before, frame, sizeof(frame));

    CHECK(psx_ws_fill_2d_edges_argb(frame, W, H, W, M, 1) == 1,
          "valid wide frame receives edge fill");
    for (int y = 0; y < H; y++) {
        CHECK(memcmp(frame + y * W + M, before + y * W + M,
                     (W - 2 * M) * sizeof(uint32_t)) == 0,
              "canonical centre remains bit-exact");
        CHECK((frame[y * W] & 0x00ffffffu) != 0,
              "left reveal is derived from the left edge palette");
        CHECK((frame[y * W + W - 1] & 0x00ffffffu) != 0,
              "right reveal is derived from the right edge palette");
        CHECK(frame[y * W] != before[y * W + M],
              "fill is an averaged extension, not a mirrored UI pixel");
    }
}

static void test_identity_geometry(void) {
    uint32_t frame[4] = { 1, 2, 3, 4 };
    uint32_t before[4];
    memcpy(before, frame, sizeof(frame));
    CHECK(psx_ws_fill_2d_edges_argb(frame, 4, 1, 4, 0, 1) == 0,
          "zero-margin 4:3 geometry is rejected");
    CHECK(memcmp(frame, before, sizeof(frame)) == 0,
          "identity geometry is byte-exact");
}

int main(void) {
    test_scene_gate();
    test_margins_only();
    test_identity_geometry();
    if (failures) return 1;
    puts("ALL PASS");
    return 0;
}
