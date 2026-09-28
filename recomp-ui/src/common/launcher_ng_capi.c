// launcher_ng_capi.c — the C ABI the game calls, backed by the launcher_ng UI.
//
// Implements recomp_launcher_run_window() (declared in recomp_launcher.h),
// the generic C ABI a host app calls to run the pre-boot launcher UI. Hosts
// seed the C structs, call the function, and read back the chosen ROM +
// settings.
//
// Returns: 0 = LAUNCH, 1 = QUIT, 2 = UNAVAILABLE, 3 = RELAUNCH.

#include "recomp_launcher.h"

#include "launcher_backend.h"
#include "launcher_binds.h"
#include "launcher_boot_timing.h"
#include "launcher_model.h"
#include "launcher_platform.h"
#include "launcher_theme.h"

#include <stdio.h>
#include <string.h>

static char g_last_relaunch_exe[512];

void recomp_launcher_set_preserve_sdl(int preserve) {
    launcher_platform_set_quit_sdl(!preserve);
}

int recomp_launcher_relaunch_exe(char* out, size_t out_cap) {
    if (!out || out_cap == 0 || !g_last_relaunch_exe[0])
        return 0;
    snprintf(out, out_cap, "%s", g_last_relaunch_exe);
    return 1;
}

int recomp_launcher_run_window(const char* window_title,
                             RecompLauncherCSettings* io,
                             const RecompLauncherCGameInfo* game,
                             const char* assets_dir,
                             const char* initial_rom,
                             char* out_rom_path, size_t out_rom_path_len) {
    (void)assets_dir;   // launcher_ng resolves assets next to the exe (SDL base path)
    g_last_relaunch_exe[0] = '\0';

    launcher_boot_timing_mark("rui:run_window:enter");

    LauncherPlatform plat;
    if (!launcher_platform_open(&plat, window_title ? window_title : "Launcher",
                                1100, 880)) {
        // Window/GL init failed — tell the caller to boot as if the launcher was
        // skipped, exactly like the old launcher's UNAVAILABLE path.
        return RECOMP_LAUNCHER_RESULT_UNAVAILABLE;
    }

    LauncherModel model;
    launcher_model_init(&model, io, game, initial_rom);
    launcher_binds_load(&model, game ? game->config_path : NULL,
                                game ? game->keybinds_path : NULL);
    launcher_boot_timing_mark("rui:model+binds_ready");

    LauncherTheme theme = launcher_theme_by_name(game ? game->theme : NULL);

    LngAction act = launcher_backend_run(&plat, &model, &theme);

    launcher_platform_close(&plat);

    if (act == LNG_ACTION_LAUNCH || act == LNG_ACTION_RELAUNCH) {
        launcher_model_commit(&model, io);   // edited settings back to the caller
        const char* rom = launcher_model_rom_path(&model);
        if (out_rom_path && out_rom_path_len) {
            if (rom && rom[0])
                snprintf(out_rom_path, out_rom_path_len, "%s", rom);
            else if (initial_rom)
                snprintf(out_rom_path, out_rom_path_len, "%s", initial_rom);
            else
                out_rom_path[0] = '\0';
        }
        if (act == LNG_ACTION_RELAUNCH) {
            if (model.relaunch_exe[0])
                snprintf(g_last_relaunch_exe, sizeof(g_last_relaunch_exe),
                         "%s", model.relaunch_exe);
            return RECOMP_LAUNCHER_RESULT_RELAUNCH;
        }
        return RECOMP_LAUNCHER_RESULT_LAUNCH;
    }

    return RECOMP_LAUNCHER_RESULT_QUIT;
}
