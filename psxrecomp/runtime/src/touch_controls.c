/* touch_controls.c — a PS1 pad drawn over the game for touch screens.
 *
 * Fingers come from SDL touch events through an event watch, so every event
 * loop of the runtime (boot, game, pause gate) feeds it and the buttons act
 * the moment a finger lands. Each finger belongs to the D-pad for its whole
 * life when it lands there (it keeps steering outside the pad), otherwise it
 * presses whatever buttons lie under it, so a finger can slide from one
 * button to the next. The layout is computed from the drawable size, inside
 * the safe area (clear of a display cutout), in the same place for hit tests
 * and drawing; gpu_gl_renderer.c draws it over the presented frame
 * (touch_controls_draw_list).
 */

#include "touch_controls.h"
#include "psx_sdl.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* PS1 pad bits (active-low in the pad word). */
enum {
    PSX_SELECT = 0x0001, PSX_START = 0x0008,
    PSX_UP = 0x0010, PSX_RIGHT = 0x0020, PSX_DOWN = 0x0040, PSX_LEFT = 0x0080,
    PSX_L2 = 0x0100, PSX_R2 = 0x0200, PSX_L1 = 0x0400, PSX_R1 = 0x0800,
    PSX_TRIANGLE = 0x1000, PSX_CIRCLE = 0x2000, PSX_CROSS = 0x4000, PSX_SQUARE = 0x8000,
};

enum {
    E_UP, E_RIGHT, E_DOWN, E_LEFT,
    E_TRIANGLE, E_CIRCLE, E_CROSS, E_SQUARE,
    E_L1, E_L2, E_R1, E_R2, E_SELECT, E_START,
    E_COUNT
};
static const uint16_t kBits[E_COUNT] = {
    PSX_UP, PSX_RIGHT, PSX_DOWN, PSX_LEFT,
    PSX_TRIANGLE, PSX_CIRCLE, PSX_CROSS, PSX_SQUARE,
    PSX_L1, PSX_L2, PSX_R1, PSX_R2, PSX_SELECT, PSX_START,
};

/* ---- settings ---------------------------------------------------------------- */
/* What the layout editor moves, sizes and hides, one by one. Their names are
 * the keys of touch_controls.ini: "name = x, y, scale, shown", with x and y
 * the centre as fractions of the screen. The Java editor
 * (org.psxrecomp.TouchLayout) reads and writes the same file. */
enum {
    T_DPAD, T_TRIANGLE, T_CIRCLE, T_CROSS, T_SQUARE,
    T_L1, T_L2, T_R1, T_R2, T_SELECT, T_START, T_COUNT
};
static const char *const kItemNames[T_COUNT] = {
    "dpad", "triangle", "circle", "cross", "square",
    "l1", "l2", "r1", "r2", "select", "start",
};
typedef struct { float x, y, scale; int shown; } TouchItem;

typedef struct {
    int   visible;          /* 0: nothing drawn, the buttons still act */
    int   opacity;          /* percent */
    int   size;             /* percent, all the buttons */
    int   stick;            /* the D-pad as 0 a cross, 1 a joystick, 2 a joystick
                               that starts where the thumb lands (left half) */
    int   neutral;          /* the neutral middle, percent of the D-pad's reach:
                               a slide through it lets go of the directions, as
                               lifting the thumb does (f, N, d, d/f moves) */
    TouchItem item[T_COUNT];
} TouchSettings;

/* Where RetroArch's flat PSX overlay puts them, on a 20:9 phone. */
static const TouchSettings kDefaults = { 1, 70, 100, 0, 35, {
    { 0.125f, 0.780f, 1.0f, 1 },                                  /* dpad */
    { 0.875f, 0.669f, 1.0f, 1 }, { 0.925f, 0.780f, 1.0f, 1 },     /* triangle, circle */
    { 0.875f, 0.891f, 1.0f, 1 }, { 0.825f, 0.780f, 1.0f, 1 },     /* cross, square */
    { 0.049f, 0.490f, 1.0f, 1 }, { 0.049f, 0.300f, 1.0f, 1 },     /* l1, l2 */
    { 0.951f, 0.490f, 1.0f, 1 }, { 0.951f, 0.300f, 1.0f, 1 },     /* r1, r2 */
    { 0.450f, 0.925f, 1.0f, 1 }, { 0.550f, 0.925f, 1.0f, 1 },     /* select, start */
} };

/* NaN (a damaged touch_controls.ini) becomes lo. */
static float clampf(float v, float lo, float hi) { return !(v >= lo) ? lo : v > hi ? hi : v; }
/* Clamped as a float first: converting an out-of-range float to int is undefined. */
static int   clamp_to_int(float v, int lo, int hi) { return (int)clampf(v, (float)lo, (float)hi); }

