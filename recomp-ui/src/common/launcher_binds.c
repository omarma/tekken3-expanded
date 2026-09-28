// launcher_binds.c — real binding persistence (keybinds.ini + config.ini [KeyMap]).

#include "launcher_binds.h"
#include "launcher_sdlcompat.h"   // SDL header (2 or 3)
#include "keybinds.h"             // engine keyboard-binding store
#include "launcher_system.h"      // SystemProfile / ControllerSpec.button_count
#include "consoles/psx/psx_binds.h"   // PSX-native keybind bridge (psx_keybinds.c format)
#include "consoles/psx/psx_pad_binds.h" // PSX gamepad input.ini per-GUID bridge
#include "consoles/n64/n64_binds.h"   // N64-native input.cfg bridge (kb+pad tables)
#include "consoles/nes/nes_binds.h"   // NES-native keybind bridge (nesrecomp keybinds.c format)
#include "consoles/genesis/genesis_binds.h"   // Genesis-native bridge (settings.ini [input.pN])
#include "consoles/gb/gb_binds.h"     // Game Boy-native bridge (keybinds.ini [controls])

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// MSVC spells these differently than POSIX.
#ifdef _MSC_VER
  #define strtok_r     strtok_s
  #define strncasecmp  _strnicmp
  #define strdup       _strdup
#endif

const char* g_launcher_config_path = NULL;
const char* g_launcher_keybinds_path = NULL;

// Per-system rebind-spec index -> keybinds.c button index. keybinds order is
// a,b,x,y,l,r,start,select,up,down,left,right,l2,r2,l3,r3 (see keybinds.h).
//
// SNES rebind spec order (launcher_system.h kSnesPadButtons): Up,Down,Left,
// Right,A,B,X,Y,L,R,Start,Select. UNCHANGED from before per-system vocab —
// SNES bind persistence stays byte-identical (indices 0..11, same mapping).
//
// PSX no longer routes through this generic table/keybinds.c at all — see
// consoles/psx/psx_binds.c, which persists through psxrecomp's own
// psx_keybinds.c format instead so rebinds actually reach the game (routing
// PSX's 24 buttons through this 16-slot generic format silently discarded
// the 8 stick-direction binds and, worse, wrote a file the game's runtime
// can't parse at all). Every profile that still uses this table today
// borrows kSnesPadButtons (launcher_system.h stub macro), so it always
// matches LNG_SNES_PAD_BUTTON_COUNT.
static const int kKbIndexSnes[LNG_SNES_PAD_BUTTON_COUNT] = {
    /* UP    */ 8, /* DOWN  */ 9, /* LEFT  */ 10, /* RIGHT */ 11,
    /* A     */ 0, /* B     */ 1, /* X     */ 2,  /* Y     */ 3,
    /* L     */ 4, /* R     */ 5, /* START */ 6,  /* SELECT*/ 7,
};

// Resolve the keybinds-index table (and its length) for the model's ACTIVE
// SystemProfile. PSX is handled entirely by the native bridge below (see
// is_psx_profile()) before this is ever consulted; GBA persists through the
// generic store with its own 10-button vocabulary (kGbaKbIndex,
// consoles/gba/gba_profile.h); everything else is SNES-shaped (12 buttons).
static const int* active_kb_index(const LauncherModel* m, int* out_n) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    if (prof && prof->id && !strcmp(prof->id, "gba")) {
        *out_n = LNG_GBA_PAD_BUTTON_COUNT;
        return kGbaKbIndex;
    }
    *out_n = LNG_SNES_PAD_BUTTON_COUNT;
    return kKbIndexSnes;
}

// ---- PSX-native keybind bridge ---------------------------------------------
// Lives in consoles/psx/psx_binds.c (the console's own unit) — for a PSX
// SystemProfile, persistence routes through psxrecomp's native 24-scancode
// psx_keybinds.c format instead of the generic keybinds.c store, so rebinds
// actually reach the game. This file only decides WHICH store to use (by the
// active profile) and resolves the file path.
static int is_psx_profile(const LauncherModel* m) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    return prof && prof->id && !strcmp(prof->id, "psx");
}

// NES routes to its own native bridge too (consoles/nes/nes_binds.c): the
// nesrecomp runner's keybinds.ini format has 8 NES-named keys plus [zapper]
// and [gamepad1]/[gamepad2] sections the generic store's whole-file rewrite
// would destroy.
static int is_nes_profile(const LauncherModel* m) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    return prof && prof->id && !strcmp(prof->id, "nes");
}

static const char* keybinds_file_path(void) {
    return (g_launcher_keybinds_path && g_launcher_keybinds_path[0])
             ? g_launcher_keybinds_path : "keybinds.ini";
}

// input.ini lives next to keybinds.ini (same exe dir the runtime uses).
static const char* psx_input_ini_path(void) {
    static char buf[1024];
    const char* kb = keybinds_file_path();
    const char* slash = strrchr(kb, '/');
#ifdef _WIN32
    const char* bslash = strrchr(kb, '\\');
    if (bslash && (!slash || bslash > slash)) slash = bslash;
#endif
    if (!slash) {
        snprintf(buf, sizeof(buf), "input.ini");
        return buf;
    }
    size_t dir_len = (size_t)(slash - kb + 1);
    if (dir_len >= sizeof(buf)) dir_len = sizeof(buf) - 1;
    memcpy(buf, kb, dir_len);
    buf[dir_len] = '\0';
    strncat(buf, "input.ini", sizeof(buf) - strlen(buf) - 1);
    return buf;
}

static const char* psx_player_guid(const LauncherModel* m, int player /*1-based*/) {
    if (!m || player < 1 || player > LNG_MAX_PLAYERS) return "";
    return m->s.player_gamepad_guid[player - 1];
}

