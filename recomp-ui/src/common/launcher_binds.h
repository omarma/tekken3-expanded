// launcher_binds.h — real input-binding persistence for the launcher.
//
// Bridges the launcher's Controller view to the engine's persisted files:
//   * player buttons  -> keybinds.ini  (SDL *scancode* names), via keybinds.c
//     -- EXCEPT the PSX SystemProfile, which persists through psxrecomp's own
//        24-button psx_keybinds.c format instead (see the PSX-native bridge
//        below launcher_binds_load's declaration) so PSX rebinds actually
//        reach the game. SNES (and every stub profile) is unaffected.
//   * system hotkeys   -> config.ini [KeyMap] (SDL *keycode* names), surgical edit
//
// This is the module that makes remaps actually STICK. Kept separate from the
// pure view-model so the model stays SDL/engine-free; the backend calls these
// on capture, and the capi/proto driver calls launcher_binds_load() at startup.

#ifndef LAUNCHER_NG_BINDS_H
#define LAUNCHER_NG_BINDS_H

#include "launcher_model.h"
#include "launcher_input.h"   // LauncherPad for prepare_psx_launch

#ifdef __cplusplus
extern "C" {
#endif

// Load current bindings from disk into the model for DISPLAY. Initializes
// keybinds.ini (generating defaults if absent) and reads config.ini [KeyMap].
// config_path may be NULL (=> "config.ini" in the exe dir). keybinds_path may
// be NULL (=> "keybinds.ini" in the exe dir); for a PSX SystemProfile this is
// the psx_keybinds.c-format file, for every other profile it is this
// launcher's own generic keybinds.c-format file (see recomp_launcher.h
// RecompLauncherCGameInfo.keybinds_path).
void launcher_binds_load(LauncherModel* m, const char* config_path, const char* keybinds_path);

// A player button was rebound to `scancode` (an SDL_Scancode). `b` is a
// generic index into the active profile's ControllerSpec.buttons[]
// (0..button_count-1), matching LauncherModel.capture_btn. Persist to
// keybinds.ini and refresh the model's display string.
void launcher_binds_set_button(LauncherModel* m, int player, int b, int scancode);

// N64-native store only: bind an arbitrary FIELD (type/id per
// consoles/n64/n64_binds.h — key, pad button, signed pad axis, raw joystick
// button/axis) into alternate slot 0/1 of the device table the player's
// current input source selects. No-op for every other profile.
void launcher_binds_set_field(LauncherModel* m, int player, int b, int slot,
                              int type, int id);

// Re-read every player's bind display strings from the active store. Cheap;
// the backend calls it when a Configure page's input source changes (the N64
// store is per-device-TYPE, so the shown table follows the source).
void launcher_binds_refresh(LauncherModel* m);

// Whether a capture for `player` (1-based) should listen for GAMEPAD events
// (pad buttons / axis throws / raw joystick fields) instead of the keyboard —
// true only for the N64 store when that player's source is a gamepad.
int launcher_binds_wants_pad_capture(const LauncherModel* m, int player);

// Generic GAMEPAD-bind kind codes for launcher_binds_set_pad_button()'s `kind`
// argument. Values mirror the engine's GamepadBindKind exactly (and equal the
// console-native genesis_binds.h RUI_GEN_BIND_* — both anchored to the engine,
// not to each other). The toolkit-agnostic backends use THESE so they need no
// console-specific header.
#define LNG_PADBIND_NONE   0
#define LNG_PADBIND_BUTTON 1   // `code` = SDL_GameControllerButton
#define LNG_PADBIND_AXIS   2   // `code` = SDL_GameControllerAxis, `axis_dir` = +1/-1

// A player button's GAMEPAD bind was captured (Genesis has_pad_binds, or PSX
// Gamepad Bindings panel keyed by the player's selected gamepad GUID).
// kind/code/axis_dir use the LNG_PADBIND_* encoding above. Persists through
// the console's native bridge and refreshes the model's pad_binds display
// string. No-op on consoles without a pad-bind store.
void launcher_binds_set_pad_button(LauncherModel* m, int player, int b,
                                   int kind, int code, int axis_dir);

// Reset one player's keyboard bindings to defaults and persist.
// (N64: resets the whole device TABLE the player's source selects.)
void launcher_binds_reset_player(LauncherModel* m, int player);

// ---- PSX gamepad registry (input.ini [gamepads] + [mapping.<guid>]) --------
// Save Profile: persist this player's selected gamepad name, custom-name flag,
// deadzone, and button mappings into input.ini.
void launcher_binds_save_psx_gamepad(LauncherModel* m, int player /*1-based*/);
// Rename the selected gamepad (custom display name for the GUID).
void launcher_binds_rename_psx_gamepad(LauncherModel* m, int player /*1-based*/,
                                       const char* name);
// Apply a GUID profile's saved deadzone (+ display name) onto the player slot.
void launcher_binds_apply_psx_pad_profile(LauncherModel* m, int player /*0-based*/);
// Remove that player's selected GUID from input.ini; caller should also switch
// the input source to Keyboard.
void launcher_binds_delete_psx_gamepad(LauncherModel* m, int player /*1-based*/);
// On LAUNCH: for every PSX player with a gamepad source, persist default (or
// current) mappings + registry name so the pad is remembered and works in-game
// even if the user never opened Map/Save. Resolves a bare "Gamepad" (no GUID)
// via `pads` when possible.
void launcher_binds_prepare_psx_launch(LauncherModel* m,
                                       const LauncherPad* pads, int pad_count);
// Hydrate player_pad_name from the registry when settings restored a GUID.
void launcher_binds_hydrate_psx_pad_names(LauncherModel* m);
// Per-frame: match player GUIDs to live pads (refresh name/id), learn names
// into the [gamepads] registry, and resolve a bare gamepad source (no GUID)
// onto a specific live/saved pad. Never leaves the label as generic "Gamepad"
// when a concrete device can be named.
void launcher_binds_sync_psx_pad_sources(LauncherModel* m,
                                         const LauncherPad* pads, int pad_count);
// Enumerate previously saved PSX gamepads (for the Input source dropdown).
int launcher_binds_psx_known_count(void);
int launcher_binds_psx_known_at(int index, char* guid, int guid_cap,
                                char* name, int name_cap);
// 1 if the GUID has a user-chosen display name (Rename Gamepad).
int launcher_binds_psx_name_is_custom(const char* guid);

// A system hotkey was rebound. `keycode` is an SDL_Keycode, `kmod` the SDL
// modifier mask; pass keycode==0 to UNBIND. Persists to config.ini [KeyMap]
// and refreshes the model's display string.
void launcher_binds_set_hotkey(LauncherModel* m, LngHotkey h, int keycode, int kmod);

// NES Zapper switches were toggled (mouse-as-gun / crosshair). Persists to
// keybinds.ini [zapper] via the NES-native bridge's surgical writer; the
// rest of the file is preserved. Meaningful only under an NES profile
// (the model gates the UI on GameInfo.zapper).
void launcher_binds_set_zapper(int mouse_enabled, int crosshair);

/* NES Voxel camera bindings ([camera] in keybinds.ini). The Controls page
 * calls these only when an enabled feature advertises camera_controls. */
void launcher_binds_refresh_camera(LauncherModel* m);
void launcher_binds_set_camera(LauncherModel* m, int action, int scancode);
void launcher_binds_reset_camera(LauncherModel* m);

// Surgically set "Key = value" inside [section] of `path`, preserving every
// other line (comments, blank lines, unrelated sections). Creates the file
// and/or section when absent. Shared by the config.ini [KeyMap] hotkey
// writer and console units whose native bind files carry sections the
// launcher doesn't own (consoles/nes/nes_binds.c).
void launcher_ini_kv_write(const char* path, const char* section,
                           const char* key, const char* value);

// The config.ini path hotkeys are written to (NULL => default). Set once at load.
extern const char* g_launcher_config_path;
// The keybinds file path player buttons are written to (NULL => default).
// Set once at load; see launcher_binds_load(). Format is chosen from the
// active profile, not from this path.
extern const char* g_launcher_keybinds_path;

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_BINDS_H
