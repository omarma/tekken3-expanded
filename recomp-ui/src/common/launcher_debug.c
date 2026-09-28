// launcher_debug.c — LNG_SCRIPT interpreter + framebuffer capture.

#include "launcher_debug.h"
#include "launcher_sdlcompat.h"   // SDL2/SDL3 event-symbol shim + GL header

// A host that already compiles the stb_image_write implementation (e.g.
// gb-recompiled's gb_printer.c) defines RECOMP_UI_HOST_STB_WRITE so this TU
// pulls in the DECLARATIONS only and links against the host's single copy —
// otherwise two implementations collide at link time. Standalone recomp-ui
// (no host stb) leaves it undefined and provides the implementation here.
#ifndef RECOMP_UI_HOST_STB_WRITE
#define STB_IMAGE_WRITE_IMPLEMENTATION
#endif
#include "third_party/stb_image_write.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LNG_MAX_CMDS 64

static char  g_script[2048];
static char* g_cmds[LNG_MAX_CMDS];
static int   g_cmd_count = 0;
static int   g_cmd_index = 0;
static int   g_wait_frames = 0;
static bool  g_active = false;

bool launcher_debug_active(void) { return g_active; }

void launcher_debug_init(void) {
    const char* s = SDL_getenv("LNG_SCRIPT");
    if (!s || !s[0]) return;

    snprintf(g_script, sizeof(g_script), "%s", s);
    g_cmd_count = 0;
    char* tok = strtok(g_script, ";");
    while (tok && g_cmd_count < LNG_MAX_CMDS) {
        while (*tok == ' ') ++tok;          // trim leading spaces
        if (*tok) g_cmds[g_cmd_count++] = tok;
        tok = strtok(NULL, ";");
    }
    g_active = g_cmd_count > 0;
    if (g_active) fprintf(stderr, "[dbg] script: %d commands\n", g_cmd_count);
}

bool launcher_capture_png(const char* path, int w, int h) {
    if (w <= 0 || h <= 0) return false;
    unsigned char* px = (unsigned char*)malloc((size_t)w * h * 3);
    if (!px) return false;

    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, px);

    // GL origin is bottom-left; PNG wants top-down. Flip rows in place.
    const size_t stride = (size_t)w * 3;
    unsigned char* row = (unsigned char*)malloc(stride);
    if (row) {
        for (int y = 0; y < h / 2; ++y) {
            unsigned char* a = px + (size_t)y * stride;
            unsigned char* b = px + (size_t)(h - 1 - y) * stride;
            memcpy(row, a, stride); memcpy(a, b, stride); memcpy(b, row, stride);
        }
        free(row);
    }

    int ok = stbi_write_png(path, w, h, 3, px, (int)stride);
    free(px);
    if (ok) fprintf(stderr, "[dbg] shot -> %s (%dx%d)\n", path, w, h);
    else    fprintf(stderr, "[dbg] shot FAILED -> %s\n", path);
    return ok != 0;
}

// Synthesize a click at logical window coords: warp the cursor (so backends
// that sample SDL_GetMouseState see it) and push button events (so backends
// that consume the event queue see it). Covers both ImGui and Clay.
static void synth_click(LauncherPlatform* p, float x, float y) {
#if defined(LNG_SDL3)
    SDL_WarpMouseInWindow(p->window, x, y);
#else
    // SDL2 stores mouse coordinates as integers. Make its existing truncation
    // behavior explicit while preserving SDL3's subpixel coordinates.
    const int event_x = (int)x;
    const int event_y = (int)y;
    SDL_WarpMouseInWindow(p->window, event_x, event_y);
#endif

    SDL_Event e;
    SDL_zero(e);
    e.type = SDL_EVENT_MOUSE_MOTION;
    e.motion.windowID = SDL_GetWindowID(p->window);
#if defined(LNG_SDL3)
    e.motion.x = x; e.motion.y = y;
#else
    e.motion.x = event_x; e.motion.y = event_y;
#endif
    SDL_PushEvent(&e);

    SDL_zero(e);
    e.type = SDL_EVENT_MOUSE_BUTTON_DOWN;
    e.button.windowID = SDL_GetWindowID(p->window);
    e.button.button = SDL_BUTTON_LEFT;
    e.button.clicks = 1;
#if defined(LNG_SDL3)
    e.button.x = x; e.button.y = y;
    e.button.down = true;
#else
    e.button.x = event_x; e.button.y = event_y;
    e.button.state = SDL_PRESSED;
#endif
    SDL_PushEvent(&e);

    e.type = SDL_EVENT_MOUSE_BUTTON_UP;
#if defined(LNG_SDL3)
    e.button.down = false;
#else
    e.button.state = SDL_RELEASED;
#endif
    SDL_PushEvent(&e);
}

