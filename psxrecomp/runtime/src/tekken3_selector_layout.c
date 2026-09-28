#include "tekken3_selector_layout.h"

#include <string.h>

#define T3_SEL_A_LO 0x00125000u
#define T3_SEL_A_HI 0x00126400u
#define T3_SEL_B_LO 0x00120A00u
#define T3_SEL_B_HI 0x00121E00u

/* VS handicap LIFE bars: resting x of each bar's frame, and how far the
 * game parks it to hide it (just past the 4:3 edge). */
#define T3_HANDICAP_LEFT_X 23
#define T3_HANDICAP_RIGHT_X 221
#define T3_HANDICAP_TRAVEL 149

/* The unlocked roster and CREDIT / INSERT COIN glyphs allocate extra records
 * ahead of the clear (observed at 0x12609C / 0x121A9C). Keep bounded arenas,
 * with the complete clear + both portrait composites as the scene authority. */

static uint32_t phys(uint32_t address) {
    return address & 0x1FFFFFu;
}

int tekken3_gameplay_retain(int retained, int enabled, int has_draw,
    int gameplay_draw, int framebuffer_changed, int32_t width, int32_t height,
    int video) {
    if (!enabled || width != 368 || height != 480 || video || framebuffer_changed)
        return 0;
    return has_draw ? !!gameplay_draw : !!retained;
}

static int arena_for(uint32_t address, uint32_t *lo, uint32_t *hi) {
    uint32_t a = phys(address);
    if (a >= T3_SEL_A_LO && a < T3_SEL_A_HI) {
        if (lo) *lo = T3_SEL_A_LO;
        if (hi) *hi = T3_SEL_A_HI;
        return 1;
    }
    if (a >= T3_SEL_B_LO && a < T3_SEL_B_HI) {
        if (lo) *lo = T3_SEL_B_LO;
        if (hi) *hi = T3_SEL_B_HI;
        return 1;
    }
    return 0;
}

static int full_base(const Tekken3SelectorPacket *p, int32_t width) {
    return p->opcode == 0x60u && p->x == 0 && p->y == 0 &&
           p->width == width && (p->height == 340 || p->height == 306);
}

static uint8_t player_panel_coverage(const Tekken3SelectorPacket *p, int side,
                                     int32_t width, int32_t panel_top) {
    static const int32_t sample_offsets[] = { 12, 42, 82, 142, 197, 227 };
    int32_t right = p->x + p->width;
    uint8_t mask = 0;
    if (p->opcode != 0x2Du && p->opcode != 0x2Eu && p->opcode != 0x3Eu)
        return 0;
    if (p->width != 126 || p->height <= 0 || p->y < panel_top ||
        p->y + p->height > panel_top + 252)
        return 0;
    if (side < 0) {
        if (p->x != 33 || right != 159) return 0;
    } else if (p->x != width - 159 || right != width - 33) {
        return 0;
    }
    /* The portrait/panel is authored as horizontal strips. Arena A/B use the
     * same six vertical bands; the left lower band is split at y=254 while the
     * right is one y=240..300 quad. Sample coverage fingerprints the complete
     * composite without assuming one particular tessellation. */
    for (size_t i = 0;
         i < sizeof(sample_offsets) / sizeof(sample_offsets[0]); i++) {
        int32_t sample = panel_top + sample_offsets[i];
        if (p->y <= sample && sample < p->y + p->height)
            mask |= (uint8_t)(1u << i);
    }
    return mask;
}

/* Main menu and Team Battle use independent alternating DMA arenas. A
 * complete authored composition, never an address alone, establishes them. */
