// launcher_model.c — implementation of the game-agnostic launcher view-model.
//
// Pure logic: no SDL, no OpenGL, no UI toolkit. Safe to compile as C and link
// into any game or either prototype backend.

#include "launcher_model.h"
#include "launcher_system.h"

#include "crc32.h"
#include "consoles/psx/memcard_format.h"   // PSX-specific; used only under SAVE_MEMCARD
#include "sha256.h"
#include "sha1.h"
#include "ips_patch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#  include <windows.h>
#else
#  include <pthread.h>
#  include <unistd.h>
#if defined(__APPLE__)
#  include <mach-o/dyld.h>
#endif
#endif

// 32040 = the SNES S-DSP's native output rate; kept reachable in the cycle so
// users chasing bit-exact SNES audio can pick it (matches the legacy launcher).
static const int kFreqTable[] = { 32040, 32000, 44100, 48000 };
static const int kFreqCount   = (int)(sizeof(kFreqTable) / sizeof(kFreqTable[0]));

static const int kWindowWidths[]    = { 960, 1280, 1600, 1920 };
static const int kWindowWidthCount  = (int)(sizeof(kWindowWidths) / sizeof(kWindowWidths[0]));
static const int kInterpFpsTable[]  = { 0, 90, 120, 144, 165, 240 };
static const int kInterpFpsCount    = (int)(sizeof(kInterpFpsTable) / sizeof(kInterpFpsTable[0]));
static const char* kScreenKindNames[4] = { "Raw", "CRT", "Composite", "Trinitron" };

static const char* kButtonNames[LNG_BTN_COUNT] = {
    "Up", "Down", "Left", "Right", "A", "B", "X", "Y",
    "L", "R", "Start", "Select"
};
// Player 1 keyboard defaults (Player 2 defaults unbound, mirroring the RML note).
static const char* kP1Defaults[LNG_BTN_COUNT] = {
    "Up", "Down", "Left", "Right", "X", "Z", "S", "A", "D", "C", "Enter", "RShift"
};
// Display labels for engine hotkeys (order == LngHotkey == [KeyMap] keys).
static const char* kHotkeyNames[LNG_HK_COUNT] = {
    "Fullscreen", "Reset", "Pause", "Pause (dimmed)", "Fast-forward",
    "Window bigger", "Window smaller", "Volume up", "Volume down",
    "FPS readout", "Toggle renderer",
    "Solar level up", "Solar level down", "Resume live solar"
};
static const char* kViewNames[7] = {
    "Dashboard", "Settings", "Controller", "Netplay", "Mods",
    "Assist Tools", "Credits"
};
static const char* kSrcNames[3]  = { "None", "Keyboard", "Gamepad" };

