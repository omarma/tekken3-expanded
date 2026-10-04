/* gpu_render.c — renderer facade / backend dispatch.
 *
 * gpu.c and main.cpp call the gr_* functions; this file forwards each to the
 * selected backend's vtable.  The software rasterizer is the default and the
 * fallback.  The OpenGL backend (gpu_gl_renderer.c) is selected via
 * gr_set_backend(GR_BACKEND_OPENGL) and supplies its table through
 * gl_backend_get(); if that returns NULL (GL unavailable / init failed) we
 * stay on software so a misconfigured [video] renderer never bricks boot.
 *
 * The software backend table points straight at the existing sw_* functions,
 * so the software path is byte-for-byte unchanged. */

#include "gpu_render.h"
#include "gpu_sw_renderer.h"
#include <stdio.h>

static const GpuRenderBackend SW_BACKEND = {
    .name                          = "software",
    .init                          = sw_renderer_init,
    .set_scale                     = sw_renderer_set_scale,
    .scale                         = sw_renderer_scale,
    .set_texture_filter            = sw_set_texture_filter,
    .texture_filter                = sw_texture_filter,
    .set_semi_transparency         = sw_set_semi_transparency,
    .set_mask_bits                 = sw_set_mask_bits,
    .set_texture_window            = sw_set_texture_window,
    .set_color_modulation          = sw_set_color_modulation,
    .set_precise_triangle          = sw_set_precise_triangle,
    .set_perspective_triangle      = sw_set_perspective_triangle,
    .fill_rect                     = sw_fill_rect,
    .copy_rect                     = sw_copy_rect,
    .draw_flat_triangle            = sw_draw_flat_triangle,
    .draw_gouraud_triangle         = sw_draw_gouraud_triangle,
    .draw_textured_triangle        = sw_draw_textured_triangle,
    .draw_shaded_textured_triangle = sw_draw_shaded_textured_triangle,
    .draw_flat_rect                = sw_draw_flat_rect,
    .draw_textured_rect            = sw_draw_textured_rect,
    .draw_textured_rect_scaled     = sw_draw_textured_rect_scaled,
    .draw_line                     = sw_draw_line,
    .draw_shaded_line              = sw_draw_shaded_line,
    .render_display                = sw_render_display,
    .render_display_hires          = sw_render_display_hires,
    .vram_write                    = sw_vram_write,
    .vram_read                     = sw_vram_read,
    .vram_transfer_in              = sw_vram_transfer_in,
    .vram_transfer_out             = sw_vram_transfer_out,
    .set_draw_area                 = sw_set_draw_area,
    .get_draw_area                 = sw_get_draw_area,
    .set_draw_offset               = sw_set_draw_offset,
    .wide_configure                = sw_wide_configure,
    .wide_set_target               = sw_wide_set_target,
    .wide_disable_target           = sw_wide_disable_target,
    .wide_set_primitive_x_delta    = sw_wide_set_primitive_x_delta,
    .wide_set_primitive_suppressed = sw_wide_set_primitive_suppressed,
    .wide_set_primitive_unclipped  = sw_wide_set_primitive_unclipped,
    .wide_set_primitive_expanded   = sw_wide_set_primitive_expanded,
    .wide_clear                    = sw_wide_clear,
    .wide_clear_margins            = sw_wide_clear_margins,
    .wide_set_mirror_authoritative = sw_wide_set_mirror_authoritative,
    .wide_set_sidecar_complete     = sw_wide_set_sidecar_complete,
    .render_wide_display           = sw_render_wide_display,
    .wide_dump_full                = sw_wide_dump_full,
};

/* Supplied by gpu_gl_renderer.c; returns NULL until the GL backend is ready. */
extern const GpuRenderBackend *gl_backend_get(void);
/* Supplied by gpu_vk_renderer.c; returns NULL until the Vulkan backend is
 * ready (init succeeded). When Vulkan isn't compiled in it returns NULL. */
extern const GpuRenderBackend *vk_backend_get(void);

static const GpuRenderBackend *g_b         = &SW_BACKEND;
static GrBackend               g_effective = GR_BACKEND_SOFTWARE;

