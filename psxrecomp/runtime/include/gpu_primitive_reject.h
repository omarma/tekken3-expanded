#ifndef PSX_GPU_PRIMITIVE_REJECT_H
#define PSX_GPU_PRIMITIVE_REJECT_H

#include <stdint.h>

/* PS1 hardware primitive-size rejection. Parsed coordinates are checked before
 * widescreen transforms and draw offsets; offsets do not change distances.
 * Quads are tested as their two rendered triangles independently. */
static inline int psx_gpu_triangle_oversize(const int32_t* vx,
                                            const int32_t* vy,
                                            int a, int b, int c) {
    int32_t minx = vx[a], maxx = vx[a];
    if (vx[b] < minx) minx = vx[b];
    if (vx[b] > maxx) maxx = vx[b];
    if (vx[c] < minx) minx = vx[c];
    if (vx[c] > maxx) maxx = vx[c];
    if (maxx - minx > 1023) return 1;

    int32_t miny = vy[a], maxy = vy[a];
    if (vy[b] < miny) miny = vy[b];
    if (vy[b] > maxy) maxy = vy[b];
    if (vy[c] < miny) miny = vy[c];
    if (vy[c] > maxy) maxy = vy[c];
    return maxy - miny > 511;
}

static inline int psx_gpu_line_oversize(int32_t x0, int32_t y0,
                                        int32_t x1, int32_t y1) {
    int32_t dx = x0 > x1 ? x0 - x1 : x1 - x0;
    int32_t dy = y0 > y1 ? y0 - y1 : y1 - y0;
    return dx > 1023 || dy > 511;
}

#endif