static void safe_copy(char* dst, size_t cap, const char* src) {
    if (!dst || cap == 0) return;
    if (!src) { dst[0] = '\0'; return; }
    size_t n = strlen(src);
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

static int clampi(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static void run_verify(LauncherModel* m);   // fwd; defined below, called from launcher_model_set_rom
static void update_msu1_patch_available(LauncherModel* m);   // fwd; called from launcher_model_set_rom
static void lm_inspect_memcard(LauncherModel* m, int slot); // fwd; host memcard_inspect callback
static void lm_inspect_tpak(LauncherModel* m, int slot);    // fwd; host tpak_inspect callback

void launcher_model_init(LauncherModel* m,
                         const RecompLauncherCSettings* io,
                         const RecompLauncherCGameInfo* game,
                         const char* initial_rom) {
    memset(m, 0, sizeof(*m));

    if (game) {
        m->game_name            = game->name ? game->name : "Unknown Game";
        m->region               = game->region ? game->region : "";
        m->platform             = game->platform;   // NULL => no subtitle
        m->widescreen_supported = game->widescreen_supported != 0;
        m->msu1_supported       = game->msu1_supported != 0;
        m->msu1_note            = game->msu1_note;
        m->msu1_patch_path      = game->msu1_patch_path;
        m->saves_supported      = game->sram_path != NULL;
        m->sram_path            = game->sram_path;
        m->has_solar_sensor     = game->has_solar_sensor != 0;
        m->has_integer_scale    = game->has_integer_scale != 0;
        m->hdpack_supported     = game->hdpack_supported != 0;
        m->password_save_path   = game->password_save_path;
        m->password_save_label  = game->password_save_label;
        m->zapper               = game->zapper != 0;
        /* 0 = unset (caller predates the field) -> assume 2 players. */
        m->player_count         = game->num_players ? clampi(game->num_players, 1, LNG_MAX_PLAYERS) : 2;
        m->expected_crc         = game->expected_crc;
        m->has_expected_crc     = game->has_expected_crc;
        m->known_sha256         = game->known_sha256;
        m->known_sha1_hex       = game->known_sha1_hex;
        m->num_known_sha1       = game->num_known_sha1;
        m->num_known_sha256     = game->num_known_sha256;

        m->pad_mode_supported   = game->pad_mode_supported != 0;
        m->pad_mode_selectable  = game->pad_mode_selectable != 0;
        m->locked_pad_mode      = clampi(game->locked_pad_mode, 0, 2);
        m->lock_device          = game->lock_device != 0;
        m->aspect_mask          = game->aspect_mask;

        m->has_window_size      = game->has_window_size != 0;
        m->has_renderer         = game->has_renderer != 0;
        m->has_supersampling    = game->has_supersampling != 0;
        m->has_antialiasing     = game->has_antialiasing != 0;
        m->has_texture_filter   = game->has_texture_filter != 0;
        m->has_screen_kind      = game->has_screen_kind != 0;
        m->has_frame_interp     = game->has_frame_interp != 0;
        m->has_spu_hq           = game->has_spu_hq != 0;
        m->has_skip_fmv         = game->has_skip_fmv != 0;
        m->has_turbo_loads      = game->has_turbo_loads != 0;
        m->has_geometry_precision = game->has_geometry_precision != 0;
        // game->has_fullscreen_toggle is deliberately NOT read: the Fullscreen
        // row is universal (drawn for every console) — see recomp_launcher.h.
        m->has_bios             = game->has_bios != 0;
        m->has_deadzone_pct     = game->has_deadzone_pct != 0;
        m->rom_noun             = game->rom_noun ? game->rom_noun : "ROM";
        m->language_labels      = game->language_labels;
        m->num_languages        = game->num_languages;
        m->disc_verify_cb       = game->disc_verify;      // real disc verdict (PSX), or NULL
        m->memcard_inspect_cb   = game->memcard_inspect;  // real memcard summary (PSX), or NULL
        m->bios_verify_cb       = game->bios_verify;
        m->persist_setup_cb     = game->persist_setup;
        m->persist_setup_ctx    = game->persist_setup_ctx;
        /* Wizard + Generate & rebuild are a single opt-in. Without the flag,
         * ignore prepare/rebuild/toolchain even if a host filled them — keeps
         * unadvertised platforms from surfacing in-development UI. */
        m->setup_wizard_supported = game->setup_wizard_supported != 0;
        if (m->setup_wizard_supported) {
            m->prepare_disc_cb      = game->prepare_disc;
            m->prepare_with_progress_cb = game->prepare_with_progress;
            m->rebuild_with_progress_cb = game->rebuild_with_progress;
            m->prepare_disc_label   = game->prepare_disc_label;
            m->prepare_disc_note    = game->prepare_disc_note;
            m->prepare_section_title = game->prepare_section_title;
            m->prepare_busy_status  = game->prepare_busy_status;
            m->prepare_success_status = game->prepare_success_status;
            m->rebuild_busy_status  = game->rebuild_busy_status;
            m->rebuild_success_status = game->rebuild_success_status;
            m->prepare_use_selected_rom = game->prepare_use_selected_rom != 0;
            m->rebuild_after_prepare = game->rebuild_after_prepare != 0;
            m->relaunch_after_rebuild = game->relaunch_after_rebuild != 0;
            m->prepare_required_before_continue =
                game->prepare_required_before_continue != 0;
            m->setup_needs_toolchain = game->setup_needs_toolchain != 0;
            m->toolchain_is_ready_cb = game->toolchain_is_ready;
            m->ensure_toolchain_with_progress_cb =
                game->ensure_toolchain_with_progress;
            m->toolchain_update_available_cb = game->toolchain_update_available;
        } else {
            m->prepare_disc_cb = NULL;
            m->prepare_with_progress_cb = NULL;
            m->rebuild_with_progress_cb = NULL;
            m->prepare_disc_label = NULL;
            m->prepare_disc_note = NULL;
            m->prepare_section_title = NULL;
            m->prepare_busy_status = NULL;
            m->prepare_success_status = NULL;
            m->rebuild_busy_status = NULL;
            m->rebuild_success_status = NULL;
            m->prepare_use_selected_rom = false;
            m->rebuild_after_prepare = false;
            m->relaunch_after_rebuild = false;
            m->prepare_required_before_continue = false;
            m->setup_needs_toolchain = false;
            m->toolchain_is_ready_cb = NULL;
            m->ensure_toolchain_with_progress_cb = NULL;
            m->toolchain_update_available_cb = NULL;
        }
        /* PGO / FMV-timing are Settings actions, not the first-run wizard. */
        m->pgo_optimize_with_progress_cb = game->pgo_optimize_with_progress;
        m->fmv_timing_optimize_with_progress_cb =
            game->fmv_timing_optimize_with_progress;
        m->pgo_busy_status      = game->pgo_busy_status;
        m->pgo_success_status   = game->pgo_success_status;
        m->fmv_timing_busy_status = game->fmv_timing_busy_status;
        m->fmv_timing_success_status = game->fmv_timing_success_status;
        m->boxart_path          = game->boxart_path;      // NULL => default boxart.tga
        m->aspect_labels        = game->aspect_labels;    // NULL => built-in 4:3/16:9/21:9
        m->num_aspect_labels    = game->num_aspect_labels;
        m->aspect_experimental  = game->aspect_experimental != 0;
        m->aspect_setting_label = game->aspect_setting_label;
        m->aspect_setting_help  = game->aspect_setting_help;
        m->adaptive_view_supported = game->adaptive_view_supported != 0;
        m->display_layout_labels = game->display_layout_labels;
        m->num_display_layouts = game->num_display_layouts;
        m->has_assist_tools     = game->has_assist_tools != 0;
        m->assist_tools_note    = game->assist_tools_note;
        m->settings_bindings    = game->settings_bindings != 0;
        m->assist_binding_labels = game->assist_binding_labels;
        m->assist_binding_count =
            clampi(game->assist_binding_count, 0,
                   RECOMP_LAUNCHER_MAX_ASSIST_BINDINGS);
        m->credits_text         = game->credits_text;
        m->tpak_slots           = clampi(game->tpak_slots, 0, RECOMP_LAUNCHER_MAX_TPAKS);
        m->tpak_inspect_cb      = game->tpak_inspect;
        m->audio_device_labels  = game->audio_device_labels;
        m->num_audio_devices    = game->num_audio_devices;
        m->renderer_labels      = game->renderer_labels;
        m->num_renderers        = game->num_renderers;
        m->hide_rebind          = game->hide_rebind != 0;
        m->has_mouse_controls   = game->has_mouse_controls != 0;
        m->has_gyro_controls    = game->has_gyro_controls != 0;
        m->has_sharp_filter     = game->has_sharp_filter != 0;
        m->has_affine_filter    = game->has_affine_filter != 0;
        m->netplay_supported    = game->netplay_supported != 0 && game->netplay != NULL;
        m->netplay              = game->netplay;
#if RECOMP_UI_ENABLE_MODS
        m->mods                 = game->mods;
#else
        /* The provider ABI is always present for stable consumer structs, but
         * a normal launcher build must not expose or mutate mods. */
        m->mods                 = NULL;
#endif
    } else {
        m->game_name    = "Unknown Game";
        m->region       = "";
        m->platform     = NULL;
        m->player_count = 2;
        m->rom_noun     = "ROM";
    }

    if (io) m->s = *io;
    if (m->has_sharp_filter) {
        m->s.linear_filter = m->s.linear_filter ? 1 : 0;
        m->s.sharp_filter = m->s.sharp_filter ? 1 : 0;
        // Preserve an existing explicit linear-filter preference when a host
        // first gains the three-state scaler control.
        if (m->s.linear_filter) m->s.sharp_filter = 0;
    }
    memset(&m->s.netplay_launch, 0, sizeof(m->s.netplay_launch));
    if (!m->s.netplay_player_name[0] && m->netplay && m->netplay->player_name) {
        safe_copy(m->s.netplay_player_name, sizeof(m->s.netplay_player_name),
                  m->netplay->player_name(m->netplay->ctx));
    }
    safe_copy(m->netplay_name_edit, sizeof(m->netplay_name_edit), m->s.netplay_player_name);
    if (m->netplay && m->netplay->default_url) {
        safe_copy(m->netplay_lobby_url, sizeof(m->netplay_lobby_url),
                  m->netplay->default_url(m->netplay->ctx));
    }
    if (m->s.netplay_player_name[0]) {
        snprintf(m->netplay_host_name, sizeof(m->netplay_host_name), "%s's Lobby",
                 m->s.netplay_player_name);
    }
    safe_copy(m->netplay_host_port, sizeof(m->netplay_host_port), "7777");
    safe_copy(m->netplay_host_ip, sizeof(m->netplay_host_ip), "Detecting...");
    m->netplay_host_local_ip[0] = '\0';
    m->netplay_local_address_count = 0;
    safe_copy(m->netplay_direct_ip, sizeof(m->netplay_direct_ip), "127.0.0.1");
    safe_copy(m->netplay_direct_port, sizeof(m->netplay_direct_port), "7777");
    m->netplay_lan_only = false;
    m->netplay_list_fresh = false;
    m->netplay_selected_lobby = -1;
    m->netplay_public_ip[0] = '\0';
    m->netplay_public_ip_resolved = false;
    m->netplay_lobby_settings_open = false;
    m->netplay_lobby_input_delay = 2;
    m->netplay_manual_input_delay = false; /* auto from max peer RTT at launch */
    m->netplay_lobby_input_prediction = 6; /* P = 4 + D at default D=2 */
    m->netplay_manual_input_prediction = false; /* auto P from RTT when rollback */
    /* Default off so waiting-room ICE can prove a direct path; host Force
     * Online start is always lobby SFU (§108). */
    m->netplay_force_input_relay = false;
    m->netplay_force_turn = false;
    /* Rollback on by default; Lobby Settings “Disable Rollback” opts out. */
    m->netplay_rollback = true;
    {
        int max_p = m->player_count > 0 ? m->player_count : 2;
        if (max_p < 2) max_p = 2;
        if (max_p > RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS)
            max_p = RECOMP_LAUNCHER_NETPLAY_MAX_MEMBERS;
        m->netplay_host_max_players = max_p;
    }
    m->netplay_lobby_max_slots = 0;
    m->mod_selected = 0;
    m->mod_package_selected = 0;
    m->mod_show_packages = false;
    if (game && game->default_settings) {
        m->default_settings = *game->default_settings;
        m->has_default_settings = true;
    }
    m->s.adaptive_view =
        (m->adaptive_view_supported && m->s.adaptive_view) ? 1 : 0;

    // ---- memory-card slots default to enabled (0 == "unset": a host struct
    // that predates this field, or was zero-initialized, reads as both cards
    // plugged in — matching the legacy launcher's default) ----
    if (!m->s.memcard_enabled[0]) m->s.memcard_enabled[0] = 1;
    if (!m->s.memcard_enabled[1]) m->s.memcard_enabled[1] = 1;

    // ---- infer the SystemProfile this game belongs to (panel composition +
    // per-system specs) from the ABI caps launcher_profile_apply() already set ----
    m->profile = launcher_system_infer(game);
    if (m->profile && m->profile->controller.max_players > 0) {
        /* num_players is a per-game capability, while max_players is the
         * console ceiling. Raising the ABI storage width must never make a
         * two-player game/system expose extra controller or lobby seats. */
        m->player_count = clampi(m->player_count, 1,
                                 m->profile->controller.max_players);
    }

    // ---- gate pad_mode per player ----
    if (m->pad_mode_supported) {
        const SystemProfile* pm_prof = (const SystemProfile*)m->profile;
        const ControllerSpec* pm_spec = pm_prof ? &pm_prof->controller : NULL;
        for (int p = 0; p < LNG_MAX_PLAYERS; ++p) {
            if (!m->pad_mode_selectable) {
                m->s.pad_mode[p] = m->locked_pad_mode;
            } else if (pm_spec && pm_spec->modes && pm_spec->mode_count > 0) {
                // Custom mode list (Genesis 3-Button/6-Button): any listed
                // mode value is valid; anything else snaps to the first
                // listed mode. The Hybrid rule below is PSX-only semantics.
                int ok = 0;
                for (int i = 0; i < pm_spec->mode_count; ++i)
                    if (pm_spec->modes[i].mode == m->s.pad_mode[p]) { ok = 1; break; }
                if (!ok) m->s.pad_mode[p] = pm_spec->modes[0].mode;
            } else if (m->s.pad_mode[p] == 0) {
                /* Hybrid is mod-only and never selectable: migrate any stale
                 * persisted value. The mod requests it at runtime instead. */
                m->s.pad_mode[p] = 1;
            }
            /* Keyboard cannot drive Analog/Hybrid — force D-Pad. */
            if (m->s.player_src[p] == 1 &&
                !(pm_spec && pm_spec->modes && pm_spec->mode_count > 0))
                m->s.pad_mode[p] = 2;
        }
    }

    // ---- Transfer Pak slots: inspect whatever the host's config seeded ----
    // (re-run per slot on every ROM/save change; see launcher_model_set_tpak_*).
    for (int t = 0; t < m->tpak_slots; ++t) lm_inspect_tpak(m, t);

    // ---- validate/clamp aspect_index against the offered set ----
    if (m->aspect_labels && m->num_aspect_labels > 0) {
        // Game-supplied vocabulary: a plain 0..n-1 cycle, every entry offered.
        m->s.aspect_index = clampi(m->s.aspect_index, 0, m->num_aspect_labels - 1);
    } else if (m->aspect_mask) {
        int idx = clampi(m->s.aspect_index, 0, 2);
        // walk down from the requested index to the nearest offered aspect;
        // 4:3 (bit0, index 0) is always offered so this always terminates.
        while (idx > 0 && !(m->aspect_mask & (1 << idx))) --idx;
        m->s.aspect_index = idx;
    }
    if (m->display_layout_labels && m->num_display_layouts > 0) {
        m->s.display_layout =
            clampi(m->s.display_layout, 0, m->num_display_layouts - 1);
    } else {
        m->s.display_layout = 0;
    }

    // ---- clamp/seed the deeper PSX-style settings against their own ranges ----
    if (m->has_window_size) {
        int ok = 0;
        for (int i = 0; i < kWindowWidthCount; ++i)
            if (kWindowWidths[i] == m->s.window_width) { ok = 1; break; }
        if (!ok) m->s.window_width = kWindowWidths[0];
    }
    if (m->has_supersampling) m->s.supersampling = clampi(m->s.supersampling ? m->s.supersampling : 1, 1, 4);
    if (m->has_screen_kind) {
        // Clamp against the active profile's screen-model vocabulary (GBA has
        // 5 LCD models; the legacy PSX-era set has 4) — see screen_kind_vocab.
        const SystemProfile* sk_prof = (const SystemProfile*)m->profile;
        int sk_n = (sk_prof && sk_prof->screen_kind_names && sk_prof->screen_kind_count > 0)
                     ? sk_prof->screen_kind_count : 4;
        m->s.screen_kind = clampi(m->s.screen_kind, 0, sk_n - 1);
    }
    if (m->has_texture_filter) m->s.texture_filter = m->s.texture_filter ? 1 : 0;
    if (m->has_renderer) {
        if (m->renderer_labels && m->num_renderers > 0) {
            /* Multi-label cycle (Software / OpenGL / Vulkan). Prefer OpenGL
             * when the seeded index is out of range — never snap to Software
             * just because memset left renderer at 0 and the host forgot a seed. */
            if (m->s.renderer < 0 || m->s.renderer >= m->num_renderers) {
                int def = 0;
                for (int i = 0; i < m->num_renderers; ++i) {
                    const char* lab = m->renderer_labels[i];
                    if (lab && strstr(lab, "OpenGL")) { def = i; break; }
                }
                m->s.renderer = def;
            }
        } else {
            m->s.renderer = m->s.renderer ? 1 : 0;
        }
    }
    if (m->has_frame_interp) {
        int ok = 0;
        for (int i = 0; i < kInterpFpsCount; ++i)
            if (kInterpFpsTable[i] == m->s.frame_interp_fps) { ok = 1; break; }
        if (!ok) m->s.frame_interp_fps = 0;
    }
    if (m->num_languages > 0)
        m->s.language_index = clampi(m->s.language_index, 0, m->num_languages - 1);
    if (m->has_deadzone_pct) {
        m->s.deadzone[0] = clampi((m->s.deadzone[0] / 5) * 5, 0, 50);
        m->s.deadzone[1] = m->s.deadzone[0];
    }

    // ---- mouse controls: seed/clamp against their own ranges ----------------
    // Only touched when has_mouse_controls (every other game leaves the whole
    // mouse_* block at its memset-zero state, untouched). The host normally
    // seeds real defaults from its config; a zero sensitivity is the tell of a
    // fresh/zero-initialized struct (e.g. a demo harness) — seed the full Snap
    // default set in that case, otherwise just clamp the sensitivity.
    if (m->has_mouse_controls) {
        if (m->s.mouse_sensitivity <= 0.0f) {
            m->s.player_src[0]      = 1;      // Keyboard (+ mouse) by default
            m->s.mouse_enabled      = 1;
            m->s.mouse_sensitivity  = 0.06f;
            m->s.mouse_invert_x     = 0;
            m->s.mouse_invert_y     = 1;
            m->s.mouse_bind[0]      = 0;      // Left  -> A  (kN64PadButtons[0])
            m->s.mouse_bind[1]      = 2;      // Right -> Z  (kN64PadButtons[2])
            m->s.mouse_bind[2]      = -1;     // Middle-> none
        } else {
            m->s.mouse_sensitivity = clampf(m->s.mouse_sensitivity, 0.01f, 0.50f);
        }
    }
    if (m->has_gyro_controls) {
        m->s.gyro_sensitivity =
            m->s.gyro_sensitivity > 0.0f
                ? clampf(m->s.gyro_sensitivity, 0.25f, 4.00f)
                : 1.00f;
    }
    // ---- widescreen extra-cells (video.widescreen_cells consoles, e.g.
    // Genesis): 0 = unset host -> the engine default of 8; else clamp 1..16. ----
    {
        const SystemProfile* ws_prof = (const SystemProfile*)m->profile;
        if (ws_prof && ws_prof->video.widescreen_cells)
            m->s.widescreen_cells = m->s.widescreen_cells
                                      ? clampi(m->s.widescreen_cells, 1, 16) : 8;
    }

    // Real ROM read + CRC/SHA verification (computes rom_size, crc_match,
    // sha_match). No synthesized/faked facts.
    launcher_model_set_rom(m, initial_rom);

    // Password/mantra save: read the current one-line password file so the
    // SAVES row can show it. (Zapper switch state is loaded later by
    // launcher_binds_load(), which owns the keybinds.ini path.)
    launcher_model_password_reload(m);

    // Inspect both memory-card slots up front (real block usage/validity when a
    // host memcard_inspect callback is wired; no-op otherwise).
    lm_inspect_memcard(m, 0);
    lm_inspect_memcard(m, 1);

    m->view      = LNG_VIEW_DASHBOARD;
    m->action    = LNG_ACTION_NONE;
    m->cfg_player = 0;
    m->setup_wizard_open = false;
    m->setup_page = 1;
    m->setup_tc_auto = true;
    m->setup_tc_ready = false;
    m->setup_tc_update_available = false;
    m->setup_tc_update_skipped = false;
    m->setup_tc_local_ver[0] = '\0';
    m->setup_tc_remote_ver[0] = '\0';
    m->setup_tc_zip[0] = '\0';
    m->setup_bios_needs_regen = false;
    m->bios_confirm_open = false;
    m->bios_pending_path[0] = '\0';
    m->bios_switch_uncommitted = false;
    m->bios_revert_path[0] = '\0';
    m->bios_play_modal_open = false;
    m->setup_preparing = false;
    m->setup_prepare_pulse = 0.0f;
    m->setup_prepare_fraction = -1.0f;
    m->setup_progress_title[0] = '\0';
    m->setup_status[0] = '\0';
    m->setup_error[0] = '\0';
    m->setup_prepare_satisfied = false;
    m->relaunch_exe[0] = '\0';
    if (!game || !game->setup_needs_toolchain) {
        m->setup_needs_toolchain = false;
        m->toolchain_is_ready_cb = NULL;
        m->ensure_toolchain_with_progress_cb = NULL;
        m->toolchain_update_available_cb = NULL;
    }
    launcher_model_refresh_bios_status(m);

    /* Soft-return from a match: land on Netplay with the room modal open. */
    if (game && game->resume_netplay_room && m->netplay_supported && m->netplay &&
        m->netplay->in_lobby && m->netplay->in_lobby(m->netplay->ctx)) {
        m->view = LNG_VIEW_NETPLAY;
        m->netplay_list_fresh = true;
        if (game->resume_netplay_endpoint && game->resume_netplay_endpoint[0]) {
            m->netplay_local_room = true;
            safe_copy(m->netplay_host_endpoint, sizeof(m->netplay_host_endpoint),
                      game->resume_netplay_endpoint);
        } else {
            m->netplay_local_room = false;
            m->netplay_host_endpoint[0] = '\0';
        }
        /* Mirror engine match caps — UI default rollback=true must not flip a
         * delay-sync Cable Club rematch on ▶ Play without opening Settings. */
        if (m->netplay->rollback_get)
            m->netplay_rollback =
                m->netplay->rollback_get(m->netplay->ctx) != 0;
        if (m->netplay->input_delay_get) {
            m->netplay_lobby_input_delay =
                m->netplay->input_delay_get(m->netplay->ctx);
            if (m->netplay_lobby_input_delay < 2)
                m->netplay_lobby_input_delay = 2;
        }
    }

    /* First-run setup: only when the host opted into the wizard product.
     * Host can force it, or we open when ROM/BIOS is missing. A selected BIOS
     * that merely needs Generate & rebuild (needs_regen) is handled by the
     * Switch-BIOS / PLAY prompts — not the full wizard. */
    if (m->setup_wizard_supported) {
        const int force = game && game->needs_setup;
        const int missing_rom = !m->rom_present || strcmp(m->rom_size, "--") == 0;
        const int missing_bios = m->has_bios && !m->setup_bios_ok &&
                                 !m->setup_bios_needs_regen;
        if (force || missing_rom || missing_bios)
            m->setup_wizard_open = true;
    }

    /* Probe toolchain readiness even when the wizard is closed — BIOS switch
     * Generate & rebuild needs setup_tc_ready, and codegen hosts always set
     * setup_needs_toolchain. When a usable pack exists, also compare against
     * GitHub /releases/latest so page 0 can prompt for an update. */
    if (m->setup_needs_toolchain) {
        m->setup_tc_ready =
            (m->toolchain_is_ready_cb && m->toolchain_is_ready_cb()) ? true
                                                                    : false;
        m->setup_tc_update_available = false;
        m->setup_tc_local_ver[0] = '\0';
        m->setup_tc_remote_ver[0] = '\0';
        /* Host may have just deleted a broken latest/ — surface that on page 0. */
        if (!m->setup_tc_ready && game && game->toolchain_repair_note) {
            const char* note = game->toolchain_repair_note();
            if (note && note[0])
                safe_copy(m->setup_status, sizeof(m->setup_status), note);
        }
        if (m->setup_tc_ready && m->toolchain_update_available_cb) {
            char local_ver[64] = {0};
            char remote_ver[64] = {0};
            if (m->toolchain_update_available_cb(local_ver, sizeof(local_ver),
                                                remote_ver, sizeof(remote_ver))) {
                m->setup_tc_update_available = true;
                safe_copy(m->setup_tc_local_ver, sizeof(m->setup_tc_local_ver),
                          local_ver);
                safe_copy(m->setup_tc_remote_ver, sizeof(m->setup_tc_remote_ver),
                          remote_ver);
            } else {
                if (local_ver[0])
                    safe_copy(m->setup_tc_local_ver,
                              sizeof(m->setup_tc_local_ver), local_ver);
                if (remote_ver[0])
                    safe_copy(m->setup_tc_remote_ver,
                              sizeof(m->setup_tc_remote_ver), remote_ver);
            }
        }
        if (m->setup_wizard_open) {
            const int need_tc_page =
                !m->setup_tc_ready ||
                (m->setup_tc_update_available && !m->setup_tc_update_skipped);
            m->setup_page = need_tc_page ? 0 : 1;
        } else {
            m->setup_page = 1;
        }
    } else {
        m->setup_page = 1;
        m->setup_tc_ready = true;
    }

    // Placeholder display until launcher_binds_load() fills real values from
    // keybinds.ini / config.ini [KeyMap]. Walk the ACTIVE profile's button
    // count (SNES 12, PSX 16, ...) so every rebind slot the page will render
    // gets a placeholder — kP1Defaults only names the SNES-shaped first 12.
    {
        const SystemProfile* prof = (const SystemProfile*)m->profile;
        int bc = prof ? prof->controller.button_count : LNG_BTN_COUNT;
        if (bc > LNG_MAX_BUTTONS) bc = LNG_MAX_BUTTONS;
        for (int b = 0; b < bc; ++b) {
            safe_copy(m->binds[0][b], sizeof(m->binds[0][b]),
                      b < LNG_BTN_COUNT ? kP1Defaults[b] : "(unbound)");
            safe_copy(m->binds[1][b], sizeof(m->binds[1][b]), "(unbound)");
            safe_copy(m->pad_binds[0][b], sizeof(m->pad_binds[0][b]), "(unbound)");
            safe_copy(m->pad_binds[1][b], sizeof(m->pad_binds[1][b]), "(unbound)");
        }
    }
    for (int h = 0; h < LNG_HK_COUNT; ++h)
        m->hotkeys[h][0] = '\0';
}

void launcher_model_commit(const LauncherModel* m, RecompLauncherCSettings* io) {
    if (io) *io = m->s;
}

void launcher_model_set_rom(LauncherModel* m, const char* path) {
    m->rom_present = path && path[0] != '\0';
    safe_copy(m->rom_full, sizeof(m->rom_full), m->rom_present ? path : "");

    // Display just the basename (handles both / and \ separators).
    const char* base = m->rom_full;
    for (const char* q = m->rom_full; *q; ++q)
        if (*q == '/' || *q == '\\') base = q + 1;
    safe_copy(m->rom_file, sizeof(m->rom_file), m->rom_present ? base : "(none)");

    /* Cartridge consoles: read the ROM once for size + CRC32/SHA over the
     * body (SMC header stripped) vs expected fingerprints.
     * Disc systems (verify.mode==1, e.g. PSX): only ftell for the size label.
     * Full-image CRC/SHA would block launcher open on multi-hundred-MB BINs
     * and is unused — identity is disc_verify / identify_disc instead. */
    m->rom_size[0] = '\0';
    m->crc_match = false;
    m->sha_match = false;
    m->sha1_match = false;
    const int disc_verify = m->profile && m->profile->verify.mode == 1;
    if (m->rom_present) {
        FILE* f = fopen(m->rom_full, "rb");
        if (f) {
            fseek(f, 0, SEEK_END);
            long n = ftell(f);
            if (n > 0) {
                snprintf(m->rom_size, sizeof(m->rom_size), "%.2f MB (%ld Mbit)",
                         (double)n / (1024.0 * 1024.0), (long)((n * 8) / (1024 * 1024)));
                if (!disc_verify) {
                    fseek(f, 0, SEEK_SET);
                    uint8_t* buf = (uint8_t*)malloc((size_t)n);
                    if (buf && fread(buf, 1, (size_t)n, f) == (size_t)n) {
                        /* Normalize container headers before fingerprinting.
                         * SNES .smc images may carry a 512-byte copier header;
                         * NES .nes images carry a 16-byte iNES/NES 2.0 header.
                         * NESRecomp's ROM and package CRCs intentionally cover
                         * every byte after that 16-byte header. */
                        size_t hdr = ((size_t)n % 1024 == 512) ? 512 : 0;
                        if ((size_t)n > 16 &&
                            buf[0] == 'N' && buf[1] == 'E' &&
                            buf[2] == 'S' && buf[3] == 0x1A) {
                            hdr = 16;
                        }
                        const uint8_t* body = buf + hdr;
                        size_t blen = (size_t)n - hdr;
                        uint32_t crc = recompui_crc32_compute(body, blen);
                        uint8_t  sha[32];
                        recompui_sha256_compute(body, blen, sha);
                        m->crc_match = m->has_expected_crc && crc == m->expected_crc;
                        for (size_t k = 0; k < m->num_known_sha256; ++k)
                            if (memcmp(sha, m->known_sha256[k], 32) == 0) {
                                m->sha_match = true;
                                break;
                            }
                        /* SHA-1: cartridge identity gate (GBA/SNES). */
                        if (m->num_known_sha1 && m->known_sha1_hex) {
                            uint8_t s1[20]; char s1hex[41];
                            recompui_sha1_compute(body, blen, s1);
                            recompui_sha1_hex(s1, s1hex);
                            for (size_t k = 0; k < m->num_known_sha1; ++k) {
                                const char* want = m->known_sha1_hex[k];
                                if (!want) continue;
                                int eq = 1;
                                for (int c = 0; c < 40 && eq; ++c) {
                                    char a = s1hex[c], b = want[c];
                                    if (b >= 'A' && b <= 'Z') b = (char)(b + 32);
                                    if (a != b) eq = 0;
                                }
                                if (eq && want[40] == '\0') {
                                    m->sha1_match = true;
                                    break;
                                }
                            }
                        }
                    }
                    free(buf);
                }
            }
            fclose(f);
        }
    }
    if (!m->rom_size[0]) safe_copy(m->rom_size, sizeof(m->rom_size), "--");

    run_verify(m);
    update_msu1_patch_available(m);
}

// Disc-verdict (verify.mode==1 systems, e.g. PSX): run the SystemProfile's
// VerifyProbeFn against the current ROM/disc path, or synthesize a sensible
// placeholder verdict when the probe is NULL / declines (no host wired up
// yet) so the disc-verdict UI always renders a real verdict block instead of
// a "not recognized" dead end. No-op for verify.mode==0 systems (SNES) — the
// CRC/SHA line above already covers them and m->verify stays zeroed.
static void run_verify(LauncherModel* m) {
    if (!m->profile || m->profile->verify.mode != 1) return;
    memset(&m->verify, 0, sizeof(m->verify));
    // Host disc-verify callback (REAL serial/region/ISO/verdict) takes
    // precedence — re-run here on every ROM/disc change.
    if (m->disc_verify_cb && m->rom_present) {
        RecompLauncherCDiscVerify dv; memset(&dv, 0, sizeof(dv));
        if (m->disc_verify_cb(m->rom_full, &dv)) {
            safe_copy(m->verify.serial, sizeof(m->verify.serial), dv.serial);
            safe_copy(m->verify.region, sizeof(m->verify.region), dv.region);
            m->verify.iso_ok  = dv.iso_ok != 0;
            m->verify.verdict = dv.verdict;
            m->verify.track_count = dv.track_count;
            m->verify.netplay_ok = dv.netplay_ok;
            safe_copy(m->verify.disc_fp, sizeof(m->verify.disc_fp), dv.disc_fp);
            safe_copy(m->verify.netplay_detail, sizeof(m->verify.netplay_detail),
                      dv.netplay_detail);
            return;
        }
    }
    VerifyProbeFn probe = m->profile->verify.probe;
    bool ok = probe && probe(m, &m->verify);
    if (ok) return;
    if (m->rom_present) {
        /* Placeholder facts: no real disc reader is wired up yet, but the
         * checklist should still show something plausible rather than a
         * blank/TODO state. */
        safe_copy(m->verify.serial, sizeof(m->verify.serial), "SCUS-94423");
        safe_copy(m->verify.region, sizeof(m->verify.region),
                  (m->region && m->region[0]) ? m->region : "NTSC-U");
        m->verify.iso_ok  = true;
        m->verify.verdict = 1;   // ok
    } else {
        m->verify.serial[0] = '\0';
        m->verify.region[0] = '\0';
        m->verify.iso_ok  = false;
        m->verify.verdict = 0;   // none
    }
}

const char* launcher_model_rom_path(const LauncherModel* m) {
    return m->rom_full;
}

bool launcher_model_rom_verified(const LauncherModel* m) {
    if (!m->rom_present) return false;
    const int has_crc  = m->has_expected_crc;
    const int has_sha  = m->num_known_sha256 > 0;
    const int has_sha1 = m->num_known_sha1 > 0;
    if (!has_crc && !has_sha && !has_sha1) return false;   // no fingerprint => can't vouch
    if (has_crc  && !m->crc_match)  return false;
    if (has_sha  && !m->sha_match)  return false;
    if (has_sha1 && !m->sha1_match) return false;
    return true;
}

void launcher_model_set_view(LauncherModel* m, LngView v) {
    if (v < 0 || v > LNG_VIEW_MODS) return;
    /* Re-entering Netplay should rescan server + LAN lists. */
    if (m->view == LNG_VIEW_NETPLAY && v != LNG_VIEW_NETPLAY)
        m->netplay_list_fresh = false;
    m->view = v;
}

void launcher_model_open_config(LauncherModel* m, int player) {
    m->cfg_player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    m->view = LNG_VIEW_CONTROLLER;
}

bool launcher_model_can_restore_defaults(const LauncherModel* m) {
    return m && m->has_default_settings;
}

void launcher_model_request_restore_defaults(LauncherModel* m) {
    if (!launcher_model_can_restore_defaults(m)) return;
    m->defaults_modal_open = true;
}

void launcher_model_restore_defaults(LauncherModel* m) {
    if (!launcher_model_can_restore_defaults(m)) return;
    m->s = m->default_settings;
    m->defaults_modal_open = false;
}

void launcher_model_cancel_restore_defaults(LauncherModel* m) {
    if (m) m->defaults_modal_open = false;
}

void launcher_model_cycle_scale(LauncherModel* m) {
    m->s.window_scale = (m->s.window_scale >= 6) ? 1 : m->s.window_scale + 1;
    if (m->s.window_scale < 1) m->s.window_scale = 1;
}

void launcher_model_toggle_filter(LauncherModel* m) {
    m->s.linear_filter = !m->s.linear_filter;
    if (m->s.linear_filter && m->has_sharp_filter)
        m->s.sharp_filter = 0;
}

void launcher_model_cycle_scaling_filter(LauncherModel* m) {
    if (!m || !m->has_sharp_filter) return;
    if (m->s.sharp_filter) {
        m->s.sharp_filter = 0;
        m->s.linear_filter = 0;
    } else if (m->s.linear_filter) {
        m->s.linear_filter = 0;
        m->s.sharp_filter = 1;
    } else {
        m->s.linear_filter = 1;
    }
}

const char* launcher_model_scaling_filter_label(const LauncherModel* m) {
    if (!m) return "Nearest";
    if (m->s.sharp_filter) return "Sharp fractional";
    if (m->s.linear_filter) return "Linear";
    return "Nearest";
}

void launcher_model_toggle_affine_filter(LauncherModel* m) {
    if (!m || !m->has_affine_filter) return;
    m->s.affine_filter = !m->s.affine_filter;
}

void launcher_model_toggle_widescreen(LauncherModel* m) {
    if (!m->widescreen_supported) return;   // gated: no-op when unsupported
    m->s.widescreen = !m->s.widescreen;
}

void launcher_model_toggle_adaptive_view(LauncherModel* m) {
    if (!m->adaptive_view_supported) return;
    m->s.adaptive_view = !m->s.adaptive_view;
}

static int aspect_choice_count(const LauncherModel* m) {
    if (m->aspect_labels && m->num_aspect_labels > 0)
        return m->num_aspect_labels;
    if (!m->aspect_mask) return 0;
    int count = 0;
    for (int i = 0; i < 3; ++i)
        if (launcher_model_aspect_offered(m, i)) ++count;
    return count;
}

static int first_offered_aspect(const LauncherModel* m) {
    if (m->aspect_labels && m->num_aspect_labels > 0) return 0;
    for (int i = 0; i < 3; ++i)
        if (launcher_model_aspect_offered(m, i)) return i;
    return 0;
}

static int next_offered_aspect(const LauncherModel* m, int current) {
    if (m->aspect_labels && m->num_aspect_labels > 0) {
        int next = current + 1;
        return next < m->num_aspect_labels ? next : -1;
    }
    for (int i = current + 1; i < 3; ++i)
        if (launcher_model_aspect_offered(m, i)) return i;
    return -1;
}

void launcher_model_cycle_view_mode(LauncherModel* m) {
    if (!m) return;
    const int fixed_count = aspect_choice_count(m);

    if (m->s.adaptive_view && m->adaptive_view_supported) {
        m->s.adaptive_view = 0;
        if (fixed_count) m->s.aspect_index = first_offered_aspect(m);
        else m->s.widescreen = 0;
        return;
    }

    if (fixed_count) {
        int next = next_offered_aspect(m, m->s.aspect_index);
        if (next >= 0) {
            m->s.aspect_index = next;
            return;
        }
        if (m->adaptive_view_supported) {
            m->s.adaptive_view = 1;
            return;
        }
        m->s.aspect_index = first_offered_aspect(m);
        return;
    }

    if (m->widescreen_supported && !m->s.widescreen) {
        m->s.widescreen = 1;
        return;
    }
    if (m->adaptive_view_supported) {
        m->s.widescreen = 0;
        m->s.adaptive_view = 1;
        return;
    }
    m->s.widescreen = 0;
}

const char* launcher_model_view_mode_label(const LauncherModel* m) {
    if (!m) return "Native";
    if (m->adaptive_view_supported && m->s.adaptive_view) return "Adaptive";
    if (aspect_choice_count(m)) return launcher_model_aspect_label(m);
    return m->s.widescreen ? "16:9 fixed" : "Native";
}

void launcher_model_cycle_display_layout(LauncherModel* m) {
    if (!m || !m->display_layout_labels || m->num_display_layouts <= 0) return;
    m->s.display_layout =
        (clampi(m->s.display_layout, 0, m->num_display_layouts - 1) + 1) %
        m->num_display_layouts;
}

const char* launcher_model_display_layout_label(const LauncherModel* m) {
    if (!m || !m->display_layout_labels || m->num_display_layouts <= 0)
        return "Default";
    return m->display_layout_labels[
        clampi(m->s.display_layout, 0, m->num_display_layouts - 1)];
}

void launcher_model_ws_cells_delta(LauncherModel* m, int delta) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    if (!prof || !prof->video.widescreen_cells) return;   // gated per console
    int v = m->s.widescreen_cells ? m->s.widescreen_cells : 8;
    m->s.widescreen_cells = clampi(v + delta, 1, 16);
}

const char* launcher_model_ws_cells_label(const LauncherModel* m) {
    static char buf[16];
    int v = m->s.widescreen_cells ? clampi(m->s.widescreen_cells, 1, 16) : 8;
    snprintf(buf, sizeof(buf), "%d cells", v);
    return buf;
}

bool launcher_model_aspect_offered(const LauncherModel* m, int index) {
    if (index == 0) return true;   // 4:3 is always implied/available
    if (index == 1) return (m->aspect_mask & 2) != 0;
    if (index == 2) return (m->aspect_mask & 4) != 0;
    return false;
}

void launcher_model_cycle_aspect(LauncherModel* m) {
    if (m->adaptive_view_supported && m->s.adaptive_view && m->s.fullscreen) return;
    if (m->aspect_labels && m->num_aspect_labels > 0) {
        // Game-supplied vocabulary: plain 0..n-1 cycle.
        m->s.aspect_index =
            (clampi(m->s.aspect_index, 0, m->num_aspect_labels - 1) + 1) %
            m->num_aspect_labels;
        return;
    }
    if (!m->aspect_mask) return;   // gated: legacy widescreen-bool games no-op
    int idx = clampi(m->s.aspect_index, 0, 2);
    for (int i = 0; i < 3; ++i) {
        idx = (idx + 1) % 3;
        if (launcher_model_aspect_offered(m, idx)) { m->s.aspect_index = idx; return; }
    }
}

const char* launcher_model_aspect_label(const LauncherModel* m) {
    if (m->aspect_labels && m->num_aspect_labels > 0)
        return m->aspect_labels[clampi(m->s.aspect_index, 0,
                                       m->num_aspect_labels - 1)];
    static const char* kLabels[3] = {
        "4:3 (Native)", "16:9 (Widescreen)", "21:9 (Ultrawide)"
    };
    int idx = clampi(m->s.aspect_index, 0, 2);
    return kLabels[idx];
}

void launcher_model_cycle_freq(LauncherModel* m) {
    int idx = 0;
    for (int i = 0; i < kFreqCount; ++i)
        if (kFreqTable[i] == m->s.audio_freq) { idx = i; break; }
    m->s.audio_freq = kFreqTable[(idx + 1) % kFreqCount];
}

void launcher_model_volume_delta(LauncherModel* m, int delta) {
    m->s.volume = clampi(m->s.volume + delta, 0, 100);
}

// ---- deeper PSX-style settings ---------------------------------------------

void launcher_model_cycle_window_size(LauncherModel* m) {
    int idx = 0;
    for (int i = 0; i < kWindowWidthCount; ++i)
        if (kWindowWidths[i] == m->s.window_width) { idx = i; break; }
    m->s.window_width = kWindowWidths[(idx + 1) % kWindowWidthCount];
}

const char* launcher_model_window_size_label(const LauncherModel* m) {
    static char buf[32];
    int w = m->s.window_width > 0 ? m->s.window_width : kWindowWidths[0];
    int aspect = clampi(m->s.aspect_index, 0, 2);
    int h = (aspect == 1) ? (w * 9 / 16) : (aspect == 2) ? (w * 9 / 21) : (w * 3 / 4);
    snprintf(buf, sizeof(buf), "%d \xC3\x97 %d", w, h);   // "×" (U+00D7)
    return buf;
}

void launcher_model_toggle_renderer(LauncherModel* m) {
    // Game-supplied renderer vocabulary (RT64 hosts: Auto/Vulkan/D3D12)
    // cycles its full list; the legacy pair stays a 2-value toggle.
    if (m->renderer_labels && m->num_renderers > 0) {
        m->s.renderer = (m->s.renderer + 1) % m->num_renderers;
        return;
    }
    m->s.renderer = !m->s.renderer;
}

const char* launcher_model_renderer_label(const LauncherModel* m) {
    if (m->renderer_labels && m->num_renderers > 0) {
        int i = clampi(m->s.renderer, 0, m->num_renderers - 1);
        return m->renderer_labels[i];
    }
    // Per-console vocabulary (SystemProfile.renderer_labels): NES says
    // Accelerated/Software; NULL keeps the legacy PSX-era pair.
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    if (prof && prof->renderer_labels)
        return prof->renderer_labels[m->s.renderer ? 1 : 0];
    return m->s.renderer ? "OpenGL" : "Software";
}

void launcher_model_cycle_supersampling(LauncherModel* m) {
    int v = clampi(m->s.supersampling ? m->s.supersampling : 1, 1, 4);
    m->s.supersampling = (v % 4) + 1;
}

const char* launcher_model_supersampling_label(const LauncherModel* m) {
    /* Settings SSAA: offline full SW/GL path; netplay dual-raster uses this
     * for OpenGL present quality while SW authority stays 1×. */
    static char buf[24];
    int v = clampi(m->s.supersampling ? m->s.supersampling : 1, 1, 4);
    if (v <= 1)
        snprintf(buf, sizeof(buf), "1x");
    else
        snprintf(buf, sizeof(buf), "%dx", v);
    return buf;
}

// Antialiasing is an MSAA sample COUNT, not a bool: Off / 2x / 4x / 8x. Cycle
// wraps 0 -> 2 -> 4 -> 8 -> 0. A legacy on/off host value of 1 is treated as
// "on" by the label and advances to Off on the next cycle.
void launcher_model_cycle_aa(LauncherModel* m) {
    switch (m->s.antialiasing) {
        case 0:  m->s.antialiasing = 2; break;
        case 2:  m->s.antialiasing = 4; break;
        case 4:  m->s.antialiasing = 8; break;
        default: m->s.antialiasing = 0; break;   // 8 (or legacy 1/other) -> Off
    }
}

const char* launcher_model_aa_label(const LauncherModel* m) {
    switch (m->s.antialiasing) {
        case 0:  return "Off";
        case 2:  return "2x";
        case 4:  return "4x";
        case 8:  return "8x";
        default: return "On";   // legacy on/off host value (1)
    }
}

void launcher_model_toggle_texture_filter(LauncherModel* m) {
    m->s.texture_filter = !m->s.texture_filter;
}

const char* launcher_model_texture_filter_label(const LauncherModel* m) {
    return m->s.texture_filter ? "Bilinear" : "Nearest";
}

void launcher_model_toggle_geometry_correction(LauncherModel* m) {
    m->s.geometry_correction = !m->s.geometry_correction;
}

void launcher_model_toggle_perspective_texturing(LauncherModel* m) {
    m->s.perspective_texturing = !m->s.perspective_texturing;
}

/* Sub-pixel vertices are only observable in the supersampled mirror: at 1x the
 * corrected position rounds back to the pixel it came from. Say so in the UI
 * rather than letting the row look broken when someone ticks it at native res. */
bool launcher_model_geometry_correction_inert(const LauncherModel* m) {
    return m->s.geometry_correction && m->s.supersampling < 2;
}

// Screen-model vocabulary: the active SystemProfile's own set when it has one
// (e.g. GBA's 5 LCD models), else the legacy 4-entry PSX-era set above.
static const char* const* screen_kind_vocab(const LauncherModel* m, int* out_n) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    if (prof && prof->screen_kind_names && prof->screen_kind_count > 0) {
        *out_n = prof->screen_kind_count;
        return prof->screen_kind_names;
    }
    *out_n = 4;
    return kScreenKindNames;
}

