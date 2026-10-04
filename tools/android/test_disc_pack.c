/* test_disc_pack.c — the runtime's packed-track reader (disc_pack.c), checked
 * against the original tracks, byte for byte. Built and run by
 * test_disc_pack.py, natively and for arm64 Android under qemu.
 *
 * Usage: test_disc_pack [--ecc-check] <packed> <original> [<packed> <original>]...
 * For each pair: every sector read back in order, then random reads of any
 * size and position (block edges, the end, past the end), the decode time per
 * sector, and with --ecc-check, every Mode 2 Form 1 sector's ECC verified by
 * libchdr's own ecc_verify (MAME's code, independent of disc_pack.c).
 */
#include "disc_pack.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifdef WITH_LIBCHDR
int ecc_verify(const uint8_t* sector);
#endif

static int g_failures;

#define FAIL(...) do { ++g_failures; fprintf(stderr, "FAIL: " __VA_ARGS__); fputc('\n', stderr); } while (0)

static uint8_t* slurp(const char* path, size_t* size)
{
    FILE* f = fopen(path, "rb");
    if (!f) return NULL;
    fseeko(f, 0, SEEK_END);
    *size = (size_t)ftello(f);
    fseeko(f, 0, SEEK_SET);
    uint8_t* data = (uint8_t*)malloc(*size ? *size : 1);
    if (data && fread(data, 1, *size, f) != *size) { free(data); data = NULL; }
    fclose(f);
    return data;
}

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static uint64_t s_rng = 88172645463325252ull;
static uint64_t rnd(void)
{
    s_rng ^= s_rng << 13; s_rng ^= s_rng >> 7; s_rng ^= s_rng << 17;
    return s_rng;
}

static void check(const char* packed_path, const char* original_path, int ecc_check)
{
    size_t size = 0;
    uint8_t* want = slurp(original_path, &size);
    if (!want) { FAIL("cannot read %s", original_path); return; }
    size_t packed_size = 0;
    uint8_t* packed = slurp(packed_path, &packed_size);
    if (!packed) { FAIL("cannot read %s", packed_path); free(want); return; }

    /* Inside a bigger file at an odd offset, as in the APK. */
    char container[] = "/tmp/disc_pack_apk_XXXXXX";
    int fd = mkstemp(container);
    const uint64_t offset = 4099;
    uint8_t filler[4099];
    memset(filler, 0xA5, sizeof(filler));
    if (fd < 0 || write(fd, filler, sizeof(filler)) != (ssize_t)sizeof(filler) ||
        write(fd, packed, packed_size) != (ssize_t)packed_size ||
        write(fd, filler, 77) != 77) {
        FAIL("cannot write %s", container);
        free(packed); free(want); return;
    }
    unlink(container);
    free(packed);
    DiscPack* pack = disc_pack_open(fd, offset, (uint64_t)packed_size);
    if (!pack) { FAIL("disc_pack_open %s: %s", packed_path, strerror(errno)); close(fd); free(want); return; }
    if (disc_pack_size(pack) != size) FAIL("%s: size %llu, want %zu", packed_path,
                                           (unsigned long long)disc_pack_size(pack), size);

    /* Every sector, in order (the CD-ROM's reads). */
    uint8_t sector[2352];
    const size_t sectors = (size + 2351) / 2352;
    size_t bad = 0, form1 = 0;
    const double start = now();
    for (size_t s = 0; s < sectors; ++s) {
        const size_t length = size - s * 2352 < 2352 ? size - s * 2352 : 2352;
        if (disc_pack_read(pack, (uint64_t)s * 2352, sector, 2352) != (int64_t)length ||
            memcmp(sector, want + s * 2352, length) != 0) {
            if (bad++ < 5) FAIL("%s: sector %zu differs", packed_path, s);
        }
    }
    const double elapsed = now() - start;
    if (ecc_check) {
#ifdef WITH_LIBCHDR
        for (size_t s = 0; s + 1 <= size / 2352; ++s) {
            const uint8_t* p = want + s * 2352;
            if (p[1] == 0xFF && p[15] == 2 && !(p[18] & 0x20)) {
                ++form1;
                if (!ecc_verify(p) && bad++ < 5) FAIL("%s: libchdr: sector %zu's ECC is wrong", packed_path, s);
            }
        }
#endif
    }

    /* Random reads: any size, any position, past the end too. */
    uint8_t* buf = (uint8_t*)malloc(200000);
    for (int i = 0; i < 3000; ++i) {
        uint64_t at;
        switch (i % 4) {
        case 0: at = rnd() % (size + 5000); break;
        case 1: at = (rnd() % (sectors / 16 + 1)) * 16 * 2352 - (rnd() % 3); break;  /* block edges */
        case 2: at = size > 7000 ? size - rnd() % 7000 : rnd() % (size + 1); break;  /* the end */
        default: at = (rnd() % sectors) * 2352; break;
        }
        if (at > size + 5000) at = 0;
        const size_t length = (size_t)(rnd() % (i % 10 == 0 ? 200000 : 6000));
        const int64_t got = disc_pack_read(pack, at, buf, length);
        const size_t expect = at >= size ? 0 : (size - at < length ? (size_t)(size - at) : length);
        if (got != (int64_t)expect || (expect && memcmp(buf, want + at, expect) != 0)) {
            FAIL("%s: read %zu at %llu: got %lld, want %zu", packed_path, length,
                 (unsigned long long)at, (long long)got, expect);
            break;
        }
    }
    free(buf);
    disc_pack_close(pack);
    close(fd);
    free(want);
    printf("ok  %s: %zu sectors, %zu bytes -> %lld bytes (%.1f%%), %.1f us per sector",
           packed_path, sectors, size, (long long)packed_size, 100.0 * (double)packed_size / (double)size,
           1e6 * elapsed / (double)sectors);
    if (ecc_check) printf(", %zu Form 1 sectors verified by libchdr", form1);
    printf("\n");
}