/* ---- the safe area ------------------------------------------------------------- */
static volatile float s_safe[4];   /* left, top, right, bottom: fractions of the screen */

void psx_safe_area_set(float left, float top, float right, float bottom) {
    s_safe[0] = clampf(left, 0.0f, 0.4f);
    s_safe[1] = clampf(top, 0.0f, 0.4f);
    s_safe[2] = clampf(right, 0.0f, 0.4f);
    s_safe[3] = clampf(bottom, 0.0f, 0.4f);
}

void psx_safe_area_px(int w, int h, int *left, int *top, int *right, int *bottom) {
    *left   = (int)(s_safe[0] * (float)w + 0.5f);
    *top    = (int)(s_safe[1] * (float)h + 0.5f);
    *right  = (int)(s_safe[2] * (float)w + 0.5f);
    *bottom = (int)(s_safe[3] * (float)h + 0.5f);
}

static void write_settings(const TouchSettings *s, const char *path) {
    FILE *out = path ? fopen(path, "w") : NULL;
    if (!out) return;
    fprintf(out, "; On-screen buttons (the launcher's Touch page and its layout editor)\n"
                 "visible=%d\nopacity=%d\nsize=%d\nstick=%d\nneutral=%d\n",
            s->visible, s->opacity, s->size, s->stick, s->neutral);
    for (int i = 0; i < T_COUNT; ++i)
        fprintf(out, "%s=%.4f,%.4f,%.2f,%d\n", kItemNames[i], s->item[i].x, s->item[i].y,
                s->item[i].scale, s->item[i].shown);
    fclose(out);
}

static void load_settings(TouchSettings *s, const char *path) {
    *s = kDefaults;
    FILE *f = path ? fopen(path, "r") : NULL;
    if (!f) {
        /* Write the defaults, for the launcher's Touch page to start from. */
        write_settings(s, path);
        return;
    }
    char line[160];
    while (fgets(line, sizeof line, f)) {
        char key[64];
        float value, y, scale;
        int shown;
        if (line[0] == ';' || line[0] == '#') continue;
        const int n = sscanf(line, " %63[^= ] = %f , %f , %f , %d", key, &value, &y, &scale, &shown);
        if (n == 5) {
            for (int i = 0; i < T_COUNT; ++i) {
                if (strcmp(key, kItemNames[i]) != 0) continue;
                s->item[i] = (TouchItem){ clampf(value, 0.0f, 1.0f), clampf(y, 0.0f, 1.0f),
                                          clampf(scale, 0.4f, 3.0f), shown != 0 };
            }
            continue;
        }
        if (n < 2) continue;
        if      (!strcmp(key, "visible")) s->visible = value != 0.0f;
        else if (!strcmp(key, "opacity")) s->opacity = clamp_to_int(value, 10, 100);
        else if (!strcmp(key, "size"))    s->size = clamp_to_int(value, 50, 160);
        else if (!strcmp(key, "stick"))   s->stick = clamp_to_int(value, 0, 2);
        else if (!strcmp(key, "neutral")) s->neutral = clamp_to_int(value, 10, 60);
    }
    fclose(f);
}

/* ---- layout -------------------------------------------------------------------- */
typedef struct { float cx, cy, hw, hh, radius; } Box;
typedef struct {
    Box   e[E_COUNT];
    int   on[E_COUNT];
    float unit[E_COUNT];                 /* each button's own size unit */
    float dpad_x, dpad_y, dpad_zone;     /* a finger landing here steers */
    float dpad_unit;
    int   dpad_on;
} Layout;

/* Sizes are fractions of the screen height at size 100%. The look and the
 * proportions follow RetroArch's "flat" PlayStation overlay
 * (libretro/common-overlays, gamepads/flat/psx.cfg): white outlines, arrow
 * buttons pointing at the D-pad's middle, square shoulder buttons, a
 * triangle for Start and a box for Select. The Java editor
 * (org.psxrecomp.TouchLayout) uses the same numbers. */
#define ARM_LEN      0.146f   /* D-pad arrow button, outer edge to point */
#define ARM_WIDTH    0.126f
#define ARM_DIST     0.094f   /* its centre from the D-pad's centre */
#define FACE_R       0.066f   /* face button radius */
#define SHOULDER     0.085f   /* half side of L1/L2/R1/R2 */
#define DPAD_EXTENT  0.170f   /* the D-pad's reach from its centre */
#define STICK_BASE   0.150f   /* joystick: the ring */
#define STICK_KNOB   0.068f   /* joystick: the thumb */
#define STICK_TRAVEL 0.085f   /* how far the thumb shows off centre */