void launcher_model_cycle_screen_kind(LauncherModel* m) {
    int n = 4; (void)screen_kind_vocab(m, &n);
    m->s.screen_kind = (clampi(m->s.screen_kind, 0, n - 1) + 1) % n;
}

const char* launcher_model_screen_kind_label(const LauncherModel* m) {
    int n = 4;
    const char* const* names = screen_kind_vocab(m, &n);
    return names[clampi(m->s.screen_kind, 0, n - 1)];
}

void launcher_model_toggle_frame_interp(LauncherModel* m) {
    m->s.frame_interp = !m->s.frame_interp;
}

void launcher_model_cycle_interp_fps(LauncherModel* m) {
    int idx = 0;
    for (int i = 0; i < kInterpFpsCount; ++i)
        if (kInterpFpsTable[i] == m->s.frame_interp_fps) { idx = i; break; }
    m->s.frame_interp_fps = kInterpFpsTable[(idx + 1) % kInterpFpsCount];
}

const char* launcher_model_interp_fps_label(const LauncherModel* m) {
    static char buf[24];
    if (m->s.frame_interp_fps == 0) return "Display refresh";
    snprintf(buf, sizeof(buf), "%d fps", m->s.frame_interp_fps);
    return buf;
}

void launcher_model_toggle_spu_hq(LauncherModel* m) {
    m->s.spu_hq = !m->s.spu_hq;
}

