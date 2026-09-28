#include "recomp_runtime_ui.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct TestState {
    int enabled;
    int level;
    int action_count;
    int save_count;
    int visible;
} TestState;

static int get_value(void *context, const RecompRuntimeUiItem *item, int *out) {
    TestState *state = (TestState *)context;
    if (!strcmp(item->key, "enabled")) *out = state->enabled;
    else if (!strcmp(item->key, "level")) *out = state->level;
    else if (!strcmp(item->key, RECOMP_RUNTIME_UI_KEY_VIEW_MODE)) *out = state->level;
    else return 0;
    return 1;
}

static int set_value(void *context, const RecompRuntimeUiItem *item, int value) {
    TestState *state = (TestState *)context;
    if (!strcmp(item->key, "enabled")) state->enabled = value;
    else if (!strcmp(item->key, "level")) state->level = value;
    else if (!strcmp(item->key, RECOMP_RUNTIME_UI_KEY_VIEW_MODE)) state->level = value;
    else return 0;
    return 1;
}

static int run_action(void *context, const RecompRuntimeUiItem *item) {
    TestState *state = (TestState *)context;
    if (strcmp(item->key, "reset")) return 0;
    ++state->action_count;
    return 1;
}

static void save(void *context) { ++((TestState *)context)->save_count; }
static void visible(void *context, int open) {
    ((TestState *)context)->visible = open;
}

int main(void) {
    static const RecompRuntimeUiItem items[] = {
        { "enabled", "Video", "Enabled", "Toggle the feature.",
          RECOMP_RUNTIME_UI_BOOL, 0, 1, 1, NULL, 0, NULL },
        { "level", "Video", "Level", "Adjust the level.",
          RECOMP_RUNTIME_UI_INT, 0, 10, 2, NULL, 0, NULL },
        { "reset", "System", "Reset", "Run the action.",
          RECOMP_RUNTIME_UI_ACTION, 0, 0, 0, NULL, 0, NULL },
    };
    TestState state = { 0 };
    RecompRuntimeUiConfig config = {0};
    config.title = "Runtime UI";
    config.subtitle = "TEST";
    config.items = items;
    config.item_count = sizeof(items) / sizeof(items[0]);
    config.callbacks = (RecompRuntimeUiCallbacks){
        &state, get_value, set_value, run_action, NULL, save, visible
    };
    config.theme = "n64";
    RecompRuntimeUi *ui = recomp_runtime_ui_create(&config);
    assert(ui != NULL);
    assert(!recomp_runtime_ui_is_open(ui));

    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_TOGGLE, 1, 0));
    assert(recomp_runtime_ui_is_open(ui) && state.visible);
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_ACCEPT, 1, 0));
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_ACCEPT, 1, 0));
    assert(state.enabled == 1 && state.save_count == 1);
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_DOWN, 1, 0));
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_RIGHT, 1, 0));
    assert(state.level == 2 && state.save_count == 2);

    uint32_t frame[256 * 224];
    memset(frame, 0x7f, sizeof(frame));
    uint32_t before = frame[0];
    recomp_runtime_ui_render_argb8888(ui, frame, 256, 224, 256 * 4);
    assert(frame[0] != before);
    assert(frame[112 * 256 + 128] != 0x7f7f7f7fU);

    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_BACK, 1, 0));
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_DOWN, 1, 0));
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_ACCEPT, 1, 0));
    assert(recomp_runtime_ui_handle_input(
        ui, RECOMP_RUNTIME_UI_INPUT_ACCEPT, 1, 0));
    /* Actions own any persistence they need; value persistence is not rerun. */
    assert(state.action_count == 1 && state.save_count == 2);
    recomp_runtime_ui_close(ui);
    assert(!state.visible);
    recomp_runtime_ui_destroy(ui);

    /* Sparse universal view modes retain their semantic values (0 -> 2). */
    state.level = RECOMP_RUNTIME_UI_VIEW_NATIVE;
    RecompRuntimeUiStandardConfig standard = {0};
    standard.menu.title = "Standard settings";
    standard.menu.theme = "gba";
    standard.menu.callbacks = config.callbacks;
    standard.features = RECOMP_RUNTIME_UI_STANDARD_VIEW_MODE;
    standard.view_modes = RECOMP_RUNTIME_UI_VIEW_MODE_NATIVE |
                          RECOMP_RUNTIME_UI_VIEW_MODE_ADAPTIVE;
    RecompRuntimeUi *standard_ui = recomp_runtime_ui_create_standard(&standard);
    assert(standard_ui != NULL);
    recomp_runtime_ui_open(standard_ui);
    assert(recomp_runtime_ui_handle_input(
        standard_ui, RECOMP_RUNTIME_UI_INPUT_ACCEPT, 1, 0));
    assert(recomp_runtime_ui_handle_input(
        standard_ui, RECOMP_RUNTIME_UI_INPUT_RIGHT, 1, 0));
    assert(state.level == RECOMP_RUNTIME_UI_VIEW_ADAPTIVE);
    recomp_runtime_ui_destroy(standard_ui);
    puts("runtime UI tests passed");
    return 0;
}
