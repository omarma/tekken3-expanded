// psx_pad_binds.c — PSX gamepad bind persistence (input.ini per GUID).

#include "psx_pad_binds.h"
#include "psx_profile.h"
#include "launcher_sdlcompat.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PSX_PAD_SRC_CAP 48
#define PSX_PAD_GUID_CAP 40
#define PSX_PAD_NAME_CAP 64

static const char* kPsxPadKeyName[LNG_PSX_PAD_BUTTON_COUNT] = {
    "up", "down", "left", "right",
    "triangle", "circle", "cross", "square",
    "l1", "l2", "r1", "r2",
    "l3", "r3", "start", "select",
    "ls_up", "ls_down", "ls_left", "ls_right",
    "rs_up", "rs_down", "rs_left", "rs_right",
};

static const char* kPsxPadDefaults[LNG_PSX_PAD_BUTTON_COUNT] = {
    "dpup", "dpdown", "dpleft", "dpright",
    "y", "b", "a", "x",
    "leftshoulder", "lefttrigger", "rightshoulder", "righttrigger",
    "leftstick", "rightstick", "start", "back",
    "lefty-", "lefty+", "leftx-", "leftx+",
    "righty-", "righty+", "rightx-", "rightx+",
};

typedef struct {
    char guid[PSX_PAD_GUID_CAP];
    char name[PSX_PAD_NAME_CAP];   // display name (driver default or custom)
    int  name_custom;              // 1 = user renamed; sync won't overwrite
    int  deadzone_pct;             // 0..100; default RUI_PSX_PAD_DEFAULT_DEADZONE_PCT
    char src[LNG_PSX_PAD_BUTTON_COUNT][PSX_PAD_SRC_CAP];
    int used;
} PsxPadGuidMap;

static char s_global[LNG_PSX_PAD_BUTTON_COUNT][PSX_PAD_SRC_CAP];
static PsxPadGuidMap s_maps[RUI_PSX_PAD_MAX_KNOWN];
static int s_init = 0;
static char s_path[1024];

static void copy_str(char* d, size_t cap, const char* s) {
    if (!d || !cap) return;
    if (!s) { d[0] = 0; return; }
    size_t n = strlen(s);
    if (n >= cap) n = cap - 1;
    memcpy(d, s, n);
    d[n] = 0;
}

static void seed_defaults_into(char dest[][PSX_PAD_SRC_CAP]) {
    for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b)
        copy_str(dest[b], PSX_PAD_SRC_CAP, kPsxPadDefaults[b]);
}

static void tolower_inplace(char* s) {
    for (; *s; ++s) *s = (char)tolower((unsigned char)*s);
}

static int key_index(const char* key) {
    for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b)
        if (!strcmp(key, kPsxPadKeyName[b])) return b;
    return -1;
}

static PsxPadGuidMap* find_map(const char* guid) {
    if (!guid || !guid[0]) return NULL;
    for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i)
        if (s_maps[i].used && !strcmp(s_maps[i].guid, guid))
            return &s_maps[i];
    return NULL;
}

static PsxPadGuidMap* alloc_map(const char* guid) {
    PsxPadGuidMap* m = find_map(guid);
    if (m) return m;
    for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i) {
        if (s_maps[i].used) continue;
        memset(&s_maps[i], 0, sizeof(s_maps[i]));
        s_maps[i].used = 1;
        s_maps[i].deadzone_pct = RUI_PSX_PAD_DEFAULT_DEADZONE_PCT;
        copy_str(s_maps[i].guid, sizeof(s_maps[i].guid), guid);
        seed_defaults_into(s_maps[i].src);
        for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b)
            if (s_global[b][0])
                copy_str(s_maps[i].src[b], PSX_PAD_SRC_CAP, s_global[b]);
        return &s_maps[i];
    }
    return NULL;
}

static int clamp_dz(int pct) {
    if (pct < 0) return 0;
    if (pct > 100) return 100;
    return pct;
}

static void parse_mapping_line(char dest[][PSX_PAD_SRC_CAP], const char* key,
                               const char* val) {
    char kbuf[32];
    copy_str(kbuf, sizeof(kbuf), key);
    tolower_inplace(kbuf);
    int b = key_index(kbuf);
    if (b < 0) return;
    char vbuf[PSX_PAD_SRC_CAP];
    copy_str(vbuf, sizeof(vbuf), val);
    char* comma = strchr(vbuf, ',');
    if (comma) *comma = '\0';
    char* s = vbuf;
    while (*s && isspace((unsigned char)*s)) ++s;
    size_t n = strlen(s);
    while (n > 0 && isspace((unsigned char)s[n - 1])) s[--n] = '\0';
    tolower_inplace(s);
    if (!strcmp(s, "none") || !strcmp(s, "disabled")) s[0] = '\0';
    copy_str(dest[b], PSX_PAD_SRC_CAP, s);
}

