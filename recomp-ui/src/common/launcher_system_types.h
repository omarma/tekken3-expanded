// launcher_system_types.h — the SystemProfile TYPE and its module specs.
//
// Concrete C shapes for the "inheritance" half of the architecture (see
// docs/ARCHITECTURE.md): each module (Controller/Save/Video/Verify) has a
// universal BASE behavior implemented once in the panel `draw()` functions,
// specialized per system by a small data SPEC held in a SystemProfile row.
// A SystemProfile also carries the "composition" half: the three panel-id
// arrays that tell each view (dashboard/settings/controller) WHICH panels
// this console gets, in slot order.
//
// This header is the CONSOLE-AGNOSTIC part only: the types, the shared panel
// composition arrays, and the string matcher. The per-console ROWS live in
// src/consoles/<id>/<id>_profile.h (one unit per console: pad vocabulary +
// profile row + ABI capability defaults); src/launcher_system.h aggregates
// them and provides the by-id / inference lookups. Adding a system = adding
// one directory under src/consoles/ and registering it in the aggregator.
//
// Pure data + lookup: no UI toolkit dependency, safe to include from both
// the C model and the C++ ImGui backend.

#ifndef LAUNCHER_NG_SYSTEM_TYPES_H
#define LAUNCHER_NG_SYSTEM_TYPES_H

#include "recomp_launcher.h"
#include "launcher_model.h"   // LauncherModel (SaveProbeFn/VerifyProbeFn take a pointer to it)

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

// ---- Controller module -------------------------------------------------------
typedef struct { const char* label; int code; } ButtonDef;

// A named pad MODE a console offers. `mode` is the value stored in
// RecompLauncherCSettings.pad_mode[player]; `label` is the selector segment
// text; `button_count` is how many LEADING entries of ControllerSpec.buttons[]
// the rebind page shows in that mode (a Genesis 3-button pad has no X/Y/Z/Mode
// rows). A profile that leaves ControllerSpec.modes NULL keeps the legacy
// PSX-shaped selector (Analog/D-Pad) with the
// full button set in every mode — PSX itself is untouched by this concept.
typedef struct { int mode; const char* label; int button_count; } PadModeDef;

typedef struct {
    const ButtonDef* buttons; int button_count;   // per-system base set (rebind page)
    const char* image;                             // base pad art (fallback / no pad-mode)
    const char* image_analog, *image_digital;       // optional mode-swap pair (PSX-style)
    int  max_players;                              // 1..RECOMP_LAUNCHER_MAX_PLAYERS
    int  has_pad_mode;                              // analog/digital selector offered
    // Alternate bind slots per input the console's bind store keeps (N64's
    // input.cfg format stores 2 — e.g. Z on both shoulder triggers). 0 (the
    // trailing zero-fill of every older positional initializer) reads as 1.
    int  binds_per_input;
    // ---- appended additively (older positional initializers zero-fill) ----
    const PadModeDef* modes; int mode_count;       // custom mode list (NULL => legacy PSX set)
    int  has_pad_binds;                            // rebind page adds a GAMEPAD bind column
} ControllerSpec;

// ---- Save module --------------------------------------------------------------
typedef enum { SAVE_NONE = 0, SAVE_SRAM, SAVE_MEMCARD } SaveKind;
typedef bool (*SaveProbeFn)(const LauncherModel* m, int slot);   // unimplemented hook (NULL today)
typedef struct { SaveKind kind; int slots; SaveProbeFn probe; } SaveSpec;

// ---- Video / Display module ----------------------------------------------------
// Documents each system's DEFAULT capability template. The model's own
// has_*/aspect_mask/widescreen_supported fields (sourced straight from the C
// ABI GameInfo, unchanged by this refactor) remain the single source of truth
// panels actually gate on — this spec is the authored "shape" for the system,
// kept here so a system row is legible as ONE unit.
typedef struct {
    int window_scale, fullscreen;                  // base (every system)
    int linear_filter, widescreen;                  // SNES-ish legacy surface
    int renderer, supersampling, screen_kind, frame_interp, aspect, texture_filter,
        antialiasing, spu_hq, skip_fmv, turbo_loads, bios, deadzone; // PSX-ish deep surface
    // appended additively (older positional initializers zero-fill):
    int widescreen_cells;   // Genesis-ish: "extra cells per side" stepper shown while widescreen is on
} VideoSpec;

// ---- Verify module --------------------------------------------------------------
// Host-provided disc-verdict probe (mode==1 systems, e.g. PSX): given the
// model (rom_full/rom_present etc.), fill `out` with the real serial/region/
// ISO-header/verdict facts and return true. Return false (or pass probe ==
// NULL, the default today) to have launcher_model_set_rom() synthesize a
// placeholder verdict from available facts instead, so the disc-verdict UI
// always has something real to render even before a host wires this up.
typedef bool (*VerifyProbeFn)(const LauncherModel* m, VerifyResult* out);
typedef struct { int mode; /* 0 rom-hash, 1 disc-verdict */ VerifyProbeFn probe; } VerifySpec;

