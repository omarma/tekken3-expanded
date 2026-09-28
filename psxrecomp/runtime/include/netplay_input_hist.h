#ifndef PSX_NETPLAY_INPUT_HIST_H
#define PSX_NETPLAY_INPUT_HIST_H

/*
 * Per-slot tick → RNetRbFrame history for MotK rollback invent/contract.
 *
 * Local authority rows: is_predicted = 0.
 * Invent (hold-last) remotes: is_predicted = 1.
 * Late wire promote: replace the row in place (clears predicted).
 *
 * Only available when PSX_HAS_RECOMP_NET is defined (linked recomp-net).
 */

#if defined(PSX_HAS_RECOMP_NET)

#include <stdint.h>

#include "recomp_net/rollback.h"
#include "psx_netplay.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NETPLAY_INPUT_HIST_DEPTH 128u
#define NETPLAY_INPUT_HIST_MAX_SLOTS 8

typedef struct NetplayInputHist {
    RNetRbFrame rows[NETPLAY_INPUT_HIST_MAX_SLOTS][NETPLAY_INPUT_HIST_DEPTH];
    int         slot_count;
    uint32_t    invent_count;
    uint32_t    promote_count;
    uint32_t    rewind_count;
} NetplayInputHist;

void netplay_ih_reset(NetplayInputHist *h, int slot_count);

/* PsxNetPad ↔ RNetRbFrame (LX/LY only; RX/RY stay on the pad blob path). */
void netplay_ih_pad_to_frame(const PsxNetPad *pad, uint32_t tick, uint8_t predicted,
                             RNetRbFrame *out);
void netplay_ih_frame_to_pad(const RNetRbFrame *frame, PsxNetPad *pad);
void netplay_ih_frame_to_contract(const RNetRbFrame *frame, RNetInputContractFrame *out);

int  netplay_ih_put(NetplayInputHist *h, int slot, const RNetRbFrame *frame);
int  netplay_ih_get(const NetplayInputHist *h, int slot, uint32_t tick, RNetRbFrame *out);

/* Hold-last invent for missing remote at tick. Uses prior valid row for slot,
 * else neutral (buttons 0xFFFF, sticks 0). Marks is_predicted=1 and stores. */
int  netplay_ih_invent_hold_last(NetplayInputHist *h, int slot, uint32_t tick,
                                 RNetRbFrame *out);

/* Neutral invent (buttons 0xFFFF). Seal gap-fill only — live MotK admit uses
 * hold-last so a held D-pad does not re-episode every tick. */
int  netplay_ih_invent_idle(NetplayInputHist *h, int slot, uint32_t tick,
                            RNetRbFrame *out);

/* Replace a published predicted/auth row with authoritative wire (promote). */
int  netplay_ih_promote(NetplayInputHist *h, int slot, const RNetRbFrame *wire);

#ifdef __cplusplus
}
#endif

#endif /* PSX_HAS_RECOMP_NET */

#endif /* PSX_NETPLAY_INPUT_HIST_H */
