// consoles/n64/n64_profile.h — the Nintendo 64 console unit, in one file:
// pad vocabulary, panel composition, SystemProfile row, name aliases, and the
// ABI capability defaults launcher_profile_apply() writes for "n64".
//
// Include via src/launcher_system.h (profiles + lookups) or
// src/launcher_profile.h (ABI apply) — consumers never include this directly.
//
// N64 is the multi-port cartridge-console model (vs PSX the deep disc console,
// GBA the handheld): FOUR controller ports (the launcher's only 4-player
// console), an 18-input controller (analog stick + C-button cluster + Z
// trigger), RT64-backed video settings (graphics API / SSAA / MSAA /
// fullscreen — the SS Anne launcher's Settings page), an optional per-port
// Transfer Pak GB-cartridge card set (GameInfo.tpak_slots; Stadium games),
// and native bind persistence through the games' own input.cfg format
// (consoles/n64/n64_binds.c — keyboard AND gamepad tables, two alternate
// binds per input).

#ifndef RUI_CONSOLE_N64_PROFILE_H
#define RUI_CONSOLE_N64_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- pad vocabulary (rebind page) ---------------------------------------------
// The real N64 input set: 18 inputs. Order MIRRORS PokemonStadiumRecomp's
// N64Input enum (include/input_bindings.h: A,B,Z,START,DPAD_*,L,R,C_*,STICK_*)
// so the spec index IS the engine input index — the n64_binds.c input.cfg
// bridge relies on this identity mapping for its <dev>.<INPUT>.<idx> keys.
static const ButtonDef kN64PadButtons[] = {
    { "A", 0 }, { "B", 1 }, { "Z", 2 }, { "Start", 3 },
    { "D-Pad Up", 4 }, { "D-Pad Down", 5 }, { "D-Pad Left", 6 }, { "D-Pad Right", 7 },
    { "L", 8 }, { "R", 9 },
    { "C-Up", 10 }, { "C-Down", 11 }, { "C-Left", 12 }, { "C-Right", 13 },
    { "Stick Up", 14 }, { "Stick Down", 15 }, { "Stick Left", 16 }, { "Stick Right", 17 },
};
#define LNG_N64_PAD_BUTTON_COUNT ((int)(sizeof(kN64PadButtons) / sizeof(kN64PadButtons[0])))

// ---- panel composition --------------------------------------------------------
// Dashboard: the common game + controller cards, plus the Transfer Pak card
// row (WIDE; composes only for games with GameInfo.tpak_slots > 0 — its
// availability gate — so Snap simply never shows it).
static const char* const kPanelsDashboardN64[] = { "game", "controller", "tpak", NULL };
// Settings: video + audio only — NO hotkeys page. The N64 runtimes read no
// config.ini [KeyMap] (in-game hotkeys are fixed in the runtime), and the SS
// Anne launcher exposed no hotkey editor either. Offering an editor that
// writes a file the game never reads would be a lie.
static const char* const kPanelsSettingsN64[] = { "video", "audio", NULL };

// ---- ROM file-picker filter -----------------------------------------------------
// The same filter the runners' native fallback dialog offers.
static const char* const kN64RomPatterns[] = { "*.z64", "*.n64", "*.v64" };
#define LNG_N64_ROM_PATTERN_COUNT \
    ((int)(sizeof(kN64RomPatterns) / sizeof(kN64RomPatterns[0])))

// ---- SystemProfile row ----------------------------------------------------------
static const SystemProfile kSystemProfileN64 = {
    /* id       */ "n64",
    /* platform */ "NINTENDO 64",
    /* theme    */ "n64",       // graphite + Nintendo-red, no CRT scanlines (RT64 era)
    /* rom_noun */ "ROM",
    /* controller */ {
        kN64PadButtons, LNG_N64_PAD_BUTTON_COUNT,
        "pad_n64.tga", NULL, NULL,     // real N64 controller art; no analog/digital pair
        /* max_players */ 4, /* has_pad_mode */ 0,
        /* binds_per_input */ 2,       // input.cfg keeps two alternate binds per input
    },
    // Cartridge battery saves, one file per game (per-game via sram_path —
    // the compact save row folded into the GAME card, like SNES/GBA).
    /* save */    { SAVE_SRAM, 1, NULL },
    /* video */   {
        /*window_scale*/0, /*fullscreen*/1, /*linear_filter*/0, /*widescreen*/1,
        /*renderer*/1, /*supersampling*/1, /*screen_kind*/0, /*frame_interp*/0, /*aspect*/0,
        /*texture_filter*/0, /*antialiasing*/1, /*spu_hq*/0, /*skip_fmv*/0, /*turbo_loads*/0,
        /*bios*/0, /*deadzone*/0,
    },
    /* verify */  { 0, NULL },    // rom-hash mode (CRC32/SHA pin, like the other carts)
    // No launcher-editable hotkeys (see kPanelsSettingsN64 above): the panel
    // never composes, and the mask documents the same fact.
    /* hotkeys_mask */ 0u,
    /* panels_dashboard  */ kPanelsDashboardN64,
    /* panels_settings   */ kPanelsSettingsN64,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ NULL,
    /* screen_kind_count */ 0,
    /* rom_filter        */ { kN64RomPatterns, LNG_N64_ROM_PATTERN_COUNT,
                              "N64 ROM (.z64 .n64 .v64)" },
    /* renderer_labels   */ NULL,              // hosts pass RT64 labels via ABI GameInfo
    /* hide_audio_freq   */ 0,                 // N64 audio panel keeps the sample-rate cycle
    /* brand             */ "",                // no corner emblem — the wordmark leads
    /* wordmark_image    */ "wordmark_n64.tga", // optional; absent => "NINTENDO 64" text
};

// ---- name aliases + ABI capability defaults -------------------------------------
static inline int launcher_console_is_n64(const char* name) {
    return lps_streq_ci(name, "n64") || lps_streq_ci(name, "nintendo64");
}

// The "n64" row of launcher_profile_apply(): system identity + capability
// defaults onto the C ABI GameInfo. Per-game fields (name, hashes, sram_path,
// num_players, tpak_slots + tpak_inspect, audio_device_labels, hide_rebind,
// widescreen_supported) are set by the host AFTER this.
static inline void launcher_profile_apply_n64(RecompLauncherCGameInfo* gi) {
    gi->theme    = "n64";              // graphite + Nintendo-red, no scanlines
    gi->platform = "NINTENDO 64";
    gi->rom_noun = "ROM";
    // The RT64-backed settings surface every N64 runner shares (the SS Anne
    // launcher's Settings page): graphics API pick, supersampling, MSAA,
    // fullscreen-on-launch. Hosts pass renderer_labels ({"Auto","Vulkan",
    // "D3D12"}) so the renderer cycle speaks RT64's vocabulary.
    gi->has_renderer          = 1;
    gi->has_supersampling     = 1;
    gi->has_antialiasing      = 1;
    // num_players deliberately NOT defaulted here: 1-player Snap and 4-player
    // Stadium diverge too much for a console default to be safe — each game
    // must state its player count explicitly (0 would legacy-default to 2).
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_N64_PROFILE_H
