// launcher_settings.c — the Display and Audio settings as a table (see
// launcher_settings.h). Availability and order follow the ImGui panels
// (draw_display_controls / draw_audio_controls); rows a phone cannot use
// (window size, fullscreen, renderer, folder pickers, audio device) are not
// listed, as the table's first user is the Android launcher.

#include "launcher_settings.h"
#include "launcher_system_types.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ---- availability --------------------------------------------------------------
static int av_integer_scale(const LauncherModel* m) { return m->has_integer_scale; }
static int av_supersampling(const LauncherModel* m) { return m->has_supersampling; }
static int av_display_layout(const LauncherModel* m) { return m->num_display_layouts > 0; }
static int av_view_mode(const LauncherModel* m) {
    return m->aspect_mask || m->num_aspect_labels > 0 ||
           m->widescreen_supported || m->adaptive_view_supported;
}
static int av_scaling_filter(const LauncherModel* m) { return m->has_sharp_filter; }
static int av_texture_filter(const LauncherModel* m) {
    return !m->has_sharp_filter && m->has_texture_filter;
}
static int av_linear_filter(const LauncherModel* m) {
    return !m->has_sharp_filter && !m->has_texture_filter;
}
static int av_antialiasing(const LauncherModel* m) { return m->has_antialiasing; }
static int av_affine(const LauncherModel* m) { return m->has_affine_filter; }
static int av_perspective(const LauncherModel* m) { return m->has_geometry_precision; }
static int av_screen_kind(const LauncherModel* m) { return m->has_screen_kind; }
static int av_frame_interp(const LauncherModel* m) {
    return m->has_frame_interp && m->s.renderer;
}
static int av_interp_fps(const LauncherModel* m) {
    return av_frame_interp(m) && m->s.frame_interp;
}
static int av_skip_fmv(const LauncherModel* m) { return m->has_skip_fmv; }
static int av_freq(const LauncherModel* m) {
    const SystemProfile* p = (const SystemProfile*)m->profile;
    return !p || !p->hide_audio_freq;
}
static int av_always(const LauncherModel* m) { (void)m; return 1; }
static int av_spu_hq(const LauncherModel* m) { return m->has_spu_hq; }
static int av_language(const LauncherModel* m) { return m->num_languages > 0; }

// ---- toggles -----------------------------------------------------------------
static int on_integer_scale(const LauncherModel* m) { return m->s.integer_scale != 0; }
static int on_linear_filter(const LauncherModel* m) { return m->s.linear_filter != 0; }
static int on_affine(const LauncherModel* m) { return m->s.affine_filter != 0; }
static int on_perspective(const LauncherModel* m) { return m->s.perspective_texturing != 0; }
static int on_frame_interp(const LauncherModel* m) { return m->s.frame_interp != 0; }
static int on_skip_fmv(const LauncherModel* m) { return m->s.auto_skip_fmv != 0; }
static int on_spu_hq(const LauncherModel* m) { return m->s.spu_hq != 0; }

// ---- labels ------------------------------------------------------------------
static const char* view_mode_name(const LauncherModel* m) {
    return m->aspect_setting_label ? m->aspect_setting_label : "View mode";
}
static int view_mode_experimental(const LauncherModel* m) {
    return !m->aspect_labels || m->aspect_experimental;
}
static const char* volume_label(const LauncherModel* m) {
    static char buf[16];
    snprintf(buf, sizeof(buf), "%d%%", m->s.volume);
    return buf;
}

