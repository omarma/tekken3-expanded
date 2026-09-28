#include "tekken3_force_background.h"

static int wrap(int n, int size) { n %= size; return n < 0 ? n + size : n; }
static int thirds(int n) { return n < 0 ? (n-2)/3 : n/3; }
static int same(Tekken3ForceCell a, Tekken3ForceCell b) {
    return (a.tile & 0x1f0f) == (b.tile & 0x1f0f) && a.clut == b.clut;
}

size_t tekken3_force_reveal(const Tekken3ForceCell *map, int columns, int rows,
    int scroll, int slope_fp, int margin, const Tekken3ForceSprite *sprites, size_t count,
    Tekken3ForceReveal *out, size_t capacity) {
    size_t n = 0;
    if (!map || !sprites || !out || columns < 1 || columns > T3_FORCE_MAX_COLUMNS ||
        rows < 1 || rows > T3_FORCE_MAX_ROWS || margin <= 0 || margin > 192) return 0;
    scroll = wrap(scroll, columns * 64);
    int first = scroll / 64, x0 = -(scroll % 64);
    for (size_t i = 0; i < count; i++) {
        const Tekken3ForceSprite *edge = &sprites[i];
        if (edge->x != x0) continue;
        const Tekken3ForceSprite *strip[7] = {0};
        /* Force's background is a sprite plane. The guest allocates each
         * row consecutively, including when an offscreen row was skipped. */
        for (size_t j = 0; j < count; j++) {
            const Tekken3ForceSprite *s = &sprites[j];
            if (s->source < edge->source || s->source >= edge->source + 7*20 ||
                (s->source-edge->source)%20) continue;
            int col = (int)(s->source-edge->source)/20;
            int dy = (int)((int64_t)slope_fp * (thirds(first+col)-thirds(first))/4096);
            int error = s->y - (edge->y-dy);
            if (s->x == x0+col*64 && error >= -1 && error <= 1) strip[col] = s;
        }
        int complete = 1;
        for (int col = 0; col < 7; col++) if (!strip[col]) complete = 0;
        if (!complete) continue;
        int selected = -1, ambiguous = 0;
        for (int row = 0; row < rows; row++) {
            int matches = 1;
            for (int col = 0; col < 7; col++)
                if (!same(strip[col]->cell, map[row*columns+wrap(first+col,columns)])) matches = 0;
            if (!matches) continue;
            if (selected >= 0) {
                /* Repeated rows are safe only if the revealed cells agree. */
                for (int col = -3; col < 10; col++)
                    if (!same(map[selected*columns+wrap(first+col,columns)],
                              map[row*columns+wrap(first+col,columns)])) ambiguous = 1;
            } else selected = row;
        }
        if (selected < 0 || ambiguous) continue;
        for (int side = -1; side <= 1; side += 2) {
            int col = side < 0 ? -1 : 7;
            for (; side < 0 ? x0+(col+1)*64 > -margin : x0+col*64 < 368+margin; col += side) {
                if (n == capacity) return n;
                int anchor = side < 0 ? 0 : 6;
                int dy = (int)((int64_t)slope_fp * (thirds(first+col)-thirds(first+anchor))/4096);
                out[n++] = (Tekken3ForceReveal){strip[anchor]->source,
                    x0+col*64, strip[anchor]->y-dy,
                    map[selected*columns+wrap(first+col,columns)]};
            }
        }
    }
    return n;
}
