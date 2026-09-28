#ifndef PSXRECOMP_NATIVE_WIDE_MARGIN_POLICY_H
#define PSXRECOMP_NATIVE_WIDE_MARGIN_POLICY_H

#include <stdint.h>

/*
 * Host-only native-wide surfaces do not inherit the guest framebuffer's
 * per-frame redraw contract.  Track each sidecar framebuffer independently so
 * its synthetic margins are invalidated exactly once before that frame's first
 * primitive.  This is deliberately transient renderer policy, not emulated
 * machine state.
 */
static inline int psx_ws_margin_refresh_once(uint32_t frame,
                                             uint32_t *last_refresh_frame) {
    if (!last_refresh_frame || *last_refresh_frame == frame) return 0;
    *last_refresh_frame = frame;
    return 1;
}

#endif /* PSXRECOMP_NATIVE_WIDE_MARGIN_POLICY_H */
