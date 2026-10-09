#include "tekken3_force_background.h"

static int wrap(int n, int size) { n %= size; return n < 0 ? n + size : n; }
static int thirds(int n) { return n < 0 ? (n-2)/3 : n/3; }
static int same(Tekken3ForceCell a, Tekken3ForceCell b) {
    return (a.tile & 0x1f0f) == (b.tile & 0x1f0f) && a.clut == b.clut;
}

/* Force's background is a sprite plane: map row r, screen column c is drawn
 * at y = top + 64*r - tilt(c). The guest skips every cell above y = -64, so a
 * steep tilt (the last stage's bridge) leaves the top rows with fewer than
 * seven sprites. Each visible sprite therefore votes for the plane's top:
 * its x names the column, its cell the row. */
static int tilt(int first, int col, int slope_fp) {
    return (int)((int64_t)slope_fp * (thirds(first+col)-thirds(first))/4096);
}

/* Sprites consistent with this top, or -1 if a sprite contradicts it. */
static int agree(const Tekken3ForceCell *map, int columns, int rows, int first, int x0,
    int slope_fp, int top, const Tekken3ForceSprite *sprites, size_t count) {
    int votes = 0;
    for (size_t i = 0; i < count; i++) {
        const Tekken3ForceSprite *s = &sprites[i];
        if ((s->x - x0) % 64) continue;
        int col = (s->x - x0)/64, dy = s->y - (top - tilt(first, col, slope_fp));
        int row = (dy + 32 + 64*T3_FORCE_MAX_ROWS)/64 - T3_FORCE_MAX_ROWS, error = dy - row*64;
        if (col < 0 || col > 6) continue;
        if (row < 0 || row >= rows || error < -1 || error > 1 ||
            !same(s->cell, map[row*columns+wrap(first+col,columns)])) return -1;
        votes++;
    }
    return votes;
}

size_t tekken3_force_reveal(const Tekken3ForceCell *map, int columns, int rows,
    int scroll, int slope_fp, int margin, const Tekken3ForceSprite *sprites, size_t count,
    Tekken3ForceReveal *out, size_t capacity) {
    size_t n = 0;
    if (!map || !sprites || !out || columns < 1 || columns > T3_FORCE_MAX_COLUMNS ||
        rows < 1 || rows > T3_FORCE_MAX_ROWS || margin <= 0 || margin > 192) return 0;
    scroll = wrap(scroll, columns * 64);
    int first = scroll / 64, x0 = -(scroll % 64);
    const Tekken3ForceSprite *anchor = 0;
    int top = 0, best = 0, ambiguous = 0;
    for (size_t i = 0; i < count; i++) {
        const Tekken3ForceSprite *s = &sprites[i];
        if ((s->x - x0) % 64 || s->x < x0 || s->x > x0+6*64) continue;
        int col = (s->x - x0)/64;
        for (int row = 0; row < rows; row++) {
            if (!same(s->cell, map[row*columns+wrap(first+col,columns)])) continue;
            int candidate = s->y + tilt(first, col, slope_fp) - 64*row;
            if (best && candidate >= top-1 && candidate <= top+1) continue;
            int votes = agree(map, columns, rows, first, x0, slope_fp, candidate, sprites, count);
            if (votes <= 0) continue;
            /* Repeated cells could place the plane twice: reveal nothing. */
            if (best) { ambiguous = 1; continue; }
            best = votes; top = candidate; anchor = s;
        }
    }
    if (!anchor || ambiguous) return 0;
    for (int row = 0; row < rows; row++)
        for (int side = -1; side <= 1; side += 2) {
            int col = side < 0 ? -1 : 7;
            for (; side < 0 ? x0+(col+1)*64 > -margin : x0+col*64 < 368+margin; col += side) {
                int y = top - tilt(first, col, slope_fp) + 64*row;
                if (y < -64 || y > 480) continue;        /* the guest's own on-screen test */
                if (n == capacity) return n;
                /* Like 800B4D88: the last row puts a filler under each column
                 * that starts the map again. */
                out[n++] = (Tekken3ForceReveal){anchor->source, x0+col*64, y,
                    map[row*columns+wrap(first+col,columns)],
                    row == rows-1 && wrap(first+col,columns) == 0};
            }
        }
    return n;
}
