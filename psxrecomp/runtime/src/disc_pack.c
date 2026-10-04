/* disc_pack.c — random access to a packed disc track (Android's APK).
 *
 * The APK carries the disc's tracks packed losslessly by
 * tools/android/disc_pack.py (format described there): blocks of 16 sectors,
 * each deflated, with what can be computed back left out — the sync and
 * header of Mode 2 sectors, the subheader's copy, the EDC and ECC, the
 * duplicated halves of XA sound group headers, all-zero sectors. CD audio is
 * stored as sample differences. The packer keeps a sector in such a form only
 * when computing it back gives exactly the original bytes; this file computes
 * them back, so a read returns the original track byte for byte.
 *
 * android_apk_file.c opens one DiscPack per stdio stream of a packed track.
 * Each keeps the block it decoded last: a CD read (75 or 150 sectors a
 * second) decodes a 16-sector block about 5 to 10 times a second.
 */
#include "disc_pack.h"

#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <zlib.h>

#define SECTOR 2352
#define MAX_SECTORS_PER_BLOCK 1024

enum { RAW, ZERO, FORM1, FORM2, FORM2_NOEDC, XA, XA_NOEDC, AUDIO, KINDS };

#define XA_GROUPS 18

struct DiscPack {
    int       fd;
    uint64_t  offset;           /* where the packed track starts in the file */
    uint64_t  size;             /* of the original track */
    uint32_t  per_block;
    uint32_t  blocks;
    uint32_t  base;             /* address (MSF frame) of sector 0 */
    uint64_t* index;            /* blocks + 1 offsets */
    uint8_t*  packed;           /* a block as stored */
    size_t    packed_size;
    uint8_t*  payload;          /* a block inflated: types, then bodies */
    uint8_t*  block;            /* a block of the original track */
    int64_t   cached;           /* the block in `block`, or -1 */
    z_stream  z;
    int       z_ready;
};

/* --- EDC and ECC (ECMA-130) ---------------------------------------------- */

static uint32_t s_edc[256];
static uint8_t  s_ecc_f[256], s_ecc_b[256];
static pthread_once_t s_tables_once = PTHREAD_ONCE_INIT;

static void make_tables(void)
{
    for (uint32_t i = 0; i < 256; ++i) {
        uint32_t c = i;
        for (int k = 0; k < 8; ++k) c = (c >> 1) ^ ((c & 1) ? 0xD8018001u : 0);
        s_edc[i] = c;
        uint32_t f = (i << 1) ^ ((i & 0x80) ? 0x11D : 0);
        s_ecc_f[i] = (uint8_t)f;
        s_ecc_b[i ^ (uint8_t)f] = (uint8_t)i;
    }
}

static uint32_t edc(const uint8_t* data, size_t size)
{
    uint32_t crc = 0;
    for (size_t i = 0; i < size; ++i) crc = (crc >> 8) ^ s_edc[(crc ^ data[i]) & 0xFF];
    return crc;
}

static void put32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint64_t get64(const uint8_t* p)
{
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = v << 8 | p[i];
    return v;
}

