#ifndef TEKKEN3_SELECTOR_LAYOUT_H
#define TEKKEN3_SELECTOR_LAYOUT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Evidence extracted from Tekken 3's alternating selector DMA packet arenas.
 * Coordinates are canonical 4:3 draw coordinates, before draw offset. */
typedef struct Tekken3SelectorPacket {
    uint32_t source_addr;
    uint8_t opcode;
    int32_t x;
    int32_t y;
    int32_t width;
    int32_t height;
} Tekken3SelectorPacket;

typedef enum Tekken3SelectorRole {
    TEKKEN3_SELECTOR_NONE = 0,
    TEKKEN3_SELECTOR_BACKDROP,
    TEKKEN3_SELECTOR_LEFT_PLAYER,
    TEKKEN3_SELECTOR_RIGHT_PLAYER,
    TEKKEN3_SELECTOR_LEFT_FRAME,
    TEKKEN3_SELECTOR_RIGHT_FRAME,
    TEKKEN3_SELECTOR_ROSTER,
    TEKKEN3_SELECTOR_CENTRE
} Tekken3SelectorRole;


typedef struct Tekken3SelectorFrame {
    uint32_t arena_lo;
    uint32_t arena_hi;
    uint32_t backdrop_source;
    int32_t backdrop_height;
    int32_t display_width;
    int32_t display_height;
    int active;
    /* 0 = cabinet selector, 1 = main menu, 2 = team roster selector. */
    int layout_kind;
    /* Observed complete roster: cabinet 10/11 columns, team 7/8 columns. */
    int roster_columns;
    /* Team roster screen: Tekken Ball's ball choice (or another choice
     * made in the same centred panel between the two chosen faces). */
    int choice_panel;
    /* VS handicap panels under that centred panel: how far each player's
     * LIFE bar sits from its resting place (0 = in place, -149 / +149 =
     * parked just outside the 4:3 screen), and whether it was seen. */
    int handicap_seen[2];
    int32_t handicap_slide[2];
} Tekken3SelectorFrame;

typedef struct Tekken3SelectorPlacement {
    Tekken3SelectorRole role;
    /* Added only by the native-wide sidecar. Canonical VRAM never receives it. */
    int32_t sidecar_dx;
    /* The backdrop is widened by the renderer's existing sidecar scale path. */
    int expand_backdrop;
    /* Widen by pieces instead (gr_wide_set_primitive_split): display x below
     * split_lo follows the left player's panel, above split_hi the right's,
     * and [split_lo, split_hi] stretches between them. Off while equal. */
    int32_t split_lo, split_hi;
    /* Skip the animated full-screen selector layer in the sidecar while the
     * canonical 4:3 renderer continues to receive it unchanged. */
    int suppress_sidecar;
    /* Tekken retains the lower cabinet/roster in canonical VRAM, then submits
     * its sprites and gradient under a y<=339 (locked) or y<=305 (unlocked)
     * draw area. Reconstruct those exact sidecar packets while canonical PS1
     * clipping stays unchanged. */
    int unclipped_sidecar;
    /* Repeat an authored narrow decorative frame only in the synthetic outer
     * margin, filling the otherwise empty selector sides with real UI art. */
    int duplicate_outer;
    /* Stable rigid-composite key: 1=left player, 2=right, 3=centre,
     * 4..13=stock cabinet slots; expanded rosters use 20+column. */
    uint32_t group_id;
} Tekken3SelectorPlacement;

/* Find an authored UI in one complete GPU linked list. Arena addresses alone
 * are insufficient: cabinet selectors require the base and both 126px player
 * panels; the main menu requires all logo tiles and its highlight; Team Battle
 * requires its clear, two gradients and complete three-row roster. */
int tekken3_selector_analyze_frame(const Tekken3SelectorPacket *packets,
                                   size_t count,
                                   int32_t display_width,
                                   int32_t display_height,
                                   Tekken3SelectorFrame *out);

/* A completed selector survives lists with no drawing (CD/upload waits).
 * New drawing outside its proven arena or a display-mode change ends it. */
int tekken3_selector_can_retain_frame(const Tekken3SelectorFrame *frame,
    const Tekken3SelectorPacket *packets, size_t count,
    int32_t display_width, int32_t display_height);

/* A completed full-mirror gameplay image survives no-draw scene/CD waits.
 * A new non-game draw, framebuffer upload, video, or format change ends it. */
int tekken3_gameplay_retain(int retained, int enabled, int has_draw,
    int gameplay_draw, int framebuffer_changed, int32_t width, int32_t height,
    int video);

/* Map a packet to one authored layer/composite. Every primitive belonging to
 * a player panel receives the same +/-margin delta. Roster grids stay compact
 * and centered, and the active cursor plus its 1P/CPU label follows the
 * selected slot. The timer remains centered,
 * and the cabinet grid fills the canvas. margin==0 is strict 4:3 identity. */
Tekken3SelectorPlacement tekken3_selector_place(
    const Tekken3SelectorFrame *frame,
    const Tekken3SelectorPacket *packet,
    int32_t margin);

/* Versus/loading is a retained 2D scene. Its two sliding 126x212 portraits,
 * borders and names are independent rigid groups; the tiled backdrop alone
 * fills the wider coordinate space. Upload-only lists retain this frame. */
typedef struct Tekken3LoadingFrame {
    uint32_t arena_lo, arena_hi;
    uint32_t left_source, right_source;
    int active;
    int layout_kind; /* 0 arcade, 1 Team Battle, 2 Tekken Force */
} Tekken3LoadingFrame;

int tekken3_loading_analyze_frame(const Tekken3SelectorPacket *packets,
    size_t count, int32_t display_width, int32_t display_height,
    Tekken3LoadingFrame *out);
Tekken3SelectorPlacement tekken3_loading_place(
    const Tekken3LoadingFrame *frame, const Tekken3SelectorPacket *packet,
    int32_t margin);

#ifdef __cplusplus
}
#endif

#endif /* TEKKEN3_SELECTOR_LAYOUT_H */
