// launcher_boot_timing.h — opt-in wall-clock stamps for launcher spawn.
//
// Enable with PSX_LAUNCHER_BOOT_TIMING=1 (or LNG_BOOT_TIMING=1). Marks print
// to stderr as:
//   [boot-timing] +  12.3 ms  total   45.6 ms  phase-name
// First mark anchors t0. Safe to call before SDL_Init.

#ifndef LAUNCHER_BOOT_TIMING_H
#define LAUNCHER_BOOT_TIMING_H

#ifdef __cplusplus
extern "C" {
#endif

void launcher_boot_timing_mark(const char *phase);

#ifdef __cplusplus
}
#endif

#endif /* LAUNCHER_BOOT_TIMING_H */
