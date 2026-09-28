/* data_shards.h — memoized pure-function replay ("post-decompression shards").
 *
 * Design: docs/DATA_SHARDS.md. Functions listed in game.toml [data_shards]
 * funcs get a gen-time entry hook (psx_datashard_enter) and return hooks
 * (psx_datashard_ret). First encounter of a (function, inputs) pair runs
 * NATIVELY under a read/write recorder fed from the memory chokepoints;
 * the finalized shard stores the read-set (input proof), write-set (effect),
 * caller-visible register results, and the guest cycle cost. Subsequent
 * encounters byte-verify the read-set against live RAM (kernel-bless style)
 * and, on match, apply the write-set, restore registers, and credit the
 * recorded cycles through the normal advance/IRQ machinery — guest timing
 * preserved, host executes ~a memcmp+memcpy instead of the function.
 *
 * Purity is proven per-capture: any MMIO access, DMA write into RAM, or
 * abnormal exit during the recording window poisons the capture. FMV/MDEC
 * streaming is out of scope by design (user directive 2026-07-10).
 */
#ifndef PSXRECOMP_DATA_SHARDS_H
#define PSXRECOMP_DATA_SHARDS_H

#include <stdint.h>
#include "cpu_state.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Gen-time hooks (emitted by code_generator for [data_shards] funcs). */
int  psx_datashard_enter(CPUState* cpu, uint32_t key);  /* 1 = replayed, return now */
void psx_datashard_ret(CPUState* cpu);                  /* at the function's jr $ra */

/* Memory-chokepoint feeds (memory.c). Called only while g_ds_recording != 0,
 * outside exception context. addr is the VIRTUAL address. */
extern volatile int g_ds_recording;
void ds_note_read(uint32_t addr, uint32_t size);
void ds_note_write(uint32_t addr, uint32_t size);
void ds_note_mmio(uint32_t addr, int is_read);   /* purity poison */
void ds_note_dma_write(void);                    /* DMA wrote RAM mid-window: poison */

/* Runtime init (cache dir for persistence; NULL disables persistence). */
void ds_init(const char* cache_dir, const char* game_id);

/* Debug/TCP surface. */
void ds_stats_json(char* buf, int cap);
void ds_set_enabled(int on);

#ifdef __cplusplus
}
#endif
#endif /* PSXRECOMP_DATA_SHARDS_H */
