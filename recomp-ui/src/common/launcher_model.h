// launcher_model.h — game-agnostic view-model for the next-gen launcher.
//
// This is the DRY heart of the new launcher: it owns all launcher STATE and
// BEHAVIOR (which panels exist, what a control does, how a rebind is captured)
// and is completely free of any UI toolkit, SDL, or OpenGL. Both prototype
// render backends (Dear ImGui and Clay) draw this same model and call the same
// mutators, so behavior is identical across backends and — because it is built
// purely from the existing C ABI structs (RecompLauncherCSettings /
// RecompLauncherCGameInfo) — identical across every game in the ecosystem.
//
// The surface mirrors the shipping legacy MMX launcher so the
// prototype is a faithful parity check of what we offer the end user:
//   Dashboard  : game/ROM info + CRC/SHA badges + Change ROM + controllers
//   Settings   : window scale, linear filter, sample rate, volume, hotkeys
//   Controller : input source, deadzone, keyboard rebinds
//   Footer     : Skip-on-Boot (+confirm modal), Settings/Back, PLAY
// Per-game gating (widescreen/MSU-1/saves) hides panels exactly as today.

#ifndef LAUNCHER_NG_MODEL_H
#define LAUNCHER_NG_MODEL_H

#include "recomp_launcher.h"   // RecompLauncherCSettings, RecompLauncherCGameInfo

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LNG_NETPLAY_MAX_LOCAL_ADDRESSES 8

