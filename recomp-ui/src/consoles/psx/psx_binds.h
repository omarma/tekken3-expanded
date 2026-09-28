// consoles/psx/psx_binds.h — the PSX-native keybind persistence bridge.
//
// psxrecomp's runtime (runtime/include/psx_keybinds.h + .c) owns its OWN
// keyboard-bind format: an INI with [player1]..[player5] sections and 24
// named keys (up/down/left/right/cross/circle/square/triangle/l1/r1/l2/r2/
// l3/r3/start/select/ls_*/rs_*), storing SDL *scancode* names exactly like
// keybinds.c does. It is NOT the same format as keybinds.c's generic
// PlayerBinds — routing PSX's 24 buttons through that 16-slot generic format
// silently discarded the 8 stick-direction binds. This bridge fixes that:
// for a PSX SystemProfile, launcher_binds.c routes persistence through this
// native 24-scancode store to the SAME "keybinds.ini" the runtime reads.
//
// Button indices are the kPsxPadButtons rebind-spec order (psx_profile.h),
// players are 0-based (0 = P1). Every slot resets to the same default map.
// The `path` every call takes is the resolved keybinds.ini path.

#ifndef RUI_CONSOLE_PSX_BINDS_H
#define RUI_CONSOLE_PSX_BINDS_H

#ifdef __cplusplus
extern "C" {
#endif

// Load existing keybinds.ini if present (whichever process wrote it last —
// launcher or game, same format), else seed defaults and write it so the
// game's first run sees identical bindings to what the launcher displays.
// A file matching ZERO native-only keys is foreign-format (e.g. a stale
// generic keybinds.ini written pre-bridge) — defaults are re-seeded and the
// file rewritten cleanly rather than half-applying a foreign blend.
void rui_psx_binds_init(const char* path);

// Current binding (SDL_Scancode as int) for player (0..LNG_MAX_PLAYERS-1),
// rebind-spec button b (0..LNG_PSX_PAD_BUTTON_COUNT-1). Auto-initializes
// from `path` on first use.
int rui_psx_binds_get(const char* path, int player, int b);

// Rebind + persist.
void rui_psx_binds_set(const char* path, int player, int b, int scancode);

// Slot-aware variants: slot 0 is the primary bind, slot 1 the alternate.
// Either slot asserts the input at runtime. Mouse buttons are representable
// as pseudo-scancodes (Mouse1..Mouse5), matching psx_keybinds.c.
int  rui_psx_binds_get_slot(const char* path, int player, int b, int slot);
void rui_psx_binds_set_slot(const char* path, int player, int b, int slot, int scancode);

// Reset one player to the shared default keyboard map + persist.
void rui_psx_binds_reset(const char* path, int player);

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_PSX_BINDS_H
