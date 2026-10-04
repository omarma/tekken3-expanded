// launcher_android.c — the launcher on Android: native Android screens instead
// of the ImGui window.
//
// recomp_launcher_run_window() hands the LauncherModel here. The Java side
// (org.recompui.launcher.LauncherBridge + LauncherView, recomp-ui/android)
// draws the screens with Android widgets and reads and changes the model
// through the JNI functions below; this thread waits until the player presses
// PLAY or leaves. Everything a setting does stays in launcher_model.c; which
// settings exist comes from launcher_settings.c. Data crosses JNI as JSON.

#include "launcher_android.h"

#include "launcher_binds.h"
#include "launcher_input.h"
#include "launcher_settings.h"
#include "launcher_system.h"          // kPsxGamepadBindOrder (Buttons page)

#include <SDL3/SDL.h>
#include <jni.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static LauncherModel* g_model;
static SDL_Mutex*     g_lock;
static SDL_Condition* g_done;
static int            g_action = -1;      // LngAction once the player chose
static jclass         g_bridge;           // org.recompui.launcher.LauncherBridge
static LauncherPad    g_pads[LNG_MAX_PADS];
static int            g_pad_count;

// ---- JSON -------------------------------------------------------------------
typedef struct { char* p; size_t n, cap; } Json;

