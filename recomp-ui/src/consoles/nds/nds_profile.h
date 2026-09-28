// consoles/nds/nds_profile.h — Nintendo DS console profile.

#ifndef RUI_CONSOLE_NDS_PROFILE_H
#define RUI_CONSOLE_NDS_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

static const ButtonDef kNdsPadButtons[] = {
    { "Up", 0 }, { "Down", 1 }, { "Left", 2 }, { "Right", 3 },
    { "A", 4 }, { "B", 5 }, { "X", 6 }, { "Y", 7 },
    { "L", 8 }, { "R", 9 }, { "Start", 10 }, { "Select", 11 },
};
#define LNG_NDS_PAD_BUTTON_COUNT \
    ((int)(sizeof(kNdsPadButtons) / sizeof(kNdsPadButtons[0])))

// Touch is intentionally not represented as a pad binding. The host owns the
// bottom-screen pointer mapping; this profile describes Player 1's ordinary
// buttons and controller assignment.
static const char* const kPanelsSettingsNds[] = {
    "video", "audio", NULL
};

static const char* const kNdsRomPatterns[] = { "*.nds", "*.srl" };
#define LNG_NDS_ROM_PATTERN_COUNT \
    ((int)(sizeof(kNdsRomPatterns) / sizeof(kNdsRomPatterns[0])))

static const SystemProfile kSystemProfileNds = {
    /* id       */ "nds",
    /* platform */ "NINTENDO DS",
    /* theme    */ "nds",
    /* rom_noun */ "ROM",
    /* controller */ {
        kNdsPadButtons, LNG_NDS_PAD_BUTTON_COUNT,
        "pad_nds.tga", NULL, NULL,
        /* max_players */ 1, /* has_pad_mode */ 0,
    },
    /* save */ { SAVE_NONE, 0, NULL },
    /* video */ {
        /*window_scale*/1, /*fullscreen*/1, /*linear_filter*/0,
        /*widescreen*/0, /*renderer*/0, /*supersampling*/1,
        /*screen_kind*/0, /*frame_interp*/0, /*aspect*/0,
        /*texture_filter*/0, /*antialiasing*/1, /*spu_hq*/0,
        /*skip_fmv*/0, /*turbo_loads*/0, /*bios*/0, /*deadzone*/0,
    },
    /* verify */ { 0, NULL },
    /* hotkeys_mask */ 0,
    /* panels_dashboard  */ kPanelsDashboardCommon,
    /* panels_settings   */ kPanelsSettingsNds,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ NULL,
    /* screen_kind_count */ 0,
    /* rom_filter */ {
        kNdsRomPatterns, LNG_NDS_ROM_PATTERN_COUNT,
        "Nintendo DS ROM (.nds .srl)"
    },
    /* renderer_labels */ NULL,
    /* hide_audio_freq */ 1,
    /* brand */ "brand_nds.tga",
    /* wordmark_image */ NULL,
};

static inline int launcher_console_is_nds(const char* name) {
    return lps_streq_ci(name, "nds") ||
           lps_streq_ci(name, "nintendods") ||
           lps_streq_ci(name, "ds");
}

static inline void launcher_profile_apply_nds(RecompLauncherCGameInfo* gi) {
    gi->theme = "nds";
    gi->platform = "NINTENDO DS";
    gi->rom_noun = "ROM";
    gi->num_players = 1;
    gi->has_supersampling = 1;
    gi->has_antialiasing = 1;
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_NDS_PROFILE_H
