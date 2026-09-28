// genesis_binds.c — Genesis-native bind persistence bridge (see genesis_binds.h).
//
// Reads/writes segagenesisrecomp's settings.ini [input.pN] key.<Name>/pad.<Name>
// lines in runner/app_config.c's exact grammar, surgically (all other sections
// and lines — [video], device/pad_type/deadzone, comments — are preserved).
// Defaults mirror the engine's input_map_init_defaults() byte-for-byte so an
// absent file displays exactly what the game would use.

#include "genesis_binds.h"
#include "genesis_profile.h"      // LNG_GENESIS_PAD_BUTTON_COUNT (rebind-spec order)
#include "launcher_sdlcompat.h"   // SDL header (2 or 3)

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GEN_NBTN LNG_GENESIS_PAD_BUTTON_COUNT

// ini key NAMEs, rebind-spec order == engine GenesisButton order. Exact case:
// app_config.c's button_by_name() matches with strcmp against
// input_button_name()'s "Up".."Mode" spellings.
static const char* kGenKeyName[GEN_NBTN] = {
    "Up", "Down", "Left", "Right",
    "A", "B", "C", "Start",
    "X", "Y", "Z", "Mode",
};

typedef struct { int kind, code, axis_dir; } GenPadBind;

// ---- engine defaults (input_map_init_defaults(), mirrored exactly) ----------
// Gamepad codes are SDL_GameControllerButton values (numerically identical in
// SDL2 and SDL3): A=0 B=1 X=2 Y=3 BACK=4 START=6 LSHOULDER=9 RSHOULDER=10
// DPAD_UP=11 DPAD_DOWN=12 DPAD_LEFT=13 DPAD_RIGHT=14.
static const int kGenDefaultKeyP1[GEN_NBTN] = {
    /* Up    */ SDL_SCANCODE_UP,     /* Down  */ SDL_SCANCODE_DOWN,
    /* Left  */ SDL_SCANCODE_LEFT,   /* Right */ SDL_SCANCODE_RIGHT,
    /* A     */ SDL_SCANCODE_Z,      /* B     */ SDL_SCANCODE_X,
    /* C     */ SDL_SCANCODE_C,      /* Start */ SDL_SCANCODE_RETURN,
    /* X     */ SDL_SCANCODE_A,      /* Y     */ SDL_SCANCODE_S,
    /* Z     */ SDL_SCANCODE_D,      /* Mode  */ SDL_SCANCODE_BACKSPACE,
};
static const int kGenDefaultKeyP2[GEN_NBTN] = {
    /* Up    */ SDL_SCANCODE_I,      /* Down  */ SDL_SCANCODE_K,
    /* Left  */ SDL_SCANCODE_J,      /* Right */ SDL_SCANCODE_L,
    /* A     */ SDL_SCANCODE_N,      /* B     */ SDL_SCANCODE_M,
    /* C     */ SDL_SCANCODE_COMMA,  /* Start */ SDL_SCANCODE_RSHIFT,
    /* X     */ SDL_SCANCODE_U,      /* Y     */ SDL_SCANCODE_O,
    /* Z     */ SDL_SCANCODE_P,      /* Mode  */ SDL_SCANCODE_SLASH,
};
// Same gamepad layout both players (engine: d-pad + B/A/X/Start face
// mapping — Genesis B on the face-bottom button — with Y/LB/RB/Back for
// X/Y/Z/Mode).
static const GenPadBind kGenDefaultPad[GEN_NBTN] = {
    /* Up    */ { RUI_GEN_BIND_BUTTON, 11, 0 },  /* DPAD_UP */
    /* Down  */ { RUI_GEN_BIND_BUTTON, 12, 0 },  /* DPAD_DOWN */
    /* Left  */ { RUI_GEN_BIND_BUTTON, 13, 0 },  /* DPAD_LEFT */
    /* Right */ { RUI_GEN_BIND_BUTTON, 14, 0 },  /* DPAD_RIGHT */
    /* A     */ { RUI_GEN_BIND_BUTTON,  1, 0 },  /* face-right (B on Xbox) */
    /* B     */ { RUI_GEN_BIND_BUTTON,  0, 0 },  /* face-bottom (A on Xbox) */
    /* C     */ { RUI_GEN_BIND_BUTTON,  2, 0 },  /* face-left (X on Xbox) */
    /* Start */ { RUI_GEN_BIND_BUTTON,  6, 0 },  /* START */
    /* X     */ { RUI_GEN_BIND_BUTTON,  3, 0 },  /* face-top (Y on Xbox) */
    /* Y     */ { RUI_GEN_BIND_BUTTON,  9, 0 },  /* LEFTSHOULDER */
    /* Z     */ { RUI_GEN_BIND_BUTTON, 10, 0 },  /* RIGHTSHOULDER */
    /* Mode  */ { RUI_GEN_BIND_BUTTON,  4, 0 },  /* BACK */
};

static int        s_key[2][GEN_NBTN];
static GenPadBind s_pad[2][GEN_NBTN];
static int        s_init = 0;

