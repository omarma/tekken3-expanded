/* android_apk_file.c — disc images read in place from the APK (Android).
 *
 * The APK stores the disc's track files (.bin) uncompressed. Instead of
 * copying ~700 MB out of it after each install, the app (GameData.java)
 * leaves a placeholder at the file's usual path in the data folder: a sparse
 * file of the track's exact size whose first bytes say where the track lies
 * in the APK:
 *
 *     psxrecomp-apk-slice\n
 *     <offset> <length>\n
 *     <path of the APK>\n
 *
 * Everything else on disk is zeros that take no space. The placeholder keeps
 * every path-based check working as on PC (exists, file size, directory
 * listings, the cue's FILE lines), and the reads are redirected here: the
 * runtime is linked with -Wl,--wrap=fopen (runtime.cmake), so every fopen in
 * libmain.so — the runtime's own, and the std::ifstream of the static C++
 * library, which opens through fopen — comes through __wrap_fopen. A
 * placeholder opened for reading becomes a stdio stream over that range of
 * the APK; any other file opens normally.
 *
 * A packed track (tools/android/disc_pack.py: the disc stored losslessly
 * compressed in the APK) has a placeholder of the same kind with another
 * first line, psxrecomp-apk-pack, whose range is the packed file; the
 * placeholder still has the size of the original track, and its stream reads
 * the original bytes, unpacked block by block (disc_pack.c). Other files read
 * in place (the mods' PNG textures) are plain slices.
 *
 * Each stream has its own descriptor and position and reads with pread, so
 * streams on the same track can be read from several threads at once.
 * Offsets are 64-bit throughout: the game is built for arm64 only, where
 * off_t and fpos_t are 64-bit (checked below).
 */
#define _BSD_SOURCE   /* funopen */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "android_apk_file.h"
#include "disc_pack.h"

#define APK_SLICE_MAGIC "psxrecomp-apk-slice\n"
#define APK_PACK_MAGIC "psxrecomp-apk-pack\n"
#define APK_SLICE_HEADER_MAX 4096

/* A decimal number in [p, end), digits only (no sign, no spaces), that fits
 * 64 bits; *next is the byte after it. The header is not NUL-terminated, so
 * strtoull, which reads on until a non-digit, cannot be used on it. */
static int parse_u64(const char* p, const char* end, uint64_t* value, const char** next)
{
    uint64_t v = 0;
    const char* start = p;
    for (; p < end && *p >= '0' && *p <= '9'; ++p) {
        const unsigned digit = (unsigned)(*p - '0');
        if (v > (UINT64_MAX - digit) / 10) return 0;
        v = v * 10 + digit;
    }
    if (p == start) return 0;
    *value = v;
    *next = p;
    return 1;
}

int psx_apk_slice_parse(const char* header, size_t size, char* apk, size_t apk_size,
                        uint64_t* offset, uint64_t* length, int* packed)
{
    const size_t slice = sizeof(APK_SLICE_MAGIC) - 1, pack = sizeof(APK_PACK_MAGIC) - 1;
    size_t magic;
    if (size >= slice && memcmp(header, APK_SLICE_MAGIC, slice) == 0) {
        magic = slice;
        *packed = 0;
    } else if (size >= pack && memcmp(header, APK_PACK_MAGIC, pack) == 0) {
        magic = pack;
        *packed = 1;
    } else {
        return 0;
    }
    const char* p = header + magic;
    const char* end = header + size;
    const char* next;
    uint64_t off, len;
    if (!parse_u64(p, end, &off, &next) || next >= end || *next != ' ') return 0;
    p = next + 1;
    if (!parse_u64(p, end, &len, &next) || next >= end || *next != '\n') return 0;
    p = next + 1;
    const char* eol = memchr(p, '\n', (size_t)(end - p));
    if (!eol || eol == p || (size_t)(eol - p) >= apk_size) return 0;
    memcpy(apk, p, (size_t)(eol - p));
    apk[eol - p] = '\0';
    *offset = off;
    *length = len;
    return 1;
}

/* The rest is Android's (funopen, 64-bit fpos_t); PSX_APK_SLICE_PARSE_ONLY
 * builds the parser alone, for its desktop test (tools/android/test_apk_slice.py). */
#ifndef PSX_APK_SLICE_PARSE_ONLY

_Static_assert(sizeof(off_t) == 8 && sizeof(fpos_t) == 8, "64-bit file offsets");

FILE* __real_fopen(const char* path, const char* mode);

typedef struct {
    int       fd;
    uint64_t  offset;   /* where the file starts in the APK */
    uint64_t  length;   /* of the file the stream reads */
    uint64_t  pos;      /* within the file */
    DiscPack* pack;     /* a packed track: read through it */
} ApkSlice;

/* 1 when `path` is a placeholder; fills the APK range it stands for, and the
 * size of the file it stands for (`size`: the placeholder's own). */
