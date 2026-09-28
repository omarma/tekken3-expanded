// consoles/psx/psx_profile.h — the PlayStation console unit, in one file:
// pad vocabulary, panel composition, SystemProfile row, name aliases, and the
// ABI capability defaults launcher_profile_apply() writes for "psx".
//
// Include via src/launcher_system.h (profiles + lookups) or
// src/launcher_profile.h (ABI apply) — consumers never include this directly.
// The PSX-native keybind persistence bridge lives next door in psx_binds.c.

#ifndef RUI_CONSOLE_PSX_PROFILE_H
#define RUI_CONSOLE_PSX_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- pad vocabulary (rebind page) ---------------------------------------------
// PSX DualShock/digital-pad base set (24) — real vocabulary for the PSX
// rebind page. `code` is just the button's own index (0..23): the rebind page
// and bind persistence (launcher_binds.c + psx_binds.c) both address buttons
// by this spec index, not by any engine-side enum. The first 16 are the
// physical DualShock inputs; the last 8 are the keyboard->analog-stick
// DIRECTION binds (psxrecomp's runtime/launcher/psx_keybinds.h
// PSX_KB_LS_UP..PSX_KB_RS_RIGHT) that drive the left/right analog stick from
// the keyboard in analog pad modes. Mirrors the game's full 24-button
// kButtons vocabulary so every bind psx_keybinds.c understands is reachable
// from this launcher's rebind page (see psx_binds.c for the persistence side).
static const ButtonDef kPsxPadButtons[] = {
    { "Up", 0 }, { "Down", 1 }, { "Left", 2 }, { "Right", 3 },
    { "Triangle", 4 }, { "Circle", 5 }, { "Cross", 6 }, { "Square", 7 },
    { "L1", 8 }, { "L2", 9 }, { "R1", 10 }, { "R2", 11 },
    { "L3", 12 }, { "R3", 13 }, { "Start", 14 }, { "Select", 15 },
    { "L-Stick Up", 16 }, { "L-Stick Down", 17 }, { "L-Stick Left", 18 }, { "L-Stick Right", 19 },
    { "R-Stick Up", 20 }, { "R-Stick Down", 21 }, { "R-Stick Left", 22 }, { "R-Stick Right", 23 },
};
#define LNG_PSX_PAD_BUTTON_COUNT ((int)(sizeof(kPsxPadButtons) / sizeof(kPsxPadButtons[0])))

// Gamepad Bindings panel / Map All order: column-major (top→bottom, then
// next column). Indices into kPsxPadButtons.
//   Col1: D-pad + L-Stick    Col2: Face + R-Stick    Col3: Shoulders / Start
static const int kPsxGamepadBindOrder[LNG_PSX_PAD_BUTTON_COUNT] = {
    0, 1, 2, 3, 16, 17, 18, 19,   // Up Down Left Right / LS*
    6, 5, 7, 4, 20, 21, 22, 23,   // Cross Circle Square Triangle / RS*
    8, 9, 10, 11, 14, 15, 12, 13, // L1 L2 R1 R2 Start Select L3 R3
};
#define LNG_PSX_GAMEPAD_BIND_COLS 3
#define LNG_PSX_GAMEPAD_BIND_ROWS 8

// ---- panel composition --------------------------------------------------------
// PSX only: adds the standalone "save" panel (WIDE, memory-card block-grid
// UI) below the game/controller row. SNES keeps kPanelsDashboardCommon
// unchanged — its SRAM row stays folded into the GAME card exactly as today.
static const char* const kPanelsDashboardPsx[] = { "game", "controller", "save", NULL };
static const char* const kPanelsSettingsPsx[]   =
    { "video", "audio", "input", "system", "hotkeys", NULL };

// ---- ROM (disc) file-picker filter ----------------------------------------------
// Cue sheets only (Redump-style). Track .bin files sit beside the .cue; bare
// .iso/.bin/.img are not offered in the picker — generate/boot need a TOC.
static const char* const kPsxDiscPatterns[] = {
    "*.cue",
};
#define LNG_PSX_DISC_PATTERN_COUNT \
    ((int)(sizeof(kPsxDiscPatterns) / sizeof(kPsxDiscPatterns[0])))