static void load_ini(const char* path) {
    seed_defaults_into(s_global);
    memset(s_maps, 0, sizeof(s_maps));

    FILE* f = fopen(path, "r");
    if (!f) return;

    char section[96] = "";
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r' ||
                         isspace((unsigned char)line[n - 1])))
            line[--n] = '\0';
        char* s = line;
        while (*s && isspace((unsigned char)*s)) ++s;
        if (!*s || *s == '#' || *s == ';') continue;
        if (*s == '[') {
            char* end = strchr(s, ']');
            if (end) *end = '\0';
            copy_str(section, sizeof(section), s + 1);
            tolower_inplace(section);
            if (!strncmp(section, "mapping.", 8)) {
                const char* guid = section + 8;
                if (guid[0]) alloc_map(guid);
            }
            continue;
        }
        char* eq = strchr(s, '=');
        if (!eq) continue;
        *eq = '\0';
        char* key = s;
        char* val = eq + 1;
        size_t kl = strlen(key);
        while (kl > 0 && isspace((unsigned char)key[kl - 1])) key[--kl] = '\0';
        while (*val && isspace((unsigned char)*val)) ++val;

        if (!strcmp(section, "mapping")) {
            parse_mapping_line(s_global, key, val);
        } else if (!strncmp(section, "mapping.", 8)) {
            PsxPadGuidMap* m = find_map(section + 8);
            if (!m) continue;
            char kbuf[32];
            copy_str(kbuf, sizeof(kbuf), key);
            tolower_inplace(kbuf);
            if (!strcmp(kbuf, "deadzone")) {
                m->deadzone_pct = clamp_dz(atoi(val));
            } else if (!strcmp(kbuf, "name_custom")) {
                m->name_custom = (atoi(val) != 0) ? 1 : 0;
            } else if (!strcmp(kbuf, "name")) {
                // Prefer [gamepads] name when both exist; only fill if empty.
                if (!m->name[0]) copy_str(m->name, sizeof(m->name), val);
            } else {
                parse_mapping_line(m->src, key, val);
            }
        } else if (!strcmp(section, "gamepads")) {
            char gbuf[PSX_PAD_GUID_CAP];
            copy_str(gbuf, sizeof(gbuf), key);
            tolower_inplace(gbuf);
            PsxPadGuidMap* m = alloc_map(gbuf);
            if (m) copy_str(m->name, sizeof(m->name), val);
        }
    }
    fclose(f);
}

static int section_is_ours(const char* sec) {
    return !strcmp(sec, "mapping") || !strncmp(sec, "mapping.", 8) ||
           !strcmp(sec, "gamepads");
}

