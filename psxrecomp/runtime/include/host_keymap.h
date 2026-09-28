#ifndef PSX_HOST_KEYMAP_H
#define PSX_HOST_KEYMAP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Host hotkeys from recomp-ui config.ini [KeyMap] (SDL key names + Ctrl+/Alt+/
 * Shift+ prefixes). VolumeUp / VolumeDown are honored by the runtime; missing
 * lines keep the historic keypad +/- defaults.
 */

typedef enum HostKeymapAction {
    HOST_KEYMAP_VOLUME_UP = 0,
    HOST_KEYMAP_VOLUME_DOWN,
    HOST_KEYMAP_ACTION_COUNT
} HostKeymapAction;

/* Load [KeyMap] from path (NULL => no file, apply defaults only). */
void host_keymap_load(const char *config_ini_path);

/* 1 if (keycode, mod) matches a binding for `action`. */
int host_keymap_match(HostKeymapAction action, int keycode, int mod);

#ifdef __cplusplus
}
#endif

#endif /* PSX_HOST_KEYMAP_H */
