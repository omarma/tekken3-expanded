#ifndef PSX_NETPLAY_HASH_CONFIRM_H
#define PSX_NETPLAY_HASH_CONFIRM_H

/*
 * Local digest ring + peer FRAME_COMMIT matching → resolved_through watermark.
 *
 * hash_confirm_through(T) is 1 iff every tick in (prev_resolved, T] has a
 * local digest that matched a peer FRAME_COMMIT (contiguous from the prior
 * watermark). Used as RNetInputContractHostGates.hash_confirm_promote /
 * RNetRollbackVTable.hash_confirm_through.
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NETPLAY_HC_RING 128u

typedef struct NetplayHashConfirm {
    uint32_t local_tick[NETPLAY_HC_RING];
    uint32_t local_digest[NETPLAY_HC_RING];
    uint8_t  local_valid[NETPLAY_HC_RING];
    uint32_t peer_tick[NETPLAY_HC_RING];
    uint32_t peer_digest[NETPLAY_HC_RING];
    uint8_t  peer_valid[NETPLAY_HC_RING];
    uint32_t resolved_through; /* inclusive; 0 = none yet (tick 0 may match) */
    uint8_t  resolved_valid;   /* 0 until first match advances watermark */
} NetplayHashConfirm;

void netplay_hc_reset(NetplayHashConfirm* hc);

/* Clear the ring and set resolved_through = last_ok so the next compared tick
 * is last_ok+1. Used at Replay entry to drop live invent FRAME_COMMITs that
 * would false-trigger mid-resim diverge aborts. */
void netplay_hc_prime_after(NetplayHashConfirm* hc, uint32_t last_ok);

/* Record our digest after sim tick T completes. */
void netplay_hc_note_local(NetplayHashConfirm* hc, uint32_t tick, uint32_t digest);

/* Record peer RB_FRAME_COMMIT (through_tick, state_hash). Advances watermark
 * when it matches our local digest for that tick. */
void netplay_hc_note_peer(NetplayHashConfirm* hc, uint32_t tick, uint32_t digest);

uint32_t netplay_hc_resolved_through(const NetplayHashConfirm* hc);
uint8_t  netplay_hc_confirm_through(const NetplayHashConfirm* hc, uint32_t tick);

/* Peek local digest for tick; returns 0 if missing. */
uint8_t netplay_hc_local_digest(const NetplayHashConfirm* hc, uint32_t tick,
                                uint32_t* digest_out);

/* Peek peer FRAME_COMMIT digest for tick; returns 0 if missing. */
uint8_t netplay_hc_peer_digest(const NetplayHashConfirm* hc, uint32_t tick,
                               uint32_t* digest_out);

/* 1 if the next tick after resolved_through has both digests but they differ.
 * Fills tick/local/peer when non-NULL. Used to log first live core fork. */
uint8_t netplay_hc_peek_mismatch(const NetplayHashConfirm* hc, uint32_t* tick_out,
                                 uint32_t* local_out, uint32_t* peer_out);

/* Heal a stuck watermark when the next tick after resolved_through has aged
 * out of the ring (slot reused) and is no longer a live mismatch. Scans the
 * ring for the highest tick where local==peer with no newer mismatch present,
 * then advances resolved_through there (ring contents kept).
 * Returns 1 if the watermark moved. Call from FRAME_COMMIT ingress. */
uint8_t netplay_hc_heal_stale_gap(NetplayHashConfirm* hc);

#ifdef __cplusplus
}
#endif

#endif /* PSX_NETPLAY_HASH_CONFIRM_H */
