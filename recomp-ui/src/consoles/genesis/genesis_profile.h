// consoles/genesis/genesis_profile.h — the Sega Genesis / Mega Drive console
// unit, in one file: pad vocabulary, pad-mode list, panel composition,
// SystemProfile row, name aliases, and the ABI capability defaults
// launcher_profile_apply() writes for "genesis".
//
// Include via src/launcher_system.h (profiles + lookups) or
// src/launcher_profile.h (ABI apply) — consumers never include this directly.
//
// Genesis is the cartridge-CONSOLE model like SNES (SRAM folded into the GAME
// card, legacy widescreen bool, CRT-era default theme) plus three concepts of
// its own:
//   * a 3-Button / 6-Button pad-mode selector (the protocol the controller
//     port exposes; per player, mirroring the engine's per-player PadType) —
//     3-button mode hides the X/Y/Z/Mode rebind rows,
//   * a GAMEPAD bind column on the rebind page (has_pad_binds): the engine's
//     input map stores an SDL_GameController button/axis bind per logical
//     button alongside the keyboard scancode, and the legacy launcher this
//     replaces offered "Set key" AND "Set pad" per row,
//   * a widescreen "extra cells per side" stepper (video.widescreen_cells):
//     the engine renders N extra 8-px background cells per side in widescreen.
// Bind persistence routes through the Genesis-native settings.ini bridge
// (consoles/genesis/genesis_binds.c — [input.pN] key.<Name>/pad.<Name>, the
// exact format segagenesisrecomp's runner/app_config.c reads and writes).

#ifndef RUI_CONSOLE_GENESIS_PROFILE_H
#define RUI_CONSOLE_GENESIS_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- pad vocabulary (rebind page) ---------------------------------------------
// The full 12-input Genesis logical set. Order MIRRORS the engine's
// GenesisButton enum (segagenesisrecomp runner/input_map.h GB_UP..GB_MODE) so
// the spec index IS the engine button index — the settings.ini bridge
// (genesis_binds.c) relies on this identity mapping, as does the 3-button
// subset rule: the first 8 entries (U/D/L/R + A/B/C/Start) are exactly the
// 3-button pad; X/Y/Z/Mode are the 6-button extension.
static const ButtonDef kGenesisPadButtons[] = {
    { "Up", 0 }, { "Down", 1 }, { "Left", 2 }, { "Right", 3 },
    { "A", 4 }, { "B", 5 }, { "C", 6 }, { "Start", 7 },
    { "X", 8 }, { "Y", 9 }, { "Z", 10 }, { "Mode", 11 },
};
#define LNG_GENESIS_PAD_BUTTON_COUNT \
    ((int)(sizeof(kGenesisPadButtons) / sizeof(kGenesisPadButtons[0])))

// ---- pad modes ------------------------------------------------------------------
// Values mirror the engine's PadType enum (0 = 3-button, 1 = 6-button); stored
// per player in RecompLauncherCSettings.pad_mode[], like the engine's
// per-player pad_type. 3-Button shows only the first 8 rebind rows.
static const PadModeDef kGenesisPadModes[] = {
    { 0, "3-Button", 8 },
    { 1, "6-Button", LNG_GENESIS_PAD_BUTTON_COUNT },
};
#define LNG_GENESIS_PAD_MODE_COUNT \
    ((int)(sizeof(kGenesisPadModes) / sizeof(kGenesisPadModes[0])))

// ---- panel composition --------------------------------------------------------
// Dashboard stays common (game + controller; battery SRAM folds into the GAME
// card like SNES — per-game via sram_path, only S3/S3&K carts have a battery).
// Settings is video + audio ONLY: the Genesis runtime's hotkeys (F1-F9
// savestates, F11 fullscreen, F5 turbo, ...) are fixed in the runner and read
// no config, and the legacy launcher this replaces exposed no hotkey editor —
// offering an editor that writes a file the game never reads would be a lie.
static const char* const kPanelsSettingsGenesis[] = { "video", "audio", NULL };