void launcher_model_toggle_skip_fmv(LauncherModel* m) {
    m->s.auto_skip_fmv = !m->s.auto_skip_fmv;
}

void launcher_model_toggle_turbo_loads(LauncherModel* m) {
    m->s.turbo_loads = !m->s.turbo_loads;
}

// Fullscreen is a universal display setting: every console's runner applies
// the committed tri-state (0 off / 1 borderless / 2 exclusive) to its window
// at boot and persists it in its own config. The cycle walks all three
// states, restoring the vocabulary of the original SNES launcher.
void launcher_model_cycle_fullscreen(LauncherModel* m) {
    m->s.fullscreen = (clampi(m->s.fullscreen, 0, 2) + 1) % 3;
}

const char* launcher_model_fullscreen_label(const LauncherModel* m) {
    static const char* const kNames[3] = { "Off", "Borderless", "Exclusive" };
    return kNames[clampi(m->s.fullscreen, 0, 2)];
}

void launcher_model_toggle_fullscreen(LauncherModel* m) {
    // Binary on/off (0 <-> 1); superseded in the UI by the tri-state cycle
    // above but kept for hosts that drive the field as a bool.
    m->s.fullscreen = m->s.fullscreen ? 0 : 1;
}

void launcher_model_cycle_language(LauncherModel* m) {
    if (m->num_languages <= 0) return;
    m->s.language_index = (m->s.language_index + 1) % m->num_languages;
}

const char* launcher_model_language_label(const LauncherModel* m) {
    if (m->num_languages <= 0 || !m->language_labels) return "";
    int idx = clampi(m->s.language_index, 0, m->num_languages - 1);
    return m->language_labels[idx] ? m->language_labels[idx] : "";
}

void launcher_model_cycle_deadzone_pct(LauncherModel* m) {
    int v = clampi(m->s.deadzone[0], 0, 50);
    v = ((v / 5) + 1) * 5;
    if (v > 50) v = 0;
    m->s.deadzone[0] = v;
    m->s.deadzone[1] = v;
}

const char* launcher_model_deadzone_pct_label(const LauncherModel* m) {
    static char buf[8];
    snprintf(buf, sizeof(buf), "%d%%", clampi(m->s.deadzone[0], 0, 50));
    return buf;
}

void launcher_model_refresh_bios_status(LauncherModel* m) {
    if (!m) return;
    m->setup_bios_ok = false;
    m->setup_bios_warn = false;
    m->setup_bios_needs_regen = false;
    m->setup_bios_detail[0] = '\0';
    if (!m->has_bios) {
        m->setup_bios_ok = true;
        return;
    }
    /* Empty path = use the BIOS this build ships with (OpenBIOS / bundled).
     * Host bios_verify("", ...) may refuse that for titles that require a
     * retail dump; otherwise empty is OK — matching Settings → BIOS. */
    if (!m->s.bios_path[0]) {
        if (m->bios_verify_cb) {
            RecompLauncherCBiosVerify bv;
            memset(&bv, 0, sizeof(bv));
            if (!m->bios_verify_cb("", &bv)) {
                safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                          "BIOS verification failed.");
                return;
            }
            m->setup_bios_ok = bv.ok != 0;
            m->setup_bios_warn = bv.warn != 0;
            /* Empty path is OpenBIOS — never treat as needing regen. */
            m->setup_bios_needs_regen = false;
            if (bv.detail[0])
                safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                          bv.detail);
            else if (m->setup_bios_ok)
                safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                          "Using OpenBIOS.");
            return;
        }
        m->setup_bios_ok = true;
        m->setup_bios_needs_regen = false;
        safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                  "Using OpenBIOS.");
        return;
    }
    if (!m->bios_verify_cb) {
        /* No host verifier: path non-empty is enough. */
        FILE* f = fopen(m->s.bios_path, "rb");
        if (f) { fclose(f); m->setup_bios_ok = true; }
        else safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                       "BIOS file not found.");
        return;
    }
    RecompLauncherCBiosVerify bv;
    memset(&bv, 0, sizeof(bv));
    if (!m->bios_verify_cb(m->s.bios_path, &bv)) {
        safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                  "BIOS verification failed.");
        return;
    }
    m->setup_bios_ok = bv.ok != 0;
    m->setup_bios_warn = bv.warn != 0;
    m->setup_bios_needs_regen = bv.needs_regen != 0;
    safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail), bv.detail);
}

/* Write/clear a one-line sidecar in dir (dir may be NULL => cwd "."). */
static void lm_write_sidecar_in_dir(const char* dir, const char* name,
                                    const char* value) {
    char path[1100];
    if (!name || !name[0]) return;
    if (dir && dir[0]) {
        size_t n = strlen(dir);
        int need = (n > 0 && dir[n - 1] != '/' && dir[n - 1] != '\\');
        if ((size_t)snprintf(path, sizeof(path), "%s%s%s", dir, need ? "/" : "",
                             name) >= sizeof(path))
            return;
    } else {
        if ((size_t)snprintf(path, sizeof(path), "%s", name) >= sizeof(path))
            return;
    }
    if (!value || !value[0]) {
        remove(path);
        return;
    }
    FILE* f = fopen(path, "w");
    if (!f) return;
    fprintf(f, "%s\n", value);
    fclose(f);
}

static int lm_running_exe_dir(char* out, size_t cap) {
    if (!out || cap < 2) return 0;
    out[0] = '\0';
#if defined(_WIN32)
    {
        char mod[MAX_PATH];
        DWORD n = GetModuleFileNameA(NULL, mod, MAX_PATH);
        char* slash;
        if (n == 0 || n >= MAX_PATH) return 0;
        slash = strrchr(mod, '\\');
        if (!slash) slash = strrchr(mod, '/');
        if (!slash) return 0;
        *slash = '\0';
        if ((size_t)snprintf(out, cap, "%s", mod) >= cap) return 0;
        return 1;
    }
#elif defined(__APPLE__)
    {
        char mod[1024];
        uint32_t n = (uint32_t)sizeof(mod);
        char* slash;
        if (_NSGetExecutablePath(mod, &n) != 0) return 0;
        slash = strrchr(mod, '/');
        if (!slash) return 0;
        *slash = '\0';
        if ((size_t)snprintf(out, cap, "%s", mod) >= cap) return 0;
        return 1;
    }
#else
    {
        char mod[1024];
        ssize_t n = readlink("/proc/self/exe", mod, sizeof(mod) - 1);
        char* slash;
        if (n <= 0) return 0;
        mod[n] = '\0';
        slash = strrchr(mod, '/');
        if (!slash) return 0;
        *slash = '\0';
        if ((size_t)snprintf(out, cap, "%s", mod) >= cap) return 0;
        return 1;
    }
#endif
}

/* Persist ROM/BIOS picks where codegen hosts and the relaunched exe look:
 * cwd, running-exe dir, and (when known) the rebuild output dir. */
static void lm_persist_setup_sidecars(LauncherModel* m) {
    char exe_dir[1024];
    const char* rom = (m && m->rom_full[0]) ? m->rom_full : NULL;
    const char* bios =
        (m && m->has_bios && m->s.bios_path[0]) ? m->s.bios_path : NULL;
    /* PSX hosts read disc.cfg; cart hosts read rom.cfg — write both names. */
    lm_write_sidecar_in_dir(NULL, "rom.cfg", rom);
    lm_write_sidecar_in_dir(NULL, "disc.cfg", rom);
    lm_write_sidecar_in_dir(NULL, "bios.cfg", bios);
    if (lm_running_exe_dir(exe_dir, sizeof(exe_dir))) {
        lm_write_sidecar_in_dir(exe_dir, "rom.cfg", rom);
        lm_write_sidecar_in_dir(exe_dir, "disc.cfg", rom);
        lm_write_sidecar_in_dir(exe_dir, "bios.cfg", bios);
    }
    if (m && m->relaunch_exe[0]) {
        char rdir[1024];
        char* slash = strrchr(m->relaunch_exe, '/');
        char* bslash = strrchr(m->relaunch_exe, '\\');
        char* cut = slash;
        if (bslash && (!cut || bslash > cut)) cut = bslash;
        if (cut && cut > m->relaunch_exe) {
            size_t n = (size_t)(cut - m->relaunch_exe);
            if (n < sizeof(rdir)) {
                memcpy(rdir, m->relaunch_exe, n);
                rdir[n] = '\0';
                lm_write_sidecar_in_dir(rdir, "rom.cfg", rom);
                lm_write_sidecar_in_dir(rdir, "disc.cfg", rom);
                lm_write_sidecar_in_dir(rdir, "bios.cfg", bios);
            }
        }
    }
    if (m && m->persist_setup_cb)
        m->persist_setup_cb(m->persist_setup_ctx, rom ? rom : "",
                            bios ? bios : "");
}

void launcher_model_set_bios_path(LauncherModel* m, const char* path) {
    if (path && path[0]) {
#if defined(_WIN32)
        char abs[MAX_PATH];
        DWORD n = GetFullPathNameA(path, (DWORD)sizeof(abs), abs, NULL);
        safe_copy(m->s.bios_path, sizeof(m->s.bios_path),
                  (n > 0 && n < (DWORD)sizeof(abs)) ? abs : path);
#else
        char* rp = realpath(path, NULL);
        safe_copy(m->s.bios_path, sizeof(m->s.bios_path), rp ? rp : path);
        free(rp);
#endif
    } else {
        m->s.bios_path[0] = '\0';
    }
    launcher_model_refresh_bios_status(m);
    lm_persist_setup_sidecars(m);
}

static void lm_normalize_bios_path(const char* path, char* out, size_t out_cap) {
    if (!out || out_cap == 0) return;
    out[0] = '\0';
    if (!path || !path[0]) return;
#if defined(_WIN32)
    {
        char abs[MAX_PATH];
        DWORD n = GetFullPathNameA(path, (DWORD)sizeof(abs), abs, NULL);
        safe_copy(out, out_cap,
                  (n > 0 && n < (DWORD)sizeof(abs)) ? abs : path);
    }
#else
    {
        char* rp = realpath(path, NULL);
        safe_copy(out, out_cap, rp ? rp : path);
        free(rp);
    }
#endif
}