static void j_raw(Json* j, const char* s, size_t len) {
    if (j->n + len + 1 > j->cap) {
        size_t cap = j->cap ? j->cap : 1024;
        while (j->n + len + 1 > cap) cap *= 2;
        char* p = (char*)realloc(j->p, cap);
        if (!p) return;
        j->p = p; j->cap = cap;
    }
    memcpy(j->p + j->n, s, len);
    j->n += len;
    j->p[j->n] = '\0';
}
static void j_lit(Json* j, const char* s) { j_raw(j, s, strlen(s)); }
static void j_fmt(Json* j, const char* fmt, ...) {
    char buf[128];
    va_list ap; va_start(ap, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (len > 0) j_raw(j, buf, (size_t)(len < (int)sizeof(buf) ? len : (int)sizeof(buf) - 1));
}
static void j_str(Json* j, const char* s) {
    j_lit(j, "\"");
    for (const unsigned char* c = (const unsigned char*)(s ? s : ""); *c; ++c) {
        if (*c == '"' || *c == '\\') { char e[2] = { '\\', (char)*c }; j_raw(j, e, 2); }
        else if (*c == '\n') j_lit(j, "\\n");
        else if (*c < 0x20) j_fmt(j, "\\u%04x", *c);
        else j_raw(j, (const char*)c, 1);
    }
    j_lit(j, "\"");
}
static void j_key(Json* j, const char* key) { j_str(j, key); j_lit(j, ":"); }

// JSON may carry any UTF-8 (NewStringUTF only takes modified UTF-8).
static jstring to_jstring(JNIEnv* env, Json* j) {
    const char* s = j->p ? j->p : "";
    jsize len = (jsize)strlen(s);
    jbyteArray bytes = (*env)->NewByteArray(env, len);
    (*env)->SetByteArrayRegion(env, bytes, 0, len, (const jbyte*)s);
    jclass string_class = (*env)->FindClass(env, "java/lang/String");
    jmethodID ctor = (*env)->GetMethodID(env, string_class, "<init>", "([BLjava/lang/String;)V");
    jstring out = (jstring)(*env)->NewObject(env, string_class, ctor, bytes,
                                             (*env)->NewStringUTF(env, "UTF-8"));
    free(j->p);
    return out;
}

static char* dup_jstring(JNIEnv* env, jstring s) {
    if (!s) return NULL;
    const char* utf = (*env)->GetStringUTFChars(env, s, NULL);
    char* out = strdup(utf ? utf : "");
    (*env)->ReleaseStringUTFChars(env, s, utf);
    return out;
}

static int is_psx(const LauncherModel* m) {
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    return prof && prof->id && strcmp(prof->id, "psx") == 0;
}

// Player 1's default on a phone: a connected controller, else the touch
// screen (a phone has no keyboard). It applies while the game has never been
// played (no settings.toml in the data folder, the working directory); a
// Keyboard stored by an older build already became Touch (launcher_model.c).
static void default_player_one(LauncherModel* m) {
    if (m->lock_device || !is_psx(m)) return;
    if (access("settings.toml", F_OK) == 0) return;
    if (g_pad_count > 0) {
        launcher_model_set_source(m, 0, 2, g_pads[0].id, g_pads[0].name, g_pads[0].guid);
        launcher_binds_apply_psx_pad_profile(m, 0);
    } else {
        launcher_model_set_source(m, 0, 3, 0, NULL, NULL);
    }
    launcher_binds_refresh(m);
}

// ---- pad binding capture (the Buttons page) -----------------------------------------
// The same rules as the PC launcher's Configure page: while a bind is being
// captured, the first button press or decisive axis push of the player's pad
// is bound; Map All walks every button and waits for a full release between
// them. The Java side forwards the pad's key and motion events to SDL while
// capturing (the launcher screens have the focus); this thread reads them.
static void commit_pad(LauncherModel* m, int kind, int code, int axis_dir) {
    launcher_binds_set_pad_button(m, m->cfg_player + 1, m->capture_btn, kind, code, axis_dir);
    if (m->map_all_active) launcher_model_map_all_advance(m);
    else launcher_model_cancel_capture(m);
}

static void capture_event(LauncherModel* m, const SDL_Event* ev) {
    if (!m->capturing || !m->capture_pad) return;
    const uint32_t want = m->player_pad_id[m->cfg_player];
    uint32_t which = 0;
    if (ev->type == SDL_EVENT_GAMEPAD_BUTTON_DOWN || ev->type == SDL_EVENT_GAMEPAD_BUTTON_UP)
        which = (uint32_t)ev->gbutton.which;
    else if (ev->type == SDL_EVENT_GAMEPAD_AXIS_MOTION)
        which = (uint32_t)ev->gaxis.which;
    else
        return;
    if (!want || which != want) return;
    if (m->map_all_wait_release) {
        // The whole pad must be at rest before the next bind is taken.
        if (launcher_input_gamepad_at_rest(which)) m->map_all_wait_release = false;
        return;
    }
    if (ev->type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
        commit_pad(m, LNG_PADBIND_BUTTON, (int)ev->gbutton.button, 0);
    } else if (ev->type == SDL_EVENT_GAMEPAD_AXIS_MOTION) {
        const int val = (int)ev->gaxis.value, axis = (int)ev->gaxis.axis;
        if (val < 20000 && val > -20000) return;   // rest / jitter
        // Sticks bind only to the stick-direction rows (16..23), so a
        // twitchy stick cannot take L1 or Cross; triggers bind anywhere.
        const int stick = axis == SDL_GAMEPAD_AXIS_LEFTX || axis == SDL_GAMEPAD_AXIS_LEFTY ||
                          axis == SDL_GAMEPAD_AXIS_RIGHTX || axis == SDL_GAMEPAD_AXIS_RIGHTY;
        if (stick && !(m->capture_btn >= 16 && m->capture_btn < 24)) return;
        commit_pad(m, LNG_PADBIND_AXIS, axis, val < 0 ? -1 : +1);
    }
}

// ---- the run ------------------------------------------------------------------
// Model calls from the Java UI thread take the lock: the runtime's thread
// changes the model too while it captures a binding. The lock is made when the
// bridge registers, before the screens exist; a call before that finds no model
// and SDL_LockMutex(NULL) does nothing. SDL mutexes are recursive (finish()
// under LOCKED is fine). Nothing run under the lock calls back into Java.
#define LOCKED(body) do { SDL_Mutex* lk_ = g_lock; SDL_LockMutex(lk_); body; SDL_UnlockMutex(lk_); } while (0)

LngAction launcher_android_run(LauncherModel* m) {
    if (!g_bridge) return LNG_ACTION_LAUNCH;   // no launcher screens in this app
    SDL_InitSubSystem(SDL_INIT_GAMEPAD);
    if (!g_lock) { g_lock = SDL_CreateMutex(); g_done = SDL_CreateCondition(); }
    g_action = -1;
    g_pad_count = launcher_input_poll(g_pads, LNG_MAX_PADS, 0);
    launcher_binds_sync_psx_pad_sources(m, g_pads, g_pad_count);
    default_player_one(m);
    LOCKED(g_model = m);   // the screens see the model from here on

    JNIEnv* env = (JNIEnv*)SDL_GetAndroidJNIEnv();
    jmethodID show = (*env)->GetStaticMethodID(env, g_bridge, "show", "()V");
    (*env)->CallStaticVoidMethod(env, g_bridge, show);

    SDL_LockMutex(g_lock);
    while (g_action < 0) {
        SDL_WaitConditionTimeout(g_done, g_lock, m->capturing ? 15 : 100);
        // Keep SDL's queues (controllers, lifecycle) moving; pad events feed
        // a binding capture. Polled without the lock: while the app is paused
        // SDL_PollEvent blocks until it resumes, and the resume comes through
        // the UI thread, which must not be stuck waiting for the lock.
        SDL_UnlockMutex(g_lock);
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) LOCKED(capture_event(m, &ev));
        SDL_LockMutex(g_lock);
    }
    const LngAction action = (LngAction)g_action;
    g_model = NULL;        // a late call from the screens no longer touches it
    SDL_UnlockMutex(g_lock);

    if (action == LNG_ACTION_LAUNCH)
        launcher_binds_prepare_psx_launch(m, g_pads, g_pad_count);
    return action;
}

static void finish(int action) {
    SDL_LockMutex(g_lock);
    g_action = action;
    SDL_SignalCondition(g_done);
    SDL_UnlockMutex(g_lock);
}

