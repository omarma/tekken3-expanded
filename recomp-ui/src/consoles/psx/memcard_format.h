// memcard_format.h — standalone PS1 memory-card blank-image formatter.
//
// recomp-ui is a console-agnostic, self-contained launcher: it does not
// depend on any host recomp project's runtime headers (psxrecomp's
// runtime/include/memcard.h in particular). The PSX memory-card save panel
// still needs to be able to write a real, mountable blank 128KB card image
// when the user picks "New", so this is recomp-ui's own tiny formatter —
// same on-disk layout a real PS1 BIOS expects (verified against
// DuckStation's MemoryCardImage::Format(), same reference psxrecomp's own
// memcard.c formatter uses), reimplemented here from scratch so this repo
// never has to reach across into another project's tree to build.

#ifndef RECOMPUI_MEMCARD_FORMAT_H
#define RECOMPUI_MEMCARD_FORMAT_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// 128KB per card: 1024 sectors of 128 bytes each — the standard PS1 memory
// card size (15 usable save blocks after the header/directory/broken-sector
// bookkeeping frames).
#define RECOMPUI_MEMCARD_SIZE (128 * 1024)

// Write a freshly formatted (blank) 128KB memory-card image to `path`,
// creating the file or overwriting whatever is there. Layout: frame 0 is the
// "MC"-magic header, frames 1..15 are the (all-free) directory, frames
// 16..35 are the (all-clear) broken-sector list, frames 36..62 are reserved/
// zeroed, and frame 63 is a write-test copy of frame 0 — every frame's last
// byte carries the standard XOR checksum over its first 127 bytes.
// Returns 0 on success, -1 on a NULL/empty path or I/O failure.
int recompui_memcard_format_file(const char* path);

#ifdef __cplusplus
}
#endif

#endif // RECOMPUI_MEMCARD_FORMAT_H