int main(int argc, char** argv)
{
    int i = 1, ecc_check = 0;
    if (i < argc && strcmp(argv[i], "--ecc-check") == 0) { ecc_check = 1; ++i; }
    if (argc - i < 2 || (argc - i) % 2) {
        fprintf(stderr, "usage: %s [--ecc-check] <packed> <original>...\n", argv[0]);
        return 2;
    }
    for (; i + 1 < argc; i += 2) check(argv[i], argv[i + 1], ecc_check);

    /* Damaged input fails cleanly instead of returning wrong bytes. */
    {
        char path[] = "/tmp/disc_pack_bad_XXXXXX";
        int fd = mkstemp(path);
        uint8_t junk[4096] = "PSXPACK1";
        junk[8] = 0x10;   /* size 16, but nothing else valid */
        if (fd >= 0 && write(fd, junk, sizeof(junk)) == (ssize_t)sizeof(junk)) {
            DiscPack* pack = disc_pack_open(fd, 0, sizeof(junk));
            if (pack) FAIL("a damaged header opened");
            disc_pack_close(pack);
        }
        if (fd >= 0) { close(fd); unlink(path); }
    }
    /* Headers whose numbers overflow: a size near 2^64 (its sector count
     * wraps to 0, so 0 blocks matched and reads went past the index), and
     * 2^32 - 1 blocks (blocks + 1 wrapped to an index of 0 bytes). */
    {
        static const struct { uint64_t size; uint32_t per_block, blocks; } bad[] = {
            { UINT64_MAX - 100, 16, 0 },
            { (uint64_t)0xFFFFFFFFu * 2352, 1, 0xFFFFFFFFu },
        };
        for (size_t k = 0; k < sizeof(bad) / sizeof(bad[0]); ++k) {
            char path[] = "/tmp/disc_pack_bad_XXXXXX";
            int fd = mkstemp(path);
            uint8_t junk[4096] = "PSXPACK1";
            for (int b = 0; b < 8; ++b) junk[8 + b] = (uint8_t)(bad[k].size >> (8 * b));
            const uint32_t fields[] = { 2352, bad[k].per_block, bad[k].blocks, 0, 64 };
            for (int f = 0; f < 5; ++f)
                for (int b = 0; b < 4; ++b) junk[16 + 4 * f + b] = (uint8_t)(fields[f] >> (8 * b));
            junk[64] = 72;   /* index[0]: the first block right after a 1-entry index */
            if (fd >= 0 && write(fd, junk, sizeof(junk)) == (ssize_t)sizeof(junk)) {
                DiscPack* pack = disc_pack_open(fd, 0, sizeof(junk));
                if (pack) FAIL("a header with overflowing numbers opened (case %zu)", k);
                disc_pack_close(pack);
            }
            if (fd >= 0) { close(fd); unlink(path); }
        }
    }
    printf("%d failures\n", g_failures);
    return g_failures ? 1 : 0;
}
