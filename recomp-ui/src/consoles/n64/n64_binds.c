// n64_binds.c — N64-native input.cfg persistence bridge (see n64_binds.h).
//
// Replicates PokemonStadiumRecomp's src/main/input_bindings.cpp on-disk
// format, key vocabulary, and built-in defaults byte-for-byte, minus the
// runtime evaluation half (accumulate() stays in the game — the launcher
// only edits and persists).

#include "n64_binds.h"
#include "n64_profile.h"          // LNG_N64_PAD_BUTTON_COUNT (rebind-spec order)
#include "launcher_sdlcompat.h"   // SDL header (2 or 3)

#include <stdio.h>
#include <string.h>

typedef struct { int type; int id; } N64Field;

// input.cfg identifiers, in kN64PadButtons rebind-spec order (== PSR's
// N64Input enum order — the identity mapping n64_profile.h documents).
static const char* kN64InputKey[LNG_N64_PAD_BUTTON_COUNT] = {
    "A", "B", "Z", "START",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
    "L", "R",
    "C_UP", "C_DOWN", "C_LEFT", "C_RIGHT",
    "STICK_UP", "STICK_DOWN", "STICK_LEFT", "STICK_RIGHT",
};

// SDL2/SDL3 spell the gamepad button/axis constants differently; the NUMERIC
// values are identical (A/SOUTH=0 ... DPAD_RIGHT=14; LEFTX=0 ... TRIGGERRIGHT
// =5), and input.cfg stores the numbers, so pin them once here.
enum {
    RUI_GPB_A = 0, RUI_GPB_B = 1, RUI_GPB_X = 2, RUI_GPB_Y = 3,
    RUI_GPB_BACK = 4, RUI_GPB_GUIDE = 5, RUI_GPB_START = 6,
    RUI_GPB_LEFTSTICK = 7, RUI_GPB_RIGHTSTICK = 8,
    RUI_GPB_LEFTSHOULDER = 9, RUI_GPB_RIGHTSHOULDER = 10,
    RUI_GPB_DPAD_UP = 11, RUI_GPB_DPAD_DOWN = 12,
    RUI_GPB_DPAD_LEFT = 13, RUI_GPB_DPAD_RIGHT = 14,
    RUI_GPA_LEFTX = 0, RUI_GPA_LEFTY = 1, RUI_GPA_RIGHTX = 2, RUI_GPA_RIGHTY = 3,
    RUI_GPA_TRIGGERLEFT = 4, RUI_GPA_TRIGGERRIGHT = 5,
};

#define KEYF(sc)   { RUI_N64_FIELD_KEY, (sc) }
#define BTNF(b)    { RUI_N64_FIELD_PAD_BUTTON, (b) }
#define AXPF(a)    { RUI_N64_FIELD_PAD_AXIS_P, (a) }
#define AXNF(a)    { RUI_N64_FIELD_PAD_AXIS_N, (a) }
#define NONEF      { RUI_N64_FIELD_NONE, -1 }

