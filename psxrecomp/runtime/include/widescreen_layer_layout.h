#ifndef PSXRECOMP_WIDESCREEN_LAYER_LAYOUT_H
#define PSXRECOMP_WIDESCREEN_LAYER_LAYOUT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum PsxWsGroupLayout {
    /* Preserve the complete 4:3 composition in the centred safe area. */
    PSX_WS_GROUP_SAFE_AREA = 0,

    /* Preserve distance to the nearest authored edge.  Suitable for battle HUD
     * composites once glyphs/panels have been grouped as one item. */
    PSX_WS_GROUP_EDGE_ANCHORED,

    /* Distribute group centres continuously across the expanded canvas while
     * preserving every group's internal size.  Suitable for a portrait/roster
     * grid whose rows should use the additional selector width. */
    PSX_WS_GROUP_DISTRIBUTED
} PsxWsGroupLayout;

/* Return the X delta to apply in the guest's canonical coordinate space before
 * the native-wide compositor adds `margin` to every primitive.  Applying one
 * delta to every primitive in the group guarantees that text, frames, cursor
 * pieces and portraits do not stretch or tear.
 *
 *   final_x = canonical_x + margin + returned_delta
 *
 * Identity/error cases return zero. */
int32_t psx_ws_group_layout_delta(int32_t group_x, int32_t group_width,
                                  int32_t display_width, int32_t margin,
                                  PsxWsGroupLayout layout);

#ifdef __cplusplus
}
#endif

#endif /* PSXRECOMP_WIDESCREEN_LAYER_LAYOUT_H */
