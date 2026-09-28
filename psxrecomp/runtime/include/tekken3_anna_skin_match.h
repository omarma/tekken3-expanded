/* Anna's blue gown shares hair/leg tiles with the red gown. Require the red
 * costume's full 256-color palette in the same player slot for every match. */
#ifndef TEKKEN3_ANNA_SKIN_MATCH_H
#define TEKKEN3_ANNA_SKIN_MATCH_H
#include "gpu_hd_texture_match.h"
static const HdTextureTile *tekken3_anna_skin_find(HdTextureMap *m, const uint16_t *vram,
        int tx, int ty, int depth, int cx, int cy, const int *us, const int *vs) {
    if (m->count != 32 || !vram || (cy != 504 && cy != 505 && cy != 508 && cy != 509))
        return NULL;
    const HdTextureTile *t = hd_map_find(m, vram, tx, ty, depth, cx, cy, us, vs);
    if (!t) return NULL;
    /* anna_skin_pack.py writes sixteen records per player, face first. */
    HdTextureTile *anchor = &m->tiles[cy >= 508 ? 16 : 0];
    if (anchor->depth != 1 || anchor->cy != (uint32_t)(cy >= 508 ? 508 : 504) ||
        !hd_tile_matches(m, anchor, vram)) return NULL;
    return t;
}
#endif