// ---- ROM file-picker filter -----------------------------------------------------
// Same extension set the legacy launcher's Change-ROM dialog filtered on.
static const char* const kGenesisRomPatterns[] = { "*.bin", "*.md", "*.gen", "*.smd" };
#define LNG_GENESIS_ROM_PATTERN_COUNT \
    ((int)(sizeof(kGenesisRomPatterns) / sizeof(kGenesisRomPatterns[0])))

// ---- SystemProfile row ----------------------------------------------------------
static const SystemProfile kSystemProfileGenesis = {
    /* id       */ "genesis",
    /* platform */ "SEGA GENESIS",
    /* theme    */ "genesis",    // Sega-blue accent, CRT scanlines (launcher_theme.h)
    /* rom_noun */ "ROM",
    /* controller */ {
        kGenesisPadButtons, LNG_GENESIS_PAD_BUTTON_COUNT,
        "pad_genesis.tga", NULL, NULL,   // single pad art; no analog/digital swap pair
        /* max_players */ 2, /* has_pad_mode */ 1,
        /* binds_per_input */ 1,       // one key bind per input (the GAMEPAD chip is a separate pad bind)
        kGenesisPadModes, LNG_GENESIS_PAD_MODE_COUNT,
        /* has_pad_binds */ 1,
    },
    /* save */    { SAVE_SRAM, 1, NULL },   // battery cartridge SRAM (per-game via sram_path)
    /* video */   {
        /*window_scale*/1, /*fullscreen*/1, /*linear_filter*/1, /*widescreen*/1,
        /*renderer*/0, /*supersampling*/0, /*screen_kind*/0, /*frame_interp*/0, /*aspect*/0,
        /*texture_filter*/0, /*antialiasing*/0, /*spu_hq*/0, /*skip_fmv*/0, /*turbo_loads*/0,
        /*bios*/0, /*deadzone*/0,
        /*widescreen_cells*/1,
    },
    /* verify */  { 0, NULL },   // rom-hash mode (CRC32 vs the game spec's expected CRC)
    // No launcher-editable hotkeys (see kPanelsSettingsGenesis above): the
    // runner's hotkeys are fixed and read no config — 0 keeps the catalog
    // honest even if a future composition re-adds the panel.
    /* hotkeys_mask */ 0u,
    /* panels_dashboard  */ kPanelsDashboardCommon,
    /* panels_settings   */ kPanelsSettingsGenesis,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ NULL,    // no screen-model cycle (video.screen_kind is 0)
    /* screen_kind_count */ 0,
    /* rom_filter        */ { kGenesisRomPatterns, LNG_GENESIS_ROM_PATTERN_COUNT,
                              "Sega Genesis ROM (.bin/.md/.gen/.smd)" },
    /* renderer_labels   */ NULL,    // legacy Software/OpenGL pair
    /* hide_audio_freq   */ 0,       // Genesis shows the sample-rate cycle
    /* brand             */ "brand_genesis.tga",   // SEGA GENESIS wordmark (top-left header)
};

// ---- name aliases + ABI capability defaults -------------------------------------
static inline int launcher_console_is_genesis(const char* name) {
    return lps_streq_ci(name, "genesis") || lps_streq_ci(name, "megadrive") ||
           lps_streq_ci(name, "md") || lps_streq_ci(name, "segagenesis");
}

// The "genesis" row of launcher_profile_apply(): system identity + capability
// defaults onto the C ABI GameInfo. Per-game fields (name, region, CRC,
// sram_path, num_players, and widescreen_supported for titles without a
// widescreen-capable layout) are set by the host AFTER this.
static inline void launcher_profile_apply_genesis(RecompLauncherCGameInfo* gi) {
    gi->theme    = "genesis";          // Sega-blue accent, CRT scanlines
    gi->platform = "SEGA GENESIS";
    gi->rom_noun = "ROM";
    // 3-Button/6-Button pad-mode selector (per player, engine PadType values).
    // The custom mode list lives on the SystemProfile row; these ABI flags
    // just switch the selector on.
    gi->pad_mode_supported  = 1;
    gi->pad_mode_selectable = 1;
    // Widescreen defaults ON at the console level (every shipped Genesis
    // recomp exposes the experimental 16:9 path); a per-game host overrides
    // to 0 when its layout isn't widescreen-capable (g_game_layout.ws_capable).
    gi->widescreen_supported = 1;
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_GENESIS_PROFILE_H