static int other_menu_frame(const Tekken3SelectorPacket *packets, size_t count,
                            Tekken3SelectorFrame *out) {
    static const uint32_t menu_lo[] = {0x15C000u, 0x15FC00u};
    static const uint32_t team_lo[] = {0xB8000u, 0xBBC00u};
    for (int kind = 1; kind <= 2; kind++) {
        for (int buffer = 0; buffer < 2; buffer++) {
            uint32_t lo = kind == 1 ? menu_lo[buffer] : team_lo[buffer];
            uint32_t hi = lo + 0x3C00u;
            uint32_t tiles = 0, roster = 0, expanded_roster = 0, six_roster = 0, base = 0;
            int bar = 0, gradients = 0, menu_fades = 0, menu_glyphs = 0;
            int choice_panel = 0;
            int handicap_seen[2] = {0, 0};
            int32_t handicap_slide[2] = {0, 0};
            for (size_t i = 0; i < count; i++) {
                const Tekken3SelectorPacket *p = &packets[i];
                uint32_t a = phys(p->source_addr);
                if (a < lo || a >= hi) continue;
                if (kind == 1) {
                    if (p->opcode == 0x65 && p->x >= 0 && p->x <= 256 &&
                        p->x % 128 == 0 && p->y >= 0 && p->y <= 448 &&
                        p->y % 64 == 0 &&
                        p->width == (p->x == 256 ? 112 : 128) &&
                        p->height == (p->y == 448 ? 32 : 64))
                        tiles |= 1u << ((p->x / 128) * 8 + p->y / 64);
                    if (p->opcode == 0x38 && p->y == 360 && p->height == 28 &&
                        p->width == 176 && (p->x == 8 || p->x == 184))
                        bar |= p->x == 8 ? 1 : 2;
                    /* Navigation temporarily omits the highlight. The full
                     * logo, scrolling glyphs and two fade masks still prove
                     * the same menu in either alternating packet arena. */
                    if (p->opcode == 0x3A && p->x == 68 && p->width == 232 &&
                        p->height == 28) {
                        if (p->y == 316) menu_fades |= 1;
                        if (p->y == 404) menu_fades |= 2;
                    }
                    if (p->opcode == 0x65 && p->width == 14 && p->height == 24 &&
                        p->y >= 250 && p->y <= 480) menu_glyphs++;
                } else {
                    if (p->opcode == 0x60 && p->x == 0 && p->y == 0 &&
                        p->width == 368 && p->height == 480) base = a;
                    /* The ball choice's dark panel, between its two fades. */
                    if (p->opcode == 0x62 && p->x == 88 && p->y == 315 &&
                        p->width == 192 && p->height == 80)
                        choice_panel = 1;
                    /* VS handicap: each LIFE bar's frame, 124 x 16 at
                     * (23, 418) / (221, 418) once in place. */
                    if (p->opcode == 0x60 && p->y == 418 &&
                        p->width == 124 && p->height == 16) {
                        int side = p->x < T3_HANDICAP_RIGHT_X ? 0 : 1;
                        handicap_seen[side] = 1;
                        handicap_slide[side] = p->x -
                            (side ? T3_HANDICAP_RIGHT_X : T3_HANDICAP_LEFT_X);
                    }
                    if (p->opcode == 0x38 && p->x == 0 && p->width == 368) {
                        if (p->y == 277 && p->height == 128) gradients |= 1;
                        if (p->y == 405 && p->height == 75) gradients |= 2;
                    }
                    /* Sample each cell at its top. Gon is three texture
                     * strips instead of one 32x58 sprite. */
                    if (p->opcode == 0x65 && p->width == 32 &&
                        p->x >= 59 && p->x <= 275 && (p->x - 59) % 36 == 0 &&
                        p->y >= 70 && p->y <= 196 && (p->y - 70) % 63 == 0 &&
                        p->height >= 10 && p->height <= 58)
                        roster |= 1u << (((p->y - 70) / 63) * 7 + (p->x - 59) / 36);
                    if (p->opcode == 0x65 && p->width == 32 &&
                        p->x >= 43 && p->x <= 295 && (p->x - 43) % 36 == 0 &&
                        p->y >= 70 && p->y <= 196 && (p->y - 70) % 63 == 0 &&
                        p->height >= 10 && p->height <= 58) {
                        unsigned cell = ((p->y - 70) / 63) * 8 + (p->x - 43) / 36;
                        if (cell < 22) expanded_roster |= 1u << cell;
                    }
                    /* Six columns from x=77: the TTT1 guests' Tag page,
                     * rows of six. */
                    if (p->opcode == 0x65 && p->width == 32 &&
                        p->x >= 77 && p->x <= 257 && (p->x - 77) % 36 == 0 &&
                        p->y >= 70 && p->y <= 196 && (p->y - 70) % 63 == 0 &&
                        p->height >= 10 && p->height <= 58) {
                        unsigned cell = ((p->y - 70) / 63) * 6 + (p->x - 77) / 36;
                        if (cell < 18) six_roster |= 1u << cell;
                    }
                }
            }
            if ((kind == 1 && tiles == 0xFFFFFFu &&
                 (bar == 3 || (menu_fades == 3 && menu_glyphs >= 6))) ||
                (kind == 2 && base && gradients == 3 &&
                 (roster == 0x1FFFFFu || expanded_roster == 0x3FFFFFu ||
                  /* The TTT1 guests' Tag page, rows of six filled from
                   * its first cell. A partial eight-column grid is a
                   * frame still being drawn, not a page. */
                  (six_roster >= 0x3Fu &&
                   (six_roster & (six_roster + 1u)) == 0)))) {
                out->arena_lo = lo;
                out->arena_hi = hi;
                out->backdrop_source = base;
                out->backdrop_height = 480;
                out->layout_kind = kind;
                out->roster_columns = kind == 2 ? (roster == 0x1FFFFFu ? 7 :
                                       six_roster >= 0x3Fu ? 6 : 8) : 0;
                out->choice_panel = kind == 2 && choice_panel;
                if (out->choice_panel) {
                    for (int side = 0; side < 2; side++) {
                        out->handicap_seen[side] = handicap_seen[side];
                        out->handicap_slide[side] = handicap_slide[side];
                    }
                }
                out->active = 1;
                return 1;
            }
        }
    }
    return 0;
}