// The table. Display first, then Audio, each in the ImGui panel's order.
static const LauncherSetting kSettings[] = {
    { "integer_scale", "display", "Integer scaling", NULL, LSET_TOGGLE, 0,
      av_integer_scale, NULL, on_integer_scale, launcher_model_toggle_integer_scale,
      NULL, NULL, NULL, NULL },
    { "supersampling", "display", "Supersampling",
      "Renders the game at a higher internal resolution.", LSET_CHOICE, 0,
      av_supersampling, NULL, NULL, NULL,
      launcher_model_supersampling_label, launcher_model_cycle_supersampling, NULL, NULL },
    { "display_layout", "display", "Screen layout", NULL, LSET_CHOICE, 0,
      av_display_layout, NULL, NULL, NULL,
      launcher_model_display_layout_label, launcher_model_cycle_display_layout, NULL, NULL },
    { "view_mode", "display", "View mode", NULL, LSET_CHOICE, 0,
      av_view_mode, view_mode_name, NULL, NULL,
      launcher_model_view_mode_label, launcher_model_cycle_view_mode, NULL,
      view_mode_experimental },
    { "scaling_filter", "display", "Scaling filter", NULL, LSET_CHOICE, 0,
      av_scaling_filter, NULL, NULL, NULL,
      launcher_model_scaling_filter_label, launcher_model_cycle_scaling_filter, NULL, NULL },
    { "texture_filter", "display", "Texture filtering", NULL, LSET_CHOICE, 0,
      av_texture_filter, NULL, NULL, NULL,
      launcher_model_texture_filter_label, launcher_model_toggle_texture_filter, NULL, NULL },
    { "linear_filter", "display", "Linear filtering", NULL, LSET_TOGGLE, 0,
      av_linear_filter, NULL, on_linear_filter, launcher_model_toggle_filter,
      NULL, NULL, NULL, NULL },
    { "antialiasing", "display", "Antialiasing", NULL, LSET_CHOICE, 0,
      av_antialiasing, NULL, NULL, NULL,
      launcher_model_aa_label, launcher_model_cycle_aa, NULL, NULL },
    { "affine_filter", "display", "Affine background smoothing", NULL, LSET_TOGGLE, 0,
      av_affine, NULL, on_affine, launcher_model_toggle_affine_filter,
      NULL, NULL, NULL, NULL },
    { "perspective_textures", "display", "Perspective textures",
      "Stops large floors and walls from warping as the camera moves.", LSET_TOGGLE, 0,
      av_perspective, NULL, on_perspective, launcher_model_toggle_perspective_texturing,
      NULL, NULL, NULL, NULL },
    { "screen_model", "display", "Screen model", NULL, LSET_CHOICE, 0,
      av_screen_kind, NULL, NULL, NULL,
      launcher_model_screen_kind_label, launcher_model_cycle_screen_kind, NULL, NULL },
    { "frame_interp", "display", "Frame interpolation", NULL, LSET_TOGGLE, 0,
      av_frame_interp, NULL, on_frame_interp, launcher_model_toggle_frame_interp,
      NULL, NULL, NULL, NULL },
    { "interp_fps", "display", "Presentation target", NULL, LSET_CHOICE, 0,
      av_interp_fps, NULL, NULL, NULL,
      launcher_model_interp_fps_label, launcher_model_cycle_interp_fps, NULL, NULL },
    { "skip_fmv", "display", "Skip FMVs", NULL, LSET_TOGGLE, 0,
      av_skip_fmv, NULL, on_skip_fmv, launcher_model_toggle_skip_fmv,
      NULL, NULL, NULL, NULL },

    { "sample_rate", "audio", "Sample rate", NULL, LSET_CHOICE, 0,
      av_freq, NULL, NULL, NULL,
      launcher_model_freq_label, launcher_model_cycle_freq, NULL, NULL },
    { "volume", "audio", "Volume", NULL, LSET_STEPPER, 5,
      av_always, NULL, NULL, NULL,
      volume_label, NULL, launcher_model_volume_delta, NULL },
    { "spu_hq", "audio", "High-quality SPU", NULL, LSET_TOGGLE, 0,
      av_spu_hq, NULL, on_spu_hq, launcher_model_toggle_spu_hq,
      NULL, NULL, NULL, NULL },
    { "language", "audio", "Language", NULL, LSET_CHOICE, 0,
      av_language, NULL, NULL, NULL,
      launcher_model_language_label, launcher_model_cycle_language, NULL, NULL },
};

int launcher_settings_count(void) {
    return (int)(sizeof(kSettings) / sizeof(kSettings[0]));
}

const LauncherSetting* launcher_setting_at(int index) {
    if (index < 0 || index >= launcher_settings_count()) return NULL;
    return &kSettings[index];
}

const LauncherSetting* launcher_setting_find(const char* id) {
    if (!id) return NULL;
    for (int i = 0; i < launcher_settings_count(); ++i)
        if (strcmp(kSettings[i].id, id) == 0) return &kSettings[i];
    return NULL;
}

int launcher_setting_available(const LauncherSetting* s, const LauncherModel* m) {
    return s && m && (!s->available || s->available(m));
}

const char* launcher_setting_label(const LauncherSetting* s, const LauncherModel* m) {
    if (s->dynamic_label) return s->dynamic_label(m);
    return s->label;
}

int launcher_setting_choices(LauncherModel* m, const LauncherSetting* s,
                             char labels[][96], int max) {
    if (!m || !s || s->kind != LSET_CHOICE || !s->next || !s->value || max <= 0)
        return 0;
    // Cycle a saved copy of the model and put it back: the model only knows
    // "next", and a front end wants the whole list.
    LauncherModel* saved = (LauncherModel*)malloc(sizeof(*m));
    if (!saved) return 0;
    memcpy(saved, m, sizeof(*m));
    int count = 0;
    snprintf(labels[count++], 96, "%s", s->value(m));
    while (count < max) {
        s->next(m);
        const char* label = s->value(m);
        if (strcmp(label, labels[0]) == 0) break;
        int seen = 0;
        for (int i = 0; i < count && !seen; ++i) seen = strcmp(labels[i], label) == 0;
        if (seen) break;
        snprintf(labels[count++], 96, "%s", label);
    }
    memcpy(m, saved, sizeof(*m));
    free(saved);
    return count;
}

void launcher_setting_choose(LauncherModel* m, const LauncherSetting* s, int index) {
    if (!m || !s || s->kind != LSET_CHOICE || !s->next) return;
    for (int i = 0; i < index; ++i) s->next(m);
}
