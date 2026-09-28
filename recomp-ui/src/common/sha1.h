// sha1.h — bundled SHA-1 (recomp-ui is self-contained).
//
// Many cartridge consoles (GBA, SNES) gate ROM identity on SHA-1 — the same
// 40-hex fingerprint the game runtime verifies. The launcher computes it over
// the picked ROM so its "verified" check matches the runtime's real gate
// (crc32.c / sha256.c cover the consoles that fingerprint those instead).

#ifndef RECOMPUI_SHA1_H
#define RECOMPUI_SHA1_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Compute the SHA-1 digest of `len` bytes at `data` into out[20].
void recompui_sha1_compute(const uint8_t* data, size_t len, uint8_t out[20]);

// Format a 20-byte digest as 40 lowercase hex chars + NUL (out[41]).
void recompui_sha1_hex(const uint8_t digest[20], char out[41]);

#ifdef __cplusplus
}
#endif

#endif  // RECOMPUI_SHA1_H