int tekken3_selector_analyze_frame(const Tekken3SelectorPacket *packets,
                                   size_t count,
                                   int32_t display_width,
                                   int32_t display_height,
                                   Tekken3SelectorFrame *out) {
    uint32_t anchor = 0, arena_lo = 0, arena_hi = 0;
    int32_t backdrop_height = 0;
    uint8_t left_coverage = 0, right_coverage = 0;
    size_t i;

    if (!out) return 0;
    memset(out, 0, sizeof(*out));
    out->display_width = display_width;
    out->display_height = display_height;
    if (!packets || display_width != 368 || display_height < 224)
        return 0;

    for (i = 0; i < count; i++) {
        uint32_t lo, hi;
        if (!arena_for(packets[i].source_addr, &lo, &hi) ||
            !full_base(&packets[i], display_width))
            continue;
        anchor = phys(packets[i].source_addr);
        backdrop_height = packets[i].height;
        arena_lo = lo;
        arena_hi = hi;
        break;
    }
    if (!anchor) return display_height == 480
        ? other_menu_frame(packets, count, out) : 0;

    for (i = 0; i < count; i++) {
        uint32_t source = phys(packets[i].source_addr);
        if (source < arena_lo || source >= arena_hi) continue;
        int32_t panel_top = backdrop_height == 306 ? 14 : 48;
        left_coverage |= player_panel_coverage(
            &packets[i], -1, display_width, panel_top);
        right_coverage |= player_panel_coverage(
            &packets[i], +1, display_width, panel_top);
    }
    /* Require every vertical sample on both symmetric player composites. This
     * prevents an unrelated 368x340 clear or one incidental strip from arming
     * the complete-sidecar presentation contract. */
    if (left_coverage != 0x3Fu || right_coverage != 0x3Fu) return 0;

    out->arena_lo = arena_lo;
    out->arena_hi = arena_hi;
    out->backdrop_source = anchor;
    out->backdrop_height = backdrop_height;
    uint32_t expanded_roster = 0;
    for (i = 0; i < count; i++) {
        const Tekken3SelectorPacket *p = &packets[i];
        uint32_t source = phys(p->source_addr);
        if (source < arena_lo || source >= arena_hi || p->opcode != 0x65 ||
            p->width != 32 || p->height < 10 || p->height > 58 ||
            (p->y != 336 && p->y != 398) || p->x < 3 || p->x > 333 ||
            (p->x - 3) % 33) continue;
        expanded_roster |= 1u << (((p->y - 336) / 62) * 11 + (p->x - 3) / 33);
    }
    out->roster_columns = expanded_roster == 0x3FFFFFu ? 11 : 10;
    out->active = 1;
    return 1;
}

static int same_arena(const Tekken3SelectorFrame *f, uint32_t source) {
    source = phys(source);
    return source >= f->arena_lo && source < f->arena_hi;
}

int tekken3_selector_can_retain_frame(const Tekken3SelectorFrame *frame,
    const Tekken3SelectorPacket *packets, size_t count,
    int32_t display_width, int32_t display_height) {
    if (!frame || !frame->active || (count && !packets) ||
        display_width != frame->display_width ||
        display_height != frame->display_height)
        return 0;
    for (size_t i = 0; i < count; i++) {
        const Tekken3SelectorPacket *p = &packets[i];
        if (p->opcode >= 0x20u && p->opcode < 0x80u &&
            !same_arena(frame, p->source_addr))
            return 0;
    }
    return 1;
}

static int side_from_bounds(const Tekken3SelectorFrame *f,
                            const Tekken3SelectorPacket *p) {
    int32_t right = p->x + p->width;
    int32_t mid = f->display_width / 2;
    if (p->width >= 96 && p->y >= (f->backdrop_height == 306 ? -6 : 10) &&
        p->y + p->height <= f->backdrop_height) {
        if (right <= mid) return -1;
        if (p->x >= mid) return +1;
    }
    return 0;
}

static int rounded_div_nonnegative(int numerator, int denominator) {
    return (numerator + denominator / 2) / denominator;
}

/* Keep the roster centered at its authored portrait spacing. The expanded
 * eleven-column grid is squeezed to a 33px pitch in 4:3; use up to 10px of
 * each wide margin to restore the stock 35px pitch (3px portrait gaps).
 * Additional screen width belongs outside the grid, not between faces. */
static int roster_delta(int slot, int columns, int32_t margin) {
    if (columns != 11 || margin <= 0 || slot < 0 || slot >= columns) return 0;
    int reveal = margin < 10 ? margin : 10;
    return -reveal + rounded_div_nonnegative(slot * 2 * reveal, columns - 1);
}

static int roster_slot_from_cursor(const Tekken3SelectorPacket *p) {
    int32_t authored_x;
    int32_t dx;
    if (p->opcode != 0x64u ||
        !((p->width == 20 && (p->y == 328 || p->y == 363 || p->y == 390)) ||
          (p->width == 18 && (p->y == 334 || p->y == 363 || p->y == 396))))
        return -1;
    /* Native panel+0x7A offsets the 2P label by 20px; frame halves do not
     * inherit that offset (8010F9C8 / 8010F9DC). From upstream v0.1.3. */
    if (p->width == 20 && p->x >= 29 && (p->x - 29) % 35 == 0)
        authored_x = 29;
    else if (p->width == 20 ||
        (p->width == 18 && p->x >= 9 && (p->x - 9) % 35 == 0))
        authored_x = 9;
    else if (p->width == 18 && p->x >= 27 && (p->x - 27) % 35 == 0)
        authored_x = 27;
    else
        return -1;
    dx = p->x - authored_x;
    if (dx < 0 || dx % 35 != 0 || dx / 35 > 9) return -1;
    return dx / 35;
}