// ---- Hotkeys module: a bitmask over LngHotkey (launcher_model.h) --------------
// The first 11 entries are the universal catalog. Capability-specific rows
// (currently the three solar controls) are added by the panel at draw time, so
// SNES and other non-solar systems keep their byte-identical legacy catalog.
#define LNG_HOTKEYS_ALL 0x7FFu
#define LNG_HOTKEYS_SOLAR ((uint32_t)((1u << LNG_HK_SOLAR_BRIGHTER) | \
                                      (1u << LNG_HK_SOLAR_DIMMER) | \
                                      (1u << LNG_HK_SOLAR_LIVE)))

// ---- ROM file-picker filter --------------------------------------------------
// The native "Change ROM" dialog's extension filter, per console — so a GBA
// game offers *.gba, a PSX game *.cue/*.bin, never a hardcoded SNES set.
// patterns is a tinyfiledialogs glob list ("*.gba"); desc is the filter label.
typedef struct {
    const char* const* patterns; int pattern_count;
    const char* desc;                              // e.g. "Game Boy Advance ROM (.gba)"
} RomFilterSpec;

typedef struct SystemProfile {
    const char* id, *platform, *theme, *rom_noun;
    ControllerSpec controller;   SaveSpec save;   VideoSpec video;   VerifySpec verify;
    uint32_t hotkeys_mask;                         // universal hotkeys opted into
    const char* const* panels_dashboard;           // composition (panel ids, in slot order)
    const char* const* panels_settings;
    const char* const* panels_controller;
    // Screen-model vocabulary for the "Screen model" cycle (video.screen_kind
    // capability). NULL/0 => the legacy 4-entry PSX-era set (Raw/CRT/
    // Composite/Trinitron, launcher_model.c) — existing rows are positional
    // initializers, so trailing zero-init keeps them on the legacy set.
    const char* const* screen_kind_names;
    int                screen_kind_count;
    // "Change ROM" native-dialog filter (per console). All-zero => the
    // built-in SNES default (back-compat); every built-out console sets it.
    RomFilterSpec rom_filter;
    // Renderer-toggle vocabulary for the has_renderer control: two labels
    // indexed by Settings.renderer (0/1). NULL => the legacy PSX-era pair
    // ("Software"/"OpenGL"). NES uses {"Accelerated","Software"} — its
    // renderer value means SDL-accelerated vs SDL-software output.
    const char* const* renderer_labels;
    // 1 => hide the Sample-rate cycle in the AUDIO panel (the nesrecomp
    // runner has no audio-frequency setting; only Volume). 0 = legacy (show).
    int hide_audio_freq;
    // Per-console brand mark drawn in the header (top-left, next to the game
    // title). NULL => the shared default "brand_mark.tga"; a console sets this
    // to ship its own logo (NES "brand_nes.tga", Genesis "brand_genesis.tga").
    // The N64 profile sets this to an EMPTY STRING "" to draw NO corner emblem
    // (header title starts flush-left). Appended so existing positional
    // profile rows zero-fill it.
    const char* brand;
    // Optional platform WORDMARK image (assets/img/<file>) rendered in the
    // header in place of the plain `platform` TEXT when the file is present.
    // NULL => always text. The file is NOT shipped by recomp-ui (a console's
    // wordmark may be a third-party trademark); an absent file falls back to
    // the text, so this is inert unless a host drops the asset in.
    const char* wordmark_image;
} SystemProfile;                                    // ONE ROW PER CONSOLE

// ---- shared panel composition arrays (NULL-terminated) --------------------------
// Per-console arrays that DIFFER from these live in that console's profile
// header (e.g. kPanelsDashboardPsx adds the "save" memcard panel).
static const char* const kPanelsDashboardCommon[] = { "game", "controller", NULL };
static const char* const kPanelsSettingsStub[]  = { "video", "audio", "hotkeys", NULL };
static const char* const kPanelsControllerCommon[] = { "controller_config", NULL };

// Case-insensitive exact-string match, shared by every console's name-alias
// matcher and the aggregator lookups (launcher_system.h).
static inline int lps_streq_ci(const char* a, const char* b) {
    if (!a || !b) return 0;
    for (; *a && *b; ++a, ++b) {
        char ca = (*a >= 'A' && *a <= 'Z') ? (char)(*a + 32) : *a;
        char cb = (*b >= 'A' && *b <= 'Z') ? (char)(*b + 32) : *b;
        if (ca != cb) return 0;
    }
    return *a == 0 && *b == 0;
}

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_SYSTEM_TYPES_H