#define BRIDGE(name) Java_org_recompui_launcher_LauncherBridge_##name

JNIEXPORT void JNICALL BRIDGE(nativeRegister)(JNIEnv* env, jclass cls) {
    if (!g_lock) { g_lock = SDL_CreateMutex(); g_done = SDL_CreateCondition(); }
    if (!g_bridge) g_bridge = (jclass)(*env)->NewGlobalRef(env, cls);
}

// ---- game --------------------------------------------------------------------
static Json game_json(LauncherModel* m) {
    Json j = {0};
    j_lit(&j, "{");
    j_key(&j, "name"); j_str(&j, m && m->game_name ? m->game_name : "");
    j_lit(&j, ","); j_key(&j, "platform"); j_str(&j, m && m->platform ? m->platform : "");
    j_lit(&j, ","); j_key(&j, "canLaunch");
    j_lit(&j, m && launcher_model_can_launch(m) ? "true" : "false");
    j_lit(&j, ","); j_key(&j, "hasGame"); j_lit(&j, m && m->rom_present ? "true" : "false");
    j_lit(&j, ","); j_key(&j, "hasMods"); j_lit(&j, m && m->mods ? "true" : "false");
    j_lit(&j, "}");
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeGame)(JNIEnv* env, jclass cls) {
    (void)cls;
    Json j;
    LOCKED(j = game_json(g_model));
    return to_jstring(env, &j);
}

// ---- settings table -------------------------------------------------------------
static Json settings_json(const char* section) {
    Json j = {0};
    j_lit(&j, "[");
    int first = 1;
    for (int i = 0; g_model && section && i < launcher_settings_count(); ++i) {
        const LauncherSetting* s = launcher_setting_at(i);
        if (strcmp(s->section, section) != 0 || !launcher_setting_available(s, g_model))
            continue;
        if (!first) j_lit(&j, ",");
        first = 0;
        j_lit(&j, "{"); j_key(&j, "id"); j_str(&j, s->id);
        j_lit(&j, ","); j_key(&j, "label"); j_str(&j, launcher_setting_label(s, g_model));
        j_lit(&j, ","); j_key(&j, "kind"); j_fmt(&j, "%d", s->kind);
        if (s->help) { j_lit(&j, ","); j_key(&j, "help"); j_str(&j, s->help); }
        if (s->kind == LSET_TOGGLE) {
            j_lit(&j, ","); j_key(&j, "on"); j_lit(&j, s->is_on(g_model) ? "true" : "false");
        } else {
            j_lit(&j, ","); j_key(&j, "value"); j_str(&j, s->value(g_model));
        }
        if (s->experimental && s->experimental(g_model)) {
            j_lit(&j, ","); j_key(&j, "experimental"); j_lit(&j, "true");
        }
        j_lit(&j, "}");
    }
    j_lit(&j, "]");
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeSettings)(JNIEnv* env, jclass cls, jstring jsection) {
    (void)cls;
    char* section = dup_jstring(env, jsection);   // NULL: no section, no rows
    Json j;
    LOCKED(j = settings_json(section));
    free(section);
    return to_jstring(env, &j);
}

static Json choices_json(const char* id) {
    const LauncherSetting* s = launcher_setting_find(id);
    static char labels[24][96];                    // under the lock
    const int count = g_model && s ? launcher_setting_choices(g_model, s, labels, 24) : 0;
    Json j = {0};
    j_lit(&j, "[");
    for (int i = 0; i < count; ++i) { if (i) j_lit(&j, ","); j_str(&j, labels[i]); }
    j_lit(&j, "]");
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeChoices)(JNIEnv* env, jclass cls, jstring jid) {
    (void)cls;
    char* id = dup_jstring(env, jid);
    Json j;
    LOCKED(j = choices_json(id));
    free(id);
    return to_jstring(env, &j);
}

JNIEXPORT void JNICALL BRIDGE(nativeChoose)(JNIEnv* env, jclass cls, jstring jid, jint index) {
    (void)cls;
    char* id = dup_jstring(env, jid);
    const LauncherSetting* s = launcher_setting_find(id);
    LOCKED(if (g_model && s) launcher_setting_choose(g_model, s, index));
    free(id);
}

JNIEXPORT void JNICALL BRIDGE(nativeToggle)(JNIEnv* env, jclass cls, jstring jid) {
    (void)cls;
    char* id = dup_jstring(env, jid);
    const LauncherSetting* s = launcher_setting_find(id);
    LOCKED(if (g_model && s && s->kind == LSET_TOGGLE) s->toggle(g_model));
    free(id);
}

JNIEXPORT void JNICALL BRIDGE(nativeStep)(JNIEnv* env, jclass cls, jstring jid, jint direction) {
    (void)cls;
    char* id = dup_jstring(env, jid);
    const LauncherSetting* s = launcher_setting_find(id);
    LOCKED(if (g_model && s && s->kind == LSET_STEPPER)
               s->add(g_model, direction < 0 ? -s->step : s->step));
    free(id);
}