static Tekken3SelectorPlacement other_menu_place(
    const Tekken3SelectorFrame *f, const Tekken3SelectorPacket *p, int32_t margin) {
    Tekken3SelectorPlacement out = {0};
    out.role = TEKKEN3_SELECTOR_CENTRE;
    out.group_id = 3;
    if (f->layout_kind == 1) {
        /* The logo is baked into the 24 full-screen background tiles. Keep
         * that artwork and every menu glyph proportional and centered. */
        if (p->opcode == 0x38 && p->y >= 360 && p->y <= 386 &&
            p->height <= 28 && p->width >= 176) {
            out.role = TEKKEN3_SELECTOR_BACKDROP;
            out.expand_backdrop = 1;
        }
        return out;
    }
    if ((p->opcode == 0x60 && p->x == 0 && p->y == 0 &&
         p->width == 368 && p->height == 480) ||
        (p->opcode == 0x38 && (p->y == 24 || p->y >= 277))) {
        out.role = TEKKEN3_SELECTOR_BACKDROP;
        out.expand_backdrop = 1;
        return out;
    }
    /* Portraits, border lines and both players' cursor ornaments stay in one
     * centered grid at the authored 36px pitch. Inclusive bounds matter. */
    int columns = f->roster_columns == 8 || f->roster_columns == 6 ? f->roster_columns : 7;
    int origin = columns == 6 ? 75 : columns == 8 ? 41 : 57;
    if (p->y >= 60 && p->y + p->height <= 258 &&
        (p->opcode == 0x40 || p->opcode == 0x64 || p->opcode == 0x65) &&
        p->width <= 36 && p->height <= 64 &&
        p->x >= origin - 2 && p->x <= origin + columns * 36 + 1) {
        int column = (p->x + p->width / 2 - origin) / 36;
        if (column < 0) column = 0;
        if (column >= columns) column = columns - 1;
        out.role = TEKKEN3_SELECTOR_ROSTER;
        out.group_id = (columns != 7 ? 20u : 4u) + (uint32_t)column;
        return out;
    }
    /* Keep the scrolling title and its narrow blue edge gradients centered
     * with the compact roster. */
    if (p->opcode == 0x3A && p->y == 67 && p->height == 190 && p->width == 32) {
        return out;
    }
    /* Tekken Ball's ball choice is one centred panel from x = 48 to 320:
     * both chosen faces at its ends, the ball's name and damage between
     * them, the first player's name above. Sorting its glyphs by their
     * own x sent BEA left and ALL right of BEACH BALL. Only the credit
     * line, 10x16 glyphs at y = 278, stays with the right player. VS
     * draws both players' names in 14x24 glyphs at y = 274, each over
     * its underline (y = 292): they stay with the centred faces, the
     * right one too. */
    if (f->choice_panel && p->y >= 270 &&
        !(p->y < 300 && p->x >= 208 && p->opcode == 0x65 &&
          p->width == 10 && p->height == 16)) {
        /* VS draws its score in the same panel and, under it, each
         * player's LIFE handicap bar: parked just past the 4:3 edge until
         * that player has chosen, then slid in. Centred as is, the parked
         * bars showed in the 16:9 margins; stretch their travel so they
         * start past the wide edge instead. The chosen faces' frame
         * lines end at y = 386 and stay with the faces. */
        if (p->y >= 370 && p->y + p->height <= 440 &&
            (p->opcode < 0x40 || p->opcode >= 0x60)) {
            int side = p->x + p->width <= 150 ? 0 : p->x >= 219 ? 1 : -1;
            if (side >= 0 && f->handicap_seen[side])
                out.sidecar_dx = f->handicap_slide[side] * margin /
                                 T3_HANDICAP_TRAVEL;
            else if (side == 0 && p->x + p->width <= 0)
                out.sidecar_dx = -margin;
            else if (side == 1 && p->x >= f->display_width)
                out.sidecar_dx = margin;
        }
        return out;
    }
    /* Team-size prompt, chosen faces, borders, name and underline belong to
     * their player panel. VS remains centered between those panels. */
    if (p->y >= 270 && (p->x + p->width <= 160 ||
        /* The prompt row ("PLEASE WAIT!"): its "!" ends past x = 160. */
        (p->y < 300 && p->x < 176 && p->x + p->width <= 184))) {
        out.role = TEKKEN3_SELECTOR_LEFT_PLAYER;
        out.group_id = 1;
        out.sidecar_dx = -margin;
    } else if (p->y >= 270 && p->x >= 208) {
        out.role = TEKKEN3_SELECTOR_RIGHT_PLAYER;
        out.group_id = 2;
        out.sidecar_dx = margin;
    }
    return out;
}