// ---- SystemProfile row ----------------------------------------------------------
static const SystemProfile kSystemProfilePsx = {
    /* id       */ "psx",
    /* platform */ "PLAYSTATION",
    /* theme    */ "psx",
    /* rom_noun */ "Disc",
    /* controller */ {
        kPsxPadButtons, LNG_PSX_PAD_BUTTON_COUNT,     // real PSX pad vocabulary (Triangle/Circle/Cross/Square/L1-2/R1-2/L3/R3)
        "pad.tga", "pad_analog.tga", "pad_digital.tga",
        /* max_players */ 8, /* dual multitap ceiling; game num_players may be lower */
        /* has_pad_mode */ 1,
        /* binds_per_input */ 2,  // primary + alternate; either asserts the
                                  // input, and either may be a mouse button
    },
    // MEMCARD is PSX's real target shape (2 slots): the standalone "save" panel
    // (see kPanelsDashboardPsx above) renders a dual-slot picker + 15-block
    // usage grid per slot (panel_save_draw in launcher_imgui.cpp). `probe` stays
    // NULL until a host wires up real per-block card scanning; the panel still
    // renders a full, real placeholder grid in the meantime (never a TODO).
    /* save */    { SAVE_MEMCARD, 2, NULL },
    /* video */   {
        /*window_scale*/0, /*fullscreen*/1, /*linear_filter*/0, /*widescreen*/0,
        /*renderer*/1, /*supersampling*/1, /*screen_kind*/1, /*frame_interp*/1, /*aspect*/1,
        /*texture_filter*/1, /*antialiasing*/1, /*spu_hq*/1, /*skip_fmv*/1, /*turbo_loads*/1,
        /*bios*/1, /*deadzone*/1,
    },
    /* verify */  { 1, NULL },    // disc-verdict mode; probe==NULL -> synthesized verdict (see launcher_model.c)
    // PSX's real hotkey catalog: the everyday transport controls only. Omits
    // LNG_HK_PAUSE_DIMMED (an SNES-engine-only attract-loop affordance) and
    // the window-resize pair (SNES-only integer-scale window; PSX sizes via
    // window_scale + fullscreen instead) — see requirement in the hotkey
    // catalog task. Everything else in the universal LngHotkey catalog applies.
    /* hotkeys_mask */ (uint32_t)((1u << LNG_HK_FULLSCREEN)     |
                                   (1u << LNG_HK_RESET)          |
                                   (1u << LNG_HK_PAUSE)          |
                                   (1u << LNG_HK_TURBO)          |
                                   (1u << LNG_HK_VOLUME_UP)      |
                                   (1u << LNG_HK_VOLUME_DOWN)    |
                                   (1u << LNG_HK_DISPLAY_PERF)   |
                                   (1u << LNG_HK_TOGGLE_RENDERER)),
    /* panels_dashboard  */ kPanelsDashboardPsx,
    /* panels_settings   */ kPanelsSettingsPsx,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ NULL,   /* legacy Raw/CRT/Composite/Trinitron set */
    /* screen_kind_count */ 0,
    /* rom_filter        */ { kPsxDiscPatterns, LNG_PSX_DISC_PATTERN_COUNT,
                              "PlayStation disc (.cue)" },
    /* renderer_labels   */ NULL,
    /* hide_audio_freq   */ 0,
    /* brand             */ "brand_psx.tga",
    /* wordmark_image    */ NULL,
};

// ---- name aliases + ABI capability defaults -------------------------------------
static inline int launcher_console_is_psx(const char* name) {
    return lps_streq_ci(name, "psx") || lps_streq_ci(name, "ps1") ||
           lps_streq_ci(name, "playstation");
}

// The "psx" row of launcher_profile_apply(): system identity + capability
// defaults onto the C ABI GameInfo. Per-game fields (name, aspect_mask
// additions, pad-mode locks, disc CRC, callbacks) are set by the host AFTER
// this.
static inline void launcher_profile_apply_psx(RecompLauncherCGameInfo* gi) {
    gi->theme    = "psx";              // PlayStation blue, no CRT scanlines
    gi->platform = "PLAYSTATION";
    gi->rom_noun = "Disc";
    // Controller: PSX has analog/digital pad modes + swapping DualShock art.
    gi->pad_mode_supported  = 1;
    gi->pad_mode_selectable = 1;       // per-game lock_mode may set this to 0
    /* Display enhancements are mod-owned on PSX. Keep the generic View mode,
     * Frame interpolation, and Skip FMVs rows absent by default; trusted game
     * plugins activate those features after launcher resolution. */
    gi->widescreen_supported = 0;
    gi->aspect_mask           = 0;
    // Full PS1 settings surface.
    gi->has_window_size = 1; gi->has_renderer = 1; gi->has_supersampling = 1;
    gi->has_antialiasing = 1; gi->has_texture_filter = 1; gi->has_screen_kind = 1;
    gi->has_frame_interp = 0; gi->has_spu_hq = 1; gi->has_skip_fmv = 0;
    gi->has_turbo_loads = 1; gi->has_bios = 1;
    gi->has_deadzone_pct = 1;
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_PSX_PROFILE_H
