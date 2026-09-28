// launcher_input.h — live gamepad enumeration for the launcher (shared core).
//
// Polls SDL for currently-connected gamepads every frame, so a controller
// turned on AFTER the launcher opens shows up without a relaunch (and one
// turned off disappears). Game-agnostic; both backends use it to populate the
// per-player input-source dropdown with real device names.

#ifndef LAUNCHER_NG_INPUT_H
#define LAUNCHER_NG_INPUT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LNG_MAX_PADS 8

typedef struct {
    uint32_t id;        // SDL_JoystickID (stable while connected)
    char     name[64];  // e.g. "PS5 Controller", "Xbox Series Controller"
    char     guid[40];  // SDL_JoystickGetGUIDString (persists across reconnects)
    int      has_gyro;  // bool: angular-rate sensor opened and enabled
    float    gyro_z;    // radians/second around the controller face normal
} LauncherPad;

// Fill `out` (capacity `max`) with the gamepads SDL currently sees. Returns the
// count. `enable_gyro` is a game/build capability: when 0, sensors are neither
// enabled nor read and the gyro fields remain zero.
int launcher_input_poll(LauncherPad* out, int max, int enable_gyro);

// 1 if every button is up and every axis is near rest on the open pad with
// this SDL instance id. Used by bind capture to wait for a full release before
// accepting the next mapping (sticks otherwise re-fire on every axis tick).
int launcher_input_gamepad_at_rest(uint32_t id);

// Close controller handles retained for live input/sensor polling. Call before
// the launcher tears down SDL.
void launcher_input_shutdown(void);

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_INPUT_H
