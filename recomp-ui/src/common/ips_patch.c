// ips_patch.c — classic IPS patch format implementation. See ips_patch.h.

#include "ips_patch.h"

#include <stdlib.h>
#include <string.h>

// Grow `*buf` (currently `*cap` bytes) so it holds at least `need` bytes,
// doubling capacity as needed (patches are small; ROMs are a few MB at most,
// so this never loops more than ~20 times). Returns false on OOM, in which
// case `*buf`/`*cap` are left as they were (still valid, still owned).
static bool ips_grow(uint8_t** buf, size_t* cap, size_t need) {
    if (need <= *cap) return true;
    size_t ncap = *cap ? *cap : 4096;
    while (ncap < need) ncap *= 2;
    uint8_t* nb = (uint8_t*)realloc(*buf, ncap);
    if (!nb) return false;
    *buf = nb;
    *cap = ncap;
    return true;
}

bool ips_apply(const uint8_t* src, size_t src_len,
               const uint8_t* patch, size_t patch_len,
               uint8_t** out_data, size_t* out_len) {
    if (!patch || patch_len < 8 || memcmp(patch, "PATCH", 5) != 0) return false;

    size_t cap = src_len ? src_len : 4096;
    uint8_t* out = (uint8_t*)malloc(cap);
    if (!out) return false;
    size_t len = src_len;
    if (src && src_len) memcpy(out, src, src_len);

    size_t i = 5;
    while (i + 3 <= patch_len) {
        if (memcmp(patch + i, "EOF", 3) == 0) {
            *out_data = out;
            *out_len  = len;
            return true;
        }

        // 24-bit big-endian offset.
        size_t off = ((size_t)patch[i] << 16) | ((size_t)patch[i + 1] << 8) | patch[i + 2];
        i += 3;

        if (i + 2 > patch_len) { free(out); return false; }
        // 16-bit big-endian length. len==0 introduces an RLE record instead.
        size_t rec_len = ((size_t)patch[i] << 8) | patch[i + 1];
        i += 2;

        if (rec_len == 0) {
            if (i + 3 > patch_len) { free(out); return false; }
            size_t run = ((size_t)patch[i] << 8) | patch[i + 1];
            i += 2;
            uint8_t val = patch[i++];
            size_t need = off + run;
            if (!ips_grow(&out, &cap, need)) { free(out); return false; }
            if (need > len) { memset(out + len, 0, need - len); len = need; }
            memset(out + off, val, run);
        } else {
            if (i + rec_len > patch_len) { free(out); return false; }
            size_t need = off + rec_len;
            if (!ips_grow(&out, &cap, need)) { free(out); return false; }
            if (need > len) { memset(out + len, 0, need - len); len = need; }
            memcpy(out + off, patch + i, rec_len);
            i += rec_len;
        }
    }

    // No EOF marker, but every record parsed cleanly — matches the reference
    // launcher_gui.cpp behavior (still a successful patch).
    *out_data = out;
    *out_len  = len;
    return true;
}
