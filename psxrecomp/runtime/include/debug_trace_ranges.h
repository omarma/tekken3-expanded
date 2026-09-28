#ifndef PSXRECOMP_DEBUG_TRACE_RANGES_H
#define PSXRECOMP_DEBUG_TRACE_RANGES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PSXDebugTraceRange {
    uint32_t lo;
    uint32_t hi;
} PSXDebugTraceRange;

/*
 * Parse "lo,hi[;lo,hi...]" into masked-physical, half-open ranges.
 *
 * Returns the number of ranges, or -1 for malformed/reversed input and -2
 * when the destination is too small. Callers must discard the output on any
 * negative result.
 */
int psx_debug_parse_trace_ranges(const char *spec,
                                 PSXDebugTraceRange *ranges,
                                 int capacity);

#ifdef __cplusplus
}
#endif

#endif
