#ifndef PSXRECOMP_WIDESCREEN_LAYER_CLASSIFIER_H
#define PSXRECOMP_WIDESCREEN_LAYER_CLASSIFIER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * A renderer cannot infer scene ownership from the GP0 opcode.  Tekken 3, for
 * example, submits the stage, fighters and several effects through the same
 * textured-polygon families.  This classifier therefore consumes provenance
 * gathered before rasterisation:
 *
 *   - gte_position_mask says which position words in the DMA packet are exact
 *     SWC2 projection stores (same address + packed value),
 *   - sprite_tagged identifies a screen-space primitive tied to a projected
 *     world anchor,
 *   - OT rank and draw phase separate the front UI layer from the world, and
 *   - screen coverage identifies only genuine backdrop/filter candidates.
 *
 * The result is deliberately a small cross-backend contract.  It does not
 * mutate coordinates and it is an exact identity when a caller does not opt in
 * to widescreen processing.
 */
typedef enum PsxWsLayer {
    PSX_WS_LAYER_IGNORE = 0,
    PSX_WS_LAYER_WORLD_3D,
    PSX_WS_LAYER_WORLD_ANCHORED_EFFECT,
    PSX_WS_LAYER_STAGE_BACKDROP,
    PSX_WS_LAYER_SCREEN_EFFECT,
    PSX_WS_LAYER_HUD,
    PSX_WS_LAYER_MENU_BACKDROP,
    PSX_WS_LAYER_MENU_UI,
    PSX_WS_LAYER_SCREEN_SPACE_UNKNOWN
} PsxWsLayer;

typedef enum PsxWsLayerPolicy {
    PSX_WS_POLICY_IGNORE = 0,

    /* Keep the model's shape and native projection.  A wider camera and the
     * guest's object/polygon culls are the only valid ways to reveal more. */
    PSX_WS_POLICY_WORLD_NATIVE,

    /* Extend coverage into synthetic margins without scaling foreground
     * geometry.  The implementation may expand a solid plane, tile authored
     * background texels, or render a dedicated background pass. */
    PSX_WS_POLICY_BACKDROP_EXTEND,

    /* Keep each element's size/aspect and translate complete spatial groups to
     * anchors in the expanded canvas. */
    PSX_WS_POLICY_UI_RELAYOUT,

    /* A proven full-screen fade/filter must continue to cover the full output. */
    PSX_WS_POLICY_WIDE_COVERAGE,

    /* Insufficient evidence: preserve the primitive in the original safe area. */
    PSX_WS_POLICY_SAFE_AREA
} PsxWsLayerPolicy;

typedef struct PsxWsPrimitiveEvidence {
    uint8_t opcode;
    uint8_t vertex_count;       /* position words represented by the mask (0..4) */
    uint8_t gte_position_mask;  /* bit i = exact GTE RAM provenance for vertex i */
    uint8_t sprite_tagged;      /* screen-space geometry tied to a world anchor */
    uint8_t axis_aligned;       /* exact rectangle/axis-aligned-quad test */
    uint8_t scene_has_3d;       /* stable game/scene classification, not this prim */
    uint8_t world_seen_before;  /* proven WORLD_3D already submitted this frame */
    uint8_t reserved;

    uint16_t ot_rank;
    uint16_t front_ot_rank;     /* 0xffff when no complete OT prepass is available */

    int32_t min_x;
    int32_t min_y;
    int32_t max_x;              /* exclusive */
    int32_t max_y;              /* exclusive */
    int32_t display_width;
    int32_t display_height;
} PsxWsPrimitiveEvidence;

/* Classify one complete GP0 primitive.  Transfer/environment commands return
 * IGNORE.  Complete GTE provenance always wins over shape/rank heuristics. */
PsxWsLayer psx_ws_classify_layer(const PsxWsPrimitiveEvidence *evidence);

PsxWsLayerPolicy psx_ws_layer_policy(PsxWsLayer layer);

/* Convenience predicates for renderer integration. */
int psx_ws_layer_is_world(PsxWsLayer layer);
int psx_ws_layer_can_cover_margins(PsxWsLayer layer);
int psx_ws_layer_needs_authored_layout(PsxWsLayer layer);

/* Strict renderer-side backdrop band predicate.  Tekken composes a backdrop
 * from multiple opaque, full-canonical-width horizontal quads rather than one
 * full-height rectangle.  Admit those substantial bands while rejecting
 * semitransparent filters, partial-width panels and GTE-projected world/fighter
 * polygons. */
int psx_ws_is_opaque_backdrop_band(const PsxWsPrimitiveEvidence *evidence);

#ifdef __cplusplus
}
#endif

#endif /* PSXRECOMP_WIDESCREEN_LAYER_CLASSIFIER_H */
