// consoles/gba/gba_profile.h — the Game Boy Advance console unit, in one file:
// pad vocabulary, keybind-store mapping, panel composition, screen-model
// vocabulary, SystemProfile row, name aliases, and the ABI capability
// defaults launcher_profile_apply() writes for "gba".
//
// Include via src/launcher_system.h (profiles + lookups) or
// src/launcher_profile.h (ABI apply) — consumers never include this directly.
//
// GBA is the cartridge-HANDHELD model console (vs PSX, the deep disc-console
// model): a single player, a 10-input pad that is the console itself, one
// battery-backed save file per cartridge (the runtime unifies EEPROM/flash/
// SRAM behind one .sav), a required BIOS image (LLE by default), and an LCD
// screen-model filter instead of CRT emulation.

#ifndef RUI_CONSOLE_GBA_PROFILE_H
#define RUI_CONSOLE_GBA_PROFILE_H

#include "launcher_system_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// ---- pad vocabulary (rebind page) ---------------------------------------------
// The real GBA input set: 10 inputs (D-pad, A, B, L, R, Start, Select) — no
// X/Y, no sticks, no pad modes. `code` is the button's own index (0..9): the
// rebind page and bind persistence address buttons by this spec index.
static const ButtonDef kGbaPadButtons[] = {
    { "Up", 0 }, { "Down", 1 }, { "Left", 2 }, { "Right", 3 },
    { "A", 4 }, { "B", 5 },
    { "L", 6 }, { "R", 7 },
    { "Start", 8 }, { "Select", 9 },
};
#define LNG_GBA_PAD_BUTTON_COUNT ((int)(sizeof(kGbaPadButtons) / sizeof(kGbaPadButtons[0])))

// Rebind-spec index -> keybinds.c button index (generic PlayerBinds store:
// a,b,x,y,l,r,start,select,up,down,left,right,l2,r2,l3,r3). GBA persists
// through the generic store (unlike PSX's native bridge) — every GBA input
// exists in that vocabulary, so the game runtime and this launcher read the
// same keybinds.ini. Consumed by launcher_binds.c's active_kb_index().
static const int kGbaKbIndex[LNG_GBA_PAD_BUTTON_COUNT] = {
    /* UP    */ 8, /* DOWN  */ 9, /* LEFT  */ 10, /* RIGHT */ 11,
    /* A     */ 0, /* B     */ 1,
    /* L     */ 4, /* R     */ 5,
    /* START */ 6, /* SELECT*/ 7,
};

// ---- panel composition --------------------------------------------------------
// Dashboard stays common (game + controller; the save row folds into the GAME
// card like SNES — one .sav per cartridge, no slot grid). Settings adds the
// "system" panel: GBA needs a BIOS image (LLE by default; the panel's BIOS
// path picker replaces the runtime's blocking Win32 file dialog).
// "solar" composes only for a cartridge that actually has the photodiode
// (avail_solar gates on GameInfo.has_solar_sensor), so listing it here costs
// nothing for the other GBA titles.
static const char* const kPanelsSettingsGba[] = { "video", "audio", "system",
                                                  "solar", "hotkeys", NULL };

// ---- screen-model vocabulary ----------------------------------------------------
// Mirrors the gbarecomp runtime's screen filters (host_window GBARECOMP_SCREEN
// / game.toml [video].screen: raw|unlit|frontlit|backlit|classic) by index.
static const char* const kGbaScreenKindNames[] = {
    "Raw", "Unlit", "Frontlit", "Backlit", "Classic"
};
#define LNG_GBA_SCREEN_KIND_COUNT \
    ((int)(sizeof(kGbaScreenKindNames) / sizeof(kGbaScreenKindNames[0])))

// ---- ROM file-picker filter -----------------------------------------------------
static const char* const kGbaRomPatterns[] = { "*.gba", "*.agb", "*.bin" };
#define LNG_GBA_ROM_PATTERN_COUNT \
    ((int)(sizeof(kGbaRomPatterns) / sizeof(kGbaRomPatterns[0])))

