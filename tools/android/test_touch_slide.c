/* test_touch_slide.c — the on-screen D-pad, slid as a thumb does an Electric
 * (f, N, d, d/f + 2): every state reaches the game for a frame, in order,
 * even when the whole slide happens within one frame.
 *
 *   python3 tools/android/test_touch_slide.py   (builds and runs this on the
 *   desktop against the SDL3 of a Linux build)
 */
#define PSX_SDL3 1
#include "../../psxrecomp/runtime/src/touch_controls.c"

#include <stdlib.h>

static int failures;

/* The pad word's D-pad bits (active low) as a name. */
static const char *dirs(uint16_t w) {
    const int u = !(w & 0x0010), r = !(w & 0x0020), d = !(w & 0x0040), l = !(w & 0x0080);
    if (d && r) return "d/f";
    if (u) return "u"; if (l) return "b";
    if (d) return "d"; if (r) return "f";
    return "N";
}

static void finger(SDL_EventType type, float x, float y) {
    SDL_Event ev;
    SDL_zero(ev);
    ev.type = type;
    ev.tfinger.touchID = 1;
    ev.tfinger.fingerID = 1;
    ev.tfinger.x = x / (float)s_w;
    ev.tfinger.y = y / (float)s_h;
    SDL_PushEvent(&ev);
}

/* A point of the D-pad: dx, dy in its reach (DPAD_EXTENT) units. */
static void at(SDL_EventType type, const Layout *L, float dx, float dy) {
    const float reach = DPAD_EXTENT * L->dpad_unit;
    finger(type, L->dpad_x + dx * reach, L->dpad_y + dy * reach);
}

static void expect(const char *what, const char *const *want, int n) {
    for (int i = 0; i < n; ++i) {
        const char *got = dirs(touch_controls_pad_word());
        if (strcmp(got, want[i]) != 0) {
            printf("FAIL %s: frame %d reads %s, expected %s\n", what, i, got, want[i]);
            failures++;
        }
        touch_controls_frame();
    }
    printf("%s %s\n", failures ? "...." : "ok  ", what);
}

int main(void) {
    if (SDL_Init(SDL_INIT_EVENTS) != 0) {   /* psx_sdl.h: 0 on success */
        printf("SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    touch_controls_init(NULL);          /* defaults: the cross, neutral 35% */
    touch_controls_set_enabled(1);
    Layout L;
    compute_layout(&s_set, s_w, s_h, &L);

    /* 1. The whole slide inside one frame: f, through the middle, d, d/f. */
    at(SDL_EVENT_FINGER_DOWN, &L, 0.55f, 0.0f);
    at(SDL_EVENT_FINGER_MOTION, &L, 0.10f, 0.05f);
    at(SDL_EVENT_FINGER_MOTION, &L, 0.0f, 0.55f);
    at(SDL_EVENT_FINGER_MOTION, &L, 0.40f, 0.40f);
    static const char *const electric[] = { "f", "N", "d", "d/f", "d/f" };
    expect("Electric slide within one frame: f, N, d, d/f", electric, 5);
    at(SDL_EVENT_FINGER_UP, &L, 0.40f, 0.40f);
    static const char *const up[] = { "N" };
    expect("lifting the thumb lets go", up, 1);

    /* 2. A slide that stays on the arms (no middle) rolls through d/f. */
    at(SDL_EVENT_FINGER_DOWN, &L, 0.55f, 0.0f);
    at(SDL_EVENT_FINGER_MOTION, &L, 0.45f, 0.45f);
    at(SDL_EVENT_FINGER_MOTION, &L, 0.0f, 0.55f);
    static const char *const roll[] = { "f", "d/f", "d", "d" };
    expect("rolling on the arms: f, d/f, d (a quarter circle)", roll, 4);
    at(SDL_EVENT_FINGER_UP, &L, 0.0f, 0.55f);
    touch_controls_frame();

    /* 3. A tap shorter than a frame is still seen. */
    at(SDL_EVENT_FINGER_DOWN, &L, 0.55f, 0.0f);
    at(SDL_EVENT_FINGER_UP, &L, 0.55f, 0.0f);
    static const char *const tap[] = { "f", "N" };
    expect("a tap within one frame", tap, 2);

    /* 4. The delay stays bounded however much the thumb wiggles. */
    at(SDL_EVENT_FINGER_DOWN, &L, 0.55f, 0.0f);
    for (int i = 0; i < 40; ++i)
        at(SDL_EVENT_FINGER_MOTION, &L, (i & 1) ? 0.55f : 0.0f, (i & 1) ? 0.0f : 0.55f);
    int frames = 0;
    while (s_queued > 1 && frames < 100) { touch_controls_frame(); frames++; }
    if (frames > QUEUE_MAX) { printf("FAIL the queue took %d frames\n", frames); failures++; }
    else printf("ok   40 changes in a frame catch up in %d frames\n", frames);

    printf(failures ? "%d failures\n" : "all passed\n", failures);
    SDL_Quit();
    return failures != 0;
}