/* Defined below; load() hydrates names after init. */
void launcher_binds_hydrate_psx_pad_names(LauncherModel* m);

// ---- N64-native input.cfg bridge --------------------------------------------
// Lives in consoles/n64/n64_binds.c. The N64 runners persist bindings in
// their own input.cfg format — TWO device-type tables (keyboard, controller —
// shared by all pads, NOT per-port) with two alternate slots per input, where
// a controller bind can be a pad button, a signed pad axis, or a raw joystick
// field. This file only decides WHICH store to use and, for N64, WHICH device
// table a player edits: the one their current input source selects.
static int is_n64_profile(const LauncherModel* m) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    return prof && prof->id && !strcmp(prof->id, "n64");
}

static const char* n64_binds_file_path(void) {
    return (g_launcher_keybinds_path && g_launcher_keybinds_path[0])
             ? g_launcher_keybinds_path : "input.cfg";
}

// Device table (0 kb / 1 pad) player p's Configure page edits.
static int n64_device_for_player(const LauncherModel* m, int player /*0-based*/) {
    return m->s.player_src[player] == 2 ? 1 : 0;
}

// ---- Genesis-native bind bridge ----------------------------------------------
// Lives in consoles/genesis/genesis_binds.c — for a Genesis SystemProfile,
// persistence routes through segagenesisrecomp's own settings.ini
// [input.pN] key.<Name>/pad.<Name> format (runner/app_config.c) instead of
// the generic keybinds.c store, so rebinds actually reach the game's
// g_input_map. Note the DIFFERENT default filename: the Genesis engine's
// bind store is settings.ini, not keybinds.ini.
static int is_genesis_profile(const LauncherModel* m) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    return prof && prof->id && !strcmp(prof->id, "genesis");
}

// ---- Game Boy-native bind bridge ---------------------------------------------
// Lives in consoles/gb/gb_binds.c — for a gb/gbc SystemProfile, persistence
// routes through gb-recompiled's own keybinds.ini [controls] format (SDL
// scancode names) instead of the generic keybinds.c store, so rebinds reach
// the game. Single player (the Game Boy is a one-player handheld). Both the
// "gb" and "gbc" profiles share this bridge; the default file is keybinds.ini.
static int is_gb_profile(const LauncherModel* m) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    return prof && prof->id && (!strcmp(prof->id, "gb") || !strcmp(prof->id, "gbc"));
}

static const char* gb_binds_file_path(void) {
    // gb-recompiled drives input from runtime_prefs.ini keyboard.<btn>.0 lines
    // (keybinds.ini [controls] is vestigial). The seam points keybinds_path at
    // the exe-anchored runtime_prefs.ini; fall back to it by name too.
    return (g_launcher_keybinds_path && g_launcher_keybinds_path[0])
             ? g_launcher_keybinds_path : "runtime_prefs.ini";
}

static const char* genesis_binds_file_path(void) {
    return (g_launcher_keybinds_path && g_launcher_keybinds_path[0])
             ? g_launcher_keybinds_path : "settings.ini";
}

// The engine's config.ini [KeyMap] keys, in LngHotkey order.
static const char* kHotkeyKey[LNG_HK_COUNT] = {
    "Fullscreen", "Reset", "Pause", "PauseDimmed", "Turbo",
    "WindowBigger", "WindowSmaller", "VolumeUp", "VolumeDown",
    "DisplayPerf", "ToggleRenderer",
    "SolarBrighter", "SolarDimmer", "SolarLive"
};
// Built-in defaults (shown when config.ini has no line; "" = unbound).
static const char* kHotkeyDef[LNG_HK_COUNT] = {
    "Alt+Return", "Ctrl+R", "Shift+P", "P", "Tab",
    /* WindowBigger/Smaller unbound; VolumeUp/Down default keypad +/-
     * (psxrecomp host_keymap reads these from [KeyMap]). */
    "", "", "Keypad +", "Keypad -", "F", "R",
    "", "", ""
};

static void copy_str(char* d, size_t cap, const char* s) {
    if (!d || !cap) return;
    if (!s) { d[0] = 0; return; }
    size_t n = strlen(s); if (n >= cap) n = cap - 1;
    memcpy(d, s, n); d[n] = 0;
}

static const char* scancode_label(SDL_Scancode sc) {
    if (sc == SDL_SCANCODE_UNKNOWN) return "(unbound)";
    /* Mouse buttons are bound as pseudo-scancodes ABOVE SDL keyboard space
     * (512 + SDL button), so SDL_GetScancodeName knows nothing about them
     * and every mouse bind rendered as "(unbound)" - the bind had actually
     * been written and persisted, it was purely a display failure. */
    if ((int)sc > 512 && (int)sc <= 517) {
        static const char* const kMouseNames[5] =
            { "Mouse1", "Mouse2", "Mouse3", "Mouse4", "Mouse5" };
        return kMouseNames[(int)sc - 513];
    }
    const char* n = SDL_GetScancodeName(sc);
    return (n && n[0]) ? n : "(unbound)";
}

// Display label for a Genesis gamepad bind: SDL's own controller button/axis
// names ("dpup", "a", "leftshoulder"; axes get a direction suffix, "leftx+").
static void genesis_pad_label(int kind, int code, int axis_dir, char* out, size_t cap) {
    if (kind == RUI_GEN_BIND_BUTTON) {
        const char* n = SDL_GetGamepadStringForButton((LNG_GamepadButton)code);
        copy_str(out, cap, (n && n[0]) ? n : "(unbound)");
    } else if (kind == RUI_GEN_BIND_AXIS) {
        const char* n = SDL_GetGamepadStringForAxis((LNG_GamepadAxis)code);
        char buf[32];
        snprintf(buf, sizeof(buf), "%s%c", (n && n[0]) ? n : "axis",
                 axis_dir < 0 ? '-' : '+');
        copy_str(out, cap, buf);
    } else {
        copy_str(out, cap, "(unbound)");
    }
}

