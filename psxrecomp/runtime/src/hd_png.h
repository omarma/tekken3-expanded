/* hd_png.h — PNG decoding for the HD texture packs. See hd_png.c. */
#ifndef PSXRECOMP_HD_PNG_H
#define PSXRECOMP_HD_PNG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* RGBA pixels (8 bits per channel, rows top to bottom) of a PNG in memory,
 * or NULL; free them with free(). */
unsigned char* hd_png_decode(const unsigned char* data, size_t size,
                             uint32_t* width, uint32_t* height);

#ifdef __cplusplus
}
#endif

#endif