#ifdef __cplusplus
extern "C" {
#endif

// Opaque forward decl: the model carries a pointer to its inferred
// SystemProfile (launcher_system.h) so panels can read per-system specs
// (pad art, save kind, hotkeys mask, panel composition) without every TU that
// touches LauncherModel needing the full SystemProfile definition.
struct SystemProfile;

typedef enum {
    LNG_VIEW_DASHBOARD = 0,
    LNG_VIEW_SETTINGS,
    LNG_VIEW_CONTROLLER,
    LNG_VIEW_NETPLAY,
    LNG_VIEW_MODS,
    LNG_VIEW_ASSIST_TOOLS,
    LNG_VIEW_CREDITS,
} LngView;

typedef enum {
    LNG_ACTION_NONE = 0,   // still running
    LNG_ACTION_LAUNCH,     // boot the game with committed settings
    LNG_ACTION_QUIT,       // user quit
    LNG_ACTION_RELAUNCH    // quit + host should exec rebuilt binary
} LngAction;

// Representative subset of the SNES pad for the rebind UI. This enum is the
// SNES-specific naming still used for keybinds.ini's engine-side defaults
// (kP1Defaults/kButtonNames in launcher_model.c, kKbIndexSnes in
// launcher_binds.c) — indices 0..11 are byte-identical to before this enum
// was joined by per-system rebind vocab. The rebind PAGE itself no longer
// walks this enum: it walks the active SystemProfile's ControllerSpec.buttons
// (launcher_system.h), addressing buttons by a generic 0..button_count-1
// index (see LNG_MAX_BUTTONS) so non-SNES systems (PSX: 16 buttons) render
// their own vocabulary instead of this SNES catalog.
typedef enum {
    LNG_BTN_UP = 0, LNG_BTN_DOWN, LNG_BTN_LEFT, LNG_BTN_RIGHT,
    LNG_BTN_A, LNG_BTN_B, LNG_BTN_X, LNG_BTN_Y,
    LNG_BTN_L, LNG_BTN_R, LNG_BTN_START, LNG_BTN_SELECT,
    LNG_BTN_COUNT
} LngButton;

// Upper bound on a SystemProfile's ControllerSpec.button_count — sizes the
// generic per-player bind-label storage below. SNES uses 12 (LNG_BTN_COUNT),
// PSX uses 24 (LNG_PSX_PAD_BUTTON_COUNT, launcher_system.h: 16 physical
// DualShock inputs + 8 keyboard->analog-stick direction binds); this leaves
// headroom for future systems without another struct-layout change.
#define LNG_MAX_BUTTONS 24

// Upper bound on a SystemProfile's ControllerSpec.max_players — sizes the
// per-player state below. Mirrors RECOMP_LAUNCHER_MAX_PLAYERS (the ABI
// player-array width, recomp_launcher.h): N64 exposes 4 controller ports.
#define LNG_MAX_PLAYERS RECOMP_LAUNCHER_MAX_PLAYERS

// System hotkeys — mirrors the engine's config.ini [KeyMap] keys exactly, so
// editing them here surgically rewrites the same lines config.c parses.
typedef enum {
    LNG_HK_FULLSCREEN = 0, LNG_HK_RESET, LNG_HK_PAUSE, LNG_HK_PAUSE_DIMMED,
    LNG_HK_TURBO, LNG_HK_WINDOW_BIGGER, LNG_HK_WINDOW_SMALLER,
    LNG_HK_VOLUME_UP, LNG_HK_VOLUME_DOWN, LNG_HK_DISPLAY_PERF, LNG_HK_TOGGLE_RENDERER,
    LNG_HK_SOLAR_BRIGHTER, LNG_HK_SOLAR_DIMMER, LNG_HK_SOLAR_LIVE,
    LNG_HK_COUNT
} LngHotkey;

enum {
    LNG_CAMERA_LOOK_UP = 0,
    LNG_CAMERA_LOOK_DOWN,
    LNG_CAMERA_LOOK_LEFT,
    LNG_CAMERA_LOOK_RIGHT,
    LNG_CAMERA_ROLL_LEFT,
    LNG_CAMERA_ROLL_RIGHT,
    LNG_CAMERA_ZOOM_IN,
    LNG_CAMERA_ZOOM_OUT,
    LNG_CAMERA_SPRITE_SMALLER,
    LNG_CAMERA_SPRITE_LARGER,
    LNG_CAMERA_RESET,
    LNG_CAMERA_TOGGLE,
    LNG_CAMERA_BIND_COUNT
};

// Disc-verdict result (SystemProfile.verify.mode == 1 systems, e.g. PSX).
// Populated by the profile's VerifyProbeFn (launcher_system.h) — or
// synthesized from available facts when the probe is NULL — every time the
// ROM/disc path changes (see launcher_model_set_rom() in launcher_model.c).
// Kept intentionally minimal: just enough for the checklist UI (Serial /
// Region / ISO header) plus one overall verdict panels key their icon on.
typedef struct {
    char serial[16];   // e.g. "SCUS-94423"; "" => unknown/unread
    char region[8];    // e.g. "NTSC-U"; "" => unknown/unread
    bool iso_ok;        // ISO9660/system header sanity check passed
    int  verdict;       // 0 none, 1 ok, 2 warn, 3 bad
    int  track_count;   // mounted TOC track count (0 if unknown)
    int  netplay_ok;    // 1 = OK for online; 0 = TOC/cue policy failed
    char disc_fp[65];   // TOC fingerprint for lobby peer matching
    char netplay_detail[160];
} VerifyResult;

typedef struct {
    // ---- static game facts (borrowed from RecompLauncherCGameInfo) ----
    const char* game_name;          // e.g. "Mega Man X"
    const char* region;             // e.g. "USA"
    const char* platform;           // console subtitle, e.g. "PLAYSTATION" (NULL => none)
    bool        widescreen_supported;
    bool        msu1_supported;      // sram-like: show the MSU-1 module when true
    const char* msu1_note;           // borrowed; which patch, shown in the card
    // ---- MSU-1 IPS auto-patching (dashboard "Patch ROM"/"Skip" flow) ----
    // Borrowed IPS file path; NULL => this game has no auto-patch (msu1_note-only
    // games still show the Settings->Audio MSU-1 toggle, just no dashboard prompt).
    const char* msu1_patch_path;
    // Computed each time the ROM changes (launcher_model_set_rom): true iff
    // msu1_supported && msu1_patch_path && the loaded ROM verifies against the
    // game's vanilla CRC && the user hasn't dismissed the prompt this session.
    // Mirrors the legacy launcher's `msu1_patch_available` predicate exactly.
    bool        msu1_patch_available;
    bool        msu1_patch_skipped;  // session-only "Play Unpatched" dismissal
    bool        saves_supported;     // sram_path != NULL -> show the SAVES panel
    const char* sram_path;           // borrowed; NULL when the game has no SRAM

    // ---- NES-style capabilities (borrowed from RecompLauncherCGameInfo) ----
    bool        has_solar_sensor;    // Solar sensor panel in Settings
    bool        has_integer_scale;   // Integer-scale checkbox in Display settings
    bool        hdpack_supported;    // HD-texture-pack toggle + folder picker
    // Password/mantra save (e.g. Faxanadu): non-NULL path swaps the SAVES row
    // for a password-text UI (read + edit-with-confirm of a 1-line file).
    const char* password_save_path;
    const char* password_save_label; // e.g. "Password" / "Mantra"; NULL => "Password"
    char        password_text[128];  // current file contents (reloaded on init/commit)
    // Light-gun (NES Zapper) game: controller pages add a Zapper block whose
    // two switches persist to the engine's keybinds.ini [zapper] section via
    // launcher_binds (surgical writes — the rest of the file is preserved).
    bool        zapper;
    bool        zapper_mouse;        // mouse acts as the light gun
    bool        zapper_crosshair;    // draw a crosshair at the aim point

    // ---- PSX memory-card block usage (SAVE_MEMCARD; see launcher_system.h) ----
    // Per-slot bitmask over the 15 PS1 card blocks (bit i = block i occupied).
    // Populated by a SystemProfile's SaveSpec.probe hook (SaveProbeFn) once a
    // host wires one up; left zeroed/unused while probe is NULL (every profile
    // today), in which case the Save panel renders a representative placeholder
    // grid instead of reading this field.
    uint16_t    memcard_blocks_used[2];
    // Set true by launcher_model_new_memcard() right after it formats+adopts
    // a blank card for that slot, cleared as soon as the slot's path changes
    // again (browse-in, or the model is re-initialized). While no real
    // SaveProbeFn is wired (memcard_blocks_used stays unpopulated), this lets
    // the panel show "0 / 15 blocks" for a card it just knows is blank,
    // instead of falling back to the representative placeholder count.
    bool        memcard_freshly_formatted[2];
    bool        memcard_valid[2];      // last inspect: image is a valid 128KB "MC" card
    bool        memcard_inspected[2];  // a host memcard_inspect callback populated blocks/valid

    // ---- host verification/inspection callbacks (borrowed from GameInfo) ----
    // When non-NULL these drive the REAL disc verdict + memcard block usage
    // (re-run on every disc/card change) instead of the placeholder synthesis.
    int (*disc_verify_cb)(const char* disc_path, RecompLauncherCDiscVerify* out);
    int (*memcard_inspect_cb)(const char* card_path, RecompLauncherCMemcard* out);
    int (*bios_verify_cb)(const char* bios_path, RecompLauncherCBiosVerify* out);
    /* Optional host flush for first-run picks (project-root bios.cfg / disc.cfg). */
    int (*persist_setup_cb)(void* ctx, const char* rom_path, const char* bios_path);
    void*       persist_setup_ctx;
    int (*prepare_disc_cb)(const char* source_path, char* out_disc_path, size_t out_cap,
                           char* err_msg, size_t err_cap);
    int (*prepare_with_progress_cb)(const char* source_path,
                                    char* out_path, size_t out_cap,
                                    char* err_msg, size_t err_cap,
                                    RecompLauncherCPrepareProgressFn on_progress,
                                    void* progress_ctx);
    int (*rebuild_with_progress_cb)(const char* rom_path,
                                    char* out_exe_path, size_t out_cap,
                                    char* err_msg, size_t err_cap,
                                    RecompLauncherCPrepareProgressFn on_progress,
                                    void* progress_ctx);
    int (*pgo_optimize_with_progress_cb)(const char* rom_path,
                                         char* out_exe_path, size_t out_cap,
                                         char* err_msg, size_t err_cap,
                                         RecompLauncherCPrepareProgressFn on_progress,
                                         void* progress_ctx);
    int (*fmv_timing_optimize_with_progress_cb)(const char* rom_path,
                                                char* out_exe_path, size_t out_cap,
                                                char* err_msg, size_t err_cap,
                                                RecompLauncherCPrepareProgressFn on_progress,
                                                void* progress_ctx);
    const char* prepare_disc_label;   // borrowed; NULL => default button text
    const char* prepare_disc_note;    // borrowed; NULL => default help
    const char* prepare_section_title;   // borrowed; NULL => "Convert raw dump…"
    const char* prepare_busy_status;     // borrowed; NULL => "Preparing disc image…"
    const char* prepare_success_status;  // borrowed; NULL => "Disc ready."
    const char* rebuild_busy_status;     // borrowed; NULL => "Building game…"
    const char* rebuild_success_status;  // borrowed; NULL => "Build complete."
    const char* pgo_busy_status;         // borrowed; NULL => "Optimizing FMV…"
    const char* pgo_success_status;      // borrowed; NULL => "FMV optimize complete."
    const char* fmv_timing_busy_status;  // borrowed; NULL => "Applying FMV timing…"
    const char* fmv_timing_success_status; // borrowed; NULL => "FMV timing applied."
    bool        prepare_use_selected_rom; // button uses current ROM (no 2nd picker)
    bool        rebuild_after_prepare;
    bool        relaunch_after_rebuild;
    bool        prepare_required_before_continue;
    bool        setup_needs_toolchain;   // wizard page 0: portable cmake/clang
    int (*toolchain_is_ready_cb)(void);
    int (*ensure_toolchain_with_progress_cb)(
        int download, const char* zip_path, char* err_msg, size_t err_cap,
        RecompLauncherCPrepareProgressFn on_progress, void* progress_ctx);
    int (*toolchain_update_available_cb)(char* local_ver, size_t local_cap,
                                         char* remote_ver, size_t remote_cap);
    bool        setup_prepare_satisfied; // prepare (+ rebuild if chained) succeeded
    char        relaunch_exe[512];       // set when rebuild requests relaunch
    // Box-art path relative to the assets dir (GameInfo.boxart_path);
    // NULL => the default "assets/img/boxart.tga".
    const char* boxart_path;

    // ---- N64 Transfer Pak (GameInfo.tpak_slots > 0 games) ------------------
    // Per-slot facts refreshed via tpak_inspect_cb (the HOST's cartridge
    // brain — see recomp_launcher.h) on init and on every ROM/save change.
    // A NULL callback leaves tpak_inspected false and the card shows the
    // bare file name with the neutral cartridge tint.
    int  tpak_slots;                 // borrowed; 0 => "tpak" panel never composes
    int (*tpak_inspect_cb)(const char* rom_path, const char* save_path,
                           RecompLauncherCTpak* out);
    RecompLauncherCTpak tpak_info[RECOMP_LAUNCHER_MAX_TPAKS];
    bool tpak_inspected[RECOMP_LAUNCHER_MAX_TPAKS];

    // ---- audio output device picker (GameInfo.audio_device_labels) --------
    const char* const* audio_device_labels;   // borrowed; NULL/0 => no device row
    int  num_audio_devices;

    // ---- renderer vocabulary override (GameInfo.renderer_labels) ----------
    // When set, launcher_model_toggle_renderer() cycles 0..num_renderers-1
    // and launcher_model_renderer_label() speaks these labels instead of the
    // built-in Software/OpenGL pair.
    const char* const* renderer_labels;
    int  num_renderers;

    // ---- rebind-page opt-out (GameInfo.hide_rebind) ------------------------
    bool hide_rebind;
    // ---- mouse controls (GameInfo.has_mouse_controls; Snap) ----------------
    // Borrowed capability flag: when true the source dropdown offers a
    // "Keyboard + Mouse" entry and the Controller page shows a MOUSE card.
    // The editable state itself lives in m->s (mouse_enabled / _sensitivity /
    // _invert_x / _invert_y / _bind[]), like audio_device. False => none of
    // the mouse surface composes and behavior is unchanged for every game.
    bool has_mouse_controls;
    bool has_gyro_controls;
    bool has_sharp_filter;
    bool has_affine_filter;
    bool netplay_supported;
    /* Host opted into first-run wizard + Generate & rebuild (GameInfo). */
    bool setup_wizard_supported;
    const RecompLauncherCNetplayCallbacks* netplay;
    const RecompLauncherCModProvider* mods;
    int       mod_selected;
    int       mod_package_selected;
    bool      mod_show_packages;
    char      mod_search[96];
    char      mod_status[256];
    // Game-supplied aspect vocabulary (GameInfo.aspect_labels): when set,
    // the aspect cycle walks these 0..num_aspect_labels-1 instead of the
    // built-in 4:3/16:9/21:9 mask set; aspect_experimental tags the row.
    const char* const* aspect_labels;
    int  num_aspect_labels;
    bool aspect_experimental;
    const char* aspect_setting_label;
    const char* aspect_setting_help;
    bool adaptive_view_supported;
    const char* const* display_layout_labels;
    int  num_display_layouts;
    bool has_assist_tools;
    const char* assist_tools_note;
    bool settings_bindings;
    const char* const* assist_binding_labels;
    int assist_binding_count;
    const char* credits_text;
    // Number of players the GAME actually supports. Mega Man X is 1-player, so
    // the launcher must not show a dead Player 2 row. Games that support 2
    // report 2 and the second row appears. Driven by data, never hardcoded.
    // Netplay host Max Players and lobby ceilings use this full capability.
    // Dashboard controller cards use launcher_model_visible_player_count()
    // (PSX multitap may hide seats 5+).
    int         player_count;

    // ---- ROM verification ----
    // Expected fingerprint, borrowed from the game's C-ABI struct.
    uint32_t        expected_crc;
    int             has_expected_crc;
    const uint8_t (*known_sha256)[32];
    size_t          num_known_sha256;
    const char* const* known_sha1_hex;   // accepted SHA-1 (40-hex), cartridge gate
    size_t          num_known_sha1;

    // ---- controller pad-mode caps (PlayStation-style analog/digital) ----
    bool     pad_mode_supported;    // false => no selector/art swap; generic pad.tga
    bool     pad_mode_selectable;   // false => selector hidden, mode forced to locked_pad_mode
    int      locked_pad_mode;       // forced mode when !pad_mode_selectable
    bool     lock_device;           // true => hide the player controller cards entirely

    // ---- aspect ratio caps ----
    // bit0 = 4:3 (implied/always), bit1 = 16:9, bit2 = 21:9. 0 => legacy
    // widescreen_supported bool drives display settings instead.
    int      aspect_mask;

    // ---- deeper PSX-style settings capability flags (0 => control hidden) ----
    bool     has_window_size;
    bool     has_renderer;
    bool     has_supersampling;
    bool     has_antialiasing;
    bool     has_texture_filter;
    bool     has_screen_kind;
    bool     has_frame_interp;
    bool     has_spu_hq;
    bool     has_skip_fmv;
    bool     has_turbo_loads;
    // PSX geometry precision: sub-pixel vertices + perspective-correct UVs.
    // One flag gates both rows (two halves of one enhancement); the settings
    // stay independent. false => both rows hidden.
    bool     has_geometry_precision;
    // (no has_fullscreen_toggle: the Fullscreen row is universal — every
    // console draws it; the ABI flag of that name is deprecated/ignored.)
    bool     has_bios;
    bool     has_deadzone_pct;
    const char* rom_noun;             // "ROM" default; e.g. "Disc" for PSX
    const char* const* language_labels;  // borrowed; NULL/num_languages==0 => no Localization menu
    int      num_languages;

    // ---- inferred SystemProfile (launcher_system.h) ----
    // Derived once in launcher_model_init() from the ABI GameInfo's `platform`
    // field (falling back to a capability-flag heuristic) — see
    // launcher_system_infer(). Drives which panels compose into each view and
    // supplies per-system specs (pad art, save kind, hotkeys mask). Never
    // NULL after init.
    const struct SystemProfile* profile;

    bool     rom_present;
    char     rom_full[512];          // absolute path (what we hand to the game)
    char     rom_file[128];          // basename for display, e.g. "mmx.sfc"
    char     rom_size[48];           // "1.50 MB"
    char     rom_header[24];         // "LoROM"
    char     rom_crc_str[16];        // "1B4B2E9C"
    char     rom_sha_str[24];        // "9c2e…d41f"
    bool     crc_match;
    bool     sha_match;      // any known_sha256 matched
    bool     sha1_match;     // any known_sha1_hex matched

    // ---- disc-verdict result (verify.mode==1 systems only; PSX today) ----
    // See VerifyResult above. Untouched (all-zero) for verify.mode==0 systems
    // (SNES) — panels branch on m->profile->verify.mode, never on this alone.
    VerifyResult verify;

    // ---- editable settings (working copy of the C ABI struct) ----
    RecompLauncherCSettings s;
    RecompLauncherCSettings default_settings;
    bool      has_default_settings;

    // ---- transient UI state ----
    LngView   view;
    LngAction action;
    int       cfg_player;            // 0..LNG_MAX_PLAYERS-1 — which player the Controller view edits
    bool      skip_modal_open;       // "Skip the launcher on boot?" confirm
    bool      pgo_confirm_open;      // SYSTEM → VIDEO → Optimize FMV confirm
    bool      fmv_timing_confirm_open; // SYSTEM → VIDEO → Apply FMV Timing confirm
    bool      setup_wizard_open;     // first-run BIOS/ROM setup (blocking)
    int       setup_page;            // 0 = toolchain, 1 = BIOS/ROM/generate
    bool      setup_tc_auto;         // download portable toolchain (default true)
    bool      setup_tc_ready;        // toolchain resolved / installed
    bool      setup_tc_update_available; // remote latest newer than local
    bool      setup_tc_update_skipped;   // user skipped update this session
    char      setup_tc_local_ver[64];
    char      setup_tc_remote_ver[64];
    char      setup_tc_zip[512];     // offline cmake-clang-v1 zip when !auto
    bool      setup_bios_ok;         // last bios_verify_cb result (or path-only ok)
    bool      setup_bios_warn;
    bool      setup_bios_needs_regen; // valid dump but not linked in this binary
    char      setup_bios_detail[256];
    /* Confirm before persisting a BIOS switch that requires Generate & rebuild. */
    bool      bios_confirm_open;
    char      bios_pending_path[512]; // "" = OpenBIOS; absolute otherwise
    /* Staged BIOS switch: sidecars updated for the generate CLI, but reverted
     * if prepare/rebuild fails so a failed job does not stick the new pick. */
    bool      bios_switch_uncommitted;
    char      bios_revert_path[512];
    /* Play blocked because saved BIOS is not linked — offer Generate / OpenBIOS. */
    bool      bios_play_modal_open;
    bool      setup_preparing;       // prepare/rebuild/toolchain job in flight
    float     setup_prepare_pulse;   // 0..1 animation phase while preparing
    float     setup_prepare_fraction; // 0..1 real progress, or <0 for pulse-only
    char      setup_progress_title[128]; // progress modal title override
    char      setup_status[256];     // busy / result line under the wizard
    char      setup_error[256];
    bool      netplay_name_modal_open;
    bool      netplay_name_prompted;
    bool      netplay_host_modal_open;
    bool      netplay_network_modal_open;
    bool      netplay_password_modal_open;
    bool      netplay_local_room;
    int       netplay_selected_lobby;
    char      netplay_name_edit[64];
    char      netplay_lobby_url[256];
    char      netplay_host_name[96];
    char      netplay_host_password[64];
    char      netplay_host_port[16];
    char      netplay_host_ip[64];
    char      netplay_host_local_ip[64];
    int       netplay_local_address_count;
    RecompLauncherCNetplayLocalAddress
              netplay_local_addresses[LNG_NETPLAY_MAX_LOCAL_ADDRESSES];
    char      netplay_host_endpoint[96];
    bool      netplay_lan_only;   /* "LAN/Direct IP Only"; false = online / ICE path */
    bool      netplay_list_fresh; /* false → refresh lobby list on next Netplay draw */
    bool      netplay_direct_modal_open;
    char      netplay_direct_ip[64];
    char      netplay_direct_port[16];
    char      netplay_password[64];
    char      netplay_status[160];
    bool      netplay_lobby_settings_open;
    int       netplay_lobby_input_delay; /* UI cache; engine clamps 2..20 */
    /* When false (default), host picks delay from max peer RTT at match start.
     * When true, netplay_lobby_input_delay is used as-is. */
    bool      netplay_manual_input_delay;
    /* Invent runway P (rollback). Engine clamps 2..16. */
    int       netplay_lobby_input_prediction;
    /* When false (default), host picks P from RTT at match start (rollback). */
    bool      netplay_manual_input_prediction;
    /* STUN / host external_ip cache for LAN lobby Public IP field. */
    char      netplay_public_ip[64];
    bool      netplay_public_ip_resolved;
    /* Lobby UDP SFU (online default). Not exposed in Lobby Settings; LAN clears. */
    bool      netplay_force_input_relay;
    bool      netplay_force_turn;
    /* True = rollback invent path (lobby default). UI exposes “Disable Rollback”. */
    bool      netplay_rollback;
    /* Host Lobby: desired max seats (2..min(8, game player_count)). */
    int       netplay_host_max_players;
    /* Active room seat ceiling after create/join (0 = use game player_count). */
    int       netplay_lobby_max_slots;
    bool      defaults_modal_open;   // confirmed full-settings reset

    // Selected gamepad per player (when player_src == 2). pad_id is the live
    // SDL_JoystickID; name is cached for display if the device disconnects.
    uint32_t  player_pad_id[LNG_MAX_PLAYERS];
    char      player_pad_name[LNG_MAX_PLAYERS][64];

    // rebind capture state machine
    bool      capturing;         // capturing a player button
    int       capture_btn;       // generic index into the active profile's ControllerSpec.buttons[] (0..button_count-1)
    int       capture_slot;      // alternate-bind slot being captured (0 always;
                                 // 1 only for consoles with two bind slots per
                                 // input — N64 input.cfg and PSX keybinds.ini)
    // When capturing, whether the GAMEPAD bind (button/axis) is being captured
    // instead of the keyboard scancode — Genesis has_pad_binds, and PSX's
    // Gamepad Bindings panel (per selected GUID).
    bool      capture_pad;
    // PSX Gamepad Bindings: sequential Map All Bindings walk (column-major
    // order in kPsxGamepadBindOrder). map_all_step indexes that order array.
    // map_all_wait_release ignores further presses until the whole pad is at
    // rest (all buttons up, all axes near center) so a held stick/button
    // cannot auto-bind the next slot on every AXIS_MOTION.
    bool      map_all_active;
    bool      map_all_wait_release;
    int       map_all_step;
    // A mouse button may be BOUND on stores that keep alternates (PSX). ImGui
    // opens capture on release, so the next down event is a deliberate bind.
    bool      capture_mouse_armed;
    bool      camera_capturing;  // capturing an enabled Voxel camera key
    int       capture_camera;    // LNG_CAMERA_* index
    bool      capture_assist;      // capture_btn indexes assist bindings
    bool      hk_capturing;      // capturing a system hotkey
    LngHotkey capture_hk;
    // Per-player bind-label display strings, indexed like capture_btn.
    // binds[] is slot 0 (the primary bind — every console); binds_alt[] is
    // slot 1, filled only by bind bridges with two slots per input (N64).
    char      binds[LNG_MAX_PLAYERS][LNG_MAX_BUTTONS][32];
    char      binds_alt[LNG_MAX_PLAYERS][LNG_MAX_BUTTONS][32];
    // Per-player GAMEPAD binding labels (has_pad_binds consoles only; e.g.
    // "dpup", "a", "leftx+", "(unbound)"). Parallel to binds[], filled by
    // launcher_binds.c's per-console bridge alongside the keyboard labels.
    char      pad_binds[LNG_MAX_PLAYERS][LNG_MAX_BUTTONS][32];
    char      camera_binds[LNG_CAMERA_BIND_COUNT][32];
    char      hotkeys[LNG_HK_COUNT][32];    // [KeyMap] value strings, e.g. "Ctrl+R"
} LauncherModel;

// Build the model from the inbound C ABI structs. `initial_rom` may be NULL.
void launcher_model_init(LauncherModel* m,
                         const RecompLauncherCSettings* io,
                         const RecompLauncherCGameInfo* game,
                         const char* initial_rom);

// Copy the working settings back into the caller's struct (on LAUNCH).
void launcher_model_commit(const LauncherModel* m, RecompLauncherCSettings* io);

// Adopt a newly-picked ROM path (from the native file dialog): updates the
// displayed file name / verification state.
void launcher_model_set_rom(LauncherModel* m, const char* path);

// Full path of the currently selected ROM ("" when none).
const char* launcher_model_rom_path(const LauncherModel* m);

// True iff a ROM is loaded and every fingerprint the game provides (CRC and/or
// SHA-256) matches. If the game provides no fingerprint at all, returns false
// (we can't vouch for an unknown ROM).
bool launcher_model_rom_verified(const LauncherModel* m);

// ---- navigation ----
void launcher_model_set_view(LauncherModel* m, LngView v);
void launcher_model_open_config(LauncherModel* m, int player);  // -> Controller view
void launcher_model_begin_camera_capture(LauncherModel* m, int action);
void launcher_model_cancel_camera_capture(LauncherModel* m);

// ---- restore host-provided settings defaults ----
bool launcher_model_can_restore_defaults(const LauncherModel* m);
void launcher_model_request_restore_defaults(LauncherModel* m);
void launcher_model_restore_defaults(LauncherModel* m);
void launcher_model_cancel_restore_defaults(LauncherModel* m);

// ---- display settings ----
void launcher_model_cycle_scale(LauncherModel* m);   // 1..6 wrap
void launcher_model_toggle_filter(LauncherModel* m);
void launcher_model_cycle_scaling_filter(LauncherModel* m);
const char* launcher_model_scaling_filter_label(const LauncherModel* m);
void launcher_model_toggle_affine_filter(LauncherModel* m);
void launcher_model_toggle_widescreen(LauncherModel* m);  // gated
void launcher_model_toggle_adaptive_view(LauncherModel* m);  // gated; fixed aspect is retained
/* Unified Native / fixed widescreen / Adaptive control. Compatibility fields
 * (`widescreen`, `aspect_index`, `adaptive_view`) remain the host ABI, but UI
 * presents them as one mode instead of unrelated toggles. */
void launcher_model_cycle_view_mode(LauncherModel* m);
const char* launcher_model_view_mode_label(const LauncherModel* m);
void launcher_model_cycle_display_layout(LauncherModel* m);
const char* launcher_model_display_layout_label(const LauncherModel* m);

// ---- widescreen extra cells (SystemProfile.video.widescreen_cells consoles,
// e.g. Genesis: N extra 8-px background cells rendered per side while
// widescreen is on). Clamped 1..16; no-op when the profile doesn't opt in. ----
void launcher_model_ws_cells_delta(LauncherModel* m, int delta);
const char* launcher_model_ws_cells_label(const LauncherModel* m);   // "8 cells"

// ---- active rebind vocabulary size for one player -------------------------
// The number of leading ControllerSpec.buttons[] entries the rebind page
// shows for `player` right now: on a profile with a custom pad-mode list
// (ControllerSpec.modes, e.g. Genesis 3-Button/6-Button) this follows the
// player's CURRENT mode's button_count; otherwise it is the profile's full
// button_count. Always <= LNG_MAX_BUTTONS.
int launcher_model_active_button_count(const LauncherModel* m, int player);

// ---- aspect ratio (PSX-style; only meaningful when aspect_mask != 0) ----
// Cycle through the OFFERED aspects only (4:3 always offered; 16:9/21:9 per
// aspect_mask). No-op when aspect_mask == 0 (legacy widescreen bool games).
void launcher_model_cycle_aspect(LauncherModel* m);
const char* launcher_model_aspect_label(const LauncherModel* m);  // "4:3 (Native)" etc.
bool launcher_model_aspect_offered(const LauncherModel* m, int index);  // 0=4:3,1=16:9,2=21:9

// ---- audio settings ----
void launcher_model_cycle_freq(LauncherModel* m);    // 32000/44100/48000
void launcher_model_volume_delta(LauncherModel* m, int delta);  // clamp 0..100

// ---- deeper PSX-style settings (capability-gated; no-op / harmless when the
// corresponding has_* flag is false — callers should still gate the UI on the
// flag so the control isn't shown at all, per the legacy PSX launcher parity). ----
void launcher_model_cycle_window_size(LauncherModel* m);       // {960,1280,1600,1920} wrap
const char* launcher_model_window_size_label(const LauncherModel* m);  // "1280 x 960" (H follows aspect)
void launcher_model_toggle_renderer(LauncherModel* m);         // Software/OpenGL
const char* launcher_model_renderer_label(const LauncherModel* m);
void launcher_model_cycle_supersampling(LauncherModel* m);     // 1x..4x wrap
const char* launcher_model_supersampling_label(const LauncherModel* m);
void launcher_model_cycle_aa(LauncherModel* m);            // Off/2x/4x/8x (MSAA sample count)
const char* launcher_model_aa_label(const LauncherModel* m);
void launcher_model_toggle_texture_filter(LauncherModel* m);   // Nearest/Bilinear
const char* launcher_model_texture_filter_label(const LauncherModel* m);
// PSX geometry precision (gated on has_geometry_precision).
void launcher_model_toggle_geometry_correction(LauncherModel* m);
void launcher_model_toggle_perspective_texturing(LauncherModel* m);
// True when geometry correction is on but supersampling is 1x, where the
// correction rounds back to the native pixel and has no visible effect.
bool launcher_model_geometry_correction_inert(const LauncherModel* m);
void launcher_model_cycle_screen_kind(LauncherModel* m);       // Raw/CRT/Composite/Trinitron
const char* launcher_model_screen_kind_label(const LauncherModel* m);
void launcher_model_toggle_frame_interp(LauncherModel* m);
void launcher_model_cycle_interp_fps(LauncherModel* m);        // {0,90,120,144,165,240} wrap
const char* launcher_model_interp_fps_label(const LauncherModel* m);  // "Display refresh"/"90 fps"
void launcher_model_toggle_spu_hq(LauncherModel* m);
void launcher_model_toggle_skip_fmv(LauncherModel* m);
void launcher_model_toggle_turbo_loads(LauncherModel* m);
void launcher_model_cycle_fullscreen(LauncherModel* m);        // Off -> Borderless -> Exclusive, wraps
const char* launcher_model_fullscreen_label(const LauncherModel* m);  // "Off"/"Borderless"/"Exclusive"
void launcher_model_toggle_fullscreen(LauncherModel* m);       // binary on/off; kept for bool-style hosts
void launcher_model_cycle_language(LauncherModel* m);          // wraps over num_languages
const char* launcher_model_language_label(const LauncherModel* m);
void launcher_model_cycle_deadzone_pct(LauncherModel* m);      // 0..50 step 5, wraps; mirrors both players
const char* launcher_model_deadzone_pct_label(const LauncherModel* m);  // "37%"
void launcher_model_set_bios_path(LauncherModel* m, const char* path);
/* Request a BIOS change.
 * - OpenBIOS (empty path): always applies immediately when allowed — never
 *   requires Generate & rebuild.
 * - Retail already linked in this binary: hot-swap immediately.
 * - Retail valid but not linked yet: confirm Generate & rebuild. */
void launcher_model_request_bios_path(LauncherModel* m, const char* path);
/* Confirm accept: save pending BIOS and kick Generate & rebuild (no wizard). */
void launcher_model_bios_confirm_accept(LauncherModel* m);
void launcher_model_bios_confirm_cancel(LauncherModel* m);
/* Play clicked while setup_bios_needs_regen (or !ok with a saved path). */
void launcher_model_bios_play_prompt(LauncherModel* m);
void launcher_model_bios_play_use_openbios(LauncherModel* m);
void launcher_model_bios_play_generate(LauncherModel* m);
void launcher_model_bios_play_cancel(LauncherModel* m);
/* True when ROM/disc looks ready but BIOS needs Generate & rebuild. */
bool launcher_model_bios_blocks_play(const LauncherModel* m);

// ---- SRAM save management (Import/Clear; both back up to "<sram>.bak" first) ----
void launcher_model_import_sram(LauncherModel* m, const char* src);
void launcher_model_clear_sram(LauncherModel* m);

// ---- PSX memory-card slots (SAVE_MEMCARD only; no-op guarded by slot range) ----
void launcher_model_set_memcard_path(LauncherModel* m, int slot, const char* path);
// Enable/disable one card slot (mirrors the legacy launcher's per-card switch;
// a disabled slot's SIO port reports no card present to the host once wired).
void launcher_model_toggle_memcard(LauncherModel* m, int slot);
// "New" action: format a real, mountable blank 128KB PS1 memory-card image at
// `path` (recompui_memcard_format_file(), memcard_format.h — no dependency on
// any host project's runtime headers), then adopt it as the slot's path. A
// no-op (path left untouched) if the format write fails.
void launcher_model_new_memcard(LauncherModel* m, int slot, const char* path);

// ---- PSX multitap (3+ player seats on the controller dashboard) ---------
// Available when the active profile is PSX and player_count >= 3. When off,
// visible_player_count clamps to 2 (native dual ports); netplay still uses
// full player_count / slot_count.
int  launcher_model_multitap_available(const LauncherModel* m);
int  launcher_model_multitap_enabled(const LauncherModel* m);
void launcher_model_toggle_multitap(LauncherModel* m);
int  launcher_model_visible_player_count(const LauncherModel* m);
/* DualShock-on-tap hack UI (PSX, player_count >= 3). */
int  launcher_model_multitap_analog_available(const LauncherModel* m);
int  launcher_model_multitap_analog_enabled(const LauncherModel* m);
void launcher_model_toggle_multitap_analog(LauncherModel* m);

// ---- N64 Transfer Pak slots (tpak_slots only; no-op guarded by slot range) ----
// Adopt a GB cartridge ROM for one port's Transfer Pak. Re-runs the host's
// tpak_inspect_cb (when set) to refresh the card's label/trainer/tint facts,
// and enables the slot (inserting a cart = wanting it on, the SS Anne rule).
void launcher_model_set_tpak_rom(LauncherModel* m, int slot, const char* path);
// Eject the cartridge (clears rom+save paths and the inspect facts).
void launcher_model_clear_tpak(LauncherModel* m, int slot);
// Point the slot at a different battery-save file; re-inspects.
void launcher_model_set_tpak_save(LauncherModel* m, int slot, const char* path);
// Enable/disable the pak on that port (a disabled pak reports absent).
void launcher_model_toggle_tpak(LauncherModel* m, int slot);
// True when the slot is enabled (resolves the tri-state tpak_enabled field:
// >0 on, <0 off, 0 unset => on iff a cartridge is inserted).
bool launcher_model_tpak_enabled(const LauncherModel* m, int slot);

// ---- audio output device (num_audio_devices only) ----
// Adopt a device by its host-enumerated display name; NULL/"" => system
// default. The label helper renders the current pick for the dropdown.
void launcher_model_set_audio_device(LauncherModel* m, const char* name);
const char* launcher_model_audio_device_label(const LauncherModel* m);

// ---- MSU-1 (only when msu1_supported) ----
void launcher_model_toggle_msu1(LauncherModel* m);
void launcher_model_set_msu1_dir(LauncherModel* m, const char* dir);

// ---- NES-style settings (capability-gated like the PSX deep set) ----
void launcher_model_toggle_integer_scale(LauncherModel* m);   // gated has_integer_scale

// ---- cartridge light sensor (all gated on has_solar_sensor) ----------------
// The postal code is stored verbatim apart from trimming: validating which
// codes exist is the host's job (it owns the geocoder), and rejecting them here
// would just mean two places disagreeing about what is valid.
void launcher_model_set_solar_zip(LauncherModel* m, const char* zip);
void launcher_model_set_solar_country(LauncherModel* m, const char* country);
void launcher_model_set_solar_source(LauncherModel* m, int source);     // 0 live, 1 manual
void launcher_model_set_solar_manual_step(LauncherModel* m, int step);  // clamped 0..8
void launcher_model_set_solar_full_sun(LauncherModel* m, int wm2);      // clamped 300..1200
void launcher_model_toggle_hdpack(LauncherModel* m);          // gated hdpack_supported
void launcher_model_set_hdpack_dir(LauncherModel* m, const char* dir);
// Password/mantra save: reload m->password_text from password_save_path, and
// commit new text back to it (single line; file created if absent).
void launcher_model_password_reload(LauncherModel* m);
void launcher_model_password_commit(LauncherModel* m, const char* text);
// Zapper switches (gated m->zapper). Persist immediately through
// launcher_binds' [zapper] section writer, mirroring how rebinds persist.
void launcher_model_toggle_zapper_mouse(LauncherModel* m);
void launcher_model_toggle_zapper_crosshair(LauncherModel* m);

// ---- MSU-1 IPS auto-patching (dashboard GAME-panel "Patch ROM"/"Skip") ----
// Apply msu1_patch_path onto the currently loaded (vanilla) ROM, writing
// "<stem>.msu1.<ext>" beside it, then adopt the patched file as the current
// ROM (re-verifies CRC/SHA, same as launcher_model_set_rom). No-op unless
// msu1_patch_available is true.
void launcher_model_apply_msu1_patch(LauncherModel* m);
// Hide the "MSU-1 patch available" prompt for the rest of this run (does not
// persist to disk — the prompt returns next launch unless the patch is
// actually applied). No-op if the prompt wasn't showing.
void launcher_model_skip_msu1_patch(LauncherModel* m);

// ---- controllers ----
// PSX-style pad mode: 1=Analog, 2=D-Pad. Gated: no-op when
// !pad_mode_selectable (mode is locked). Mode 0 (Hybrid) is NOT selectable —
// it is a mod-only mode requested at runtime by a trusted game plugin — so a
// stale persisted 0 snaps to Analog.
void launcher_model_set_pad_mode(LauncherModel* m, int player, int mode);
void launcher_model_cycle_player_src(LauncherModel* m, int player); // None/Kbd/Pad
void launcher_model_deadzone_delta(LauncherModel* m, int player, int delta);
// Set the input source explicitly (used by the device dropdown). kind: 0 None,
// 1 Keyboard, 2 Gamepad. For gamepad, pass the SDL id + display name + GUID
// (GUID may be NULL/empty; then player_gamepad_guid[player] is cleared).
void launcher_model_set_source(LauncherModel* m, int player, int kind,
                               uint32_t pad_id, const char* pad_name,
                               const char* pad_guid);

// ---- mouse controls (has_mouse_controls games only; no-op otherwise) --------
// Select the player-0 keyboard source with mouse-aim on (enabled != 0) or off
// (enabled == 0). Sets player_src[0] = Keyboard via launcher_model_set_source
// and records mouse_enabled. No-op unless has_mouse_controls.
void launcher_model_set_mouse_source(LauncherModel* m, int enabled);
// Set the mouse aim sensitivity; clamped to [0.01, 0.50].
void launcher_model_set_mouse_sensitivity(LauncherModel* m, float value);
void launcher_model_toggle_mouse_invert_x(LauncherModel* m);
void launcher_model_toggle_mouse_invert_y(LauncherModel* m);
// Bind mouse button `which` (0 Left, 1 Right, 2 Middle) to a button index into
// the active profile's ControllerSpec.buttons[] (0..button_count-1), or -1 for
// none. Out-of-range `which` is a no-op.
void launcher_model_set_mouse_bind(LauncherModel* m, int which, int button_index);

// ---- controller motion (has_gyro_controls games only) ---------------------
// Set the host-owned angular-rate multiplier; clamped to [0.25, 4.00].
void launcher_model_set_gyro_sensitivity(LauncherModel* m, float value);

// ---- first-run setup wizard ----
// True when the wizard should ask only for BIOS/disc confirmation: prepare
// callbacks exist (codegen host) but prepare_required_before_continue is 0
// because generated sources / a full build are already present. Cleared
// disc.cfg / BIOS paths reopen the wizard without the Generate & rebuild page.
bool launcher_model_setup_media_confirm_only(const LauncherModel* m);
// True when required BIOS + ROM/disc paths are present (readable), and when
// prepare_required_before_continue is set, prepare (+ chained rebuild) has
// succeeded. Fingerprint mismatch is allowed here.
bool launcher_model_can_finish_setup(const LauncherModel* m);
// True when BIOS (if required) and ROM/disc are ready to launch (incl. fingerprint).
bool launcher_model_can_launch(const LauncherModel* m);
// True when the mounted disc is OK for online (TOC/cue policy + content).
// Non-disc games (verify.mode!=1) always return true when netplay is supported.
bool launcher_model_netplay_disc_ok(const LauncherModel* m);
// Re-run bios_verify_cb against m->s.bios_path. Empty path means "bundled
// BIOS" — OK unless the host verifier refuses "".
void launcher_model_refresh_bios_status(LauncherModel* m);
// Kick a host prepare_disc job on a background thread. No-op if no callback
// or a job is already running. On success adopts the resulting disc path.
// When rebuild_after_prepare is set, automatically chains into rebuild.
void launcher_model_start_prepare_disc(LauncherModel* m, const char* source_path);
// Kick rebuild_with_progress alone (same busy UI as prepare).
void launcher_model_start_rebuild(LauncherModel* m);
// Confirm + kick pgo_optimize_with_progress (instrument → train → use rebuild).
void launcher_model_request_pgo_optimize(LauncherModel* m);
void launcher_model_pgo_confirm_accept(LauncherModel* m);
void launcher_model_pgo_confirm_cancel(LauncherModel* m);
void launcher_model_request_fmv_timing_optimize(LauncherModel* m);
void launcher_model_fmv_timing_confirm_accept(LauncherModel* m);
void launcher_model_fmv_timing_confirm_cancel(LauncherModel* m);
// Kick ensure_toolchain_with_progress (download and/or offline zip). On success
// advances setup_page to the BIOS/ROM/generate step.
void launcher_model_start_ensure_toolchain(LauncherModel* m);
// True when Next on the toolchain page can run (auto, zip path, already ready,
// or an update is available with auto-download / zip selected).
bool launcher_model_can_advance_toolchain(const LauncherModel* m);
// Keep the current pack for this session and leave toolchain page 0.
void launcher_model_skip_toolchain_update(LauncherModel* m);
// Poll prepare/rebuild/toolchain job; call once per frame while setup_preparing.
void launcher_model_poll_prepare_disc(LauncherModel* m);
// Dismiss the wizard once can_finish_setup is true (keeps dashboard).
void launcher_model_finish_setup(LauncherModel* m);

// ---- skip-on-boot (footer switch + confirm modal) ----
void launcher_model_request_skip_toggle(LauncherModel* m); // opens modal when enabling
void launcher_model_skip_confirm(LauncherModel* m);
void launcher_model_skip_cancel(LauncherModel* m);

// ---- rebind capture (player buttons) ----
// `b` is a generic index into the active profile's ControllerSpec.buttons[]
// (0..button_count-1) — NOT necessarily an LngButton value once the active
// system isn't SNES-shaped (e.g. PSX has 16 buttons).
void launcher_model_begin_capture(LauncherModel* m, int b);
// Same, targeting an explicit alternate-bind slot (0/1). Plain
// launcher_model_begin_capture() is slot 0. Only consoles whose bind bridge
// stores two slots per input (N64) show slot-1 chips.
void launcher_model_begin_capture_slot(LauncherModel* m, int b, int slot);
// Write one bind slot (0 primary, 1 alternate) for stores that keep two.
void launcher_binds_set_button_slot(LauncherModel* m, int player, int b,
                                    int slot, int scancode);
// Begin capturing the GAMEPAD bind (button or axis) for button `b` instead of
// a keyboard scancode. Used by Genesis has_pad_binds and the PSX Gamepad
// Bindings panel. Esc cancels.
void launcher_model_begin_pad_capture(LauncherModel* m, int b);
// PSX: start Map All Bindings (walk kPsxGamepadBindOrder, one capture each).
void launcher_model_begin_map_all(LauncherModel* m);
// After a successful pad capture during Map All: advance or finish.
void launcher_model_map_all_advance(LauncherModel* m);
void launcher_model_begin_assist_capture(LauncherModel* m, int action,
                                         bool gamepad);
void launcher_model_set_captured_key(LauncherModel* m, int scancode);
void launcher_model_set_captured_pad(LauncherModel* m, int encoded_binding);
void launcher_model_reset_player_bindings(LauncherModel* m, int player);
void launcher_model_reset_assist_bindings(LauncherModel* m);
void launcher_model_cancel_capture(LauncherModel* m);
// ---- hotkey capture ----
void launcher_model_begin_hk_capture(LauncherModel* m, LngHotkey h);
void launcher_model_cancel_hk_capture(LauncherModel* m);

// ---- display-string helpers (single source of truth across backends) ----
const char* launcher_model_scale_label(const LauncherModel* m);        // "3x"
const char* launcher_model_freq_label(const LauncherModel* m);         // "44100 Hz"
const char* launcher_model_player_src_label(const LauncherModel* m, int player);
const char* launcher_button_name(LngButton b);
const char* launcher_hotkey_name(LngHotkey h);
const char* launcher_view_name(LngView v);

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_MODEL_H
