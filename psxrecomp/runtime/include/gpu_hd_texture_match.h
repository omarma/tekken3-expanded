/* Optional host texture replacements. Disk records contain no guest payload. */
#ifndef GPU_HD_TEXTURE_MATCH_H
#define GPU_HD_TEXTURE_MATCH_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define HD_MAX_TILES 2048
typedef struct HdTextureTile {
    uint32_t x, y, w, h, cx, cy;
    uint64_t pixels_hash, palette_hash;
    float map[6]; /* absolute pixel coordinates at this depth -> normalized HD UV */
    uint32_t kind; /* 1 panorama, 2 repeating ground, 3 character atlas */
    uint32_t depth; /* 0 = 4bpp, 1 = 8bpp; HDMAP001 implicitly uses 0 */
    uint64_t checked_generation;
    int matches, next;
} HdTextureTile;
typedef struct HdTextureMap {
    HdTextureTile *tiles;
    uint32_t count;
    int heads[32768];
    uint64_t generation;
} HdTextureMap;
static uint64_t hd_hash_rect(const uint16_t *vram, unsigned x, unsigned y,
                             unsigned w, unsigned h) {
    uint64_t hash = UINT64_C(14695981039346656037);
    for (unsigned row = 0; row < h; ++row)
        for (unsigned col = 0; col < w; ++col) {
            uint16_t p = vram[(y + row) * 1024 + x + col];
            hash = (hash ^ (p & 255)) * UINT64_C(1099511628211);
            hash = (hash ^ (p >> 8)) * UINT64_C(1099511628211);
        }
    return hash;
}
static void hd_map_clear(HdTextureMap *m) {
    free(m->tiles); m->tiles = NULL; m->count = 0; m->generation = 1;
    for (int i = 0; i < 32768; ++i) m->heads[i] = -1;
}
static int hd_map_load(HdTextureMap *m, const char *path) {
    char magic[8]; uint32_t count = 0; int ok = 0, version2 = 0;
    FILE *f = fopen(path, "rb");
    hd_map_clear(m);
    if (!f) return 0;
    if (fread(magic, 1, 8, f) != 8) goto done;
    version2 = !memcmp(magic, "HDMAP002", 8);
    if ((!version2 && memcmp(magic, "HDMAP001", 8)) ||
        fread(&count, 4, 1, f) != 1 || !count || count > HD_MAX_TILES) goto done;
    m->tiles = (HdTextureTile *)calloc(count, sizeof(HdTextureTile));
    if (!m->tiles) goto done;
    for (uint32_t i = 0; i < count; ++i) {
        HdTextureTile *t = &m->tiles[i];
        if (fread(&t->x, 4, 6, f) != 6 || fread(&t->pixels_hash, 8, 2, f) != 2 ||
            fread(t->map, 4, 6, f) != 6 || fread(&t->kind, 4, 1, f) != 1) goto done;
        if (version2 && fread(&t->depth, 4, 1, f) != 1) goto done;
        if (t->depth > 1) goto done;
        if (t->x >= 1024 || t->y >= 512 || !t->w || !t->h ||
            t->w > (64u << t->depth) || t->h > 256 || t->x + t->w > 1024 || t->y + t->h > 512 ||
            t->cx > 1024u - (t->depth ? 256u : 16u) || (t->cx & 15) ||
            t->cy >= 512 || t->kind < 1 || t->kind > (version2 ? 3u : 2u)) goto done;
        for (int k = 0; k < 6; ++k) if (!isfinite(t->map[k])) goto done;
        unsigned bucket = t->cy * 64 + t->cx / 16;
        t->next = m->heads[bucket]; m->heads[bucket] = (int)i;
    }
    if (fgetc(f) != EOF) goto done;
    m->count = count; ok = 1;
done:
    fclose(f);
    if (!ok) hd_map_clear(m);
    return ok;
}
static int hd_tile_matches(HdTextureMap *m, HdTextureTile *t, const uint16_t *vram) {
    if (t->checked_generation != m->generation) {
        t->matches = hd_hash_rect(vram, t->x, t->y, t->w, t->h) == t->pixels_hash &&
            hd_hash_rect(vram, t->cx, t->cy, t->depth ? 256 : 16, 1) == t->palette_hash;
        t->checked_generation = m->generation;
    }
    return t->matches;
}
static const HdTextureTile *hd_map_find(HdTextureMap *m, const uint16_t *vram,
        int tx, int ty, int depth, int cx, int cy, const int *us, const int *vs) {
    if (!m->count || !vram || depth < 0 || depth > 1 || cx < 0 || cx > 1008 ||
        (cx & 15) || cy < 0 || cy >= 512) return NULL;
    for (int i = m->heads[cy * 64 + cx / 16]; i >= 0; i = m->tiles[i].next) {
        HdTextureTile *t = &m->tiles[i]; int inside = 1;
        if ((int)t->depth != depth) continue;
        int pixels_per_word = depth ? 2 : 4;
        for (int k = 0; k < 3; ++k) {
            int x = tx * pixels_per_word + us[k], y = ty + vs[k];
            if (x < (int)t->x * pixels_per_word || x >= (int)(t->x + t->w) * pixels_per_word ||
                y < (int)t->y || y >= (int)(t->y + t->h)) inside = 0;
        }
        if (!inside) continue;
        if (hd_tile_matches(m, t, vram)) return t;
    }
    return NULL;
}
#endif
