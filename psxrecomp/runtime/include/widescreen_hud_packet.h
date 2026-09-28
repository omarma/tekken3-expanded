#ifndef PSX_WIDESCREEN_HUD_PACKET_H
#define PSX_WIDESCREEN_HUD_PACKET_H

#include <stdint.h>

/* Match a GPU command's physical source address against either configured HUD
 * arena. The native-wide gate is part of this pure helper so 4:3 remains an
 * exact identity even when packet ranges are configured. Empty/reversed ranges
 * are disabled defensively; config_loader rejects them before runtime. */
static inline int psx_ws_hud_packet_range_match(
    int native_wide_active, uint32_t source_addr,
    uint32_t range1_lo, uint32_t range1_hi,
    uint32_t range2_lo, uint32_t range2_hi) {
    const uint32_t physical_mask = 0x1FFFFFFFu;
    uint32_t source;

    if (!native_wide_active || source_addr == UINT32_MAX)
        return 0;

    source = source_addr & physical_mask;
    range1_lo &= physical_mask;
    range1_hi &= physical_mask;
    range2_lo &= physical_mask;
    range2_hi &= physical_mask;

    return (range1_hi > range1_lo &&
            source >= range1_lo && source < range1_hi) ||
           (range2_hi > range2_lo &&
            source >= range2_lo && source < range2_hi);
}

#endif /* PSX_WIDESCREEN_HUD_PACKET_H */