// ---- controllers -------------------------------------------------------------
// The input sources a player can pick: None, Touch (player 1), then known and
// connected pads. The ImGui dropdown's Keyboard is left out: a phone has none.
typedef struct { int kind; char guid[40]; char name[64]; uint32_t id; int live; } Source;

static int list_sources(const LauncherModel* m, int p, Source* out, int max) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const int psx = prof && prof->id && strcmp(prof->id, "psx") == 0;
    int n = 0;
    out[n++] = (Source){ 0, "", "None", 0, 1 };
    if (p == 0 && psx) out[n++] = (Source){ 3, "", "Touch", 0, 1 };   // on-screen pad
    #define PUSH_PAD(g, nm, pid, lv) do { \
        int dup = 0; \
        for (int k = 0; k < n; ++k) dup |= out[k].kind == 2 && strcmp(out[k].guid, (g)) == 0; \
        if (!dup && (g)[0] && n < max) { \
            Source src = { 2, "", "", (pid), (lv) }; \
            snprintf(src.guid, sizeof(src.guid), "%s", (g)); \
            snprintf(src.name, sizeof(src.name), "%s", \
                     ((nm) && (nm)[0] && strcmp((nm), "Gamepad") != 0) ? (nm) : "Controller"); \
            out[n++] = src; \
        } } while (0)
    if (psx) {
        const int known = launcher_binds_psx_known_count();
        for (int i = 0; i < known; ++i) {
            char guid[40] = {0}, name[64] = {0};
            if (!launcher_binds_psx_known_at(i, guid, (int)sizeof(guid), name, (int)sizeof(name)))
                continue;
            uint32_t id = 0; int live = 0;
            for (int k = 0; k < g_pad_count; ++k)
                if (strcmp(g_pads[k].guid, guid) == 0) { live = 1; id = g_pads[k].id; }
            PUSH_PAD(guid, name, id, live);
        }
    }
    for (int k = 0; k < g_pad_count; ++k)
        PUSH_PAD(g_pads[k].guid, g_pads[k].name, g_pads[k].id, 1);
    #undef PUSH_PAD
    return n;
}

static int source_selected(const LauncherModel* m, int p, const Source* s) {
    if (s->kind != 2) return m->s.player_src[p] == s->kind;
    return m->s.player_src[p] == 2 && strcmp(m->s.player_gamepad_guid[p], s->guid) == 0;
}

static int source_claimed(const LauncherModel* m, int p, const Source* s) {
    if (s->kind != 2) return 0;
    const int n = launcher_model_visible_player_count(m);
    for (int o = 0; o < n; ++o)
        if (o != p && m->s.player_src[o] == 2 &&
            strcmp(m->s.player_gamepad_guid[o], s->guid) == 0)
            return 1;
    return 0;
}

static jstring players_json(JNIEnv* env) {
    LauncherModel* m = g_model;
    Json j = {0};
    j_lit(&j, "[");
    if (m && !m->lock_device) {
        g_pad_count = launcher_input_poll(g_pads, LNG_MAX_PADS, 0);
        launcher_binds_sync_psx_pad_sources(m, g_pads, g_pad_count);
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        int players = launcher_model_visible_player_count(m);
        if (players < 1) players = 1;
        for (int p = 0; p < players; ++p) {
            if (p) j_lit(&j, ",");
            j_lit(&j, "{"); j_key(&j, "player"); j_fmt(&j, "%d", p);
            j_lit(&j, ","); j_key(&j, "source");
            j_str(&j, launcher_model_player_src_label(m, p));
            Source sources[LNG_MAX_PADS + 24];
            const int count = list_sources(m, p, sources, (int)(sizeof(sources) / sizeof(sources[0])));
            j_lit(&j, ","); j_key(&j, "sources"); j_lit(&j, "[");
            for (int i = 0; i < count; ++i) {
                if (i) j_lit(&j, ",");
                char label[96];
                snprintf(label, sizeof(label), "%s%s", sources[i].name,
                         sources[i].live ? "" : " (disconnected)");
                j_lit(&j, "{"); j_key(&j, "label"); j_str(&j, label);
                j_lit(&j, ","); j_key(&j, "selected");
                j_lit(&j, source_selected(m, p, &sources[i]) ? "true" : "false");
                j_lit(&j, ","); j_key(&j, "claimed");
                j_lit(&j, source_claimed(m, p, &sources[i]) ? "true" : "false");
                j_lit(&j, "}");
            }
            j_lit(&j, "]");
            // Pad modes: the profile's list, or Analog / D-Pad.
            j_lit(&j, ","); j_key(&j, "modes"); j_lit(&j, "[");
            if (m->pad_mode_supported && m->pad_mode_selectable) {
                const int touch = m->s.player_src[p] == 3;   // no sticks
                if (prof && prof->controller.modes && prof->controller.mode_count > 0) {
                    for (int i = 0; i < prof->controller.mode_count; ++i) {
                        if (i) j_lit(&j, ",");
                        j_lit(&j, "{"); j_key(&j, "mode"); j_fmt(&j, "%d", prof->controller.modes[i].mode);
                        j_lit(&j, ","); j_key(&j, "label"); j_str(&j, prof->controller.modes[i].label);
                        j_lit(&j, ","); j_key(&j, "enabled"); j_lit(&j, "true");
                        j_lit(&j, "}");
                    }
                } else {
                    j_lit(&j, "{\"mode\":1,\"label\":\"Analog\",\"enabled\":");
                    j_lit(&j, touch ? "false}" : "true}");
                    j_lit(&j, ",{\"mode\":2,\"label\":\"D-Pad\",\"enabled\":true}");
                }
            }
            j_lit(&j, "]");
            j_lit(&j, ","); j_key(&j, "mode"); j_fmt(&j, "%d", m->s.pad_mode[p]);
            j_lit(&j, ","); j_key(&j, "kind"); j_fmt(&j, "%d", m->s.player_src[p]);
            j_lit(&j, ","); j_key(&j, "canBind");
            j_lit(&j, is_psx(m) && !m->hide_rebind && m->s.player_src[p] == 2 &&
                      m->s.player_gamepad_guid[p][0] ? "true" : "false");
            j_lit(&j, "}");
        }
    }
    j_lit(&j, "]");
    return to_jstring(env, &j);
}