static void gen_seed_defaults(int player) {
    const int* def = player == 1 ? kGenDefaultKeyP2 : kGenDefaultKeyP1;
    for (int b = 0; b < GEN_NBTN; ++b) {
        s_key[player][b] = def[b];
        s_pad[player][b] = kGenDefaultPad[b];
    }
}

// Parse "button:N" / "axis:N:+" / "axis:N:-" / "none" — app_config.c's
// parse_pad_bind(), mirrored.
static void gen_parse_pad(const char* v, GenPadBind* out) {
    out->kind = RUI_GEN_BIND_NONE; out->code = 0; out->axis_dir = 0;
    if (!strncmp(v, "button:", 7)) {
        out->kind = RUI_GEN_BIND_BUTTON;
        out->code = atoi(v + 7);
    } else if (!strncmp(v, "axis:", 5)) {
        out->kind = RUI_GEN_BIND_AXIS;
        out->code = atoi(v + 5);
        const char* sign = strrchr(v, ':');
        out->axis_dir = (sign && sign[1] == '-') ? -1 : +1;
    }
}

// Format a pad bind — app_config.c's format_pad_bind(), mirrored.
static void gen_format_pad(const GenPadBind* b, char* out, size_t n) {
    if (b->kind == RUI_GEN_BIND_BUTTON)
        snprintf(out, n, "button:%d", b->code);
    else if (b->kind == RUI_GEN_BIND_AXIS)
        snprintf(out, n, "axis:%d:%c", b->code, b->axis_dir < 0 ? '-' : '+');
    else
        snprintf(out, n, "none");
}

static char* gen_trim(char* s) {
    while (*s == ' ' || *s == '\t') s++;
    char* e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n'))
        *--e = '\0';
    return s;
}

static int gen_button_by_name(const char* name) {
    for (int b = 0; b < GEN_NBTN; ++b)
        if (strcmp(name, kGenKeyName[b]) == 0) return b;
    return -1;
}

// Overlay whatever [input.pN] key.*/pad.* lines exist in `path` onto the
// in-memory store (missing lines keep their seeded defaults). Same parsing
// rules as app_config.c's app_config_load().
static void gen_load_ini(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) return;
    char line[512];
    int player = -1;   // -1 not an input section, 0 p1, 1 p2
    while (fgets(line, sizeof(line), f)) {
        char* s = gen_trim(line);
        if (!*s || *s == ';' || *s == '#') continue;
        if (*s == '[') {
            char* end = strchr(s, ']');
            if (!end) continue;
            *end = '\0';
            const char* name = s + 1;
            player = -1;
            if      (!strcmp(name, "input.p1")) player = 0;
            else if (!strcmp(name, "input.p2")) player = 1;
            continue;
        }
        if (player < 0) continue;
        char* eq = strchr(s, '=');
        if (!eq) continue;
        *eq = '\0';
        char* key = gen_trim(s);
        char* val = gen_trim(eq + 1);
        if (!strncmp(key, "key.", 4)) {
            int b = gen_button_by_name(key + 4);
            if (b >= 0) s_key[player][b] = atoi(val);
        } else if (!strncmp(key, "pad.", 4)) {
            int b = gen_button_by_name(key + 4);
            if (b >= 0) gen_parse_pad(val, &s_pad[player][b]);
        }
    }
    fclose(f);
}

// ---- surgical writer ---------------------------------------------------------
// Upsert one player's 12 key.* + 12 pad.* lines inside [input.pN], preserving
// every other line and section byte-for-byte (device/pad_type/deadzone lines,
// comments, [video]/[audio]/[launcher], the other player's section). Creates
// the section at EOF when absent.

static char* gen_strdup(const char* s) {
    size_t n = strlen(s) + 1;
    char* d = (char*)malloc(n);
    if (d) memcpy(d, s, n);
    return d;
}

static int gen_line_is_key(const char* line, const char* key) {
    const char* i = line;
    while (*i == ' ' || *i == '\t') ++i;
    size_t kl = strlen(key);
    if (strncmp(i, key, kl) != 0) return 0;
    i += kl;
    while (*i == ' ' || *i == '\t') ++i;
    return *i == '=';
}