static void reload_player_display(LauncherModel* m, int player) {
    if (is_psx_profile(m)) {
        if (player < 1 || player > LNG_MAX_PLAYERS) return;
        const char* guid = psx_player_guid(m, player);
        for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b) {
            copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                     scancode_label((SDL_Scancode)rui_psx_binds_get_slot(
                         keybinds_file_path(), player - 1, b, 0)));
            copy_str(m->binds_alt[player - 1][b],
                     sizeof(m->binds_alt[player - 1][b]),
                     scancode_label((SDL_Scancode)rui_psx_binds_get_slot(
                         keybinds_file_path(), player - 1, b, 1)));
            rui_psx_pad_binds_label(psx_input_ini_path(), guid, b,
                                    m->pad_binds[player - 1][b],
                                    (int)sizeof(m->pad_binds[player - 1][b]));
        }
        return;
    }
    if (is_nes_profile(m)) {
        for (int b = 0; b < LNG_NES_PAD_BUTTON_COUNT; ++b)
            copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                     scancode_label((SDL_Scancode)rui_nes_binds_get(
                         keybinds_file_path(), player - 1, b)));
        return;
    }
    if (is_genesis_profile(m)) {
        const char* path = genesis_binds_file_path();
        for (int b = 0; b < LNG_GENESIS_PAD_BUTTON_COUNT; ++b) {
            copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                     scancode_label((SDL_Scancode)rui_genesis_binds_get_key(path, player - 1, b)));
            int kind = 0, code = 0, dir = 0;
            rui_genesis_binds_get_pad(path, player - 1, b, &kind, &code, &dir);
            genesis_pad_label(kind, code, dir,
                              m->pad_binds[player - 1][b], sizeof(m->pad_binds[player - 1][b]));
        }
        return;
    }
    if (is_gb_profile(m)) {
        if (player != 1) return;   // Game Boy is single-player
        const char* path = gb_binds_file_path();
        for (int b = 0; b < LNG_GB_PAD_BUTTON_COUNT; ++b)
            copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                     scancode_label((SDL_Scancode)rui_gb_binds_get(path, b)));
        return;
    }
    if (is_n64_profile(m)) {
        // Per-device-TYPE tables: every player assigned the same device kind
        // shows (and edits) the same table — exactly the SS Anne contract.
        const int dev = n64_device_for_player(m, player - 1);
        for (int b = 0; b < LNG_N64_PAD_BUTTON_COUNT; ++b) {
            int type = 0, id = -1;
            rui_n64_binds_get(n64_binds_file_path(), dev, b, 0, &type, &id);
            rui_n64_binds_label(type, id, m->binds[player - 1][b],
                                sizeof(m->binds[player - 1][b]));
            rui_n64_binds_get(n64_binds_file_path(), dev, b, 1, &type, &id);
            rui_n64_binds_label(type, id, m->binds_alt[player - 1][b],
                                sizeof(m->binds_alt[player - 1][b]));
        }
        return;
    }
    if (player > 2) return;   // generic keybinds.c store is 2-player
    int n = 0;
    const int* kb_index = active_kb_index(m, &n);
    for (int b = 0; b < n; ++b) {
        SDL_Scancode sc = recompui_keybinds_get_button(player, kb_index[b]);
        copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]), scancode_label(sc));
    }
}

void launcher_binds_refresh_camera(LauncherModel* m) {
    if (!m || !is_nes_profile(m)) return;
    for (int action = 0; action < LNG_CAMERA_BIND_COUNT; ++action) {
        copy_str(
            m->camera_binds[action], sizeof(m->camera_binds[action]),
            scancode_label((SDL_Scancode)rui_nes_camera_bind_get(
                keybinds_file_path(), action)));
    }
}

// ---- config.ini [KeyMap] surgical read/write (ported from the legacy launcher) --

static int ieq(const char* a, size_t alen, const char* b) {
    size_t bl = strlen(b);
    if (alen != bl) return 0;
    for (size_t i = 0; i < alen; ++i)
        if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) return 0;
    return 1;
}