static void write_ini(const char* path) {
    char* preserved = NULL;
    size_t preserved_len = 0;
    {
        FILE* in = fopen(path, "rb");
        if (in) {
            fseek(in, 0, SEEK_END);
            long n = ftell(in);
            fseek(in, 0, SEEK_SET);
            if (n > 0) {
                char* buf = (char*)malloc((size_t)n + 1);
                if (buf) {
                    size_t got = fread(buf, 1, (size_t)n, in);
                    buf[got] = '\0';
                    size_t cap = got + 1;
                    preserved = (char*)malloc(cap);
                    preserved_len = 0;
                    if (preserved) {
                        int skip = 0;
                        char* save = NULL;
                        for (char* line = strtok(buf, "\n"); line;
                             line = strtok(NULL, "\n")) {
                            char* p = line;
                            while (*p == ' ' || *p == '\t') ++p;
                            if (*p == '[') {
                                char sec[96];
                                copy_str(sec, sizeof(sec), p + 1);
                                char* br = strchr(sec, ']');
                                if (br) *br = '\0';
                                tolower_inplace(sec);
                                skip = section_is_ours(sec);
                            }
                            if (skip) continue;
                            size_t ln = strlen(line);
                            if (preserved_len + ln + 2 > cap) {
                                cap = (preserved_len + ln + 2) * 2;
                                char* nb = (char*)realloc(preserved, cap);
                                if (!nb) break;
                                preserved = nb;
                            }
                            memcpy(preserved + preserved_len, line, ln);
                            preserved_len += ln;
                            preserved[preserved_len++] = '\n';
                            preserved[preserved_len] = '\0';
                        }
                    }
                    free(buf);
                }
            }
            fclose(in);
        }
    }

    FILE* f = fopen(path, "w");
    if (!f) {
        free(preserved);
        return;
    }
    if (preserved && preserved_len) {
        fwrite(preserved, 1, preserved_len, f);
        if (preserved[preserved_len - 1] != '\n') fputc('\n', f);
    } else {
        fputs("; PSXRecomp input mapping. PSX buttons are active when any listed\n"
              "; source is pressed. Per-device overrides live in [mapping.<guid>].\n"
              "; [gamepads] lists previously used pads (guid = display name).\n\n"
              "[controller]\n"
              "enabled = true\n"
              "device = 0\n"
              "deadzone = 3277\n\n", f);
    }
    free(preserved);

    int any_named = 0;
    for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i)
        if (s_maps[i].used && s_maps[i].name[0]) { any_named = 1; break; }
    if (any_named) {
        fputs("[gamepads]\n", f);
        for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i) {
            if (!s_maps[i].used || !s_maps[i].name[0]) continue;
            fprintf(f, "%s = %s\n", s_maps[i].guid, s_maps[i].name);
        }
        fputc('\n', f);
    }

    fputs("[mapping]\n", f);
    for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b) {
        const char* v = s_global[b][0] ? s_global[b] : "none";
        fprintf(f, "%-9s = %s\n", kPsxPadKeyName[b], v);
    }
    fputc('\n', f);

    for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i) {
        if (!s_maps[i].used) continue;
        fprintf(f, "[mapping.%s]\n", s_maps[i].guid);
        fprintf(f, "%-9s = %d\n", "deadzone", clamp_dz(s_maps[i].deadzone_pct));
        fprintf(f, "%-9s = %d\n", "name_custom", s_maps[i].name_custom ? 1 : 0);
        for (int b = 0; b < LNG_PSX_PAD_BUTTON_COUNT; ++b) {
            const char* v = s_maps[i].src[b][0] ? s_maps[i].src[b] : "none";
            fprintf(f, "%-9s = %s\n", kPsxPadKeyName[b], v);
        }
        fputc('\n', f);
    }
    fclose(f);
}

static int file_has_stick_keys(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return 0;
    char line[256];
    int hit = 0;
    while (fgets(line, sizeof(line), f)) {
        char* s = line;
        while (*s && isspace((unsigned char)*s)) ++s;
        if (!strncmp(s, "ls_", 3) || !strncmp(s, "rs_", 3)) { hit = 1; break; }
    }
    fclose(f);
    return hit;
}

static void ensure_init(const char* path) {
    if (s_init && path && s_path[0] && !strcmp(s_path, path)) return;
    copy_str(s_path, sizeof(s_path), path ? path : "input.ini");
    load_ini(s_path);
    FILE* test = fopen(s_path, "r");
    if (!test) {
        write_ini(s_path);
    } else {
        fclose(test);
        if (!file_has_stick_keys(s_path))
            write_ini(s_path);
    }
    s_init = 1;
}

static void source_from_bind(int kind, int code, int axis_dir,
                             char* out, size_t cap) {
    out[0] = 0;
    if (kind == 1) {
        const char* n = SDL_GetGamepadStringForButton((LNG_GamepadButton)code);
        copy_str(out, cap, (n && n[0]) ? n : "");
    } else if (kind == 2) {
        const char* n = SDL_GetGamepadStringForAxis((LNG_GamepadAxis)code);
        char buf[32];
        snprintf(buf, sizeof(buf), "%s%c", (n && n[0]) ? n : "axis",
                 axis_dir < 0 ? '-' : '+');
        copy_str(out, cap, buf);
    }
}

void rui_psx_pad_binds_init(const char* path) {
    s_init = 0;
    ensure_init(path ? path : "input.ini");
}

void rui_psx_pad_binds_remember(const char* path, const char* guid,
                                const char* name, int deadzone_pct) {
    ensure_init(path);
    if (!guid || !guid[0]) return;
    PsxPadGuidMap* m = alloc_map(guid);
    if (!m) return;
    // Driver-name refresh: never clobber a user rename.
    if (!m->name_custom && name && name[0] && strcmp(name, "Gamepad") != 0)
        copy_str(m->name, sizeof(m->name), name);
    else if (!m->name[0] && name && name[0] && strcmp(name, "Gamepad") != 0)
        copy_str(m->name, sizeof(m->name), name);
    if (deadzone_pct >= 0)
        m->deadzone_pct = clamp_dz(deadzone_pct);
    write_ini(s_path);
}

