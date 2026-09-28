#include "widescreen_layer_classifier.h"

#include <stddef.h>

static int psx_ws_is_polygon(uint8_t opcode) {
    return opcode >= 0x20u && opcode <= 0x3fu;
}

static int psx_ws_is_line(uint8_t opcode) {
    return opcode >= 0x40u && opcode <= 0x5fu;
}

static int psx_ws_is_rect(uint8_t opcode) {
    return opcode >= 0x60u && opcode <= 0x7fu;
}

static int psx_ws_is_draw(uint8_t opcode) {
    return opcode == 0x02u || psx_ws_is_polygon(opcode) ||
           psx_ws_is_line(opcode) || psx_ws_is_rect(opcode);
}

static int psx_ws_is_semitransparent(uint8_t opcode) {
    if (opcode == 0x02u) return 0;
    if (!psx_ws_is_polygon(opcode) && !psx_ws_is_line(opcode) &&
        !psx_ws_is_rect(opcode))
        return 0;
    return (opcode & 0x02u) != 0;
}

static int psx_ws_all_positions_are_gte(
    const PsxWsPrimitiveEvidence *evidence) {
    uint8_t required;

    if (!evidence || evidence->vertex_count < 2u ||
        evidence->vertex_count > 4u)
        return 0;
    required = (uint8_t)((1u << evidence->vertex_count) - 1u);
    return (evidence->gte_position_mask & required) == required;
}

static int psx_ws_front_rank(const PsxWsPrimitiveEvidence *evidence) {
    return evidence->front_ot_rank != UINT16_MAX &&
           evidence->ot_rank == evidence->front_ot_rank;
}

static int psx_ws_screen_space_shape(
    const PsxWsPrimitiveEvidence *evidence) {
    return evidence->axis_aligned || psx_ws_is_rect(evidence->opcode) ||
           evidence->opcode == 0x02u;
}

/* Require complete coverage with a tiny allowance for PS1 inclusive/exclusive
 * endpoint conventions.  A merely large world polygon is not a backdrop. */
static int psx_ws_covers_screen(const PsxWsPrimitiveEvidence *evidence) {
    const int32_t tolerance = 2;

    if (evidence->display_width <= 0 || evidence->display_height <= 0)
        return 0;
    return evidence->min_x <= tolerance && evidence->min_y <= tolerance &&
           evidence->max_x >= evidence->display_width - tolerance &&
           evidence->max_y >= evidence->display_height - tolerance;
}

PsxWsLayer psx_ws_classify_layer(const PsxWsPrimitiveEvidence *evidence) {
    int covers_screen;

    if (!evidence || !psx_ws_is_draw(evidence->opcode))
        return PSX_WS_LAYER_IGNORE;

    /* This is the non-negotiable foreground/world rule.  It prevents Tekken's
     * fighters and stage polygons from being stretched or mistaken for HUD just
     * because they share an opcode, are axis aligned in one pose, or reach the
     * frontmost populated OT bucket. */
    if ((psx_ws_is_polygon(evidence->opcode) ||
         psx_ws_is_line(evidence->opcode)) &&
        psx_ws_all_positions_are_gte(evidence))
        return PSX_WS_LAYER_WORLD_3D;

    if (evidence->scene_has_3d && evidence->sprite_tagged)
        return PSX_WS_LAYER_WORLD_ANCHORED_EFFECT;

    covers_screen = psx_ws_screen_space_shape(evidence) &&
                    psx_ws_covers_screen(evidence);
    if (covers_screen && !psx_ws_is_semitransparent(evidence->opcode)) {
        if (!evidence->scene_has_3d)
            return PSX_WS_LAYER_MENU_BACKDROP;
        if (!evidence->world_seen_before)
            return PSX_WS_LAYER_STAGE_BACKDROP;
    }

    /* Anything screen-covering after world submission is a fade/filter rather
     * than scenery.  It still needs wide coverage, but it must not become an
     * authority for reconstructing missing stage pixels. */
    if (covers_screen && evidence->world_seen_before)
        return PSX_WS_LAYER_SCREEN_EFFECT;

    if (!evidence->scene_has_3d)
        return PSX_WS_LAYER_MENU_UI;

    if (psx_ws_screen_space_shape(evidence) &&
        psx_ws_front_rank(evidence))
        return PSX_WS_LAYER_HUD;

    return PSX_WS_LAYER_SCREEN_SPACE_UNKNOWN;
}

PsxWsLayerPolicy psx_ws_layer_policy(PsxWsLayer layer) {
    switch (layer) {
        case PSX_WS_LAYER_IGNORE:
            return PSX_WS_POLICY_IGNORE;
        case PSX_WS_LAYER_WORLD_3D:
        case PSX_WS_LAYER_WORLD_ANCHORED_EFFECT:
            return PSX_WS_POLICY_WORLD_NATIVE;
        case PSX_WS_LAYER_STAGE_BACKDROP:
        case PSX_WS_LAYER_MENU_BACKDROP:
            return PSX_WS_POLICY_BACKDROP_EXTEND;
        case PSX_WS_LAYER_SCREEN_EFFECT:
            return PSX_WS_POLICY_WIDE_COVERAGE;
        case PSX_WS_LAYER_HUD:
        case PSX_WS_LAYER_MENU_UI:
            return PSX_WS_POLICY_UI_RELAYOUT;
        case PSX_WS_LAYER_SCREEN_SPACE_UNKNOWN:
        default:
            return PSX_WS_POLICY_SAFE_AREA;
    }
}

int psx_ws_layer_is_world(PsxWsLayer layer) {
    return layer == PSX_WS_LAYER_WORLD_3D ||
           layer == PSX_WS_LAYER_WORLD_ANCHORED_EFFECT;
}

int psx_ws_layer_can_cover_margins(PsxWsLayer layer) {
    PsxWsLayerPolicy policy = psx_ws_layer_policy(layer);
    return policy == PSX_WS_POLICY_BACKDROP_EXTEND ||
           policy == PSX_WS_POLICY_WIDE_COVERAGE;
}

int psx_ws_layer_needs_authored_layout(PsxWsLayer layer) {
    return layer == PSX_WS_LAYER_HUD || layer == PSX_WS_LAYER_MENU_UI ||
           layer == PSX_WS_LAYER_MENU_BACKDROP;
}

int psx_ws_is_opaque_backdrop_band(const PsxWsPrimitiveEvidence *evidence) {
    const int32_t x_tolerance = 2;
    if (!evidence || !psx_ws_is_polygon(evidence->opcode) ||
        evidence->vertex_count != 4u || !evidence->axis_aligned ||
        psx_ws_is_semitransparent(evidence->opcode) ||
        psx_ws_all_positions_are_gte(evidence) || evidence->sprite_tagged ||
        evidence->display_width <= 0 || evidence->display_height <= 0)
        return 0;

    return evidence->min_x <= x_tolerance &&
           evidence->max_x >= evidence->display_width - x_tolerance &&
           evidence->max_y > evidence->min_y &&
           evidence->max_y - evidence->min_y >= 64;
}
