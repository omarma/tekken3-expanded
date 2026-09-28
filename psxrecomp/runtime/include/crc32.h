#pragma once
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Compute CRC32 (IEEE 802.3) over a byte buffer. */
uint32_t crc32_compute(const uint8_t *data, size_t len);

/* Incremental CRC32. Start from 0xFFFFFFFF, fold each chunk through
 * crc32_update, then XOR the final running value with 0xFFFFFFFF. The result
 * equals crc32_compute over the concatenation of the same chunks. */
uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