static uint32_t get32(const uint8_t* p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void ecc_block(const uint8_t* src, uint32_t major_count, uint32_t minor_count,
                      uint32_t major_mult, uint32_t minor_inc, uint8_t* dest)
{
    const uint32_t size = major_count * minor_count;
    for (uint32_t major = 0; major < major_count; ++major) {
        uint32_t index = (major >> 1) * major_mult + (major & 1);
        uint8_t a = 0, b = 0;
        for (uint32_t minor = 0; minor < minor_count; ++minor) {
            const uint8_t t = src[index];
            index += minor_inc;
            if (index >= size) index -= size;
            a ^= t;
            b ^= t;
            a = s_ecc_f[a];
        }
        a = s_ecc_b[s_ecc_f[a] ^ b];
        dest[major] = a;
        dest[major + major_count] = a ^ b;
    }
}

/* P and Q parity of a Mode 2 Form 1 sector: the header counts as zeros. */
static void ecc_mode2(uint8_t* sector)
{
    uint8_t header[4];
    memcpy(header, sector + 12, 4);
    memset(sector + 12, 0, 4);
    ecc_block(sector + 12, 86, 24, 2, 86, sector + 2076);
    ecc_block(sector + 12, 52, 43, 86, 88, sector + 2248);
    memcpy(sector + 12, header, 4);
}

static uint8_t bcd(uint32_t n) { return (uint8_t)((n / 10) << 4 | n % 10); }

/* --- Sectors back from their bodies -------------------------------------- */

static size_t body_size(uint8_t kind, size_t raw_length)
{
    switch (kind) {
    case RAW: return raw_length;
    case ZERO: return 0;
    case FORM1: return 4 + 2048;
    case FORM2: case FORM2_NOEDC: return 4 + 2324;
    case XA: case XA_NOEDC: return 4 + XA_GROUPS * 120;
    case AUDIO: return SECTOR;
    default: return (size_t)-1;
    }
}

static void rebuild(uint8_t kind, const uint8_t* body, size_t raw_length, uint32_t frame,
                    uint8_t* sector)
{
    if (kind == RAW) {
        memcpy(sector, body, raw_length);
        return;
    }
    if (kind == ZERO) {
        memset(sector, 0, SECTOR);
        return;
    }
    if (kind == AUDIO) {
        /* Each channel's 16-bit differences, low bytes then high bytes. */
        uint16_t left = 0, right = 0;
        for (size_t i = 0; i < SECTOR / 2; i += 2) {
            left = (uint16_t)(left + (body[i] | body[SECTOR / 2 + i] << 8));
            right = (uint16_t)(right + (body[i + 1] | body[SECTOR / 2 + i + 1] << 8));
            sector[2 * i] = (uint8_t)left;
            sector[2 * i + 1] = (uint8_t)(left >> 8);
            sector[2 * i + 2] = (uint8_t)right;
            sector[2 * i + 3] = (uint8_t)(right >> 8);
        }
        return;
    }
    sector[0] = 0;
    memset(sector + 1, 0xFF, 10);
    sector[11] = 0;
    sector[12] = bcd(frame / 4500);
    sector[13] = bcd(frame / 75 % 60);
    sector[14] = bcd(frame % 75);
    sector[15] = 2;
    memcpy(sector + 16, body, 4);
    memcpy(sector + 20, body, 4);
    if (kind == FORM1) {
        memcpy(sector + 24, body + 4, 2048);
        put32(sector + 2072, edc(sector + 16, 2056));
        ecc_mode2(sector);
        return;
    }
    if (kind == FORM2 || kind == FORM2_NOEDC) {
        memcpy(sector + 24, body + 4, 2324);
    } else {
        uint8_t* data = sector + 24;
        const uint8_t* in = body + 4;
        for (int g = 0; g < XA_GROUPS; ++g, data += 128, in += 120) {
            memcpy(data, in, 4);
            memcpy(data + 4, in, 4);
            memcpy(data + 8, in + 4, 4);
            memcpy(data + 12, in + 4, 4);
            memcpy(data + 16, in + 8, 112);
        }
        memset(data, 0, 20);
    }
    put32(sector + 2348, (kind == FORM2 || kind == XA) ? edc(sector + 16, 2332) : 0);
}

/* --- The packed file ------------------------------------------------------ */

uint64_t disc_pack_probe(const void* header, size_t size)
{
    const uint8_t* p = (const uint8_t*)header;
    if (size < 16 || memcmp(p, DISC_PACK_MAGIC, 8) != 0) return 0;
    return get64(p + 8);
}

static int read_at(int fd, void* buffer, size_t size, uint64_t at)
{
    uint8_t* out = (uint8_t*)buffer;
    while (size > 0) {
        ssize_t got = pread(fd, out, size, (off_t)at);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) {
            if (got == 0) errno = EIO;
            return -1;
        }
        out += got;
        at += (uint64_t)got;
        size -= (size_t)got;
    }
    return 0;
}

DiscPack* disc_pack_open(int fd, uint64_t offset, uint64_t length)
{
    pthread_once(&s_tables_once, make_tables);
    uint8_t header[DISC_PACK_HEADER_SIZE];
    if (length < sizeof(header) || read_at(fd, header, sizeof(header), offset) != 0) {
        errno = EIO;
        return NULL;
    }
    const uint64_t size = disc_pack_probe(header, sizeof(header));
    const uint32_t sector = get32(header + 16), per_block = get32(header + 20);
    const uint32_t blocks = get32(header + 24);
    const uint64_t index_at = get64(header + 32);
    /* A size near 2^64 would wrap the sector count below (no track is
     * bigger than 2^48 bytes); blocks + 1 is counted in 64 bits, or 2^32 - 1
     * blocks would wrap to an index of 0 bytes and pass the check. */
    const uint64_t sectors = size < ((uint64_t)1 << 48) ? (size + SECTOR - 1) / SECTOR : 0;
    if (!size || !sectors || sector != SECTOR || per_block == 0 ||
        per_block > MAX_SECTORS_PER_BLOCK ||
        blocks != (sectors + per_block - 1) / per_block ||
        index_at < sizeof(header) || index_at > length ||
        ((uint64_t)blocks + 1) * 8 > length - index_at) {
        errno = EINVAL;
        return NULL;
    }
    DiscPack* pack = (DiscPack*)calloc(1, sizeof(*pack));
    if (!pack) return NULL;
    pack->fd = fd;
    pack->offset = offset;
    pack->size = size;
    pack->per_block = per_block;
    pack->blocks = blocks;
    pack->base = get32(header + 28);
    pack->cached = -1;
    pack->index = (uint64_t*)malloc(((size_t)blocks + 1) * sizeof(uint64_t));
    uint8_t* raw_index = (uint8_t*)malloc(((size_t)blocks + 1) * 8);
    pack->payload = (uint8_t*)malloc((size_t)per_block * (SECTOR + 1));
    pack->block = (uint8_t*)malloc((size_t)per_block * SECTOR);
    int ok = pack->index && raw_index && pack->payload && pack->block &&
             read_at(fd, raw_index, ((size_t)blocks + 1) * 8, offset + index_at) == 0;
    for (uint32_t i = 0; ok && i <= blocks; ++i) {
        pack->index[i] = get64(raw_index + 8 * (size_t)i);
        /* Each block holds at least its method byte, inside the file. */
        ok = pack->index[i] <= length &&
             (i == 0 ? pack->index[0] >= index_at + ((uint64_t)blocks + 1) * 8
                     : pack->index[i] > pack->index[i - 1]);
    }
    free(raw_index);
    if (ok) ok = inflateInit2(&pack->z, -15) == Z_OK;
    if (!ok) {
        disc_pack_close(pack);
        errno = EINVAL;
        return NULL;
    }
    pack->z_ready = 1;
    return pack;
}