JNIEXPORT jstring JNICALL BRIDGE(nativePlayers)(JNIEnv* env, jclass cls) {
    (void)cls;
    jstring out;
    LOCKED(out = players_json(env));
    return out;
}

static void set_source(int p, int index) {
    LauncherModel* m = g_model;
    if (!m || p < 0 || p >= LNG_MAX_PLAYERS) return;
    Source sources[LNG_MAX_PADS + 24];
    const int count = list_sources(m, p, sources, (int)(sizeof(sources) / sizeof(sources[0])));
    if (index < 0 || index >= count || source_claimed(m, p, &sources[index])) return;
    const Source* s = &sources[index];
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const int psx = prof && prof->id && strcmp(prof->id, "psx") == 0;
    if (s->kind == 2) {
        launcher_model_set_source(m, p, 2, s->id, s->name, s->guid);
        if (psx) launcher_binds_apply_psx_pad_profile(m, p);
    } else {
        launcher_model_set_source(m, p, s->kind, 0, NULL, NULL);
    }
    if (psx) launcher_binds_refresh(m);
}

JNIEXPORT void JNICALL BRIDGE(nativeSetSource)(JNIEnv* env, jclass cls, jint p, jint index) {
    (void)env; (void)cls;
    LOCKED(set_source(p, index));
}

JNIEXPORT void JNICALL BRIDGE(nativeSetPadMode)(JNIEnv* env, jclass cls, jint p, jint mode) {
    (void)env; (void)cls;
    LOCKED(if (g_model) launcher_model_set_pad_mode(g_model, p, mode));
}

// ---- a controller's buttons (the PC launcher's Configure page) --------------------
static int bindable(const LauncherModel* m, int p) {
    return m && p >= 0 && p < LNG_MAX_PLAYERS && is_psx(m) && !m->hide_rebind &&
           m->s.player_src[p] == 2 && m->s.player_gamepad_guid[p][0];
}

static jstring bindings_json(JNIEnv* env, int p) {
    LauncherModel* m = g_model;
    Json j = {0};
    j_lit(&j, "{");
    if (bindable(m, p)) {
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        const int live = m->player_pad_id[p] != 0;
        j_key(&j, "pad"); j_str(&j, launcher_model_player_src_label(m, p));
        j_lit(&j, ","); j_key(&j, "connected"); j_lit(&j, live ? "true" : "false");
        const int cap = m->capturing && m->capture_pad && m->cfg_player == p;
        j_lit(&j, ","); j_key(&j, "capturing"); j_fmt(&j, "%d", cap ? m->capture_btn : -1);
        j_lit(&j, ","); j_key(&j, "waitRelease"); j_lit(&j, cap && m->map_all_wait_release ? "true" : "false");
        j_lit(&j, ","); j_key(&j, "mapAll"); j_lit(&j, cap && m->map_all_active ? "true" : "false");
        j_lit(&j, ","); j_key(&j, "buttons"); j_lit(&j, "[");
        for (int i = 0; i < LNG_PSX_PAD_BUTTON_COUNT && i < prof->controller.button_count; ++i) {
            const int b = kPsxGamepadBindOrder[i];
            if (i) j_lit(&j, ",");
            j_lit(&j, "{"); j_key(&j, "button"); j_fmt(&j, "%d", b);
            j_lit(&j, ","); j_key(&j, "label"); j_str(&j, prof->controller.buttons[b].label);
            j_lit(&j, ","); j_key(&j, "bind"); j_str(&j, m->pad_binds[p][b]);
            j_lit(&j, "}");
        }
        j_lit(&j, "]");
    }
    j_lit(&j, "}");
    return to_jstring(env, &j);
}

