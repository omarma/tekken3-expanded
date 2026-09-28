#pragma once
#include <stdint.h>
#include "launcher_platform.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Controller keybinds — INI-driven, generated next to the exe on first run.
 *
 * The base 12 slots match the SNES gamepad: A, B, X, Y, L, R, Start, Select,
 * and the d-pad — this is the layout every existing keybinds.ini on disk
 * already uses, and it stays byte-identical (same field order, same names,
 * same defaults) so old files keep loading unchanged.
 *
 * Four more slots (l2, r2, l3, r3) are appended after those 12 for systems
 * with a deeper button set than SNES (PSX: L2/R2 shoulders, L3/R3 stick
 * clicks). They're purely additive: an old 12-field keybinds.ini simply
 * leaves them unbound (SDL_SCANCODE_UNKNOWN) until saved again. Two players.
 * Each button maps to one SDL_Scancode.
 *
 * The button bitmask returned by recompui_keybinds_read_player() uses the same
 * 12-bit layout as SMW's $4218/$4219 joypad register pair, low byte first:
 *
 *   bit  0: R              (high byte, $4219 bit 4)
 *   bit  1: L              (high byte, $4219 bit 5)
 *   bit  2: X              (high byte, $4219 bit 6)
 *   bit  3: A              (high byte, $4219 bit 7)
 *   bit  4: Right          (low byte,  $4218 bit 0)
 *   bit  5: Left           (low byte,  $4218 bit 1)
 *   bit  6: Down           (low byte,  $4218 bit 2)
 *   bit  7: Up             (low byte,  $4218 bit 3)
 *   bit  8: Start          (low byte,  $4218 bit 4)
 *   bit  9: Select         (low byte,  $4218 bit 5)
 *   bit 10: Y              (low byte,  $4218 bit 6)
 *   bit 11: B              (low byte,  $4218 bit 7)
 *
 * Per-game runners that prefer a different layout can ignore the
 * bitmask and read individual buttons from PlayerBinds directly.
 */

typedef struct {
    SDL_Scancode a, b, x, y;
    SDL_Scancode l, r;
    SDL_Scancode start, select;
    SDL_Scancode up, down, left, right;
    SDL_Scancode l2, r2, l3, r3;   // deeper (PSX-style) shoulder/stick-click slots
} PlayerBinds;

typedef struct {
    PlayerBinds p1;
    PlayerBinds p2;
} KeyBinds;

/* Initialize keybinds from <exe_dir>/keybinds.ini. Generates a default
 * file if one doesn't exist. exe_path may be NULL or argv[0]. */
void recompui_keybinds_init(const char *exe_path);

/* Get current keybind configuration (read-only view). */
const KeyBinds *recompui_keybinds_get(void);

/* Build a 12-bit SNES button bitmask for the given player (1 or 2)
 * from the SDL keyboard state. See header docstring for bit layout. */
uint16_t recompui_keybinds_read_player(const uint8_t *keys, int player);

/* ── Rebind API (used by the launcher's Configure view) ──────────────────
 * Buttons are indexed 0..recompui_keybinds_button_count()-1 in the fixed order
 * a, b, x, y, l, r, start, select, up, down, left, right, l2, r2, l3, r3 —
 * the same order keybinds.ini writes them (the first 12 unchanged from
 * before the l2/r2/l3/r3 slots existed). Scancodes, NOT keycodes
 * (keybinds.ini stores SDL scancode names; config.ini's [KeyMap] hotkeys use
 * keycode names). */
int          recompui_keybinds_button_count(void);
const char  *recompui_keybinds_button_name(int button);              /* "a".."right" */
SDL_Scancode recompui_keybinds_get_button(int player, int button);   /* player 1|2 */
void         recompui_keybinds_set_button(int player, int button, SDL_Scancode sc);
/* Reset one player's bindings to the built-in defaults (P2 = all unbound). */
void         recompui_keybinds_reset_player(int player);
/* Persist the current bindings to keybinds.ini (same path recompui_keybinds_init
 * resolved; call recompui_keybinds_init first). */
void         recompui_keybinds_save(void);

#ifdef __cplusplus
}
#endif