// Built-in defaults — PSR reset_defaults_locked() verbatim.
// Keyboard: the historical Project64/Mupen-style layout.
static const N64Field kN64DefaultsKb[LNG_N64_PAD_BUTTON_COUNT][RUI_N64_BINDS_PER_INPUT] = {
    /* A           */ { KEYF(SDL_SCANCODE_X), NONEF },
    /* B           */ { KEYF(SDL_SCANCODE_Z), NONEF },
    /* Z           */ { KEYF(SDL_SCANCODE_LSHIFT), KEYF(SDL_SCANCODE_SPACE) },
    /* Start       */ { KEYF(SDL_SCANCODE_RETURN), KEYF(SDL_SCANCODE_KP_ENTER) },
    /* D-Pad Up    */ { KEYF(SDL_SCANCODE_UP), NONEF },
    /* D-Pad Down  */ { KEYF(SDL_SCANCODE_DOWN), NONEF },
    /* D-Pad Left  */ { KEYF(SDL_SCANCODE_LEFT), NONEF },
    /* D-Pad Right */ { KEYF(SDL_SCANCODE_RIGHT), NONEF },
    /* L           */ { KEYF(SDL_SCANCODE_Q), NONEF },
    /* R           */ { KEYF(SDL_SCANCODE_E), NONEF },
    /* C-Up        */ { KEYF(SDL_SCANCODE_I), NONEF },
    /* C-Down      */ { KEYF(SDL_SCANCODE_K), NONEF },
    /* C-Left      */ { KEYF(SDL_SCANCODE_J), NONEF },
    /* C-Right     */ { KEYF(SDL_SCANCODE_L), NONEF },
    /* Stick Up    */ { KEYF(SDL_SCANCODE_W), NONEF },
    /* Stick Down  */ { KEYF(SDL_SCANCODE_S), NONEF },
    /* Stick Left  */ { KEYF(SDL_SCANCODE_A), NONEF },
    /* Stick Right */ { KEYF(SDL_SCANCODE_D), NONEF },
};
// Controller: bumpers for L/R, triggers for Z, right stick for C, left
// stick for analog.
static const N64Field kN64DefaultsPad[LNG_N64_PAD_BUTTON_COUNT][RUI_N64_BINDS_PER_INPUT] = {
    /* A           */ { BTNF(RUI_GPB_A), NONEF },
    /* B           */ { BTNF(RUI_GPB_B), NONEF },
    /* Z           */ { AXPF(RUI_GPA_TRIGGERLEFT), AXPF(RUI_GPA_TRIGGERRIGHT) },
    /* Start       */ { BTNF(RUI_GPB_START), NONEF },
    /* D-Pad Up    */ { BTNF(RUI_GPB_DPAD_UP), NONEF },
    /* D-Pad Down  */ { BTNF(RUI_GPB_DPAD_DOWN), NONEF },
    /* D-Pad Left  */ { BTNF(RUI_GPB_DPAD_LEFT), NONEF },
    /* D-Pad Right */ { BTNF(RUI_GPB_DPAD_RIGHT), NONEF },
    /* L           */ { BTNF(RUI_GPB_LEFTSHOULDER), NONEF },
    /* R           */ { BTNF(RUI_GPB_RIGHTSHOULDER), NONEF },
    /* C-Up        */ { AXNF(RUI_GPA_RIGHTY), NONEF },
    /* C-Down      */ { AXPF(RUI_GPA_RIGHTY), NONEF },
    /* C-Left      */ { AXNF(RUI_GPA_RIGHTX), NONEF },
    /* C-Right     */ { AXPF(RUI_GPA_RIGHTX), NONEF },
    /* Stick Up    */ { AXNF(RUI_GPA_LEFTY), NONEF },
    /* Stick Down  */ { AXPF(RUI_GPA_LEFTY), NONEF },
    /* Stick Left  */ { AXNF(RUI_GPA_LEFTX), NONEF },
    /* Stick Right */ { AXPF(RUI_GPA_LEFTX), NONEF },
};

static N64Field s_binds[2][LNG_N64_PAD_BUTTON_COUNT][RUI_N64_BINDS_PER_INPUT];
static int s_init = 0;

static void seed_defaults(void) {
    memcpy(s_binds[0], kN64DefaultsKb,  sizeof(kN64DefaultsKb));
    memcpy(s_binds[1], kN64DefaultsPad, sizeof(kN64DefaultsPad));
}

// ---- field encode/decode (PSR encode_field/decode_field, same strings) ------

static void encode_field(const N64Field* f, char* out, size_t cap) {
    switch (f->type) {
        case RUI_N64_FIELD_KEY:        snprintf(out, cap, "key:%d",      f->id); break;
        case RUI_N64_FIELD_PAD_BUTTON: snprintf(out, cap, "button:%d",   f->id); break;
        case RUI_N64_FIELD_PAD_AXIS_P: snprintf(out, cap, "axis+:%d",    f->id); break;
        case RUI_N64_FIELD_PAD_AXIS_N: snprintf(out, cap, "axis-:%d",    f->id); break;
        case RUI_N64_FIELD_JOY_BUTTON: snprintf(out, cap, "joybtn:%d",   f->id); break;
        case RUI_N64_FIELD_JOY_AXIS_P: snprintf(out, cap, "joyaxis+:%d", f->id); break;
        case RUI_N64_FIELD_JOY_AXIS_N: snprintf(out, cap, "joyaxis-:%d", f->id); break;
        default:                       snprintf(out, cap, "none");               break;
    }
}

