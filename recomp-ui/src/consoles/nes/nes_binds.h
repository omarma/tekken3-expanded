// consoles/nes/nes_binds.h — the NES-native keybind persistence bridge.
//
// nesrecomp's runner (runner/src/keybinds.c, engine repo) owns its OWN
// keyboard-bind format: keybinds.ini with [player1]/[player2] sections and 8
// named keys (a/b/select/start/up/down/left/right, SDL scancode names), PLUS
// [zapper] (mouse/crosshair booleans) and [gamepad1]/[gamepad2] (controller
// button-mask bindings) sections the launcher must NOT destroy. Routing NES
// through the generic keybinds.c store would (a) rewrite the whole file in
// the SNES vocabulary, dropping those extra sections, and (b) seed SNES
// defaults (A=X/B=Z, P2 unbound) instead of the runner's NES defaults
// (A=Z/B=X, P2=K/L/W/S/A/D/...). Same root fix as the PSX bridge — a native
// per-console store — but persisted with SURGICAL per-key section writes
// (launcher_ini_kv_write, launcher_binds.h) so every other line of the
// runner's file survives, including comments and the zapper/gamepad sections.
//
// Button indices are the kNesPadButtons rebind-spec order (nes_profile.h),
// players are 0-based (0 = P1). The `path` every call takes is the resolved
// keybinds.ini path (launcher_binds.c owns path resolution).

#ifndef RUI_CONSOLE_NES_BINDS_H
#define RUI_CONSOLE_NES_BINDS_H

#ifdef __cplusplus
extern "C" {
#endif

// Load existing keybinds.ini if present (whichever process wrote it last —
// launcher or game, same format), else seed the runner's full defaults file
// (player sections + [zapper] + [gamepad1]/[gamepad2], the same content
// runner/src/keybinds.c's write_defaults generates) so the game's first run
// sees identical bindings to what the launcher displays. Unlike PSX there is
// no foreign-format detection: every NES key name is parsed identically by
// the runner itself, so whatever this reads is exactly what the game reads.
void rui_nes_binds_init(const char* path);

// Current binding (SDL_Scancode as int) for player (0..1), rebind-spec
// button b (0..LNG_NES_PAD_BUTTON_COUNT-1). Auto-initializes from `path`
// on first use.
int rui_nes_binds_get(const char* path, int player, int b);

// Rebind + persist (surgical single-key write into [player<N>]).
void rui_nes_binds_set(const char* path, int player, int b, int scancode);

// Reset one player to the runner's defaults + persist.
void rui_nes_binds_reset(const char* path, int player);

// Zapper switches ([zapper] mouse/crosshair; runner defaults: both ON).
// _get auto-initializes from `path`; _set persists surgically.
void rui_nes_zapper_get(const char* path, int* mouse_enabled, int* crosshair);
void rui_nes_zapper_set(const char* path, int mouse_enabled, int crosshair);

/* Optional Voxel/3D camera bindings ([camera]). These are global presentation
 * controls, not NES controller bits, and are shown only while an enabled mod
 * feature advertises camera_controls. Indices are LNG_CAMERA_* from
 * launcher_model.h. Missing keys are seeded surgically with numpad defaults. */
int  rui_nes_camera_bind_get(const char* path, int action);
void rui_nes_camera_bind_set(const char* path, int action, int scancode);
void rui_nes_camera_bind_reset(const char* path);

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_NES_BINDS_H
