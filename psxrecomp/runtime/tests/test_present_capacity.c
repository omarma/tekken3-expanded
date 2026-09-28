#include "present_capacity.h"

#include <stdio.h>

static int failures;
#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "FAIL: %s\n", message); failures++; } \
} while (0)

int main(void) {
    CHECK(psx_present_native_wide_width(320, 4, 3) == 320,
          "4:3 is width identity");
    CHECK(psx_present_native_wide_width(320, 16, 9) == 426,
          "320-wide 16:9 sidecar matches renderer rounding");
    CHECK(psx_present_native_wide_width(512, 16, 9) == 682,
          "512-wide menu 16:9 capacity includes both margins");
    CHECK(psx_present_native_wide_width(640, 16, 9) == 854,
          "640-wide mode 16:9 capacity includes symmetric rounding");
    CHECK(psx_present_scaled_width(512, 4, 16, 9) == 2728,
          "supersampling scales the complete wide source");
    CHECK(psx_present_native_wide_width(640, 32, 9) == 1706,
          "maximum supported aspect has an exact bounded width");
    CHECK(psx_present_max_scaled_width() == 6824,
          "global staging width bound covers 640-wide 32:9 at 4x");
    CHECK(psx_present_max_scaled_height() == 2048,
          "global staging height bound covers 512 at 4x");
    CHECK(psx_present_native_wide_width(641, 16, 9) == 0,
          "canonical widths beyond the GPU clamp are rejected");
    CHECK(psx_present_native_wide_width(640, 33, 9) == 0,
          "aspects beyond the public 32:9 limit are rejected");
    CHECK(psx_present_scaled_width(640, 5, 16, 9) == 0,
          "scales beyond the software-renderer limit are rejected");

    if (failures) return 1;
    puts("ALL PASS");
    return 0;
}
