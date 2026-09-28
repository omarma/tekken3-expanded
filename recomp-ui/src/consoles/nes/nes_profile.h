// consoles/nes/nes_profile.h — the Nintendo Entertainment System console unit,
// in one file: pad vocabulary, panel composition, ROM filter, SystemProfile
// row, name aliases, and the ABI capability defaults launcher_profile_apply()
// writes for "nes".
//
// Include via src/launcher_system.h (profiles + lookups) or
// src/launcher_profile.h (ABI apply) — consumers never include this directly.
//
// NES is a cartridge CONSOLE like SNES (rom-hash verify, SRAM saves folded
// into the GAME card, legacy minimal video surface) with its own wrinkles:
// an 8-input pad, a nesrecomp runner that keeps its OWN keybinds.ini format
// (with [zapper] and [gamepad1]/[gamepad2] sections — see nes_binds.c, the
// native persistence bridge), NO config.ini [KeyMap] (runner hotkeys are
// fixed F5/F6/F7/F11, so no hotkey editor is offered), and per-game NES
// capabilities the ABI gates: integer scaling, Mesen HD texture packs,
// password/mantra saves (Faxanadu), and the Zapper light gun.

#ifndef RUI_CONSOLE_NES_PROFILE_H
#define RUI_CONSOLE_NES_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- pad vocabulary (rebind page) ---------------------------------------------
// The real NES input set: 8 inputs. `code` is the button's own index (0..7);
// nes_binds.c maps each spec index to the nesrecomp runner's keybinds.ini key
// NAME (runner/src/keybinds.c: a/b/select/start/up/down/left/right) so
// rebinds land in the exact format the game's runtime reads.
static const ButtonDef kNesPadButtons[] = {
    { "Up", 0 }, { "Down", 1 }, { "Left", 2 }, { "Right", 3 },
    { "A", 4 }, { "B", 5 },
    { "Start", 6 }, { "Select", 7 },
};
#define LNG_NES_PAD_BUTTON_COUNT ((int)(sizeof(kNesPadButtons) / sizeof(kNesPadButtons[0])))

// ---- panel composition --------------------------------------------------------
// No "hotkeys" panel: the nesrecomp runner reads no config.ini [KeyMap] (its
// hotkeys are hardcoded F5 turbo / F6 save / F7 load / F11 fullscreen in
// main_runner.c), so a hotkey editor would write lines nothing reads. This
// also matches the old NES launcher, which offered no hotkey UI.
static const char* const kPanelsSettingsNes[] = { "video", "audio", NULL };

// ---- renderer vocabulary --------------------------------------------------------
// The runner's [Display] Renderer key: 0 = SDL accelerated, 1 = SDL software.
// Same 0/1 the has_renderer toggle cycles; only the words differ from PSX's
// Software/OpenGL pair.
static const char* const kNesRendererLabels[] = { "Accelerated", "Software" };

// ---- ROM file-picker filter -----------------------------------------------------
static const char* const kNesRomPatterns[] = { "*.nes" };
#define LNG_NES_ROM_PATTERN_COUNT \
    ((int)(sizeof(kNesRomPatterns) / sizeof(kNesRomPatterns[0])))

// ---- SystemProfile row ----------------------------------------------------------
static const SystemProfile kSystemProfileNes = {
    /* id       */ "nes",
    /* platform */ "NINTENDO ENTERTAINMENT SYSTEM",
    /* theme    */ "nes",       // graphite + Nintendo-red NES theme
    /* rom_noun */ "ROM",
    /* controller */ {
        kNesPadButtons, LNG_NES_PAD_BUTTON_COUNT,
        "pad_nes.tga", NULL, NULL,     // shipped NES pad art; no analog/digital pair
        /* max_players */ 2, /* has_pad_mode */ 0,
    },
    // Battery SRAM, one slot, folded into the GAME card like SNES. Shown only
    // for games that pass sram_path (battery-backed titles, e.g. Zelda/Kirby);
    // password-save titles (Faxanadu) use password_save_path instead.
    /* save */    { SAVE_SRAM, 1, NULL },
    /* video */   {
        /*window_scale*/1, /*fullscreen*/1, /*linear_filter*/1, /*widescreen*/1,
        /*renderer*/0, /*supersampling*/0, /*screen_kind*/0, /*frame_interp*/0, /*aspect*/0,
        /*texture_filter*/0, /*antialiasing*/0, /*spu_hq*/0, /*skip_fmv*/0, /*turbo_loads*/0,
        /*bios*/0, /*deadzone*/0,
    },
    /* verify */  { 0, NULL },    // rom-hash mode (CRC32 pin over the post-iNES-header body)
    // No [KeyMap] in the runner (see kPanelsSettingsNes) — opt into no
    // universal hotkeys at all so no editor row can ever appear.
    /* hotkeys_mask */ 0,
    /* panels_dashboard  */ kPanelsDashboardCommon,
    /* panels_settings   */ kPanelsSettingsNes,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ NULL,   // no screen-model cycle (has_screen_kind stays 0)
    /* screen_kind_count */ 0,
    /* rom_filter        */ { kNesRomPatterns, LNG_NES_ROM_PATTERN_COUNT,
                              "NES ROM (.nes)" },
    /* renderer_labels   */ kNesRendererLabels,   // Accelerated/Software (SDL output)
    /* hide_audio_freq   */ 1,      // runner has no audio-frequency setting (Volume only)
    /* brand             */ "brand_nes.tga",      // red "Nintendo" pill, not the SNES swoosh
};

// ---- name aliases + ABI capability defaults -------------------------------------
static inline int launcher_console_is_nes(const char* name) {
    return lps_streq_ci(name, "nes") || lps_streq_ci(name, "famicom") ||
           lps_streq_ci(name, "nintendoentertainmentsystem");
}

// The "nes" row of launcher_profile_apply(): system identity + capability
// defaults onto the C ABI GameInfo. Per-game fields (name, CRC, sram_path,
// widescreen_supported, password save, zapper) are set by the host AFTER this.
static inline void launcher_profile_apply_nes(RecompLauncherCGameInfo* gi) {
    gi->theme    = "nes";              // graphite + Nintendo-red NES theme
    gi->platform = "NINTENDO ENTERTAINMENT SYSTEM";
    gi->rom_noun = "ROM";
    // Every nesrecomp runner supports integer scaling; Mesen HD texture packs
    // default ON per game (a stock build that must not load packs sets
    // hdpack_supported back to 0 — e.g. the unpatched Zelda variant, which
    // compiles with NESRECOMP_GAME_NO_HDPACK). Widescreen, SRAM path,
    // password save, and Zapper are per-game opt-ins.
    gi->has_integer_scale = 1;
    gi->hdpack_supported  = 1;
    // The runner's Accelerated/Software output toggle (config.ini [Display]
    // Renderer) — shown with kNesRendererLabels, not the PSX Software/OpenGL
    // pair. This was a real control on the old NES launcher.
    gi->has_renderer      = 1;
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_NES_PROFILE_H
