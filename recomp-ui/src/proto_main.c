// proto_main.c — standalone self-test driver for recomp-ui.
#include <stdlib.h>
//
// Console-agnostic by construction: it fabricates the SAME C ABI structs any
// consuming host passes (here seeded with a neutral placeholder game), then
// runs the compiled-in Dear ImGui backend. This is the harness the recomp-ui
// repo itself builds to self-verify; a real host implements its own main()
// that calls recomp_launcher_run_window() (see recomp_launcher.h) with its
// own game facts.

#include "launcher_backend.h"
#include "launcher_binds.h"
#include "launcher_model.h"
#include "launcher_platform.h"
#include "launcher_profile.h"
#include "launcher_theme.h"

#include <stdio.h>
#include <string.h>

// Harness-only Transfer Pak "cartridge brain". A real N64 host (PSR sniffs the
// GB header @0x134 + decodes the Gen-1 save; PMS-J uses the kana charmap) fills
// these facts; here we fabricate them from the ROM file name so the dashboard's
// Transfer Pak card exercises every populated state without a real cart.
static int proto_tpak_inspect(const char* rom_path, const char* save_path,
                              RecompLauncherCTpak* out) {
    (void)save_path;
    memset(out, 0, sizeof(*out));
    if (!rom_path || !rom_path[0]) return 0;   // empty slot => nothing inserted
    out->valid = 1;
    int kind = 0; const char* label = "Game Boy Cartridge";
    if      (strstr(rom_path, "red"))    { kind = 1; label = "Pokemon Red"; }
    else if (strstr(rom_path, "blue"))   { kind = 2; label = "Pokemon Blue"; }
    else if (strstr(rom_path, "yellow")) { kind = 3; label = "Pokemon Yellow"; }
    else if (strstr(rom_path, "green"))  { kind = 4; label = "Pokemon Green"; }
    out->cart_kind = kind;
    snprintf(out->cart_label,   sizeof(out->cart_label),   "%s", label);
    snprintf(out->trainer_name, sizeof(out->trainer_name), "SATOSHI");
    snprintf(out->trainer_id,   sizeof(out->trainer_id),   "12345");
    return 1;
}