/* Where the buttons go, in pixels: the safe area of a w x h screen. The
 * items' places are fractions of it (the Java editor does the same). */
typedef struct { float x, y, w, h; } Area;
static Area safe_area(int w, int h) {
    int l, t, r, b;
    psx_safe_area_px(w, h, &l, &t, &r, &b);
    Area a = { (float)l, (float)t, (float)(w - l - r), (float)(h - t - b) };
    if (a.w < 1.0f || a.h < 1.0f) a = (Area){ 0.0f, 0.0f, (float)w, (float)h };
    return a;
}

/* A button of half size hw x hh centred at the item, kept in the area. */
static Box place(const TouchItem *it, const Area *a, float hw, float hh, float radius) {
    return (Box){ a->x + clampf(it->x * a->w, hw, a->w - hw),
                  a->y + clampf(it->y * a->h, hh, a->h - hh), hw, hh, radius };
}

static void compute_layout(const TouchSettings *s, int w, int h, Layout *L) {
    const Area a = safe_area(w, h);
    const float base = a.h * (float)s->size / 100.0f;
    memset(L, 0, sizeof *L);

    const TouchItem *d = &s->item[T_DPAD];
    const float ud = base * d->scale;
    const float ext = (s->stick ? STICK_BASE : DPAD_EXTENT) * ud;
    const Box pad = place(d, &a, ext, ext, 0.0f);
    L->dpad_x = pad.cx;
    L->dpad_y = pad.cy;
    L->dpad_unit = ud;
    L->dpad_zone = (s->stick ? STICK_BASE * 1.25f : 0.26f) * ud;
    L->dpad_on = d->shown;
    static const float dir[4][2] = { { 0, -1 }, { 1, 0 }, { 0, 1 }, { -1, 0 } };
    for (int i = 0; i < 4; ++i) {
        const int vertical = dir[i][1] != 0;
        L->e[E_UP + i] = (Box){ L->dpad_x + dir[i][0] * ARM_DIST * ud,
                                L->dpad_y + dir[i][1] * ARM_DIST * ud,
                                (vertical ? ARM_WIDTH : ARM_LEN) * 0.5f * ud,
                                (vertical ? ARM_LEN : ARM_WIDTH) * 0.5f * ud, 0.0f };
        L->on[E_UP + i] = d->shown;
        L->unit[E_UP + i] = ud;
    }
    for (int i = 0; i < 4; ++i) {   /* triangle, circle, cross, square */
        const TouchItem *it = &s->item[T_TRIANGLE + i];
        const float u = base * it->scale, r = FACE_R * u;
        L->e[E_TRIANGLE + i] = place(it, &a, r, r, r);
        L->on[E_TRIANGLE + i] = it->shown;
        L->unit[E_TRIANGLE + i] = u;
    }
    static const int shoulders[4][2] = { { E_L1, T_L1 }, { E_L2, T_L2 }, { E_R1, T_R1 }, { E_R2, T_R2 } };
    for (int i = 0; i < 4; ++i) {
        const TouchItem *it = &s->item[shoulders[i][1]];
        const float u = base * it->scale;
        L->e[shoulders[i][0]] = place(it, &a, SHOULDER * u, SHOULDER * u, 0.018f * u);
        L->on[shoulders[i][0]] = it->shown;
        L->unit[shoulders[i][0]] = u;
    }
    const TouchItem *sel = &s->item[T_SELECT], *st = &s->item[T_START];
    const float us = base * sel->scale, ut = base * st->scale;
    L->e[E_SELECT] = place(sel, &a, 0.062f * us, 0.034f * us, 0.0f);
    L->e[E_START]  = place(st, &a, 0.062f * ut, 0.040f * ut, 0.0f);
    L->on[E_SELECT] = sel->shown;
    L->on[E_START] = st->shown;
    L->unit[E_SELECT] = us;
    L->unit[E_START] = ut;
}

/* ---- fingers --------------------------------------------------------------------- */
#define MAX_FINGERS 10
typedef struct {
    int      used;
    uint64_t touch, finger;
    float    x, y;        /* 0..1 */
    int      dpad;        /* landed on the D-pad: steers for its whole life */
    float    ox, oy;      /* where a joystick finger landed (0..1): its centre
                             for the floating joystick */
} Finger;