// ---- SystemProfile row ----------------------------------------------------------
static const SystemProfile kSystemProfileGba = {
    /* id       */ "gba",
    /* platform */ "GAME BOY ADVANCE",
    /* theme    */ "gba",       // indigo LCD theme, no CRT scanlines
    /* rom_noun */ "ROM",
    /* controller */ {
        kGbaPadButtons, LNG_GBA_PAD_BUTTON_COUNT,
        "pad_gba.tga", NULL, NULL,     // handheld art; no analog/digital pair
        /* max_players */ 1, /* has_pad_mode */ 0, /* link netplay is lobby-only */
    },
    // One battery save per cartridge: the runtime presents EEPROM/flash/SRAM
    // uniformly as a single .sav next to the ROM (or game.toml [save].path).
    // SAVE_SRAM = the compact save row folded into the GAME card, shown for
    // games that pass sram_path (all of them; the runtime always saves).
    /* save */    { SAVE_SRAM, 1, NULL },
    /* video */   {
        /*window_scale*/1, /*fullscreen*/1, /*linear_filter*/1, /*widescreen*/1,
        /*renderer*/0, /*supersampling*/0, /*screen_kind*/1, /*frame_interp*/0, /*aspect*/0,
        /*texture_filter*/0, /*antialiasing*/0, /*spu_hq*/0, /*skip_fmv*/0, /*turbo_loads*/0,
        /*bios*/1, /*deadzone*/0,
    },
    /* verify */  { 0, NULL },    // rom-hash mode (CRC32/SHA-256 pin, like SNES carts)
    // GBA's hotkey catalog: everything except LNG_HK_PAUSE_DIMMED (an
    // SNES-engine-only attract-loop affordance), LNG_HK_TOGGLE_RENDERER
    // (gbarecomp has one renderer), and LNG_HK_RESET (gbarecomp has no
    // in-process reset; relaunching the exe is the reset). The window-resize
    // pair stays — GBA windows are integer-scaled like SNES.
    /* hotkeys_mask */ (uint32_t)(LNG_HOTKEYS_ALL &
                                   ~(1u << LNG_HK_PAUSE_DIMMED) &
                                   ~(1u << LNG_HK_TOGGLE_RENDERER) &
                                   ~(1u << LNG_HK_RESET)),
    /* panels_dashboard  */ kPanelsDashboardCommon,
    /* panels_settings   */ kPanelsSettingsGba,
    /* panels_controller */ kPanelsControllerCommon,
    /* screen_kind_names */ kGbaScreenKindNames,
    /* screen_kind_count */ LNG_GBA_SCREEN_KIND_COUNT,
    /* rom_filter        */ { kGbaRomPatterns, LNG_GBA_ROM_PATTERN_COUNT,
                              "Game Boy Advance ROM (.gba)" },
};

// ---- name aliases + ABI capability defaults -------------------------------------
static inline int launcher_console_is_gba(const char* name) {
    return lps_streq_ci(name, "gba") || lps_streq_ci(name, "gameboyadvance");
}

// The "gba" row of launcher_profile_apply(): system identity + capability
// defaults onto the C ABI GameInfo. Per-game fields (name, hashes, sram_path,
// widescreen_supported for titles with an extended-view build) are set by the
// host AFTER this.
static inline void launcher_profile_apply_gba(RecompLauncherCGameInfo* gi) {
    gi->theme    = "gba";              // indigo LCD theme, no CRT scanlines
    gi->platform = "GAME BOY ADVANCE";
    gi->rom_noun = "ROM";
    gi->num_players = 1;               // one pad card; LAN lobby seats via netplay callbacks
    // GBA settings surface: integer window scale + linear filter (base rows),
    // LCD screen-model cycle, fullscreen-on-launch, and the BIOS path picker
    // (gbarecomp is LLE-BIOS by default — a real BIOS image is required).
    gi->has_screen_kind       = 1;
    gi->has_bios              = 1;
    // widescreen_supported stays 0: per-game opt-in (e.g. Mega Man Zero's
    // extended view); most titles render the stock 240x160.
}

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_GBA_PROFILE_H
