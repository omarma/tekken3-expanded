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
 * need a larger primitive arena use this otherwise-unmapped 1 MiB aperture so
 * their CPU pointers survive the tag truncation. Nothing is mapped until an
 * enhancement explicitly allocates from it.
 */
#define PSX_MOD_GPU_DMA_APERTURE_BASE 0x00F00000u
#define PSX_MOD_GPU_DMA_APERTURE_SIZE (1u * 1024u * 1024u)
#define PSX_MOD_GPU_DMA_GUEST_BASE    0x80F00000u

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

#ifdef __cplusplus
}
#endif

#endif
