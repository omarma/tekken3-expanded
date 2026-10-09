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
    int filler;          /* the guest's 64x32 underlay below the last row's cell */
} Tekken3ForceReveal;

/* Resolve additional columns from the original scrolling tile map. The
 * visible sprites must agree on one placement of the map (rows may be partial:
 * the guest skips cells above the screen); any contradiction reveals nothing. */
size_t tekken3_force_reveal(const Tekken3ForceCell *map, int columns, int rows,
    int scroll, int slope_fp, int margin, const Tekken3ForceSprite *sprites, size_t count,
    Tekken3ForceReveal *out, size_t capacity);
#endif