Tekken3SelectorPlacement tekken3_selector_place(
    const Tekken3SelectorFrame *frame,
    const Tekken3SelectorPacket *packet,
    int32_t margin) {
    Tekken3SelectorPlacement r = {0};
    int32_t rel;
    int side = 0;

    if (!frame || !frame->active || !packet || !same_arena(frame, packet->source_addr))
        return r;
    if (frame->layout_kind && margin > 0)
        return other_menu_place(frame, packet, margin);
    if (frame->layout_kind) return r;

    rel = (int32_t)phys(packet->source_addr) -
          (int32_t)frame->backdrop_source;

    /* The extra fighter uses eleven 33px cells instead of ten 35px cells.
     * Classify their faces, Gon strips, cursor halves and player label before
     * source-relative cabinet art. The guest clips the roster during ordinary
     * presents, so all of these must also reach the unclipped wide surface. */
    if (frame->roster_columns == 11) {
        int slot = -1;
        if (packet->opcode == 0x65 && packet->width == 32 &&
            packet->height > 0 && packet->y >= 336 && packet->y + packet->height <= 456 &&
            packet->x >= 3 && (packet->x - 3) % 33 == 0)
            slot = (packet->x - 3) / 33;
        if (packet->opcode == 0x64 &&
            ((packet->width == 18 && (packet->y == 334 || packet->y == 396)) ||
             (packet->width == 20 && (packet->y == 328 || packet->y == 390)))) {
            if (packet->x >= 1 && (packet->x - 1) % 33 == 0) slot = (packet->x - 1) / 33;
            else if (packet->width == 18 && packet->x >= 19 && (packet->x - 19) % 33 == 0)
                slot = (packet->x - 19) / 33;
            else if (packet->width == 20 && packet->x >= 21 && (packet->x - 21) % 33 == 0)
                slot = (packet->x - 21) / 33;
        }
        if (slot >= 0 && slot < 11) {
            r.role = TEKKEN3_SELECTOR_ROSTER;
            r.group_id = 20u + (unsigned)slot;
            r.sidecar_dx = roster_delta(slot, 11, margin);
            r.unclipped_sidecar = margin > 0;
            return r;
        }
    }

    if (full_base(packet, frame->display_width)) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.expand_backdrop = margin > 0;
        return r;
    }

    /* Stretch the authored cabinet grid as one continuous background. Each
     * tile uses the same affine X mapping, so its seams stay joined while the
     * portraits and text keep their original proportions. */
    if (packet->opcode == 0x65u && rel >= -0x550 && rel < -0xC0 &&
        ((packet->x == 0 && packet->width == 40) ||
         (packet->x >= 40 && packet->x <= 328 &&
          (packet->x - 40) % 48 == 0 && packet->width == 48)) &&
        packet->height > 0 && packet->height <= 64) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.expand_backdrop = margin > 0;
        return r;
    }

    /* Outer cabinet caps and posts stay at the physical screen edges. */
    if (packet->opcode == 0x65u &&
        ((packet->width == 12 && packet->height == 86 && packet->y == 0) ||
         (packet->width == 6 && packet->height == 78 &&
          packet->y == frame->backdrop_height - 96)) &&
        (packet->x == 0 || packet->x + packet->width == frame->display_width)) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.sidecar_dx = margin > 0 ? (packet->x == 0 ? -margin : margin) : 0;
        return r;
    }

    /* Nameplate art and the variable-width character-name sprite belong to
     * the portrait above them. They must move together, before the broader
     * lower-cabinet expansion rule can classify these overlapping rows. */
    if (packet->opcode == 0x65u &&
        ((packet->y == frame->backdrop_height - 20 &&
          packet->height == 31 &&
          (packet->width == 128 || packet->width == 16)) ||
         (packet->y == frame->backdrop_height - 18 &&
          packet->height == 16 && packet->width <= 126))) {
        side = packet->x + packet->width / 2 < frame->display_width / 2 ? -1 : 1;
        r.role = side < 0 ? TEKKEN3_SELECTOR_LEFT_PLAYER : TEKKEN3_SELECTOR_RIGHT_PLAYER;
        r.group_id = side < 0 ? 1 : 2;
        r.sidecar_dx = margin > 0 ? side * margin : 0;
        r.unclipped_sidecar = margin > 0;
        return r;
    }

    /* CREDIT / INSERT COIN is centered above the right player's panel. */
    if (packet->opcode == 0x65u && packet->height == 16 &&
        packet->y == 34 &&
        packet->x >= frame->display_width / 2 &&
        packet->x + packet->width <= frame->display_width) {
        r.role = TEKKEN3_SELECTOR_RIGHT_PLAYER;
        r.group_id = 2;
        r.sidecar_dx = margin > 0 ? margin : 0;
        return r;
    }

    /* The fully unlocked selector exposes an extra character via arrows at
     * the two outer screen edges. Preserve those authored edge gutters. */
    if (packet->opcode == 0x64u && packet->width == 10 &&
        packet->height == 16 && packet->y == 146 &&
        (packet->x == 7 || packet->x == frame->display_width - 17)) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.sidecar_dx = margin > 0 ? (packet->x == 7 ? -margin : margin) : 0;
        return r;
    }

    /* The selector's looping centre video is not the 40-tile cabinet
     * background. It is this exact six-SPRT overlay immediately preceding the
     * base packet in both alternating arenas. Suppress only its native-wide
     * copy: the guest can keep advancing it without repainting the selector. */
    if (packet->opcode == 0x65u && rel >= -0xEC && rel <= -0x20 &&
        packet->y >= 48 && packet->y + packet->height <= 160 &&
        packet->height <= 40) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.suppress_sidecar = margin > 0;
        return r;
    }
    if (packet->opcode == 0x38u && packet->x <= 0 &&
        packet->x + packet->width >= frame->display_width &&
        packet->y >= frame->backdrop_height) {
        /* The unlocked two-row roster recolours its lower cabinet with this
         * full-width Gouraud quad. It is selector chrome, not the looping
         * centre animation caught by the broad full-screen suppression below;
         * redraw it over the complete sidecar so no earlier 3D polygon can
         * remain visible in either reveal margin. */
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.group_id = 16;
        r.expand_backdrop = margin > 0;
        r.unclipped_sidecar = margin > 0;
        return r;
    }
    if (packet->x <= 0 &&
        packet->x + packet->width >= frame->display_width &&
        packet->height >= 64) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.suppress_sidecar = margin > 0;
        return r;
    }

    /* Selector cabinet-edge artwork: preserve the original inner pair and
     * add one copy at each true 16:9 edge. These tall, narrow strips are an
     * exact geometry fingerprint and cannot collide with roster portraits. */
    if (packet->height >= 120 && packet->width > 0 && packet->width <= 32) {
        if (packet->x < frame->display_width / 4) {
            r.role = TEKKEN3_SELECTOR_LEFT_FRAME;
            r.group_id = 14;
            r.sidecar_dx = margin > 0 ? -margin : 0;
            r.duplicate_outer = margin > 0;
            return r;
        }
        if (packet->x + packet->width > frame->display_width * 3 / 4) {
            r.role = TEKKEN3_SELECTOR_RIGHT_FRAME;
            r.group_id = 15;
            r.sidecar_dx = margin > 0 ? margin : 0;
            r.duplicate_outer = margin > 0;
            return r;
        }
    }

    /* The lower selector cabinet is a symmetric set of SPRTs separate from
     * the ten portraits and their cursor. Expand that decorative coordinate
     * space across 16:9, then place the portraits below at their unchanged
     * 32-pixel width. This keeps the complete bottom UI under every slot. */
    if (rel > -0x830 && rel < -0x550 &&
        packet->y >= frame->backdrop_height - 18) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.group_id = 16;
        r.expand_backdrop = margin > 0;
        r.unclipped_sidecar = margin > 0;
        /* Except the striped band right under the nameplates (four SPRTs,
         * 34 high, at the nameplates' row + 2): a notch in it takes each
         * plate's white point. Stretched in one piece its notches slid
         * towards the centre while the plates moved out with their
         * portraits. It follows the plates instead, and only its middle,
         * between the two plates (x 167..199 of 368), stretches. */
        if (margin > 0 && packet->opcode == 0x65u && packet->height == 34 &&
            packet->y == frame->backdrop_height - 18) {
            r.expand_backdrop = 0;
            r.split_lo = frame->display_width / 2 - 17;
            r.split_hi = frame->display_width / 2 + 15;
        }
        return r;
    }

    /* Roster portrait packets are stable 0x20-byte records in both alternating
     * arenas. Cursor/label packets immediately precede them and move in 35px
     * authored steps; deriving their slot from X keeps the red frame and the
     * 1P/CPU lettering attached while the player navigates. */
    if (packet->opcode == 0x65 && packet->width == 32 &&
        ((packet->height == 68 && packet->y == 369) ||
         (packet->height > 0 && packet->y >= 336 &&
          packet->y + packet->height <= 456)) && packet->x >= 11 &&
        (packet->x - 11) % 35 == 0 && (packet->x - 11) / 35 <= 9) {
        /* Geometry is the runtime authority. Source records are stable in the
         * captured A/B lists too, but some DMA walkers report the containing
         * tag address rather than the command address for this consecutive
         * SPRT run; the exact 10-slot fingerprint is invariant either way. */
        int slot = (packet->x - 11) / 35;
        r.role = TEKKEN3_SELECTOR_ROSTER;
        r.group_id = (uint32_t)(4 + slot);
        r.sidecar_dx = roster_delta(slot, 10, margin);
        r.unclipped_sidecar = margin > 0;
        return r;
    } else {
        int slot = roster_slot_from_cursor(packet);
        if (slot >= 0) {
            r.role = TEKKEN3_SELECTOR_ROSTER;
            r.group_id = (uint32_t)(4 + slot);
            r.sidecar_dx = roster_delta(slot, 10, margin);
            r.unclipped_sidecar = margin > 0;
            return r;
        }
    }

    /* Exact source families relative to the 368x340 base packet. These offsets
     * are stable across selector arena A/B despite dynamic allocation before
     * the list. Portrait chains come first, timer/roster next, then complete
     * left and right name/label composites. Geometry chooses the side inside
     * the portrait family so its split quads remain one rigid group. */
    if (rel >= -0xD60 && rel <= -0xAE0 && packet->width >= 96)
        side = packet->x + packet->width / 2 < frame->display_width / 2 ? -1 : +1;
    /* The mode banner (SURVIVAL !, TIME ATTACK !) is a run of 14x24 glyphs
     * centred under the portrait of the side nobody plays. */
    if (packet->opcode == 0x65u && packet->width == 14 && packet->height == 24 &&
        packet->y >= 200 && packet->y + packet->height <= frame->backdrop_height - 20)
        side = packet->x + packet->width / 2 < frame->display_width / 2 ? -1 : +1;
    /* Name/glyph composites use variable-width records in these source
     * families. Keep them centred unless their geometry proves membership in
     * a large player panel; translating the whole address range detached the
     * names from the portraits and disturbed the bottom roster chrome. */

    /* The large shaded player-panel bands live between the lower composites
     * and central grid. Bounds are exact and symmetric; small grid cells and
     * glyphs cannot match this rule. */
    if (!side) side = side_from_bounds(frame, packet);

    if (side < 0) {
        r.role = TEKKEN3_SELECTOR_LEFT_PLAYER;
        r.group_id = 1;
        r.sidecar_dx = margin > 0 ? -margin : 0;
        return r;
    }
    if (side > 0) {
        r.role = TEKKEN3_SELECTOR_RIGHT_PLAYER;
        r.group_id = 2;
        r.sidecar_dx = margin > 0 ? margin : 0;
        return r;
    }

    /* Timer (-0xAA0..), main grid (-0x550..) and central headings are
     * intentionally one centred composition. */
    if ((rel >= -0xAA0 && rel < -0x830) || rel >= -0x550) {
        r.role = TEKKEN3_SELECTOR_CENTRE;
        r.group_id = 3;
    }
    return r;
}

