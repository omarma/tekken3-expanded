// psx_binds.c — PSX-native keybind persistence bridge (see psx_binds.h).
//
// Extracted verbatim from launcher_binds.c's in-file "PSX-native keybind
// bridge" block when the per-console split landed: the logic, key vocabulary,
// defaults, and foreign-format detection are unchanged — only the seam moved
// (launcher_binds.c now calls this module for PSX profiles instead of
// carrying the bridge inline).

#include "psx_binds.h"
#include "psx_profile.h"          // LNG_PSX_PAD_BUTTON_COUNT (rebind-spec order)
#include "launcher_sdlcompat.h"   // SDL header (2 or 3)

#include <ctype.h>
#include <stdio.h>
#include <string.h>

/* Keep in sync with RECOMP_LAUNCHER_MAX_PLAYERS / PSXKB_MAX_PLAYERS. */
#define PSX_BINDS_MAX_PLAYERS 5

// Rebind-spec order (psx_profile.h kPsxPadButtons, 24 entries) is a
// DIFFERENT physical ordering than psx_keybinds.c's kButtons — this table
// maps rebind-spec index -> ini key NAME (never by raw index).
static const char* kPsxKbKeyName[LNG_PSX_PAD_BUTTON_COUNT] = {
    "up", "down", "left", "right",
    "triangle", "circle", "cross", "square",
    "l1", "l2", "r1", "r2",
    "l3", "r3", "start", "select",
    "ls_up", "ls_down", "ls_left", "ls_right",
    "rs_up", "rs_down", "rs_left", "rs_right",
};

// Defaults mirror psxrecomp's PSXKB_DEFAULTS (psx_keybinds.c) exactly, just
// reordered into kPsxPadButtons's rebind-spec order, so a file either process
// creates first is byte-for-byte what the other would have generated.
// Every player slot uses the same default map (P1 historical layout).
static const SDL_Scancode kPsxDefaults[LNG_PSX_PAD_BUTTON_COUNT] = {
    /* Up */ SDL_SCANCODE_UP, /* Down */ SDL_SCANCODE_DOWN,
    /* Left */ SDL_SCANCODE_LEFT, /* Right */ SDL_SCANCODE_RIGHT,
    /* Triangle */ SDL_SCANCODE_A, /* Circle */ SDL_SCANCODE_S,
    /* Cross */ SDL_SCANCODE_X, /* Square */ SDL_SCANCODE_Z,
    /* L1 */ SDL_SCANCODE_Q, /* L2 */ SDL_SCANCODE_E,
    /* R1 */ SDL_SCANCODE_W, /* R2 */ SDL_SCANCODE_R,
    /* L3 */ SDL_SCANCODE_T, /* R3 */ SDL_SCANCODE_Y,
    /* Start */ SDL_SCANCODE_RETURN, /* Select */ SDL_SCANCODE_RSHIFT,
    /* LS Up */ SDL_SCANCODE_UP, /* LS Down */ SDL_SCANCODE_DOWN,
    /* LS Left */ SDL_SCANCODE_LEFT, /* LS Right */ SDL_SCANCODE_RIGHT,
    /* RS Up */ SDL_SCANCODE_UNKNOWN, /* RS Down */ SDL_SCANCODE_UNKNOWN,
    /* RS Left */ SDL_SCANCODE_UNKNOWN, /* RS Right */ SDL_SCANCODE_UNKNOWN,
};

static SDL_Scancode s_psx_binds[PSX_BINDS_MAX_PLAYERS][LNG_PSX_PAD_BUTTON_COUNT];
/* Alternate (secondary) bind per input. Either slot asserts the input.
 * Persisted in keybinds.ini as a comma-separated second value
 * ("cross = X, Mouse1"), byte-identical to what psx_keybinds.c writes.
 * UNKNOWN = no alt bound. */
static SDL_Scancode s_psx_binds_alt[PSX_BINDS_MAX_PLAYERS][LNG_PSX_PAD_BUTTON_COUNT];
static int s_psx_binds_init = 0;

/* Mouse-button pseudo-scancodes, mirroring psx_keybinds.c exactly: values
 * sit above SDL keyboard scancode space so they flow through the same
 * bind/save/load machinery as ordinary scancodes. INI names Mouse1..5. */
#define PSX_MOUSE_SC_BASE 512
#define PSX_MOUSE_SC(btn) ((SDL_Scancode)(PSX_MOUSE_SC_BASE + (btn)))
#define PSX_IS_MOUSE_SC(sc) \
    ((int)(sc) > PSX_MOUSE_SC_BASE && (int)(sc) <= PSX_MOUSE_SC_BASE + 5)

