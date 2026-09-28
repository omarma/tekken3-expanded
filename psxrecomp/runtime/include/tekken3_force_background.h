#ifndef TEKKEN3_FORCE_BACKGROUND_H
#define TEKKEN3_FORCE_BACKGROUND_H
#include <stdint.h>
#include <stddef.h>

enum { T3_FORCE_MAX_COLUMNS = 128, T3_FORCE_MAX_ROWS = 6 };
typedef struct Tekken3ForceCell { uint16_t tile, clut; } Tekken3ForceCell;
typedef struct Tekken3ForceSprite {
    uint32_t source;
    int x, y;
    Tekken3ForceCell cell;
} Tekken3ForceSprite;
typedef struct Tekken3ForceReveal {
    uint32_t edge_source;
    int x, y;
    Tekken3ForceCell cell;
} Tekken3ForceReveal;

/* Resolve additional columns from the original scrolling tile map. Each
 * seven-sprite row must match the map before it can authorize any reveal. */
size_t tekken3_force_reveal(const Tekken3ForceCell *map, int columns, int rows,
    int scroll, int slope_fp, int margin, const Tekken3ForceSprite *sprites, size_t count,
    Tekken3ForceReveal *out, size_t capacity);
#endif