static SDL_Mutex    *s_lock;
static TouchSettings s_set;
static Finger        s_fingers[MAX_FINGERS];
static int           s_enabled;
static int           s_pad_hidden;         /* a gamepad was used since the last touch */
static int           s_w = 1920, s_h = 1080;  /* last drawable size (hit tests) */
static uint32_t      s_pressed;            /* element mask, now (drawing) */
/* What the game reads, one state per frame: a slide through the neutral
 * middle, or a tap, can last less than a frame, and the game would never see
 * it (no N between f and d). Each change waits its turn here and is held for
 * at least one frame; touch_controls_frame() moves on at each vblank. */
#define QUEUE_MAX 6
static uint32_t      s_queue[QUEUE_MAX];
static int           s_queued = 1;
static int           s_head_seen = 1;      /* the game has had s_queue[0] for a frame */
static unsigned      s_draw_calls, s_drawn; /* frames asked / frames with buttons */
static unsigned      s_touches;            /* fingers that landed */

/* The D-pad's or joystick's centre for a finger. */
static void stick_centre(const Layout *L, const Finger *f, float *cx, float *cy) {
    if (s_set.stick == 2) { *cx = f->ox * (float)s_w; *cy = f->oy * (float)s_h; }
    else { *cx = L->dpad_x; *cy = L->dpad_y; }
}

static int dpad_dirs(const Layout *L, const Finger *f, float px, float py) {
    float cx, cy;
    stick_centre(L, f, &cx, &cy);
    const float dx = px - cx, dy = py - cy;
    /* The neutral middle: sliding through it releases the directions. */
    const float dead = (float)s_set.neutral / 100.0f *
                       (s_set.stick ? STICK_BASE : DPAD_EXTENT) * L->dpad_unit;
    if (dx * dx + dy * dy < dead * dead) return 0;
    /* Eight 45-degree sectors: a diagonal holds two directions. */
    int mask = 0;
    if (fabsf(dx) > 0.4142f * fabsf(dy)) mask |= 1u << (dx > 0 ? E_RIGHT : E_LEFT);
    if (fabsf(dy) > 0.4142f * fabsf(dx)) mask |= 1u << (dy > 0 ? E_DOWN : E_UP);
    return mask;
}

static int in_box(const Box *b, float px, float py, float grow) {
    return fabsf(px - b->cx) <= b->hw * grow && fabsf(py - b->cy) <= b->hh * grow;
}

static uint32_t buttons_at(const Layout *L, float px, float py) {
    uint32_t mask = 0;
    /* Face buttons reach a little past their circle: a finger between two
     * of them (when they sit close) presses both. */
    for (int i = E_TRIANGLE; i <= E_SQUARE; ++i) {
        if (!L->on[i]) continue;
        const float dx = px - L->e[i].cx, dy = py - L->e[i].cy, reach = L->e[i].radius * 1.3f;
        if (dx * dx + dy * dy <= reach * reach) mask |= 1u << i;
    }
    for (int i = E_L1; i <= E_START; ++i)
        if (L->on[i] && in_box(&L->e[i], px, py, 1.15f)) mask |= 1u << i;
    return mask;
}

static void recompute_locked(void) {
    Layout L;
    compute_layout(&s_set, s_w, s_h, &L);
    uint32_t mask = 0;
    for (int i = 0; i < MAX_FINGERS; ++i) {
        const Finger *f = &s_fingers[i];
        if (!f->used) continue;
        const float px = f->x * (float)s_w, py = f->y * (float)s_h;
        mask |= f->dpad ? (uint32_t)dpad_dirs(&L, f, px, py) : buttons_at(&L, px, py);
    }
    s_pressed = mask;
    if (mask == s_queue[s_queued - 1]) return;
    if (s_queued == 1 && s_head_seen) { s_queue[0] = mask; s_head_seen = 0; }   /* no delay */
    else if (s_queued < QUEUE_MAX) s_queue[s_queued++] = mask;
    else s_queue[QUEUE_MAX - 1] = mask;   /* full: keep the latest, bound the delay */
}

static void release_all_locked(void) {
    memset(s_fingers, 0, sizeof s_fingers);
    s_pressed = 0;
    s_queue[0] = 0;
    s_queued = 1;
    s_head_seen = 1;
}

#if defined(PSX_SDL3)
static Finger *find_finger(uint64_t touch, uint64_t finger) {
    for (int i = 0; i < MAX_FINGERS; ++i)
        if (s_fingers[i].used && s_fingers[i].touch == touch && s_fingers[i].finger == finger)
            return &s_fingers[i];
    return NULL;
}

