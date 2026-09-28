#include "debug_trace_ranges.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
    PSXDebugTraceRange ranges[3] = {{0}};
    int count;

    assert(psx_debug_parse_trace_ranges(NULL, ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("", ranges, 3) == 0);
    assert(psx_debug_parse_trace_ranges("  ", ranges, 3) == 0);

    count = psx_debug_parse_trace_ranges(
        "0x000B3A80,0x000B3B00", ranges, 3);
    assert(count == 1);
    assert(ranges[0].lo == 0x000B3A80u);
    assert(ranges[0].hi == 0x000B3B00u);

    count = psx_debug_parse_trace_ranges(
        " 0x800B3A80 , 0x800B3B00 ; 4096, 4352 ", ranges, 3);
    assert(count == 2);
    assert(ranges[0].lo == 0x000B3A80u);
    assert(ranges[0].hi == 0x000B3B00u);
    assert(ranges[1].lo == 4096u);
    assert(ranges[1].hi == 4352u);

    assert(psx_debug_parse_trace_ranges("1,1", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("2,1", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("-1,2", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("1", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("1,2;", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("1,2x", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges(
        "0x100000000,0x100000001", ranges, 3) == -1);
    assert(psx_debug_parse_trace_ranges("1,2;3,4", ranges, 1) == -2);

    puts("debug trace range parser: ok");
    return 0;
}
