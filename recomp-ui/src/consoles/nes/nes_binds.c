// nes_binds.c — NES-native keybind persistence bridge (see nes_binds.h).
//
// Ported from the pre-restructure in-file bridge (feat/nes-console) into the
// per-console unit layout: logic, key vocabulary, runner-exact defaults, and
// the surgical-write persistence are unchanged — only the seam moved
// (launcher_binds.c calls this module for NES profiles).

#include "nes_binds.h"
#include "nes_profile.h"          // LNG_NES_PAD_BUTTON_COUNT (rebind-spec order)
#include "launcher_binds.h"       // launcher_ini_kv_write (surgical section writes)
#include "launcher_sdlcompat.h"   // SDL header (2 or 3)

#include <ctype.h>
#include <stdio.h>
#include <string.h>

// Rebind-spec order (nes_profile.h kNesPadButtons) -> the runner's
// keybinds.ini key NAME (runner/src/keybinds.c s_buttons; never by index).
static const char* kNesKbKeyName[LNG_NES_PAD_BUTTON_COUNT] = {
    "up", "down", "left", "right", "a", "b", "start", "select",
};

// Defaults mirror nesrecomp runner/src/keybinds.c's s_binds exactly, in
// kNesPadButtons rebind-spec order.
static const SDL_Scancode kNesDefaultsP1[LNG_NES_PAD_BUTTON_COUNT] = {
    /* Up */ SDL_SCANCODE_UP, /* Down */ SDL_SCANCODE_DOWN,
    /* Left */ SDL_SCANCODE_LEFT, /* Right */ SDL_SCANCODE_RIGHT,
    /* A */ SDL_SCANCODE_Z, /* B */ SDL_SCANCODE_X,
    /* Start */ SDL_SCANCODE_RETURN, /* Select */ SDL_SCANCODE_BACKSLASH,
};
static const SDL_Scancode kNesDefaultsP2[LNG_NES_PAD_BUTTON_COUNT] = {
    /* Up */ SDL_SCANCODE_W, /* Down */ SDL_SCANCODE_S,
    /* Left */ SDL_SCANCODE_A, /* Right */ SDL_SCANCODE_D,
    /* A */ SDL_SCANCODE_K, /* B */ SDL_SCANCODE_L,
    /* Start */ SDL_SCANCODE_BACKSLASH, /* Select */ SDL_SCANCODE_RSHIFT,
};

static const char* kNesCameraKeyName[LNG_CAMERA_BIND_COUNT] = {
    "look_up", "look_down", "look_left", "look_right",
    "roll_left", "roll_right", "zoom_in", "zoom_out",
    "sprite_smaller", "sprite_larger", "reset", "toggle",
};
static const SDL_Scancode kNesCameraDefaults[LNG_CAMERA_BIND_COUNT] = {
    SDL_SCANCODE_KP_8, SDL_SCANCODE_KP_2,
    SDL_SCANCODE_KP_4, SDL_SCANCODE_KP_6,
    SDL_SCANCODE_KP_7, SDL_SCANCODE_KP_9,
    SDL_SCANCODE_KP_PLUS, SDL_SCANCODE_KP_MINUS,
    SDL_SCANCODE_KP_1, SDL_SCANCODE_KP_3,
    SDL_SCANCODE_KP_5, SDL_SCANCODE_KP_0,
};

static SDL_Scancode s_nes_binds[2][LNG_NES_PAD_BUTTON_COUNT];
static SDL_Scancode s_nes_camera_binds[LNG_CAMERA_BIND_COUNT];
static int s_nes_camera_seen[LNG_CAMERA_BIND_COUNT];
static int s_nes_binds_init = 0;
// Zapper switches ([zapper] mouse/crosshair). Runner defaults: both ON (the
// mouse IS the light gun on a PC; consumers are gated on g_zapper_enabled,
// so this is inert for non-Zapper games).
static int s_nes_zapper_mouse = 1;
static int s_nes_zapper_crosshair = 1;