void gr_set_backend(GrBackend backend) {
    if (backend == GR_BACKEND_OPENGL) {
        const GpuRenderBackend *gl = gl_backend_get();
        if (gl) {
            g_b = gl;
            g_effective = GR_BACKEND_OPENGL;
            fprintf(stdout, "psxrecomp: renderer = opengl (%s)\n", gl->name);
            return;
        }
        fprintf(stdout, "psxrecomp: renderer = opengl requested but unavailable "
                        "— falling back to software\n");
    } else if (backend == GR_BACKEND_VULKAN) {
        const GpuRenderBackend *vk = vk_backend_get();
        if (vk) {
            g_b = vk;
            g_effective = GR_BACKEND_VULKAN;
            fprintf(stdout, "psxrecomp: renderer = vulkan (%s)\n", vk->name);
            return;
        }
        fprintf(stdout, "psxrecomp: renderer = vulkan requested but unavailable "
                        "— falling back to software\n");
    }
    g_b = &SW_BACKEND;
    g_effective = GR_BACKEND_SOFTWARE;
}

GrBackend gr_backend(void) { return g_effective; }

/* ---- Dispatch wrappers (one line each; forward to the active backend) ---- */
void gr_init(uint16_t *vram)                         { g_b->init(vram); }

/* ---- VRAM write watch ----------------------------------------------------
 * A mod that keeps its own pixels in VRAM and must notice what the game
 * writes over them would otherwise read the area back every frame; on the
 * OpenGL backend each readback after drawing syncs the whole VRAM down
 * (glReadPixels) and flushes the batches. Watched rectangles are flagged by
 * every canonical VRAM write that can reach them: uploads, fills, copies,
 * single pixels, and primitives while the draw area overlaps them. */
#define GR_WATCH_MAX 16
static struct { int x0, y0, x1, y1, used; } s_watch[GR_WATCH_MAX];
static volatile uint32_t s_watch_hit;       /* bit per watch */
static uint32_t s_watch_draw_mask;          /* watches overlapping the draw area */
static int s_draw_x0, s_draw_y0, s_draw_x1 = 1023, s_draw_y1 = 511;
static uint32_t watch_mask(int x0, int y0, int x1, int y1) {
    uint32_t m = 0;
    for (int i = 0; i < GR_WATCH_MAX; i++)
        if (s_watch[i].used && x0 <= s_watch[i].x1 && s_watch[i].x0 <= x1 &&
            y0 <= s_watch[i].y1 && s_watch[i].y0 <= y1)
            m |= 1u << i;
    return m;
}
static void watch_rect(int x, int y, int w, int h) {
    if (w <= 0 || h <= 0) return;
    if (x + w > 1024 || y + h > 512) { s_watch_hit |= watch_mask(0, 0, 1023, 511); return; }
    s_watch_hit |= watch_mask(x, y, x + w - 1, y + h - 1);
}
/* A primitive can only write its bounding box clipped to the draw area. */
static void watch_prim(int x0, int y0, int x1, int y1) {
    if (x0 < s_draw_x0) x0 = s_draw_x0;
    if (y0 < s_draw_y0) y0 = s_draw_y0;
    if (x1 > s_draw_x1) x1 = s_draw_x1;
    if (y1 > s_draw_y1) y1 = s_draw_y1;
    if (x0 > x1 || y0 > y1) return;
    s_watch_hit |= watch_mask(x0, y0, x1, y1) & s_watch_draw_mask;
}
#define MIN3(a, b, c) ((a) < (b) ? ((a) < (c) ? (a) : (c)) : ((b) < (c) ? (b) : (c)))
#define MAX3(a, b, c) ((a) > (b) ? ((a) > (c) ? (a) : (c)) : ((b) > (c) ? (b) : (c)))
#define WATCH_TRI(ax, ay, bx, by, cx, cy) do { if (s_watch_draw_mask) \
    watch_prim(MIN3(ax, bx, cx), MIN3(ay, by, cy), MAX3(ax, bx, cx) + 1, MAX3(ay, by, cy) + 1); } while (0)
#define WATCH_BOX(x, y, w, h) do { if (s_watch_draw_mask) \
    watch_prim(x, y, (x) + (w) - 1, (y) + (h) - 1); } while (0)
