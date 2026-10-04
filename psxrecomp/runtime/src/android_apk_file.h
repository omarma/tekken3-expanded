/* android_apk_file.h — disc images read in place from the APK (Android).
 * See android_apk_file.c. */
#ifndef PSXRECOMP_ANDROID_APK_FILE_H
#define PSXRECOMP_ANDROID_APK_FILE_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Parses a placeholder's header; 1 on success. *packed: 1 for a packed track
 * (psxrecomp-apk-pack), 0 for a plain slice (psxrecomp-apk-slice). */
int psx_apk_slice_parse(const char* header, size_t size, char* apk, size_t apk_size,
                        uint64_t* offset, uint64_t* length, int* packed);

/* A read-only stdio stream over `length` bytes of `apk` from `offset`. */
FILE* psx_apk_slice_open(const char* apk, uint64_t offset, uint64_t length);

/* The same, or with `packed`, a stream of the `size`-byte track packed in
 * that range (disc_pack.c); NULL when the packed track is not that size. */
FILE* psx_apk_file_open(const char* apk, uint64_t offset, uint64_t length, int packed,
                        uint64_t size);

#ifdef __cplusplus
}
#endif

#endif