static char* read_whole(const char* path, long* out_len) {
    FILE* f = fopen(path, "rb");
    if (!f) { *out_len = 0; return NULL; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char* buf = (char*)malloc((size_t)n + 1);
    if (buf) { *out_len = (long)fread(buf, 1, (size_t)n, f); buf[*out_len] = 0; }
    fclose(f);
    return buf;
}

static const char* config_path(void) {
    return (g_launcher_config_path && g_launcher_config_path[0])
             ? g_launcher_config_path : "config.ini";
}

// Fill m->hotkeys[] from config.ini [KeyMap] (or defaults where absent).
static void reload_hotkey_display(LauncherModel* m) {
    for (int h = 0; h < LNG_HK_COUNT; ++h)
        copy_str(m->hotkeys[h], sizeof(m->hotkeys[h]), kHotkeyDef[h]);

    long len = 0; char* text = read_whole(config_path(), &len);
    if (!text) return;

    int in_keymap = 0;
    char* save = NULL;
    for (char* line = strtok_r(text, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
        char* p = line;
        while (*p == ' ' || *p == '\t') ++p;
        size_t l = strlen(p);
        while (l && (p[l-1] == '\r' || p[l-1] == ' ' || p[l-1] == '\t')) p[--l] = 0;
        if (!*p || *p == '#') continue;
        if (*p == '[') {
            char* close = strchr(p, ']');
            size_t sl = close ? (size_t)(close - p - 1) : strlen(p + 1);
            in_keymap = ieq(p + 1, sl, "KeyMap");
            continue;
        }
        if (!in_keymap) continue;
        char* eq = strchr(p, '=');
        if (!eq) continue;
        char* ke = eq; while (ke > p && (ke[-1] == ' ' || ke[-1] == '\t')) --ke;
        size_t klen = (size_t)(ke - p);
        char* v = eq + 1; while (*v == ' ' || *v == '\t') ++v;
        char* hash = strchr(v, '#'); if (hash) *hash = 0;
        size_t vl = strlen(v); while (vl && (v[vl-1] == ' ' || v[vl-1] == '\t')) v[--vl] = 0;
        for (int h = 0; h < LNG_HK_COUNT; ++h)
            if (ieq(p, klen, kHotkeyKey[h])) { copy_str(m->hotkeys[h], sizeof(m->hotkeys[h]), v); break; }
    }
    free(text);
}

// Does `line` (leading ws / optional '#') assign `key`? Mirrors config.c.
static int line_is_key(const char* line, const char* key) {
    const char* i = line;
    while (*i == ' ' || *i == '\t') ++i;
    if (*i == '#') { ++i; while (*i == ' ' || *i == '\t') ++i; }
    size_t kl = strlen(key);
    if (strncasecmp(i, key, kl) != 0) return 0;
    i += kl;
    while (*i == ' ' || *i == '\t') ++i;
    return *i == '=';
}

// Surgically set "Key = value" inside [section] of `path`, preserving every
// other line (comments, blank lines, and unrelated sections — e.g. the NES
// keybinds.ini's [zapper]/[gamepad1]/[gamepad2] sections survive untouched).
// Creates the file and/or section when absent. Exported (launcher_binds.h)
// for console units whose native bind files carry sections the launcher
// doesn't own (consoles/nes/nes_binds.c).
void launcher_ini_kv_write(const char* path, const char* section,
                           const char* key, const char* value) {
    long len = 0; char* text = read_whole(path, &len);
    /* split into a growable line array, PRESERVING blank lines (strtok would
     * collapse them, losing the user's config formatting). */
    int cap = 64, n = 0;
    char** lines = (char**)malloc(sizeof(char*) * cap);
    if (text) {
        char* start = text;
        for (long i = 0; i <= len; ++i) {
            if (i == len || text[i] == '\n') {
                char* end = text + i;
                if (end > start && end[-1] == '\r') end[-1] = 0;
                else if (i < len) text[i] = 0;
                else text[i] = 0;
                if (i == len && start == text + len) break;  // no trailing empty
                if (n == cap) { cap *= 2; lines = (char**)realloc(lines, sizeof(char*) * cap); }
                lines[n++] = strdup(start);
                start = text + i + 1;
            }
        }
    }
    char assign[128];
    snprintf(assign, sizeof(assign), "%s = %s", key, value ? value : "");

    /* locate [section] body [start,end) */
    int ks = -1, ke = -1;
    for (int i = 0; i < n; ++i) {
        const char* p = lines[i]; while (*p == ' ' || *p == '\t') ++p;
        if (*p != '[') continue;
        const char* close = strchr(p, ']');
        size_t sl = close ? (size_t)(close - p - 1) : strlen(p + 1);
        if (ks >= 0) { ke = i; break; }
        if (ieq(p + 1, sl, section)) ks = i + 1;
    }
    if (ks >= 0 && ke < 0) ke = n;

    if (ks < 0) {
        char header[96];
        snprintf(header, sizeof(header), "[%s]", section);
        if (n == cap) { cap += 4; lines = (char**)realloc(lines, sizeof(char*) * cap); }
        if (n && lines[n-1][0]) lines[n++] = strdup("");
        if (n == cap) { cap += 4; lines = (char**)realloc(lines, sizeof(char*) * cap); }
        lines[n++] = strdup(header);
        if (n == cap) { cap += 4; lines = (char**)realloc(lines, sizeof(char*) * cap); }
        lines[n++] = strdup(assign);
    } else {
        int hit = -1;
        for (int i = ks; i < ke; ++i) if (line_is_key(lines[i], key)) { hit = i; break; }
        if (hit >= 0) { free(lines[hit]); lines[hit] = strdup(assign); }
        else {
            int at = ke;
            while (at > ks) { const char* p = lines[at-1]; while (*p==' '||*p=='\t') ++p; if (*p) break; --at; }
            if (n == cap) { cap += 4; lines = (char**)realloc(lines, sizeof(char*) * cap); }
            for (int i = n; i > at; --i) lines[i] = lines[i-1];
            lines[at] = strdup(assign); ++n;
        }
    }

    FILE* f = fopen(path, "wb");
    if (f) { for (int i = 0; i < n; ++i) { fputs(lines[i], f); fputc('\n', f); } fclose(f); }
    for (int i = 0; i < n; ++i) free(lines[i]);
    free(lines); free(text);
}

// Original config.ini [KeyMap] entry point, now a thin wrapper.
static void keymap_write(const char* key, const char* value) {
    launcher_ini_kv_write(config_path(), "KeyMap", key, value);
}

// Format SDL keycode + mods the way config.c's ParseKeyArray reads back.
static void format_hotkey(int keycode, int kmod, char* out, size_t cap) {
    out[0] = 0;
    if (keycode == 0) return;              // unbound
    char buf[96]; buf[0] = 0;
    if (kmod & SDL_KMOD_CTRL)  strncat(buf, "Ctrl+",  sizeof(buf)-strlen(buf)-1);
    if (kmod & SDL_KMOD_ALT)   strncat(buf, "Alt+",   sizeof(buf)-strlen(buf)-1);
    if (kmod & SDL_KMOD_SHIFT) strncat(buf, "Shift+", sizeof(buf)-strlen(buf)-1);
    const char* kn = SDL_GetKeyName((SDL_Keycode)keycode);
    if (!kn || !kn[0]) return;
    strncat(buf, kn, sizeof(buf)-strlen(buf)-1);
    copy_str(out, cap, buf);
}

// ---- public API -------------------------------------------------------------

void launcher_binds_load(LauncherModel* m, const char* config_path_in, const char* keybinds_path_in) {
    g_launcher_config_path = config_path_in;
    g_launcher_keybinds_path = keybinds_path_in;
    if (is_psx_profile(m)) {
        rui_psx_binds_init(keybinds_file_path());   // load/generate psx_keybinds.c-format keybinds.ini
        rui_psx_pad_binds_init(psx_input_ini_path()); // gamepad maps (input.ini)
        launcher_binds_hydrate_psx_pad_names(m);
    } else if (is_n64_profile(m)) {
        rui_n64_binds_init(n64_binds_file_path());      // load input.cfg (defaults if absent; never seeds the file)
    } else if (is_nes_profile(m)) {
        rui_nes_binds_init(keybinds_file_path());   // load/generate nesrecomp-format keybinds.ini
        // Zapper switches live in the same file ([zapper]); surface them on
        // the model for the controller page's Zapper block.
        int zm = 1, zc = 1;
        rui_nes_zapper_get(keybinds_file_path(), &zm, &zc);
        m->zapper_mouse     = zm != 0;
        m->zapper_crosshair = zc != 0;
    } else if (is_genesis_profile(m)) {
        rui_genesis_binds_init(genesis_binds_file_path());   // overlay settings.ini [input.pN] onto engine defaults
    } else if (is_gb_profile(m)) {
        rui_gb_binds_init(gb_binds_file_path());   // load/generate keybinds.ini [controls] (gb-recompiled format)
    } else {
        recompui_keybinds_init(NULL);              // load/generate keybinds.ini (exe-anchored)
    }
    launcher_binds_refresh(m);
    launcher_binds_refresh_camera(m);
    reload_hotkey_display(m);
}

void launcher_binds_refresh(LauncherModel* m) {
    for (int p = 1; p <= LNG_MAX_PLAYERS; ++p)
        reload_player_display(m, p);
}

int launcher_binds_wants_pad_capture(const LauncherModel* m, int player) {
    if (player < 1 || player > LNG_MAX_PLAYERS) return 0;
    return is_n64_profile(m) && n64_device_for_player(m, player - 1) == 1;
}

// Persist the Zapper switches to keybinds.ini [zapper] (surgical: the rest of
// the file — player binds, gamepad sections, comments — is preserved).
// Called by launcher_model_toggle_zapper_* on every flip.
void launcher_binds_set_zapper(int mouse_enabled, int crosshair) {
    rui_nes_zapper_set(keybinds_file_path(), mouse_enabled, crosshair);
}

void launcher_binds_set_camera(LauncherModel* m, int action, int scancode) {
    if (!m || !is_nes_profile(m) ||
        action < 0 || action >= LNG_CAMERA_BIND_COUNT)
        return;
    rui_nes_camera_bind_set(keybinds_file_path(), action, scancode);
    copy_str(m->camera_binds[action], sizeof(m->camera_binds[action]),
             scancode_label((SDL_Scancode)scancode));
}

void launcher_binds_reset_camera(LauncherModel* m) {
    if (!m || !is_nes_profile(m)) return;
    rui_nes_camera_bind_reset(keybinds_file_path());
    launcher_binds_refresh_camera(m);
}

/* Slot-aware setter for stores that keep an alternate bind per input.
 * PSX keeps two (primary + alt, either may be a mouse pseudo-scancode). */
void launcher_binds_set_button_slot(LauncherModel* m, int player, int b,
                                    int slot, int scancode) {
    if (!m || !is_psx_profile(m)) return;
    if (player < 1 || player > LNG_MAX_PLAYERS) return;
    if (b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT) return;
    rui_psx_binds_set_slot(keybinds_file_path(), player - 1, b, slot, scancode);
    char* dst = (slot == 1) ? m->binds_alt[player - 1][b] : m->binds[player - 1][b];
    size_t cap = (slot == 1) ? sizeof(m->binds_alt[player - 1][b])
                             : sizeof(m->binds[player - 1][b]);
    copy_str(dst, cap, scancode_label((SDL_Scancode)scancode));
}

void launcher_binds_set_button(LauncherModel* m, int player, int b, int scancode) {
    if (is_n64_profile(m)) {
        // Keyboard capture into the N64 store routes through the field API
        // (slot 0) so there is exactly one write path for that store.
        launcher_binds_set_field(m, player, b, 0, RUI_N64_FIELD_KEY, scancode);
        return;
    }
    if (is_psx_profile(m)) {
        launcher_binds_set_button_slot(m, player, b, 0, scancode);
        return;
    }
    if (player < 1 || player > 2) return;
    if (is_nes_profile(m)) {
        if (b < 0 || b >= LNG_NES_PAD_BUTTON_COUNT) return;
        rui_nes_binds_set(keybinds_file_path(), player - 1, b, scancode);
        copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                 scancode_label((SDL_Scancode)scancode));
        return;
    }
    if (is_genesis_profile(m)) {
        if (b < 0 || b >= LNG_GENESIS_PAD_BUTTON_COUNT) return;
        rui_genesis_binds_set_key(genesis_binds_file_path(), player - 1, b, scancode);
        copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                 scancode_label((SDL_Scancode)scancode));
        return;
    }
    if (is_gb_profile(m)) {
        if (player != 1 || b < 0 || b >= LNG_GB_PAD_BUTTON_COUNT) return;
        rui_gb_binds_set(gb_binds_file_path(), b, scancode);
        copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
                 scancode_label((SDL_Scancode)scancode));
        return;
    }
    int n = 0;
    const int* kb_index = active_kb_index(m, &n);
    if (b < 0 || b >= n) return;
    recompui_keybinds_set_button(player, kb_index[b], (SDL_Scancode)scancode);
    recompui_keybinds_save();
    copy_str(m->binds[player - 1][b], sizeof(m->binds[player - 1][b]),
             scancode_label((SDL_Scancode)scancode));
}

