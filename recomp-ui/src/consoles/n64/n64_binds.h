// consoles/n64/n64_binds.h — the N64-native input.cfg persistence bridge.
//
// The N64 runners (PokemonStadiumRecomp's src/main/input_bindings.cpp is the
// canonical implementation) own their OWN bind format: a flat `input.cfg` of
// `<dev>.<INPUT>.<idx>=<field>` lines, where dev is `kb` (keyboard) or `pad`
// (controller — shared by ALL gamepads, a per-device-TYPE table, not
// per-port), INPUT is the stable N64 input key (A, C_UP, STICK_LEFT, ...),
// idx is one of TWO alternate bind slots per input, and field encodes what
// the bind refers to:
//     key:<scancode>  button:<n>  axis+:<n>  axis-:<n>
//     joybtn:<n>  joyaxis+:<n>  joyaxis-:<n>  none
// (the joy* raw forms cover pads whose SDL_GameController mapping can't
// express an input — PSR issue #15, the 8BitDo 64's C-buttons).
//
// This bridge replicates that format and PSR's built-in defaults byte-for-
// byte, so whichever process (launcher or game) writes input.cfg first, the
// other reads exactly what it expects — same contract as the PSX bridge.
//
// Button indices are the kN64PadButtons rebind-spec order (n64_profile.h),
// which IS PSR's N64Input enum order. Devices: 0 = keyboard, 1 = controller.
// The `path` every call takes is the resolved bind-file path
// (launcher_binds.c owns path resolution; N64 defaults to "input.cfg").

#ifndef RUI_CONSOLE_N64_BINDS_H
#define RUI_CONSOLE_N64_BINDS_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Field types — numeric values match PSR's FieldType enum exactly.
enum {
    RUI_N64_FIELD_NONE        = 0,
    RUI_N64_FIELD_KEY         = 1,   // id = SDL_Scancode
    RUI_N64_FIELD_PAD_BUTTON  = 2,   // id = SDL_GameControllerButton
    RUI_N64_FIELD_PAD_AXIS_P  = 3,   // id = SDL_GameControllerAxis, active > +threshold
    RUI_N64_FIELD_PAD_AXIS_N  = 4,   // id = SDL_GameControllerAxis, active < -threshold
    RUI_N64_FIELD_JOY_BUTTON  = 5,   // id = raw SDL_Joystick button index
    RUI_N64_FIELD_JOY_AXIS_P  = 6,   // id = raw SDL_Joystick axis index
    RUI_N64_FIELD_JOY_AXIS_N  = 7,
};

#define RUI_N64_BINDS_PER_INPUT 2

// Load input.cfg if present (defaults as baseline, cfg lines override —
// PSR load() semantics, including "a bound idx 0 clears the stale default
// alt"), else keep pure defaults. Never writes the file on init: PSR's
// runtime seeds defaults itself when the file is absent, so an untouched
// setup stays untouched.
void rui_n64_binds_init(const char* path);

// Current binding for device (0 kb / 1 pad), rebind-spec button b
// (0..LNG_N64_PAD_BUTTON_COUNT-1), alternate slot (0..1). Auto-initializes
// from `path` on first use. Outputs a field type/id pair.
void rui_n64_binds_get(const char* path, int device, int b, int slot,
                       int* out_type, int* out_id);

// Rebind + persist (full-file rewrite, PSR save() format). Setting slot 0
// also clears slot 1's stale default, mirroring PSR's load-order contract.
void rui_n64_binds_set(const char* path, int device, int b, int slot,
                       int type, int id);

// Reset ONE device's table (the one the Configure page is showing) to PSR's
// built-in defaults + persist.
void rui_n64_binds_reset_device(const char* path, int device);

// Human display string for a field ("X", "LT", "R-Stick Up", "Btn 16",
// em dash for none) — PSR field_to_string() vocabulary.
void rui_n64_binds_label(int type, int id, char* out, size_t cap);

#ifdef __cplusplus
}
#endif

#endif // RUI_CONSOLE_N64_BINDS_H
