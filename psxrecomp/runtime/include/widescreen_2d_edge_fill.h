#ifndef PSX_WIDESCREEN_2D_EDGE_FILL_H
#define PSX_WIDESCREEN_2D_EDGE_FILL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Presentation-only gate for the opt-in native-wide 2D edge fill.  Requiring
 * three quiet frames prevents a one-frame lull in a real 3D scene from ever
 * replacing its revealed geometry.  Authored movies remain native 4:3. */
static inline int psx_ws_2d_edge_fill_allowed(int opt_in,
                                               int native_wide,
                                               int depth24,
                                               int mdec_recent,
                                               uint32_t frames_since_gte) {
    return opt_in && native_wide && !depth24 && !mdec_recent &&
           frames_since_gte > 2u;
}

static inline uint32_t psx_ws_edge_average_argb(const uint32_t *pixels,
                                                int pitch_pixels,
                                                int x0, int x1,
                                                int y0, int y1) {
    uint64_t r = 0, g = 0, b = 0, n = 0;
    for (int y = y0; y < y1; y++) {
        const uint32_t *row = pixels + (uint64_t)y * (uint64_t)pitch_pixels;
        for (int x = x0; x < x1; x++) {
            uint32_t p = row[x];
            r += (p >> 16) & 0xffu;
            g += (p >> 8) & 0xffu;
            b += p & 0xffu;
            n++;
        }
    }
    if (n == 0) return 0xff000000u;
    return 0xff000000u |
           ((uint32_t)((r + n / 2u) / n) << 16) |
           ((uint32_t)((g + n / 2u) / n) << 8) |
           (uint32_t)((b + n / 2u) / n);
}

static inline uint32_t psx_ws_edge_mix_argb(uint32_t near_color,
                                            uint32_t ambient_color,
                                            int amount, int denominator) {
    if (denominator <= 0) denominator = 1;
    if (amount < 0) amount = 0;
    if (amount > denominator) amount = denominator;
    int inv = denominator - amount;
    uint32_t nr = (near_color >> 16) & 0xffu;
    uint32_t ng = (near_color >> 8) & 0xffu;
    uint32_t nb = near_color & 0xffu;
    uint32_t ar = (ambient_color >> 16) & 0xffu;
    uint32_t ag = (ambient_color >> 8) & 0xffu;
    uint32_t ab = ambient_color & 0xffu;
    uint32_t r = (nr * (uint32_t)inv + ar * (uint32_t)amount +
                  (uint32_t)denominator / 2u) / (uint32_t)denominator;
    uint32_t g = (ng * (uint32_t)inv + ag * (uint32_t)amount +
                  (uint32_t)denominator / 2u) / (uint32_t)denominator;
    uint32_t b = (nb * (uint32_t)inv + ab * (uint32_t)amount +
                  (uint32_t)denominator / 2u) / (uint32_t)denominator;

    /* A slight outward falloff keeps a flat edge average from reading as a
     * hard extension.  It is intentionally subtle and never touches centre. */
    uint32_t shade = 256u - (16u * (uint32_t)amount +
                             (uint32_t)denominator / 2u) /
                                (uint32_t)denominator;
    r = (r * shade + 128u) >> 8;
    g = (g * shade + 128u) >> 8;
    b = (b * shade + 128u) >> 8;
    return 0xff000000u | (r << 16) | (g << 8) | b;
}

/* Fill only the synthetic left/right columns of an ARGB native-wide frame.
 * The canonical centre is never written.  Each side is derived from a bounded
 * 24-native-pixel edge band, averaged horizontally and over a small vertical
 * radius, then eased outward.  This extends the scene's palette without
 * stretching the image or reflecting readable UI/text into the margins.
 *
 * Returns 1 when the margins were filled, 0 for an invalid/identity geometry. */
static inline int psx_ws_fill_2d_edges_argb(uint32_t *pixels,
                                            int width, int height,
                                            int pitch_pixels,
                                            int margin, int scale) {
    if (!pixels || width <= 0 || height <= 0 || pitch_pixels < width ||
        margin <= 0 || margin * 2 >= width)
        return 0;
    if (scale < 1) scale = 1;
    if (scale > 4) scale = 4;

    int native_width = width - 2 * margin;
    int sample = 24 * scale;
    int near_sample = 4 * scale;
    int vertical_radius = 2 * scale;
    if (sample > native_width) sample = native_width;
    if (near_sample > sample) near_sample = sample;
    if (sample <= 0 || near_sample <= 0) return 0;

    const int center_left = margin;
    const int center_right = width - margin; /* exclusive */
    const int denominator = margin > 1 ? margin - 1 : 1;

    for (int y = 0; y < height; y++) {
        int y0 = y - vertical_radius;
        int y1 = y + vertical_radius + 1;
        if (y0 < 0) y0 = 0;
        if (y1 > height) y1 = height;

        uint32_t left_near = psx_ws_edge_average_argb(
            pixels, pitch_pixels, center_left, center_left + near_sample, y0, y1);
        uint32_t left_ambient = psx_ws_edge_average_argb(
            pixels, pitch_pixels, center_left, center_left + sample, y0, y1);
        uint32_t right_near = psx_ws_edge_average_argb(
            pixels, pitch_pixels, center_right - near_sample, center_right, y0, y1);
        uint32_t right_ambient = psx_ws_edge_average_argb(
            pixels, pitch_pixels, center_right - sample, center_right, y0, y1);

        uint32_t *row = pixels + (uint64_t)y * (uint64_t)pitch_pixels;
        for (int x = 0; x < margin; x++) {
            int outward = margin - 1 - x;
            row[x] = psx_ws_edge_mix_argb(left_near, left_ambient,
                                          outward, denominator);
        }
        for (int x = center_right; x < width; x++) {
            int outward = x - center_right;
            row[x] = psx_ws_edge_mix_argb(right_near, right_ambient,
                                          outward, denominator);
        }
    }
    return 1;
}

#ifdef __cplusplus
}
#endif

#endif /* PSX_WIDESCREEN_2D_EDGE_FILL_H */
