#include "tekken3_selector_layout.h"

#include <assert.h>
#include <stdio.h>

static Tekken3SelectorPacket p(uint32_t src, uint8_t op,
                               int x, int y, int w, int h) {
    Tekken3SelectorPacket out = {src, op, x, y, w, h};
    return out;
}

static void verify_arena(uint32_t base, int source_bias,
                         uint32_t left, uint32_t right) {
    Tekken3SelectorPacket frame_packets[] = {
        p(base, 0x60, 0, 0, 368, 340),
        /* Real arena A/B portrait/panel strips: symmetric vertical coverage,
         * with the left lower band split at y=254. */
        p(base - 0xCFC + source_bias, 0x3E, 33, 48, 126, 30),
        p(base - 0xC94 + source_bias, 0x2D, 33, 78, 126, 34),
        p(base - 0xC6C + source_bias, 0x2D, 33, 112, 126, 64),
        p(base - 0xC44 + source_bias, 0x2D, 33, 176, 126, 64),
        p(base - 0xC1C + source_bias, 0x2D, 33, 240, 126, 14),
        p(base - 0xBC0 + source_bias, 0x3E, 33, 254, 126, 46),
        p(base - 0xB8C + source_bias, 0x3E, 209, 48, 126, 30),
        p(base - 0xB54 + source_bias, 0x2E, 209, 78, 126, 34),
        p(base - 0xB2C + source_bias, 0x2E, 209, 112, 126, 64),
        p(base - 0xB04 + source_bias, 0x2E, 209, 176, 126, 64),
        p(base - 0xAE0, 0x3E, 209, 240, 126, 60),
    };
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(frame_packets,
        sizeof(frame_packets) / sizeof(frame_packets[0]), 368, 240, &frame));

    /* Confirm-to-loading capture: a copy/environment-only list is followed
     * by twelve presents with no GPU packets. The completed menu must remain
     * authoritative throughout, including slower CD waits of any duration. */
    Tekken3SelectorPacket waiting[] = {
        p(0xFFFFFFFFu, 0x80, 0, 0, 368, 480),
        p(0xFFFFFFFFu, 0xE3, 0, 0, 0, 0),
        p(0xFFFFFFFFu, 0xA0, 0, 0, 64, 64)
    };
    assert(tekken3_selector_can_retain_frame(&frame, waiting, 3, 368, 240));
    assert(tekken3_selector_can_retain_frame(&frame, NULL, 0, 368, 240));
    Tekken3SelectorPacket cursor_update = p(base - 0x9A0, 0x64, 9, 363, 18, 76);
    assert(tekken3_selector_can_retain_frame(&frame, &cursor_update, 1, 368, 240));
    Tekken3SelectorPacket next_scene[] = {
        cursor_update, p(0xBD6C4, 0x60, 0, 0, 368, 480)
    };
    assert(!tekken3_selector_can_retain_frame(&frame, next_scene, 2, 368, 240));
    next_scene[1] = p(0x90000, 0x2D, 0, 0, 368, 240);
    assert(!tekken3_selector_can_retain_frame(&frame, next_scene, 2, 368, 240));
    assert(!tekken3_selector_can_retain_frame(&frame, NULL, 0, 320, 240));
    assert(!tekken3_selector_can_retain_frame(&frame, NULL, 0, 368, 480));
    Tekken3SelectorFrame inactive = {0};
    assert(!tekken3_selector_can_retain_frame(&inactive, NULL, 0, 368, 240));

    Tekken3SelectorPacket l0 = p(left, 0x3E, 33, 48, 126, 204);
    Tekken3SelectorPacket l1 = p(left + 0x34, 0x3E, 33, 48, 126, 204);
    Tekken3SelectorPacket r0 = p(right, 0x3E, 209, 48, 126, 204);
    Tekken3SelectorPlacement a = tekken3_selector_place(&frame, &l0, 61);
    Tekken3SelectorPlacement b = tekken3_selector_place(&frame, &l1, 61);
    Tekken3SelectorPlacement c = tekken3_selector_place(&frame, &r0, 61);
    assert(a.role == TEKKEN3_SELECTOR_LEFT_PLAYER && a.sidecar_dx == -61);
    assert(b.group_id == a.group_id && b.sidecar_dx == a.sidecar_dx);
    assert(c.role == TEKKEN3_SELECTOR_RIGHT_PLAYER && c.sidecar_dx == 61);

    /* Arena B places a narrow centre divider directly after the portrait
     * chain. Source proximity alone must never drag it into the right group. */
    Tekken3SelectorPacket divider = p(base - 0xAE8, 0x65, 184, 248, 16, 46);
    assert(tekken3_selector_place(&frame, &divider, 61).sidecar_dx == 0);

    /* SURVIVAL ! is a run of 14x24 glyphs under the free side's portrait,
     * from the portrait family's source range: it follows that panel. */
    Tekken3SelectorPacket banner_first = p(base - 0xBE8, 0x65, 213, 258, 14, 24);
    Tekken3SelectorPacket banner_last = p(base - 0xBA8, 0x65, 317, 258, 14, 24);
    assert(tekken3_selector_place(&frame, &banner_first, 61).sidecar_dx == 61);
    assert(tekken3_selector_place(&frame, &banner_last, 61).sidecar_dx == 61);

    Tekken3SelectorPacket credit = p(base - 0xA94, 0x65, 240, 34, 10, 16);
    Tekken3SelectorPacket roster0 = p(base - 0x960, 0x65, 11, 369, 32, 68);
    Tekken3SelectorPacket roster4 = p(base - 0x8E0, 0x65, 151, 369, 32, 68);
    Tekken3SelectorPacket roster5 = p(base - 0x8C0, 0x65, 186, 369, 32, 68);
    Tekken3SelectorPacket roster9 = p(base - 0x840, 0x65, 326, 369, 32, 68);
    assert(tekken3_selector_place(&frame, &credit, 61).sidecar_dx == 61);
    assert(tekken3_selector_place(&frame, &roster0, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &roster4, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &roster5, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &roster9, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &roster9, 61).group_id == 13);
    assert(tekken3_selector_place(&frame, &roster9, 61).unclipped_sidecar == 1);

    /* The cursor's left/right strips and 1P/CPU label use different authored
     * origins but must resolve to one selected roster slot. */
    Tekken3SelectorPacket cursor_l = p(base - 0x9A0, 0x64,
                                       9 + 4 * 35, 363, 18, 76);
    Tekken3SelectorPacket cursor_r = p(base - 0x980, 0x64,
                                       27 + 4 * 35, 363, 18, 76);
    Tekken3SelectorPacket label = p(base - 0x9C0, 0x64,
                                    9 + 4 * 35, 363, 20, 16);
    assert(tekken3_selector_place(&frame, &cursor_l, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &cursor_r, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &label, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &label, 61).group_id == 8);
    assert(tekken3_selector_place(&frame, &label, 61).unclipped_sidecar == 1);
    label.x += 20; /* P2's label has its own native horizontal offset. */
    assert(tekken3_selector_place(&frame, &label, 61).group_id == 8);
    assert(tekken3_selector_place(&frame, &label, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &label, 61).unclipped_sidecar == 1);

    Tekken3SelectorPacket backdrop = p(base, 0x60, 0, 0, 368, 340);
    Tekken3SelectorPacket animated = p(base - 0x100, 0x65, 0, 20, 368, 120);
    Tekken3SelectorPacket loop_panel = p(base - 0x88, 0x65, 204, 58, 34, 32);
    Tekken3SelectorPacket bottom_chrome = p(base - 0x6F0, 0x65, 24, 356, 104, 8);
    Tekken3SelectorPacket left_frame = p(base - 0x80, 0x65, 8, 40, 24, 220);
    Tekken3SelectorPacket right_frame = p(base - 0x60, 0x65, 336, 40, 24, 220);
    assert(tekken3_selector_place(&frame, &backdrop, 61).expand_backdrop == 1);
    assert(tekken3_selector_place(&frame, &backdrop, 0).expand_backdrop == 0);
    assert(tekken3_selector_place(&frame, &animated, 61).suppress_sidecar == 1);
    assert(tekken3_selector_place(&frame, &animated, 0).suppress_sidecar == 0);
    assert(tekken3_selector_place(&frame, &loop_panel, 61).suppress_sidecar == 1);
    assert(tekken3_selector_place(&frame, &loop_panel, 0).suppress_sidecar == 0);
    assert(tekken3_selector_place(&frame, &bottom_chrome, 61).expand_backdrop == 1);
    assert(tekken3_selector_place(&frame, &bottom_chrome, 61).unclipped_sidecar == 1);
    assert(tekken3_selector_place(&frame, &bottom_chrome, 0).expand_backdrop == 0);
    assert(tekken3_selector_place(&frame, &left_frame, 61).sidecar_dx == -61);
    assert(tekken3_selector_place(&frame, &left_frame, 61).duplicate_outer == 1);
    assert(tekken3_selector_place(&frame, &right_frame, 61).sidecar_dx == 61);
    assert(tekken3_selector_place(&frame, &right_frame, 61).duplicate_outer == 1);
    assert(tekken3_selector_place(&frame, &l0, 0).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &roster9, 0).sidecar_dx == 0);

    Tekken3SelectorPacket grid = p(base - 0x474, 0x65, 40, 284, 48, 64);
    Tekken3SelectorPacket name = p(base - 0xA78, 0x65, 74, 322, 46, 16);
    Tekken3SelectorPacket nameplate = p(base - 0x7AC, 0x65, 23, 320, 128, 31);
    assert(tekken3_selector_place(&frame, &grid, 61).expand_backdrop);
    assert(tekken3_selector_place(&frame, &grid, 0).expand_backdrop == 0);
    assert(tekken3_selector_place(&frame, &name, 61).sidecar_dx == -61);
    assert(tekken3_selector_place(&frame, &nameplate, 61).sidecar_dx == -61);
    name.x = 250;
    nameplate.x = 199;
    assert(tekken3_selector_place(&frame, &name, 61).sidecar_dx == 61);
    assert(tekken3_selector_place(&frame, &nameplate, 61).sidecar_dx == 61);
}

