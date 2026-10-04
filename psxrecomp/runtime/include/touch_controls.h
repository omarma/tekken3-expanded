#ifndef PSX_TOUCH_CONTROLS_H
#define PSX_TOUCH_CONTROLS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * On-screen touch controls (a PS1 pad drawn over the game) for the player
 * whose input source is "touch" (Android). Fingers are read from SDL touch
 * events; the renderer draws the buttons over the presented frame.
 *
 * Settings come from touch_controls.ini beside the runtime (the Android
 * launcher's Touch page and the layout editor write it): visible, opacity,
 * size, and each button's place, size and whether it shows. The controls
 * hide while a gamepad is being used and come back on the next touch.
 */

/* Read the settings file and start listening to touch events. */
void touch_controls_init(const char *ini_path);

/* Read the settings file again (the layout editor saved it). */
void touch_controls_reload(void);

/* 1 while a player's input source is touch (the buttons draw and act). */
void touch_controls_set_enabled(int enabled);
int  touch_controls_enabled(void);

/* Let go of every finger (a menu opened over the game took the touches). */
void touch_controls_release_all(void);

/* For the in-game menu's status line: one line of text. */
void touch_controls_describe(char *out, int cap);

/* The PS1 button word the fingers hold (active-low: 0xFFFF = none). */
/* Once per frame (vblank): the game sees each touch state for at least one
 * frame, in order, even a slide or a tap shorter than a frame. */
void touch_controls_frame(void);
uint16_t touch_controls_pad_word(void);

/* ---- the safe area ----------------------------------------------------------
 * The part of the screen clear of a display cutout (a phone's notch or punch
 * hole), as insets from each edge in fractions of the screen; the Android
 * activity reports them (org.psxrecomp.SafeArea). The buttons are laid out
 * inside it, and the game's picture keeps out of the insets when it would
 * otherwise reach into them. All zero (the whole screen) everywhere else. */
void psx_safe_area_set(float left, float top, float right, float bottom);

/* The insets in pixels on a w x h drawable. */
void psx_safe_area_px(int w, int h, int *left, int *top, int *right, int *bottom);

/* ---- drawing ----------------------------------------------------------------
 * One item per shape, in drawable pixels with the origin at the top left.
 * A shape is a rounded box (a circle when radius == half_w == half_h) or a
 * convex polygon, filled and outlined, with an ink drawing inside: line
 * segments (relative to the centre), an optional ring and optional dots. */
#define TOUCH_MAX_SEGS 32
#define TOUCH_MAX_POLY 8
typedef struct {
    float cx, cy, half_w, half_h, radius;
    float fill[4];      /* straight RGBA */
    float edge[4];      /* outline RGBA */
    float ink[4];       /* glyph RGBA */
    float border;       /* outline width in pixels */
    float stroke;       /* glyph line half-width in pixels */
    float ring;         /* glyph ring radius (0 = none) */
    int   seg_count;
    float segs[TOUCH_MAX_SEGS][4];   /* x0, y0, x1, y1 */
    int   poly_count;                /* > 0: the shape is this convex polygon */
    float poly[TOUCH_MAX_POLY][2];   /* relative to the centre */
    float dots;                      /* > 0: a grip of dots this far apart */
} TouchDrawItem;

#define TOUCH_MAX_ITEMS 20

/* Fill `out` with what to draw over a w x h drawable; 0 when nothing shows. */
int touch_controls_draw_list(int w, int h, TouchDrawItem *out, int max);

#ifdef __cplusplus
}
#endif

#endif /* PSX_TOUCH_CONTROLS_H */
