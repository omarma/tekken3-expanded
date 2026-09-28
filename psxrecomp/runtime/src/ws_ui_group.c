#include "ws_ui_group.h"

#include <stdlib.h>

int32_t ws_ui_anchor_for_bounds(int32_t x, int32_t width,
                                int32_t display_width) {
    const int32_t twice_center = 2 * x + width;
    if (3 * twice_center < 2 * display_width) return 0;
    if (3 * twice_center > 4 * display_width) return display_width;
    return display_width / 2;
}

static int32_t interval_gap(const WsUiGroupItem *a,
                            const WsUiGroupItem *b) {
    int32_t a_right = a->x + a->width;
    int32_t b_right = b->x + b->width;
    if (a_right < b->x) return b->x - a_right;
    if (b_right < a->x) return a->x - b_right;
    return 0;
}

static size_t root_of(size_t *parent, size_t index) {
    while (parent[index] != index) {
        parent[index] = parent[parent[index]];
        index = parent[index];
    }
    return index;
}

void ws_ui_group_assign(WsUiGroupItem *items, size_t count,
                        int32_t display_width, int dense_menu) {
    if (!items || count == 0 || display_width <= 0) return;
    if (dense_menu) {
        for (size_t i = 0; i < count; i++)
            items[i].anchor = display_width / 2;
        return;
    }

    size_t *parent = (size_t *)malloc(count * sizeof(*parent));
    if (!parent) {
        for (size_t i = 0; i < count; i++) {
            items[i].anchor = ws_ui_anchor_for_bounds(
                items[i].x, items[i].width, display_width);
        }
        return;
    }
    for (size_t i = 0; i < count; i++) parent[i] = i;

    /* Transitive union is important for text: each adjacent pair is close,
     * even when the complete string spans more than one thirds region. */
    for (size_t i = 0; i < count; i++) {
        for (size_t j = i + 1; j < count; j++) {
            if (items[i].key != items[j].key ||
                interval_gap(&items[i], &items[j]) > WS_UI_GROUP_JOIN_GAP)
                continue;
            size_t ri = root_of(parent, i);
            size_t rj = root_of(parent, j);
            if (ri != rj) parent[rj] = ri;
        }
    }

    for (size_t i = 0; i < count; i++) {
        size_t root = root_of(parent, i);
        int32_t min_x = items[i].x;
        int32_t max_x = items[i].x + items[i].width;
        for (size_t j = 0; j < count; j++) {
            if (root_of(parent, j) != root) continue;
            if (items[j].x < min_x) min_x = items[j].x;
            if (items[j].x + items[j].width > max_x)
                max_x = items[j].x + items[j].width;
        }
        items[i].anchor =
            ws_ui_anchor_for_bounds(min_x, max_x - min_x, display_width);
    }
    free(parent);
}
