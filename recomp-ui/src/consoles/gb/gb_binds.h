// consoles/gb/gb_binds.h — the Game Boy-native bind persistence bridge.
//
// gb-recompiled's runtime drives input from g_keyboard_bindings, persisted in
// runtime_prefs.ini as FLAT keys (runtime/src/platform_sdl.cpp):
//
//     keyboard.<action>.<slot> = key:<SDL_Scancode as decimal int>
//
// where <action> is the engine's input_action_config_name() spelling
// (up/down/left/right/a/b/select/start/…) and <slot> is 0 (primary) or 1
// (secondary). The launcher rebinds the PRIMARY slot (0); the secondary
// (WASD / J / K, etc.) is left untouched. NOTE: the older keybinds.ini
// [controls] file (runtime/src/keybinds.c) is vestigial — it is initialized
// but never consulted for input — so this bridge writes runtime_prefs.ini,
// the file that actually drives the game.
//
// Like PSX and Genesis, the Game Boy family gets a native bridge (rather than
// the generic keybinds.c store) because gb-recompiled's key format is its own.
// Single player (the Game Boy is a one-player handheld). Button indices are
// the kGbPadButtons rebind-spec order (gb_profile.h: Up/Down/Left/Right/A/B/
// Start/Select); the bridge maps each to its <action> name. All writes are
// SURGICAL: only the eight `keyboard.<btn>.0` lines are replaced/inserted;
// every other byte of runtime_prefs.ini (audio.*, game.*, the secondary and
// hotkey keyboard.* lines, controller.*) is preserved. The `path` every call
// takes is the resolved runtime_prefs.ini path (launcher_binds.c owns path
// resolution; the seam points it at the exe-anchored runtime_prefs.ini).

#ifndef RUI_CONSOLE_GB_BINDS_H
#define RUI_CONSOLE_GB_BINDS_H

#ifdef __cplusplus
extern "C" {
#endif

// Seed the in-memory store with gb-recompiled's set_default_input_bindings()
// primary-slot defaults, then overlay whatever keyboard.<btn>.0 lines exist in
// `path`. Does NOT write the file (an absent file means the game's own
// defaults already agree; the first rebind creates the lines).
void rui_gb_binds_init(const char* path);

// Current primary keyboard binding (SDL_Scancode as int; 0 = unbound) for
// rebind-spec button b (0..7). Auto-initializes from `path` on first use.
int  rui_gb_binds_get(const char* path, int b);

// Rebind + persist (surgical runtime_prefs.ini upsert of the eight
// keyboard.<btn>.0 lines, preserving every other line).
void rui_gb_binds_set(const char* path, int b, int scancode);

// Reset all buttons to gb-recompiled's primary-slot defaults + persist.
void rui_gb_binds_reset(const char* path);

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_GB_BINDS_H