void launcher_binds_set_field(LauncherModel* m, int player, int b, int slot,
                              int type, int id) {
    if (!is_n64_profile(m)) return;   // field binds exist only in the N64 store
    if (player < 1 || player > LNG_MAX_PLAYERS) return;
    if (b < 0 || b >= LNG_N64_PAD_BUTTON_COUNT) return;
    const int dev = n64_device_for_player(m, player - 1);
    rui_n64_binds_set(n64_binds_file_path(), dev, b, slot, type, id);
    // The table is shared by every player on the same device kind — refresh
    // ALL players' display strings, not just the one that captured.
    launcher_binds_refresh(m);
}

void launcher_binds_set_pad_button(LauncherModel* m, int player, int b,
                                   int kind, int code, int axis_dir) {
    if (player < 1 || player > LNG_MAX_PLAYERS) return;
    if (is_psx_profile(m)) {
        if (b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT) return;
        const char* guid = psx_player_guid(m, player);
        if (!guid[0]) return;
        rui_psx_pad_binds_set(psx_input_ini_path(), guid, b, kind, code, axis_dir);
        // Keep the pad registered (name/deadzone unchanged unless first create).
        rui_psx_pad_binds_remember(psx_input_ini_path(), guid,
                                   m->player_pad_name[player - 1], -1);
        rui_psx_pad_binds_label(psx_input_ini_path(), guid, b,
                                m->pad_binds[player - 1][b],
                                (int)sizeof(m->pad_binds[player - 1][b]));
        return;
    }
    // Genesis: has_pad_binds console (key + pad pair per logical button).
    if (!is_genesis_profile(m)) return;
    if (player > 2) return;
    if (b < 0 || b >= LNG_GENESIS_PAD_BUTTON_COUNT) return;
    rui_genesis_binds_set_pad(genesis_binds_file_path(), player - 1, b, kind, code, axis_dir);
    genesis_pad_label(kind, code, axis_dir,
                      m->pad_binds[player - 1][b], sizeof(m->pad_binds[player - 1][b]));
}

