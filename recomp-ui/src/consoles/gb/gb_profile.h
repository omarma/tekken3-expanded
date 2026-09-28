// consoles/gb/gb_profile.h — the Game Boy family console unit (DMG + Game Boy
// Color), in one file: pad vocabulary, keybind-store mapping, panel
// composition, screen-model (LCD palette) vocabulary, TWO SystemProfile rows
// (gb + gbc), name aliases, and the ABI capability defaults
// launcher_profile_apply() writes for "gb" / "gbc".
//
// Include via src/launcher_system.h (profiles + lookups) or
// src/launcher_profile.h (ABI apply) — consumers never include this directly.
//
// The Game Boy family is the cartridge-HANDHELD model like GBA, but simpler:
// a single player, an 8-input pad that is the console itself (D-pad, A, B,
// Start, Select — NO L/R, the one hardware difference from GBA), one
// battery-backed .sav per cartridge, and an LCD screen-model (DMG green /
// Pocket / Light / B&W / Amber) instead of CRT emulation.
//
// One binary (gb-recompiled) runs BOTH original Game Boy (DMG) and Game Boy
// Color (CGB) carts via a per-game `--model auto/dmg/cgb` hardware mode, and
// the pad is identical, so this is ONE code unit exposing TWO profiles that
// differ only in branding: `gb` (GAME BOY, DMG-green theme, Game Boy logo) for
// DMG titles (Tetris, Super Mario Land) and `gbc` (GAME BOY COLOR, color
// theme, Game Boy Color logo) for CGB titles (Megaman Xtreme 2) and the
// colorizable Pokémon carts. A host selects the right one per game.

#ifndef RUI_CONSOLE_GB_PROFILE_H
#define RUI_CONSOLE_GB_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- pad vocabulary (rebind page) ---------------------------------------------
// The real Game Boy input set: 8 inputs (D-pad, A, B, Start, Select) — no
// X/Y, no L/R, no sticks, no pad modes. `code` is the button's own index
// (0..7): the rebind page and the native keybind bridge (gb_binds.c) address
// buttons by this spec index.
static const ButtonDef kGbPadButtons[] = {
    { "Up", 0 }, { "Down", 1 }, { "Left", 2 }, { "Right", 3 },
    { "A", 4 }, { "B", 5 },
    { "Start", 6 }, { "Select", 7 },
};
#define LNG_GB_PAD_BUTTON_COUNT ((int)(sizeof(kGbPadButtons) / sizeof(kGbPadButtons[0])))

// ---- panel composition --------------------------------------------------------
// Dashboard stays common (game + controller; the save row folds into the GAME
// card like GBA/SNES — one .sav per cartridge, no slot grid). Settings is
// video + audio ONLY: gb-recompiled's in-game hotkeys (savestate slots,
// fullscreen, turbo) are fixed in the runner and read no launcher-editable
// config, so — like Genesis — offering a hotkey editor here would write a file
// the game never reads. The controller rebind page IS honest: game buttons
// persist through keybinds.ini, which the runtime reads (gb_binds.c bridge).
static const char* const kPanelsSettingsGb[] = { "video", "audio", NULL };

// ---- screen-model (LCD palette + SGB) vocabulary --------------------------------
// Indices 0..4 mirror the gb-recompiled runtime's DMG colorization palette list
// (platform_sdl.cpp g_palette_names) and map to runtime_prefs.ini `video.palette`
// with SGB colorization off. Indices 5..6 are the Super Game Boy models: the seam
// maps them to sgb.colors=1 (+ sgb.cart_border), not to a DMG palette. For CGB
// carts the game renders its own colors and this acts as the DMG-compat palette;
// SGB models only affect SGB-enhanced carts. Keep in sync with the seam's
// screen_kind <-> pref mapping (launcher_ui_seam.c) and the button width in
// launcher_imgui.cpp (longest label = "Super Game Boy (No Border)").
static const char* const kGbScreenKindNames[] = {
    "DMG", "Game Boy Pocket", "Game Boy Light", "Black & White", "Amber (Phosphor)",
    "Super Game Boy", "Super Game Boy (No Border)"
};
#define LNG_GB_SCREEN_KIND_SGB          5   /* Super Game Boy: colors + border */
#define LNG_GB_SCREEN_KIND_SGB_NOBORDER 6   /* Super Game Boy: colors, no border */
#define LNG_GB_SCREEN_KIND_COUNT \
    ((int)(sizeof(kGbScreenKindNames) / sizeof(kGbScreenKindNames[0])))

// ---- ROM file-picker filter -----------------------------------------------------
static const char* const kGbRomPatterns[] = { "*.gb", "*.gbc", "*.sgb" };
#define LNG_GB_ROM_PATTERN_COUNT \
    ((int)(sizeof(kGbRomPatterns) / sizeof(kGbRomPatterns[0])))

