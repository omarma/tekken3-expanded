// ips_patch.h — classic IPS patch format (PATCH...EOF, 24-bit offsets).
//
// Pure algorithm, no file I/O (mirrors the crc32.c/sha256.c "bundled engine
// helper" pattern) — ported from the legacy SNES launcher's ips_apply()
// (snesrecomp/runner/src/launcher/launcher_gui.cpp) so recomp-ui's MSU-1
// dashboard flow (launcher_model_apply_msu1_patch, launcher_model.c) can
// write a patched ROM from a vanilla ROM + a game-supplied .ips file.

#ifndef LAUNCHER_NG_IPS_PATCH_H
#define LAUNCHER_NG_IPS_PATCH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Apply an IPS patch onto `src` (src_len bytes; may be NULL/0 for an empty
// source — a patch may still build a whole file from scratch via its
// records). On success, mallocs *out_data (*out_len bytes) — the CALLER
// frees it with free(). Returns false and leaves *out_data/*out_len
// untouched on a malformed patch (bad magic, truncated record, or overlong
// record that runs past the patch buffer).
//
// Supports both normal (literal-data) and RLE (run-length, len-field == 0)
// records. A patch with no trailing "EOF" marker but otherwise well-formed
// records still succeeds (matches the reference implementation).
bool ips_apply(const uint8_t* src, size_t src_len,
               const uint8_t* patch, size_t patch_len,
               uint8_t** out_data, size_t* out_len);

#ifdef __cplusplus
}
#endif

#endif // LAUNCHER_NG_IPS_PATCH_H