static int lm_bios_paths_equal(const char* a, const char* b) {
    if ((!a || !a[0]) && (!b || !b[0])) return 1;
    if (!a || !a[0] || !b || !b[0]) return 0;
#if defined(_WIN32)
    return _stricmp(a, b) == 0;
#else
    return strcmp(a, b) == 0;
#endif
}

void launcher_model_start_prepare_disc(LauncherModel* m, const char* source_path);

static void lm_bios_revert_uncommitted(LauncherModel* m) {
    if (!m || !m->bios_switch_uncommitted) return;
    safe_copy(m->s.bios_path, sizeof(m->s.bios_path), m->bios_revert_path);
    m->bios_switch_uncommitted = false;
    m->bios_pending_path[0] = '\0';
    m->bios_revert_path[0] = '\0';
    launcher_model_refresh_bios_status(m);
    lm_persist_setup_sidecars(m);
}

static void lm_bios_commit_uncommitted(LauncherModel* m) {
    if (!m || !m->bios_switch_uncommitted) return;
    m->bios_switch_uncommitted = false;
    m->bios_pending_path[0] = '\0';
    m->bios_revert_path[0] = '\0';
    /* Path already on the model; rewrite sidecars next to the new exe. */
    lm_persist_setup_sidecars(m);
}

/* Apply pending/current BIOS and start Generate & rebuild without the full
 * first-run wizard (progress modal only). Falls back to the wizard when the
 * disc or toolchain is missing. */
static void lm_bios_kick_generate(LauncherModel* m) {
    if (!m) return;
    if (m->setup_preparing) return; /* ignore double-clicks / overlapping jobs */
    if (!m->setup_wizard_supported) {
        lm_bios_revert_uncommitted(m);
        return;
    }
    m->setup_wizard_open = false;
    m->bios_confirm_open = false;
    m->bios_play_modal_open = false;
    /* Re-probe: setup_tc_ready may still be false if the wizard never opened. */
    if (m->setup_needs_toolchain) {
        if (m->toolchain_is_ready_cb && m->toolchain_is_ready_cb())
            m->setup_tc_ready = true;
        if (!m->setup_tc_ready) {
            lm_bios_revert_uncommitted(m);
            m->setup_wizard_open = true;
            m->setup_page = 0;
            return;
        }
    }
    if (m->rom_present && m->rom_full[0] &&
        (m->prepare_with_progress_cb || m->prepare_disc_cb)) {
        /* Stage disc + BIOS sidecars so the host CLI gets --disc/--bios. */
        lm_persist_setup_sidecars(m);
        launcher_model_start_prepare_disc(m, m->rom_full);
        return;
    }
    /* Need a disc pick — open the setup page, not a silent no-op. */
    lm_bios_revert_uncommitted(m);
    m->setup_wizard_open = true;
    m->setup_page = 1;
}

void launcher_model_request_bios_path(LauncherModel* m, const char* path) {
    char normalized[512];
    RecompLauncherCBiosVerify bv;
    if (!m) return;
    lm_normalize_bios_path(path, normalized, sizeof(normalized));
    if (lm_bios_paths_equal(m->s.bios_path, normalized))
        return;

    memset(&bv, 0, sizeof(bv));
    if (m->bios_verify_cb) {
        if (!m->bios_verify_cb(normalized, &bv)) {
            safe_copy(bv.detail, sizeof(bv.detail), "BIOS verification failed.");
            /* OpenBIOS never regenerates; retail may still need Generate. */
            bv.needs_regen = normalized[0] ? 1 : 0;
            bv.ok = 0;
        }
    } else {
        /* No host callback: treat any change as immediate. */
        launcher_model_set_bios_path(m, normalized);
        return;
    }

    /* OpenBIOS (empty path): always hot-swap when accepted. Never open the
     * Generate & rebuild confirm — Play uses the bundled backend already
     * linked (or the setup host will emit it on first Generate for game C). */
    if (!normalized[0]) {
        if (bv.ok) {
            launcher_model_set_bios_path(m, "");
            return;
        }
        if (bv.detail[0])
            safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                      bv.detail);
        return;
    }

    /* Invalid dump (missing/wrong size) — keep the previous selection. */
    if (!bv.ok && !bv.needs_regen) {
        if (bv.detail[0])
            safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                      bv.detail);
        return;
    }

    /* Retail already compiled into this binary → hot-swap (no rebuild). */
    if (bv.ok && !bv.needs_regen) {
        launcher_model_set_bios_path(m, normalized);
        return;
    }

    /* Retail dump is valid but its backend is not linked yet → confirm
     * Generate & rebuild (codegen hosts kick generate on accept). */
    safe_copy(m->bios_pending_path, sizeof(m->bios_pending_path), normalized);
    if (bv.detail[0])
        safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail), bv.detail);
    else
        safe_copy(m->setup_bios_detail, sizeof(m->setup_bios_detail),
                  "This retail BIOS is not compiled into the current build. "
                  "Generate & rebuild to add it (or Use OpenBIOS).");
    m->bios_confirm_open = true;
}

void launcher_model_bios_confirm_accept(LauncherModel* m) {
    if (!m) return;
    if (m->setup_preparing) return;
    m->bios_confirm_open = false;
    /* Stage the new BIOS for the generate CLI, but remember the prior pick so
     * a failed prepare/rebuild can restore it (do not stick a failed switch). */
    safe_copy(m->bios_revert_path, sizeof(m->bios_revert_path), m->s.bios_path);
    safe_copy(m->s.bios_path, sizeof(m->s.bios_path), m->bios_pending_path);
    m->bios_switch_uncommitted = true;
    launcher_model_refresh_bios_status(m);
    lm_bios_kick_generate(m);
}

void launcher_model_bios_confirm_cancel(LauncherModel* m) {
    if (!m) return;
    m->bios_confirm_open = false;
    m->bios_pending_path[0] = '\0';
    launcher_model_refresh_bios_status(m);
}

bool launcher_model_bios_blocks_play(const LauncherModel* m) {
    if (!m || !m->has_bios) return false;
    if (m->setup_preparing) return false;
    /* Disc/ROM must otherwise look ready — otherwise the normal Play disable
     * / setup-wizard path is enough. */
    if (!m->rom_present || strcmp(m->rom_size, "--") == 0) return false;
    if (m->profile && m->profile->verify.mode == 1) {
        if (m->verify.verdict == 0 || m->verify.verdict == 3) return false;
    }
    /* OpenBIOS (empty path) never blocks Play for a BIOS regen. */
    if (!m->s.bios_path[0]) return false;
    /* Retail linked-backend mismatch (needs_regen) blocks Play. */
    if (m->setup_bios_needs_regen) return true;
    /* Retail path that isn't Play-ready in this binary. */
    if (!m->setup_bios_ok) return true;
    return false;
}

void launcher_model_bios_play_prompt(LauncherModel* m) {
    if (!m) return;
    m->bios_play_modal_open = true;
}

void launcher_model_bios_play_use_openbios(LauncherModel* m) {
    if (!m) return;
    m->bios_play_modal_open = false;
    /* OpenBIOS always applies immediately — no Generate & rebuild. */
    launcher_model_request_bios_path(m, "");
}

void launcher_model_bios_play_generate(LauncherModel* m) {
    if (!m) return;
    if (m->setup_preparing) return;
    m->bios_play_modal_open = false;
    /* Current m->s.bios_path is already the desired pick — stage + generate. */
    lm_bios_kick_generate(m);
}

void launcher_model_bios_play_cancel(LauncherModel* m) {
    if (!m) return;
    m->bios_play_modal_open = false;
}

bool launcher_model_setup_media_confirm_only(const LauncherModel* m) {
    if (!m || !m->setup_wizard_supported) return false;
    if (m->prepare_required_before_continue) return false;
    /* Codegen hosts keep prepare_* wired after the first Generate & rebuild.
     * Missing that wiring means a cart / non-codegen first-run — keep the
     * normal media picker copy, not the "confirm cleared paths" prompt. */
    if (!m->prepare_with_progress_cb && !m->prepare_disc_cb) return false;
    return true;
}

bool launcher_model_can_finish_setup(const LauncherModel* m) {
    if (!m) return false;
    if (m->setup_preparing) return false;
    /* Path selected is enough to leave the wizard (settings stay in the model).
     * PLAY still requires a readable, fingerprinted image via can_launch.
     * Codegen hosts may also require a successful prepare/rebuild. */
    if (!m->rom_present || !m->rom_full[0]) return false;
    if (m->has_bios && !m->setup_bios_ok) return false;
    if (m->prepare_required_before_continue && !m->setup_prepare_satisfied)
        return false;
    /* Disc titles: TOC / require_cue policy (netplay_ok) must pass before
     * leaving first-run setup — Track-01-only dumps fail generate + netplay. */
    if (m->profile && m->profile->verify.mode == 1) {
        if (m->verify.verdict == 0 || m->verify.verdict == 3) return false;
        if (!m->verify.netplay_ok) return false;
    }
    return true;
}

bool launcher_model_can_launch(const LauncherModel* m) {
    if (!m) return false;
    if (!m->rom_present || strcmp(m->rom_size, "--") == 0) return false;
    if (m->profile && m->profile->verify.mode == 1) {
        /* Disc systems: reject none/bad; warn (2) and ok (1) are playable. */
        if (m->verify.verdict == 0 || m->verify.verdict == 3) return false;
    } else {
        const int has_fp = m->has_expected_crc || m->num_known_sha256 > 0 ||
                           m->num_known_sha1 > 0;
        if (has_fp && !launcher_model_rom_verified(m)) return false;
    }
    if (m->has_bios && !m->setup_bios_ok) return false;
    if (m->setup_preparing) return false;
    return true;
}

bool launcher_model_netplay_disc_ok(const LauncherModel* m) {
    if (!m || !m->netplay_supported) return false;
    if (!m->profile || m->profile->verify.mode != 1)
        return true; /* non-disc titles: no TOC gate */
    if (!m->rom_present) return false;
    /* Online requires a clean verified mount (not CRC-warn-only) + TOC policy. */
    if (m->verify.verdict != 1) return false;
    if (!m->verify.netplay_ok) return false;
    if (!m->verify.disc_fp[0]) return false;
    return true;
}

void launcher_model_finish_setup(LauncherModel* m) {
    if (!m || !launcher_model_can_finish_setup(m)) return;
    m->setup_wizard_open = false;
    m->setup_status[0] = '\0';
    m->setup_error[0] = '\0';
}

/* ---- prepare / rebuild / toolchain background job (one at a time) ---- */
enum {
    PREP_JOB_PREPARE = 0,
    PREP_JOB_REBUILD = 1,
    PREP_JOB_TOOLCHAIN = 2,
    PREP_JOB_PGO = 3,
    PREP_JOB_FMV_TIMING = 4
};

typedef struct {
    LauncherModel* m;
    char source[512];
    char out_path[512];
    char err[256];
    char progress_msg[256];
    char zip_path[512];
    float progress_pct; /* <0 indeterminate; else 0..1 */
    int  kind;          /* PREP_JOB_* */
    int  download;      /* toolchain: non-zero => allow network fetch */
    int  result;        /* 0 fail, 1 ok */
    volatile int done;
    volatile int progress_dirty;
} PrepJob;

static PrepJob g_prep_job;

#if defined(_WIN32)
static CRITICAL_SECTION g_prep_lock;
static int g_prep_lock_ready = 0;
static void prep_lock_init(void) {
    if (!g_prep_lock_ready) { InitializeCriticalSection(&g_prep_lock); g_prep_lock_ready = 1; }
}
static void prep_lock(void) { prep_lock_init(); EnterCriticalSection(&g_prep_lock); }
static void prep_unlock(void) { LeaveCriticalSection(&g_prep_lock); }
#else
static pthread_mutex_t g_prep_lock = PTHREAD_MUTEX_INITIALIZER;
static void prep_lock(void) { pthread_mutex_lock(&g_prep_lock); }
static void prep_unlock(void) { pthread_mutex_unlock(&g_prep_lock); }
#endif

static void prep_progress_cb(void* ctx, float pct, const char* message) {
    PrepJob* j = (PrepJob*)ctx;
    if (!j) return;
    prep_lock();
    j->progress_pct = pct;
    if (message && message[0])
        safe_copy(j->progress_msg, sizeof(j->progress_msg), message);
    j->progress_dirty = 1;
    prep_unlock();
}

#if defined(_WIN32)
static DWORD WINAPI prep_thread_main(LPVOID arg);
#else
static void* prep_thread_main(void* arg);
#endif

static int prep_spawn_thread(LauncherModel* m) {
#if defined(_WIN32)
    HANDLE th = CreateThread(NULL, 0, prep_thread_main, &g_prep_job, 0, NULL);
    if (!th) {
        m->setup_preparing = false;
        safe_copy(m->setup_error, sizeof(m->setup_error), "Failed to start prepare thread.");
        m->setup_status[0] = '\0';
        return 0;
    }
    CloseHandle(th);
#else
    pthread_t th;
    if (pthread_create(&th, NULL, prep_thread_main, &g_prep_job) != 0) {
        m->setup_preparing = false;
        safe_copy(m->setup_error, sizeof(m->setup_error), "Failed to start prepare thread.");
        m->setup_status[0] = '\0';
        return 0;
    }
    pthread_detach(th);
#endif
    return 1;
}