// Same scancode<->name normalization keybinds.c / the runner use (SDL name
// first, then a handful of common aliases) so files round-trip identically
// whichever side writes them.
static SDL_Scancode nes_kb_name_to_scancode(const char* name) {
    if (!name || !*name) return SDL_SCANCODE_UNKNOWN;
    SDL_Scancode sc = SDL_GetScancodeFromName(name);
    if (sc != SDL_SCANCODE_UNKNOWN) return sc;
    char buf[32]; size_t i = 0;
    for (; name[i] && i < sizeof(buf) - 1; i++) buf[i] = (char)tolower((unsigned char)name[i]);
    buf[i] = '\0';
    if (!strcmp(buf, "enter") || !strcmp(buf, "return")) return SDL_SCANCODE_RETURN;
    if (!strcmp(buf, "tab"))     return SDL_SCANCODE_TAB;
    if (!strcmp(buf, "space"))   return SDL_SCANCODE_SPACE;
    if (!strcmp(buf, "lshift"))  return SDL_SCANCODE_LSHIFT;
    if (!strcmp(buf, "rshift"))  return SDL_SCANCODE_RSHIFT;
    if (!strcmp(buf, "lctrl"))   return SDL_SCANCODE_LCTRL;
    if (!strcmp(buf, "rctrl"))   return SDL_SCANCODE_RCTRL;
    if (!strcmp(buf, "backslash")) return SDL_SCANCODE_BACKSLASH;
    if (!strcmp(buf, "escape") || !strcmp(buf, "esc")) return SDL_SCANCODE_ESCAPE;
    if (!strcmp(buf, "backspace")) return SDL_SCANCODE_BACKSPACE;
    if (!strcmp(buf, "none") || !buf[0]) return SDL_SCANCODE_UNKNOWN;
    return SDL_SCANCODE_UNKNOWN;
}
static const char* nes_kb_scancode_to_name(SDL_Scancode sc) {
    if (sc == SDL_SCANCODE_UNKNOWN) return "None";
    const char* n = SDL_GetScancodeName(sc);
    return (n && n[0]) ? n : "None";
}

// Seed a fresh keybinds.ini with the SAME content the runner's own
// write_defaults() generates (runner/src/keybinds.c) — player sections from
// the default scancodes, plus the [zapper] and [gamepad1]/[gamepad2] sections
// with the runner's defaults — so whichever process (launcher or game) runs
// first creates a file the other already understands, sections included.
static void nes_kb_write_defaults(const char* path) {
    FILE* f = fopen(path, "w");
    if (!f) return;
    fprintf(f, "# NES Controller Keybinds\n");
    fprintf(f, "# Edit key names to customize. Use SDL key names.\n");
    fprintf(f, "# Common keys: Z, X, Tab, Return, Up, Down, Left, Right\n");
    fprintf(f, "# A, B, C, ..., W, S, D, K, L, Space, Left Shift, Right Shift\n\n");
    // The runner writes buttons in ITS table order (a,b,select,start,up,down,
    // left,right) — match it so the seeded file is shaped like the runner's
    // own. Runner-order index -> rebind-spec index:
    static const int kRunnerOrder[LNG_NES_PAD_BUTTON_COUNT] = { 4, 5, 7, 6, 0, 1, 2, 3 };
    for (int p = 0; p < 2; ++p) {
        fprintf(f, "[player%d]\n", p + 1);
        for (int i = 0; i < LNG_NES_PAD_BUTTON_COUNT; ++i) {
            int b = kRunnerOrder[i];
            fprintf(f, "%s = %s\n", kNesKbKeyName[b], nes_kb_scancode_to_name(s_nes_binds[p][b]));
        }
        fprintf(f, "\n");
    }
    fprintf(f, "[zapper]\n");
    fprintf(f, "# Mouse as the Zapper light gun (default on for Zapper games):\n");
    fprintf(f, "# left click = trigger, mouse position = aim.  Set false to disable.\n");
    fprintf(f, "mouse = %s\n", s_nes_zapper_mouse ? "true" : "false");
    fprintf(f, "# Show a crosshair at the aim point (and hide the OS cursor).\n");
    fprintf(f, "crosshair = %s\n\n", s_nes_zapper_crosshair ? "true" : "false");
    fprintf(f, "[camera]\n");
    fprintf(f, "# Optional Voxel/3D camera keys. Gamepad look defaults to the right stick.\n");
    for (int i = 0; i < LNG_CAMERA_BIND_COUNT; ++i)
        fprintf(f, "%s = %s\n", kNesCameraKeyName[i],
                nes_kb_scancode_to_name(s_nes_camera_binds[i]));
    fprintf(f, "\n");
    fprintf(f, "# Gamepad bindings (SDL game-controller button names).\n");
    fprintf(f, "# Values may list multiple buttons separated by commas, e.g. \"a, b\".\n");
    fprintf(f, "# Valid names: a b x y back start guide leftshoulder rightshoulder\n");
    fprintf(f, "#   leftstick rightstick dpup dpdown dpleft dpright (use \"none\" to unbind).\n");
    fprintf(f, "# deadzone: left-stick threshold 0-32767.  analog: stick also moves the d-pad.\n");
    fprintf(f, "# Names are positional (a=bottom, b=right, x=left, y=top on an Xbox pad).\n\n");
    for (int p = 1; p <= 2; ++p) {
        fprintf(f, "[gamepad%d]\n", p);
        fprintf(f, "a = a,b\n");
        fprintf(f, "b = x,y\n");
        fprintf(f, "select = back\n");
        fprintf(f, "start = start\n");
        fprintf(f, "up = dpup\n");
        fprintf(f, "down = dpdown\n");
        fprintf(f, "left = dpleft\n");
        fprintf(f, "right = dpright\n");
        fprintf(f, "deadzone = 16000\n");
        fprintf(f, "analog = true\n\n");
    }
    fclose(f);
}

