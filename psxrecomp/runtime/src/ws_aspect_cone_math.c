#include "ws_aspect_cone_math.h"

#include <math.h>

uint32_t psx_ws_widen_angle_q12(uint32_t vanilla, int extent_pixels) {
    if (extent_pixels <= 0) return vanilla;
    if (vanilla == 0) return 0;
    if (vanilla >= 1024u) return 1023u;

    const double tau = 6.283185307179586476925286766559;
    const double angle = (double)vanilla * tau / 4096.0;
    const double scale = (160.0 + (double)extent_pixels) / 160.0;
    const double widened = atan(tan(angle) * scale);
    long result = lround(widened * 4096.0 / tau);
    if (result < 1) result = 1;
    if (result > 1023) result = 1023;
    return (uint32_t)result;
}

uint32_t psx_ws_widen_full_angle_q12(uint32_t vanilla, int margin, int native_width) {
    if (margin <= 0 || native_width <= 0 || vanilla == 0) return vanilla;
    if (vanilla >= 2048u) return vanilla;
    const double pi = 3.1415926535897932384626433832795;
    const double half = (double)vanilla * pi / 4096.0;
    const double scale = 1.0 + 2.0 * (double)margin / (double)native_width;
    const double wide_half = atan(tan(half) * scale);
    uint32_t result = 2u * (uint32_t)ceil(wide_half * 2048.0 / pi);
    return result < 2048u ? result : 2046u;
}

int psx_ws_aspect_cone_contains(int32_t x, int32_t z, int32_t y,
                                int32_t fx, int32_t fz, int32_t fy,
                                uint32_t threshold, int extent_pixels) {
    if (threshold == 0 || threshold >= 1024 || extent_pixels < 0)
        return 0;

    const double fhd = hypot((double)fx, (double)fz);
    if (fhd < 1.0) return 0;

    /* Camera-local coordinates. The Q12 scale cancels from the comparisons.
     * The right vector is horizontal in world space; the derived up vector is
     * perpendicular to both right and the pitched camera-forward vector. */
    const double forward =
        ((double)fx * x + (double)fz * z + (double)fy * y) / 4096.0;
    if (forward <= 0.0) return 0;
    const double horizontal =
        ((double)fz * x - (double)fx * z) / fhd;
    const double vertical_num =
        (double)fx * fy * x -
        fhd * fhd * y +
        (double)fz * fy * z;
    const double vertical = vertical_num / (fhd * 4096.0);

    const double cosine = (double)threshold / 1024.0;
    const double tangent =
        sqrt((1.0 - cosine * cosine) / (cosine * cosine));
    if (fabs(vertical) > forward * tangent) return 0;

    const double aspect_scale = (160.0 + extent_pixels) / 160.0;
    return fabs(horizontal) <= forward * tangent * aspect_scale;
}