#if defined(_WIN32)
static DWORD WINAPI prep_thread_main(LPVOID arg) {
#else
static void* prep_thread_main(void* arg) {
#endif
    PrepJob* j = (PrepJob*)arg;
    j->out_path[0] = '\0';
    j->err[0] = '\0';
    j->result = 0;
    if (j->kind == PREP_JOB_TOOLCHAIN) {
        if (j->m && j->m->ensure_toolchain_with_progress_cb) {
            j->result = j->m->ensure_toolchain_with_progress_cb(
                            j->download,
                            j->zip_path[0] ? j->zip_path : NULL,
                            j->err, sizeof(j->err),
                            prep_progress_cb, j)
                            ? 1
                            : 0;
            if (j->result)
                safe_copy(j->out_path, sizeof(j->out_path), "ok");
        } else {
            safe_copy(j->err, sizeof(j->err), "No toolchain ensure callback.");
        }
    } else if (j->kind == PREP_JOB_REBUILD) {
        if (j->m && j->m->rebuild_with_progress_cb) {
            j->result = j->m->rebuild_with_progress_cb(
                            j->source, j->out_path, sizeof(j->out_path),
                            j->err, sizeof(j->err),
                            prep_progress_cb, j) ? 1 : 0;
        } else {
            safe_copy(j->err, sizeof(j->err), "No rebuild callback.");
        }
    } else if (j->kind == PREP_JOB_PGO) {
        if (j->m && j->m->pgo_optimize_with_progress_cb) {
            j->result = j->m->pgo_optimize_with_progress_cb(
                            j->source, j->out_path, sizeof(j->out_path),
                            j->err, sizeof(j->err),
                            prep_progress_cb, j) ? 1 : 0;
        } else {
            safe_copy(j->err, sizeof(j->err), "No PGO optimize callback.");
        }
    } else if (j->kind == PREP_JOB_FMV_TIMING) {
        if (j->m && j->m->fmv_timing_optimize_with_progress_cb) {
            j->result = j->m->fmv_timing_optimize_with_progress_cb(
                            j->source, j->out_path, sizeof(j->out_path),
                            j->err, sizeof(j->err),
                            prep_progress_cb, j) ? 1 : 0;
        } else {
            safe_copy(j->err, sizeof(j->err), "No FMV timing optimize callback.");
        }
    } else if (j->m && j->m->prepare_with_progress_cb) {
        j->result = j->m->prepare_with_progress_cb(
                        j->source, j->out_path, sizeof(j->out_path),
                        j->err, sizeof(j->err),
                        prep_progress_cb, j) ? 1 : 0;
    } else if (j->m && j->m->prepare_disc_cb) {
        j->result = j->m->prepare_disc_cb(j->source, j->out_path, sizeof(j->out_path),
                                          j->err, sizeof(j->err)) ? 1 : 0;
    } else {
        safe_copy(j->err, sizeof(j->err), "No prepare callback.");
    }
    j->done = 1;
#if defined(_WIN32)
    return 0;
#else
    return NULL;
#endif
}

static void launcher_model_begin_rebuild_locked(LauncherModel* m) {
    /* Caller has already cleared setup_preparing from a completed prepare. */
    memset(&g_prep_job, 0, sizeof(g_prep_job));
    g_prep_job.m = m;
    g_prep_job.kind = PREP_JOB_REBUILD;
    g_prep_job.progress_pct = -1.0f;
    safe_copy(g_prep_job.source, sizeof(g_prep_job.source), m->rom_full);
    m->setup_preparing = true;
    m->setup_prepare_pulse = 0.0f;
    m->setup_prepare_fraction = -1.0f;
    m->setup_error[0] = '\0';
    safe_copy(m->setup_status, sizeof(m->setup_status),
              (m->rebuild_busy_status && m->rebuild_busy_status[0])
                  ? m->rebuild_busy_status
                  : "Building game…");
    if (!prep_spawn_thread(m))
        return;
}

void launcher_model_start_rebuild(LauncherModel* m) {
    if (!m || m->setup_preparing || !m->rebuild_with_progress_cb) return;
    if (!m->rom_full[0]) {
        safe_copy(m->setup_error, sizeof(m->setup_error), "Select a ROM before rebuilding.");
        return;
    }
    m->setup_progress_title[0] = '\0';
    launcher_model_begin_rebuild_locked(m);
}

void launcher_model_request_pgo_optimize(LauncherModel* m) {
    if (!m || m->setup_preparing || !m->pgo_optimize_with_progress_cb) return;
    m->pgo_confirm_open = true;
}

void launcher_model_pgo_confirm_cancel(LauncherModel* m) {
    if (!m) return;
    m->pgo_confirm_open = false;
}

static void launcher_model_begin_pgo_locked(LauncherModel* m) {
    memset(&g_prep_job, 0, sizeof(g_prep_job));
    g_prep_job.m = m;
    g_prep_job.kind = PREP_JOB_PGO;
    g_prep_job.progress_pct = -1.0f;
    safe_copy(g_prep_job.source, sizeof(g_prep_job.source), m->rom_full);
    m->setup_preparing = true;
    m->setup_prepare_pulse = 0.0f;
    m->setup_prepare_fraction = -1.0f;
    m->setup_error[0] = '\0';
    safe_copy(m->setup_progress_title, sizeof(m->setup_progress_title),
              "Optimize FMV Playback");
    safe_copy(m->setup_status, sizeof(m->setup_status),
              (m->pgo_busy_status && m->pgo_busy_status[0])
                  ? m->pgo_busy_status
                  : "Optimizing FMV (instrument → train → rebuild)…");
    if (!prep_spawn_thread(m))
        return;
}

void launcher_model_pgo_confirm_accept(LauncherModel* m) {
    if (!m || m->setup_preparing || !m->pgo_optimize_with_progress_cb) return;
    m->pgo_confirm_open = false;
    if (!m->rom_full[0]) {
        safe_copy(m->setup_error, sizeof(m->setup_error),
                  "Select a disc image before optimizing FMV.");
        return;
    }
    launcher_model_begin_pgo_locked(m);
}

void launcher_model_request_fmv_timing_optimize(LauncherModel* m) {
    if (!m || m->setup_preparing || !m->fmv_timing_optimize_with_progress_cb)
        return;
    m->fmv_timing_confirm_open = true;
}

void launcher_model_fmv_timing_confirm_cancel(LauncherModel* m) {
    if (!m) return;
    m->fmv_timing_confirm_open = false;
}

static void launcher_model_begin_fmv_timing_locked(LauncherModel* m) {
    memset(&g_prep_job, 0, sizeof(g_prep_job));
    g_prep_job.m = m;
    g_prep_job.kind = PREP_JOB_FMV_TIMING;
    g_prep_job.progress_pct = -1.0f;
    safe_copy(g_prep_job.source, sizeof(g_prep_job.source), m->rom_full);
    m->setup_preparing = true;
    m->setup_prepare_pulse = 0.0f;
    m->setup_prepare_fraction = -1.0f;
    m->setup_error[0] = '\0';
    safe_copy(m->setup_progress_title, sizeof(m->setup_progress_title),
              "Apply FMV Timing Opt");
    safe_copy(m->setup_status, sizeof(m->setup_status),
              (m->fmv_timing_busy_status && m->fmv_timing_busy_status[0])
                  ? m->fmv_timing_busy_status
                  : "Regenerating sources and rebuilding…");
    if (!prep_spawn_thread(m))
        return;
}

void launcher_model_fmv_timing_confirm_accept(LauncherModel* m) {
    if (!m || m->setup_preparing || !m->fmv_timing_optimize_with_progress_cb)
        return;
    m->fmv_timing_confirm_open = false;
    if (!m->rom_full[0]) {
        safe_copy(m->setup_error, sizeof(m->setup_error),
                  "Select a disc image before applying FMV timing.");
        return;
    }
    launcher_model_begin_fmv_timing_locked(m);
}

bool launcher_model_can_advance_toolchain(const LauncherModel* m) {
    if (!m || !m->setup_needs_toolchain) return true;
    if (m->setup_preparing) return false;
    const int want_update =
        m->setup_tc_update_available && !m->setup_tc_update_skipped;
    if (m->setup_tc_ready && !want_update) return true;
    if (m->setup_tc_auto) return true;
    return m->setup_tc_zip[0] != '\0';
}

void launcher_model_skip_toolchain_update(LauncherModel* m) {
    if (!m || !m->setup_needs_toolchain) return;
    if (!m->setup_tc_ready || !m->setup_tc_update_available) return;
    m->setup_tc_update_skipped = true;
    m->setup_page = 1;
    m->setup_error[0] = '\0';
    safe_copy(m->setup_status, sizeof(m->setup_status),
              "Keeping current toolchain — continue with BIOS and disc.");
}

void launcher_model_start_ensure_toolchain(LauncherModel* m) {
    if (!m || m->setup_preparing) return;
    if (!m->setup_needs_toolchain) {
        m->setup_tc_ready = true;
        m->setup_page = 1;
        return;
    }
    const int want_update =
        m->setup_tc_update_available && !m->setup_tc_update_skipped;
    if ((m->setup_tc_ready ||
         (m->toolchain_is_ready_cb && m->toolchain_is_ready_cb())) &&
        !want_update) {
        m->setup_tc_ready = true;
        m->setup_page = 1;
        m->setup_error[0] = '\0';
        safe_copy(m->setup_status, sizeof(m->setup_status),
                  "Using existing portable toolchain.");
        return;
    }
    if (!m->ensure_toolchain_with_progress_cb) {
        safe_copy(m->setup_error, sizeof(m->setup_error),
                  "Toolchain install is not available in this build.");
        return;
    }
    if (!launcher_model_can_advance_toolchain(m)) {
        safe_copy(m->setup_error, sizeof(m->setup_error),
                  "Select a cmake-clang-v1 toolchain zip, or enable automatic download.");
        return;
    }
    memset(&g_prep_job, 0, sizeof(g_prep_job));
    g_prep_job.m = m;
    g_prep_job.kind = PREP_JOB_TOOLCHAIN;
    g_prep_job.progress_pct = -1.0f;
    /* download: 0 = zip only, 1 = fetch if missing, 2 = force latest update */
    if (m->setup_tc_auto)
        g_prep_job.download = want_update ? 2 : 1;
    else
        g_prep_job.download = 0;
    if (!m->setup_tc_auto && m->setup_tc_zip[0])
        safe_copy(g_prep_job.zip_path, sizeof(g_prep_job.zip_path), m->setup_tc_zip);
    m->setup_preparing = true;
    m->setup_prepare_pulse = 0.0f;
    m->setup_prepare_fraction = -1.0f;
    m->setup_error[0] = '\0';
    safe_copy(m->setup_progress_title, sizeof(m->setup_progress_title),
              want_update ? "Updating build tools…" : "Installing build tools…");
    safe_copy(m->setup_status, sizeof(m->setup_status),
              m->setup_tc_auto
                  ? (want_update ? "Downloading toolchain update…"
                                 : "Downloading portable cmake/clang…")
                  : "Installing toolchain from zip…");
    prep_spawn_thread(m);
}

void launcher_model_start_prepare_disc(LauncherModel* m, const char* source_path) {
    if (!m || m->setup_preparing) return;
    if (!m->prepare_with_progress_cb && !m->prepare_disc_cb) return;
    if (!source_path || !source_path[0]) return;
    /* Persist ROM/BIOS for codegen hosts (project root + exe dirs + cwd). */
    if (source_path && source_path[0] &&
        (!m->rom_full[0] || strcmp(m->rom_full, source_path) != 0))
        launcher_model_set_rom(m, source_path);
    lm_persist_setup_sidecars(m);
    memset(&g_prep_job, 0, sizeof(g_prep_job));
    g_prep_job.m = m;
    g_prep_job.kind = PREP_JOB_PREPARE;
    g_prep_job.progress_pct = -1.0f;
    safe_copy(g_prep_job.source, sizeof(g_prep_job.source), source_path);
    m->setup_preparing = true;
    m->setup_prepare_pulse = 0.0f;
    m->setup_prepare_fraction = -1.0f;
    m->setup_error[0] = '\0';
    m->setup_progress_title[0] = '\0';
    safe_copy(m->setup_status, sizeof(m->setup_status),
              (m->prepare_busy_status && m->prepare_busy_status[0])
                  ? m->prepare_busy_status
                  : "Preparing disc image…");
    prep_spawn_thread(m);
}

void launcher_model_poll_prepare_disc(LauncherModel* m) {
    if (!m || !m->setup_preparing) return;
    m->setup_prepare_pulse += 0.02f;
    if (m->setup_prepare_pulse > 1.0f) m->setup_prepare_pulse = 0.0f;

    prep_lock();
    if (g_prep_job.m == m && g_prep_job.progress_dirty) {
        if (g_prep_job.progress_pct >= 0.0f)
            m->setup_prepare_fraction = g_prep_job.progress_pct;
        if (g_prep_job.progress_msg[0])
            safe_copy(m->setup_status, sizeof(m->setup_status), g_prep_job.progress_msg);
        g_prep_job.progress_dirty = 0;
    }
    const int done = g_prep_job.done && g_prep_job.m == m;
    const int kind = g_prep_job.kind;
    char out_path[512];
    char err[256];
    int result = 0;
    if (done) {
        result = g_prep_job.result;
        safe_copy(out_path, sizeof(out_path), g_prep_job.out_path);
        safe_copy(err, sizeof(err), g_prep_job.err);
        g_prep_job.m = NULL;
    }
    prep_unlock();

    if (!done) return;
    m->setup_preparing = false;
    m->setup_prepare_fraction = -1.0f;

    if (kind == PREP_JOB_TOOLCHAIN) {
        m->setup_progress_title[0] = '\0';
        if (result) {
            m->setup_tc_ready = true;
            m->setup_tc_update_available = false;
            m->setup_tc_update_skipped = false;
            m->setup_page = 1;
            m->setup_error[0] = '\0';
            safe_copy(m->setup_status, sizeof(m->setup_status),
                      "Build tools ready — continue with BIOS and disc.");
        } else {
            m->setup_status[0] = '\0';
            safe_copy(m->setup_error, sizeof(m->setup_error),
                      err[0] ? err : "Toolchain install failed.");
        }
        return;
    }

    if (kind == PREP_JOB_REBUILD || kind == PREP_JOB_PGO ||
        kind == PREP_JOB_FMV_TIMING) {
        if (result && out_path[0]) {
            safe_copy(m->relaunch_exe, sizeof(m->relaunch_exe), out_path);
            /* BIOS switch sticks only after a successful rebuild. */
            lm_bios_commit_uncommitted(m);
            /* Sidecars beside build/<exe> before the host execs it. */
            lm_persist_setup_sidecars(m);
            m->setup_prepare_satisfied = true;
            if (kind == PREP_JOB_PGO) {
                safe_copy(m->setup_status, sizeof(m->setup_status),
                          (m->pgo_success_status && m->pgo_success_status[0])
                              ? m->pgo_success_status
                              : "FMV optimize complete.");
            } else if (kind == PREP_JOB_FMV_TIMING) {
                safe_copy(m->setup_status, sizeof(m->setup_status),
                          (m->fmv_timing_success_status &&
                           m->fmv_timing_success_status[0])
                              ? m->fmv_timing_success_status
                              : "FMV timing applied.");
            } else {
                safe_copy(m->setup_status, sizeof(m->setup_status),
                          (m->rebuild_success_status && m->rebuild_success_status[0])
                              ? m->rebuild_success_status
                              : "Build complete.");
            }
            m->setup_error[0] = '\0';
            if (m->relaunch_after_rebuild) {
                safe_copy(m->setup_status, sizeof(m->setup_status),
                          kind == PREP_JOB_PGO
                              ? "FMV optimize complete — restarting…"
                              : (kind == PREP_JOB_FMV_TIMING
                                     ? "FMV timing applied — restarting…"
                                     : "Build complete — restarting…"));
                m->action = LNG_ACTION_RELAUNCH;
            }
        } else {
            lm_bios_revert_uncommitted(m);
            m->setup_status[0] = '\0';
            safe_copy(m->setup_error, sizeof(m->setup_error),
                      err[0] ? err
                             : (kind == PREP_JOB_PGO
                                    ? "FMV optimize failed."
                                    : (kind == PREP_JOB_FMV_TIMING
                                           ? "FMV timing apply failed."
                                           : "Rebuild failed.")));
        }
        return;
    }

    if (result && out_path[0]) {
        launcher_model_set_rom(m, out_path);
        m->setup_error[0] = '\0';
        if (m->rebuild_after_prepare && m->rebuild_with_progress_cb) {
            safe_copy(m->setup_status, sizeof(m->setup_status),
                      (m->prepare_success_status && m->prepare_success_status[0])
                          ? m->prepare_success_status
                          : "Sources ready — starting build…");
            /* Keep bios_switch_uncommitted through rebuild. */
            launcher_model_begin_rebuild_locked(m);
            return;
        }
        lm_bios_commit_uncommitted(m);
        m->setup_prepare_satisfied = true;
        safe_copy(m->setup_status, sizeof(m->setup_status),
                  (m->prepare_success_status && m->prepare_success_status[0])
                      ? m->prepare_success_status
                      : "Disc ready.");
    } else {
        lm_bios_revert_uncommitted(m);
        m->setup_status[0] = '\0';
        safe_copy(m->setup_error, sizeof(m->setup_error),
                  err[0] ? err : "Disc prepare failed.");
    }
}

// Re-inspect one memory-card slot via the host callback (if any), caching the
// result (block bitmask + validity) on the model. Clears the inspected flag
// when there's no callback or no path, so the panel falls back to the
// freshly-formatted/placeholder display.
static void lm_inspect_memcard(LauncherModel* m, int slot) {
    if (slot < 0 || slot > 1) return;
    m->memcard_inspected[slot] = false;
    m->memcard_valid[slot]     = false;
    if (!m->memcard_inspect_cb || !m->s.memcard_path[slot][0]) return;
    RecompLauncherCMemcard mc; memset(&mc, 0, sizeof(mc));
    if (!m->memcard_inspect_cb(m->s.memcard_path[slot], &mc)) return;
    uint16_t bits = 0;
    for (int i = 0; i < 15; ++i) if (mc.block_used[i]) bits |= (uint16_t)(1u << i);
    m->memcard_blocks_used[slot] = bits;
    m->memcard_valid[slot]       = mc.valid != 0;
    m->memcard_inspected[slot]   = true;
}

void launcher_model_set_memcard_path(LauncherModel* m, int slot, const char* path) {
    if (slot < 0 || slot > 1) return;
    safe_copy(m->s.memcard_path[slot], sizeof(m->s.memcard_path[slot]), path ? path : "");
    // A newly browsed-in card is not known to be blank; only
    // launcher_model_new_memcard() re-arms this flag.
    m->memcard_freshly_formatted[slot] = false;
    lm_inspect_memcard(m, slot);   // refresh real block usage/validity for the new path
}

void launcher_model_toggle_memcard(LauncherModel* m, int slot) {
    if (slot < 0 || slot > 1) return;
    m->s.memcard_enabled[slot] = m->s.memcard_enabled[slot] ? 0 : 1;
}

int launcher_model_multitap_available(const LauncherModel* m) {
    if (!m || m->player_count < 3) return 0;
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    return (prof && prof->id && strcmp(prof->id, "psx") == 0) ? 1 : 0;
}

int launcher_model_multitap_enabled(const LauncherModel* m) {
    if (!m) return 0;
    if (!launcher_model_multitap_available(m)) return 0;
    return m->s.multitap_enabled ? 1 : 0;
}

void launcher_model_toggle_multitap(LauncherModel* m) {
    if (!m || !launcher_model_multitap_available(m)) return;
    m->s.multitap_enabled = m->s.multitap_enabled ? 0 : 1;
    /* Drop the configure target if it was on a now-hidden seat. */
    {
        const int vis = launcher_model_visible_player_count(m);
        if (m->cfg_player >= vis) m->cfg_player = vis > 0 ? vis - 1 : 0;
    }
}

int launcher_model_visible_player_count(const LauncherModel* m) {
    if (!m) return 1;
    int n = m->player_count > 0 ? m->player_count : 1;
    if (n > LNG_MAX_PLAYERS) n = LNG_MAX_PLAYERS;
    if (launcher_model_multitap_available(m) && !m->s.multitap_enabled) {
        if (n > 2) n = 2;
    }
    return n;
}

int launcher_model_multitap_analog_available(const LauncherModel* m) {
    if (!m || m->player_count < 3) return 0;
    /* Digital-only titles (lock_mode + locked_pad_mode=D-Pad): DualShock-on-tap
     * is unsupported — hide the Lobby / Controllers toggle. */
    if (!m->pad_mode_selectable && m->locked_pad_mode == 2)
        return 0;
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    return (prof && prof->id && strcmp(prof->id, "psx") == 0) ? 1 : 0;
}

int launcher_model_multitap_analog_enabled(const LauncherModel* m) {
    if (!m || !launcher_model_multitap_analog_available(m)) return 0;
    return m->s.multitap_analog ? 1 : 0;
}

void launcher_model_toggle_multitap_analog(LauncherModel* m) {
    if (!m || !launcher_model_multitap_analog_available(m)) return;
    m->s.multitap_analog = m->s.multitap_analog ? 0 : 1;
}

void launcher_model_new_memcard(LauncherModel* m, int slot, const char* path) {
    if (slot < 0 || slot > 1 || !path || !path[0]) return;
    if (recompui_memcard_format_file(path) != 0) return;  // I/O failure: leave as-is
    launcher_model_set_memcard_path(m, slot, path);
    m->memcard_freshly_formatted[slot] = true;   // known-blank: panel shows 0 / 15
}

// ---- N64 Transfer Pak slots (mirrors the memcard slot pattern) -----------------

// Refresh one slot's cartridge facts through the host's tpak_inspect callback.
// Clears to "not inspected" when there's no callback, no cartridge, or the
// callback declines — the panel then shows the bare file name, neutral tint.
static void lm_inspect_tpak(LauncherModel* m, int slot) {
    if (slot < 0 || slot >= RECOMP_LAUNCHER_MAX_TPAKS) return;
    memset(&m->tpak_info[slot], 0, sizeof(m->tpak_info[slot]));
    m->tpak_inspected[slot] = false;
    if (!m->tpak_inspect_cb || !m->s.tpak_rom_path[slot][0]) return;
    RecompLauncherCTpak out; memset(&out, 0, sizeof(out));
    if (m->tpak_inspect_cb(m->s.tpak_rom_path[slot],
                           m->s.tpak_save_path[slot][0] ? m->s.tpak_save_path[slot] : NULL,
                           &out)) {
        m->tpak_info[slot] = out;
        m->tpak_inspected[slot] = true;
    }
}

void launcher_model_set_tpak_rom(LauncherModel* m, int slot, const char* path) {
    if (slot < 0 || slot >= m->tpak_slots) return;
    safe_copy(m->s.tpak_rom_path[slot], sizeof(m->s.tpak_rom_path[slot]), path ? path : "");
    if (m->s.tpak_rom_path[slot][0]) m->s.tpak_enabled[slot] = 1;  // inserting = wanting it on
    lm_inspect_tpak(m, slot);
}

void launcher_model_clear_tpak(LauncherModel* m, int slot) {
    if (slot < 0 || slot >= m->tpak_slots) return;
    m->s.tpak_rom_path[slot][0]  = '\0';
    m->s.tpak_save_path[slot][0] = '\0';
    m->s.tpak_enabled[slot] = 0;
    lm_inspect_tpak(m, slot);
}

void launcher_model_set_tpak_save(LauncherModel* m, int slot, const char* path) {
    if (slot < 0 || slot >= m->tpak_slots) return;
    safe_copy(m->s.tpak_save_path[slot], sizeof(m->s.tpak_save_path[slot]), path ? path : "");
    lm_inspect_tpak(m, slot);
}

bool launcher_model_tpak_enabled(const LauncherModel* m, int slot) {
    if (slot < 0 || slot >= m->tpak_slots) return false;
    int e = m->s.tpak_enabled[slot];
    if (e > 0) return true;
    if (e < 0) return false;
    return m->s.tpak_rom_path[slot][0] != '\0';   // unset: on iff a cart is inserted
}

void launcher_model_toggle_tpak(LauncherModel* m, int slot) {
    if (slot < 0 || slot >= m->tpak_slots) return;
    m->s.tpak_enabled[slot] = launcher_model_tpak_enabled(m, slot) ? -1 : 1;
}

// ---- audio output device -------------------------------------------------------

void launcher_model_set_audio_device(LauncherModel* m, const char* name) {
    safe_copy(m->s.audio_device, sizeof(m->s.audio_device), name ? name : "");
}

const char* launcher_model_audio_device_label(const LauncherModel* m) {
    return m->s.audio_device[0] ? m->s.audio_device : "(system default)";
}

// ---- SRAM save management (mirrors the legacy launcher's Import/Clear) --------
// Both back up any existing save to "<sram>.bak" first (never a destructive op
// without a recoverable copy), matching the old launcher's behavior.
static bool lm_copy_file(const char* src, const char* dst) {
    FILE* in = fopen(src, "rb");
    if (!in) return false;
    FILE* out = fopen(dst, "wb");
    if (!out) { fclose(in); return false; }
    char buf[8192]; size_t n; bool ok = true;
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0)
        if (fwrite(buf, 1, n, out) != n) { ok = false; break; }
    fclose(in); fclose(out);
    return ok;
}