/* PSX_TOUCH_MOUSE=1 (desktop testing): the left mouse button is a finger. */
static int s_mouse_finger;
static bool mouse_as_finger(SDL_Event *ev) {
    if (!s_mouse_finger) return false;
    int type;
    float x, y;
    if (ev->type == SDL_EVENT_MOUSE_BUTTON_DOWN || ev->type == SDL_EVENT_MOUSE_BUTTON_UP) {
        if (ev->button.button != SDL_BUTTON_LEFT) return false;
        type = ev->type == SDL_EVENT_MOUSE_BUTTON_DOWN ? SDL_EVENT_FINGER_DOWN : SDL_EVENT_FINGER_UP;
        x = ev->button.x; y = ev->button.y;
    } else if (ev->type == SDL_EVENT_MOUSE_MOTION && (ev->motion.state & SDL_BUTTON_LMASK)) {
        type = SDL_EVENT_FINGER_MOTION;
        x = ev->motion.x; y = ev->motion.y;
    } else {
        return false;
    }
    int w = 0, h = 0;
    SDL_Window *win = SDL_GetWindowFromEvent(ev);
    if (!win || !SDL_GetWindowSize(win, &w, &h) || w <= 0 || h <= 0) return false;
    SDL_zerop(ev);
    ev->type = (Uint32)type;
    ev->tfinger.touchID = 1;
    ev->tfinger.fingerID = 1;
    ev->tfinger.x = x / (float)w;
    ev->tfinger.y = y / (float)h;
    return true;
}

static bool SDLCALL touch_event_watch(void *userdata, SDL_Event *event) {
    (void)userdata;
    SDL_Event mouse = *event;
    SDL_Event *ev = mouse_as_finger(&mouse) ? &mouse : event;
    switch (ev->type) {
    case SDL_EVENT_FINGER_DOWN:
    case SDL_EVENT_FINGER_MOTION:
    case SDL_EVENT_FINGER_UP:
    case SDL_EVENT_FINGER_CANCELED:
        break;
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
        s_pad_hidden = 1;
        return true;
    case SDL_EVENT_GAMEPAD_AXIS_MOTION:
        /* A real push: triggers rest at their low end on some pads. */
        if (ev->gaxis.value > 16000 ||
            (ev->gaxis.value < -16000 && ev->gaxis.axis != SDL_GAMEPAD_AXIS_LEFT_TRIGGER &&
             ev->gaxis.axis != SDL_GAMEPAD_AXIS_RIGHT_TRIGGER))
            s_pad_hidden = 1;
        return true;
    case SDL_EVENT_WINDOW_FOCUS_LOST:
    case SDL_EVENT_DID_ENTER_BACKGROUND:
        SDL_LockMutex(s_lock);
        release_all_locked();
        SDL_UnlockMutex(s_lock);
        return true;
    default:
        return true;
    }
    SDL_LockMutex(s_lock);
    const SDL_TouchFingerEvent *t = &ev->tfinger;
    Finger *f = find_finger((uint64_t)t->touchID, (uint64_t)t->fingerID);
    if (ev->type == SDL_EVENT_FINGER_DOWN) {
        s_pad_hidden = 0;
        s_touches++;
        if (!f) {
            for (int i = 0; i < MAX_FINGERS && !f; ++i)
                if (!s_fingers[i].used) f = &s_fingers[i];
        }
        if (f) {
            Layout L;
            compute_layout(&s_set, s_w, s_h, &L);
            const float dx = t->x * (float)s_w - L.dpad_x, dy = t->y * (float)s_h - L.dpad_y;
            f->used = 1;
            f->touch = (uint64_t)t->touchID;
            f->finger = (uint64_t)t->fingerID;
            f->x = t->x;
            f->y = t->y;
            f->dpad = L.dpad_on && dx * dx + dy * dy <= L.dpad_zone * L.dpad_zone;
            f->ox = t->x;
            f->oy = t->y;
            /* Floating joystick: a thumb landing anywhere in the left half
             * (off the shoulder and Select/Start buttons) takes the stick,
             * centred where it landed. One thumb at a time. */
            if (s_set.stick == 2 && L.dpad_on && !f->dpad && t->x < 0.5f &&
                !(buttons_at(&L, t->x * (float)s_w, t->y * (float)s_h))) {
                int taken = 0;
                for (int i = 0; i < MAX_FINGERS; ++i)
                    taken |= &s_fingers[i] != f && s_fingers[i].used && s_fingers[i].dpad;
                f->dpad = !taken;
            }
        }
    } else if (f && ev->type == SDL_EVENT_FINGER_MOTION) {
        f->x = t->x;
        f->y = t->y;
    } else if (f) {
        f->used = 0;
    }
    recompute_locked();
    SDL_UnlockMutex(s_lock);
    return true;
}
#endif