void rui_psx_pad_binds_save_profile(const char* path, const char* guid,
                                    const char* name, int name_custom,
                                    int deadzone_pct) {
    ensure_init(path);
    if (!guid || !guid[0]) return;
    PsxPadGuidMap* m = alloc_map(guid);
    if (!m) return;
    if (name && name[0])
        copy_str(m->name, sizeof(m->name), name);
    m->name_custom = name_custom ? 1 : 0;
    m->deadzone_pct = clamp_dz(deadzone_pct >= 0
                                   ? deadzone_pct
                                   : RUI_PSX_PAD_DEFAULT_DEADZONE_PCT);
    write_ini(s_path);
}

void rui_psx_pad_binds_rename(const char* path, const char* guid,
                              const char* name) {
    ensure_init(path);
    if (!guid || !guid[0] || !name || !name[0]) return;
    PsxPadGuidMap* m = alloc_map(guid);
    if (!m) return;
    copy_str(m->name, sizeof(m->name), name);
    m->name_custom = 1;
    write_ini(s_path);
}

void rui_psx_pad_binds_delete(const char* path, const char* guid) {
    ensure_init(path);
    if (!guid || !guid[0]) return;
    PsxPadGuidMap* m = find_map(guid);
    if (!m) return;
    memset(m, 0, sizeof(*m));
    write_ini(s_path);
}

void rui_psx_pad_binds_label(const char* path, const char* guid, int b,
                             char* out, int cap) {
    ensure_init(path);
    if (!out || cap <= 0) return;
    out[0] = 0;
    if (b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT) {
        copy_str(out, (size_t)cap, "(unbound)");
        return;
    }
    const char* src = NULL;
    if (guid && guid[0]) {
        PsxPadGuidMap* m = find_map(guid);
        if (m) src = m->src[b];
    }
    if (!src || !src[0]) src = s_global[b];
    if (!src || !src[0]) src = kPsxPadDefaults[b];
    if (!src || !src[0]) copy_str(out, (size_t)cap, "(unbound)");
    else copy_str(out, (size_t)cap, src);
}

void rui_psx_pad_binds_set(const char* path, const char* guid, int b,
                           int kind, int code, int axis_dir) {
    ensure_init(path);
    if (!guid || !guid[0]) return;
    if (b < 0 || b >= LNG_PSX_PAD_BUTTON_COUNT) return;
    PsxPadGuidMap* m = alloc_map(guid);
    if (!m) return;
    source_from_bind(kind, code, axis_dir, m->src[b], PSX_PAD_SRC_CAP);
    write_ini(s_path);
}

void rui_psx_pad_binds_reset(const char* path, const char* guid) {
    ensure_init(path);
    if (!guid || !guid[0]) return;
    PsxPadGuidMap* m = alloc_map(guid);
    if (!m) return;
    seed_defaults_into(m->src);
    write_ini(s_path);
}

int rui_psx_pad_binds_known_count(const char* path) {
    ensure_init(path);
    int n = 0;
    for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i)
        if (s_maps[i].used) ++n;
    return n;
}

int rui_psx_pad_binds_known_at(const char* path, int index,
                               char* guid, int guid_cap,
                               char* name, int name_cap) {
    ensure_init(path);
    if (index < 0) return 0;
    int n = 0;
    for (int i = 0; i < RUI_PSX_PAD_MAX_KNOWN; ++i) {
        if (!s_maps[i].used) continue;
        if (n == index) {
            if (guid && guid_cap > 0)
                copy_str(guid, (size_t)guid_cap, s_maps[i].guid);
            if (name && name_cap > 0) {
                if (s_maps[i].name[0] && strcmp(s_maps[i].name, "Gamepad") != 0)
                    copy_str(name, (size_t)name_cap, s_maps[i].name);
                else {
                    size_t gl = strlen(s_maps[i].guid);
                    if (gl >= 8)
                        snprintf(name, (size_t)name_cap, "Controller …%s",
                                 s_maps[i].guid + gl - 8);
                    else
                        copy_str(name, (size_t)name_cap, "Controller");
                }
            }
            return 1;
        }
        ++n;
    }
    return 0;
}

void rui_psx_pad_binds_name(const char* path, const char* guid,
                            char* out, int cap) {
    ensure_init(path);
    if (!out || cap <= 0) return;
    out[0] = 0;
    PsxPadGuidMap* m = find_map(guid);
    if (m && m->name[0]) copy_str(out, (size_t)cap, m->name);
}

int rui_psx_pad_binds_name_is_custom(const char* path, const char* guid) {
    ensure_init(path);
    PsxPadGuidMap* m = find_map(guid);
    return (m && m->name_custom) ? 1 : 0;
}

int rui_psx_pad_binds_deadzone(const char* path, const char* guid) {
    ensure_init(path);
    PsxPadGuidMap* m = find_map(guid);
    if (!m) return RUI_PSX_PAD_DEFAULT_DEADZONE_PCT;
    return clamp_dz(m->deadzone_pct);
}