static void synth_key(SDL_Keycode key) {
    SDL_Scancode sc = SDL_GetScancodeFromKey(key
#if defined(LNG_SDL3)
        , NULL
#endif
        );
    SDL_Event e;
    SDL_zero(e);
    e.type = SDL_EVENT_KEY_DOWN;
#if defined(LNG_SDL3)
    e.key.key = key;
    e.key.scancode = sc;
    e.key.down = true;
#else
    e.key.keysym.sym = key;
    e.key.keysym.scancode = sc;
    e.key.state = SDL_PRESSED;
#endif
    SDL_PushEvent(&e);
    e.type = SDL_EVENT_KEY_UP;
#if defined(LNG_SDL3)
    e.key.down = false;
#else
    e.key.state = SDL_RELEASED;
#endif
    SDL_PushEvent(&e);
}

void launcher_debug_step(LauncherPlatform* p, LauncherModel* m) {
    if (!g_active) return;

    // Never clobber an action the UI already set this frame (e.g. PLAY -> LAUNCH);
    // otherwise a script that clicks PLAY and then ends would overwrite LAUNCH
    // with the script-exhausted QUIT below.
    if (m->action != LNG_ACTION_NONE) return;

    if (g_wait_frames > 0) { --g_wait_frames; return; }

    if (g_cmd_index >= g_cmd_count) {   // script exhausted -> exit
        m->action = LNG_ACTION_QUIT;
        return;
    }

    const char* c = g_cmds[g_cmd_index++];

    if (strncmp(c, "view:", 5) == 0) {
        const char* v = c + 5;
        if      (strcmp(v, "dashboard")  == 0) launcher_model_set_view(m, LNG_VIEW_DASHBOARD);
        else if (strcmp(v, "settings")   == 0) launcher_model_set_view(m, LNG_VIEW_SETTINGS);
        else if (strcmp(v, "controller") == 0) launcher_model_set_view(m, LNG_VIEW_CONTROLLER);
        else if (strcmp(v, "assist_tools") == 0) launcher_model_set_view(m, LNG_VIEW_ASSIST_TOOLS);
        else if (strcmp(v, "credits") == 0) launcher_model_set_view(m, LNG_VIEW_CREDITS);
    } else if (strncmp(c, "player:", 7) == 0) {
        // Select which player the Controller view configures. Clamp to the
        // launcher's real player range (N64 profiles run up to 4) instead of
        // the old 0/1-only test hook, so scripted screenshots can reach P3/P4.
        int pl = atoi(c + 7);
        if (pl < 0) pl = 0;
        if (pl > LNG_MAX_PLAYERS - 1) pl = LNG_MAX_PLAYERS - 1;
        m->cfg_player = pl;
    } else if (strncmp(c, "capbtn:", 7) == 0) {
        launcher_model_begin_capture(m, atoi(c + 7));   // rebind a player button (generic spec index)
    } else if (strncmp(c, "caphk:", 6) == 0) {
        launcher_model_begin_hk_capture(m, (LngHotkey)atoi(c + 6)); // rebind a hotkey
    } else if (strncmp(c, "size:", 5) == 0) {
        int w = 0, h = 0;
        if (sscanf(c + 5, "%dx%d", &w, &h) == 2 && w > 0 && h > 0) {
            SDL_SetWindowSize(p->window, w, h);
            launcher_platform_refresh_metrics(p);
        }
    } else if (strncmp(c, "click:", 6) == 0) {
        float x = 0, y = 0;
        if (sscanf(c + 6, "%f,%f", &x, &y) == 2) synth_click(p, x, y);
    } else if (strncmp(c, "key:", 4) == 0) {
        if (strcmp(c + 4, "escape") == 0) synth_key(SDLK_ESCAPE);
        else {
            SDL_Keycode k = SDL_GetKeyFromName(c + 4);
            if (k != SDLK_UNKNOWN) synth_key(k);
            else fprintf(stderr, "[dbg] unknown key: %s\n", c + 4);
        }
    } else if (strncmp(c, "wait:", 5) == 0) {
        g_wait_frames = atoi(c + 5);
    } else if (strncmp(c, "shot:", 5) == 0) {
        launcher_capture_png(c + 5, p->pixel_w, p->pixel_h);
    } else if (strcmp(c, "quit") == 0) {
        m->action = LNG_ACTION_QUIT;
    } else {
        fprintf(stderr, "[dbg] unknown command: %s\n", c);
    }
}
