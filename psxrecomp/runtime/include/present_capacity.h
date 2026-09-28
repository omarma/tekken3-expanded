#ifndef PSX_PRESENT_CAPACITY_H
#define PSX_PRESENT_CAPACITY_H

/* Bounds and exact width math for CPU-backed presentation. The GPU exposes at
 * most 640x512 canonical pixels, the software renderer supports at most 4x
 * internal scale, and the public aspect API caps the host view at 32:9. */
#include <stdint.h>

#define PSX_PRESENT_CANONICAL_MAX_W 640
#define PSX_PRESENT_CANONICAL_MAX_H 512
#define PSX_PRESENT_MAX_SCALE       4
#define PSX_PRESENT_MAX_ASPECT_NUM 32
#define PSX_PRESENT_MAX_ASPECT_DEN  9

/* Match gpu.c::ws_nw_configured_offset exactly. Native-wide expands a display
 * symmetrically by a rounded integer side margin; 4:3 and narrower are an
 * identity. Returns zero for invalid/unbounded input. */
static inline int psx_present_native_wide_width(int display_w,
                                                int aspect_num,
                                                int aspect_den) {
    int64_t numr;
    int64_t offset;
    int64_t width;
    if (display_w <= 0 || display_w > PSX_PRESENT_CANONICAL_MAX_W ||
        aspect_num <= 0 || aspect_den <= 0)
        return 0;
    if ((int64_t)aspect_num * 3 <= (int64_t)aspect_den * 4)
        return display_w;
    if ((int64_t)aspect_num * PSX_PRESENT_MAX_ASPECT_DEN >
        (int64_t)aspect_den * PSX_PRESENT_MAX_ASPECT_NUM)
        return 0;
    numr = (int64_t)3 * aspect_num - (int64_t)4 * aspect_den;
    offset = ((int64_t)display_w * numr + (int64_t)4 * aspect_den) /
             ((int64_t)8 * aspect_den);
    width = (int64_t)display_w + 2 * offset;
    if (width <= 0 || width > INT32_MAX)
        return 0;
    return (int)width;
}

static inline int psx_present_scaled_width(int display_w, int scale,
                                           int aspect_num, int aspect_den) {
    int width;
    if (scale < 1 || scale > PSX_PRESENT_MAX_SCALE)
        return 0;
    width = psx_present_native_wide_width(display_w, aspect_num, aspect_den);
    return width > 0 ? width * scale : 0;
}

static inline int psx_present_max_scaled_width(void) {
    return psx_present_scaled_width(PSX_PRESENT_CANONICAL_MAX_W,
                                    PSX_PRESENT_MAX_SCALE,
                                    PSX_PRESENT_MAX_ASPECT_NUM,
                                    PSX_PRESENT_MAX_ASPECT_DEN);
}

static inline int psx_present_max_scaled_height(void) {
    return PSX_PRESENT_CANONICAL_MAX_H * PSX_PRESENT_MAX_SCALE;
}

#endif /* PSX_PRESENT_CAPACITY_H */
