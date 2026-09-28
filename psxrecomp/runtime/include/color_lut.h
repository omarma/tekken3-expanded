/* color_lut.h — present-time screen-color simulation (BGR555 -> RGB888 LUT).
 *
 * PRESENT-TIME ONLY. This never touches the emulation, the VRAM the GPU
 * produces, or the differential-verify path — diff_frame / oracle comparisons
 * stay defined on the raw RGB888 expansion the GPU scanout produces. The LUT
 * is a 32768-entry table consulted at the 15-bit-scanout -> RGB888 conversion
 * step (gpu_rgb555_to_rgb888), and it defaults to Raw (exact 5->8 passthrough),
 * so default behavior and every hashed/verified frame are byte-identical unless
 * a screen model is opted in via PSX_SCREEN={raw,crt,composite,trinitron}.
 *
 * The math is first-principles CIE colorimetry (xyY->XYZ, primaries->matrix,
 * Bradford adaptation, sRGB OETF) over a CRT/composite display model; it is not
 * a ported shader.
 *
 * SCOPE / WHAT IS MODELLED vs DOCUMENTED-ONLY:
 *   - The 15-bit (BGR555) display path is fully covered: each scanout pixel is
 *     a 5-bit-per-channel index into the baked table.
 *   - The 24-bit (depth24, FMV) display path is NOT colour-mapped here — those
 *     frames already carry 8-bit-per-channel data and have no 5-bit hardware
 *     index to key the table on; they pass through untouched (documented).
 *   - The model is a REASONABLE consumer-CRT / composite approximation (SMPTE-C
 *     phosphors, ~2.4 display gamma, a small black lift). The real per-TV
 *     transfer and the composite-encoder bandwidth/notch effects are NOT
 *     guessed at the signal level — only a colorimetric approximation is baked.
 *     See docs/SHADOW_ENHANCEMENTS.md for what is approximated.
 *
 * ── Attribution ───────────────────────────────────────────────────
 * Ported from JRickey/gba-recomp (https://github.com/JRickey/gba-recomp),
 * crates/screen/src/{color,profile,lut}.rs, via the gbarecomp C++ port
 * (src/runtime/color_lut.*), © Jrickey, MIT OR Apache-2.0, used with
 * permission. The C re-implementation and the CRT/composite panel models are
 * ours. See THIRD_PARTY_ATTRIBUTION.md.
 */

#ifndef PSXRECOMP_COLOR_LUT_H
#define PSXRECOMP_COLOR_LUT_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Which physical display model to simulate. */
typedef enum {
  SCREEN_RAW = 0,    /* 5->8 bit replication, untouched (default; passthrough) */
  SCREEN_CRT,        /* generic consumer CRT (SMPTE-C phosphors, gamma ~2.4) */
  SCREEN_COMPOSITE,  /* CRT via composite: same phosphors, lifted black + softer */
  SCREEN_TRINITRON,  /* late near-sRGB Trinitron-class tube, clean blacks */
} ScreenKind;

/* Display colorspace the emitted bytes are interpreted in. */
typedef enum {
  DISPLAY_SRGB = 0,
  DISPLAY_P3,
} DisplayTarget;

/* Parse a config/env token; returns false if unrecognized. */
bool screen_kind_from_name(const char* name, ScreenKind* out);

typedef struct {
  ScreenKind    screen;   /* default SCREEN_RAW */
  double        darken;   /* <0 = per-screen default */
  DisplayTarget target;   /* default DISPLAY_SRGB */
} ColorSettings;

/* A baked BGR555 -> RGB888 table. Build once per settings change; apply per
 * scanout pixel as one indexed lookup. Opaque to callers. */
typedef struct ColorLut ColorLut;

ColorLut* color_lut_create(const ColorSettings* settings);
void      color_lut_destroy(ColorLut* lut);
bool      color_lut_is_passthrough(const ColorLut* lut);

/* Map one BGR555 hardware pixel (red=low 5 bits, as in PS1 VRAM) to RGB888. */
void color_lut_map555(const ColorLut* lut, uint16_t bgr555,
                      uint8_t* r, uint8_t* g, uint8_t* b);

#ifdef __cplusplus
}
#endif

#endif  /* PSXRECOMP_COLOR_LUT_H */