static void verify_loading(void) {
    Tekken3SelectorPacket packets[] = {
        p(0xBD73C, 0x60, 0, 0, 368, 480),
        p(0xBD364, 0x2D, -126, 106, 126, 44),
        p(0xBD38C, 0x2D, -126, 150, 126, 64),
        p(0xBD3B4, 0x2D, -126, 214, 126, 64),
        p(0xBD3DC, 0x2D, -126, 278, 126, 40),
        p(0xBD528, 0x2D, 368, 216, 126, 44),
        p(0xBD550, 0x2D, 368, 260, 126, 64),
        p(0xBD578, 0x2D, 368, 324, 126, 64),
        p(0xBD5A0, 0x2D, 368, 388, 126, 40),
    };
    Tekken3LoadingFrame frame;
    assert(tekken3_loading_analyze_frame(packets, 9, 368, 480, &frame));
    assert(tekken3_loading_place(&frame, &packets[1], 61).sidecar_dx == -61);
    assert(tekken3_loading_place(&frame, &packets[5], 61).sidecar_dx == 61);
    assert(tekken3_loading_place(&frame, &packets[0], 61).expand_backdrop);
    Tekken3SelectorPacket left_name = p(0xBD4A4, 0x65, 149, 106, 24, 40);
    Tekken3SelectorPacket right_name = p(0xBD668, 0x65, 12, 390, 24, 40);
    Tekken3SelectorPacket vs = p(0xBD748, 0x65, 162, 250, 24, 40);
    Tekken3SelectorPacket tile = p(0xBD87C, 0x2D, 0, 20, 69, 64);
    assert(tekken3_loading_place(&frame, &left_name, 61).sidecar_dx == -61);
    assert(tekken3_loading_place(&frame, &right_name, 61).sidecar_dx == 61);
    assert(tekken3_loading_place(&frame, &vs, 61).sidecar_dx == 0);
    assert(tekken3_loading_place(&frame, &tile, 61).expand_backdrop);
    assert(!tekken3_loading_place(&frame, &tile, 0).expand_backdrop);
    assert(tekken3_loading_place(&frame, &left_name, 0).sidecar_dx == 0);
    /* Variable name lengths move the second portrait's packet allocation.
     * In particular, a short CPU name places VS inside the old fixed-size
     * name range. It must remain centered for every pairing. */
    for (int i = 5; i < 9; i++) packets[i].source_addr += 0x50;
    assert(tekken3_loading_analyze_frame(packets, 9, 368, 480, &frame));
    vs.source_addr = frame.right_source + 0x1A0;
    assert(tekken3_loading_place(&frame, &vs, 61).sidecar_dx == 0);
    right_name.source_addr = frame.right_source + 0x140;
    assert(tekken3_loading_place(&frame, &right_name, 61).sidecar_dx == 61);
    for (int i = 0; i < 9; i++) packets[i].source_addr -= 0x3C00;
    assert(tekken3_loading_analyze_frame(packets, 9, 368, 480, &frame));
    assert(frame.arena_lo == 0xB9700 && frame.arena_hi == 0xBA400);
    assert(tekken3_loading_place(&frame, &packets[1], 61).sidecar_dx == -61);
    assert(tekken3_loading_place(&frame, &packets[5], 61).sidecar_dx == 61);
    /* The other buffer cannot inherit this buffer's placement authority. */
    assert(tekken3_loading_place(&frame, &right_name, 61).role == TEKKEN3_SELECTOR_NONE);
    /* One incomplete portrait, a foreign arena, or another video mode must
     * never mark an unrelated screen as a complete widescreen UI. */
    assert(!tekken3_loading_analyze_frame(packets, 8, 368, 480, &frame));
    assert(!tekken3_loading_analyze_frame(packets, 9, 320, 240, &frame));
    packets[1].source_addr = 0x125364;
    assert(!tekken3_loading_analyze_frame(packets, 9, 368, 480, &frame));
}

