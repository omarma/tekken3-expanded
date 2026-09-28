// gb_binds.c — Game Boy-native keybind persistence bridge (see gb_binds.h).
//
// Reads/writes gb-recompiled's runtime_prefs.ini keyboard.<action>.0 = key:<sc>
// bindings (the store that actually drives input; the keybinds.ini [controls]
// file is vestigial). All writes are a SURGICAL upsert of the eight primary
// keyboard lines — every other line of runtime_prefs.ini is preserved.

#include "gb_binds.h"
#include "gb_profile.h"           // LNG_GB_PAD_BUTTON_COUNT (rebind-spec order)
#include "launcher_sdlcompat.h"   // SDL header (2 or 3)

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Rebind-spec order (kGbPadButtons: Up/Down/Left/Right/A/B/Start/Select) ->
// engine input_action_config_name() spelling.
static const char* kGbActionName[LNG_GB_PAD_BUTTON_COUNT] = {
    "up", "down", "left", "right", "a", "b", "start", "select"
};

// gb-recompiled set_default_input_bindings() PRIMARY-slot (slot 0) defaults,
// in rebind-spec order. Note Select's primary default is Backspace (RShift is
// its secondary), and Start's is Return.
static const SDL_Scancode kGbDefaults[LNG_GB_PAD_BUTTON_COUNT] = {
    /* Up */ SDL_SCANCODE_UP,    /* Down */ SDL_SCANCODE_DOWN,
    /* Left */ SDL_SCANCODE_LEFT, /* Right */ SDL_SCANCODE_RIGHT,
    /* A */ SDL_SCANCODE_Z,      /* B */ SDL_SCANCODE_X,
    /* Start */ SDL_SCANCODE_RETURN, /* Select */ SDL_SCANCODE_BACKSPACE,
};

static SDL_Scancode s_gb_binds[LNG_GB_PAD_BUTTON_COUNT];
static int s_gb_binds_init = 0;

// ---- runtime_prefs.ini parse ---------------------------------------------------
// Overlay keyboard.<action>.0 = key:<int> lines onto the current store.
static void gb_load_prefs(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        char* s = line;
        while (*s == ' ' || *s == '\t') ++s;
        if (*s == '#' || *s == ';') continue;
        char* eq = strchr(s, '=');
        if (!eq) continue;
        *eq = '\0';
        char* key = s; char* val = eq + 1;
        size_t kl = strlen(key); while (kl && isspace((unsigned char)key[kl-1])) key[--kl] = '\0';
        while (*val == ' ' || *val == '\t') ++val;
        size_t vl = strlen(val);
        while (vl && (val[vl-1]=='\n'||val[vl-1]=='\r'||isspace((unsigned char)val[vl-1]))) val[--vl] = '\0';
        // Match "keyboard.<action>.0" against our eight primary bindings.
        for (int b = 0; b < LNG_GB_PAD_BUTTON_COUNT; ++b) {
            char want[48];
            snprintf(want, sizeof(want), "keyboard.%s.0", kGbActionName[b]);
            if (strcmp(key, want) == 0) {
                if (strncmp(val, "key:", 4) == 0)
                    s_gb_binds[b] = (SDL_Scancode)strtol(val + 4, NULL, 10);
                else if (strcmp(val, "none") == 0)
                    s_gb_binds[b] = SDL_SCANCODE_UNKNOWN;
                break;
            }
        }
    }
    fclose(f);
}

// ---- surgical upsert of the eight keyboard.<btn>.0 lines -----------------------
static char* gb_read_whole(const char* path, long* out_len) {
    FILE* f = fopen(path, "rb");
    if (!f) { *out_len = 0; return NULL; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char* buf = (char*)malloc((size_t)(n > 0 ? n : 0) + 1);
    if (buf) { *out_len = (long)fread(buf, 1, (size_t)(n > 0 ? n : 0), f); buf[*out_len] = 0; }
    fclose(f);
    return buf;
}

// Does `line` (leading ws) assign flat key `key` (before the '=')?
static int gb_line_is_key(const char* line, const char* key) {
    const char* i = line;
    while (*i == ' ' || *i == '\t') ++i;
    size_t kl = strlen(key);
    if (strncmp(i, key, kl) != 0) return 0;
    i += kl;
    while (*i == ' ' || *i == '\t') ++i;
    return *i == '=';
}

static void gb_write_prefs(const char* path) {
    long len = 0; char* text = gb_read_whole(path, &len);

    // split into a growable line array, preserving blank lines
    int cap = 128, n = 0;
    char** lines = (char**)malloc(sizeof(char*) * cap);
    if (text) {
        char* start = text;
        for (long i = 0; i <= len; ++i) {
            if (i == len || text[i] == '\n') {
                char* end = text + i;
                if (end > start && end[-1] == '\r') end[-1] = 0;
                if (i < len) text[i] = 0; else text[i] = 0;
                if (i == len && start == text + len) break;   // no trailing empty
                if (n == cap) { cap *= 2; lines = (char**)realloc(lines, sizeof(char*) * cap); }
                lines[n++] = strdup(start);
                start = text + i + 1;
            }
        }
    }

    // upsert each of the eight primary bindings
    for (int b = 0; b < LNG_GB_PAD_BUTTON_COUNT; ++b) {
        char key[48], assign[80];
        snprintf(key, sizeof(key), "keyboard.%s.0", kGbActionName[b]);
        if (s_gb_binds[b] == SDL_SCANCODE_UNKNOWN)
            snprintf(assign, sizeof(assign), "%s=none", key);
        else
            snprintf(assign, sizeof(assign), "%s=key:%d", key, (int)s_gb_binds[b]);
        int hit = -1;
        for (int i = 0; i < n; ++i) if (gb_line_is_key(lines[i], key)) { hit = i; break; }
        if (hit >= 0) { free(lines[hit]); lines[hit] = strdup(assign); }
        else {
            if (n == cap) { cap += 8; lines = (char**)realloc(lines, sizeof(char*) * cap); }
            lines[n++] = strdup(assign);
        }
    }

    FILE* f = fopen(path, "wb");
    if (f) { for (int i = 0; i < n; ++i) { fputs(lines[i], f); fputc('\n', f); } fclose(f); }
    for (int i = 0; i < n; ++i) free(lines[i]);
    free(lines); free(text);
}

// ---- public API ----------------------------------------------------------------
void rui_gb_binds_init(const char* path) {
    memcpy(s_gb_binds, kGbDefaults, sizeof(kGbDefaults));
    if (path) gb_load_prefs(path);   // overlay; do not create the file
    s_gb_binds_init = 1;
}

int rui_gb_binds_get(const char* path, int b) {
    if (!s_gb_binds_init) rui_gb_binds_init(path);
    if (b < 0 || b >= LNG_GB_PAD_BUTTON_COUNT) return SDL_SCANCODE_UNKNOWN;
    return (int)s_gb_binds[b];
}

void rui_gb_binds_set(const char* path, int b, int scancode) {
    if (b < 0 || b >= LNG_GB_PAD_BUTTON_COUNT) return;
    if (!s_gb_binds_init) rui_gb_binds_init(path);
    s_gb_binds[b] = (SDL_Scancode)scancode;
    if (path) gb_write_prefs(path);
}

void rui_gb_binds_reset(const char* path) {
    if (!s_gb_binds_init) rui_gb_binds_init(path);
    memcpy(s_gb_binds, kGbDefaults, sizeof(kGbDefaults));
    if (path) gb_write_prefs(path);
}