static char s_ini_path[1024];

void touch_controls_reload(void) {
    TouchSettings set;
    load_settings(&set, s_ini_path[0] ? s_ini_path : NULL);
    if (s_lock) SDL_LockMutex(s_lock);
    s_set = set;
    release_all_locked();
    if (s_lock) SDL_UnlockMutex(s_lock);
}

void touch_controls_init(const char *ini_path) {
    snprintf(s_ini_path, sizeof s_ini_path, "%s", ini_path ? ini_path : "");
    load_settings(&s_set, ini_path);
#if defined(PSX_SDL3)
    if (!s_lock) {
        const char *mouse = SDL_getenv("PSX_TOUCH_MOUSE");
        s_mouse_finger = mouse && mouse[0] == '1';
        s_lock = SDL_CreateMutex();
        SDL_AddEventWatch(touch_event_watch, NULL);
    }
#endif
}

void touch_controls_set_enabled(int enabled) {
    if ((enabled ? 1 : 0) != s_enabled)
        fprintf(stdout, "psxrecomp: touch controls %s\n", enabled ? "on" : "off");
    if (s_lock) SDL_LockMutex(s_lock);
    s_enabled = enabled ? 1 : 0;
    if (!s_enabled) release_all_locked();
    if (s_lock) SDL_UnlockMutex(s_lock);
}

int touch_controls_enabled(void) { return s_enabled; }

void touch_controls_release_all(void) {
    if (!s_lock) return;
    SDL_LockMutex(s_lock);
    release_all_locked();
    SDL_UnlockMutex(s_lock);
}

void touch_controls_frame(void) {
    if (!s_lock) return;
    SDL_LockMutex(s_lock);
    if (s_queued > 1) {
        memmove(s_queue, s_queue + 1, (size_t)(s_queued - 1) * sizeof s_queue[0]);
        s_queued--;
        s_head_seen = 0;
    } else {
        s_head_seen = 1;
    }
    SDL_UnlockMutex(s_lock);
}

uint16_t touch_controls_pad_word(void) {
    if (!s_enabled || !s_lock) return 0xFFFF;
    SDL_LockMutex(s_lock);
    const uint32_t pressed = s_queue[0];
    SDL_UnlockMutex(s_lock);
    uint16_t word = 0xFFFF;
    for (int i = 0; i < E_COUNT; ++i)
        if (pressed & (1u << i)) word &= (uint16_t)~kBits[i];
    return word;
}

/* ---- drawing ------------------------------------------------------------------------ */
/* A stroke font for the labels, on a 4 x 6 grid (y down). */
typedef struct { char c; int n; signed char s[12][4]; } StrokeGlyph;
static const StrokeGlyph kFont[] = {
    { 'L', 2, { {0,0,0,6}, {0,6,4,6} } },
    { 'R', 7, { {0,6,0,0}, {0,0,3,0}, {3,0,4,1}, {4,1,4,2}, {4,2,3,3}, {3,3,0,3}, {2,3,4,6} } },
    { '1', 3, { {1,1,2,0}, {2,0,2,6}, {1,6,3,6} } },
    { '2', 6, { {0,1,1,0}, {1,0,3,0}, {3,0,4,1}, {4,1,4,2}, {4,2,0,6}, {0,6,4,6} } },
    { 'S', 11, { {4,1,3,0}, {3,0,1,0}, {1,0,0,1}, {0,1,0,2}, {0,2,1,3}, {1,3,3,3},
                 {3,3,4,4}, {4,4,4,5}, {4,5,3,6}, {3,6,1,6}, {1,6,0,5} } },
    { 'T', 2, { {0,0,4,0}, {2,0,2,6} } },
    { 'A', 3, { {0,6,2,0}, {2,0,4,6}, {1,4,3,4} } },
    { 'E', 4, { {4,0,0,0}, {0,0,0,6}, {0,6,4,6}, {0,3,3,3} } },
    { 'C', 7, { {4,1,3,0}, {3,0,1,0}, {1,0,0,1}, {0,1,0,5}, {0,5,1,6}, {1,6,3,6}, {3,6,4,5} } },
};

static void add_seg(TouchDrawItem *it, float x0, float y0, float x1, float y1) {
    if (it->seg_count >= TOUCH_MAX_SEGS) return;
    float *s = it->segs[it->seg_count++];
    s[0] = x0; s[1] = y0; s[2] = x1; s[3] = y1;
}