static void verify_unlocked_selector(uint32_t base) {
    Tekken3SelectorPacket packets[] = {
        p(base, 0x60, 0, 0, 368, 306),
        p(base - 0xD54, 0x3E, 33, 14, 126, 64),
        p(base - 0xD2C, 0x2D, 33, 78, 126, 64),
        p(base - 0xD04, 0x2D, 33, 142, 126, 64),
        p(base - 0xCA8, 0x3E, 33, 206, 126, 60),
        p(base - 0xC74, 0x3E, 209, 14, 126, 30),
        p(base - 0xC40, 0x2E, 209, 44, 126, 34),
        p(base - 0xC18, 0x2E, 209, 78, 126, 64),
        p(base - 0xBF0, 0x2E, 209, 142, 126, 64),
        p(base - 0xBC8, 0x3E, 209, 206, 126, 60),
    };
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(
        packets, sizeof(packets) / sizeof(packets[0]), 368, 240, &frame));
    assert(frame.backdrop_height == 306);

    Tekken3SelectorPacket top0 = p(base - 0xA48, 0x65, 11, 336, 32, 58);
    Tekken3SelectorPacket lower2 = p(base - 0x908, 0x65, 81, 398, 32, 58);
    Tekken3SelectorPacket cursor7 = p(base - 0xAA8, 0x64, 254, 390, 20, 16);
    Tekken3SelectorPacket top_cursor = p(base - 0xAE8, 0x64, 9, 334, 18, 62);
    Tekken3SelectorPacket top_label = p(base - 0xB08, 0x64, 9, 328, 20, 16);
    Tekken3SelectorPacket top_shading = p(base - 0x528, 0x3A, 33, -6, 126, 228);
    Tekken3SelectorPacket extra_arrow = p(base - 0xB80, 0x64, 7, 146, 10, 16);
    Tekken3SelectorPacket chrome = p(base - 0x6F0, 0x65, 24, 322, 104, 8);
    Tekken3SelectorPacket tint = p(base - 0x588, 0x38, 0, 322, 368, 158);
    assert(tekken3_selector_place(&frame, &top0, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &top0, 61).unclipped_sidecar == 1);
    assert(tekken3_selector_place(&frame, &lower2, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &cursor7, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &cursor7, 61).unclipped_sidecar == 1);
    assert(tekken3_selector_place(&frame, &top_cursor, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &top_label, 61).sidecar_dx == 0);
    assert(tekken3_selector_place(&frame, &top_shading, 61).sidecar_dx == -61);
    assert(tekken3_selector_place(&frame, &extra_arrow, 61).sidecar_dx == -61);
    assert(tekken3_selector_place(&frame, &chrome, 61).expand_backdrop == 1);
    assert(tekken3_selector_place(&frame, &chrome, 61).unclipped_sidecar == 1);
    assert(tekken3_selector_place(&frame, &tint, 61).expand_backdrop == 1);
    assert(tekken3_selector_place(&frame, &tint, 61).unclipped_sidecar == 1);
    /* This native red gradient sits at y=322..480 while the guest clips to
     * y<=305. Both triangle halves must reach the unclipped sidecar, and no
     * generated background may suppress the original color interpolation. */
    assert(tekken3_selector_place(&frame, &tint, 61).suppress_sidecar == 0);
    assert(tekken3_selector_place(&frame, &tint, 0).unclipped_sidecar == 0);
    assert(tekken3_selector_place(&frame, &tint, 0).expand_backdrop == 0);
    /* The striped band under the nameplates (frame 4206: 128/56/128/56 x 34
     * at y=288) follows the plates and stretches only between them, so each
     * plate's white point stays in its notch. */
    Tekken3SelectorPacket band0 = p(base - 0x7E0, 0x65, 0, 288, 128, 34);
    Tekken3SelectorPacket band2 = p(base - 0x67C, 0x65, 184, 288, 128, 34);
    for (int i = 0; i < 2; i++) {
        Tekken3SelectorPlacement band =
            tekken3_selector_place(&frame, i ? &band2 : &band0, 61);
        assert(band.expand_backdrop == 0);
        assert(band.split_lo == 167 && band.split_hi == 199);
        assert(band.unclipped_sidecar == 1);
        band = tekken3_selector_place(&frame, i ? &band2 : &band0, 0);
        assert(band.split_lo == 0 && band.split_hi == 0);
    }
    /* The rest of the lower cabinet still stretches whole. */
    assert(tekken3_selector_place(&frame, &chrome, 61).split_lo == 0);
    assert(tekken3_selector_place(&frame, &chrome, 61).split_hi == 0);
    tint.source_addr = 0x90000;
    assert(tekken3_selector_place(&frame, &tint, 61).role == TEKKEN3_SELECTOR_NONE);
}

