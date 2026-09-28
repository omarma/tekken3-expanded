// consoles/psx/psx_pad_binds.h — PSX gamepad (SDL) bind persistence bridge.
//
// psxrecomp's runtime maps DualShock buttons from input.ini ([mapping] and
// optional per-device [mapping.<guid>] sections). This bridge is the launcher's
// writer/reader for that file so the Configure page's Gamepad Bindings panel
// can remap any connected SDL gamepad, keyed by GUID.
//
// Per-GUID profile (identity = GUID; UI label = human name):
//   [gamepads]              guid = display name
//   [mapping.<guid>]        button sources + deadzone (percent) + name_custom
//
// Default display name is the SDL driver name; Rename Gamepad sets a custom
// name that wins over the driver name until cleared.

#ifndef RUI_CONSOLE_PSX_PAD_BINDS_H
#define RUI_CONSOLE_PSX_PAD_BINDS_H

#ifdef __cplusplus
extern "C" {
#endif

#define RUI_PSX_PAD_MAX_KNOWN 16
#define RUI_PSX_PAD_DEFAULT_DEADZONE_PCT 10

// Load input.ini (or seed defaults). `path` is the resolved input.ini path.
void rui_psx_pad_binds_init(const char* path);

// Fill `out` (cap bytes) with the display label for player GUID `guid`'s
// button `b` (0..LNG_PSX_PAD_BUTTON_COUNT-1). Falls back to global [mapping]
// then built-in defaults when a GUID section is absent. Does NOT create a
// GUID section (Save Profile / remember / Play do that).
void rui_psx_pad_binds_label(const char* path, const char* guid, int b,
                             char* out, int cap);

// Rebind button `b` for `guid`. kind: 0 none, 1 button, 2 axis.
void rui_psx_pad_binds_set(const char* path, const char* guid, int b,
                           int kind, int code, int axis_dir);

// Reset one GUID's mapping sources to built-in defaults (keeps name/deadzone).
void rui_psx_pad_binds_reset(const char* path, const char* guid);

// Ensure a GUID profile exists. `name` is the driver (or current) display name
// when not custom; does not clear an existing custom name. `deadzone_pct` < 0
// leaves the stored deadzone unchanged (default 10 on first create).
void rui_psx_pad_binds_remember(const char* path, const char* guid,
                                const char* name, int deadzone_pct);

// Full profile save: name, custom flag, deadzone, and current mappings on disk.
void rui_psx_pad_binds_save_profile(const char* path, const char* guid,
                                    const char* name, int name_custom,
                                    int deadzone_pct);

// Set a user-chosen display name (marks name_custom).
void rui_psx_pad_binds_rename(const char* path, const char* guid,
                              const char* name);

// Remove a GUID's mapping + registry entry from input.ini.
void rui_psx_pad_binds_delete(const char* path, const char* guid);

int  rui_psx_pad_binds_known_count(const char* path);
int  rui_psx_pad_binds_known_at(const char* path, int index,
                                char* guid, int guid_cap,
                                char* name, int name_cap);

void rui_psx_pad_binds_name(const char* path, const char* guid,
                            char* out, int cap);
int  rui_psx_pad_binds_name_is_custom(const char* path, const char* guid);

// Deadzone percent (0..100) for GUID; default RUI_PSX_PAD_DEFAULT_DEADZONE_PCT.
int  rui_psx_pad_binds_deadzone(const char* path, const char* guid);

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_PSX_PAD_BINDS_H