int gr_vram_watch(int x, int y, int w, int h) {
    for (int i = 0; i < GR_WATCH_MAX; i++) {
        if (s_watch[i].used) continue;
        s_watch[i].x0 = x; s_watch[i].y0 = y;
        s_watch[i].x1 = x + w - 1; s_watch[i].y1 = y + h - 1;
        s_watch[i].used = 1;
        s_watch_hit |= 1u << i;             /* unknown until first checked */
        s_watch_draw_mask = watch_mask(s_draw_x0, s_draw_y0, s_draw_x1, s_draw_y1);
        return i;
    }
    return -1;
}
int gr_vram_watch_take(int id) {
    if (id < 0 || id >= GR_WATCH_MAX) return 1;
    uint32_t bit = 1u << id;
    int hit = (s_watch_hit & bit) != 0;
    s_watch_hit &= ~bit;
    return hit;
}
void gr_set_scale(int scale)                         { g_b->set_scale(scale); }
int  gr_scale(void)                                  { return g_b->scale(); }
void gr_set_texture_filter(int bilinear)             { g_b->set_texture_filter(bilinear); }
int  gr_texture_filter(void)                         { return g_b->texture_filter(); }
void gr_set_semi_transparency(int e, int m)          { g_b->set_semi_transparency(e, m); }
void gr_set_mask_bits(int s, int c)                  { g_b->set_mask_bits(s, c); }
void gr_set_texture_window(uint32_t raw)             { g_b->set_texture_window(raw); }
void gr_set_color_modulation(int r, int g, int b, int raw) { g_b->set_color_modulation(r, g, b, raw); }
void gr_set_precise_triangle(int enabled, int32_t x0, int32_t y0, int32_t x1, int32_t y1,
                             int32_t x2, int32_t y2) {
    if (g_b->set_precise_triangle)
        g_b->set_precise_triangle(enabled, x0, y0, x1, y1, x2, y2);
}
void gr_set_perspective_triangle(int enabled, float q0, float q1, float q2) {
    if (g_b->set_perspective_triangle)
        g_b->set_perspective_triangle(enabled, q0, q1, q2);
}
void gr_fill_rect(int x, int y, int w, int h, uint16_t c)  { watch_rect(x, y, w, h); g_b->fill_rect(x, y, w, h, c); }
void gr_copy_rect(int sx, int sy, int dx, int dy, int w, int h) { watch_rect(dx, dy, w, h); g_b->copy_rect(sx, sy, dx, dy, w, h); }
void gr_draw_flat_triangle(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t c) {
    WATCH_TRI(x0, y0, x1, y1, x2, y2); g_b->draw_flat_triangle(x0, y0, x1, y1, x2, y2, c);
}
void gr_draw_gouraud_triangle(int x0, int y0, uint16_t c0, int x1, int y1, uint16_t c1,
                              int x2, int y2, uint16_t c2) {
    WATCH_TRI(x0, y0, x1, y1, x2, y2); g_b->draw_gouraud_triangle(x0, y0, c0, x1, y1, c1, x2, y2, c2);
}
void gr_draw_textured_triangle(int x0, int y0, int u0, int v0, int x1, int y1, int u1, int v1,
                               int x2, int y2, int u2, int v2,
                               uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    WATCH_TRI(x0, y0, x1, y1, x2, y2); g_b->draw_textured_triangle(x0, y0, u0, v0, x1, y1, u1, v1, x2, y2, u2, v2,
                                clut_x, clut_y, texpage);
}
void gr_draw_shaded_textured_triangle(int x0, int y0, int u0, int v0, uint32_t c0,
                                      int x1, int y1, int u1, int v1, uint32_t c1,
                                      int x2, int y2, int u2, int v2, uint32_t c2,
                                      uint16_t clut_x, uint16_t clut_y,
                                      uint16_t texpage, int raw) {
    WATCH_TRI(x0, y0, x1, y1, x2, y2); g_b->draw_shaded_textured_triangle(x0, y0, u0, v0, c0, x1, y1, u1, v1, c1,
                                       x2, y2, u2, v2, c2, clut_x, clut_y, texpage, raw);
}
void gr_draw_flat_rect(int x, int y, int w, int h, uint16_t c) { WATCH_BOX(x, y, w, h); g_b->draw_flat_rect(x, y, w, h, c); }
void gr_draw_textured_rect(int x, int y, int w, int h, int u, int v,
                           uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    WATCH_BOX(x, y, w, h); g_b->draw_textured_rect(x, y, w, h, u, v, clut_x, clut_y, texpage);
}
void gr_draw_textured_rect_scaled(int x, int y, int w, int h, int u0, int v0, int u1, int v1,
                                  uint16_t clut_x, uint16_t clut_y, uint16_t texpage) {
    WATCH_BOX(x, y, w, h); g_b->draw_textured_rect_scaled(x, y, w, h, u0, v0, u1, v1, clut_x, clut_y, texpage);
}
void gr_draw_line(int x0, int y0, int x1, int y1, uint16_t c) { WATCH_TRI(x0, y0, x1, y1, x1, y1); g_b->draw_line(x0, y0, x1, y1, c); }
void gr_draw_shaded_line(int x0, int y0, uint16_t c0, int x1, int y1, uint16_t c1) {
    WATCH_TRI(x0, y0, x1, y1, x1, y1); g_b->draw_shaded_line(x0, y0, c0, x1, y1, c1);
}
int gr_render_display(uint32_t *o, int p, int dx, int dy, int dw, int dh) {
    return g_b->render_display(o, p, dx, dy, dw, dh);
}
int gr_render_display_hires(uint32_t *o, int p, int dx, int dy, int dw, int dh) {
    return g_b->render_display_hires(o, p, dx, dy, dw, dh);
}
void gr_vram_write(int x, int y, uint16_t pixel)     { watch_rect(x, y, 1, 1); g_b->vram_write(x, y, pixel); }
uint16_t gr_vram_read(int x, int y)                  { return g_b->vram_read(x, y); }
void gr_vram_transfer_in(int x, int y, int w, int h, const uint16_t *d)  { watch_rect(x, y, w, h); g_b->vram_transfer_in(x, y, w, h, d); }
void gr_vram_transfer_out(int x, int y, int w, int h, uint16_t *d)       { g_b->vram_transfer_out(x, y, w, h, d); }
void gr_set_draw_area(int x1, int y1, int x2, int y2){
    s_draw_x0 = x1; s_draw_y0 = y1; s_draw_x1 = x2; s_draw_y1 = y2;
    s_watch_draw_mask = watch_mask(x1, y1, x2, y2);
    g_b->set_draw_area(x1, y1, x2, y2);
}
void gr_get_draw_area(int *x1, int *y1, int *x2, int *y2) { g_b->get_draw_area(x1, y1, x2, y2); }
void gr_set_draw_offset(int x, int y)                { g_b->set_draw_offset(x, y); }