static int loading_arena(uint32_t source) {
    source = phys(source);
    return (source >= 0x000BD300u && source < 0x000BEC00u) ||
           (source >= 0x000B9700u && source < 0x000BB000u);
}

static int loading_analyze_kind(const Tekken3SelectorPacket *packets,
    size_t count, int32_t display_width, int32_t display_height,
    Tekken3LoadingFrame *out, int kind) {
    static const int tops[3][2] = {{106, 216}, {102, 220}, {218, 0}};
    static const int offsets[4] = {0, 44, 108, 172};
    const int sides = kind == 2 ? 1 : 2;
    static const int hs[4] = {44, 64, 64, 40};
    uint32_t anchors[2] = {0, 0};
    int xs[2] = {0, 0}, clear = 0, tiles = 0;
    unsigned coverage[2] = {0, 0};
    if (!out) return 0;
    memset(out, 0, sizeof(*out));
    if (!packets || display_width != 368 || display_height < 224) return 0;
    for (size_t i = 0; i < count; i++) {
        const Tekken3SelectorPacket *p = &packets[i];
        if (!loading_arena(p->source_addr)) continue;
        if (p->opcode == 0x60 && p->x == 0 && p->y == 0 &&
            p->width == 368 && p->height == 480) clear = 1;
        if (p->opcode != 0x2D) continue;
        if ((p->width == 68 || p->width == 69) && p->height == 64 &&
            p->y >= 20 && p->y <= 404 && (p->y - 20) % 64 == 0)
            tiles++;
        for (int side = 0; side < sides; side++) {
            if (p->width == 126 && p->height == 44 && p->y == tops[kind][side]) {
                anchors[side] = phys(p->source_addr);
                xs[side] = p->x;
            }
        }
    }
    if (!anchors[0] || (!clear && tiles < 42)) return 0;
    if (sides == 2 && (anchors[1] < anchors[0] + 0x128u ||
        anchors[1] > anchors[0] + (kind == 1 ? 0x900u : 0x400u))) return 0;
    for (size_t i = 0; i < count; i++) {
        const Tekken3SelectorPacket *p = &packets[i];
        for (int side = 0; side < sides; side++)
            for (int band = 0; band < 4; band++)
                if (phys(p->source_addr) == anchors[side] + 0x28u * band &&
                    p->opcode == 0x2D && p->x == xs[side] && p->width == 126 &&
                    p->y == tops[kind][side] + offsets[band] && p->height == hs[band])
                    coverage[side] |= 1u << band;
    }
    if (coverage[0] != 15 || (sides == 2 && coverage[1] != 15)) return 0;
    /* Tekken alternates two loading packet buffers, 0x3C00 bytes apart. */
    out->arena_lo = anchors[0] >= 0x000BD300u ? 0x000BD300u : 0x000B9700u;
    out->arena_hi = out->arena_lo + (kind == 1 ? 0x1900u : 0xD00u);
    out->left_source = anchors[0];
    out->right_source = anchors[1];
    out->layout_kind = kind;
    out->active = 1;
    return 1;
}