static int psx_guid_claimed_by_other(const LauncherModel* m, int self,
                                     const char* guid) {
    if (!m || !guid || !guid[0]) return 0;
    for (int o = 0; o < LNG_MAX_PLAYERS; ++o) {
        if (o == self) continue;
        if (m->s.player_src[o] == 2 && m->s.player_gamepad_guid[o][0] &&
            !strcmp(m->s.player_gamepad_guid[o], guid))
            return 1;
    }
    return 0;
}

static void psx_fallback_pad_label(const char* guid, char* out, size_t cap) {
    if (!out || !cap) return;
    if (guid && guid[0]) {
        size_t n = strlen(guid);
        if (n >= 8)
            snprintf(out, cap, "Controller …%s", guid + n - 8);
        else
            snprintf(out, cap, "Controller %s", guid);
        return;
    }
    copy_str(out, cap, "Controller");
}

void launcher_binds_hydrate_psx_pad_names(LauncherModel* m) {
    if (!m || !is_psx_profile(m)) return;
    const char* path = psx_input_ini_path();
    for (int p = 0; p < LNG_MAX_PLAYERS; ++p) {
        if (m->s.player_src[p] != 2) continue;
        const char* guid = m->s.player_gamepad_guid[p];
        if (!guid[0]) continue;
        if (m->player_pad_name[p][0] &&
            strcmp(m->player_pad_name[p], "Gamepad") != 0)
            continue;
        rui_psx_pad_binds_name(path, guid, m->player_pad_name[p],
                               (int)sizeof(m->player_pad_name[p]));
        if (!m->player_pad_name[p][0] ||
            !strcmp(m->player_pad_name[p], "Gamepad"))
            psx_fallback_pad_label(guid, m->player_pad_name[p],
                                   sizeof(m->player_pad_name[p]));
    }
}