JNIEXPORT jstring JNICALL BRIDGE(nativeBindings)(JNIEnv* env, jclass cls, jint p) {
    (void)cls;
    jstring out;
    LOCKED(out = bindings_json(env, p));
    return out;
}

static void begin_capture(int p, int b, int all) {
    LauncherModel* m = g_model;
    if (!bindable(m, p)) return;
    m->cfg_player = p;
    m->map_all_active = false;
    m->map_all_wait_release = false;
    if (all) launcher_model_begin_map_all(m);
    else     launcher_model_begin_pad_capture(m, b);
    // Still holding the last input: wait for a full release first.
    if (m->capturing && m->player_pad_id[p] &&
        !launcher_input_gamepad_at_rest(m->player_pad_id[p]))
        m->map_all_wait_release = true;
}

JNIEXPORT void JNICALL BRIDGE(nativeCaptureButton)(JNIEnv* env, jclass cls, jint p, jint b) {
    (void)env; (void)cls;
    LOCKED(begin_capture(p, b, 0));
}

JNIEXPORT void JNICALL BRIDGE(nativeCaptureAll)(JNIEnv* env, jclass cls, jint p) {
    (void)env; (void)cls;
    LOCKED(begin_capture(p, 0, 1));
}

JNIEXPORT jboolean JNICALL BRIDGE(nativeCapturing)(JNIEnv* env, jclass cls) {
    (void)env; (void)cls;
    jboolean on;
    LOCKED(on = g_model && g_model->capturing && g_model->capture_pad ? JNI_TRUE : JNI_FALSE);
    return on;
}

static void cancel_capture(void) {
    LauncherModel* m = g_model;
    if (!m) return;
    m->map_all_active = false;
    m->map_all_wait_release = false;
    launcher_model_cancel_capture(m);
}

JNIEXPORT void JNICALL BRIDGE(nativeCancelCapture)(JNIEnv* env, jclass cls) {
    (void)env; (void)cls;
    LOCKED(cancel_capture());
}

JNIEXPORT void JNICALL BRIDGE(nativeResetBindings)(JNIEnv* env, jclass cls, jint p) {
    (void)env; (void)cls;
    LOCKED(if (bindable(g_model, p)) launcher_binds_reset_player(g_model, p + 1));
}

JNIEXPORT void JNICALL BRIDGE(nativeSaveBindings)(JNIEnv* env, jclass cls, jint p) {
    (void)env; (void)cls;
    LOCKED(if (bindable(g_model, p)) launcher_binds_save_psx_gamepad(g_model, p + 1));
}

// ---- memory cards -----------------------------------------------------------
static Json memcards_json(void) {
    LauncherModel* m = g_model;
    const SystemProfile* prof = m ? (const SystemProfile*)m->profile : NULL;
    Json j = {0};
    j_lit(&j, "[");
    if (prof && prof->save.kind == SAVE_MEMCARD) {
        const int slots = (prof->save.slots > 0 && prof->save.slots <= 2) ? prof->save.slots : 2;
        for (int s = 0; s < slots; ++s) {
            if (s) j_lit(&j, ",");
            const char* path = m->s.memcard_path[s];
            const char* name = path;
            for (const char* c = path; *c; ++c) if (*c == '/' || *c == '\\') name = c + 1;
            j_lit(&j, "{"); j_key(&j, "slot"); j_fmt(&j, "%d", s);
            j_lit(&j, ","); j_key(&j, "enabled"); j_lit(&j, m->s.memcard_enabled[s] ? "true" : "false");
            j_lit(&j, ","); j_key(&j, "name"); j_str(&j, name);
            j_lit(&j, ","); j_key(&j, "used"); j_fmt(&j, "%d", (int)m->memcard_blocks_used[s]);
            j_lit(&j, "}");
        }
    }
    j_lit(&j, "]");
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeMemcards)(JNIEnv* env, jclass cls) {
    (void)cls;
    Json j;
    LOCKED(j = memcards_json());
    return to_jstring(env, &j);
}

JNIEXPORT void JNICALL BRIDGE(nativeToggleMemcard)(JNIEnv* env, jclass cls, jint slot) {
    (void)env; (void)cls;
    LOCKED(if (g_model) launcher_model_toggle_memcard(g_model, slot));
}

