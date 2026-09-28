#include "widescreen_hud_packet.h"

#include <stdio.h>

static int failures;
#define CHECK(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "FAIL: %s\n", message); failures++; } \
} while (0)

int main(void) {
    const uint32_t range1_lo = 0x000DCC00u;
    const uint32_t range1_hi = 0x000DD000u;
    const uint32_t range2_lo = 0x000ECC00u;
    const uint32_t range2_hi = 0x000ED000u;

    CHECK(psx_ws_hud_packet_range_match(
              1, range1_lo, range1_lo, range1_hi, range2_lo, range2_hi),
          "first range includes its lower boundary");
    CHECK(!psx_ws_hud_packet_range_match(
              1, range1_hi, range1_lo, range1_hi, range2_lo, range2_hi),
          "first range excludes its upper boundary");
    CHECK(psx_ws_hud_packet_range_match(
              1, range2_lo + 4u,
              range1_lo, range1_hi, range2_lo, range2_hi),
          "second packet arena matches independently");
    CHECK(psx_ws_hud_packet_range_match(
              1, 0x800ECC04u,
              range1_lo, range1_hi, range2_lo, range2_hi),
          "KSEG packet aliases normalize to physical RAM");
    CHECK(!psx_ws_hud_packet_range_match(
              1, 0x000E0000u,
              range1_lo, range1_hi, range2_lo, range2_hi),
          "world packet between narrow HUD arenas does not match");
    CHECK(!psx_ws_hud_packet_range_match(
              1, UINT32_MAX,
              range1_lo, range1_hi, range2_lo, range2_hi),
          "unknown command source never matches");
    CHECK(!psx_ws_hud_packet_range_match(
              0, range2_lo,
              range1_lo, range1_hi, range2_lo, range2_hi),
          "4:3/native-wide-disabled path is an exact identity");
    CHECK(!psx_ws_hud_packet_range_match(
              1, range2_lo, range1_lo, range1_lo, range2_hi, range2_lo),
          "empty or reversed ranges are disabled defensively");

    if (failures) return 1;
    puts("ALL PASS");
    return 0;
}