static void verify_expanded_roster(void) {
    const uint32_t base=0x001219a8;
    Tekken3SelectorPacket packets[40];unsigned n=0;
    packets[n++]=p(base,0x60,0,0,368,306);
    for(int side=0;side<2;side++)for(int band=0;band<4;band++)
        packets[n++]=p(base-0xd00+side*0x100+band*0x28,0x2d,33+side*176,14+band*64,126,band==3?60:64);
    for(int cell=0;cell<22;cell++)
        packets[n++]=p(base-0xb08+cell*0x20,0x65,3+(cell%11)*33,336+(cell/11)*62,32,58);
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(packets,n,368,480,&frame));
    assert(frame.roster_columns==11);
    for(int column=0;column<11;column++) {
        Tekken3SelectorPacket face=p(base-0x900,0x65,3+column*33,398,32,58);
        Tekken3SelectorPacket cursor=p(base-0x980,0x64,1+column*33,396,18,62);
        Tekken3SelectorPacket right=p(base-0x960,0x64,19+column*33,396,18,62);
        Tekken3SelectorPacket label=p(base-0x9a0,0x64,1+column*33,390,20,16);
        Tekken3SelectorPlacement a=tekken3_selector_place(&frame,&face,61);
        Tekken3SelectorPlacement b=tekken3_selector_place(&frame,&cursor,61);
        Tekken3SelectorPlacement c=tekken3_selector_place(&frame,&right,61);
        Tekken3SelectorPlacement d=tekken3_selector_place(&frame,&label,61);
        assert(a.role==TEKKEN3_SELECTOR_ROSTER && a.unclipped_sidecar);
        assert(a.sidecar_dx==b.sidecar_dx && a.sidecar_dx==c.sidecar_dx && a.sidecar_dx==d.sidecar_dx);
        assert(a.group_id==b.group_id && a.group_id==c.group_id && a.group_id==d.group_id);
        assert(a.sidecar_dx==-10+column*2);
        assert(tekken3_selector_place(&frame,&face,184).sidecar_dx==a.sidecar_dx);
        assert(tekken3_selector_place(&frame,&face,5).sidecar_dx==-5+column);
        assert(tekken3_selector_place(&frame,&face,0).sidecar_dx==0);
    }
    /* One incidental row or a missing tile cannot switch the whole layout. */
    assert(tekken3_selector_analyze_frame(packets,n-1,368,480,&frame));
    assert(frame.roster_columns==10);
}

