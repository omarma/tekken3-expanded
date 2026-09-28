// memcard_format.c — standalone PS1 memory-card blank-image formatter.
// See memcard_format.h. Self-contained: no dependency on any host recomp
// project's runtime headers.

#include "memcard_format.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// XOR checksum of a frame's first 127 bytes, stored at byte 0x7F.
static uint8_t recompui_memcard_frame_checksum(const uint8_t* frame) {
    uint8_t xor_val = 0;
    for (int i = 0; i < 127; ++i) xor_val ^= frame[i];
    return xor_val;
}

// Fill `data` (RECOMPUI_MEMCARD_SIZE bytes) with a blank-formatted card image.
static void recompui_memcard_format(uint8_t* data) {
    memset(data, 0xFF, RECOMPUI_MEMCARD_SIZE);

    // Frame 0: header ("MC" magic).
    memset(&data[0], 0x00, 128);
    data[0] = 'M';
    data[1] = 'C';
    data[0x7F] = recompui_memcard_frame_checksum(&data[0]);

    // Frames 1-15: directory entries, all free.
    for (int s = 1; s <= 15; ++s) {
        int off = s * 128;
        memset(&data[off], 0x00, 128);
        data[off + 0] = 0xA0;  // status: free/available
        data[off + 8] = 0xFF;  // next block pointer = none
        data[off + 9] = 0xFF;
        data[off + 0x7F] = recompui_memcard_frame_checksum(&data[off]);
    }

    // Frames 16-35: broken sector list, no broken sectors.
    for (int s = 16; s <= 35; ++s) {
        int off = s * 128;
        memset(&data[off], 0x00, 128);
        data[off + 0] = 0xFF;
        data[off + 1] = 0xFF;
        data[off + 2] = 0xFF;
        data[off + 3] = 0xFF;
        data[off + 8] = 0xFF;
        data[off + 9] = 0xFF;
        data[off + 0x7F] = recompui_memcard_frame_checksum(&data[off]);
    }

    // Frames 36-62: broken sector replacement data + unused, zeroed.
    for (int s = 36; s <= 62; ++s) {
        memset(&data[s * 128], 0x00, 128);
    }

    // Frame 63: write-test frame (copy of frame 0).
    memcpy(&data[63 * 128], &data[0], 128);
}

int recompui_memcard_format_file(const char* path) {
    if (!path || !path[0]) return -1;

    uint8_t* data = (uint8_t*)malloc(RECOMPUI_MEMCARD_SIZE);
    if (!data) return -1;
    recompui_memcard_format(data);

    int ok = 0;
    FILE* f = fopen(path, "wb");
    if (f) {
        size_t n = fwrite(data, 1, RECOMPUI_MEMCARD_SIZE, f);
        int flush_ok = (fflush(f) == 0);
        int close_ok = (fclose(f) == 0);
        ok = (n == RECOMPUI_MEMCARD_SIZE && flush_ok && close_ok);
    }
    free(data);
    return ok ? 0 : -1;
}