// A new, formatted card in the slot, in the folder of the card it replaces
// (memcards/ in the app's data folder when there is none). The old card
// stays on disk. Returns the new card's file name, "" on failure.
static Json new_memcard(int slot) {
    LauncherModel* m = g_model;
    Json j = {0};
    j_lit(&j, "");
    if (m && slot >= 0 && slot <= 1) {
        char dir[512];
        snprintf(dir, sizeof(dir), "%s", m->s.memcard_path[slot]);
        char* cut = strrchr(dir, '/');
        if (cut) *cut = '\0';
        else snprintf(dir, sizeof(dir), "memcards");
        mkdir(dir, 0777);
        const time_t now = time(NULL);
        struct tm tmv;
        localtime_r(&now, &tmv);
        char path[600];
        snprintf(path, sizeof(path), "%s/card%d-%04d%02d%02d-%02d%02d%02d.mcd", dir, slot + 1,
                 tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
                 tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
        launcher_model_new_memcard(m, slot, path);
        if (strcmp(m->s.memcard_path[slot], path) == 0) {
            m->s.memcard_enabled[slot] = 1;
            j_lit(&j, strrchr(path, '/') + 1);
        }
    }
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeNewMemcard)(JNIEnv* env, jclass cls, jint slot) {
    (void)cls;
    Json j;
    LOCKED(j = new_memcard(slot));
    return to_jstring(env, &j);
}

// ---- mods ----------------------------------------------------------------------
static void mod_error(LauncherModel* m) {
    const char* error = m->mods && m->mods->last_error ? m->mods->last_error(m->mods->ctx) : NULL;
    snprintf(m->mod_status, sizeof(m->mod_status), "%s",
             error && error[0] ? error : "The mod change could not be applied.");
}

static Json mods_json(void) {
    LauncherModel* m = g_model;
    const RecompLauncherCModProvider* mods = m ? m->mods : NULL;
    Json j = {0};
    j_lit(&j, "{"); j_key(&j, "status"); j_str(&j, m ? m->mod_status : "");
    j_lit(&j, ","); j_key(&j, "features"); j_lit(&j, "[");
    if (mods && mods->feature_count && mods->feature_get) {
        const int count = mods->feature_count(mods->ctx);
        int first = 1;
        for (int i = 0; i < count; ++i) {
            RecompLauncherCModFeature f;
            memset(&f, 0, sizeof(f));
            if (!mods->feature_get(mods->ctx, i, &f)) continue;
            if (!first) j_lit(&j, ",");
            first = 0;
            j_lit(&j, "{"); j_key(&j, "package"); j_str(&j, f.package_id);
            j_lit(&j, ","); j_key(&j, "id"); j_str(&j, f.id);
            j_lit(&j, ","); j_key(&j, "name"); j_str(&j, f.name);
            j_lit(&j, ","); j_key(&j, "group"); j_str(&j, f.group[0] ? f.group : "General");
            j_lit(&j, ","); j_key(&j, "description"); j_str(&j, f.description);
            j_lit(&j, ","); j_key(&j, "author"); j_str(&j, f.author);
            j_lit(&j, ","); j_key(&j, "status"); j_str(&j, f.status);
            j_lit(&j, ","); j_key(&j, "enabled"); j_lit(&j, f.enabled ? "true" : "false");
            j_lit(&j, ","); j_key(&j, "error"); j_lit(&j, f.has_error ? "true" : "false");
            j_lit(&j, ","); j_key(&j, "options"); j_fmt(&j, "%d", f.option_count);
            j_lit(&j, "}");
        }
    }
    j_lit(&j, "]}");
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeMods)(JNIEnv* env, jclass cls) {
    (void)cls;
    Json j;
    LOCKED(j = mods_json());
    return to_jstring(env, &j);
}

static int mod_enable(const char* pkg, const char* id, int on) {
    LauncherModel* m = g_model;
    if (!m || !m->mods || !m->mods->feature_enable || !pkg || !id) return 0;
    const int ok = m->mods->feature_enable(m->mods->ctx, pkg, id, on);
    if (ok) snprintf(m->mod_status, sizeof(m->mod_status), "Changes apply when you press PLAY.");
    else    mod_error(m);
    return ok;
}

JNIEXPORT jboolean JNICALL BRIDGE(nativeModEnable)(JNIEnv* env, jclass cls,
                                                   jstring jpkg, jstring jid, jboolean on) {
    (void)cls;
    char* pkg = dup_jstring(env, jpkg);
    char* id = dup_jstring(env, jid);
    int ok;
    LOCKED(ok = mod_enable(pkg, id, on ? 1 : 0));
    free(pkg); free(id);
    return ok ? JNI_TRUE : JNI_FALSE;
}

static Json mod_options_json(const char* pkg, const char* id) {
    LauncherModel* m = g_model;
    const RecompLauncherCModProvider* mods = m ? m->mods : NULL;
    Json j = {0};
    j_lit(&j, "[");
    if (pkg && id && mods && mods->feature_count && mods->feature_get && mods->feature_option_get) {
        RecompLauncherCModFeature f;
        int found = 0;
        const int count = mods->feature_count(mods->ctx);
        for (int i = 0; i < count && !found; ++i) {
            memset(&f, 0, sizeof(f));
            found = mods->feature_get(mods->ctx, i, &f) &&
                    strcmp(f.package_id, pkg) == 0 && strcmp(f.id, id) == 0;
        }
        for (int o = 0; found && o < f.option_count; ++o) {
            RecompLauncherCModOption opt;
            memset(&opt, 0, sizeof(opt));
            if (!mods->feature_option_get(mods->ctx, pkg, id, o, &opt)) continue;
            if (o) j_lit(&j, ",");
            j_lit(&j, "{"); j_key(&j, "id"); j_str(&j, opt.id);
            j_lit(&j, ","); j_key(&j, "label"); j_str(&j, opt.label);
            j_lit(&j, ","); j_key(&j, "description"); j_str(&j, opt.description);
            j_lit(&j, ","); j_key(&j, "group"); j_str(&j, opt.group);
            j_lit(&j, ","); j_key(&j, "value"); j_str(&j, opt.value);
            j_lit(&j, ","); j_key(&j, "type"); j_fmt(&j, "%d", opt.type);
            j_lit(&j, ","); j_key(&j, "min"); j_fmt(&j, "%lld", (long long)opt.min_value);
            j_lit(&j, ","); j_key(&j, "max"); j_fmt(&j, "%lld", (long long)opt.max_value);
            j_lit(&j, ","); j_key(&j, "step"); j_fmt(&j, "%lld", (long long)opt.step);
            j_lit(&j, ","); j_key(&j, "disabled"); j_lit(&j, opt.disabled ? "true" : "false");
            j_lit(&j, ","); j_key(&j, "choices"); j_lit(&j, "[");
            for (int c = 0; mods->feature_choice_get && c < opt.choice_count; ++c) {
                RecompLauncherCModChoice choice;
                memset(&choice, 0, sizeof(choice));
                if (!mods->feature_choice_get(mods->ctx, pkg, id, opt.id, c, &choice)) continue;
                if (c) j_lit(&j, ",");
                j_lit(&j, "{"); j_key(&j, "value"); j_str(&j, choice.value);
                j_lit(&j, ","); j_key(&j, "label"); j_str(&j, choice.label[0] ? choice.label : choice.value);
                j_lit(&j, "}");
            }
            j_lit(&j, "]}");
        }
    }
    j_lit(&j, "]");
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativeModOptions)(JNIEnv* env, jclass cls,
                                                   jstring jpkg, jstring jid) {
    (void)cls;
    char* pkg = dup_jstring(env, jpkg);
    char* id = dup_jstring(env, jid);
    Json j;
    LOCKED(j = mod_options_json(pkg, id));
    free(pkg); free(id);
    return to_jstring(env, &j);
}

static int mod_set_option(const char* pkg, const char* id, const char* opt, const char* value) {
    LauncherModel* m = g_model;
    if (!m || !m->mods || !m->mods->feature_set_option || !pkg || !id || !opt || !value)
        return 0;
    const int ok = m->mods->feature_set_option(m->mods->ctx, pkg, id, opt, value);
    if (!ok) mod_error(m);
    return ok;
}

JNIEXPORT jboolean JNICALL BRIDGE(nativeModSetOption)(JNIEnv* env, jclass cls, jstring jpkg,
                                                      jstring jid, jstring jopt, jstring jvalue) {
    (void)cls;
    char* pkg = dup_jstring(env, jpkg);
    char* id = dup_jstring(env, jid);
    char* opt = dup_jstring(env, jopt);
    char* value = dup_jstring(env, jvalue);
    int ok;
    LOCKED(ok = mod_set_option(pkg, id, opt, value));
    free(pkg); free(id); free(opt); free(value);
    return ok ? JNI_TRUE : JNI_FALSE;
}

// ---- PLAY / leave -----------------------------------------------------------------
// "" when the game starts, else why it cannot (the screens stay up).
static Json play(void) {
    LauncherModel* m = g_model;
    Json j = {0};
    if (!m) {
        j_lit(&j, "The launcher is not running.");
    } else if (!launcher_model_can_launch(m)) {
        j_lit(&j, m->rom_present ? "The game cannot start with these settings."
                                 : "This build has no game in it. Build the APK with the setup on your computer.");
    } else if (m->mods && m->mods->commit &&
               !m->mods->commit(m->mods->ctx, launcher_model_rom_path(m))) {
        mod_error(m);
        j_lit(&j, m->mod_status);
    } else {
        j_lit(&j, "");
        finish(LNG_ACTION_LAUNCH);
    }
    return j;
}

JNIEXPORT jstring JNICALL BRIDGE(nativePlay)(JNIEnv* env, jclass cls) {
    (void)cls;
    Json j;
    LOCKED(j = play());
    return to_jstring(env, &j);
}

JNIEXPORT void JNICALL BRIDGE(nativeQuit)(JNIEnv* env, jclass cls) {
    (void)env; (void)cls;
    finish(LNG_ACTION_QUIT);
}
