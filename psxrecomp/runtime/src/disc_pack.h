/* disc_pack.h — random access to a packed disc track (Android's APK).
 * See disc_pack.c and tools/android/disc_pack.py (the format). */
#ifndef PSXRECOMP_DISC_PACK_H
#define PSXRECOMP_DISC_PACK_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DISC_PACK_MAGIC "PSXPACK1"
#define DISC_PACK_HEADER_SIZE 64

typedef struct DiscPack DiscPack;

/* The size of the original track when `header` (at least 16 bytes) starts a
 * packed track; 0 otherwise. */
uint64_t disc_pack_probe(const void* header, size_t size);

/* Opens the packed track stored at [offset, offset + length) of the file open
 * on `fd` (read with pread; the caller keeps the descriptor open until
 * disc_pack_close). NULL, with errno set, when it is not a valid packed track. */
DiscPack* disc_pack_open(int fd, uint64_t offset, uint64_t length);

/* The size of the original track. */
uint64_t disc_pack_size(const DiscPack* pack);

/* Reads up to `size` bytes of the original track from `position` (fewer at
 * its end, 0 past it); -1 with errno set on a read or format error. Keeps the
 * last block it decoded, so sequential reads decode each block once. One
 * DiscPack is not to be used by two threads at once (open one per stream). */
int64_t disc_pack_read(DiscPack* pack, uint64_t position, void* buffer, size_t size);

void disc_pack_close(DiscPack* pack);

#ifdef __cplusplus
}
#endif

#endif