// Parse [player1]/[player2] (the 8 NES keys) and [zapper] from the runner's
// format. All other sections ([gamepad*]) are left for the runner; writes
// never touch them (surgical per-key persistence).
static void nes_kb_load_ini(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return;
    int player = -1;   // -1 none, 0 p1, 1 p2
    int in_zapper = 0;
    int in_camera = 0;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        while (n > 0 && (line[n-1] == '\n' || line[n-1] == '\r' || isspace((unsigned char)line[n-1]))) line[--n] = '\0';
        char* s = line;
        while (*s && isspace((unsigned char)*s)) ++s;
        if (!*s || *s == '#' || *s == ';') continue;
        if (*s == '[') {
            char* end = strchr(s, ']');
            if (end) *end = '\0';
            const char* section = s + 1;
            player = -1; in_zapper = 0; in_camera = 0;
            if (!strcmp(section, "player1")) player = 0;
            else if (!strcmp(section, "player2")) player = 1;
            else if (!strcmp(section, "zapper")) in_zapper = 1;
            else if (!strcmp(section, "camera")) in_camera = 1;
            continue;
        }
        char* eq = strchr(s, '=');
        if (!eq || (player < 0 && !in_zapper && !in_camera)) continue;
        *eq = '\0';
        char* key = s; char* val = eq + 1;
        size_t kl = strlen(key); while (kl > 0 && isspace((unsigned char)key[kl-1])) key[--kl] = '\0';
        while (*val && isspace((unsigned char)*val)) ++val;
        size_t vl = strlen(val); while (vl > 0 && isspace((unsigned char)val[vl-1])) val[--vl] = '\0';
        for (char* c = key; *c; c++) *c = (char)tolower((unsigned char)*c);
        if (in_zapper) {
            char vb[16]; size_t i = 0;
            for (char* c = val; *c && i < sizeof(vb) - 1; c++) vb[i++] = (char)tolower((unsigned char)*c);
            vb[i] = '\0';
            int bval = (!strcmp(vb, "true") || !strcmp(vb, "1") || !strcmp(vb, "yes"));
            if (!strcmp(key, "mouse"))          s_nes_zapper_mouse = bval;
            else if (!strcmp(key, "crosshair")) s_nes_zapper_crosshair = bval;
            continue;
        }
        if (in_camera) {
            for (int i = 0; i < LNG_CAMERA_BIND_COUNT; ++i) {
                if (!strcmp(key, kNesCameraKeyName[i])) {
                    s_nes_camera_binds[i] =
                        nes_kb_name_to_scancode(val);
                    s_nes_camera_seen[i] = 1;
                    break;
                }
            }
            continue;
        }
        for (int b = 0; b < LNG_NES_PAD_BUTTON_COUNT; ++b) {
            if (!strcmp(key, kNesKbKeyName[b])) {
                s_nes_binds[player][b] = nes_kb_name_to_scancode(val);
                break;
            }
        }
    }
    fclose(f);
}