/* Tekken Ball's ball choice (arena 0xBBC00, captured in game 2026-09-25):
 * BEACH BALL is 14px glyphs from x = 119 to 250, over the dark panel. */
static void verify_ball_choice(void) {
    Tekken3SelectorPacket packets[40];unsigned n=0;
    packets[n++]=p(0xbea74,0x60,0,0,368,480);
    packets[n++]=p(0xbea50,0x38,0,405,368,75);
    packets[n++]=p(0xbea2c,0x38,0,277,368,128);
    for(int cell=0;cell<21;cell++)
        packets[n++]=p(0xbe000+cell*0x14,0x65,59+(cell%7)*36,70+(cell/7)*63,32,58);
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(packets,n,368,480,&frame));
    assert(frame.layout_kind==2 && !frame.choice_panel);
    Tekken3SelectorPacket bea=p(0xbcbb8,0x65,145,342,14,24);
    Tekken3SelectorPacket all=p(0xbcc08,0x65,210,342,14,24);
    Tekken3SelectorPacket face=p(0xbce30,0x65,70,326,32,58);
    Tekken3SelectorPacket credit=p(0xbd15c,0x65,233,278,10,16);
    /* The grid phase keeps each chosen face with its player. */
    assert(tekken3_selector_place(&frame,&face,61).sidecar_dx==-61);
    packets[n++]=p(0xbe928,0x62,88,315,192,80);
    assert(tekken3_selector_analyze_frame(packets,n,368,480,&frame));
    assert(frame.choice_panel);
    assert(tekken3_selector_place(&frame,&bea,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&all,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&face,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&credit,61).sidecar_dx==61);
}

