/* test_png_textures.c — the PNG the APK ships for each texture, decoded by
 * the runtime's hd_png.c, against its .rgba. Run by test_png_textures.py.
 * Usage: test_png_textures [--refuse <png>]... <png> <rgba> [<png> <rgba>]...
 * --refuse: a PNG bigger than any texture, which must not decode. */
#include "hd_png.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static unsigned char* slurp(const char* path, size_t* size)
{
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    *size = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char* data = (unsigned char*)malloc(*size ? *size : 1);
    if (data && fread(data, 1, *size, f) != *size) { free(data); data = NULL; }
    fclose(f);
    return data;
}

int main(int argc, char** argv)
{
    int failures = 0;
    double total_ms = 0, total_png = 0, total_rgba = 0;
    int first = 1;
    for (; first + 1 < argc && strcmp(argv[first], "--refuse") == 0; first += 2) {
        size_t png_size = 0;
        unsigned char* png = slurp(argv[first + 1], &png_size);
        uint32_t w = 0, h = 0;
        unsigned char* pixels = png ? hd_png_decode(png, png_size, &w, &h) : NULL;
        const int ok = png && !pixels;
        printf("%s  %s: %s\n", ok ? "ok  " : "FAIL", argv[first + 1],
               ok ? "refused" : "decoded, or unreadable");
        failures += !ok;
        free(pixels); free(png);
    }
    for (int i = first; i + 1 < argc; i += 2) {
        size_t png_size = 0, rgba_size = 0;
        unsigned char* png = slurp(argv[i], &png_size);
        unsigned char* rgba = slurp(argv[i + 1], &rgba_size);
        uint32_t w = 0, h = 0, want_w = 0, want_h = 0;
        if (rgba && rgba_size >= 16) { memcpy(&want_w, rgba + 8, 4); memcpy(&want_h, rgba + 12, 4); }
        struct timespec a, b;
        clock_gettime(CLOCK_MONOTONIC, &a);
        unsigned char* pixels = png ? hd_png_decode(png, png_size, &w, &h) : NULL;
        clock_gettime(CLOCK_MONOTONIC, &b);
        const double ms = (double)(b.tv_sec - a.tv_sec) * 1e3 + (double)(b.tv_nsec - a.tv_nsec) / 1e6;
        const int ok = pixels && rgba && w == want_w && h == want_h &&
                       rgba_size == 16 + (size_t)w * h * 4 &&
                       memcmp(pixels, rgba + 16, (size_t)w * h * 4) == 0;
        printf("%s  %s: %ux%u, %zu bytes of PNG for %zu of .rgba, decoded in %.1f ms\n",
               ok ? "ok  " : "FAIL", argv[i], w, h, png_size, rgba_size, ms);
        failures += !ok;
        total_ms += ms;
        total_png += (double)png_size;
        total_rgba += (double)rgba_size;
        free(pixels); free(png); free(rgba);
    }
    printf("%d textures: %.1f MB of PNG for %.1f MB of .rgba, decoded in %.0f ms in all; %d failures\n",
           (argc - first) / 2, total_png / 1e6, total_rgba / 1e6, total_ms, failures);
    return failures ? 1 : 0;
}