static int read_placeholder(const char* path, char* apk, size_t apk_size,
                            uint64_t* offset, uint64_t* length, int* packed, uint64_t* size)
{
    struct stat st;
    if (stat(path, &st) != 0 || !S_ISREG(st.st_mode)) return 0;
    if (st.st_size < APK_SLICE_HEADER_MAX) return 0;

    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    char header[APK_SLICE_HEADER_MAX];
    ssize_t got = pread(fd, header, sizeof(header), 0);
    close(fd);
    if (got <= 0) return 0;
    if (!psx_apk_slice_parse(header, (size_t)got, apk, apk_size, offset, length, packed))
        return 0;
    *size = (uint64_t)st.st_size;
    /* A placeholder always has the size of what it stands for (a packed
     * track's is checked against the packed file's header when it opens). */
    return *packed || *length == *size;
}

static int slice_read(void* cookie, char* buf, int n)
{
    ApkSlice* s = (ApkSlice*)cookie;
    if (n <= 0 || s->pos >= s->length) return 0;
    if (s->pack) {
        int64_t got = disc_pack_read(s->pack, s->pos, buf, (size_t)n);
        if (got < 0) return -1;
        s->pos += (uint64_t)got;
        return (int)got;
    }
    uint64_t want = (uint64_t)n;
    if (want > s->length - s->pos) want = s->length - s->pos;
    ssize_t got;
    do {
        got = pread(s->fd, buf, (size_t)want, (off_t)(s->offset + s->pos));
    } while (got < 0 && errno == EINTR);
    if (got < 0) return -1;
    s->pos += (uint64_t)got;
    return (int)got;
}

static fpos_t slice_seek(void* cookie, fpos_t where, int whence)
{
    ApkSlice* s = (ApkSlice*)cookie;
    int64_t base;
    switch (whence) {
    case SEEK_SET: base = 0; break;
    case SEEK_CUR: base = (int64_t)s->pos; break;
    case SEEK_END: base = (int64_t)s->length; break;
    default: errno = EINVAL; return -1;
    }
    int64_t to = base + (int64_t)where;
    if (to < 0) { errno = EINVAL; return -1; }
    s->pos = (uint64_t)to;   /* past the end reads as end of file */
    return (fpos_t)to;
}

static int slice_close(void* cookie)
{
    ApkSlice* s = (ApkSlice*)cookie;
    disc_pack_close(s->pack);
    int result = close(s->fd);
    free(s);
    return result;
}

FILE* psx_apk_slice_open(const char* apk, uint64_t offset, uint64_t length)
{
    return psx_apk_file_open(apk, offset, length, 0, 0);
}

FILE* psx_apk_file_open(const char* apk, uint64_t offset, uint64_t length, int packed,
                        uint64_t size)
{
    int fd = open(apk, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return NULL;
    struct stat st;
    if (fstat(fd, &st) != 0 || offset > (uint64_t)st.st_size ||
        length > (uint64_t)st.st_size - offset) {
        /* Not the APK the placeholder was made for: fail rather than
         * hand out the wrong bytes. */
        close(fd);
        errno = EIO;
        return NULL;
    }
    ApkSlice* s = (ApkSlice*)calloc(1, sizeof(*s));
    if (!s) {
        close(fd);
        errno = ENOMEM;
        return NULL;
    }
    s->fd = fd;
    s->offset = offset;
    s->length = length;
    if (packed) {
        s->pack = disc_pack_open(fd, offset, length);
        if (!s->pack || disc_pack_size(s->pack) != size) {
            /* Damaged, or not the track the placeholder was made for. */
            slice_close(s);
            errno = EIO;
            return NULL;
        }
        s->length = size;
    }
    FILE* f = funopen(s, slice_read, NULL, slice_seek, slice_close);
    if (!f) slice_close(s);
    return f;
}

FILE* __wrap_fopen(const char* path, const char* mode)
{
    /* Only read-only opens are redirected; the APK cannot be written. */
    if (path && mode && mode[0] == 'r' && !strchr(mode, '+')) {
        char apk[APK_SLICE_HEADER_MAX];
        uint64_t offset, length, size;
        int packed;
        if (read_placeholder(path, apk, sizeof(apk), &offset, &length, &packed, &size)) {
            FILE* f = psx_apk_file_open(apk, offset, length, packed, size);
            if (!f) {
                fprintf(stderr, "[apk] %s: cannot read it from %s (%s)\n",
                        path, apk, strerror(errno));
            }
            return f;
        }
    }
    return __real_fopen(path, mode);
}

/* bionic's fopen64 is the same function under another name. */
FILE* __wrap_fopen64(const char* path, const char* mode)
{
    return __wrap_fopen(path, mode);
}

#endif /* PSX_APK_SLICE_PARSE_ONLY */
