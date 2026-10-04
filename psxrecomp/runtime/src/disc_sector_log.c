/* disc_sector_log.c — optional map of the disc sectors the game reads.
 * See disc_sector_log.h. Costs one getenv until enabled, then a bit test per
 * sector read; the CD-ROM emulation runs on one thread. */
#include "disc_sector_log.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* 99 minutes of CD, the longest a cue sheet can describe. */
#define LOG_SECTORS 445500u
#define LOG_BYTES   ((LOG_SECTORS + 7u) / 8u)
#define LOG_MAGIC   "PSXSECT1"
/* New sectors between two writes: about 3 s of reading at double speed. */
#define LOG_FLUSH_EVERY 450u

static int s_state;            /* 0: not looked yet, 1: on, -1: off */
static char s_path[1024];
static uint8_t* s_read;
static uint8_t* s_used;
static unsigned s_unsaved;

static void put_u32(uint8_t* p, uint32_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint32_t get_u32(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* What an earlier session saved: kept, so the sessions add up. */
static void merge_saved(void) {
    FILE* f = fopen(s_path, "rb");
    uint8_t header[16];
    if (!f) return;
    if (fread(header, 1, sizeof header, f) == sizeof header &&
        memcmp(header, LOG_MAGIC, 8) == 0 && get_u32(header + 8) == LOG_SECTORS) {
        uint8_t* saved = (uint8_t*)malloc(LOG_BYTES);
        if (saved) {
            uint8_t* maps[2] = { s_read, s_used };
            for (int m = 0; m < 2; ++m) {
                if (fread(saved, 1, LOG_BYTES, f) != LOG_BYTES) break;
                for (uint32_t i = 0; i < LOG_BYTES; ++i) maps[m][i] |= saved[i];
            }
            free(saved);
        }
    }
    fclose(f);
}

static int enabled(void) {
    if (s_state) return s_state > 0;
    s_state = -1;
    const char* path = getenv("PSX_DISC_SECTOR_LOG");
    if (!path || !*path || strlen(path) >= sizeof s_path - 4) return 0;
    s_read = (uint8_t*)calloc(1, LOG_BYTES);
    s_used = (uint8_t*)calloc(1, LOG_BYTES);
    if (!s_read || !s_used) {
        free(s_read); free(s_used); s_read = s_used = NULL;
        return 0;
    }
    snprintf(s_path, sizeof s_path, "%s", path);
    merge_saved();
    s_state = 1;
    atexit(disc_sector_log_flush);
    fprintf(stdout, "psxrecomp: disc sector log: %s\n", s_path);
    return 1;
}

void disc_sector_log_flush(void) {
    if (s_state <= 0 || !s_unsaved) return;
    char temp[sizeof s_path + 4];
    snprintf(temp, sizeof temp, "%s.tmp", s_path);
    FILE* f = fopen(temp, "wb");
    /* On a failure, retry after the next LOG_FLUSH_EVERY new sectors. */
    if (!f) { s_unsaved = 1; return; }
    uint8_t header[16];
    memcpy(header, LOG_MAGIC, 8);
    put_u32(header + 8, LOG_SECTORS);
    put_u32(header + 12, 0);
    int ok = fwrite(header, 1, sizeof header, f) == sizeof header &&
             fwrite(s_read, 1, LOG_BYTES, f) == LOG_BYTES &&
             fwrite(s_used, 1, LOG_BYTES, f) == LOG_BYTES;
    ok = fclose(f) == 0 && ok;
    if (!ok) { remove(temp); s_unsaved = 1; return; }
#ifdef _WIN32
    remove(s_path);   /* rename does not replace on Windows */
#endif
    s_unsaved = rename(temp, s_path) == 0 ? 0 : 1;
}

static void mark(uint8_t* map, uint32_t lba) {
    if (lba >= LOG_SECTORS) return;
    const uint8_t bit = (uint8_t)(1u << (lba & 7u));
    if (map[lba >> 3] & bit) return;
    map[lba >> 3] |= bit;
    if (++s_unsaved >= LOG_FLUSH_EVERY) disc_sector_log_flush();
}

void disc_sector_log_read(uint32_t lba) {
    if (enabled()) mark(s_read, lba);
}

void disc_sector_log_used(uint32_t lba) {
    if (enabled()) mark(s_used, lba);
}
