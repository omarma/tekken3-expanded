#include "ws_ui_group.h"

#include <assert.h>
#include <stdint.h>

static int32_t scale_about(int32_t x, int32_t anchor,
                           int32_t numerator, int32_t denominator) {
    int32_t delta = x - anchor;
    int32_t scaled =
        (delta * numerator +
         (delta >= 0 ? denominator / 2 : -denominator / 2)) / denominator;
    return anchor + scaled;
}

int main(void) {
    const int display_width = 384;

    WsUiGroupItem text[] = {
        {1, 120, 16, 0}, {1, 136, 16, 0}, {1, 152, 16, 0},
        {1, 168, 16, 0}, {1, 184, 16, 0}, {1, 200, 16, 0},
        {1, 216, 16, 0}, {1, 232, 16, 0}, {1, 248, 16, 0},
    };
    ws_ui_group_assign(text, 9, display_width, 0);
    for (int i = 0; i < 9; i++) assert(text[i].anchor == 192);
    assert(scale_about(184, text[3].anchor, 4, 7) ==
           scale_about(184, text[4].anchor, 4, 7));

    WsUiGroupItem monkeys[] = {
        {2, 300, 16, 0}, {2, 320, 16, 0},
        {2, 340, 16, 0}, {2, 360, 16, 0},
    };
    ws_ui_group_assign(monkeys, 4, display_width, 0);
    for (int i = 0; i < 4; i++) assert(monkeys[i].anchor == 384);
    for (int i = 0; i < 3; i++) {
        int32_t a = scale_about(monkeys[i].x, monkeys[i].anchor, 3, 4);
        int32_t b = scale_about(monkeys[i + 1].x,
                                monkeys[i + 1].anchor, 3, 4);
        assert(b - a == 15);
    }

    WsUiGroupItem edge_runs[] = {
        {3, 20, 16, 0}, {3, 36, 16, 0},
        {3, 330, 16, 0}, {3, 346, 16, 0},
    };
    ws_ui_group_assign(edge_runs, 4, display_width, 0);
    assert(edge_runs[0].anchor == 0 && edge_runs[1].anchor == 0);
    assert(edge_runs[2].anchor == 384 && edge_runs[3].anchor == 384);

    WsUiGroupItem dense[] = {{4, 8, 16, 0}, {5, 340, 16, 0}};
    ws_ui_group_assign(dense, 2, display_width, 1);
    assert(dense[0].anchor == 192 && dense[1].anchor == 192);

    assert(ws_ui_anchor_for_bounds(8, 32, display_width) == 0);
    assert(ws_ui_anchor_for_bounds(344, 32, display_width) == 384);
    return 0;
}
