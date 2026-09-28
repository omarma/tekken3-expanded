#include "tekken3_ball_background.h"

static int wrap(int n, int size) { n %= size; return n < 0 ? n + size : n; }
/* The overlay reads page, U and V from these bits of a tile entry. */
static int same(Tekken3BallCell a, Tekken3BallCell b) {
    return (a.tile & 0x1f3f) == (b.tile & 0x1f3f) && a.clut == b.clut;
}

size_t tekken3_ball_reveal(const Tekken3BallCell *map, int columns, int rows,
    const Tekken3BallCell row[T3_BALL_ROW_CELLS], int x0, int y, int margin,
    Tekken3BallReveal *out, size_t capacity) {
    if (!map || !row || !out || columns < 1 || columns > T3_BALL_MAX_COLUMNS ||
        rows < 1 || rows > T3_BALL_MAX_ROWS || margin <= 0 || margin > 192 ||
        x0 > 0 || x0 <= -32) return 0;
    int left = 0, right = T3_BALL_ROW_CELLS;
    while (x0 + left*32 > -margin) left--;
    while (x0 + right*32 < 368 + margin) right++;
    int found_row = -1, found_col = 0;
    for (int r = 0; r < rows; r++) {
        for (int c = 0; c < columns; c++) {
            int matches = 1;
            for (int k = 0; k < T3_BALL_ROW_CELLS && matches; k++)
                if (!same(row[k], map[r*columns + wrap(c+k, columns)])) matches = 0;
            if (!matches) continue;
            if (found_row < 0) { found_row = r; found_col = c; continue; }
            /* A repeating panorama is safe only if the revealed cells agree. */
            for (int k = left; k < right; k++)
                if (!same(map[found_row*columns + wrap(found_col+k, columns)],
                          map[r*columns + wrap(c+k, columns)])) return 0;
        }
    }
    if (found_row < 0) return 0;
    size_t n = 0;
    for (int k = left; k < right; k++) {
        if (k >= 0 && k < T3_BALL_ROW_CELLS) continue;
        if (n == capacity) break;
        out[n++] = (Tekken3BallReveal){x0 + k*32, y,
            map[found_row*columns + wrap(found_col+k, columns)]};
    }
    return n;
}