/* VS handicap (arena 0xB8000, captured in game 2026-09-25): the score sits
 * in the ball choice's centred panel; each LIFE bar waits 149px past its
 * 4:3 edge until its player has chosen, then slides in. */
static void verify_vs_handicap(void) {
    Tekken3SelectorPacket packets[40];unsigned n=0;
    packets[n++]=p(0xbb508,0x60,0,0,368,480);
    packets[n++]=p(0xbb4e4,0x38,0,405,368,75);
    packets[n++]=p(0xbb4c0,0x38,0,277,368,128);
    for(int cell=0;cell<21;cell++)
        packets[n++]=p(0xb9800+cell*0x14,0x65,59+(cell%7)*36,70+(cell/7)*63,32,58);
    packets[n++]=p(0xbb3bc,0x62,88,315,192,80);
    unsigned rest=n;
    /* Neither player has chosen: both bars parked. */
    packets[n++]=p(0xb9020,0x60,-126,418,124,16);
    packets[n++]=p(0xb91d4,0x60,370,418,124,16);
    Tekken3SelectorFrame frame;
    assert(tekken3_selector_analyze_frame(packets,n,368,480,&frame));
    assert(frame.choice_panel);
    assert(frame.handicap_seen[0] && frame.handicap_slide[0]==-149);
    assert(frame.handicap_seen[1] && frame.handicap_slide[1]==149);
    Tekken3SelectorPacket bar=p(0xb9058,0x2c,-120,414,112,24);
    Tekken3SelectorPacket life=p(0xb9240,0x65,-127,376,10,16);
    Tekken3SelectorPacket rbar=p(0xb920c,0x2c,376,414,112,24);
    Tekken3SelectorPacket score=p(0xbb300,0x65,171,385,14,24);
    /* Parked past the wide edge too: -120 - 61 + 112 < -61. */
    assert(tekken3_selector_place(&frame,&bar,61).sidecar_dx==-61);
    assert(tekken3_selector_place(&frame,&life,61).sidecar_dx==-61);
    assert(tekken3_selector_place(&frame,&rbar,61).sidecar_dx==61);
    assert(tekken3_selector_place(&frame,&score,61).sidecar_dx==0);
    Tekken3SelectorPacket frame_line=p(0xb9530,0x40,69,384,34,1);
    assert(tekken3_selector_place(&frame,&frame_line,61).sidecar_dx==0);
    /* Both names (JIN, KING: 14x24 glyphs) and their underlines stay over
     * the centred faces (captured in game 2026-09-27). */
    Tekken3SelectorPacket name_left=p(0xb99d4,0x65,67,274,14,24);
    Tekken3SelectorPacket name_right=p(0xb9a50,0x65,256,274,14,24);
    Tekken3SelectorPacket underline_right=p(0xb9aac,0x2d,252,292,62,10);
    assert(tekken3_selector_place(&frame,&name_left,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&name_right,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&underline_right,61).sidecar_dx==0);
    /* Both in place: the bars stay under the centred faces. */
    n=rest;
    packets[n++]=p(0xb9020,0x60,23,418,124,16);
    packets[n++]=p(0xb91d4,0x60,221,418,124,16);
    assert(tekken3_selector_analyze_frame(packets,n,368,480,&frame));
    assert(frame.handicap_seen[0] && frame.handicap_slide[0]==0);
    assert(frame.handicap_seen[1] && frame.handicap_slide[1]==0);
    bar.x=29;rbar.x=227;
    assert(tekken3_selector_place(&frame,&bar,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&rbar,61).sidecar_dx==0);
    assert(tekken3_selector_place(&frame,&bar,0).sidecar_dx==0);
    /* Halfway, halfway across the wider travel. */
    n=rest;
    packets[n++]=p(0xb9020,0x60,23-74,418,124,16);
    assert(tekken3_selector_analyze_frame(packets,n,368,480,&frame));
    bar.x=29-74;
    assert(tekken3_selector_place(&frame,&bar,61).sidecar_dx==-74*61/149);
    /* Without the frame in the list, a bar wholly off the 4:3 screen is
     * still kept off the wide one. */
    assert(!frame.handicap_seen[1]);
    rbar.x=376;
    assert(tekken3_selector_place(&frame,&rbar,61).sidecar_dx==61);
}

int main(void) {
    /* Real frame 4155 arena A and frame 4206 arena B packet addresses. */
    verify_arena(0x00125E94u, 0, 0x00125198u, 0x00125308u);
    /* Arena B's strip chains are shifted 0x3C earlier relative to its base. */
    verify_arena(0x00121900u, -0x3C, 0x00120BC8u, 0x00120D38u);
    verify_unlocked_selector(0x00125F4Cu);
    /* CREDIT text extends both unlocked packet arenas past their old limits. */
    verify_unlocked_selector(0x0012609Cu);
    verify_unlocked_selector(0x00121A9Cu);
    verify_loading();
    verify_expanded_roster();
    verify_ball_choice();
    verify_vs_handicap();

    /* Arena ownership without the complete symmetric fingerprint is inert. */
    Tekken3SelectorPacket lone[] = { p(0x00121900u, 0x60, 0, 0, 368, 340) };
    Tekken3SelectorFrame frame;
    assert(!tekken3_selector_analyze_frame(lone, 1, 368, 240, &frame));
    puts("PASS: Tekken 3 selector A/B, locked/unlocked and versus/loading layouts");
    return 0;
}
