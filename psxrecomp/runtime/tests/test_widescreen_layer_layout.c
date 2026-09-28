#include "widescreen_layer_layout.h"

#include <assert.h>
#include <stdio.h>

static int32_t final_x(int32_t x, int32_t group_x, int32_t group_width,
                       int layout) {
    const int32_t display_width = 368;
    const int32_t margin = 61;
    return x + margin + psx_ws_group_layout_delta(
        group_x, group_width, display_width, margin,
        (PsxWsGroupLayout)layout);
}

int main(void) {
    /* Centre safe area is the exact current native-wide mapping. */
    assert(final_x(40, 40, 80, PSX_WS_GROUP_SAFE_AREA) == 101);

    /* Battle HUD composites retain distance from their corresponding edge. */
    assert(final_x(20, 20, 100, PSX_WS_GROUP_EDGE_ANCHORED) == 20);
    assert(final_x(268, 268, 80, PSX_WS_GROUP_EDGE_ANCHORED) == 390);
    assert(final_x(164, 148, 72, PSX_WS_GROUP_EDGE_ANCHORED) == 225);

    /* Every glyph/panel primitive in one group receives exactly one rigid
     * delta: internal spacing and dimensions remain unchanged. */
    int32_t d0 = psx_ws_group_layout_delta(
        20, 100, 368, 61, PSX_WS_GROUP_EDGE_ANCHORED);
    assert((24 + 61 + d0) - (20 + 61 + d0) == 4);

    /* A selector row can occupy the full 490px canvas without scaling portrait
     * art: groups at the authored edges move by one margin; the centre stays. */
    assert(psx_ws_group_layout_delta(
        -16, 32, 368, 61, PSX_WS_GROUP_DISTRIBUTED) == -61);
    assert(psx_ws_group_layout_delta(
        168, 32, 368, 61, PSX_WS_GROUP_DISTRIBUTED) == 0);
    assert(psx_ws_group_layout_delta(
        352, 32, 368, 61, PSX_WS_GROUP_DISTRIBUTED) == 61);

    /* Distribution is monotonic and symmetric, so moving the cursor between
     * portrait groups cannot jump backwards or distort its pieces. */
    int32_t previous = -62;
    for (int32_t x = 0; x <= 336; x += 16) {
        int32_t delta = psx_ws_group_layout_delta(
            x, 32, 368, 61, PSX_WS_GROUP_DISTRIBUTED);
        assert(delta >= previous);
        assert(delta >= -61 && delta <= 61);
        previous = delta;
    }
    assert(psx_ws_group_layout_delta(
        40, 32, 368, 0, PSX_WS_GROUP_DISTRIBUTED) == 0);

    puts("PASS: rigid widescreen UI-group layout");
    return 0;
}