static int decode_field(const char* s, N64Field* out) {
    const char* colon = strchr(s, ':');
    if (!colon) return 0;
    size_t tl = (size_t)(colon - s);
    int id = 0;
    if (sscanf(colon + 1, "%d", &id) != 1) return 0;
    struct { const char* name; int type; } kTypes[] = {
        { "key", RUI_N64_FIELD_KEY }, { "button", RUI_N64_FIELD_PAD_BUTTON },
        { "axis+", RUI_N64_FIELD_PAD_AXIS_P }, { "axis-", RUI_N64_FIELD_PAD_AXIS_N },
        { "joybtn", RUI_N64_FIELD_JOY_BUTTON },
        { "joyaxis+", RUI_N64_FIELD_JOY_AXIS_P }, { "joyaxis-", RUI_N64_FIELD_JOY_AXIS_N },
    };
    for (size_t i = 0; i < sizeof(kTypes) / sizeof(kTypes[0]); ++i) {
        if (tl == strlen(kTypes[i].name) && strncmp(s, kTypes[i].name, tl) == 0) {
            out->type = kTypes[i].type; out->id = id; return 1;
        }
    }
    return 0;
}

// ---- load/save (PSR load()/save(), same header comments and semantics) -------

static const char* bind_path(const char* path) {
    return (path && path[0]) ? path : "input.cfg";
}

static void load_file(const char* path) {
    seed_defaults();   // baseline; cfg lines override individual bindings
    FILE* f = fopen(bind_path(path), "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        while (n && (line[n-1] == '\n' || line[n-1] == '\r')) line[--n] = '\0';
        if (!line[0] || line[0] == '#') continue;
        char* eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        const char* lhs = line;
        const char* rhs = eq + 1;

        // lhs = <dev>.<INPUT>.<idx>
        char* d1 = strchr(line, '.');
        char* d2 = strrchr(line, '.');
        if (!d1 || d2 == d1) continue;
        *d1 = '\0'; *d2 = '\0';
        const char* dev_s = lhs;
        const char* in_s  = d1 + 1;
        const char* idx_s = d2 + 1;

        int dev;
        if      (strcmp(dev_s, "kb")  == 0) dev = 0;
        else if (strcmp(dev_s, "pad") == 0) dev = 1;
        else continue;

        int in = -1;
        for (int i = 0; i < LNG_N64_PAD_BUTTON_COUNT; ++i)
            if (strcmp(in_s, kN64InputKey[i]) == 0) { in = i; break; }
        if (in < 0) continue;

        int idx = 0;
        if (sscanf(idx_s, "%d", &idx) != 1) continue;
        if (idx < 0 || idx >= RUI_N64_BINDS_PER_INPUT) continue;

        N64Field field = { RUI_N64_FIELD_NONE, -1 };
        if (strcmp(rhs, "none") != 0 && !decode_field(rhs, &field)) continue;

        // First cfg line for a (dev,input) replaces the default pair;
        // subsequent lines (idx 1) fill the alternate slot. An input entirely
        // absent from the cfg keeps its default.
        s_binds[dev][in][idx] = field;
        // A bound idx 0 with no idx 1 line should clear the stale default alt.
        if (idx == 0) { N64Field none = NONEF; s_binds[dev][in][1] = none; }
    }
    fclose(f);
}

static void save_file(const char* path) {
    FILE* f = fopen(bind_path(path), "w");
    if (!f) return;
    fputs("# PokemonStadiumRecomp input bindings - managed by the launcher's\n"
          "# per-controller rebinding menu. Format: <dev>.<input>.<idx>=<field>\n"
          "#   dev:   kb (keyboard) | pad (controller, shared by all gamepads)\n"
          "#   field: key:<scancode> | button:<n> | axis+:<n> | axis-:<n> | none\n", f);
    for (int d = 0; d < 2; ++d) {
        for (int i = 0; i < LNG_N64_PAD_BUTTON_COUNT; ++i) {
            for (int b = 0; b < RUI_N64_BINDS_PER_INPUT; ++b) {
                const N64Field* fld = &s_binds[d][i][b];
                if (fld->type == RUI_N64_FIELD_NONE) continue;
                char enc[32]; encode_field(fld, enc, sizeof(enc));
                fprintf(f, "%s.%s.%d=%s\n", d ? "pad" : "kb", kN64InputKey[i], b, enc);
            }
        }
    }
    fclose(f);
}

static void ensure_init(const char* path) {
    if (s_init) return;
    load_file(path);
    s_init = 1;
}

// ---- public API ---------------------------------------------------------------

void rui_n64_binds_init(const char* path) {
    load_file(path);
    s_init = 1;
}

