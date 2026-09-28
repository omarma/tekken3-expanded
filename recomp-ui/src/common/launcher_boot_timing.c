/* launcher_boot_timing.c — see launcher_boot_timing.h */

#include "launcher_boot_timing.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#else
#include <time.h>
#endif

static int s_on = -1;
#if defined(_WIN32)
static LARGE_INTEGER s_freq;
static LONGLONG s_t0;
static LONGLONG s_prev;
#else
static struct timespec s_t0;
static struct timespec s_prev;
#endif

static int boot_timing_enabled(void) {
    if (s_on >= 0) return s_on;
    const char *e = getenv("PSX_LAUNCHER_BOOT_TIMING");
    if (!e || !e[0]) e = getenv("LNG_BOOT_TIMING");
    s_on = (e && e[0] && e[0] != '0') ? 1 : 0;
    if (!s_on) return 0;
#if defined(_WIN32)
    if (!QueryPerformanceFrequency(&s_freq) || s_freq.QuadPart == 0) {
        s_on = 0;
        return 0;
    }
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    s_t0 = s_prev = c.QuadPart;
#else
    if (clock_gettime(CLOCK_MONOTONIC, &s_t0) != 0) {
        s_on = 0;
        return 0;
    }
    s_prev = s_t0;
#endif
    return 1;
}

void launcher_boot_timing_mark(const char *phase) {
    if (!boot_timing_enabled()) return;

#if defined(_WIN32)
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    const LONGLONG now = c.QuadPart;
    const double ms_total =
        (double)(now - s_t0) * 1000.0 / (double)s_freq.QuadPart;
    const double ms_delta =
        (double)(now - s_prev) * 1000.0 / (double)s_freq.QuadPart;
    s_prev = now;
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return;
    const double ms_total =
        (double)(now.tv_sec - s_t0.tv_sec) * 1000.0 +
        (double)(now.tv_nsec - s_t0.tv_nsec) / 1.0e6;
    const double ms_delta =
        (double)(now.tv_sec - s_prev.tv_sec) * 1000.0 +
        (double)(now.tv_nsec - s_prev.tv_nsec) / 1.0e6;
    s_prev = now;
#endif

    fprintf(stderr, "[boot-timing] +%7.1f ms  total %7.1f ms  %s\n",
            ms_delta, ms_total, phase && phase[0] ? phase : "?");
    fflush(stderr);
}
