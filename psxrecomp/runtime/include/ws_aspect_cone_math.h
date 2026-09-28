#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Test whether a camera-relative vector is inside a rectangular view cone.
 *
 * Coordinates use Tomba 2's X,Z,Y ordering. The camera forward vector is Q12.
 * `threshold` is the game's Q10 cosine threshold (the SLTI immediate after its
 * normalized dot product). `extent_pixels` expands only the horizontal
 * half-angle from the vanilla 160-pixel half-width; the vertical half-angle is
 * unchanged.
 */
int psx_ws_aspect_cone_contains(int32_t x, int32_t z, int32_t y,
                                int32_t fx, int32_t fz, int32_t fy,
                                uint32_t threshold, int extent_pixels);

/* Widen a positive PSX 12-bit angular half-extent by the same horizontal
 * projection scale used by a 320-wide 4:3 viewport. `extent_pixels` is the
 * extra per-side reveal (including any configured guard). Identity is exact
 * when extent_pixels is zero. Results stay below a 90-degree half-angle. */
uint32_t psx_ws_widen_angle_q12(uint32_t vanilla, int extent_pixels);

/* Full aperture in 4096 units/turn; scale tan(aperture/2) using the actual
 * native viewport width. Return an even aperture so guest integer halving
 * retains conservative coverage. */
uint32_t psx_ws_widen_full_angle_q12(uint32_t vanilla, int margin, int native_width);

#ifdef __cplusplus
}
#endif