void launcher_binds_sync_psx_pad_sources(LauncherModel* m,
                                         const LauncherPad* pads, int pad_count) {
    if (!m || !is_psx_profile(m)) return;
    const char* path = psx_input_ini_path();
    const int nplayers = launcher_model_visible_player_count(m);

    for (int p = 0; p < nplayers; ++p) {
        if (m->s.player_src[p] != 2) continue;

        // Legacy device="gamepad" with no GUID: pin to a concrete pad.
        if (!m->s.player_gamepad_guid[p][0]) {
            int chosen = -1;
            if (pads && pad_count > 0) {
                for (int i = 0; i < pad_count; ++i) {
                    if (!pads[i].guid[0]) continue;
                    if (psx_guid_claimed_by_other(m, p, pads[i].guid)) continue;
                    chosen = i;
                    break;
                }
                if (chosen < 0) chosen = 0;
                launcher_model_set_source(m, p, 2, pads[chosen].id,
                                          pads[chosen].name, pads[chosen].guid);
            } else {
                const int known = rui_psx_pad_binds_known_count(path);
                for (int i = 0; i < known; ++i) {
                    char guid[40] = {}, name[64] = {};
                    if (!rui_psx_pad_binds_known_at(path, i, guid, (int)sizeof(guid),
                                                    name, (int)sizeof(name)))
                        continue;
                    if (psx_guid_claimed_by_other(m, p, guid)) continue;
                    if (!name[0] || !strcmp(name, "Gamepad"))
                        psx_fallback_pad_label(guid, name, sizeof(name));
                    launcher_model_set_source(m, p, 2, 0, name, guid);
                    break;
                }
            }
        }

        const char* guid = m->s.player_gamepad_guid[p];
        if (!guid[0]) continue;

        // Prefer the live SDL name when this GUID is connected.
        int live = -1;
        if (pads) {
            for (int i = 0; i < pad_count; ++i) {
                if (pads[i].guid[0] && !strcmp(pads[i].guid, guid)) {
                    live = i;
                    break;
                }
            }
        }
        const int custom = rui_psx_pad_binds_name_is_custom(path, guid);
        if (live >= 0) {
            m->player_pad_id[p] = pads[live].id;
            if (custom) {
                // Keep the user's rename in the model / dropdown.
                char reg[64] = {};
                rui_psx_pad_binds_name(path, guid, reg, (int)sizeof(reg));
                if (reg[0])
                    copy_str(m->player_pad_name[p],
                             sizeof(m->player_pad_name[p]), reg);
            } else if (pads[live].name[0] &&
                       strcmp(pads[live].name, "Gamepad") != 0) {
                const int name_changed =
                    strcmp(m->player_pad_name[p], pads[live].name) != 0;
                copy_str(m->player_pad_name[p], sizeof(m->player_pad_name[p]),
                         pads[live].name);
                if (name_changed)
                    rui_psx_pad_binds_remember(path, guid, pads[live].name, -1);
            }
            continue;
        }

        // Disconnected: registry name, else a non-generic fallback.
        char reg[64] = {};
        rui_psx_pad_binds_name(path, guid, reg, (int)sizeof(reg));
        if (reg[0] && strcmp(reg, "Gamepad") != 0)
            copy_str(m->player_pad_name[p], sizeof(m->player_pad_name[p]), reg);
        else if (!m->player_pad_name[p][0] ||
                 !strcmp(m->player_pad_name[p], "Gamepad"))
            psx_fallback_pad_label(guid, m->player_pad_name[p],
                                   sizeof(m->player_pad_name[p]));
        m->player_pad_id[p] = 0;
    }
}

void launcher_binds_apply_psx_pad_profile(LauncherModel* m, int player) {
    if (!m || !is_psx_profile(m)) return;
    player = (player < 0) ? 0 : (player >= LNG_MAX_PLAYERS ? LNG_MAX_PLAYERS - 1
                                                           : player);
    if (m->s.player_src[player] != 2) return;
    const char* guid = m->s.player_gamepad_guid[player];
    if (!guid[0]) return;
    const char* path = psx_input_ini_path();
    char name[64] = {};
    rui_psx_pad_binds_name(path, guid, name, (int)sizeof(name));
    if (name[0] && strcmp(name, "Gamepad") != 0)
        copy_str(m->player_pad_name[player], sizeof(m->player_pad_name[player]),
                 name);
    m->s.deadzone[player] = rui_psx_pad_binds_deadzone(path, guid);
    reload_player_display(m, player + 1);
}

void launcher_binds_rename_psx_gamepad(LauncherModel* m, int player,
                                       const char* name) {
    if (!m || !is_psx_profile(m) || !name || !name[0]) return;
    if (player < 1 || player > LNG_MAX_PLAYERS) return;
    const int p = player - 1;
    const char* guid = m->s.player_gamepad_guid[p];
    if (!guid[0]) return;
    rui_psx_pad_binds_rename(psx_input_ini_path(), guid, name);
    copy_str(m->player_pad_name[p], sizeof(m->player_pad_name[p]), name);
}

void launcher_binds_save_psx_gamepad(LauncherModel* m, int player) {
    if (!m || !is_psx_profile(m)) return;
    if (player < 1 || player > LNG_MAX_PLAYERS) return;
    const int p = player - 1;
    if (m->s.player_src[p] != 2) return;
    const char* guid = m->s.player_gamepad_guid[p];
    if (!guid[0]) return;
    const char* path = psx_input_ini_path();
    char name[64];
    if (m->player_pad_name[p][0] && strcmp(m->player_pad_name[p], "Gamepad") != 0)
        copy_str(name, sizeof(name), m->player_pad_name[p]);
    else
        psx_fallback_pad_label(guid, name, sizeof(name));
    const int custom = rui_psx_pad_binds_name_is_custom(path, guid);
    int dz = m->s.deadzone[p];
    if (dz < 0) dz = 0;
    if (dz > 100) dz = 100;
    rui_psx_pad_binds_save_profile(path, guid, name, custom, dz);
    copy_str(m->player_pad_name[p], sizeof(m->player_pad_name[p]), name);
    reload_player_display(m, player);
}

