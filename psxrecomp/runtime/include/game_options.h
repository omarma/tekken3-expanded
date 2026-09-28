/* game_options.h — persist in-RAM game config globals across launches.
 *
 * Some PS1 games (e.g. Tomba!) keep their OPTION-screen settings only in a RAM
 * global that re-initialises to defaults every boot, with no memory-card config
 * block — so the player must re-set them each launch (issue #5). This module
 * persists a game-declared set of those globals to a small state file next to
 * the runtime exe: it restores them shortly after boot (once the game's own
 * config-init has run) and writes them back whenever they change.
 *
 * The fields are declared per-game in game.toml ([persist_options]); the
 * addresses are guest RAM addresses (KUSEG 0x80xxxxxx) of the canonical config
 * globals (pinned via consumer RE / option-screen write capture). Generic: any
 * game can list its own. Runtime-only, no debug server, works in release.
 */
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Configure the persisted-options set. addrs/sizes/names/vmins/vmaxs have
 * `count` entries (size is 1 or 2 bytes per field); names[i] is the field key
 * written to the state file. vmins[i]/vmaxs[i] are the inclusive valid range for
 * RESTORE-time validation: a saved value outside [vmin,vmax] is rejected (the
 * game default is used) so a corrupt/stale file can't inject an out-of-range
 * value. Pass [INT32_MIN, INT32_MAX] for a field that needs no validation.
 * state_path is the absolute file to persist into. Copies what it needs; safe
 * to call once at startup. count==0 disables the feature. */
void game_options_configure(const char *state_path,
                            const uint32_t *addrs,
                            const uint8_t  *sizes,
                            const char *const *names,
                            const int32_t  *vmins,
                            const int32_t  *vmaxs,
                            int count);

/* Recompiler hook (called from generated code at each config global's boot-init
 * store): returns the persisted value for `addr` if one was loaded, else `val`
 * unchanged. This is what performs restore-at-init. */
int psx_game_option_store(uint32_t addr, int val);

/* Persist the current option globals to the state file. Registered via atexit,
 * so a clean exit saves whatever the player last chose in the OPTION screen. */
void game_options_save_now(void);

/* Diagnostics: write a JSON object describing the module state (configured
 * fields, whether the state file loaded, per-field loaded/current/released).
 * Returns bytes written. For the debug server only. */
int game_options_debug_json(char *out, int cap);

#ifdef __cplusplus
}
#endif