// Same scancode<->name normalization psx_keybinds.c/keybinds.c use (SDL name
// first, then a handful of common aliases) so files round-trip identically
// whichever side writes them.
static SDL_Scancode psx_kb_name_to_scancode(const char* name) {
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
    if (!strcmp(buf, "lalt"))    return SDL_SCANCODE_LALT;
    if (!strcmp(buf, "ralt"))    return SDL_SCANCODE_RALT;
    if (!strcmp(buf, "backslash")) return SDL_SCANCODE_BACKSLASH;
    if (!strcmp(buf, "escape") || !strcmp(buf, "esc")) return SDL_SCANCODE_ESCAPE;
    if (!strcmp(buf, "backspace")) return SDL_SCANCODE_BACKSPACE;
    if (!strcmp(buf, "none") || !buf[0]) return SDL_SCANCODE_UNKNOWN;
    /* Mouse buttons (SDL order: 1 left, 2 middle, 3 right, 4/5 side). */
    if (!strncmp(buf, "mouse", 5) && buf[5] >= '1' && buf[5] <= '5' && !buf[6])
        return PSX_MOUSE_SC(buf[5] - '0');
    if (!strcmp(buf, "lmb")) return PSX_MOUSE_SC(1);
    if (!strcmp(buf, "mmb")) return PSX_MOUSE_SC(2);
    if (!strcmp(buf, "rmb")) return PSX_MOUSE_SC(3);
    return SDL_SCANCODE_UNKNOWN;
}
static const char* psx_kb_scancode_to_name(SDL_Scancode sc) {
    if (sc == SDL_SCANCODE_UNKNOWN) return "None";
    if (PSX_IS_MOUSE_SC(sc)) {
        static const char* const kMouseNames[5] =
            { "Mouse1", "Mouse2", "Mouse3", "Mouse4", "Mouse5" };
        return kMouseNames[(int)sc - PSX_MOUSE_SC_BASE - 1];
    }
    const char* n = SDL_GetScancodeName(sc);
    return (n && n[0]) ? n : "None";
}

static void psx_kb_write_ini(const char* path) {
    FILE* f = fopen(path, "w");
    if (!f) return;
    fprintf(f,
        "# PSXRecomp Keyboard Keybinds (keyboard -> DualShock).\n"
        "# Written by recomp-ui's launcher (psx_keybinds.c-compatible format);\n"
        "# also read/regenerated by the game's own runtime. Edit values and\n"
        "# restart, or rebind live in the launcher's Controls page.\n"
        "# Use SDL key names, or \"None\" to leave an input unbound.\n\n");
    for (int p = 0; p < PSX_BINDS_MAX_PLAYERS; ++p) {
        fprintf(f, "[player%d]\n", p + 1);
        for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b) {
            if (s_psx_binds_alt[p][b] != SDL_SCANCODE_UNKNOWN)
                fprintf(f, "%-9s = %s, %s\n", kPsxKbKeyName[b],
                        psx_kb_scancode_to_name(s_psx_binds[p][b]),
                        psx_kb_scancode_to_name(s_psx_binds_alt[p][b]));
            else
                fprintf(f, "%-9s = %s\n", kPsxKbKeyName[b],
                        psx_kb_scancode_to_name(s_psx_binds[p][b]));
        }
        fprintf(f, "\n");
    }
    fclose(f);
}

// Key indices present ONLY in psx_keybinds.c's vocabulary (never in
// keybinds.c's generic PlayerBinds format): triangle/circle/cross/square,
// l1/r1 (generic only has l/r), and all 8 ls_*/rs_* stick binds. up/down/
// left/right/start/select/l2/r2/l3/r3 (the other 10 keys) exist in BOTH
// formats by coincidence of naming, so matching one of those alone does NOT
// prove the file is psx_keybinds.c-shaped — see psx_kb_load_ini()'s use of
// this, which is what stops a stale pre-bridge generic-format keybinds.ini
// from being silently half-applied as if it were native.
static int psx_kb_key_is_native_only(int b) {
    switch (b) {
        case 4: case 5: case 6: case 7:        // triangle/circle/cross/square
        case 8: case 10:                        // l1/r1
        case 16: case 17: case 18: case 19:     // ls_up/down/left/right
        case 20: case 21: case 22: case 23:     // rs_up/down/left/right
            return 1;
        default:
            return 0;
    }
}

