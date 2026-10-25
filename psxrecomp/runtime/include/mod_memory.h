#ifndef PSXRECOMP_MOD_MEMORY_H
#define PSXRECOMP_MOD_MEMORY_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Host-backed guest memory handed out by psx_mod_alloc_guest_memory(), in
 * Expansion 1 (physical 0x1F000000, which has room for 8 MiB). Game-specific
 * mods keep whole imported characters there: Tekken 3's TTT1 guests need up to
 * about 0.4 MiB each for their combat data and model, plus the selector
 * tables, so two different guests in one fight do not fit in 1 MiB.
 */
#define PSX_MOD_GUEST_MEMORY_BASE  0x9F000000u
#define PSX_MOD_GUEST_MEMORY_SIZE  (4u * 1024u * 1024u)

/*
 * GPU linked-list tags carry only 24 address bits. Trusted enhancements that
 * need a larger primitive arena use this otherwise-unmapped 2 MiB aperture
 * (the top of the 24-bit space) so their CPU pointers survive the tag
 * truncation. Nothing is mapped until an enhancement explicitly allocates
 * from it. 1 MiB was not enough for Tekken 3 Expanded: TTT1 guests (512 KiB),
 * Arcade Stages (384 KiB), the cinematic engine's floor and sprites.
 */
#define PSX_MOD_GPU_DMA_APERTURE_BASE 0x00E00000u
#define PSX_MOD_GPU_DMA_APERTURE_SIZE (2u * 1024u * 1024u)
#define PSX_MOD_GPU_DMA_GUEST_BASE    0x80E00000u

static inline int psx_mod_gpu_dma_aperture_offset_for(
    uint32_t address, uint32_t width, uint32_t used, uint32_t *offset) {
    uint32_t canonical = address & 0x00FFFFFFu;
    uint32_t off;
    if (canonical < PSX_MOD_GPU_DMA_APERTURE_BASE) return 0;
    off = canonical - PSX_MOD_GPU_DMA_APERTURE_BASE;
    if (off > used || width > used - off) return 0;
    if (offset) *offset = off;
    return 1;
}

/*
 * Preserve the retail DMAC's 2 MiB folding unless the address is inside the
 * portion of the enhancement aperture that has actually been allocated.
 */
static inline uint32_t psx_mod_gpu_dma_resolve_address_for(
    uint32_t address, uint32_t used) {
    uint32_t canonical = address & 0x00FFFFFCu;
    if (psx_mod_gpu_dma_aperture_offset_for(
            canonical, 4u, used, (uint32_t *)0))
        return canonical;
    return canonical & 0x001FFFFCu;
}

uint32_t psx_mod_gpu_dma_memory_alloc(uint32_t size, uint32_t alignment);
uint32_t psx_mod_gpu_dma_resolve_address(uint32_t address);

/* Save states (boot_state.c BS_SEC_MOD_MEM / BS_SEC_MOD_GPU_DMA): the
 * allocated part of a region (0 = guest memory, 1 = GPU-DMA aperture), and
 * its restore. Mods allocate both at startup in a fixed order, so the same
 * build lays them out the same way in every launch; a restore longer than the
 * region is refused. */
const uint8_t *psx_mod_memory_region(int which, uint32_t *used);
int psx_mod_memory_restore(int which, const uint8_t *data, uint32_t len);

#ifdef __cplusplus
}
#endif

#endif