// ---- shared video shape (both profiles) -----------------------------------------
// Integer window scale + linear-filter toggle (base rows), the LCD palette
// cycle (screen_kind), and fullscreen-on-launch. No BIOS (gb-recompiled boots
// its bundled/HLE boot ROM), no widescreen by default (per-game opt-in, e.g.
// Megaman Xtreme 2's extended view sets widescreen_supported=1).
#define LNG_GB_VIDEO_SPEC {                                                    \
    /*window_scale*/1, /*fullscreen*/1, /*linear_filter*/1, /*widescreen*/0,   \
    /*renderer*/0, /*supersampling*/0, /*screen_kind*/0, /*frame_interp*/0, /*aspect*/0, \
    /*texture_filter*/0, /*antialiasing*/0, /*spu_hq*/0, /*skip_fmv*/0, /*turbo_loads*/0, \
    /*bios*/0, /*deadzone*/0,                                                   \
}

// ---- SystemProfile rows (gb = DMG branding, gbc = color branding) ---------------
// Both share pad vocabulary, panels, save model, ROM filter, palette list and
// (empty) hotkey set; they differ only in id / platform label / theme / pad
// art / brand mark.
static const SystemProfile kSystemProfileGb = {
    /* id       */ "gb",
    /* platform */ "GAME BOY",
    /* theme    */ "gb",         // DMG pea-green LCD theme (launcher_theme.h)
    /* rom_noun */ "ROM",
    /* controller */ {
        kGbPadButtons, LNG_GB_PAD_BUTTON_COUNT,
        "pad_gb.tga", NULL, NULL,       // handheld art; no analog/digital pair
        /* max_players */ 1, /* has_pad_mode */ 0,
    },
    /* save */    { SAVE_SRAM, 1, NULL },   // one battery .sav per cartridge
    /* video */   LNG_GB_VIDEO_SPEC,
    /* verify */  { 0, NULL },              // rom-hash mode (CRC32 / SHA-256 pin)
    /* hotkeys_mask */ 0u,                  // no launcher-editable hotkeys (runner-fixed)
    /* panels_dashboard  */ kPanelsDashboardCommon,
    /* panels_settings   */ kPanelsSettingsGb,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ kGbScreenKindNames,
    /* screen_kind_count */ LNG_GB_SCREEN_KIND_COUNT,
    /* rom_filter        */ { kGbRomPatterns, LNG_GB_ROM_PATTERN_COUNT,
                              "Game Boy ROM (.gb/.gbc)" },
    /* renderer_labels   */ NULL,          // GL-only; no renderer toggle shown
    /* hide_audio_freq   */ 0,             // AUDIO panel shows the (fixed) rate
    /* brand             */ "brand_gb.tga",
};

static const SystemProfile kSystemProfileGbc = {
    /* id       */ "gbc",
    /* platform */ "GAME BOY COLOR",
    /* theme    */ "gbc",        // Game Boy Color berry/teal theme (launcher_theme.h)
    /* rom_noun */ "ROM",
    /* controller */ {
        kGbPadButtons, LNG_GB_PAD_BUTTON_COUNT,
        "pad_gbc.tga", NULL, NULL,
        /* max_players */ 1, /* has_pad_mode */ 0,
    },
    /* save */    { SAVE_SRAM, 1, NULL },
    /* video */   LNG_GB_VIDEO_SPEC,
    /* verify */  { 0, NULL },
    /* hotkeys_mask */ 0u,
    /* panels_dashboard  */ kPanelsDashboardCommon,
    /* panels_settings   */ kPanelsSettingsGb,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ kGbScreenKindNames,
    /* screen_kind_count */ LNG_GB_SCREEN_KIND_COUNT,
    /* rom_filter        */ { kGbRomPatterns, LNG_GB_ROM_PATTERN_COUNT,
                              "Game Boy Color ROM (.gbc/.gb)" },
    /* renderer_labels   */ NULL,          // GL-only; no renderer toggle shown
    /* hide_audio_freq   */ 0,             // AUDIO panel shows the (fixed) rate
    /* brand             */ "brand_gbc.tga",
};

// ---- name aliases ---------------------------------------------------------------
static inline int launcher_console_is_gb(const char* name) {
    return lps_streq_ci(name, "gb") || lps_streq_ci(name, "gameboy") ||
           lps_streq_ci(name, "dmg");
}
static inline int launcher_console_is_gbc(const char* name) {
    return lps_streq_ci(name, "gbc") || lps_streq_ci(name, "gameboycolor") ||
           lps_streq_ci(name, "cgb");
}

// ---- ABI capability defaults ----------------------------------------------------
// The shared "gb family" caps; the two apply rows differ only in theme/platform.
static inline void launcher_profile_apply_gb_common(RecompLauncherCGameInfo* gi) {
    gi->rom_noun = "ROM";
    gi->num_players = 1;               // handheld: one player (no link cable yet)
    // gb settings surface: integer window scale + linear filter (base rows),
    // the LCD palette cycle, and fullscreen-on-launch. No BIOS picker.
    gi->has_screen_kind       = 1;
    // widescreen_supported stays 0: per-game opt-in (Megaman Xtreme 2's
    // extended view); stock titles render the native 160x144.
}

static inline void launcher_profile_apply_gb(RecompLauncherCGameInfo* gi) {
    gi->theme    = "gb";
    gi->platform = "GAME BOY";
    launcher_profile_apply_gb_common(gi);
}

static inline void launcher_profile_apply_gbc(RecompLauncherCGameInfo* gi) {
    gi->theme    = "gbc";
    gi->platform = "GAME BOY COLOR";
    launcher_profile_apply_gb_common(gi);
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_GB_PROFILE_H