// Returns the count of NATIVE-ONLY keys matched (see above) — the caller
// uses this to detect a foreign-format file instead of silently blending
// its overlapping-name values into the defaults.
static int psx_kb_load_ini(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return 0;
    int player = -1;   // -1 none, 0..PSX_BINDS_MAX_PLAYERS-1
    int native_hits = 0;
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
            player = -1;
            if (!strncmp(section, "player", 6)) {
                int npl = 0;
                for (const char* c = section + 6; *c >= '0' && *c <= '9'; ++c)
                    npl = npl * 10 + (*c - '0');
                if (npl >= 1 && npl <= PSX_BINDS_MAX_PLAYERS) player = npl - 1;
            }
            continue;
        }
        char* eq = strchr(s, '=');
        if (!eq || player < 0) continue;
        *eq = '\0';
        char* key = s; char* val = eq + 1;
        // trim key/val
        size_t kl = strlen(key); while (kl > 0 && isspace((unsigned char)key[kl-1])) key[--kl] = '\0';
        while (*val && isspace((unsigned char)*val)) ++val;
        size_t vl = strlen(val); while (vl > 0 && isspace((unsigned char)val[vl-1])) val[--vl] = '\0';
        for (char* c = key; *c; c++) *c = (char)tolower((unsigned char)*c);
        /* Optional alternate bind after a comma: "cross = X, Mouse1". */
        char* alt_val = NULL;
        {
            char* comma = strchr(val, ',');
            if (comma) {
                *comma = '\0';
                alt_val = comma + 1;
                size_t tl = strlen(val);
                while (tl > 0 && isspace((unsigned char)val[tl-1])) val[--tl] = '\0';
                while (*alt_val && isspace((unsigned char)*alt_val)) ++alt_val;
                size_t al = strlen(alt_val);
                while (al > 0 && isspace((unsigned char)alt_val[al-1])) alt_val[--al] = '\0';
            }
        }
        for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b) {
            if (!strcmp(key, kPsxKbKeyName[b])) {
                s_psx_binds[player][b] = psx_kb_name_to_scancode(val);
                s_psx_binds_alt[player][b] =
                    alt_val ? psx_kb_name_to_scancode(alt_val) : SDL_SCANCODE_UNKNOWN;
                if (psx_kb_key_is_native_only(b)) ++native_hits;
                break;
            }
        }
    }
    fclose(f);
    return native_hits;
}

static void psx_kb_seed_defaults(void) {
    for (int p = 0; p < PSX_BINDS_MAX_PLAYERS; ++p) {
        memcpy(s_psx_binds[p], kPsxDefaults, sizeof(kPsxDefaults));
        for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b)
            s_psx_binds_alt[p][b] = SDL_SCANCODE_UNKNOWN;   /* no alt by default */
    }
}

static int psx_kb_player_all_unbound(int player) {
    for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b)
        if (s_psx_binds[player][b] != SDL_SCANCODE_UNKNOWN) return 0;
    return 1;
}

/* Older keybinds.ini left P2+ fully unbound — promote empty slots to the
 * shared default map so Reset / keyboard routing works on every player. */
static void psx_kb_promote_empty_players(void) {
    for (int p = 0; p < PSX_BINDS_MAX_PLAYERS; ++p) {
        if (psx_kb_player_all_unbound(p))
            memcpy(s_psx_binds[p], kPsxDefaults, sizeof(kPsxDefaults));
    }
}

void rui_psx_binds_init(const char* path) {
    psx_kb_seed_defaults();
    FILE* test = fopen(path, "r");
    if (test) {
        fclose(test);
        int native_hits = psx_kb_load_ini(path);
        if (native_hits == 0) {
            psx_kb_seed_defaults();
            psx_kb_write_ini(path);
        } else {
            psx_kb_promote_empty_players();
        }
    } else {
        psx_kb_write_ini(path);
    }
    s_psx_binds_init = 1;
}

int rui_psx_binds_get(const char* path, int player, int b) {
    if (!s_psx_binds_init) rui_psx_binds_init(path);
    if (player < 0 || player >= PSX_BINDS_MAX_PLAYERS || b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT)
        return SDL_SCANCODE_UNKNOWN;
    return (int)s_psx_binds[player][b];
}

void rui_psx_binds_set(const char* path, int player, int b, int scancode) {
    if (player < 0 || player >= PSX_BINDS_MAX_PLAYERS || b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT) return;
    if (!s_psx_binds_init) rui_psx_binds_init(path);
    s_psx_binds[player][b] = (SDL_Scancode)scancode;
    psx_kb_write_ini(path);
}

int rui_psx_binds_get_slot(const char* path, int player, int b, int slot) {
    if (slot != 1) return rui_psx_binds_get(path, player, b);
    if (!s_psx_binds_init) rui_psx_binds_init(path);
    if (player < 0 || player >= PSX_BINDS_MAX_PLAYERS ||
        b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT)
        return SDL_SCANCODE_UNKNOWN;
    return (int)s_psx_binds_alt[player][b];
}

void rui_psx_binds_set_slot(const char* path, int player, int b, int slot, int scancode) {
    if (slot != 1) { rui_psx_binds_set(path, player, b, scancode); return; }
    if (player < 0 || player >= PSX_BINDS_MAX_PLAYERS ||
        b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT) return;
    if (!s_psx_binds_init) rui_psx_binds_init(path);
    s_psx_binds_alt[player][b] = (SDL_Scancode)scancode;
    psx_kb_write_ini(path);
}

void rui_psx_binds_reset(const char* path, int player) {
    if (player < 0 || player >= PSX_BINDS_MAX_PLAYERS) return;
    if (!s_psx_binds_init) rui_psx_binds_init(path);
    memcpy(s_psx_binds[player], kPsxDefaults, sizeof(kPsxDefaults));
    for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b)
        s_psx_binds_alt[player][b] = SDL_SCANCODE_UNKNOWN;
    psx_kb_write_ini(path);
}