static void add_text(TouchDrawItem *it, const char *text, float height) {
    const float k = height / 6.0f, advance = 6.0f * k;
    const float width = (float)strlen(text) * advance - 2.0f * k;
    float x = -width * 0.5f;
    for (const char *c = text; *c; ++c, x += advance) {
        for (size_t g = 0; g < sizeof kFont / sizeof kFont[0]; ++g) {
            if (kFont[g].c != *c) continue;
            for (int i = 0; i < kFont[g].n; ++i) {
                const signed char *s = kFont[g].s[i];
                add_seg(it, x + s[0] * k, (s[1] - 3) * k, x + s[2] * k, (s[3] - 3) * k);
            }
        }
    }
}

/* A closed polygon from `n` points on a circle (triangle, square, arrows). */
static void add_poly(TouchDrawItem *it, int n, float radius, float angle_deg) {
    const float a0 = angle_deg * 3.14159265f / 180.0f;
    for (int i = 0; i < n; ++i) {
        const float a = a0 + 2.0f * 3.14159265f * (float)i / (float)n;
        const float b = a0 + 2.0f * 3.14159265f * (float)(i + 1) / (float)n;
        add_seg(it, cosf(a) * radius, sinf(a) * radius, cosf(b) * radius, sinf(b) * radius);
    }
}

static void set4(float *d, float r, float g, float b, float a) { d[0] = r; d[1] = g; d[2] = b; d[3] = a; }

static void add_vertex(TouchDrawItem *it, float x, float y) {
    if (it->poly_count >= TOUCH_MAX_POLY) return;
    it->poly[it->poly_count][0] = x;
    it->poly[it->poly_count][1] = y;
    it->poly_count++;
}

/* A small solid triangle: its outline, stroked as wide as it is thick. */
static void add_solid_triangle(TouchDrawItem *it, float cx, float cy, float r, float angle_deg) {
    const int first = it->seg_count;
    add_poly(it, 3, r, angle_deg);
    for (int s = first; s < it->seg_count; ++s) {
        it->segs[s][0] += cx; it->segs[s][2] += cx;
        it->segs[s][1] += cy; it->segs[s][3] += cy;
    }
}

/* The flat look: outlines, a faint shade inside, lit while held. */
static void style(TouchDrawItem *it, int on, float alpha, float u) {
    if (on) set4(it->fill, 1.0f, 1.0f, 1.0f, 0.35f * alpha);
    else    set4(it->fill, 0.0f, 0.0f, 0.0f, 0.12f * alpha);
    set4(it->edge, 1.0f, 1.0f, 1.0f, 0.90f * alpha);
    set4(it->ink, 1.0f, 1.0f, 1.0f, 0.95f * alpha);
    it->border = fmaxf(1.5f, 0.0045f * u);
    it->stroke = fmaxf(1.0f, 0.0060f * u);
}

void touch_controls_describe(char *out, int cap) {
    snprintf(out, (size_t)cap, "Touch controls: %s%s%s, %s; drawn %u of %u frames; %u touches",
             s_enabled ? "on" : "off", s_lock ? "" : " (not started)",
             s_pad_hidden ? ", hidden (a controller was used)" : "",
             s_set.visible ? "shown" : "hidden in settings", s_drawn, s_draw_calls, s_touches);
}

