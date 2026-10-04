/* hd_png.c — PNG decoding for the HD texture packs (gpu_gl_renderer.c).
 *
 * The packs' textures are RGBA images, HDRGBA01 files (<name>.rgba) on PC.
 * The Android APK ships their PNG instead (built on Android only) (tools/android/build_apk.py checks
 * that each decodes to exactly the .rgba's pixels): about a quarter of the
 * size, decoded when the texture loads. stb_image, as the launcher uses it
 * (recomp-ui), with only its PNG decoder. */
#include "hd_png.h"

#define STB_IMAGE_STATIC
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#define STBI_NO_LINEAR
#define STBI_NO_HDR
/* No texture is bigger (hd_size_ok in gpu_gl_renderer.c): a bigger PNG is
 * refused before stb allocates for it (a tiny PNG can claim gigabytes). */
#define HD_PNG_MAX_SIDE 8192
#define HD_PNG_MAX_PIXELS (8192u * 2048u)
#define STBI_MAX_DIMENSIONS HD_PNG_MAX_SIDE
/* stb's static API: most of it unused here. */
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "stb_image.h"

unsigned char* hd_png_decode(const unsigned char* data, size_t size,
                             uint32_t* width, uint32_t* height)
{
    int w = 0, h = 0, channels = 0;
    if (size > 0x7FFFFFFF) return NULL;
    if (!stbi_info_from_memory(data, (int)size, &w, &h, &channels) || w <= 0 || h <= 0 ||
        w > HD_PNG_MAX_SIDE || h > HD_PNG_MAX_SIDE ||
        (uint64_t)w * (uint64_t)h > HD_PNG_MAX_PIXELS)
        return NULL;
    unsigned char* pixels = stbi_load_from_memory(data, (int)size, &w, &h, &channels, 4);
    if (!pixels) return NULL;
    *width = (uint32_t)w;
    *height = (uint32_t)h;
    return pixels;
}
