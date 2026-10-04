/* disc_sector_log.h — optional map of the disc sectors the game reads.
 *
 * Off unless PSX_DISC_SECTOR_LOG names a file (on Android, android_main.c
 * sets it when the APK was built with --disc-sector-log). Two bitmaps, one
 * bit per absolute LBA: the sectors the drive read (iso_reader_c.cpp) and
 * those the game actually got (data delivered, XA or CD audio played,
 * cdrom.c). The file is merged with what it already holds, so several play
 * sessions add up. tools/disc_usage.py turns it into a report per disc file.
 *
 * File: "PSXSECT1", u32 sector count (LE), u32 0, then the read bitmap and
 * the used bitmap, count/8 bytes each, bit (lba & 7) of byte lba >> 3.
 */
#ifndef DISC_SECTOR_LOG_H
#define DISC_SECTOR_LOG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void disc_sector_log_read(uint32_t lba);
void disc_sector_log_used(uint32_t lba);
/* Writes the map now (also done every few hundred new sectors and at exit). */
void disc_sector_log_flush(void);

#ifdef __cplusplus
}
#endif

#endif