/* Native-wide compositor — present only on backends that supply it. */
int  gr_wide_supported(void) { return g_b->render_wide_display != 0; }
void gr_wide_configure(int wide_w, int offset) {
    if (g_b->wide_configure) g_b->wide_configure(wide_w, offset);
}
void gr_wide_set_target(int base_x) {
    if (g_b->wide_set_target) g_b->wide_set_target(base_x);
}
void gr_wide_disable_target(void) {
    if (g_b->wide_disable_target) g_b->wide_disable_target();
}
void gr_wide_set_primitive_x_delta(int delta) {
    if (g_b->wide_set_primitive_x_delta)
        g_b->wide_set_primitive_x_delta(delta);
}
void gr_wide_set_primitive_suppressed(int suppressed) {
    if (g_b->wide_set_primitive_suppressed)
        g_b->wide_set_primitive_suppressed(suppressed);
}
void gr_wide_set_primitive_unclipped(int unclipped) {
    if (g_b->wide_set_primitive_unclipped)
        g_b->wide_set_primitive_unclipped(unclipped);
}
void gr_wide_set_primitive_expanded(int expanded) {
    if (g_b->wide_set_primitive_expanded)
        g_b->wide_set_primitive_expanded(expanded);
}
void gr_wide_set_primitive_split(int lo, int hi) {
    if (g_b->wide_set_primitive_split)
        g_b->wide_set_primitive_split(lo, hi);
    else if (lo < hi)
        gr_wide_set_primitive_expanded(1);
}
void gr_wide_clear(int base_x, int y, int h, uint16_t color) {
    if (g_b->wide_clear) g_b->wide_clear(base_x, y, h, color);
}



void gr_wide_clear_margins(int base_x, int y, int h, uint16_t color, int sides) {
    if (g_b->wide_clear_margins)
        g_b->wide_clear_margins(base_x, y, h, color, sides);
}
void gr_wide_set_mirror_authoritative(int authoritative) {
    if (g_b->wide_set_mirror_authoritative)
        g_b->wide_set_mirror_authoritative(authoritative);
}
void gr_wide_set_sidecar_complete(int complete) {
    if (g_b->wide_set_sidecar_complete)
        g_b->wide_set_sidecar_complete(complete);
}
int gr_render_wide_display(uint32_t *out, int pitch, int base_x,
                           int disp_y, int disp_h) {
    if (g_b->render_wide_display)
        return g_b->render_wide_display(out, pitch, base_x, disp_y, disp_h);
    return 0;
}
int gr_wide_dump_full(uint32_t *out, int cap_pixels, int *ow, int *oh, int base_x) {
    if (g_b->wide_dump_full)
        return g_b->wide_dump_full(out, cap_pixels, ow, oh, base_x);
    return 0;
}