int main(int argc, char** argv) {
    (void)argc; (void)argv;

    // ---- seed the C ABI structs the same way a real host would ----
    RecompLauncherCSettings s;
    memset(&s, 0, sizeof(s));
    s.output_method  = 2;      // OpenGL
    s.window_scale   = 3;
    s.fullscreen     = 0;
    s.linear_filter  = 0;
    s.widescreen     = 0;
    s.enable_audio   = 1;
    s.audio_freq     = 32000;
    s.volume         = 100;
    s.player_src[0]  = 1;      // keyboard
    s.player_src[1]  = 0;      // none
    s.skip_launcher  = 0;
    s.pad_mode[0]    = 0;      // Hybrid
    s.pad_mode[1]    = 0;
    s.aspect_index   = 1;      // 16:9

    // Neutral placeholder game: no CRC/SHA pinning, no MSU-1, no SRAM. Just
    // enough to exercise every panel that doesn't require real game facts.
    RecompLauncherCGameInfo gi;
    memset(&gi, 0, sizeof(gi));
    gi.name                 = "Recomp UI Test";
    gi.region               = "";
    gi.has_expected_crc     = 0;
    gi.widescreen_supported = 0;
    gi.msu1_supported       = 0;
    gi.sram_path            = NULL;
    gi.num_players          = 1;
    // One coherent VARIANT PROFILE picks the whole launcher identity so nothing
    // drifts (theme + controller + platform + rom_noun + capability set):
    //   LNG_VARIANT=psx  -> PlayStation (blue theme, DualShock, Disc, full PS settings)
    //   LNG_VARIANT=snes -> Super Nintendo (CRT theme, SNES pad, widescreen)
    // Unset = neutral default. See launcher_profile.h — one row per system.
    static const char* kPreviewLanguages[2] = { "English", "Japanese" };
    // Set by a variant that manages its OWN LNG_DEMO_FULL preview so the generic
    // (SNES-shaped) demo block below doesn't clobber it with MSU-1 / 1-player.
    int variant_owns_demo = 0;
    const char* variant = getenv("LNG_VARIANT");
    if (variant && variant[0]) {
        launcher_profile_apply(variant, &gi);
        if (lpr_is(variant, "psx") || lpr_is(variant, "ps1") || lpr_is(variant, "playstation")) {
            // Preview a PS1 title that offers the full surface (both wide aspects,
            // a language menu, a "configured" settings state).
            gi.aspect_mask     = 0x7;   // 4:3 + 16:9 + 21:9
            gi.language_labels = kPreviewLanguages;
            gi.num_languages   = 2;
            gi.num_players     = 1;
            s.window_width = 1280; s.renderer = 1; s.supersampling = 1;
            s.screen_kind = 1; s.frame_interp = 0; s.spu_hq = 1; s.aspect_index = 1;
        }
        if (lpr_is(variant, "nes")) {
            // Preview an NES title exercising the whole NES surface: 2 players,
            // widescreen opt-in, HD-pack row (on via launcher_profile_apply),
            // and the Zapper block. LNG_DEMO_FULL=1 additionally previews the
            // password/mantra save row (Faxanadu-style; the file is created
            // next to the exe on the first Edit -> Save).
            gi.num_players = 2;
            gi.widescreen_supported = 1;
            gi.zapper = 1;
            const char* nd = getenv("LNG_DEMO_FULL");
            if (nd && nd[0] == '1') {
                gi.password_save_path  = "nes_password_demo.txt";
                gi.password_save_label = "Mantra";
            }
        }
        if (lpr_is(variant, "gba")) {
            // Preview a GBA title: the one battery .sav (save row in the GAME
            // card), a "configured" LCD screen model, 3x integer scale.
            gi.sram_path  = "saves/save.sav";
            s.screen_kind = 3;   // Backlit (kGbaScreenKindNames)
            s.window_scale = 3;
            // LNG_DEMO_FULL=1 additionally previews a game-supplied aspect
            // vocabulary (the Mega Man Zero extended-view shape).
            static const char* const kGbaAspectPreview[] = {
                "3:2 (Native)", "9:5 (288 px)", "12:5 (384 px)", "6:2 (480 px)"
            };
            const char* gd = getenv("LNG_DEMO_FULL");
            if (gd && gd[0] == '1') {
                gi.aspect_labels       = kGbaAspectPreview;
                gi.num_aspect_labels   = 4;
                gi.aspect_experimental = 1;
            }
        }
        if (lpr_is(variant, "gb") || lpr_is(variant, "gbc") ||
            lpr_is(variant, "gameboy") || lpr_is(variant, "gameboycolor") ||
            lpr_is(variant, "dmg") || lpr_is(variant, "cgb")) {
            // Preview a Game Boy family title: the one battery .sav (folds into
            // the GAME card), a "configured" LCD palette, 4x integer scale. The
            // "gbc" variant shows the GAME BOY COLOR branding + a color title;
            // "gb" shows the DMG branding + a DMG title.
            int is_color = lpr_is(variant, "gbc") ||
                           lpr_is(variant, "gameboycolor") || lpr_is(variant, "cgb");
            gi.name        = is_color ? "Megaman Xtreme 2" : "Tetris";
            gi.region      = "USA";
            gi.sram_path   = "saves/save.sav";
            gi.boxart_path = "assets/img/boxart.tga";  // placeholder if absent
            gi.widescreen_supported = is_color ? 1 : 0;  // preview MMX2's opt-in 16:9 (EXPERIMENTAL)
            s.screen_kind  = 0;    // DMG palette (kGbScreenKindNames)
            s.window_scale = 4;
            variant_owns_demo = 1;
        }
        if (lpr_is(variant, "n64")) {
            // Preview an N64 title with the full surface a Stadium-class host
            // contributes: 4 players (2x2 card grid), an SRAM save row, a host
            // audio-device picker, a renderer vocabulary, and 4 Transfer Pak
            // slots wired to the fake cartridge brain above. Two slots come
            // pre-populated so the tpak card shows its inserted/decoded state.
            gi.num_players         = 4;
            gi.sram_path           = "saves/game.sram";
            static const char* const kN64AudioDevices[2] = {
                "Speakers (Realtek High Definition Audio)", "Headphones (USB DAC)"
            };
            gi.audio_device_labels = kN64AudioDevices;
            gi.num_audio_devices   = 2;
            static const char* const kN64Renderers[3] = { "Auto", "Vulkan", "D3D12" };
            gi.renderer_labels     = kN64Renderers;
            gi.num_renderers       = 3;
            gi.tpak_slots          = 4;
            gi.tpak_inspect        = proto_tpak_inspect;
            gi.has_mouse_controls  = 1;   // preview the opt-in mouse-controls UI (Snap-style)
            // Box art is a per-GAME asset the host supplies (a real N64 host
            // passes its own gi.boxart_path); the shared preview ships none, so
            // point LNG_BOX at a local .tga to see the GAME card light up.
            const char* box = getenv("LNG_BOX");
            if (box && box[0]) gi.boxart_path = box;
            s.renderer     = 1;   // Vulkan
            s.supersampling = 1;
            s.player_src[1] = 1;  // a second active player so the 2x2 grid isn't all-empty
            snprintf(s.tpak_rom_path[0], sizeof(s.tpak_rom_path[0]), "carts/pokemon_red.gb");
            snprintf(s.tpak_rom_path[1], sizeof(s.tpak_rom_path[1]), "carts/pokemon_blue.gb");
        }
        if (lpr_is(variant, "genesis") || lpr_is(variant, "megadrive") ||
            lpr_is(variant, "md")) {
            // Preview a Sonic-class Genesis title: 2 players (both controller
            // cards, the 3-Button/6-Button pad-mode selector, and the KEY +
            // GAMEPAD rebind grid), widescreen ON so the "Extra cells / side"
            // stepper is visible, real Sonic 1 box art, the SEGA GENESIS brand.
            // LNG_GAME picks which title, to show the SAVE row present vs absent:
            //   sonic1  (default) — no battery SRAM  -> no SAVE row
            //   sonic3k           — battery SRAM      -> SAVE row (Import/Clear)
            gi.region      = "USA";
            gi.num_players = 2;
            gi.boxart_path = "assets/img/boxart_sonic1.tga";  // real cart art
            s.widescreen   = 1;      // reveals the Genesis widescreen-cells stepper
            s.window_scale = 3;
            const char* g = getenv("LNG_GAME");
            if (g && (g[0] == '3' || lpr_is(g, "sonic3k") || lpr_is(g, "s3k"))) {
                gi.name      = "Sonic 3 & Knuckles";
                gi.sram_path = "saves/sonic3k.srm";  // battery cart -> SAVE row
            } else {
                gi.name      = "Sonic The Hedgehog";  // no battery -> no SAVE row
            }
            variant_owns_demo = 1;   // keep the generic demo block from overriding
        }
    }

    // Flip these to preview the 2-player + SRAM module set (what a save-game
    // capable, 2-player host contributes), e.g. LNG_DEMO_FULL=1.
    const char* demo = SDL_getenv("LNG_DEMO_FULL");
    if (!variant_owns_demo && demo && demo[0] == '1') {
        gi.num_players = 1;
        gi.sram_path   = "saves/save.srm";
        gi.widescreen_supported = 1;
        gi.msu1_supported = 1;
        gi.msu1_note = "Place the MSU-1 pack (.pcm + .msu) in this folder.";
    }
    if (demo && demo[0] == '2') {   // 2-player variant for layout testing
        gi.num_players = 2;
        gi.sram_path   = "saves/save.srm";
    }

    // Harness-only: exercises the MSU-1 dashboard "Patch ROM"/"Skip" flow
    // (launcher_model_apply_msu1_patch / launcher_model_skip_msu1_patch, drawn
    // in draw_game_panel — launcher_imgui.cpp). Points at a tiny fixture ROM
    // + IPS patch (test_data/) whose expected_crc matches the vanilla fixture
    // byte-for-byte, so msu1_patch_available comes up true without a real
    // game. See test_data/README-ish note in the fixture generator this was
    // produced from (ips_apply unit test) for the exact byte layout.
    const char* demo_msu_rom = NULL;
    const char* demo_msu = SDL_getenv("LNG_DEMO_MSU");
    if (demo_msu && demo_msu[0] == '1') {
        gi.msu1_supported   = 1;
        gi.msu1_note        = "This demo ROM has a tiny synthetic MSU-1 IPS patch "
                              "(test_data/msu1_demo.ips) for harness verification.";
        gi.msu1_patch_path  = "test_data/msu1_demo.ips";
        gi.has_expected_crc = 1;
        gi.expected_crc     = 0xA2B10169u;   // CRC32 of test_data/msu1_demo_vanilla.rom
        demo_msu_rom = "test_data/msu1_demo_vanilla.rom";
    }

    LauncherModel model;
    const char* rom = SDL_getenv("LNG_ROM");
    if (!rom || !rom[0]) rom = demo_msu_rom ? demo_msu_rom : "test.rom";
    launcher_model_init(&model, &s, &gi, rom);
    launcher_binds_load(&model, NULL, NULL);   // keybinds.ini + config.ini [KeyMap]
    fprintf(stderr, "[proto] rom=%s present=%d crc_match=%d sha_match=%d verified=%d size=%s\n",
            rom, model.rom_present, model.crc_match, model.sha_match,
            launcher_model_rom_verified(&model), model.rom_size);

    LauncherTheme theme = launcher_theme_by_name(gi.theme);

    char title[128];
    snprintf(title, sizeof(title), "Recomp UI — Launcher [%s]", launcher_backend_name());

    LauncherPlatform plat;
    if (!launcher_platform_open(&plat, title, 1100, 880)) {
        fprintf(stderr, "[proto] platform init failed; a real host would boot as if skipped.\n");
        return 2;
    }

    LngAction act = launcher_backend_run(&plat, &model, &theme);
    launcher_platform_close(&plat);

    // In production this is the value recomp_launcher_run_window() returns to
    // the host, which then boots the game IN-PROCESS with the committed
    // settings (0=LAUNCH, 1=QUIT). The standalone harness just reports it.
    if (act == LNG_ACTION_LAUNCH) {
        launcher_model_commit(&model, &s);
        printf("[proto] LAUNCH  scale=%s fullscreen=%d filter=%d freq=%d skip=%d rom=%s\n",
               launcher_model_scale_label(&model), s.fullscreen, s.linear_filter,
               s.audio_freq, s.skip_launcher, launcher_model_rom_path(&model));
    } else {
        printf("[proto] QUIT\n");
    }
    return 0;
}
