#include "widescreen_layer_layout.h"

#include <stdint.h>

static int32_t psx_ws_clamp_delta(int64_t delta, int32_t margin) {
    if (delta < -(int64_t)margin) return -margin;
    if (delta >  (int64_t)margin) return  margin;
    return (int32_t)delta;
}

int32_t psx_ws_group_layout_delta(int32_t group_x, int32_t group_width,
                                  int32_t display_width, int32_t margin,
                                  PsxWsGroupLayout layout) {
    int64_t twice_center;

    if (display_width <= 0 || margin <= 0 || group_width <= 0 ||
        layout == PSX_WS_GROUP_SAFE_AREA)
        return 0;

    twice_center = 2 * (int64_t)group_x + group_width;

    if (layout == PSX_WS_GROUP_EDGE_ANCHORED) {
        if (3 * twice_center < 2 * (int64_t)display_width) return -margin;
        if (3 * twice_center > 4 * (int64_t)display_width) return  margin;
        return 0;
    }

    if (layout == PSX_WS_GROUP_DISTRIBUTED) {
        /* Map canonical centre 0..W to delta -margin..+margin.  Round to
         * nearest, symmetrically about the screen centre. */
        int64_t numerator =
            (twice_center - display_width) * (int64_t)margin;
        int64_t rounded = numerator >= 0
            ? numerator + display_width / 2
            : numerator - display_width / 2;
        return psx_ws_clamp_delta(rounded / display_width, margin);
    }

    return 0;
}