void rui_n64_binds_get(const char* path, int device, int b, int slot,
                       int* out_type, int* out_id) {
    if (out_type) *out_type = RUI_N64_FIELD_NONE;
    if (out_id)   *out_id   = -1;
    if (device < 0 || device > 1 || b < 0 || b >= LNG_N64_PAD_BUTTON_COUNT ||
        slot < 0 || slot >= RUI_N64_BINDS_PER_INPUT) return;
    ensure_init(path);
    if (out_type) *out_type = s_binds[device][b][slot].type;
    if (out_id)   *out_id   = s_binds[device][b][slot].id;
}

void rui_n64_binds_set(const char* path, int device, int b, int slot,
                       int type, int id) {
    if (device < 0 || device > 1 || b < 0 || b >= LNG_N64_PAD_BUTTON_COUNT ||
        slot < 0 || slot >= RUI_N64_BINDS_PER_INPUT) return;
    ensure_init(path);
    s_binds[device][b][slot].type = type;
    s_binds[device][b][slot].id   = id;
    save_file(path);
}

void rui_n64_binds_reset_device(const char* path, int device) {
    if (device < 0 || device > 1) return;
    ensure_init(path);
    memcpy(s_binds[device], device ? kN64DefaultsPad : kN64DefaultsKb,
           sizeof(s_binds[device]));
    save_file(path);
}

// ---- display labels (PSR field_to_string vocabulary) ---------------------------

static const char* pad_button_label(int b) {
    switch (b) {
        case RUI_GPB_A:             return "A";
        case RUI_GPB_B:             return "B";
        case RUI_GPB_X:             return "X";
        case RUI_GPB_Y:             return "Y";
        case RUI_GPB_BACK:          return "Back";
        case RUI_GPB_GUIDE:         return "Guide";
        case RUI_GPB_START:         return "Start";
        case RUI_GPB_LEFTSTICK:     return "L3";
        case RUI_GPB_RIGHTSTICK:    return "R3";
        case RUI_GPB_LEFTSHOULDER:  return "LB";
        case RUI_GPB_RIGHTSHOULDER: return "RB";
        case RUI_GPB_DPAD_UP:       return "D-Pad Up";
        case RUI_GPB_DPAD_DOWN:     return "D-Pad Down";
        case RUI_GPB_DPAD_LEFT:     return "D-Pad Left";
        case RUI_GPB_DPAD_RIGHT:    return "D-Pad Right";
        default:                    return "Button";
    }
}

static const char* pad_axis_label(int axis, int positive) {
    switch (axis) {
        case RUI_GPA_TRIGGERLEFT:  return "LT";
        case RUI_GPA_TRIGGERRIGHT: return "RT";
        case RUI_GPA_LEFTX:        return positive ? "L-Stick Right" : "L-Stick Left";
        case RUI_GPA_LEFTY:        return positive ? "L-Stick Down"  : "L-Stick Up";
        case RUI_GPA_RIGHTX:       return positive ? "R-Stick Right" : "R-Stick Left";
        case RUI_GPA_RIGHTY:       return positive ? "R-Stick Down"  : "R-Stick Up";
        default:                   return positive ? "Axis+" : "Axis-";
    }
}

void rui_n64_binds_label(int type, int id, char* out, size_t cap) {
    if (!out || !cap) return;
    switch (type) {
        case RUI_N64_FIELD_KEY: {
            const char* name = SDL_GetScancodeName((SDL_Scancode)id);
            if (name && name[0]) snprintf(out, cap, "%s", name);
            else                 snprintf(out, cap, "Key %d", id);
            break;
        }
        case RUI_N64_FIELD_PAD_BUTTON: snprintf(out, cap, "%s", pad_button_label(id)); break;
        case RUI_N64_FIELD_PAD_AXIS_P: snprintf(out, cap, "%s", pad_axis_label(id, 1)); break;
        case RUI_N64_FIELD_PAD_AXIS_N: snprintf(out, cap, "%s", pad_axis_label(id, 0)); break;
        case RUI_N64_FIELD_JOY_BUTTON: snprintf(out, cap, "Btn %d", id); break;
        case RUI_N64_FIELD_JOY_AXIS_P: snprintf(out, cap, "Axis %d+", id); break;
        case RUI_N64_FIELD_JOY_AXIS_N: snprintf(out, cap, "Axis %d-", id); break;
        default: snprintf(out, cap, "\xE2\x80\x94"); break;   // em dash
    }
}