int tekken3_loading_analyze_frame(const Tekken3SelectorPacket *packets,
    size_t count, int32_t display_width, int32_t display_height,
    Tekken3LoadingFrame *out) {
    if (!out) return 0;
    for (int kind = 0; kind < 3; kind++)
        if (loading_analyze_kind(packets, count, display_width, display_height, out, kind))
            return 1;
    return 0;
}

Tekken3SelectorPlacement tekken3_loading_place(
    const Tekken3LoadingFrame *frame, const Tekken3SelectorPacket *p,
    int32_t margin) {
    Tekken3SelectorPlacement r = {0};
    if (!frame || !frame->active || !p ||
        phys(p->source_addr) < frame->arena_lo ||
        phys(p->source_addr) >= frame->arena_hi) return r;
    uint32_t source = phys(p->source_addr);
    /* Each mode uses the same original lightning art, but different portrait
     * baselines and name/bench bands. Keep complete composites together. */
    if (frame->layout_kind && !((p->opcode == 0x60 && p->x == 0 &&
        p->y == 0 && p->width == 368 && p->height == 480) ||
        (p->opcode == 0x2D && (p->width == 68 || p->width == 69) &&
        p->height == 64 && p->y >= 20 && p->y <= 404 && (p->y-20)%64 == 0))) {
        int side = 0;
        if (frame->layout_kind == 2) {
            if ((source >= frame->left_source && source < frame->left_source+0x128u) ||
                (p->opcode == 0x65 && p->y == 390 && p->height == 40) ||
                (p->y == 42 && p->height == 24) ||
                (p->y == 84 && p->height == 24)) side = -1;
            else if (p->y == 120 && p->height == 40) side = 1;
        } else {
            if ((source >= frame->left_source && source < frame->left_source+0x128u) ||
                (p->opcode == 0x65 && (p->y == 166 ||
                    (p->y >= 96 && p->y < 166 && p->width == 32))) ||
                (p->opcode == 0x60 && p->y == 100 && p->height == 62)) side = -1;
            else if ((source >= frame->right_source && source < frame->right_source+0x128u) ||
                (p->opcode == 0x65 && (p->y == 328 ||
                    (p->y >= 368 && p->y < 434 && p->width == 32))) ||
                (p->opcode == 0x60 && p->y == 372 && p->height == 62)) side = 1;
            else if (p->y == 42 && p->height == 24) side = -1;
        }
        if ((p->y == 36 && p->height == 36) ||
            (frame->layout_kind == 1 && p->opcode == 0x3A &&
             p->height == 88 && (p->y == 96 || p->y == 350))) {
            r.role = TEKKEN3_SELECTOR_BACKDROP;
            r.expand_backdrop = margin > 0;
        } else {
            r.role = side < 0 ? TEKKEN3_SELECTOR_LEFT_PLAYER :
                side > 0 ? TEKKEN3_SELECTOR_RIGHT_PLAYER : TEKKEN3_SELECTOR_CENTRE;
            r.group_id = side < 0 ? 1 : side > 0 ? 2 : 3;
            r.sidecar_dx = margin > 0 ? side * margin : 0;
        }
        return r;
    }
    if ((p->opcode == 0x60 && p->x == 0 && p->y == 0 &&
         p->width == 368 && p->height == 480) ||
        (p->opcode == 0x2D && (p->width == 68 || p->width == 69) &&
         p->height == 64 && p->y >= 20 && p->y <= 404 &&
         (p->y - 20) % 64 == 0)) {
        r.role = TEKKEN3_SELECTOR_BACKDROP;
        r.expand_backdrop = margin > 0;
    } else if ((source >= frame->left_source && source < frame->left_source + 0x128u) ||
               (p->opcode == 0x65 && p->y == 106 && p->width == 24 && p->height == 40)) {
        r.role = TEKKEN3_SELECTOR_LEFT_PLAYER;
        r.group_id = 1;
        r.sidecar_dx = margin > 0 ? -margin : 0;
    } else if ((source >= frame->right_source && source < frame->right_source + 0x128u) ||
               (p->opcode == 0x65 && p->y == 390 && p->width == 24 && p->height == 40)) {
        r.role = TEKKEN3_SELECTOR_RIGHT_PLAYER;
        r.group_id = 2;
        r.sidecar_dx = margin > 0 ? margin : 0;
    } else if ((p->opcode == 0x65 && p->y == 42 && p->height == 24) ||
               (p->y == 36 && p->height == 36)) {
        r.role = TEKKEN3_SELECTOR_LEFT_PLAYER;
        r.sidecar_dx = margin > 0 ? -margin : 0;
    } else {
        r.role = TEKKEN3_SELECTOR_CENTRE;
        r.group_id = 3;
    }
    return r;
}
