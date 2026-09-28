#include "tekken3_ball_background.h"
#include <assert.h>
#include <stdio.h>

/* A 32-column, 3-row panorama with distinct cells, like the beach map. */
static Tekken3BallCell cell(int row, int col) {
    return (Tekken3BallCell){(uint16_t)(((col & 7) | ((row*4 + col/8) & 7) << 3) | (col/16) << 8),
                             (uint16_t)(0x7c00 + row*32 + col)};
}

static void every_scroll(int margin) {
    Tekken3BallCell map[3*32], row[T3_BALL_ROW_CELLS];
    Tekken3BallReveal out[16];
    for (int r = 0; r < 3; r++) for (int c = 0; c < 32; c++) map[r*32 + c] = cell(r, c);
    for (int scroll = 0; scroll < 32*32; scroll++) {
        for (int r = 0; r < 3; r++) {
            int first = scroll/32 + 2, x0 = -(scroll % 32);
            for (int k = 0; k < T3_BALL_ROW_CELLS; k++) row[k] = map[r*32 + (first + k) % 32];
            size_t n = tekken3_ball_reveal(map, 32, 3, row, x0, 81 + 32*r, margin, out, 16);
            /* The drawn row plus the reveal covers the whole wide view. */
            int lo = x0, hi = x0 + 32*T3_BALL_ROW_CELLS;
            for (size_t i = 0; i < n; i++) {
                int k = (out[i].x - x0)/32;
                assert(out[i].x == x0 + 32*k && out[i].y == 81 + 32*r);
                assert(k < 0 || k >= T3_BALL_ROW_CELLS);
                Tekken3BallCell want = map[r*32 + ((first + k) % 32 + 32) % 32];
                assert(out[i].cell.tile == want.tile && out[i].cell.clut == want.clut);
                if (out[i].x < lo) lo = out[i].x;
                if (out[i].x + 32 > hi) hi = out[i].x + 32;
            }
            assert(lo <= -margin && lo > -margin - 32);
            assert(hi >= 368 + margin);
        }
    }
}

int main(void) {
    every_scroll(61);
    every_scroll(139);

    Tekken3BallCell map[2*32], row[T3_BALL_ROW_CELLS];
    Tekken3BallReveal out[16];
    for (int r = 0; r < 2; r++) for (int c = 0; c < 32; c++) map[r*32 + c] = cell(r, c);
    for (int k = 0; k < T3_BALL_ROW_CELLS; k++) row[k] = map[32 + k];
    /* No reveal without a margin, for an impossible phase, or a foreign row. */
    assert(!tekken3_ball_reveal(map, 32, 2, row, -5, 0, 0, out, 16));
    assert(!tekken3_ball_reveal(map, 32, 2, row, -32, 0, 61, out, 16));
    row[7].clut ^= 1;
    assert(!tekken3_ball_reveal(map, 32, 2, row, -5, 0, 61, out, 16));
    row[7].clut ^= 1;
    /* Tile bits the overlay ignores do not matter. */
    row[3].tile |= 0x00c0;
    assert(tekken3_ball_reveal(map, 32, 2, row, -5, 0, 61, out, 16) == 2);
    row[3].tile &= (uint16_t)~0x00c0;
    /* Two rows equal in the drawn span but not in the reveal: nothing. */
    for (int k = 0; k < T3_BALL_ROW_CELLS; k++) map[k + 2] = map[32 + k];
    assert(!tekken3_ball_reveal(map, 32, 2, row, -5, 0, 61, out, 16));
    /* ... and equal in the reveal too: the cells are unambiguous. */
    map[0] = map[32 + 30]; map[1] = map[32 + 31];
    assert(tekken3_ball_reveal(map, 32, 2, row, -5, 0, 61, out, 16) == 2);
    puts("tekken3_ball_wide_test: ok");
    return 0;
}
