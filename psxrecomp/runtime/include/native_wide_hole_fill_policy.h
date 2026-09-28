#ifndef PSXRECOMP_NATIVE_WIDE_HOLE_FILL_POLICY_H
#define PSXRECOMP_NATIVE_WIDE_HOLE_FILL_POLICY_H

#include <stddef.h>
#include <stdint.h>

/* A PS1 colour target writes mask alpha as exactly 0 or 255.  Alpha 128 is
 * therefore an unambiguous host-only marker for an untouched synthetic-wide
 * margin texel.  It must never be used in canonical VRAM. */
#define PSX_WS_HOLE_ALPHA 128u

static inline int psx_ws_is_margin_hole_argb(uint32_t pixel) {
    unsigned a = pixel >> 24;
    /* GL_RGBA8 may round glClearColor(.5) to either adjacent byte. */
    return a == PSX_WS_HOLE_ALPHA || a == PSX_WS_HOLE_ALPHA - 1u;
}

/* Resolve arbitrary-shaped untouched holes in the two synthetic margins.
 * Covered pixels -- including genuinely black pixels -- are never changed.
 * Each hole receives the canonical edge texel from the same scanline. */
static inline int psx_ws_resolve_margin_holes_argb(
        uint32_t *pixels, int pitch_pixels, int width, int height, int margin) {
    int changed = 0;
    if (!pixels || pitch_pixels < width || width <= 0 || height <= 0 ||
        margin <= 0 || margin * 2 >= width)
        return 0;
    for (int y = 0; y < height; y++) {
        uint32_t *row = pixels + (size_t)y * (size_t)pitch_pixels;
        const uint32_t left = row[margin];
        const uint32_t right = row[width - margin - 1];
        for (int x = 0; x < margin; x++) {
            if (psx_ws_is_margin_hole_argb(row[x])) {
                row[x] = left;
                changed++;
            }
        }
        for (int x = width - margin; x < width; x++) {
            if (psx_ws_is_margin_hole_argb(row[x])) {
                row[x] = right;
                changed++;
            }
        }
    }
    return changed;
}

#endif
