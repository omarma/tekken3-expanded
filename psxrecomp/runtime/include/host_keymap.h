#ifndef PSX_HOST_KEYMAP_H
#define PSX_HOST_KEYMAP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Host hotkeys from recomp-ui config.ini [KeyMap] (SDL key names + Ctrl+/Alt+/
 * Shift+/Cmd+ prefixes). Fullscreen, Pause, Turbo (fast-forward, held),
 * DisplayPerf (FPS readout) and VolumeUp / VolumeDown are honored by the
 * runtime; missing lines keep the historic defaults. Reset and
 * ToggleRenderer are not implemented by the runtime.
 */

typedef enum HostKeymapAction {
    HOST_KEYMAP_VOLUME_UP = 0,
    HOST_KEYMAP_VOLUME_DOWN,
    HOST_KEYMAP_FULLSCREEN,
    HOST_KEYMAP_PAUSE,
    HOST_KEYMAP_TURBO,
    HOST_KEYMAP_DISPLAY_PERF,
    HOST_KEYMAP_ACTION_COUNT
} HostKeymapAction;

/* Load [KeyMap] from path (NULL => no file, apply defaults only). */
void host_keymap_load(const char *config_ini_path);

/* 1 if (keycode, mod) matches a binding for `action`. */
int host_keymap_match(HostKeymapAction action, int keycode, int mod);

/* 1 while a key bound to `action` is physically held (modifiers included). */
int host_keymap_is_down(HostKeymapAction action);

#ifdef __cplusplus
}
#endif

#endif /* PSX_HOST_KEYMAP_H */