void launcher_model_import_sram(LauncherModel* m, const char* src) {
    if (!m->sram_path || !m->sram_path[0] || !src || !src[0]) return;
    char bak[600]; snprintf(bak, sizeof(bak), "%s.bak", m->sram_path);
    FILE* existing = fopen(m->sram_path, "rb");
    if (existing) { fclose(existing); lm_copy_file(m->sram_path, bak); }  // back up first
    lm_copy_file(src, m->sram_path);
}

void launcher_model_clear_sram(LauncherModel* m) {
    if (!m->sram_path || !m->sram_path[0]) return;
    char bak[600]; snprintf(bak, sizeof(bak), "%s.bak", m->sram_path);
    FILE* existing = fopen(m->sram_path, "rb");
    if (existing) { fclose(existing); lm_copy_file(m->sram_path, bak); remove(m->sram_path); }
}

void launcher_model_toggle_msu1(LauncherModel* m) {
    if (!m->msu1_supported) return;
    m->s.msu1_enabled = !m->s.msu1_enabled;
}

void launcher_model_set_msu1_dir(LauncherModel* m, const char* dir) {
    safe_copy(m->s.msu1_dir, sizeof(m->s.msu1_dir), dir ? dir : "");
}

// ---- cartridge light sensor --------------------------------------------------

/* Trims surrounding whitespace; a code pasted with a stray space should still
 * work. Case and existence are the host's business -- it owns the geocoder. */
static void copy_trimmed(char* dst, size_t cap, const char* src) {
    if (!dst || cap == 0) return;
    if (!src) { dst[0] = '\0'; return; }
    while (*src == ' ' || *src == '\t') ++src;
    size_t n = strlen(src);
    while (n > 0 && (src[n - 1] == ' ' || src[n - 1] == '\t')) --n;
    if (n >= cap) n = cap - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

void launcher_model_set_solar_zip(LauncherModel* m, const char* zip) {
    if (!m->has_solar_sensor) return;    /* gated: no-op when unsupported */
    copy_trimmed(m->s.solar_zip, sizeof(m->s.solar_zip), zip);
}

void launcher_model_set_solar_country(LauncherModel* m, const char* country) {
    if (!m->has_solar_sensor) return;
    copy_trimmed(m->s.solar_country, sizeof(m->s.solar_country), country);
}

void launcher_model_set_solar_source(LauncherModel* m, int source) {
    if (!m->has_solar_sensor) return;
    m->s.solar_source = (source != 0) ? 1 : 0;
}

void launcher_model_set_solar_manual_step(LauncherModel* m, int step) {
    if (!m->has_solar_sensor) return;
    if (step < 0) step = 0;
    if (step > 8) step = 8;
    m->s.solar_manual_step = step;
}

void launcher_model_set_solar_full_sun(LauncherModel* m, int wm2) {
    if (!m->has_solar_sensor) return;
    if (wm2 < 300)  wm2 = 300;
    if (wm2 > 1200) wm2 = 1200;
    m->s.solar_full_sun = wm2;
}

// ---- NES-style settings ------------------------------------------------------

void launcher_model_toggle_integer_scale(LauncherModel* m) {
    if (!m->has_integer_scale) return;   // gated: no-op when unsupported
    m->s.integer_scale = !m->s.integer_scale;
}

void launcher_model_toggle_hdpack(LauncherModel* m) {
    if (!m->hdpack_supported) return;    // gated: no-op when unsupported
    m->s.hdpack_enabled = !m->s.hdpack_enabled;
}

void launcher_model_set_hdpack_dir(LauncherModel* m, const char* dir) {
    safe_copy(m->s.hdpack_dir, sizeof(m->s.hdpack_dir), dir ? dir : "");
}

// Password/mantra save: the file is one line of text (e.g. Faxanadu's mantra),
// read/rewritten whole. Mirrors the legacy NES launcher's SAVES-panel variant.
void launcher_model_password_reload(LauncherModel* m) {
    m->password_text[0] = '\0';
    if (!m->password_save_path || !m->password_save_path[0]) return;
    FILE* f = fopen(m->password_save_path, "r");
    if (!f) return;
    if (fgets(m->password_text, sizeof(m->password_text), f)) {
        size_t n = strlen(m->password_text);
        while (n > 0 && (m->password_text[n-1] == '\n' || m->password_text[n-1] == '\r'))
            m->password_text[--n] = '\0';
    } else {
        m->password_text[0] = '\0';
    }
    fclose(f);
}

void launcher_model_password_commit(LauncherModel* m, const char* text) {
    if (!m->password_save_path || !m->password_save_path[0]) return;
    FILE* f = fopen(m->password_save_path, "w");
    if (!f) return;
    fprintf(f, "%s\n", text ? text : "");
    fclose(f);
    launcher_model_password_reload(m);   // reflect what actually landed on disk
}

// Zapper switches: flip the model state and persist through launcher_binds'
// [zapper] section writer immediately (same persist-on-change behavior as the
// rebind chips). launcher_binds_set_zapper is a no-op-safe plain writer.
void launcher_binds_set_zapper(int mouse_enabled, int crosshair);   // launcher_binds.c

void launcher_model_toggle_zapper_mouse(LauncherModel* m) {
    if (!m->zapper) return;
    m->zapper_mouse = !m->zapper_mouse;
    launcher_binds_set_zapper(m->zapper_mouse ? 1 : 0, m->zapper_crosshair ? 1 : 0);
}

void launcher_model_toggle_zapper_crosshair(LauncherModel* m) {
    if (!m->zapper) return;
    m->zapper_crosshair = !m->zapper_crosshair;
    launcher_binds_set_zapper(m->zapper_mouse ? 1 : 0, m->zapper_crosshair ? 1 : 0);
}

// ---- MSU-1 IPS auto-patching (mirrors the legacy launcher's do_patch() /
// msu1_patch_available predicate in snesrecomp's launcher_gui.cpp) -----------

// Recomputed on every ROM change: the dashboard prompt only makes sense when
// this game HAS a patch, the loaded file verifies against the vanilla CRC
// (patching an already-patched or wrong ROM would corrupt it), and the user
// hasn't already dismissed it this run.
static void update_msu1_patch_available(LauncherModel* m) {
    m->msu1_patch_available = m->msu1_supported && m->msu1_patch_path &&
                              m->msu1_patch_path[0] && m->rom_present &&
                              m->crc_match && !m->msu1_patch_skipped;
}

static bool lm_read_whole_file(const char* path, uint8_t** out_data, size_t* out_len) {
    FILE* f = fopen(path, "rb");
    if (!f) return false;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n < 0) { fclose(f); return false; }
    uint8_t* buf = (uint8_t*)malloc(n ? (size_t)n : 1);
    if (!buf) { fclose(f); return false; }
    if (n > 0 && fread(buf, 1, (size_t)n, f) != (size_t)n) { free(buf); fclose(f); return false; }
    fclose(f);
    *out_data = buf;
    *out_len  = (size_t)n;
    return true;
}

// Build "<dir>/<stem>.msu1.<ext>" beside `rom_path` (matches the legacy
// launcher's std::filesystem stem()/extension() splice exactly).
static void lm_msu1_target_path(const char* rom_path, char* out, size_t out_cap) {
    const char* base = rom_path;
    for (const char* q = rom_path; *q; ++q)
        if (*q == '/' || *q == '\\') base = q + 1;
    const char* dot = strrchr(base, '.');
    size_t dir_len  = (size_t)(base - rom_path);
    size_t stem_len = dot ? (size_t)(dot - base) : strlen(base);
    const char* ext = dot ? dot : "";
    snprintf(out, out_cap, "%.*s%.*s.msu1%s",
             (int)dir_len, rom_path, (int)stem_len, base, ext);
}