static void gen_write_player(const char* path, int player) {
    // read the whole file into a line array (preserving blank lines)
    char** lines = NULL; int n = 0, cap = 0;
    FILE* f = fopen(path, "rb");
    if (f) {
        char buf[512];
        while (fgets(buf, sizeof(buf), f)) {
            size_t l = strlen(buf);
            while (l && (buf[l-1] == '\n' || buf[l-1] == '\r')) buf[--l] = '\0';
            if (n == cap) { cap = cap ? cap * 2 : 64; lines = (char**)realloc(lines, sizeof(char*) * cap); }
            lines[n++] = gen_strdup(buf);
        }
        fclose(f);
    }

    char section[16];
    snprintf(section, sizeof(section), "[input.p%d]", player + 1);

    // locate the section body [ks, ke)
    int ks = -1, ke = n;
    for (int i = 0; i < n; ++i) {
        const char* p = lines[i];
        while (*p == ' ' || *p == '\t') ++p;
        if (*p != '[') continue;
        if (ks >= 0) { ke = i; break; }
        if (!strncmp(p, section, strlen(section))) ks = i + 1;
    }

    // compose the 24 assignments
    char assign[GEN_NBTN * 2][64];
    char keyname[GEN_NBTN * 2][32];
    for (int b = 0; b < GEN_NBTN; ++b) {
        snprintf(keyname[b], sizeof(keyname[b]), "key.%s", kGenKeyName[b]);
        snprintf(assign[b], sizeof(assign[b]), "key.%s = %d", kGenKeyName[b], s_key[player][b]);
        char padv[32];
        gen_format_pad(&s_pad[player][b], padv, sizeof(padv));
        snprintf(keyname[GEN_NBTN + b], sizeof(keyname[GEN_NBTN + b]), "pad.%s", kGenKeyName[b]);
        snprintf(assign[GEN_NBTN + b], sizeof(assign[GEN_NBTN + b]), "pad.%s = %s", kGenKeyName[b], padv);
    }

    if (ks < 0) {
        // section absent: append it at EOF
        if (n && lines[n-1][0]) {
            if (n == cap) { cap += 4; lines = (char**)realloc(lines, sizeof(char*) * cap); }
            lines[n++] = gen_strdup("");
        }
        if (n + 1 + GEN_NBTN * 2 > cap) { cap = n + 1 + GEN_NBTN * 2 + 4; lines = (char**)realloc(lines, sizeof(char*) * cap); }
        lines[n++] = gen_strdup(section);
        for (int a = 0; a < GEN_NBTN * 2; ++a) lines[n++] = gen_strdup(assign[a]);
    } else {
        for (int a = 0; a < GEN_NBTN * 2; ++a) {
            int hit = -1;
            for (int i = ks; i < ke; ++i)
                if (gen_line_is_key(lines[i], keyname[a])) { hit = i; break; }
            if (hit >= 0) {
                free(lines[hit]);
                lines[hit] = gen_strdup(assign[a]);
            } else {
                // insert before the section's trailing blank lines
                int at = ke;
                while (at > ks) {
                    const char* p = lines[at-1];
                    while (*p == ' ' || *p == '\t') ++p;
                    if (*p) break;
                    --at;
                }
                if (n == cap) { cap += 8; lines = (char**)realloc(lines, sizeof(char*) * cap); }
                for (int i = n; i > at; --i) lines[i] = lines[i-1];
                lines[at] = gen_strdup(assign[a]);
                ++n; ++ke;
            }
        }
    }

    FILE* out = fopen(path, "wb");
    if (out) {
        for (int i = 0; i < n; ++i) { fputs(lines[i], out); fputc('\n', out); }
        fclose(out);
    }
    for (int i = 0; i < n; ++i) free(lines[i]);
    free(lines);
}

// ---- public API ----------------------------------------------------------------

void rui_genesis_binds_init(const char* path) {
    gen_seed_defaults(0);
    gen_seed_defaults(1);
    gen_load_ini(path);
    s_init = 1;
}

static void gen_ensure_init(const char* path) {
    if (!s_init) rui_genesis_binds_init(path);
}

int rui_genesis_binds_get_key(const char* path, int player, int b) {
    gen_ensure_init(path);
    if (player < 0 || player > 1 || b < 0 || b >= GEN_NBTN) return 0;
    return s_key[player][b];
}

void rui_genesis_binds_get_pad(const char* path, int player, int b,
                               int* kind, int* code, int* axis_dir) {
    gen_ensure_init(path);
    GenPadBind v = { RUI_GEN_BIND_NONE, 0, 0 };
    if (player >= 0 && player <= 1 && b >= 0 && b < GEN_NBTN) v = s_pad[player][b];
    if (kind)     *kind     = v.kind;
    if (code)     *code     = v.code;
    if (axis_dir) *axis_dir = v.axis_dir;
}

void rui_genesis_binds_set_key(const char* path, int player, int b, int scancode) {
    gen_ensure_init(path);
    if (player < 0 || player > 1 || b < 0 || b >= GEN_NBTN) return;
    s_key[player][b] = scancode;
    gen_write_player(path, player);
}

void rui_genesis_binds_set_pad(const char* path, int player, int b,
                               int kind, int code, int axis_dir) {
    gen_ensure_init(path);
    if (player < 0 || player > 1 || b < 0 || b >= GEN_NBTN) return;
    s_pad[player][b].kind     = kind;
    s_pad[player][b].code     = code;
    s_pad[player][b].axis_dir = kind == RUI_GEN_BIND_AXIS ? (axis_dir < 0 ? -1 : +1) : 0;
    gen_write_player(path, player);
}

void rui_genesis_binds_reset(const char* path, int player) {
    gen_ensure_init(path);
    if (player < 0 || player > 1) return;
    gen_seed_defaults(player);
    gen_write_player(path, player);
}