int touch_controls_draw_list(int w, int h, TouchDrawItem *out, int max) {
    s_draw_calls++;
    if (!s_enabled || !s_lock || w <= 0 || h <= 0 || !out) return 0;
    SDL_LockMutex(s_lock);
    static float seen_safe[4];
    if (w != s_w || h != s_h || memcmp(seen_safe, (const float *)s_safe, sizeof seen_safe) != 0) {
        s_w = w;
        s_h = h;
        memcpy(seen_safe, (const float *)s_safe, sizeof seen_safe);
        recompute_locked();
    }
    const TouchSettings set = s_set;
    const uint32_t pressed = s_pressed;
    const int hidden = !set.visible || s_pad_hidden;
    SDL_UnlockMutex(s_lock);
    if (hidden) return 0;

    Layout L;
    compute_layout(&set, w, h, &L);
    const float alpha = (float)set.opacity / 100.0f;
    int n = 0;
    if (set.stick && L.dpad_on && n + 2 <= max) {
        const float u = L.dpad_unit;
        /* The ring (where it was grabbed, for the floating one) and the
         * thumb, pushed toward the finger. */
        float cx = L.dpad_x, cy = L.dpad_y, kx = 0.0f, ky = 0.0f;
        int held = 0;
        SDL_LockMutex(s_lock);
        for (int f = 0; f < MAX_FINGERS; ++f) {
            if (!s_fingers[f].used || !s_fingers[f].dpad) continue;
            stick_centre(&L, &s_fingers[f], &cx, &cy);
            kx = s_fingers[f].x * (float)w - cx;
            ky = s_fingers[f].y * (float)h - cy;
            held = 1;
            break;
        }
        SDL_UnlockMutex(s_lock);
        const float len = sqrtf(kx * kx + ky * ky), travel = STICK_TRAVEL * u;
        if (len > travel) { kx *= travel / len; ky *= travel / len; }
        TouchDrawItem *ring = &out[n++];
        memset(ring, 0, sizeof *ring);
        style(ring, 0, alpha, u);
        ring->cx = cx; ring->cy = cy;
        ring->half_w = ring->half_h = ring->radius = STICK_BASE * u;
        ring->fill[3] = 0.06f * alpha;
        ring->border = fmaxf(1.2f, 0.0035f * u);
        TouchDrawItem *knob = &out[n++];
        memset(knob, 0, sizeof *knob);
        style(knob, held, alpha, u);
        knob->cx = cx + kx; knob->cy = cy + ky;
        knob->half_w = knob->half_h = knob->radius = STICK_KNOB * u;
        knob->border = fmaxf(2.0f, 0.0075f * u);
        knob->dots = 0.016f * u;   /* the grip */
    }
    for (int i = 0; i < E_COUNT && n < max; ++i) {
        if (!L.on[i] || (set.stick && i <= E_LEFT)) continue;   /* hidden; the joystick replaces the arrows */
        const float u = L.unit[i];
        TouchDrawItem *it = &out[n++];
        memset(it, 0, sizeof *it);
        const Box *b = &L.e[i];
        style(it, (pressed >> i) & 1u, alpha, u);
        it->cx = b->cx; it->cy = b->cy;
        it->half_w = b->hw; it->half_h = b->hh; it->radius = b->radius;
        const float r = b->hw;
        switch (i) {
        case E_UP: case E_RIGHT: case E_DOWN: case E_LEFT: {
            /* A pentagon: square outside, a point toward the middle; a small
             * solid arrow pointing outward. Drawn for "up", then turned. */
            static const float rot[4][2] = { { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 } };
            const float c = rot[i - E_UP][0], s = rot[i - E_UP][1];
            const float hw = ARM_WIDTH * 0.5f * u, hl = ARM_LEN * 0.5f * u;
            const float pts[5][2] = { { -hw, -hl }, { hw, -hl }, { hw, hl - hw },
                                      { 0.0f, hl }, { -hw, hl - hw } };
            for (int k = 0; k < 5; ++k)
                add_vertex(it, pts[k][0] * c - pts[k][1] * s, pts[k][0] * s + pts[k][1] * c);
            const float ay = -hl * 0.42f, ar = 0.021f * u;
            add_solid_triangle(it, -ay * s, ay * c, ar, -90.0f + 90.0f * (float)(i - E_UP));
            it->stroke = ar * 0.5f;
            break;
        }
        case E_TRIANGLE:
            add_poly(it, 3, r * 0.50f, -90.0f);
            for (int s = 0; s < it->seg_count; ++s) { it->segs[s][1] += r * 0.1f; it->segs[s][3] += r * 0.1f; }
            break;
        case E_CIRCLE:
            it->ring = r * 0.43f;
            break;
        case E_CROSS:
            add_seg(it, -r * 0.38f, -r * 0.38f, r * 0.38f, r * 0.38f);
            add_seg(it, -r * 0.38f, r * 0.38f, r * 0.38f, -r * 0.38f);
            break;
        case E_SQUARE:
            add_poly(it, 4, r * 0.50f, 45.0f);
            break;
        case E_L1: add_text(it, "L1", b->hh * 0.62f); break;
        case E_L2: add_text(it, "L2", b->hh * 0.62f); break;
        case E_R1: add_text(it, "R1", b->hh * 0.62f); break;
        case E_R2: add_text(it, "R2", b->hh * 0.62f); break;
        case E_SELECT: break;   /* the box itself */
        case E_START:           /* a triangle pointing right */
            add_vertex(it, -b->hw, -b->hh);
            add_vertex(it, b->hw, 0.0f);
            add_vertex(it, -b->hw, b->hh);
            break;
        }
        if (i >= E_L1 && i <= E_R2) it->stroke = fmaxf(1.0f, 0.0055f * u);
        if (i <= E_LEFT || i >= E_SELECT) it->border = fmaxf(1.2f, 0.0035f * u);
    }
    if (n > 0) s_drawn++;
    return n;
}
