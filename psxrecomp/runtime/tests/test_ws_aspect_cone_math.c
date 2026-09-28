#include "ws_aspect_cone_math.h"

#include <stdio.h>
#include <math.h>

static int failures;

static void check(int condition, const char *name) {
    if (condition) {
        printf("PASS  %s\n", name);
    } else {
        fprintf(stderr, "FAIL  %s\n", name);
        failures++;
    }
}

int main(void) {
    /* Camera looking along +X, with an approximately 30-degree vanilla cone. */
    const int32_t q12 = 4096;
    const uint32_t cos_q10 = 880;

    check(psx_ws_aspect_cone_contains(
              1000, 500, 0, q12, 0, 0, cos_q10, 0),
          "vanilla horizontal interior is accepted");
    check(!psx_ws_aspect_cone_contains(
              1000, 650, 0, q12, 0, 0, cos_q10, 0),
          "vanilla horizontal exterior is rejected");
    check(psx_ws_aspect_cone_contains(
              1000, 650, 0, q12, 0, 0, cos_q10, 80),
          "wide extent expands horizontal acceptance");
    check(!psx_ws_aspect_cone_contains(
              1000, 0, 650, q12, 0, 0, cos_q10, 80),
          "wide extent preserves the vertical boundary");
    check(!psx_ws_aspect_cone_contains(
              -1000, 0, 0, q12, 0, 0, cos_q10, 160),
          "points behind the camera are rejected");

    /* A 45-degree pitched forward vector still produces orthogonal forward,
     * horizontal, and vertical tests. */
    check(psx_ws_aspect_cone_contains(
              1000, 0, 1000, 2896, 0, 2896, cos_q10, 0),
          "pitched camera accepts a point on its forward axis");
    check(!psx_ws_aspect_cone_contains(
              1000, 0, -1000, 2896, 0, 2896, cos_q10, 160),
          "horizontal expansion does not bypass pitched vertical rejection");

    check(!psx_ws_aspect_cone_contains(
              1000, 0, 0, q12, 0, 0, 0, 0),
          "invalid zero threshold is inert");
    check(!psx_ws_aspect_cone_contains(
              1000, 0, 0, 0, 0, q12, cos_q10, 0),
          "degenerate horizontal camera basis is inert");

    check(psx_ws_widen_angle_q12(341, 0) == 341,
          "terrain angle is exact at 4:3");
    check(psx_ws_widen_angle_q12(341, 136) == 533,
          "terrain angle follows 21:9 plus guard geometry");
    check(psx_ws_widen_angle_q12(455, 136) == 651,
          "wider vanilla terrain angle scales geometrically");
    check(psx_ws_widen_angle_q12(300, 136) == 484,
          "lava terrain angle uses the same projection geometry");
    check(psx_ws_widen_angle_q12(318, 80) <
              psx_ws_widen_angle_q12(318, 136),
          "terrain angle tracks dynamic horizontal extent");
    check(psx_ws_widen_angle_q12(1023, 256) <= 1023,
          "terrain angle remains below a quarter turn");

    check(psx_ws_widen_full_angle_q12(600, 0, 368) == 600,
          "full aperture preserves exact 4:3");
    check(psx_ws_widen_full_angle_q12(600, 61, 0) == 600,
          "invalid viewport leaves full aperture unchanged");
    for (uint32_t aperture = 600; aperture <= 780; aperture += 180) {
        const double pi = 3.14159265358979323846;
        const uint32_t wide = psx_ws_widen_full_angle_q12(aperture, 61, 368);
        const double edge_slope = tan(aperture * pi / 4096.0) * 490.0 / 368.0;
        const double kept_slope = tan((wide / 2u) * pi / 2048.0);
        check(kept_slope >= edge_slope,
              "guest-halved full aperture includes both 16:9 edges");
        check(tan(((wide / 2u) - 1u) * pi / 2048.0) < edge_slope,
              "full aperture adds no more than one angular unit of overdraw");
        check(wide < 2u * psx_ws_widen_angle_q12(aperture, 61),
              "full aperture is not mistaken for a half-angle");
    }
    check(psx_ws_widen_full_angle_q12(600, 61, 368) <
              psx_ws_widen_full_angle_q12(600, 61, 320),
          "full aperture uses the real native viewport width");

    return failures ? 1 : 0;
}