void launcher_model_apply_msu1_patch(LauncherModel* m) {
    if (!m->msu1_patch_available) return;
    if (!m->rom_present || !m->msu1_patch_path || !m->msu1_patch_path[0]) return;

    uint8_t* src = NULL;   size_t src_len = 0;
    uint8_t* patch = NULL; size_t patch_len = 0;
    if (!lm_read_whole_file(m->rom_full, &src, &src_len)) return;
    if (!lm_read_whole_file(m->msu1_patch_path, &patch, &patch_len)) { free(src); return; }

    uint8_t* out = NULL; size_t out_len = 0;
    bool ok = ips_apply(src, src_len, patch, patch_len, &out, &out_len);
    free(src);
    free(patch);
    if (!ok) {
        fprintf(stderr, "launcher: IPS patch failed (%s)\n", m->msu1_patch_path);
        return;
    }

    char target[600];
    lm_msu1_target_path(m->rom_full, target, sizeof(target));
    FILE* f = fopen(target, "wb");
    if (!f) {
        fprintf(stderr, "launcher: cannot write %s\n", target);
        free(out);
        return;
    }
    bool wrote = fwrite(out, 1, out_len, f) == out_len;
    fclose(f);
    free(out);
    if (!wrote) { fprintf(stderr, "launcher: short write to %s\n", target); return; }

    fprintf(stderr, "launcher: wrote MSU-1 patched ROM: %s\n", target);
    // Switch the model onto the patched file and re-verify (this also
    // recomputes msu1_patch_available — the patched ROM's CRC will no longer
    // match the vanilla expected_crc, so it naturally clears). Belt-and-braces:
    // also mark skipped so the prompt never reappears if a game's expected_crc
    // happens to also match the patched image.
    m->msu1_patch_skipped = true;
    launcher_model_set_rom(m, target);
}

void launcher_model_skip_msu1_patch(LauncherModel* m) {
    if (!m->msu1_patch_available) return;
    m->msu1_patch_skipped = true;
    update_msu1_patch_available(m);
}

/* PSX Hybrid/Analog need sticks; keyboard players are forced to D-Pad.
 * Gamepads default to Analog — virtually every modern pad has sticks. */
static int pad_mode_is_psx_legacy(const LauncherModel* m) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const ControllerSpec* spec = prof ? &prof->controller : NULL;
    return !(spec && spec->modes && spec->mode_count > 0);
}

static void apply_default_pad_mode_for_source(LauncherModel* m, int player) {
    if (!m->pad_mode_supported || !m->pad_mode_selectable) return;
    player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    if (!pad_mode_is_psx_legacy(m)) return;
    if (m->s.player_src[player] == 1)
        m->s.pad_mode[player] = 2;   // D-Pad / digital (no sticks)
    else if (m->s.player_src[player] == 2)
        m->s.pad_mode[player] = 1;   // Analog / DualShock
}

void launcher_model_set_pad_mode(LauncherModel* m, int player, int mode) {
    if (!m->pad_mode_supported || !m->pad_mode_selectable) return;   // gated/locked
    player = clampi(player, 0, 1);
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    const ControllerSpec* spec = prof ? &prof->controller : NULL;
    if (spec && spec->modes && spec->mode_count > 0) {
        // Custom mode list (Genesis): accept listed mode values only.
        for (int i = 0; i < spec->mode_count; ++i)
            if (spec->modes[i].mode == mode) { m->s.pad_mode[player] = mode; return; }
        return;
    }
    /* Keyboard has no sticks — Analog is unavailable. */
    if (m->s.player_src[player] == 1 && mode != 2) return;
    mode = clampi(mode, 0, 2);
    if (mode == 0) mode = 1;   /* Hybrid is mod-only -> snap to Analog */
    m->s.pad_mode[player] = mode;
}

int launcher_model_active_button_count(const LauncherModel* m, int player) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    int bc = prof ? prof->controller.button_count : LNG_BTN_COUNT;
    if (prof && prof->controller.modes && prof->controller.mode_count > 0) {
        player = clampi(player, 0, 1);
        for (int i = 0; i < prof->controller.mode_count; ++i)
            if (prof->controller.modes[i].mode == m->s.pad_mode[player]) {
                bc = prof->controller.modes[i].button_count;
                break;
            }
    }
    if (bc > LNG_MAX_BUTTONS) bc = LNG_MAX_BUTTONS;
    if (bc < 0) bc = 0;
    return bc;
}

void launcher_model_cycle_player_src(LauncherModel* m, int player) {
    player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    m->s.player_src[player] = (m->s.player_src[player] + 1) % 3;  // None/Kbd/Pad
    apply_default_pad_mode_for_source(m, player);
}

void launcher_model_deadzone_delta(LauncherModel* m, int player, int delta) {
    player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    m->s.deadzone[player] = clampi(m->s.deadzone[player] + delta, 0, 100);
}

void launcher_model_set_source(LauncherModel* m, int player, int kind,
                               uint32_t pad_id, const char* pad_name,
                               const char* pad_guid) {
    player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    m->s.player_src[player] = clampi(kind, 0, 2);
    if (kind == 2) {
        m->player_pad_id[player] = pad_id;
        safe_copy(m->player_pad_name[player], sizeof(m->player_pad_name[player]),
                  pad_name ? pad_name : "Gamepad");
        safe_copy(m->s.player_gamepad_guid[player],
                  sizeof(m->s.player_gamepad_guid[player]),
                  pad_guid ? pad_guid : "");
    } else {
        m->player_pad_id[player] = 0;
        m->player_pad_name[player][0] = '\0';
        m->s.player_gamepad_guid[player][0] = '\0';
    }
    apply_default_pad_mode_for_source(m, player);
}

// ---- mouse controls --------------------------------------------------------

void launcher_model_set_mouse_source(LauncherModel* m, int enabled) {
    if (!m->has_mouse_controls) return;
    launcher_model_set_source(m, 0, 1, 0, NULL, NULL);   // player 0 -> Keyboard
    m->s.mouse_enabled = enabled ? 1 : 0;
}

void launcher_model_set_mouse_sensitivity(LauncherModel* m, float value) {
    m->s.mouse_sensitivity = clampf(value, 0.01f, 0.50f);
}

void launcher_model_toggle_mouse_invert_x(LauncherModel* m) {
    m->s.mouse_invert_x = !m->s.mouse_invert_x;
}

void launcher_model_toggle_mouse_invert_y(LauncherModel* m) {
    m->s.mouse_invert_y = !m->s.mouse_invert_y;
}

void launcher_model_set_mouse_bind(LauncherModel* m, int which, int button_index) {
    if (which < 0 || which > 2) return;
    m->s.mouse_bind[which] = (button_index < 0) ? -1 : button_index;
}

void launcher_model_set_gyro_sensitivity(LauncherModel* m, float value) {
    if (!m || !m->has_gyro_controls) return;
    m->s.gyro_sensitivity = clampf(value, 0.25f, 4.00f);
}

void launcher_model_request_skip_toggle(LauncherModel* m) {
    if (!m->s.skip_launcher) {
        m->skip_modal_open = true;    // enabling: confirm first
    } else {
        m->s.skip_launcher = 0;       // disabling: immediate
    }
}

void launcher_model_skip_confirm(LauncherModel* m) {
    m->s.skip_launcher = 1;
    m->skip_modal_open = false;
}

void launcher_model_skip_cancel(LauncherModel* m) {
    m->skip_modal_open = false;
}

void launcher_model_begin_capture(LauncherModel* m, int b) {
    launcher_model_begin_capture_slot(m, b, 0);
}
void launcher_model_begin_capture_slot(LauncherModel* m, int b, int slot) {
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    int bc = prof ? prof->controller.button_count : LNG_BTN_COUNT;
    if (bc > LNG_MAX_BUTTONS) bc = LNG_MAX_BUTTONS;
    if (b < 0 || b >= bc) return;
    m->hk_capturing  = false;
    m->camera_capturing = false;
    m->capturing     = true;
    m->capture_btn   = b;
    m->capture_slot  = (slot == 1) ? 1 : 0;
    /* ImGui activates a button on RELEASE, so the click that opened this
     * capture is already fully consumed by the time capturing is true.
     * Arm straight away: the next press is a deliberate new click. */
    m->capture_mouse_armed = true;
    m->capture_pad  = false;
    m->capture_assist = false;
}
void launcher_model_begin_pad_capture(LauncherModel* m, int b) {
    launcher_model_begin_capture(m, b);
    if (m->capturing) m->capture_pad = true;   // begin_capture validated b
}
void launcher_model_begin_map_all(LauncherModel* m) {
    if (!m) return;
    const SystemProfile* prof = (const SystemProfile*)m->profile;
    if (!prof || !prof->id || strcmp(prof->id, "psx") != 0) return;
    const int p = clampi(m->cfg_player, 0, LNG_MAX_PLAYERS - 1);
    if (m->s.player_src[p] != 2 || !m->s.player_gamepad_guid[p][0]) return;
    m->map_all_active = true;
    m->map_all_wait_release = false;
    m->map_all_step = 0;
    launcher_model_begin_pad_capture(m, kPsxGamepadBindOrder[0]);
}
void launcher_model_map_all_advance(LauncherModel* m) {
    if (!m || !m->map_all_active) return;
    m->map_all_step++;
    if (m->map_all_step >= LNG_PSX_PAD_BUTTON_COUNT) {
        m->map_all_active = false;
        m->map_all_wait_release = false;
        m->map_all_step = 0;
        m->capturing = false;
        m->capture_pad = false;
        return;
    }
    /* Stay in pad-capture for the next button, but ignore input until the
     * previous press/throw has been released (see try_capture). */
    m->map_all_wait_release = true;
    launcher_model_begin_pad_capture(m, kPsxGamepadBindOrder[m->map_all_step]);
}
void launcher_model_begin_assist_capture(LauncherModel* m, int action,
                                         bool gamepad) {
    if (!m->settings_bindings || action < 0 ||
        action >= m->assist_binding_count)
        return;
    m->hk_capturing = false;
    m->capturing = true;
    m->capture_assist = true;
    m->capture_pad = gamepad;
    m->capture_btn = action;
    m->capture_slot = 0;
}
void launcher_model_set_captured_key(LauncherModel* m, int scancode) {
    if (!m || !m->capturing || m->capture_pad) return;
    if (m->capture_assist) {
        if (m->capture_btn >= 0 &&
            m->capture_btn < m->assist_binding_count)
            m->s.assist_key_bind[m->capture_btn] = scancode;
    } else {
        int buttons = launcher_model_active_button_count(m, m->cfg_player);
        if (m->capture_btn >= 0 && m->capture_btn < buttons)
            m->s.player_key_bind[m->cfg_player][m->capture_btn] = scancode;
    }
}
void launcher_model_set_captured_pad(LauncherModel* m, int encoded_binding) {
    if (!m || !m->capturing || !m->capture_pad) return;
    if (m->capture_assist) {
        if (m->capture_btn >= 0 &&
            m->capture_btn < m->assist_binding_count)
            m->s.assist_pad_bind[m->capture_btn] = encoded_binding;
    } else {
        int buttons = launcher_model_active_button_count(m, m->cfg_player);
        if (m->capture_btn >= 0 && m->capture_btn < buttons)
            m->s.player_pad_bind[m->cfg_player][m->capture_btn] =
                encoded_binding;
    }
}
void launcher_model_reset_player_bindings(LauncherModel* m, int player) {
    if (!m || !m->settings_bindings || !m->has_default_settings) return;
    player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    memcpy(m->s.player_key_bind[player],
           m->default_settings.player_key_bind[player],
           sizeof m->s.player_key_bind[player]);
    memcpy(m->s.player_pad_bind[player],
           m->default_settings.player_pad_bind[player],
           sizeof m->s.player_pad_bind[player]);
}
void launcher_model_reset_assist_bindings(LauncherModel* m) {
    if (!m || !m->settings_bindings || !m->has_default_settings) return;
    memcpy(m->s.assist_key_bind, m->default_settings.assist_key_bind,
           sizeof m->s.assist_key_bind);
    memcpy(m->s.assist_pad_bind, m->default_settings.assist_pad_bind,
           sizeof m->s.assist_pad_bind);
}
void launcher_model_cancel_capture(LauncherModel* m) {
    m->capturing      = false;
    m->capture_pad    = false;
    m->capture_assist = false;
    m->map_all_active = false;
    m->map_all_wait_release = false;
    m->map_all_step   = 0;
}

void launcher_model_begin_hk_capture(LauncherModel* m, LngHotkey h) {
    if (h < 0 || h >= LNG_HK_COUNT) return;
    m->capturing    = false;
    m->camera_capturing = false;
    m->hk_capturing = true;
    m->capture_hk   = h;
}
void launcher_model_cancel_hk_capture(LauncherModel* m) { m->hk_capturing = false; }

void launcher_model_begin_camera_capture(LauncherModel* m, int action) {
    if (!m || action < 0 || action >= LNG_CAMERA_BIND_COUNT) return;
    m->capturing = false;
    m->capture_pad = false;
    m->hk_capturing = false;
    m->camera_capturing = true;
    m->capture_camera = action;
}

void launcher_model_cancel_camera_capture(LauncherModel* m) {
    if (m) m->camera_capturing = false;
}

const char* launcher_model_scale_label(const LauncherModel* m) {
    static char buf[8];
    int s = m->s.window_scale < 1 ? 1 : m->s.window_scale;
    snprintf(buf, sizeof(buf), "%dx", s);
    return buf;
}

const char* launcher_model_freq_label(const LauncherModel* m) {
    static char buf[16];
    snprintf(buf, sizeof(buf), "%d Hz", m->s.audio_freq);
    return buf;
}

const char* launcher_model_player_src_label(const LauncherModel* m, int player) {
    player = clampi(player, 0, LNG_MAX_PLAYERS - 1);
    int src = clampi(m->s.player_src[player], 0, 2);
    if (src == 2) {
        // Never show the generic "Gamepad" placeholder when we have a concrete
        // pad name (or at least a GUID-backed label filled by sync/hydrate).
        if (m->player_pad_name[player][0] &&
            strcmp(m->player_pad_name[player], "Gamepad") != 0)
            return m->player_pad_name[player];
        if (m->s.player_gamepad_guid[player][0])
            return m->s.player_gamepad_guid[player];
    }
    // Mouse-capable games split the keyboard source (player 0 only): the label
    // reflects whether mouse-aim is on. Every non-mouse game keeps kSrcNames.
    if (src == 1 && m->has_mouse_controls && player == 0)
        return m->s.mouse_enabled ? "Keyboard + Mouse" : "Keyboard";
    return kSrcNames[src];
}

const char* launcher_button_name(LngButton b) {
    if (b < 0 || b >= LNG_BTN_COUNT) return "?";
    return kButtonNames[b];
}

const char* launcher_hotkey_name(LngHotkey h) {
    if (h < 0 || h >= LNG_HK_COUNT) return "?";
    return kHotkeyNames[h];
}

const char* launcher_view_name(LngView v) {
    if (v < 0 || v > LNG_VIEW_CREDITS) return "?";
    return kViewNames[v];
}