uint64_t disc_pack_size(const DiscPack* pack)
{
    return pack->size;
}

static int decode_block(DiscPack* pack, uint32_t i)
{
    const uint64_t stored = pack->index[i + 1] - pack->index[i];
    const uint64_t first = (uint64_t)i * pack->per_block;
    const uint64_t sectors = (pack->size + SECTOR - 1) / SECTOR;
    const uint32_t count = (uint32_t)(sectors - first < pack->per_block ? sectors - first
                                                                         : pack->per_block);
    const size_t payload_max = (size_t)pack->per_block * (SECTOR + 1);
    if (stored > payload_max + 1 + 1024) goto bad;   /* stored payload or worse */
    if (pack->packed_size < stored) {
        uint8_t* grown = (uint8_t*)realloc(pack->packed, (size_t)stored);
        if (!grown) return -1;
        pack->packed = grown;
        pack->packed_size = (size_t)stored;
    }
    pack->cached = -1;
    if (read_at(pack->fd, pack->packed, (size_t)stored, pack->offset + pack->index[i]) != 0)
        return -1;

    size_t payload_size;
    if (pack->packed[0] == 0) {
        payload_size = (size_t)stored - 1;
        if (payload_size > payload_max) goto bad;
        memcpy(pack->payload, pack->packed + 1, payload_size);
    } else if (pack->packed[0] == 1) {
        inflateReset(&pack->z);
        pack->z.next_in = pack->packed + 1;
        pack->z.avail_in = (uInt)(stored - 1);
        pack->z.next_out = pack->payload;
        pack->z.avail_out = (uInt)payload_max;
        if (inflate(&pack->z, Z_FINISH) != Z_STREAM_END || pack->z.avail_in != 0) goto bad;
        payload_size = payload_max - pack->z.avail_out;
    } else {
        goto bad;
    }

    size_t at = count;
    if (payload_size < at) goto bad;
    for (uint32_t s = 0; s < count; ++s) {
        const uint8_t kind = pack->payload[s];
        const uint64_t sector_at = (first + s) * SECTOR;
        const size_t raw_length = (size_t)(pack->size - sector_at < SECTOR ? pack->size - sector_at
                                                                           : SECTOR);
        if (kind >= KINDS || (kind != RAW && raw_length != SECTOR)) goto bad;
        const size_t length = body_size(kind, raw_length);
        if (length > payload_size - at) goto bad;
        rebuild(kind, pack->payload + at, raw_length, pack->base + (uint32_t)(first + s),
                pack->block + (size_t)s * SECTOR);
        at += length;
    }
    if (at != payload_size) goto bad;
    pack->cached = i;
    return 0;
bad:
    errno = EINVAL;
    return -1;
}

int64_t disc_pack_read(DiscPack* pack, uint64_t position, void* buffer, size_t size)
{
    uint8_t* out = (uint8_t*)buffer;
    const uint64_t span = (uint64_t)pack->per_block * SECTOR;
    size_t done = 0;
    while (done < size && position < pack->size) {
        const uint64_t i = position / span;
        if (pack->cached != (int64_t)i && decode_block(pack, (uint32_t)i) != 0) return -1;
        const uint64_t start = position - i * span;
        uint64_t end = (i + 1) * span;
        if (end > pack->size) end = pack->size;
        size_t part = (size_t)(end - position);
        if (part > size - done) part = size - done;
        memcpy(out + done, pack->block + start, part);
        done += part;
        position += part;
    }
    return (int64_t)done;
}

void disc_pack_close(DiscPack* pack)
{
    if (!pack) return;
    if (pack->z_ready) inflateEnd(&pack->z);
    free(pack->index);
    free(pack->packed);
    free(pack->payload);
    free(pack->block);
    free(pack);
}