void rui_nes_binds_init(const char* path) {
    memcpy(s_nes_binds[0], kNesDefaultsP1, sizeof(kNesDefaultsP1));
    memcpy(s_nes_binds[1], kNesDefaultsP2, sizeof(kNesDefaultsP2));
    memcpy(s_nes_camera_binds, kNesCameraDefaults,
           sizeof(s_nes_camera_binds));
    memset(s_nes_camera_seen, 0, sizeof(s_nes_camera_seen));
    s_nes_zapper_mouse = 1;
    s_nes_zapper_crosshair = 1;
    FILE* test = fopen(path, "r");
    if (test) {
        fclose(test);
        nes_kb_load_ini(path);
        /* Existing installs predate [camera]. Add only missing entries so
         * user-defined keys and every unrelated section remain untouched. */
        for (int i = 0; i < LNG_CAMERA_BIND_COUNT; ++i) {
            if (!s_nes_camera_seen[i])
                launcher_ini_kv_write(
                    path, "camera", kNesCameraKeyName[i],
                    nes_kb_scancode_to_name(s_nes_camera_binds[i]));
        }
    } else {
        nes_kb_write_defaults(path);
    }
    s_nes_binds_init = 1;
}

int rui_nes_binds_get(const char* path, int player, int b) {
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    if (player < 0 || player > 1 || b < 0 || b >= LNG_NES_PAD_BUTTON_COUNT)
        return SDL_SCANCODE_UNKNOWN;
    return (int)s_nes_binds[player][b];
}

void rui_nes_binds_set(const char* path, int player, int b, int scancode) {
    if (player < 0 || player > 1 || b < 0 || b >= LNG_NES_PAD_BUTTON_COUNT) return;
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    s_nes_binds[player][b] = (SDL_Scancode)scancode;
    char section[16];
    snprintf(section, sizeof(section), "player%d", player + 1);
    launcher_ini_kv_write(path, section, kNesKbKeyName[b],
                          nes_kb_scancode_to_name((SDL_Scancode)scancode));
}

void rui_nes_binds_reset(const char* path, int player) {
    if (player < 0 || player > 1) return;
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    memcpy(s_nes_binds[player], player == 1 ? kNesDefaultsP2 : kNesDefaultsP1,
           sizeof(s_nes_binds[player]));
    char section[16];
    snprintf(section, sizeof(section), "player%d", player + 1);
    for (int b = 0; b < LNG_NES_PAD_BUTTON_COUNT; ++b)
        launcher_ini_kv_write(path, section, kNesKbKeyName[b],
                              nes_kb_scancode_to_name(s_nes_binds[player][b]));
}

void rui_nes_zapper_get(const char* path, int* mouse_enabled, int* crosshair) {
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    if (mouse_enabled) *mouse_enabled = s_nes_zapper_mouse;
    if (crosshair)     *crosshair     = s_nes_zapper_crosshair;
}

void rui_nes_zapper_set(const char* path, int mouse_enabled, int crosshair) {
    s_nes_zapper_mouse     = mouse_enabled ? 1 : 0;
    s_nes_zapper_crosshair = crosshair ? 1 : 0;
    launcher_ini_kv_write(path, "zapper", "mouse",     s_nes_zapper_mouse ? "true" : "false");
    launcher_ini_kv_write(path, "zapper", "crosshair", s_nes_zapper_crosshair ? "true" : "false");
}

int rui_nes_camera_bind_get(const char* path, int action) {
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    if (action < 0 || action >= LNG_CAMERA_BIND_COUNT)
        return SDL_SCANCODE_UNKNOWN;
    return (int)s_nes_camera_binds[action];
}

void rui_nes_camera_bind_set(const char* path, int action, int scancode) {
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    if (action < 0 || action >= LNG_CAMERA_BIND_COUNT) return;
    s_nes_camera_binds[action] = (SDL_Scancode)scancode;
    launcher_ini_kv_write(
        path, "camera", kNesCameraKeyName[action],
        nes_kb_scancode_to_name((SDL_Scancode)scancode));
}

void rui_nes_camera_bind_reset(const char* path) {
    if (!s_nes_binds_init) rui_nes_binds_init(path);
    memcpy(s_nes_camera_binds, kNesCameraDefaults,
           sizeof(s_nes_camera_binds));
    for (int i = 0; i < LNG_CAMERA_BIND_COUNT; ++i)
        launcher_ini_kv_write(
            path, "camera", kNesCameraKeyName[i],
            nes_kb_scancode_to_name(s_nes_camera_binds[i]));
}
