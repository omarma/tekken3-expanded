#include "recomp_runtime_ui_internal.h"

#include <stdlib.h>
#include <string.h>

static const char *const kFullscreenChoices[] = {
    "Windowed", "Borderless", "Exclusive"
};
static const char *const kTextureFilterChoices[] = { "Nearest", "Linear" };

static int has(RecompRuntimeUiStandardFeatures features,
               RecompRuntimeUiStandardFeatures feature) {
    return (features & feature) != 0;
}

static void add_item(RecompRuntimeUiItem *items, size_t *count,
                     const char *key, const char *section, const char *label,
                     const char *description, RecompRuntimeUiItemType type,
                     int minimum, int maximum, int step,
                     const char *const *choices, size_t choice_count,
                     const int *choice_values) {
    RecompRuntimeUiItem *item = &items[(*count)++];
    memset(item, 0, sizeof(*item));
    item->key = key;
    item->section = section;
    item->label = label;
    item->description = description;
    item->type = type;
    item->minimum = minimum;
    item->maximum = maximum;
    item->step = step;
    item->choices = choices;
    item->choice_count = choice_count;
    item->choice_values = choice_values;
}

RecompRuntimeUi *recomp_runtime_ui_create_standard(
    const RecompRuntimeUiStandardConfig *standard) {
    if (!standard) return NULL;
    size_t standard_count = 0;
    RecompRuntimeUiStandardFeatures f = standard->features;
    for (unsigned bit = 0; bit < 64; ++bit)
        if (f & (UINT64_C(1) << bit)) ++standard_count;
    size_t total = standard_count + standard->extra_item_count;
    if (!total) return NULL;

    RecompRuntimeUiItem *items = (RecompRuntimeUiItem *)calloc(total, sizeof(*items));
    if (!items) return NULL;
    const char **view_choices = NULL;
    int *view_values = NULL;
    size_t view_count = 0;
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_VIEW_MODE)) {
        unsigned modes = standard->view_modes | RECOMP_RUNTIME_UI_VIEW_MODE_NATIVE;
        for (unsigned i = 0; i < 3; ++i)
            if (modes & (1u << i)) ++view_count;
        view_choices = (const char **)calloc(view_count, sizeof(*view_choices));
        view_values = (int *)calloc(view_count, sizeof(*view_values));
        if (!view_choices || !view_values) {
            free(items); free(view_choices); free(view_values);
            return NULL;
        }
        size_t out = 0;
        if (modes & RECOMP_RUNTIME_UI_VIEW_MODE_NATIVE) {
            view_choices[out] = standard->native_view_label
                                    ? standard->native_view_label : "Native";
            view_values[out++] = RECOMP_RUNTIME_UI_VIEW_NATIVE;
        }
        if (modes & RECOMP_RUNTIME_UI_VIEW_MODE_FIXED_16_9) {
            view_choices[out] = standard->fixed_view_label
                                    ? standard->fixed_view_label : "16:9 fixed";
            view_values[out++] = RECOMP_RUNTIME_UI_VIEW_FIXED_16_9;
        }
        if (modes & RECOMP_RUNTIME_UI_VIEW_MODE_ADAPTIVE) {
            view_choices[out] = standard->adaptive_view_label
                                    ? standard->adaptive_view_label : "Adaptive";
            view_values[out++] = RECOMP_RUNTIME_UI_VIEW_ADAPTIVE;
        }
    }

    size_t count = 0;
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_FULLSCREEN))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_FULLSCREEN, "Display",
                 "Fullscreen", "Choose windowed or fullscreen output.",
                 RECOMP_RUNTIME_UI_CHOICE, 0, 2, 1, kFullscreenChoices, 3, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_WINDOW_SCALE))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_WINDOW_SCALE, "Display",
                 "Window scale", "Resize the window in native-size steps.",
                 RECOMP_RUNTIME_UI_INT, 1,
                 standard->window_scale_max > 0 ? standard->window_scale_max : 8,
                 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_VIEW_MODE))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_VIEW_MODE, "Display",
                 "View mode", "Native, fixed widescreen, or live window aspect.",
                 RECOMP_RUNTIME_UI_CHOICE, 0, 2, 1, view_choices, view_count,
                 view_values);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_WIDESCREEN_HUD))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_WIDESCREEN_HUD, "Display",
                 "Edge HUD", "Anchor status groups to widescreen edges.",
                 RECOMP_RUNTIME_UI_BOOL, 0, 1, 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_INTEGER_SCALE))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_INTEGER_SCALE, "Graphics",
                 "Integer scaling", "Snap output to whole native-pixel multiples.",
                 RECOMP_RUNTIME_UI_BOOL, 0, 1, 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_LINEAR_FILTER))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_LINEAR_FILTER, "Graphics",
                 "Linear filter", "Smooth the final game image.",
                 RECOMP_RUNTIME_UI_BOOL, 0, 1, 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_TEXTURE_FILTER))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_TEXTURE_FILTER, "Graphics",
                 "Texture filtering", "Choose nearest or linear sampling.",
                 RECOMP_RUNTIME_UI_CHOICE, 0, 1, 1, kTextureFilterChoices, 2, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_RESOLUTION_SCALE))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_RESOLUTION_SCALE, "Graphics",
                 "Resolution scale", "Set the internal rendering resolution.",
                 RECOMP_RUNTIME_UI_INT, 1,
                 standard->resolution_scale_max > 0 ? standard->resolution_scale_max : 8,
                 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_COLOR_CORRECTION))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_COLOR_CORRECTION, "Graphics",
                 "Color correction", "Use display-aware handheld color correction.",
                 RECOMP_RUNTIME_UI_BOOL, 0, 1, 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_LCD_GHOSTING))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_LCD_GHOSTING, "Graphics",
                 "LCD ghosting", "Simulate the original LCD response.",
                 RECOMP_RUNTIME_UI_BOOL, 0, 1, 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_AUDIO))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_AUDIO, "Audio", "Audio",
                 "Enable or mute game audio output.", RECOMP_RUNTIME_UI_BOOL,
                 0, 1, 1, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_VOLUME))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_VOLUME, "Audio", "Volume",
                 "Set the in-game mixer volume.", RECOMP_RUNTIME_UI_INT,
                 0, 100, 5, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_RESUME))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_RESUME, "System", "Resume game",
                 "Close settings and return to the game.", RECOMP_RUNTIME_UI_ACTION,
                 0, 0, 0, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_SAVE_STATE))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_SAVE_STATE, "System", "Save state",
                 "Save the current state.", RECOMP_RUNTIME_UI_ACTION,
                 0, 0, 0, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_LOAD_STATE))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_LOAD_STATE, "System", "Load state",
                 "Load the current state slot.", RECOMP_RUNTIME_UI_ACTION,
                 0, 0, 0, NULL, 0, NULL);
    if (has(f, RECOMP_RUNTIME_UI_STANDARD_RESET))
        add_item(items, &count, RECOMP_RUNTIME_UI_KEY_RESET, "System", "Reset game",
                 "Reset the emulated machine.", RECOMP_RUNTIME_UI_ACTION,
                 0, 0, 0, NULL, 0, NULL);

    if (standard->extra_items && standard->extra_item_count) {
        memcpy(items + count, standard->extra_items,
               standard->extra_item_count * sizeof(*items));
        count += standard->extra_item_count;
    }

    RecompRuntimeUiConfig menu = standard->menu;
    menu.items = items;
    menu.item_count = count;
    RecompRuntimeUi *ui = recomp_runtime_ui_create(&menu);
    if (!ui) {
        free(items); free(view_choices); free(view_values);
        return NULL;
    }
    ui->owned_items = items;
    ui->owned_view_choices = view_choices;
    ui->owned_view_values = view_values;
    return ui;
}