void launcher_binds_delete_psx_gamepad(LauncherModel* m, int player) {
    if (!m || !is_psx_profile(m)) return;
    if (player < 1 || player > LNG_MAX_PLAYERS) return;
    const char* guid = psx_player_guid(m, player);
    if (!guid[0]) return;
    rui_psx_pad_binds_delete(psx_input_ini_path(), guid);
    // Clear any other players that pointed at the same GUID.
    for (int p = 0; p < LNG_MAX_PLAYERS; ++p) {
        if (m->s.player_src[p] == 2 &&
            m->s.player_gamepad_guid[p][0] &&
            !strcmp(m->s.player_gamepad_guid[p], guid)) {
            launcher_model_set_source(m, p, 1, 0, NULL, NULL);
        }
    }
    launcher_binds_refresh(m);
}

void launcher_binds_prepare_psx_launch(LauncherModel* m,
                                       const LauncherPad* pads, int pad_count) {
    if (!m || !is_psx_profile(m)) return;
    const char* path = psx_input_ini_path();
    for (int p = 0; p < LNG_MAX_PLAYERS; ++p) {
        if (m->s.player_src[p] != 2) continue;
        // Bare "Gamepad" (legacy auto): pin to a live pad when available so
        // settings.toml stores a real GUID and input.ini gets a mapping.
        if (!m->s.player_gamepad_guid[p][0] && pads && pad_count > 0) {
            // Prefer a pad not already claimed by an earlier player.
            int chosen = -1;
            for (int i = 0; i < pad_count; ++i) {
                int claimed = 0;
                for (int o = 0; o < p; ++o) {
                    if (m->s.player_src[o] == 2 &&
                        m->s.player_gamepad_guid[o][0] &&
                        !strcmp(m->s.player_gamepad_guid[o], pads[i].guid)) {
                        claimed = 1;
                        break;
                    }
                }
                if (!claimed) { chosen = i; break; }
            }
            if (chosen < 0) chosen = 0;
            launcher_model_set_source(m, p, 2, pads[chosen].id,
                                      pads[chosen].name, pads[chosen].guid);
        }
        const char* guid = m->s.player_gamepad_guid[p];
        if (!guid[0]) continue;
        char name[64];
        const int custom = rui_psx_pad_binds_name_is_custom(path, guid);
        if (custom) {
            rui_psx_pad_binds_name(path, guid, name, (int)sizeof(name));
            if (!name[0])
                psx_fallback_pad_label(guid, name, sizeof(name));
        } else if (m->player_pad_name[p][0] &&
                   strcmp(m->player_pad_name[p], "Gamepad") != 0) {
            copy_str(name, sizeof(name), m->player_pad_name[p]);
        } else {
            psx_fallback_pad_label(guid, name, sizeof(name));
        }
        if (!custom && pads) {
            for (int i = 0; i < pad_count; ++i) {
                if (pads[i].guid[0] && !strcmp(pads[i].guid, guid) &&
                    pads[i].name[0]) {
                    copy_str(name, sizeof(name), pads[i].name);
                    copy_str(m->player_pad_name[p],
                             sizeof(m->player_pad_name[p]), name);
                    m->player_pad_id[p] = pads[i].id;
                    break;
                }
            }
        }
        int dz = m->s.deadzone[p];
        if (dz < 0) dz = 0;
        if (dz > 100) dz = 100;
        rui_psx_pad_binds_save_profile(path, guid, name, custom, dz);
    }
}

int launcher_binds_psx_known_count(void) {
    return rui_psx_pad_binds_known_count(psx_input_ini_path());
}

int launcher_binds_psx_known_at(int index, char* guid, int guid_cap,
                                char* name, int name_cap) {
    return rui_psx_pad_binds_known_at(psx_input_ini_path(), index,
                                      guid, guid_cap, name, name_cap);
}

int launcher_binds_psx_name_is_custom(const char* guid) {
    if (!guid || !guid[0]) return 0;
    return rui_psx_pad_binds_name_is_custom(psx_input_ini_path(), guid);
}

void launcher_binds_reset_player(LauncherModel* m, int player) {
    if (is_n64_profile(m)) {
        if (player < 1 || player > LNG_MAX_PLAYERS) return;
        rui_n64_binds_reset_device(n64_binds_file_path(),
                                   n64_device_for_player(m, player - 1));
        launcher_binds_refresh(m);
        return;
    }
    if (is_psx_profile(m)) {
        if (player < 1 || player > LNG_MAX_PLAYERS) return;
        // Configure's Gamepad Bindings panel resets the selected gamepad's
        // input.ini map. Keyboard keybinds.ini is left alone (not shown there).
        const char* guid = psx_player_guid(m, player);
        if (guid[0])
            rui_psx_pad_binds_reset(psx_input_ini_path(), guid);
        else
            rui_psx_binds_reset(keybinds_file_path(), player - 1);
        reload_player_display(m, player);
        return;
    }
    if (player < 1 || player > 2) return;
    if (is_nes_profile(m)) {
        rui_nes_binds_reset(keybinds_file_path(), player - 1);
        reload_player_display(m, player);
        return;
    }
    if (is_genesis_profile(m)) {
        rui_genesis_binds_reset(genesis_binds_file_path(), player - 1);
        reload_player_display(m, player);
        return;
    }
    if (is_gb_profile(m)) {
        if (player != 1) return;
        rui_gb_binds_reset(gb_binds_file_path());
        reload_player_display(m, player);
        return;
    }
    recompui_keybinds_reset_player(player);
    recompui_keybinds_save();
    reload_player_display(m, player);
}

void launcher_binds_set_hotkey(LauncherModel* m, LngHotkey h, int keycode, int kmod) {
    if (h < 0 || h >= LNG_HK_COUNT) return;
    char val[64];
    format_hotkey(keycode, kmod, val, sizeof(val));
    keymap_write(kHotkeyKey[h], val);
    copy_str(m->hotkeys[h], sizeof(m->hotkeys[h]), val[0] ? val : "(unbound)");
}
