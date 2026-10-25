/* A host clock for the journal's timings (time spent per frame, per load):
 * nanoseconds, only their differences mean anything. timespec_get is C11 but
 * Bionic has it only from API 29 and the APK targets 28 (B99), so it serves
 * Windows alone (the UCRT has no clock_gettime); macOS, Linux and Android use
 * clock_gettime(CLOCK_MONOTONIC). */
#ifndef TEKKEN3_HOST_CLOCK_H
#define TEKKEN3_HOST_CLOCK_H
#include <stdint.h>
#include <time.h>

static inline uint64_t tekken3_host_ns(void) {
    struct timespec t;
#ifdef _WIN32
    timespec_get(&t, TIME_UTC);
#else
    clock_gettime(CLOCK_MONOTONIC, &t);
#endif
    return (uint64_t)t.tv_sec * 1000000000u + (uint64_t)t.tv_nsec;
}

#endif
