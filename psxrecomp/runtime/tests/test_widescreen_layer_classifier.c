#include "widescreen_layer_classifier.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static PsxWsPrimitiveEvidence base(uint8_t opcode) {
    PsxWsPrimitiveEvidence e;
    memset(&e, 0, sizeof(e));
    e.opcode = opcode;
    e.ot_rank = UINT16_MAX;
    e.front_ot_rank = UINT16_MAX;
    e.display_width = 368;
    e.display_height = 480;
    return e;
}

int main(void) {
    PsxWsPrimitiveEvidence e;

    /* Tekken stage and fighter meshes share these textured polygon families.
     * Exact GTE-to-DMA provenance, not opcode or bbox, owns classification. */
    e = base(0x3c);
    e.vertex_count = 4;
    e.gte_position_mask = 0x0f;
    e.scene_has_3d = 1;
    e.axis_aligned = 1;
    e.ot_rank = e.front_ot_rank = 180;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_WORLD_3D);
    assert(psx_ws_layer_policy(psx_ws_classify_layer(&e)) ==
           PSX_WS_POLICY_WORLD_NATIVE);

    e = base(0x24);
    e.vertex_count = 3;
    e.gte_position_mask = 0x07;
    e.scene_has_3d = 1;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_WORLD_3D);

    /* Partial provenance must fail closed.  A CPU-authored primitive that reuses
     * one rounded projection cannot become world geometry. */
    e.gte_position_mask = 0x03;
    assert(psx_ws_classify_layer(&e) ==
           PSX_WS_LAYER_SCREEN_SPACE_UNKNOWN);

    e = base(0x65);
    e.scene_has_3d = 1;
    e.sprite_tagged = 1;
    assert(psx_ws_classify_layer(&e) ==
           PSX_WS_LAYER_WORLD_ANCHORED_EFFECT);

    /* An early opaque screen-covering primitive is the only generic backdrop
     * candidate.  It may fill margins but must never scale fighters. */
    e = base(0x28);
    e.vertex_count = 4;
    e.axis_aligned = 1;
    e.scene_has_3d = 1;
    e.min_x = 0; e.min_y = 0; e.max_x = 368; e.max_y = 480;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_STAGE_BACKDROP);
    assert(psx_ws_layer_can_cover_margins(PSX_WS_LAYER_STAGE_BACKDROP));

    /* Tekken's forest is segmented into substantial, opaque, full-width
     * bands. These exact observed ranges must extend even though neither band
     * covers the complete screen height. */
    e = base(0x38);
    e.vertex_count = 4;
    e.axis_aligned = 1;
    e.scene_has_3d = 1;
    e.min_x = 0; e.max_x = 368; e.min_y = 277; e.max_y = 405;
    assert(psx_ws_is_opaque_backdrop_band(&e));
    e.min_y = 405; e.max_y = 480;
    assert(psx_ws_is_opaque_backdrop_band(&e));

    e.max_x = 360;
    assert(!psx_ws_is_opaque_backdrop_band(&e));
    e.max_x = 368;
    e.opcode = 0x3a; /* semitransparent */
    assert(!psx_ws_is_opaque_backdrop_band(&e));
    e.opcode = 0x38;
    e.gte_position_mask = 0x0f;
    assert(!psx_ws_is_opaque_backdrop_band(&e));

    /* The same cover after 3D is a filter/fade, including semitransparent op. */
    e.opcode = 0x2a;
    e.world_seen_before = 1;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_SCREEN_EFFECT);
    assert(psx_ws_layer_policy(PSX_WS_LAYER_SCREEN_EFFECT) ==
           PSX_WS_POLICY_WIDE_COVERAGE);

    /* Front-ranked screen-space groups are HUD.  World provenance still wins
     * even if a polygon occupies that same rank. */
    e = base(0x65);
    e.axis_aligned = 1;
    e.scene_has_3d = 1;
    e.world_seen_before = 1;
    e.ot_rank = e.front_ot_rank = 180;
    e.min_x = 12; e.min_y = 8; e.max_x = 132; e.max_y = 40;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_HUD);
    assert(psx_ws_layer_needs_authored_layout(PSX_WS_LAYER_HUD));

    e = base(0x34);
    e.vertex_count = 3;
    e.gte_position_mask = 0x07;
    e.axis_aligned = 1;
    e.scene_has_3d = 1;
    e.world_seen_before = 1;
    e.ot_rank = e.front_ot_rank = 180;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_WORLD_3D);

    /* Character select is authored 2D.  Its background needs extension or new
     * art; portraits/grid/text need group re-layout, never a wider camera. */
    e = base(0x2c);
    e.vertex_count = 4;
    e.axis_aligned = 1;
    e.min_x = 0; e.min_y = 0; e.max_x = 368; e.max_y = 480;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_MENU_BACKDROP);
    assert(psx_ws_layer_policy(PSX_WS_LAYER_MENU_BACKDROP) ==
           PSX_WS_POLICY_BACKDROP_EXTEND);
    assert(psx_ws_layer_needs_authored_layout(PSX_WS_LAYER_MENU_BACKDROP));

    e = base(0x65);
    e.axis_aligned = 1;
    e.min_x = 40; e.min_y = 60; e.max_x = 88; e.max_y = 108;
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_MENU_UI);
    assert(psx_ws_layer_policy(PSX_WS_LAYER_MENU_UI) ==
           PSX_WS_POLICY_UI_RELAYOUT);

    /* Transfers and environment words are never visual-layer candidates. */
    e = base(0xa0);
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_IGNORE);
    e = base(0xe5);
    assert(psx_ws_classify_layer(&e) == PSX_WS_LAYER_IGNORE);

    puts("PASS: provenance-first widescreen layer classification");
    return 0;
}
