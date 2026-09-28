#include "../src/gpu_sw_edges.h"

#include <stdio.h>

static int failures;
#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "FAIL: %s\n", message); failures++; } \
} while (0)

int main(void) {
    int long_x = 0, short_x = 0;

    /* A right triangle's final scanline is y2-1; y2 itself is excluded by the
     * caller. Pin the DDA values used to produce the half-open X span. */
    psx_triangle_edges_at_y(0, 0, 8, 0, 0, 8, 0, &long_x, &short_x);
    CHECK(long_x == 0 && short_x == 8, "top scanline spans [0,8)");
    psx_triangle_edges_at_y(0, 0, 8, 0, 0, 8, 7, &long_x, &short_x);
    CHECK(long_x == 0 && short_x == 1, "last scanline spans one pixel");

    CHECK(psx_edge_step(8, 8) == (1LL << 32),
          "positive unit slope has exact 32.32 step");
    CHECK(psx_edge_step(-8, 8) == -(1LL << 32),
          "negative unit slope has exact 32.32 step");

    if (failures) return 1;
    puts("ALL PASS");
    return 0;
}
