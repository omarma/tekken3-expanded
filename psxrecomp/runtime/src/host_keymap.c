/* host_keymap.c — config.ini [KeyMap] for host volume hotkeys.
 *
 * Value format matches recomp-ui / MetalWarriors ParseKeyArray:
 *   [Ctrl+][Alt+][Shift+]<SDL_GetKeyName>
 * Comma-separated multi-binds are accepted. Empty / unknown => leave slot
 * unbound; after parse, empty VolumeUp/Down fall back to Keypad +/-.
 */

#include "host_keymap.h"
#include "psx_sdl.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HOST_KEYMAP_MAX_BINDS 4

typedef struct HostKeyBind {
    int keycode;
    int mods; /* KMOD_CTRL | KMOD_ALT | KMOD_SHIFT subset */
} HostKeyBind;

typedef struct HostKeyAction {
    HostKeyBind binds[HOST_KEYMAP_MAX_BINDS];
    int count;
} HostKeyAction;

static HostKeyAction s_actions[HOST_KEYMAP_ACTION_COUNT];

static int ieq(const char *a, const char *b) {
    if (!a || !b) return 0;
    while (*a && *b) {
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return 0;
        ++a;
        ++b;
    }
    return *a == 0 && *b == 0;
}

static int starts_ci(const char *s, const char *pfx) {
    if (!s || !pfx) return 0;
    while (*pfx) {
        if (!*s || tolower((unsigned char)*s) != tolower((unsigned char)*pfx))
            return 0;
        ++s;
        ++pfx;
    }
    return 1;
}

static void trim_inplace(char *s) {
    char *e;
    if (!s) return;
    while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n')
        memmove(s, s + 1, strlen(s));
    e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' ||
                     e[-1] == '\n'))
        *--e = 0;
}

static void clear_all(void) {
    memset(s_actions, 0, sizeof(s_actions));
}

static void add_bind(HostKeymapAction action, int keycode, int mods) {
    HostKeyAction *a;
    if (action < 0 || action >= HOST_KEYMAP_ACTION_COUNT) return;
    if (keycode == 0 || keycode == SDLK_UNKNOWN) return;
    a = &s_actions[action];
    if (a->count >= HOST_KEYMAP_MAX_BINDS) return;
    a->binds[a->count].keycode = keycode;
    a->binds[a->count].mods = mods;
    a->count++;
}

static void apply_defaults(void) {
    if (s_actions[HOST_KEYMAP_VOLUME_UP].count == 0)
        add_bind(HOST_KEYMAP_VOLUME_UP, (int)SDLK_KP_PLUS, 0);
    if (s_actions[HOST_KEYMAP_VOLUME_DOWN].count == 0)
        add_bind(HOST_KEYMAP_VOLUME_DOWN, (int)SDLK_KP_MINUS, 0);
}

/* Parse one "Ctrl+Alt+PageUp" token into key+mods. */
static void parse_one_token(HostKeymapAction action, char *tok) {
    int mods = 0;
    SDL_Keycode key;
    trim_inplace(tok);
    if (!tok[0] || ieq(tok, "(unbound)") || ieq(tok, "None")) return;
    for (;;) {
        if (starts_ci(tok, "Shift+")) {
            mods |= KMOD_SHIFT;
            tok += 6;
        } else if (starts_ci(tok, "Ctrl+")) {
            mods |= KMOD_CTRL;
            tok += 5;
        } else if (starts_ci(tok, "Alt+")) {
            mods |= KMOD_ALT;
            tok += 4;
        } else {
            break;
        }
    }
    trim_inplace(tok);
    if (!tok[0]) return;
    key = SDL_GetKeyFromName(tok);
    if (key == SDLK_UNKNOWN) {
        fprintf(stderr, "host_keymap: unknown key '%s'\n", tok);
        return;
    }
    add_bind(action, (int)key, mods);
}

static void parse_value(HostKeymapAction action, const char *value) {
    char buf[256];
    char *p;
    char *comma;
    if (!value) return;
    snprintf(buf, sizeof(buf), "%s", value);
    p = buf;
    while (p && *p) {
        comma = strchr(p, ',');
        if (comma) *comma = 0;
        parse_one_token(action, p);
        p = comma ? comma + 1 : NULL;
    }
}

static HostKeymapAction action_for_key(const char *name) {
    if (ieq(name, "VolumeUp")) return HOST_KEYMAP_VOLUME_UP;
    if (ieq(name, "VolumeDown")) return HOST_KEYMAP_VOLUME_DOWN;
    return HOST_KEYMAP_ACTION_COUNT;
}

void host_keymap_load(const char *config_ini_path) {
    FILE *f;
    char line[512];
    int in_keymap = 0;

    clear_all();
    if (!config_ini_path || !config_ini_path[0]) {
        apply_defaults();
        return;
    }
    f = fopen(config_ini_path, "rb");
    if (!f) {
        apply_defaults();
        return;
    }
    while (fgets(line, sizeof(line), f)) {
        char *p = line;
        char *eq;
        char *key;
        char *val;
        HostKeymapAction act;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == 0 || *p == ';' || *p == '#') continue;
        if (*p == '[') {
            char *end = strchr(p, ']');
            if (end) *end = 0;
            in_keymap = ieq(p + 1, "KeyMap");
            continue;
        }
        if (!in_keymap) continue;
        eq = strchr(p, '=');
        if (!eq) continue;
        *eq = 0;
        key = p;
        val = eq + 1;
        trim_inplace(key);
        trim_inplace(val);
        act = action_for_key(key);
        if (act == HOST_KEYMAP_ACTION_COUNT) continue;
        /* Explicit empty unbinds (no keypad fallback for that action until
         * apply_defaults — empty means user cleared it; still fall back). */
        s_actions[act].count = 0;
        parse_value(act, val);
    }
    fclose(f);
    apply_defaults();
}

int host_keymap_match(HostKeymapAction action, int keycode, int mod) {
    const HostKeyAction *a;
    const int relevant = (int)(KMOD_CTRL | KMOD_ALT | KMOD_SHIFT);
    int i;
    if (action < 0 || action >= HOST_KEYMAP_ACTION_COUNT) return 0;
    a = &s_actions[action];
    for (i = 0; i < a->count; i++) {
        if (a->binds[i].keycode != keycode) continue;
        if ((mod & relevant) == a->binds[i].mods) return 1;
    }
    return 0;
}
