#include "native_wide_hole_fill_policy.h"

#include <assert.h>
#include <stdio.h>

#define HOLE 0x80010203u

int main(void) {
    enum { W = 10, H = 4, M = 2 };
    uint32_t p[W * H];
    for (int i = 0; i < W * H; i++) p[i] = 0xff203040u + (uint32_t)i;

    /* Same-row authoritative edge colours. */
    for (int y = 0; y < H; y++) {
        p[y * W + M] = 0xff110000u + (uint32_t)y;
        p[y * W + W - M - 1] = 0xff001100u + (uint32_t)y;
    }

    /* Irregular wedge, plus isolated right-side holes. */
    p[0 * W + 0] = HOLE;
    p[1 * W + 0] = HOLE; p[1 * W + 1] = HOLE;
    p[2 * W + 1] = HOLE;
    p[0 * W + 9] = HOLE; p[2 * W + 8] = HOLE;

    /* Real covered black and foreground-coloured margin pixels stay intact. */
    p[3 * W + 0] = 0xff000000u;
    p[3 * W + 1] = 0xfff02010u;
    /* A sentinel-like RGB value with valid PS1 alpha is not a hole. */
    p[3 * W + 9] = 0x00010203u;
    const uint32_t centre = p[2 * W + 5];

    assert(psx_ws_resolve_margin_holes_argb(p, W, W, H, M) == 6);
    assert(p[0 * W + 0] == p[0 * W + M]);
    assert(p[1 * W + 0] == p[1 * W + M]);
    assert(p[1 * W + 1] == p[1 * W + M]);
    assert(p[2 * W + 1] == p[2 * W + M]);
    assert(p[0 * W + 9] == p[0 * W + W - M - 1]);
    assert(p[2 * W + 8] == p[2 * W + W - M - 1]);
    assert(p[3 * W + 0] == 0xff000000u);
    assert(p[3 * W + 1] == 0xfff02010u);
    assert(p[3 * W + 9] == 0x00010203u);
    assert(p[2 * W + 5] == centre);
    puts("native wide hole fill policy: PASS");
    return 0;
}
