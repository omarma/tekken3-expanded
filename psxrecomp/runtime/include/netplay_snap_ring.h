#ifndef PSX_NETPLAY_SNAP_RING_H
#define PSX_NETPLAY_SNAP_RING_H

/*
 * Tick-addressable in-memory .pst ring for rollback netplay.
 *
 * Depth defaults to 64 (enough for early soaks; raise toward
 * RNET_RB_SEAL_MAX_SPAN=128 when episodes deepen). Each slot owns a
 * boot_state_save_buffer_raw blob (uncompressed — FPS). save/load call the
 * full-machine serializer; store/peek are for tests / pre-serialized blobs.
 */

#include <stddef.h>
#include <stdint.h>
#include "cpu_state.h"

#ifdef __cplusplus
extern "C" {
#endif

/* §58: 64 → 80 — dense tip snaps (PSX_NET_SNAP_DENSE window) occupy up to
 * ~24 extra slots alongside the interval snaps; keep the interval history
 * span (~1024 ticks at iv=16) from shrinking under dense pressure. */
#define NETPLAY_SNAP_RING_DEFAULT_DEPTH 80u

typedef struct NetplaySnapRing NetplaySnapRing;

NetplaySnapRing* netplay_snap_ring_create(uint32_t depth);
void             netplay_snap_ring_destroy(NetplaySnapRing* r);
void             netplay_snap_ring_clear(NetplaySnapRing* r);

uint32_t netplay_snap_ring_depth(const NetplaySnapRing* r);
uint32_t netplay_snap_ring_count(const NetplaySnapRing* r);
int      netplay_snap_ring_has(const NetplaySnapRing* r, uint32_t tick);

/* Serialize live machine into the ring at tick (overwrites same tick). */
int netplay_snap_ring_save(NetplaySnapRing* r, uint32_t tick,
                           const CPUState* cpu, uint32_t bios_checksum,
                           uint32_t entry_pc);

/* Restore machine from the snap at tick. Returns 0 if missing/reject. */
int netplay_snap_ring_load(NetplaySnapRing* r, uint32_t tick, CPUState* cpu,
                           uint32_t bios_checksum, uint32_t entry_pc);

/* Take ownership of data on success (caller must not free). For tests /
 * pre-serialized blobs. Overwrites an existing entry for the same tick. */
int netplay_snap_ring_store(NetplaySnapRing* r, uint32_t tick,
                            uint8_t* data, size_t size);

/* Non-owning peek; NULL if missing. */
const uint8_t* netplay_snap_ring_peek(const NetplaySnapRing* r, uint32_t tick,
                                      size_t* size_out);

/* Oldest/newest occupied tick, or 0 if empty (ambiguous with tick 0 — use
 * count() first). */
/* Invalidate every snapshot with tick > tick (dead-timeline snaps after an
 * abort realign). Returns the number of slots dropped. */
uint32_t netplay_snap_ring_drop_after(NetplaySnapRing* r, uint32_t tick);
/* Drop the single snap at tick (dense-window eviction). 1 if dropped. */
int netplay_snap_ring_drop_tick(NetplaySnapRing* r, uint32_t tick);
uint32_t netplay_snap_ring_oldest_tick(const NetplaySnapRing* r);
uint32_t netplay_snap_ring_newest_tick(const NetplaySnapRing* r);

#ifdef __cplusplus
}
#endif

#endif /* PSX_NETPLAY_SNAP_RING_H */
