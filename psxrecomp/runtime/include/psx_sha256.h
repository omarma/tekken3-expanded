#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct psx_sha256_ctx {
    uint32_t h[8];
    uint64_t total;
    uint8_t buffer[64];
    size_t buffered;
} psx_sha256_ctx;

/* Self-contained public-domain SHA-256 implementation. */
void psx_sha256_init(psx_sha256_ctx* ctx);
void psx_sha256_update(psx_sha256_ctx* ctx, const uint8_t* data, size_t len);
void psx_sha256_final(psx_sha256_ctx* ctx, uint8_t out[32]);
void psx_sha256_compute(const uint8_t *data, size_t len, uint8_t out[32]);

#ifdef __cplusplus
}
#endif
