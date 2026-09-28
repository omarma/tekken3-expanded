// consoles/genesis/genesis_binds.h — the Genesis-native bind persistence bridge.
//
// segagenesisrecomp's runtime owns its OWN bind format: settings.ini sections
// [input.p1]/[input.p2] (runner/app_config.c), with per-logical-button lines
//
//     key.<Name> = <SDL_Scancode as a decimal int>      e.g.  key.A = 29
//     pad.<Name> = button:N | axis:N:+ | axis:N:- | none e.g.  pad.A = button:1
//
// where <Name> is the engine's input_button_name() spelling (Up/Down/Left/
// Right/A/B/C/Start/X/Y/Z/Mode — exact case; app_config.c matches by strcmp).
// Unlike every other console, a Genesis bind is a PAIR: a keyboard scancode
// AND a gamepad button-or-axis binding per logical button (the engine's
// PlayerInput.key[] + PlayerInput.pad[]) — which is why this bridge has
// set_key/set_pad instead of PSX's single scancode setter, and why the
// launcher's rebind page grows a GAMEPAD column for this console.
//
// The same settings.ini also carries [video]/[audio]/[launcher] sections and
// per-player device/pad_type/deadzone lines. Those are NOT this bridge's to
// write — they flow through the RecompLauncherCSettings ABI and the host's
// own app_config_save(). All writes here are SURGICAL: only key.*/pad.* lines
// inside [input.pN] are replaced/inserted; every other byte of the file is
// preserved. (The host re-loads settings.ini after the launcher returns, so
// rebinds reach its live input map before its own save rewrites the file.)
//
// Button indices are the kGenesisPadButtons rebind-spec order
// (genesis_profile.h) == the engine's GenesisButton enum order, players are
// 0-based. The `path` every call takes is the resolved settings.ini path
// (launcher_binds.c owns path resolution; the Genesis default is
// "settings.ini", NOT "keybinds.ini").

#ifndef RUI_CONSOLE_GENESIS_BINDS_H
#define RUI_CONSOLE_GENESIS_BINDS_H

#ifdef __cplusplus
extern "C" {
#endif

// Gamepad bind kinds — values mirror the engine's GamepadBindKind exactly
// (runner/input_map.h: GP_BIND_NONE/GP_BIND_BUTTON/GP_BIND_AXIS).
#define RUI_GEN_BIND_NONE   0
#define RUI_GEN_BIND_BUTTON 1
#define RUI_GEN_BIND_AXIS   2

// Seed the in-memory store with the engine's input_map_init_defaults()
// mapping, then overlay whatever [input.pN] key.*/pad.* lines exist in
// `path`. Does NOT create or rewrite the file: the defaults here mirror the
// engine's byte-for-byte, so an absent file means both sides already agree.
void rui_genesis_binds_init(const char* path);

// Current keyboard binding (SDL_Scancode as int; 0 = unbound) for player
// (0..1), rebind-spec button b. Auto-initializes from `path` on first use.
int  rui_genesis_binds_get_key(const char* path, int player, int b);

// Current gamepad binding for player/button. Any out pointer may be NULL.
void rui_genesis_binds_get_pad(const char* path, int player, int b,
                               int* kind, int* code, int* axis_dir);

// Rebind + persist (surgical settings.ini upsert of that player's lines).
void rui_genesis_binds_set_key(const char* path, int player, int b, int scancode);
void rui_genesis_binds_set_pad(const char* path, int player, int b,
                               int kind, int code, int axis_dir);

// Reset one player to the engine defaults + persist.
void rui_genesis_binds_reset(const char* path, int player);

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_GENESIS_BINDS_H
